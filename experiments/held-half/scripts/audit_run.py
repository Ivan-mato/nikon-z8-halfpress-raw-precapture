#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Independently check a stopped card, actual inputs and all decoded CFA samples."""
from pathlib import Path
import argparse, hashlib, json, re, sys, tempfile
import numpy, rawpy
from PIL import __version__ as pillow_version
from content import Card, structure, compare, digest
from behavior import audit as audit_behavior

EXPERIMENT = Path(__file__).resolve().parents[1]

def main():
    if sys.flags.optimize:
        raise ValueError('Do not use -O: audit assertions are required')
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('run','fixtures','output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--kind', choices=['candidate','stock'], required=True)
    a = p.parse_args(); run=a.run.resolve(); output=a.output.resolve()
    assert not output.exists() and not output.is_relative_to(EXPERIMENT.parents[1])
    output.mkdir(parents=True)
    lock=json.loads((EXPERIMENT/'source-lock.json').read_text())
    fixture_paths=[a.fixtures/name for name in sorted(lock['fixtures'])]
    assert len(fixture_paths)==32
    for path in fixture_paths:
        assert digest(path)==lock['fixtures'][path.name]
    d=json.loads((run/'result.json').read_text())
    exit_receipt=json.loads((run.parent/(run.name+'-exit.json')).read_text())
    guard=json.loads((run.parent/(run.name+'-transport-audit.json')).read_text())
    assert exit_receipt['exit_code']==0 and d['owned_qemu_stopped'] and d['error'] is None
    assert d['qemu_sha256']==exit_receipt['binary_sha256']
    assert d['firmware_sha256']==lock['stock_sha256' if a.kind=='stock' else 'candidate_sha256']
    assert not guard['blocked']
    gpio=[w['value'] for w in guard['writes'] if w.get('property')=='capture-gpio-input']
    assert gpio==['0','1','0']
    memory=sorted({w['command'].split()[1] for w in guard['writes'] if w['kind']=='external_mcu_gpio'})
    irq=sorted({int(w['command'].split()[-2]) for w in guard['writes'] if w['kind']=='external_irq'})
    assert memory==['0xd15100c','0xd151010'] and irq==[25,26]
    assert [s['sha256'] for s in d['sensor_frames']]==[lock['fixtures'][p.name] for p in fixture_paths]
    # Bind the recorded source order to the actual QEMU machine command, too.
    machine=d['command'][d['command'].index('-M')+1]
    primary=next(s for s in machine.split(',') if s.startswith('statistics-raw=')).split('=',1)[1]
    rest=next(s for s in machine.split(',') if s.startswith('statistics-raw-frames=')).split('=',1)[1].split(':')
    assert [primary,*rest]==[s['path'] for s in d['sensor_frames']]
    behavior=audit_behavior(run, a.kind=='stock')
    card=Card(run/'capture-card.raw')
    files=[r for r in card.rows if not r['directory']]
    rows=sorted([r for r in files if r['path'].upper().endswith('.NEF')],key=lambda r:r['path'])
    expected_count=0 if a.kind=='stock' else 27
    assert len(rows)==expected_count
    enc=re.findall(r'Z8_1540_FRAME_PASS[^\n]*bytes=(\d+)[^\n]*frame=(\d+)[^\n]*vt=(\d+)',(run/'stderr.log').read_text())
    assert [int(e[1]) for e in enc]==list(range(1,expected_count+1))
    records=[]; negative=None
    if a.kind=='stock':
        assert all(Path(r['path']).name=='NIKON001.DSC' and r['bytes']==512 for r in files)
    with tempfile.TemporaryDirectory(prefix='decode-',dir=output) as tmp:
        for i,row in enumerate(rows):
            assert row['valid_bytes']==row['bytes']
            nef=Path(tmp)/Path(row['path']).name
            with nef.open('xb') as f:
                for block in card.blocks(row['first_cluster'],row['bytes'],row['contiguous']):f.write(block)
            s=structure(nef.read_bytes()); assert s['strip_bytes']==int(enc[i][0])
            c=compare(nef,fixture_paths[i])
            records.append(dict(name=nef.name,bytes=nef.stat().st_size,sha256=digest(nef),source=c,structure=s))
            if i==0:
                try:
                    compare(nef,fixture_paths[1])
                except AssertionError as error:
                    # Reject a genuine wrong-source match, not an unrelated parse error.
                    assert error.args and isinstance(error.args[0],dict)
                    negative=error.args[0]
                    assert negative['mismatches']==45705600
                else:
                    raise AssertionError('Wrong-source negative control unexpectedly matched')
            nef.unlink()
            print(json.dumps(dict(file=row['path'],samples=c['samples'],mismatches=c['mismatches'])),flush=True)
    card.f.close()
    assert len({r['source']['decoded_sha256'] for r in records})==expected_count
    report=dict(passed=True,scope='Held-HALF model profile; not complete original six-case acceptance',
        case=a.kind,behavior=behavior,nef_count=len(rows),files=records,all_native_card_files=files,
        total_samples_compared=sum(r['source']['samples'] for r in records),
        producer_samples_compared=False,wrong_source_negative_control=negative,
        transport=dict(blocked=guard['blocked'],capture_gpio_writes=gpio,memory_addresses=memory,irq_indexes=irq),
        versions=dict(rawpy=rawpy.__version__,libraw=list(rawpy.libraw_version),numpy=numpy.__version__,pillow=pillow_version),
        scripts={p.name:digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))},
        inputs=dict(result_sha256=digest(run/'result.json'),stderr_sha256=digest(run/'stderr.log'),
                    exit_receipt_sha256=digest(run.parent/(run.name+'-exit.json')),
                    guard_receipt_sha256=digest(run.parent/(run.name+'-transport-audit.json'))))
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,case=a.kind,nef_count=len(rows),total_samples=report['total_samples_compared'])))

if __name__=='__main__':
    main()
