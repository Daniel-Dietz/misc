#!/usr/bin/env python3
"""Adapt first: prepare auditable kivitendo DATEV file handovers, without an API.

Requires Python 3.11+, Linux, and the reviewed kivitendo EXTF 700/13 exporter.
See kivitendo-datev-handover.md for configuration, deployment and recovery.
Reads accounting through a read-only Perl extractor; writes private local
snapshots, a status file and (only with queue) an immutable handover outbox.
No uploads, email, booking changes, credential creation or automatic posting.
"""
import argparse
import calendar
import csv
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from zoneinfo import ZoneInfo

NS = 'http://xml.datev.de/bedi/tps/document/v05.0'
OUTPUT_NS = 'http://xml.datev.de/bedi/tps/document/v06.0'
XSI = 'http://www.w3.org/2001/XMLSchema-instance'
GUID = r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'


def digest(data):
    """Return SHA-256 of bytes; pure, no side effects."""
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    """Return stable UTF-8 JSON bytes for a JSON-compatible value."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8') + b'\n'


def write_json(path, value):
    """Atomically replace path with private JSON; propagate filesystem failures."""
    temp = path.with_name(path.name + '.tmp')
    with temp.open('wb') as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def load_config(path):
    """Read and validate local configuration; no writes; raise on invalid input."""
    cfg = json.loads(path.read_text())
    for key in ('database', 'login'):
        if not re.fullmatch(r'[A-Za-z0-9_]+', cfg[key]):
            raise ValueError(f'Invalid {key}')
    for key in ('app_dir', 'output_dir', 'extractor', 'document_xsd'):
        if not Path(cfg[key]).is_absolute():
            raise ValueError(f'{key} must be absolute')
    if not re.fullmatch(r'\d{4,7}', str(cfg['consultant_number'])):
        raise ValueError('Invalid consultant number')
    if not re.fullmatch(r'\d{1,5}', str(cfg['client_number'])):
        raise ValueError('Invalid client number')
    dt.date.fromisoformat(cfg['start_date'])
    cfg['client_id'] = int(cfg['client_id'])
    ZoneInfo(cfg.get('timezone', 'Europe/Berlin'))
    return cfg


def validate_period(folder, period, cfg):
    """Validate one CSV and native PDF/XML ZIP; return semantic data and PDFs.

    Reads local staging files, never writes. Raises on wrong identity, broken
    dates/links, inconsistent archives, invalid PDFs or unsupported format.
    This supplements the exporter; it is not DATEV's own import validation.
    """
    files = list(folder.glob('EXTF_*.csv'))
    if len(files) != 1:
        raise ValueError(f'{period}: expected one booking file')
    raw = files[0].read_bytes()
    if b'\n' in raw.replace(b'\r\n', b''):
        raise ValueError('DATEV CSV must use CRLF')
    text = raw.decode('utf-8-sig') if raw.startswith(b'\xef\xbb\xbf') else raw.decode('cp1252')
    rows = list(csv.reader(io.StringIO(text), delimiter=';', strict=True))
    head, captions, *bookings = rows
    if len(head) != 31 or head[:5] != ['EXTF', '700', '21', 'Buchungsstapel', '13']:
        raise ValueError('Unexpected DATEV header')
    if head[10:12] != [str(cfg['consultant_number']), str(cfg['client_number'])]:
        raise ValueError('Wrong consultant or client')
    if head[13] != '4' or head[26] != '04' or head[20] != '0':
        raise ValueError('Expected SKR04 / four-digit accounts / no finalization')
    if len(captions) != 125 or any(len(row) != 125 for row in bookings):
        raise ValueError('Unexpected booking column count')
    start, end = (dt.datetime.strptime(head[i], '%Y%m%d').date() for i in (14, 15))
    fiscal = dt.datetime.strptime(head[12], '%Y%m%d').date()
    expected_fiscal = dt.date(start.year, 1, 1)
    configured_start = dt.date.fromisoformat(cfg['start_date'])
    if start.year == configured_start.year:
        expected_fiscal = configured_start
    if fiscal != expected_fiscal or start.strftime('%Y-%m') != period or end.strftime('%Y-%m') != period or end < start:
        raise ValueError('Unexpected fiscal year or booking period')
    links = set()
    for row in bookings:
        if not re.fullmatch(r'\d+,\d{2}', row[0]) or row[1] not in ('S', 'H'):
            raise ValueError('Invalid amount / debit-credit indicator')
        day = dt.datetime.strptime(row[9].zfill(4) + str(start.year), '%d%m%Y').date()
        if not fiscal <= start <= day <= end:
            raise ValueError('Booking outside fiscal year or period')
        if row[19]:
            match = re.fullmatch(r'BEDI "(' + GUID + r')"', row[19])
            if not match:
                raise ValueError('Unsupported document link')
            links.add(match[1].lower())
    documents = {}
    archive = folder / 'Belege-XML.zip'
    if archive.exists():
        with zipfile.ZipFile(archive) as zf:
            if zf.testzip():
                raise ValueError('Invalid ZIP checksum')
            root = ET.fromstring(zf.read('document.xml'))
            if root.tag != f'{{{NS}}}archive' or root.get('version') != '5.0':
                raise ValueError('Unexpected XML document format')
            expected_names = {'document.xml'}
            for node in root.findall(f'{{{NS}}}content/{{{NS}}}document'):
                guid = node.get('guid', '').lower()
                if not re.fullmatch(GUID, guid) or guid in documents:
                    raise ValueError('Invalid or duplicate GUID')
                extension = node.find(f'{{{NS}}}extension')
                if extension is None or extension.get(f'{{{XSI}}}type') != 'File':
                    raise ValueError('Expected File extension')
                name = extension.get('name', '')
                if name != guid + '.pdf':
                    raise ValueError('Unsafe or unexpected PDF filename')
                pdf = zf.read(name)
                if not pdf.startswith(b'%PDF-'):
                    raise ValueError('Invalid PDF content')
                expected_names.add(name)
                documents[guid] = pdf
            if set(zf.namelist()) != expected_names or len(zf.namelist()) != len(expected_names):
                raise ValueError('Unexpected archive members')
    if links != set(documents):
        raise ValueError('CSV links and PDF archive do not match')
    head[5] = ''  # generation time must not cause duplicate packages
    semantic = digest(encoded([head, captions, sorted(bookings)]))
    return {'file': files[0].name, 'semantic_sha256': semantic, 'rows': len(bookings),
            'linked_rows': sum(bool(row[19]) for row in bookings),
            'documents': sorted(links), 'from': start.isoformat(), 'to': end.isoformat()}, documents


def document_zip(path, documents, timestamp, cfg, metadata):
    """Write XSD-validated v6 PDF/XML ZIP for archival-only receipt linking.

    Args: path output; documents GUID->PDF; timestamp ISO; cfg local XSD and
    client identity; metadata GUID->{type,period}. Calls Perl XML::LibXML for
    validation before writing. No network. Raises on invalid XML or ZIP limits.
    """
    if not 1 <= len(documents) <= 4999:
        raise ValueError('Document count exceeds one DATEV package')
    ET.register_namespace('', OUTPUT_NS)
    ET.register_namespace('xsi', XSI)
    root = ET.Element(f'{{{OUTPUT_NS}}}archive', {
        'version': '6.0', 'generatingSystem': 'kivitendo',
        f'{{{XSI}}}schemaLocation': OUTPUT_NS + ' Document_v060.xsd'})
    header = ET.SubElement(root, f'{{{OUTPUT_NS}}}header')
    local_time = dt.datetime.fromisoformat(timestamp).astimezone(ZoneInfo(cfg.get('timezone','Europe/Berlin')))
    ET.SubElement(header, f'{{{OUTPUT_NS}}}date').text = local_time.replace(tzinfo=None).isoformat(timespec='seconds')
    ET.SubElement(header, f'{{{OUTPUT_NS}}}consultantNumber').text = str(cfg['consultant_number'])
    ET.SubElement(header, f'{{{OUTPUT_NS}}}clientNumber').text = str(cfg['client_number'])
    content = ET.SubElement(root, f'{{{OUTPUT_NS}}}content')
    for guid in sorted(documents):
        meta = metadata[guid]
        node = ET.SubElement(content, f'{{{OUTPUT_NS}}}document', {'guid': guid, 'processID': '2', 'type': meta['type']})
        ET.SubElement(node, f'{{{OUTPUT_NS}}}extension', {f'{{{XSI}}}type': 'File', 'name': guid + '.pdf'})
        repository = ET.SubElement(node, f'{{{OUTPUT_NS}}}repository')
        for level, name in enumerate(('Buchführung', 'kivitendo ' + meta['period'][:4], meta['period']),1):
            ET.SubElement(repository, f'{{{OUTPUT_NS}}}level', {'id':str(level),'name':name})
    xml = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    check = subprocess.run(['perl','-MXML::LibXML','-e',
        'my $s=XML::LibXML::Schema->new(location=>$ARGV[0]); local $/; my $x=<STDIN>; '
        '$s->validate(XML::LibXML->load_xml(string=>$x,no_network=>1));', cfg['document_xsd']],
        input=xml,capture_output=True,timeout=30)
    if check.returncode:
        raise ValueError('DATEV XML schema validation failed: ' + check.stderr.decode(errors='replace')[:2000])
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('document.xml', xml)
        for guid, pdf in sorted(documents.items()):
            zf.writestr(guid + '.pdf', pdf)


def prepare(cfg, root, asof):
    """Build an immutable snapshot if semantic content changed; update status.

    Calls the local kivitendo console with read-only PostgreSQL defaults.
    Deletes only its own staging directory, never existing published snapshots.
    A failed extraction/validation does not replace the last successful snapshot.
    """
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    actual = dict(cfg, as_of=asof)
    with tempfile.TemporaryDirectory(prefix='.stage-', dir=root) as temp:
        stage = Path(temp)
        env = dict(os.environ, PGOPTIONS='-c default_transaction_read_only=on',
                   HANDOVER_CONFIG_JSON=json.dumps(actual), HANDOVER_STAGE=str(stage))
        command = ['./scripts/console', '-c', str(cfg['client_id']), '-l', cfg['login'],
                   '--history-file', '/dev/null', '--log-file', '/dev/null', '--file', cfg['extractor']]
        proc = subprocess.run(command, cwd=cfg['app_dir'], env=env, capture_output=True, timeout=600)
        if proc.returncode or b'HANDOVER_EXTRACT_COMPLETE' not in proc.stdout:
            (root / 'last-error.log').write_bytes(proc.stdout + proc.stderr)
            raise RuntimeError('Extraction failed; see private last-error.log')
        source = json.loads((stage / 'source.json').read_text())
        periods, documents, document_meta = {}, {}, {}
        for item in source['periods']:
            period = item['period']
            meta, pdfs = validate_period(stage / 'periods' / period, period, cfg)
            if item['rows'] != meta['rows'] or item['linked_rows'] != meta['linked_rows']:
                raise ValueError('Source/export counts disagree')
            meta['unlinked_journal_rows'] = item['unlinked_journal_rows']
            for guid, data in pdfs.items():
                if guid in documents and documents[guid] != data:
                    raise ValueError('Same GUID identifies different PDF content')
                documents[guid] = data
                document_meta.setdefault(guid, {'period':period})
            periods[period] = meta
        extras, extra_bytes = [], {}
        for doc in source['documents']:
            data = Path(doc['path']).read_bytes()
            sha = digest(data)
            if doc['guid'].lower() in documents:
                if documents[doc['guid'].lower()] != data:
                    raise ValueError('Document changed during extraction')
                document_meta[doc['guid'].lower()]['type'] = '2' if doc['source_table']=='ar' else '1'
                document_meta[doc['guid'].lower()]['name'] = doc['name']
                continue
            suffix = Path(doc['name']).suffix.lower()
            if not re.fullmatch(r'\.[a-z0-9]{1,8}', suffix):
                suffix = '.bin'
            name = sha + suffix
            extra_bytes[name] = data
            extras.append({key: value for key, value in doc.items() if key != 'path'} | {'file': name, 'sha256': sha})
        doc_hashes = {guid: digest(data) for guid, data in sorted(documents.items())}
        identity = {'package_format':2,'periods': periods, 'documents': doc_hashes,
                    'document_metadata':document_meta,'extras': extras,
                    'person_accounts': source['person_accounts']}
        snapshot = digest(encoded(identity))[:24]
        target = root / 'snapshots' / snapshot
        if not target.exists():
            package = stage / 'package'
            (package / 'Buchungen').mkdir(parents=True)
            (package / 'Belegtransfer').mkdir()
            (package / 'Ergaenzende_Nachweise').mkdir()
            for period, meta in periods.items():
                original = stage / 'periods' / period
                destination = package / 'Buchungen' / period
                shutil.copytree(original, destination, ignore=shutil.ignore_patterns('Belege-XML.zip'))
            if documents:
                document_zip(package / 'Belegtransfer' / 'Belege-XML.zip', documents, now, cfg, document_meta)
            for name, data in extra_bytes.items():
                (package / 'Ergaenzende_Nachweise' / name).write_bytes(data)
            manifest = dict(identity, schema=1, snapshot=snapshot, created_at=now,
                as_of=asof, database=cfg['database'], consultant_number=str(cfg['consultant_number']),
                client_number=str(cfg['client_number']), status='prepared_not_transferred',
                journal_rows=source['journal_rows'], accounting_fingerprints=source['accounting_fingerprints'])
            manifest['files'] = {str(f.relative_to(package)): digest(f.read_bytes())
                                 for f in sorted(package.rglob('*')) if f.is_file()}
            write_json(package / 'manifest.json', manifest)
            (package / 'README.txt').write_text(
                'DATEV-Dateiuebergabe: lokal vorbereitet, noch nicht uebertragen oder importiert.\n'
                'Dies ist ein vollstaendiger Stand. Aeltere Standsicherungen NICHT zusaetzlich importieren.\n'
                'Belegtransfer/Belege-XML.zip enthaelt PDFs und document.xml; ZIP nicht entpacken.\n'
                'XML v6 / processID 2: Belege werden in DATEV archiviert/festgeschrieben; Buchungen kommen separat per CSV.\n'
                'Buchungen/ enthaelt Monatsdateien fuer DATEV Kanzlei-Rechnungswesen.\n'
                'Der laufende Monat ist vorlaeufig. Unveraenderte Monate nur EINMAL importieren.\n'
                'Erst Belege erfolgreich uebertragen, danach Buchungen im Testbestand pruefen.\n'
                'Personenkonten in manifest.json sind eine Uebersicht, kein DATEV-Stammdatenimport.\n'
                'Ergaenzende_Nachweise sind Anlagen fuer die Kanzlei, kein automatischer Belegtransfer.\n'
                'Verarbeitung und Importbestaetigung muessen zwischen Unternehmen und Kanzlei abgestimmt werden.\n', encoding='utf-8')
            (root / 'snapshots').mkdir(exist_ok=True)
            package.rename(target)
        manifest = json.loads((target / 'manifest.json').read_text())
        conflicts = []
        for queued in (root / 'outbox').glob('*/manifest.json'):
            previous = json.loads(queued.read_text())
            period = previous['period']
            if previous['semantic_sha256'] != periods.get(period, {}).get('semantic_sha256'):
                conflicts.append(period)
        status = {'checked_at': now, 'snapshot': snapshot, 'path': str(target),
                  'status': 'attention_changed_queued_period' if conflicts else 'prepared_not_transferred',
                  'changed_queued_periods': sorted(set(conflicts)), 'as_of': asof,
                  'periods': {p: {'rows': m['rows'], 'linked_rows': m['linked_rows'],
                    'provisional': p == asof[:7]} for p, m in periods.items()},
                  'unique_invoice_pdfs': len(documents), 'additional_files': len(extra_bytes),
                  'transport_configured': False, 'datev_import_confirmed': False}
        write_json(root / 'latest.json', status)
        write_json(root / 'status.json', status)
        print(json.dumps(status, ensure_ascii=False))
        if conflicts:
            raise RuntimeError('Previously queued periods changed; do not import a second full batch')


def queue(cfg, root, period, snapshot, allow_partial):
    """Copy a chosen current snapshot period once into the local outbox.

    Does not transmit anything. Full-month replacement or a second queue of the
    same period is rejected; recovery after an actual import needs reconciliation.
    Hash-checks source files and deduplicates PDF GUIDs against existing packets.
    """
    if not re.fullmatch(r'\d{4}-\d{2}', period) or not re.fullmatch(r'[a-f0-9]{24}', snapshot):
        raise ValueError('Invalid period or snapshot')
    current = json.loads((root / 'latest.json').read_text())
    if current['snapshot'] != snapshot:
        raise ValueError('Stale snapshot; prepare and review the current one')
    source = root / 'snapshots' / snapshot
    manifest = json.loads((source / 'manifest.json').read_text())
    if (manifest['database'] != cfg['database'] or
        manifest['consultant_number'] != str(cfg['consultant_number']) or
        manifest['client_number'] != str(cfg['client_number'])):
        raise ValueError('Snapshot belongs to a different client')
    meta = manifest['periods'][period]
    end = dt.date.fromisoformat(meta['to'])
    if end.day != calendar.monthrange(end.year, end.month)[1] and not allow_partial:
        raise ValueError('Incomplete month: use --allow-partial only for an agreed test')
    destination = root / 'outbox' / period
    if destination.exists():
        raise ValueError('Period already queued; refusing possible duplicate bookings')
    for relative, sha in manifest['files'].items():
        file = source / relative
        if not file.resolve().is_relative_to(source.resolve()) or digest(file.read_bytes()) != sha:
            raise ValueError('Snapshot integrity failure')
    seen = {}
    for queued in (root / 'outbox').glob('*/manifest.json'):
        seen.update(json.loads(queued.read_text())['documents'])
    new = {}
    if meta['documents']:
        with zipfile.ZipFile(source / 'Belegtransfer' / 'Belege-XML.zip') as zf:
            for guid in meta['documents']:
                sha = manifest['documents'][guid]
                if guid in seen and seen[guid] != sha:
                    raise ValueError('Changed PDF under a queued GUID')
                if guid not in seen:
                    new[guid] = zf.read(guid + '.pdf')
    with tempfile.TemporaryDirectory(prefix='.queue-', dir=root) as temp:
        package = Path(temp) / period
        package.mkdir()
        shutil.copyfile(source / 'Buchungen' / period / meta['file'], package / meta['file'])
        if new:
            document_zip(package / 'Belege-XML.zip', new, dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), cfg, manifest['document_metadata'])
        write_json(package / 'manifest.json', dict(meta, period=period, snapshot=snapshot,
            status='queued_locally_not_transferred', documents={guid:digest(pdf) for guid,pdf in new.items()}))
        (root / 'outbox').mkdir(exist_ok=True)
        package.rename(destination)
    print(json.dumps({'status':'queued_locally_not_transferred','path':str(destination)}))


def main():
    """CLI: serialize preparation/queue operations and persist failure status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    commands = parser.add_subparsers(dest='action', required=True)
    prepare_args = commands.add_parser('prepare')
    prepare_args.add_argument('--as-of')
    commands.add_parser('status')
    queue_args = commands.add_parser('queue')
    queue_args.add_argument('--period', required=True)
    queue_args.add_argument('--snapshot', required=True)
    queue_args.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args()
    cfg = load_config(args.config)
    root = Path(cfg['output_dir'])
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if args.action == 'prepare':
                asof = args.as_of or dt.datetime.now(ZoneInfo(cfg.get('timezone','Europe/Berlin'))).date().isoformat()
                if dt.date.fromisoformat(asof) < dt.date.fromisoformat(cfg['start_date']):
                    raise ValueError('Cutoff is before configured start')
                prepare(cfg, root, asof)
            elif args.action == 'queue':
                prepare(cfg, root, dt.datetime.now(ZoneInfo(cfg.get('timezone','Europe/Berlin'))).date().isoformat())
                queue(cfg, root, args.period, args.snapshot, args.allow_partial)
            else:
                print((root / 'status.json').read_text())
        except Exception as error:
            if args.action == 'prepare':
                write_json(root / 'status.json', {'status':'failed','error':str(error),
                    'checked_at':dt.datetime.now(dt.timezone.utc).isoformat()})
            raise


if __name__ == '__main__':
    main()
