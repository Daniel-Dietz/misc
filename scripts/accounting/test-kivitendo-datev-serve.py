#!/usr/bin/env python3
"""Adapt first: isolated protocol/access tests for the restricted SSH reader.

Python 3.11+, standard library. Uses synthetic files in a TemporaryDirectory;
no actual account, SSH configuration, financial data or network is accessed.
Run: python3 test-kivitendo-datev-serve.py
"""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('reader', Path(__file__).with_name('kivitendo-datev-serve.py'))
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class ReaderTests(unittest.TestCase):
    """Exercise untrusted commands and modified published files."""

    def setUp(self):
        """Create one synthetic approved packet and fresh preparation status."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'outbox' / '2026-07'
        self.folder.mkdir(parents=True)
        self.cfg = dict(output_dir=str(self.root), database='example_skr04',
                        consultant_number='1001', client_number='1', delivery_enabled=True)
        self.status = dict(status='prepared_not_transferred', changed_queued_periods=[],
                          checked_at=dt.datetime.now(dt.timezone.utc).isoformat())
        self.write_status()
        self.csv = self.folder / 'EXTF_example.csv'
        self.csv.write_bytes(b'synthetic test content\r\n')
        self.manifest = dict(schema=2, period='2026-07', snapshot='a' * 24,
                             semantic_sha256='b' * 64, rows=1, file=self.csv.name,
                             files={self.csv.name: reader.sha(self.csv.read_bytes())},
                             **{k: v for k, v in self.cfg.items() if k != 'output_dir'})
        self.write_manifest()

    def write_status(self):
        """Write test-only status after an intentional fixture change."""
        (self.root / 'status.json').write_text(json.dumps(self.status))

    def write_manifest(self):
        """Write test-only packet metadata; no external effect."""
        (self.folder / 'manifest.json').write_text(json.dumps(self.manifest))

    def test_valid_index_and_get(self):
        """A legitimate index and file response have the same packet hash."""
        index = reader.serve(self.cfg, 'index')
        reply = reader.serve(self.cfg, 'get 2026-07 EXTF_example.csv')
        self.assertEqual(index['packets'][0]['packet_sha256'], reply['packet_sha256'])
        self.assertEqual(reply['sha256'], self.manifest['files'][self.csv.name])

    def test_delivery_requires_explicit_enable(self):
        """A pause blocks index and direct file reads, even with a valid packet."""
        for value in (False, None, 'true', 1):
            cfg = dict(self.cfg, delivery_enabled=value)
            for command in ('index', 'get 2026-07 EXTF_example.csv'):
                with self.subTest(value=value, command=command), self.assertRaisesRegex(ValueError, 'paused'):
                    reader.serve(cfg, command)
        cfg = dict(self.cfg)
        cfg.pop('delivery_enabled')
        with self.assertRaisesRegex(ValueError, 'paused'):
            reader.serve(cfg, 'index')

    def test_commands_and_paths_rejected(self):
        """No shell, SCP/SFTP, path traversal, arguments or extra lines allowed."""
        for command in ('id', 'sh', 'sftp', 'scp -t /tmp/x', 'index; id', 'index\nid',
                        'get 2026-07 ../passwd', 'get 2026-13 EXTF_example.csv',
                        'get 2026-07 unknown.txt'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                reader.serve(self.cfg, command)

    def test_changed_file_rejected(self):
        """Source corruption invalidates even the index before any download."""
        self.csv.write_bytes(b'changed')
        with self.assertRaises(ValueError): reader.serve(self.cfg, 'index')

    def test_other_client_rejected(self):
        """Packet client identity must equal server configuration."""
        self.manifest['client_number'] = '2'
        self.write_manifest()
        with self.assertRaises(ValueError): reader.serve(self.cfg, 'index')

    def test_symlink_rejected(self):
        """Files cannot redirect the reader beyond the published packet."""
        outside = self.root / 'outside.csv'
        self.csv.rename(outside)
        self.csv.symlink_to(outside)
        with self.assertRaises(ValueError): reader.serve(self.cfg, 'index')

    def test_stale_or_failed_source_rejected(self):
        """Errors, changes and stale preparation each block all delivery."""
        for updates in ({'status': 'failed'}, {'changed_queued_periods': ['2026-07']},
                        {'checked_at': (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat()}):
            original = dict(self.status)
            self.status.update(updates)
            self.write_status()
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                reader.serve(self.cfg, 'index')
            self.status = original


if __name__ == '__main__':
    unittest.main()
