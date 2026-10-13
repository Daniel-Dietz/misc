#!/usr/bin/env python3
"""Adapt first: finalize a manual DATEV document handover, Python 3.11+.

Usage: script PREPARED_DIRECTORY OBSERVED_IDS_JSON NEW_OUTPUT_DIRECTORY
The operator must first upload every file and obtain its actual DATEV document
ID through the official UI. Observations are [{file: basename, datev_guid: UUID}].
Reads private local inputs, creates a new private directory, and changes only
existing BEDI document references in EXTF700/13 CSVs. No uploads, ledger writes,
tax validation, or claim of successful Kanzlei import. Never commit private data.
Retain the source snapshot and observations as the audit trail. A failed run may
leave a partial output; use a new output directory after correcting the cause.
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


def digest(data):
    """Return the SHA256 digest of bytes without changing input."""
    return hashlib.sha256(data).hexdigest()


def parse(data):
    """Read DATEV semicolon CSV while retaining all fields as strings."""
    return list(csv.reader(io.StringIO(data.decode('cp1252')), delimiter=';'))


def main(prepared, observed, output):
    """Validate the upload mapping, replace only GUIDs, and write audit files."""
    src, out = Path(prepared), Path(output)
    records = json.loads((src/'Belegzuordnung.json').read_text())
    manifest = json.loads((src/'Quellmanifest.json').read_text())
    observations = json.loads(Path(observed).read_text())
    actual = {row['file']: str(uuid.UUID(row['datev_guid'])) for row in observations}
    if len(actual) != len(observations) or len(set(actual.values())) != len(actual):
        raise ValueError('Duplicate observed filename or DATEV UUID')
    if set(actual) != {Path(row['file']).name for row in records}:
        raise ValueError('Observed upload inventory does not match prepared files')
    substitutions = {}
    for row in records:
        relative = Path(row['file'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe document path')
        if digest((src/relative).read_bytes()) != row['sha256']:
            raise ValueError('Document changed after preparation')
        row['datev_guid'] = actual[relative.name]
        row['upload_status'] = 'uploaded_verified_in_datev_ui'
        if row['source_guid']:
            substitutions[row['source_guid']] = row['datev_guid']
    os.umask(0o077)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    for folder in ['Einzelbelege', 'Kanzlei_Nachweise']:
        shutil.copytree(src/folder, out/folder)
    shutil.copyfile(src/'Quellmanifest.json', out/'Quellmanifest.json')
    audit = {'checked_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
             'snapshot': manifest['snapshot'], 'as_of': manifest['as_of'],
             'documents_uploaded': len(records), 'kanzlei_import': 'pending',
             'only_changed_csv_column': 'Beleglink', 'periods': {}}
    for period, meta in manifest['periods'].items():
        source = src/'Buchungen_NOCH_NICHT_IMPORTIEREN'/period/meta['file']
        before = source.read_bytes()
        if digest(before) != manifest['files']['Buchungen/'+period+'/'+meta['file']]:
            raise ValueError('Source CSV hash mismatch')
        old_rows = parse(before)
        if old_rows[0][:5] != ['EXTF', '700', '21', 'Buchungsstapel', '13']:
            raise ValueError('Unsupported DATEV version')
        if old_rows[0][10:12] != [manifest['consultant_number'],manifest['client_number']]:
            raise ValueError('Wrong DATEV destination')
        if len(old_rows)-2 != meta['rows'] or any(len(r)!=125 for r in old_rows[1:]):
            raise ValueError('Unexpected CSV dimensions')
        links = [r[19] for r in old_rows[2:] if r[19]]
        guids = [re.fullmatch(r'BEDI "([0-9a-f-]{36})"', v).group(1) for v in links]
        if len(guids) != meta['linked_rows'] or not set(guids) <= substitutions.keys():
            raise ValueError('Missing invoice upload mapping')
        after = before
        for guid in set(guids):
            after = after.replace(guid.encode(), substitutions[guid].encode())
        new_rows = parse(after)
        if old_rows[:2] != new_rows[:2] or len(old_rows) != len(new_rows):
            raise ValueError('CSV structure changed')
        for old, new in zip(old_rows[2:], new_rows[2:]):
            if old[:19]+old[20:] != new[:19]+new[20:]:
                raise ValueError('A financial field changed')
            expected = old[19]
            if expected:
                guid = re.fullmatch(r'BEDI "([0-9a-f-]{36})"', expected).group(1)
                expected = f'BEDI "{substitutions[guid]}"'
            if new[19] != expected:
                raise ValueError('Incorrect target document link')
        dest = out/'Buchungen'/period
        dest.mkdir(parents=True)
        (dest/meta['file']).write_bytes(after)
        shutil.copyfile(source.parent/'DATEV_Pruefhinweise.txt', dest/'DATEV_Pruefhinweise.txt')
        audit['periods'][period] = {'rows': meta['rows'], 'linked_rows':len(links),
            'source_sha256':digest(before), 'final_sha256':digest(after),
            'unchanged_financial_fields':True,
            'absolute_turnover_check':str(sum((Decimal(r[0].replace(',','.')) for r in new_rows[2:]),Decimal(0)))}
    (out/'Belegzuordnung.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    (out/'Validierung.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(audit,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main(*sys.argv[1:])
