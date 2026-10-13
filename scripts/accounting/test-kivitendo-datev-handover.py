#!/usr/bin/env python3
"""Adapt first: exercise handover failure cases on temporary snapshot copies.

Usage: python3 test-kivitendo-datev-handover.py --config /path/config.json
Requires a successful preparation. Reads its snapshot, tests queueing and
tampering only in a private temporary copy. Never uploads or changes accounting.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile


def rejects(action, label):
    """Assert callable raises ValueError; print case label or fail the test run."""
    try:
        action()
    except ValueError:
        print('PASS', label)
        return
    raise AssertionError(label)


def main():
    """Check XML identity/type, duplicate guard, partial periods and tampering."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('handover',Path(__file__).with_name('kivitendo-datev-handover.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cfg = module.load_config(args.config)
    original = Path(cfg['output_dir'])
    current = json.loads((original/'latest.json').read_text())
    snapshot = current['snapshot']
    manifest = json.loads((original/'snapshots'/snapshot/'manifest.json').read_text())
    with zipfile.ZipFile(original/'snapshots'/snapshot/'Belegtransfer/Belege-XML.zip') as zf:
        root = ET.fromstring(zf.read('document.xml'))
        ns = {'d':module.OUTPUT_NS}
        assert root.get('version')=='6.0'
        assert root.find('d:header/d:consultantNumber',ns).text==str(cfg['consultant_number'])
        assert root.find('d:header/d:clientNumber',ns).text==str(cfg['client_number'])
        nodes = root.findall('d:content/d:document',ns)
        assert len(nodes)==len(manifest['documents'])
        for node in nodes:
            guid=node.get('guid')
            assert node.get('processID')=='2'
            assert node.get('type')==manifest['document_metadata'][guid]['type']
            assert node.find('d:repository',ns) is not None
            assert module.digest(zf.read(guid+'.pdf'))==manifest['documents'][guid]
        print('PASS XML v6, client identity, archival mode, document types and PDF hashes')
    periods=sorted(manifest['periods'])
    with tempfile.TemporaryDirectory() as temp:
        target=Path(temp)
        shutil.copytree(original/'snapshots'/snapshot,target/'snapshots'/snapshot)
        shutil.copyfile(original/'latest.json',target/'latest.json')
        module.queue(cfg,target,periods[0],snapshot,False)
        rejects(lambda:module.queue(cfg,target,periods[0],snapshot,False),'duplicate period is blocked')
        rejects(lambda:module.queue(cfg,target,periods[1],'0'*24,False),'stale snapshot is blocked')
        rejects(lambda:module.queue(dict(cfg,client_number='99999'),target,periods[1],snapshot,False),'wrong client is blocked')
        partial=[p for p,m in current['periods'].items() if m['provisional']]
        if partial:
            rejects(lambda:module.queue(cfg,target,partial[0],snapshot,False),'partial current month is blocked')
        module.queue(cfg,target,periods[1],snapshot,False)
        packets=[json.loads(p.read_text()) for p in (target/'outbox').glob('*/manifest.json')]
        all_guids=[g for p in packets for g in p['documents']]
        assert len(all_guids)==len(set(all_guids))
        print('PASS documents are deduplicated across queued periods')
        third=periods[2]
        csv=target/'snapshots'/snapshot/'Buchungen'/third/manifest['periods'][third]['file']
        csv.write_bytes(csv.read_bytes()+b'corruption')
        rejects(lambda:module.queue(cfg,target,third,snapshot,False),'tampered snapshot is blocked')
    print('HANDOVER_TESTS_PASSED')


if __name__=='__main__':
    main()
