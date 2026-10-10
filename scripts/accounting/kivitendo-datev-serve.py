#!/usr/bin/env python3
"""Adapt first: read-only SSH endpoint for the controlled DATEV outbox.

Python 3.11+, Linux/OpenSSH. Install root-owned; invoke ONLY as a dedicated
unprivileged user's forced SSH command with `restrict` authorized_keys options.
Usage: kivitendo-datev-serve.py --config /etc/kivitendo/datev-reader.json
Config: output_dir, database, consultant_number, client_number, delivery_enabled.
No credentials. Delivery is denied unless delivery_enabled is JSON true.
SSH_ORIGINAL_COMMAND accepts only `index` or `get YYYY-MM BASENAME`.
The account has read/traverse ACLs only on status.json and approved outbox data.
Returns JSON with hashes; file bytes are base64 to avoid PowerShell 5.1 binary
redirection corruption. No shell evaluation, writes, arbitrary paths or DB access.
Rejects stale/failed preparation, symlinks, changed packets and oversized files.
Network/ACL failures are fatal. No upload/import receipt is implied.
See kivitendo-datev-handover.md for deployment, testing and limits.
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys

MAX_BYTES = 64 * 1024 * 1024
PERIOD = r'\d{4}-(?:0[1-9]|1[0-2])'
NAME = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,179}'


def read_regular(path):
    """Read one bounded regular non-symlink file; raise before unsafe reads."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('Unsafe, missing or oversized handover file')
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError('File grew beyond maximum size')
    return data


def sha(data):
    """Return the SHA-256 of bytes; no side effects."""
    return hashlib.sha256(data).hexdigest()


def packet(cfg, period):
    """Validate one immutable approved packet and return index metadata/bytes.

    Reads only that packet; verifies original publication hashes and client.
    Raises on traversal, extra files, malformed metadata or changed content.
    """
    if not re.fullmatch(PERIOD, period):
        raise ValueError('Invalid period')
    root = Path(cfg['output_dir']) / 'outbox'
    folder = root / period
    if root.is_symlink() or folder.is_symlink() or not folder.is_dir():
        raise ValueError('Invalid packet directory')
    manifest_bytes = read_regular(folder / 'manifest.json')
    manifest = json.loads(manifest_bytes)
    if manifest.get('schema') != 2 or manifest.get('period') != period:
        raise ValueError('Unexpected packet schema or period')
    for key in ('database', 'consultant_number', 'client_number'):
        if str(manifest.get(key)) != str(cfg[key]):
            raise ValueError('Packet client identity mismatch')
    if not re.fullmatch(r'[a-f0-9]{24}', manifest.get('snapshot', '')):
        raise ValueError('Invalid snapshot')
    names = set(manifest['files'])
    csv_name = manifest['file']
    if not re.fullmatch(r'EXTF_[A-Za-z0-9_.-]+\.csv', csv_name):
        raise ValueError('Invalid CSV name')
    if names not in ({csv_name}, {csv_name, 'Belege-XML.zip'}):
        raise ValueError('Unexpected packet files')
    if {p.name for p in folder.iterdir()} != names | {'manifest.json'}:
        raise ValueError('Unexpected packet directory contents')
    data = {'manifest.json': manifest_bytes}
    for name in sorted(names):
        data[name] = read_regular(folder / name)
        if sha(data[name]) != manifest['files'][name]:
            raise ValueError('Packet integrity failure')
    info = {'period': period, 'snapshot': manifest['snapshot'],
            'semantic_sha256': manifest['semantic_sha256'], 'rows': manifest['rows'],
            'files': [{'name': name, 'size': len(raw), 'sha256': sha(raw)}
                      for name, raw in sorted(data.items())]}
    info['packet_sha256'] = sha(json.dumps(info, sort_keys=True).encode())
    return info, data


def serve(cfg, command):
    """Dispatch a strict read-only request; return JSON-compatible response.

    No shell execution. Requires explicit delivery enablement; also refuses
    every read if preparation failed, detected
    changed queued periods or has not succeeded within the previous 48 hours.
    """
    if command != 'index' and not re.fullmatch('get (' + PERIOD + ') (' + NAME + ')', command):
        raise ValueError('Only index or get PERIOD BASENAME is allowed')
    if cfg.get('delivery_enabled') is not True:
        raise ValueError('Delivery is paused; verify DATEV target compatibility before enabling')
    root = Path(cfg['output_dir'])
    if not root.is_absolute() or root.is_symlink():
        raise ValueError('Invalid configured root')
    status = json.loads(read_regular(root / 'status.json'))
    checked = dt.datetime.fromisoformat(status['checked_at'])
    age = dt.datetime.now(dt.timezone.utc) - checked
    if status['status'] != 'prepared_not_transferred' or status.get('changed_queued_periods'):
        raise ValueError('Source preparation is not ready')
    if not dt.timedelta(minutes=-5) <= age <= dt.timedelta(hours=48):
        raise ValueError('Source preparation is stale')
    identity = {key: str(cfg[key]) for key in ('database', 'consultant_number', 'client_number')}
    if command == 'index':
        outbox = root / 'outbox'
        if outbox.is_symlink():
            raise ValueError('Invalid outbox')
        packets = [packet(cfg, p.name)[0] for p in sorted(outbox.iterdir())
                   if re.fullmatch(PERIOD, p.name)] if outbox.exists() else []
        return dict(identity, schema=1, source_checked_at=status['checked_at'], packets=packets)
    _, period, name = command.split(' ')
    info, data = packet(cfg, period)
    if name not in data:
        raise ValueError('File is not part of the approved packet')
    raw = data[name]
    return dict(identity, schema=1, period=period, name=name, size=len(raw),
                sha256=sha(raw), packet_sha256=info['packet_sha256'],
                content_base64=base64.b64encode(raw).decode('ascii'))


def main():
    """Read root-owned configuration and SSH request; print response or error."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    try:
        cfg = json.loads(args.config.read_text())
        print(json.dumps(serve(cfg, os.environ.get('SSH_ORIGINAL_COMMAND', '')), ensure_ascii=True))
    except Exception as error:
        print('DATEV_READ_DENIED: ' + str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
