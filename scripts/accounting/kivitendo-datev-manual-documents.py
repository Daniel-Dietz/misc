#!/usr/bin/env python3
"""Adapt first: prepare individual documents after new Belege online rejects XML.

Python 3.11+, reportlab, Linux DejaVuSans TTF fonts. Run with one private JSON configuration path. Reads a
fresh handover manifest, an older byte-identical document archive, and explicitly
reviewed supplementary files. Writes a NEW private directory; never uploads,
changes bookkeeping, rewrites booking CSVs or claims a DATEV import succeeded.
Required config: current_source (extracted manifest/Buchungen), reference_zip,
output, cutoff (ISO date), extra_guids, extra_names, bank_reports, note_reports.
Bank reports specify path, name, title, header, expected_balance; note reports
specify path/name/title. File names must be plain basenames. Input paths and
archive are trusted local operator inputs, not untrusted uploaded configurations.
No overwrites: choose a new output path after a partial failure. Retain original
snapshots and old transport state. The private mapping contains personal data;
never commit it. Actual upload/DATEV GUID matching and test import remain manual.
Verified on one reviewed EXTF700/13 snapshot; no general tax validation.
"""
import csv
import datetime as dt
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import zipfile
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdfmetrics.registerFont(TTFont("EvidenceSans","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("EvidenceSans-Bold","/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFontFamily("EvidenceSans",normal="EvidenceSans",bold="EvidenceSans-Bold")


def sha(data):
    """Return a bytes SHA256 string without side effects."""
    return hashlib.sha256(data).hexdigest()


def basename(name):
    """Validate a plain output basename; raise instead of allowing traversal."""
    if Path(name).name != name or '\\' in name or name in ('', '.', '..'):
        raise ValueError('Unsafe basename')
    return name


def money(value):
    """Format Decimal as German euros; pure presentation helper."""
    return f'{value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def pdf(path, title, subtitle, body):
    """Write a readable A4 evidence copy with explicit origin and page numbering."""
    styles = getSampleStyleSheet()
    styles['Title'].fontName = 'EvidenceSans-Bold'
    styles['Title'].fontSize = 17
    styles['Normal'].fontName = 'EvidenceSans'
    styles['Normal'].fontSize = 9
    styles['Normal'].leading = 13
    story = [Paragraph(escape(title), styles['Title']),
             Paragraph(escape(subtitle), styles['Normal']), Spacer(1, 7*mm)] + body
    def footer(canvas, doc):
        """Render non-sensitive page information on each generated evidence page."""
        canvas.saveState()
        canvas.setFont('EvidenceSans', 7)
        canvas.setFillColor(colors.HexColor('#586474'))
        canvas.drawString(18*mm, 12*mm, 'Lesefassung aus archivierten Quelldaten - keine Bank-Original-PDF')
        canvas.drawRightString(192*mm, 12*mm, f'Seite {doc.page}')
        canvas.restoreState()
    SimpleDocTemplate(str(path), pagesize=(210*mm,297*mm), leftMargin=18*mm,
                      rightMargin=18*mm, topMargin=18*mm, bottomMargin=22*mm
                      ).build(story, onFirstPage=footer, onLaterPages=footer)


def main(config_path):
    """Prepare a new local handover from reviewed inputs; raise on any mismatch."""
    cfg = json.loads(Path(config_path).read_text())
    cutoff = dt.date.fromisoformat(cfg['cutoff'])
    src = Path(cfg['current_source'])
    manifest = json.loads((src/'manifest.json').read_text())
    assert manifest['as_of'] == cutoff.isoformat()
    out = Path(cfg['output'])
    os.umask(0o077)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    evidence = out/'Kanzlei_Nachweise'; evidence.mkdir()
    upload = out/'Einzelbelege'
    for category in ['Rechnungseingang','Rechnungsausgang','Sonstige']:
        (upload/category).mkdir(parents=True)
    records = []
    def add(data, name, category, guid=None, note=''):
        """Write one private evidence file and append its pending-upload record."""
        name = basename(name)
        p = upload/category/name
        if p.exists(): raise ValueError('Duplicate output name')
        p.write_bytes(data)
        records.append(dict(file=str(p.relative_to(out)), sha256=sha(data),
                            source_guid=guid, datev_guid=None,
                            upload_status='not_uploaded', note=note))
    with zipfile.ZipFile(cfg['reference_zip']) as old:
        old_manifest = json.loads(old.read('manifest.json'))
        with zipfile.ZipFile(io.BytesIO(old.read('Belegtransfer/Belege-XML.zip'))) as docs:
            for guid, expected in manifest['documents'].items():
                data = docs.read(guid+'.pdf')
                if sha(data) != expected: raise ValueError('Stale invoice PDF')
                meta = manifest['document_metadata'][guid]
                category = 'Rechnungsausgang' if meta['type']=='2' else 'Rechnungseingang'
                add(data,meta['period']+'__'+meta['name'],category,guid)
            for guid in cfg.get('extra_guids',[]):
                data=docs.read(guid+'.pdf')
                if sha(data)!=old_manifest['documents'][guid]: raise ValueError('Extra PDF mismatch')
                meta=old_manifest['document_metadata'][guid]
                add(data,meta['name'],'Rechnungseingang',guid,
                    'Belegdatum innerhalb Stichtag; Buchung in spaeterer Periode. Keine zweite Buchung erzeugen.')
        for item in manifest['extras']:
            if item['name'] not in cfg.get('extra_names',[]): continue
            data=old.read('Ergaenzende_Nachweise/'+item['file'])
            if sha(data)!=item['sha256']: raise ValueError('Extra hash mismatch')
            add(data,item['name'],'Sonstige',item['guid'],'Ergaenzender Nachweis; keine neue Buchung.')
    # Keep the original CSVs outside the import-ready folder until all IDs exist.
    pending=out/'Buchungen_NOCH_NICHT_IMPORTIEREN'
    shutil.copytree(src/'Buchungen',pending)
    for period, meta in manifest['periods'].items():
        raw=(pending/period/meta['file']).read_bytes()
        if sha(raw)!=manifest['files']['Buchungen/'+period+'/'+meta['file']]:
            raise ValueError('Current booking hash mismatch')
        rows=list(csv.reader(io.StringIO(raw.decode('cp1252')),delimiter=';'))
        if len(rows)-2!=meta['rows']: raise ValueError('Booking count mismatch')
        if rows[0][:5]!=['EXTF','700','21','Buchungsstapel','13']: raise ValueError('Wrong format')
        if rows[0][10:12]!=[manifest['consultant_number'],manifest['client_number']]:
            raise ValueError('Wrong DATEV client')
        if any(len(r)!=125 for r in rows[1:]): raise ValueError('Wrong column count')
    styles=getSampleStyleSheet()
    styles['Normal'].fontName='EvidenceSans'
    styles['Normal'].fontSize=8; styles['Normal'].leading=11
    for spec in cfg.get('bank_reports',[]):
        source=Path(spec['path']); raw=source.read_bytes()
        rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
        start=next(i for i,r in enumerate(rows) if r and r[0]==spec['header'])+1
        selected=[]
        for row in rows[start:]:
            if not row or not re.fullmatch(r'\d{2}\.\d{2}\.\d{4}',row[0]): continue
            if dt.datetime.strptime(row[0],'%d.%m.%Y').date()<=cutoff:
                if row[4]!='EUR': raise ValueError('Unexpected currency')
                selected.append(row)
        balance=sum((Decimal(r[3]) for r in selected),Decimal('0'))
        if balance!=Decimal(spec['expected_balance']): raise ValueError('Bank total mismatch')
        body=[Paragraph('Anfangssaldo 0,00 EUR. Summe der Bewegungen / Endsaldo: <b>'+money(balance)+' EUR</b>. '+str(len(selected))+' Datensaetze.',styles['Normal']),Spacer(1,5*mm)]
        data=[['Datum','Gegenpartei / Verwendungszweck','Betrag EUR']]
        for row in selected:
            label=escape(row[1]) + ('<br/>'+escape(row[2]) if row[2] else '')
            data.append([row[0],Paragraph(label,styles['Normal']),money(Decimal(row[3]))])
        table=Table(data,colWidths=[24*mm,125*mm,25*mm],repeatRows=1,hAlign='LEFT')
        table.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'EvidenceSans'),('FONTNAME',(0,0),(-1,0),'EvidenceSans-Bold'),('FONTSIZE',(0,0),(-1,-1),8),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e4edf2')),('VALIGN',(0,0),(-1,-1),'TOP'),('ALIGN',(-1,1),(-1,-1),'RIGHT'),('BOTTOMPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),6),('LINEBELOW',(0,0),(-1,-1),0.25,colors.HexColor('#cdd6dc'))]))
        body += [table,Spacer(1,6*mm),Paragraph('Quelle: archivierter Vivid-CSV-Auszug. Auswahl bis '+cutoff.isoformat()+'. Ursprungsdatei SHA256: '+sha(raw),styles['Normal'])]
        p=evidence/basename(spec['name']);pdf(p,spec['title'],'Kontobewegungen bis '+cutoff.isoformat()+' - aus CSV erzeugte Lesefassung',body)
        add(p.read_bytes(),p.name,'Sonstige',note='Lesefassung aus Vivid-CSV; Original-CSV bleibt archiviert.')
        p.unlink() # Keep a single copy in the deliverable, not duplicate evidence.
    for spec in cfg.get('note_reports',[]):
        source=Path(spec['path']);raw=source.read_bytes()
        body=[Paragraph(escape(line) if line else '&#160;',styles['Normal']) for line in raw.decode().splitlines()]
        body += [Spacer(1,5*mm),Paragraph('SHA256 der archivierten Textquelle: '+sha(raw),styles['Normal'])]
        p=evidence/basename(spec['name']);pdf(p,spec['title'],'Lesefassung der archivierten Zahlungsnotiz; kein Original-Rechnungsexport',body)
        add(p.read_bytes(),p.name,'Sonstige',note='Lesefassung einer archivierten PayPal-Zahlungsnotiz.')
        shutil.copyfile(source,evidence/source.name);p.unlink()
    (out/'Belegzuordnung.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    (out/'Quellmanifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (out/'STATUS.txt').write_text('VORBEREITET - NOCH NICHT HOCHGELADEN\n'
        'Buchungen noch nicht importieren: bisherige Beleglinks sind Platzhalter fuer die spaeteren DATEV-Beleg-IDs.\n'
        'Nach bestaetigtem Upload die IDs zuordnen, alle Beleglinks ersetzen und erst dann den Kanzleiimport freigeben.\n'
        'Keine XML-Datei und kein XML-ZIP hochladen. Alte XML-Abholung bleibt deaktiviert.\n'
        'DATEV-Rechnung vom 30.09. nur als Beleg enthalten; zugehoerige Buchung bleibt im Oktober.\n'
        'netcup-Schlussrechnung ueber 0,00 EUR nur als Zusatznachweis; keine erneute Aufwandserfassung.\n',encoding='utf-8')
    print(json.dumps({'path':str(out),'documents':len(records),'pdfs':sum(r['file'].endswith('.pdf') for r in records),
                      'booking_rows':sum(m['rows'] for m in manifest['periods'].values())}))


if __name__=='__main__':
    main(sys.argv[1])
