#!/usr/bin/env python3
"""Adapt first: build one complete XML receipt ZIP after a DATEV client reset.

Python 3.11+ and lxml; offline DATEV Document_v060.xsd plus its type schema.
Usage: python3 kivitendo-datev-complete-package.py PRIVATE_CONFIG_JSON
Config: source (fresh Quellmanifest.json/Buchungen directory), documents_dir,
mapping (reviewed file/sha256/source_guid list), schema, output (NEW directory),
cutoff, fiscal_year_start, expected_documents. Paths are trusted operator inputs, never uploaded
untrusted configurations. No network, upload, queue publication or ledger writes.
Preserves original file bytes and booking CSVs. Ignores obsolete DATEV IDs from
manual uploads; uses source GUIDs and deterministic GUIDs for evidence copies.
Files use processID=2: DATEV archives/finalizes receipts. Additional evidence has
no invoice type and creates no booking proposal. Check the recreated target,
transfer log and genuine Kanzlei import separately. Existing output is rejected.
Private manifests/receipts/configuration must NEVER be committed to Git.
Verified with a reviewed 20-document/61-row snapshot; no general tax validation.
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
import uuid
import zipfile
from zoneinfo import ZoneInfo

from lxml import etree as ET

NS = 'http://xml.datev.de/bedi/tps/document/v06.0'
XSI = 'http://www.w3.org/2001/XMLSchema-instance'


def sha(data):
    """Return a bytes SHA-256 hex string; no side effects."""
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    """Write private local JSON; propagate I/O errors; caller owns new path."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main(config_path):
    """Validate reviewed files/links, then write a new local transfer bundle.

    Reads trusted private config, source manifest, receipts, CSVs and local XSD.
    Raises on mismatches before a transferable ZIP is written. Never rewrites
    source files or publishes an outbox. A failed NEW output may be incomplete;
    inspect it and choose another path for a retry. Returns no value.
    """
    os.umask(0o077)
    cfg = json.loads(Path(config_path).read_text())
    source = Path(cfg['source'])
    manifest = json.loads((source/'Quellmanifest.json').read_text())
    cutoff = dt.date.fromisoformat(cfg['cutoff'])
    if manifest['as_of'] != cutoff.isoformat():
        raise ValueError('Wrong cutoff in source manifest')
    records = json.loads(Path(cfg['mapping']).read_text())
    if len(records) != cfg['expected_documents']:
        raise ValueError('Unexpected document count')
    client = str(manifest['client_number'])
    consultant = str(manifest['consultant_number'])
    if not re.fullmatch(r'\d{4,7}', consultant) or not re.fullmatch(r'\d{1,5}', client):
        raise ValueError('Invalid DATEV target numbers')
    parser = ET.XMLParser(no_network=True, resolve_entities=False)
    schema = ET.XMLSchema(ET.parse(cfg['schema'], parser))
    timestamp = dt.datetime.now(dt.timezone.utc)
    archive = ET.Element('{%s}archive' % NS, nsmap={None:NS, 'xsi':XSI},
                         version='6.0', generatingSystem='kivitendo')
    archive.set('{%s}schemaLocation' % XSI, NS + ' Document_v060.xsd')
    header = ET.SubElement(archive, '{%s}header' % NS)
    ET.SubElement(header, '{%s}date' % NS).text = timestamp.astimezone(
        ZoneInfo('Europe/Berlin')).replace(tzinfo=None).isoformat(timespec='seconds')
    ET.SubElement(header, '{%s}consultantNumber' % NS).text = consultant
    ET.SubElement(header, '{%s}clientNumber' % NS).text = client
    content = ET.SubElement(archive, '{%s}content' % NS)
    payloads, mapping, primary = {}, [], set()
    for record in records:
        relative = Path(record['file'])
        if relative.is_absolute() or '..' in relative.parts or '\\' in record['file']:
            raise ValueError('Unsafe document path')
        path = Path(cfg['documents_dir'])/relative
        data = path.read_bytes()
        digest = sha(data)
        if digest != record['sha256']:
            raise ValueError('Changed receipt: ' + path.name)
        extension = path.suffix.lower()
        if extension == '.pdf' and not data.startswith(b'%PDF-'):
            raise ValueError('Invalid PDF')
        if extension == '.png' and not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Invalid PNG')
        if extension not in ('.pdf', '.png'):
            raise ValueError('Unsupported receipt format')
        source_guid = record.get('source_guid')
        if source_guid:
            guid = str(uuid.UUID(source_guid))
        else:
            guid = str(uuid.uuid5(uuid.NAMESPACE_URL,
                'kivitendo-datev:' + consultant + ':' + client + ':' + digest))
        if guid in payloads:
            raise ValueError('Duplicate receipt GUID')
        invoice = source_guid in manifest['documents']
        category = relative.parent.name
        attrs = dict(guid=guid, processID='2')
        if category == 'Rechnungseingang': attrs['type'] = '1'
        elif category == 'Rechnungsausgang': attrs['type'] = '2'
        elif category != 'Sonstige': raise ValueError('Unknown receipt category')
        if invoice:
            if digest != manifest['documents'][guid]:
                raise ValueError('Stale primary receipt')
            meta = manifest['document_metadata'][guid]
            if attrs.get('type') != meta['type']:
                raise ValueError('Wrong invoice type')
            register = meta['period']
            primary.add(guid)
        else:
            register = 'Nachweise bis ' + cutoff.isoformat()
        node = ET.SubElement(content, '{%s}document' % NS, **attrs)
        # DATEV document descriptions allow 40 characters; full names stay in mapping.
        ET.SubElement(node, '{%s}description' % NS).text = path.name[:40]
        filename = guid + extension
        ET.SubElement(node, '{%s}extension' % NS,
                      {'{%s}type' % XSI:'File', 'name':filename})
        repository = ET.SubElement(node, '{%s}repository' % NS)
        for level, name in enumerate(('Buchführung', 'kivitendo ' + str(cutoff.year), register), 1):
            ET.SubElement(repository, '{%s}level' % NS, id=str(level), name=name)
        payloads[guid] = (filename, data)
        mapping.append(dict(file=record['file'], sha256=digest,
            source_guid=source_guid, transfer_guid=guid, xml_file=filename,
            type=attrs.get('type'), csv_link=invoice,
            status='prepared_not_uploaded', note=record.get('note','')))
    if primary != set(manifest['documents']):
        raise ValueError('Missing source invoice')
    schema.assertValid(archive)
    xml = ET.tostring(archive, encoding='utf-8', xml_declaration=True, pretty_print=True)
    periods = {}
    for period, meta in sorted(manifest['periods'].items()):
        raw = (source/'Buchungen'/period/meta['file']).read_bytes()
        if sha(raw) != manifest['files']['Buchungen/'+period+'/'+meta['file']]:
            raise ValueError('Changed booking CSV')
        if b'\n' in raw.replace(b'\r\n', b''):
            raise ValueError('CSV needs CRLF')
        head, captions, *bookings = list(csv.reader(io.StringIO(raw.decode('cp1252')), delimiter=';', strict=True))
        if head[:5] != ['EXTF','700','21','Buchungsstapel','13'] or len(head)!=31:
            raise ValueError('Wrong EXTF format')
        if head[10:12] != [consultant,client] or head[13]!='4' or head[26]!='04' or head[20]!='0':
            raise ValueError('Wrong client/chart/finalization')
        if head[12] != dt.date.fromisoformat(cfg['fiscal_year_start']).strftime('%Y%m%d'):
            raise ValueError('Wrong fiscal year start')
        if len(captions)!=125 or any(len(row)!=125 for row in bookings):
            raise ValueError('Wrong column count')
        links = 0
        for row in bookings:
            if row[19]:
                match = re.fullmatch(r'BEDI "([0-9a-fA-F-]{36})"', row[19])
                if not match or match[1] not in primary:
                    raise ValueError('Booking link missing from XML')
                links += 1
        if len(bookings)!=meta['rows'] or links!=meta['linked_rows']:
            raise ValueError('Wrong row/link counts')
        periods[period] = dict(rows=len(bookings), linked_rows=links,
            sha256=sha(raw), semantic_sha256=meta['semantic_sha256'],
            absolute_turnover=str(sum((Decimal(row[0].replace(',','.')) for row in bookings),Decimal(0))))
    out = Path(cfg['output'])
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    transfer = out/'Belegtransfer'; transfer.mkdir()
    target = transfer/('DATEV_Belege_20_bis_'+cutoff.isoformat()+'_XML.zip')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('document.xml', xml)
        for filename, data in payloads.values(): z.writestr(filename, data)
    shutil.copytree(source/'Buchungen',out/'Buchungen_NACH_BELEGPRUEFUNG')
    write_json(out/'Belegzuordnung.json', mapping)
    write_json(out/'Quellmanifest.json', manifest)
    write_json(out/'Validierung.json', dict(created_at=timestamp.isoformat(),
        source_snapshot=manifest['snapshot'], as_of=cutoff.isoformat(),
        client_number=client, consultant_number=consultant,
        documents=len(payloads), pdfs=sum(n.endswith('.pdf') for n,b in payloads.values()),
        pngs=sum(n.endswith('.png') for n,b in payloads.values()),
        source_linked_documents=len(primary), xml_schema_valid=True,
        original_document_bytes_preserved=True, original_csv_bytes_preserved=True,
        target_verified=False, uploaded=False, datev_import_confirmed=False,
        periods=periods, transfer_zip_sha256=sha(target.read_bytes())))
    print(json.dumps(dict(path=str(out.resolve()), transfer_zip=str(target.resolve()),
                         documents=len(payloads), periods=periods)))


if __name__ == '__main__':
    main(sys.argv[1])
