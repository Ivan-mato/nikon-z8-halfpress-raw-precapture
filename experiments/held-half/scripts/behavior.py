# SPDX-License-Identifier: GPL-3.0-only
"""Recompute behavioral facts from recorded inputs, receiver dumps and counters.

This does not treat self-reported 'passed' booleans as the verdict.
"""
from pathlib import Path
import hashlib,json,re,sys
from PIL import Image


def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def encoded(row):
    return sum(b['jobs'] for b in row['capture_models']['engine1540-alternate-bank-state']['banks'])

def audit(run,stock=False):
    d=json.loads((run/'result.json').read_text())
    log=(run/'stderr.log').read_text()
    steps=d['shutter_inputs']; assert [(s['half'],s['full']) for s in steps]==[(0,0),(1,0),(0,0)]
    t0,release=steps[1]['virtual_seconds'],steps[2]['virtual_seconds']
    assert release-t0>=14
    rx=d['continuous_mcu_peer']['rx']
    assert all(bytes.fromhex(r['body_hex'])[8]==0 for r in rx if r['family']==2)
    contacts=[r for r in rx if r['family']==2 and r['accepted_virtual_seconds']>=steps[0]['virtual_seconds']]
    assert len(contacts)==3
    receipts=[]
    for planned,received in zip(steps,contacts):
        frame=bytes.fromhex(received['frame_hex']); body=bytes.fromhex(received['body_hex'])
        saved=run/f"continuous-rx-{received['index']:03d}-accepted.bin"
        assert received['complete'] and len(frame)==256 and sum(frame)%256==255
        assert saved.read_bytes()==frame and body.hex()==planned['body_hex']
        assert body[7:9]==bytes([planned['half'],planned['full']])
        assert frame[8:8+len(body)]==body
        delay=received['accepted_virtual_seconds']-planned['virtual_seconds']; assert 0<=delay<=1
        receipts.append(dict(index=received['index'],half=body[7],full=body[8],gpio_time=planned['virtual_seconds'],
            mcu_accepted_time=received['accepted_virtual_seconds'],accepted_dump_sha256=sha(saved)))
    samples=d['pipeline_samples']; assert len(samples)>20
    assert all(b['virtual_seconds']>=a['virtual_seconds'] for a,b in zip(samples,samples[1:]))
    for counter in (lambda s:s['d980']['submits'],lambda s:s['d980']['frames'],encoded):
        values=[counter(s) for s in samples]
        assert all(b>=a for a,b in zip(values,values[1:]))
    held=[s for s in samples if t0<s['virtual_seconds']<release]
    after=[s for s in samples if s['virtual_seconds']>release]
    before=[s for s in samples if s['virtual_seconds']<t0]
    assert held and after and before
    assert all(s['capture_gpio']['levels']==1 for s in held)
    assert all(s['capture_gpio']['levels']==0 for s in after)
    assert all(s['capture_gpio']['levels']&2==0 for s in samples)
    assert all(s['d980']['frames']==encoded(s)==0 for s in before)
    assert samples[-1]['capture_gpio']['edges']==2
    unknown=[line for line in log.splitlines() if 'Z8_UNKNOWN' in line]
    native_errors=[e['label'] for e in d.get('capture_full_events',[]) if 'native_error' in e.get('label','')]
    assert not unknown and not native_errors and d['error'] is None and d['owned_qemu_stopped']
    assert all(c['passed'] for c in d['checks'])
    assert d['continuous_mcu_peer']['pending_replies']==0 and d['shutter_plan_completed']
    events=[dict(bytes=int(m[0]),generation=int(m[1]),fnv64=m[2],time=int(m[3])/1e9)
        for m in re.findall(r'^Z8_1540_FRAME_PASS .*?bytes=(\d+).*?frame=(\d+).*?fnv64=([0-9a-f]+).*?vt=(\d+)',log,re.M)]
    final=samples[-1]; total=final['d980']['frames']; assert encoded(final)==total
    assert [r['generation'] for r in events]==list(range(1,total+1))
    assert total==(0 if stock else 27)
    stable=[s for s in samples if s['virtual_seconds']>=release+1]
    assert stable and all(s['d980']['frames']==s['d980']['submits']==total for s in stable)
    tail=[s for s in samples if s['virtual_seconds']>=final['virtual_seconds']-5]
    assert len(tail)>=2 and all(s['d980']['frames']==encoded(s)==total for s in tail)
    changed=[]; prev=0
    for s in samples:
        if s['d980']['frames']!=prev:
            changed.append(dict(time=s['virtual_seconds'],frames=s['d980']['frames'],submits=s['d980']['submits']))
            prev=s['d980']['frames']
    if stock: assert all(s['d980']['frames']==s['d980']['submits']==encoded(s)==0 for s in samples)
    frames=[]; panel_errors=[]
    known={'65ea568923a8d44ab61a7c5e8929a6118de867cc61828eae0315ddf44ed1993a','5ac2f792567c32317095d602a6ced213033a3727e6300107b637a0558d427b4e'}
    for p in sorted([*run.glob('frame-*.ppm'),*run.glob('*.png')]):
        with Image.open(p) as image:
            if image.size!=(1024,682):continue
            h=hashlib.sha256(image.convert('RGB').crop((171,155,844,547)).tobytes()).hexdigest()
            frames.append(p.name)
            if h in known:panel_errors.append(p.name)
    assert not panel_errors
    held_events=[e for e in events if t0<e['time']<release]
    times=[t0]+[e['time'] for e in held_events]+[release]
    release_before=max((s for s in samples if s['virtual_seconds']<=release),key=lambda s:s['virtual_seconds'])
    fact=dict(run=str(run),stock=stock,passed=True,tool_sha256=sha(__file__),firmware_sha256=d['firmware_sha256'],
        qemu_sha256=d['qemu_sha256'],hold_virtual_seconds=release-t0,input_receipts=receipts,
        unknown_lines=len(unknown),native_error_callbacks=native_errors,screens_checked=len(frames),known_error_screens=panel_errors,
        before_release=dict(time=release_before['virtual_seconds'],captures=release_before['d980']['frames'],submits=release_before['d980']['submits'],encoded=encoded(release_before)),
        final_captures=total,final_encoded=encoded(final),held_encoded_count=len(held_events),
        max_held_encoding_gap=max(b-a for a,b in zip(times,times[1:])),
        first_observed_final_capture_time=changed[-1]['time'] if changed else None,
        capture_finish_delay_after_release=changed[-1]['time']-release if changed else None,
        additional_capture_submits_after_release=final['d980']['submits']-release_before['d980']['submits'],
        last_encoding_time=events[-1]['time'] if events else None,
        last_encoding_delay_after_release=events[-1]['time']-release if events else None,
        observed_quiet_tail_seconds=final['virtual_seconds']-tail[0]['virtual_seconds'],
        total_observation_after_release=final['virtual_seconds']-release,
        capture_steps=changed,encoding_events=events,
        limitation='Recorded states cannot prove that the post-release submit was already queued in firmware before release; no claim of instantaneous stop.',
        runtime_override_claim=d.get('cpu_register_redirection') or d.get('ram_patches'))
    return fact
