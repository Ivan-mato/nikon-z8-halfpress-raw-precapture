# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Read-only card audit: one held FULL, distinct fully decoded NEFs in source order.

Extracts actual initialized exFAT files after the owned guest has stopped.
Never produces a NEF from source pixels or repairs the card.
"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import re
import struct
import subprocess
import tempfile

import numpy as np
import rawpy
from PIL import Image
from extract_card_file import extract
from inspect_card_volume import catalog
from nef_ifds import image_ifds, require_lossless14


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def native_error_frames(run):
    """Recognize two observed C3.11 English error panels, not all errors."""
    matches = []
    for path in sorted([*run.glob('frame-*.ppm'), *run.glob('*.png')]):
        with Image.open(path) as im:
            if im.size != (1024, 682):
                continue
            digest = hashlib.sha256(im.convert('RGB').crop((171, 155, 844, 547)).tobytes()).hexdigest()
        if digest in {
            # Press shutter-release button to reset.
            '65ea568923a8d44ab61a7c5e8929a6118de867cc61828eae0315ddf44ed1993a',
            # Turn camera off and then on again.
            '5ac2f792567c32317095d602a6ced213033a3727e6300107b637a0558d427b4e',
        }:
            matches.append(path.name)
    return matches


def compare_fixture(decoded, path):
    with path.open('rb') as stream:
        header = stream.read(32)
    if header[:8] != b'NZ9RAW1\0':
        raise ValueError('Invalid fixture magic')
    sw, sh, bits, cfa, black, white = struct.unpack_from('<6I', header, 8)
    if (bits, cfa, black, white) != (14, 0, 0, 16383):
        raise ValueError('Oracle requires 14-bit RGGB, black=0, white=16383')
    if path.stat().st_size != 32 + sw * sh * 2 or sw % 2 or sh % 2:
        raise ValueError('Invalid fixture geometry')
    source = np.memmap(path, dtype='<u2', mode='r', offset=32, shape=(sh, sw))
    h, w = decoded.shape
    x = np.arange(w, dtype=np.int64)
    sx = (x // 2 * (sw // 2) // (w // 2)) * 2 + (x & 1)
    mismatches = 0
    for y in range(h):
        sy = (y // 2 * (sh // 2) // (h // 2)) * 2 + (y & 1)
        mismatches += int(np.count_nonzero(decoded[y] != source[sy, sx]))
    return mismatches


def held_progress(samples, full_at, released_at, jobs, max_idle):
    """Bounded liveness criterion; a few early frames followed by a stall fails."""
    points = []
    previous = 0
    monotonic = True
    for row in samples:
        count = jobs(row)
        monotonic &= count >= previous
        if count > previous:
            points.append(row['virtual_seconds'])
        previous = count
    if full_at is None or released_at is None:
        return {'passed': False, 'max_idle_seconds': max_idle, 'progress_times': points}
    boundaries = [full_at, *points, released_at]
    gaps = [b-a for a, b in zip(boundaries, boundaries[1:])]
    return {'passed': bool(points) and monotonic and max(gaps) <= max_idle,
            'max_idle_seconds': max_idle, 'largest_observed_gap': max(gaps),
            'progress_times': points, 'monotonic': monotonic}


def audit(run, minimum, require_cl=False, max_idle=2.0):
    data = json.loads((run / 'result.json').read_text())
    if not data.get('owned_qemu_stopped'):
        raise ValueError('Owned QEMU must be stopped before card audit')
    log = (run / 'stderr.log').read_text()
    contacts = data.get('shutter_inputs', [])
    gesture = [(r['half'], r['full']) for r in contacts]
    error_frames = native_error_frames(run)
    error_callbacks = [e for e in data.get('capture_full_events', [])
                       if e['label'] == 'capture_full_native_error']
    error_callbacks += [e for e in data.get('diagnostic_burst_events', [])
                        if e['name'] == 'native_error']
    checks = {
        'final_screen_available': (run / 'final.png').is_file(),
        'no_known_native_error_panel': not error_frames,
        'no_observed_native_error_callback': not error_callbacks,
        'no_runtime_error': data.get('error') is None,
        'no_unknown_mmio': 'Z8_UNKNOWN' not in log,
        'no_guest_ram_or_pc_override': not data.get('ram_patches') and not data.get('cpu_register_redirection'),
        'one_held_gesture': gesture == [(0, 0), (1, 0), (1, 1), (1, 0), (0, 0)],
        'release_settle_completed': data.get('shutter_plan_completed') is True,
    }
    if checks['one_held_gesture']:
        full_at, released_at = contacts[2]['virtual_seconds'], contacts[3]['virtual_seconds']
        checks['hold_duration_met'] = released_at - full_at >= data['shutter_plan']['hold_virtual_seconds']
        checks['both_input_routes_agree'] = all(
            bytes.fromhex(r['body_hex'])[7:9] == bytes((r['half'], r['full']))
            and r['gpio'] == (r['half'] | (r['full'] << 1)) for r in contacts)
    else:
        full_at = released_at = None
        checks['hold_duration_met'] = checks['both_input_routes_agree'] = False
    sources = [Path(r['path']) for r in data.get('sensor_frames', [])]
    checks['source_identities_match'] = bool(sources) and all(
        sha(p) == r['sha256'] for p, r in zip(sources, data['sensor_frames']))
    listing = catalog(run / 'capture-card.raw', base=1048576)
    entries = sorted((r for r in listing['files'] if not r['directory'] and
                      r['path'].upper().endswith('.NEF')), key=lambda r: r['path'])
    checks['multiple_complete_card_files'] = len(entries) >= minimum and all(
        e['bytes'] > 0 and e['valid_bytes'] == e['bytes'] for e in entries)
    output = run / 'burst-extracted'
    output.mkdir(exist_ok=True)
    reports = []
    for entry in entries:
        record = {'card_entry': entry}
        try:
            nef = output / Path(entry['path']).name
            if not nef.exists():
                extract(run / 'capture-card.raw', entry['path'], nef)
            receipt = json.loads(nef.with_suffix('.NEF.extraction.json').read_text())
            if receipt['entry'] != entry or receipt['sha256'] != sha(nef):
                raise ValueError('Extracted file receipt differs from current card entry')
            # Compare the extraction with the card on each audit, not only with
            # its earlier receipt. A fresh path forces the read-only extractor.
            with tempfile.TemporaryDirectory(prefix='verify-', dir=output) as temp:
                verification = extract(run / 'capture-card.raw', entry['path'], Path(temp) / nef.name)
            if verification['sha256'] != receipt['sha256']:
                raise ValueError('Extracted file no longer matches card bytes')
            payload = nef.read_bytes()
            ifds = image_ifds(payload)
            raw_ifds = [r['tags'] for r in ifds if r['tags'].get(254) == [0]
                        and r['tags'].get(262) == [32803]]
            if len(raw_ifds) != 1:
                raise ValueError('One RAW IFD required')
            tags = raw_ifds[0]
            linearization = subprocess.check_output(['exiftool', '-b', '-NEFLinearizationTable', str(nef)])
            require_lossless14(tags, linearization)
            previews = []
            for row in ifds:
                t = row['tags']
                if 513 in t and 514 in t:
                    off, length = t[513][0], t[514][0]
                    if not length or off + length > len(payload):
                        raise ValueError('Truncated JPEG preview')
                    with Image.open(io.BytesIO(payload[off:off + length])) as im:
                        im.load()
                        previews.append(list(im.size))
            if not all(list(size) in previews for size in ((8256, 5504), (1620, 1080), (160, 120))):
                raise ValueError('Expected embedded previews absent')
            with rawpy.imread(str(nef)) as raw:
                decoded = raw.raw_image
                if decoded.shape != (5520, 8280):
                    raise ValueError('Unexpected RAW dimensions')
                differences = [compare_fixture(decoded, p) for p in sources]
                record.update(decoded_shape=list(decoded.shape), decoded_samples=int(decoded.size),
                              decoded_sha256=hashlib.sha256(decoded.tobytes()).hexdigest(),
                              source_mismatches=differences,
                              exact_source_matches=[i for i, n in enumerate(differences) if n == 0])
            record.update(file=str(nef), sha256=sha(nef), previews=previews,
                          lossless14=True, decoded=True)
        except Exception as exc:
            record.update(decoded=False, error=repr(exc))
        reports.append(record)
    mapping = [r.get('exact_source_matches', []) for r in reports]
    checks['all_nefs_decode'] = bool(reports) and all(r['decoded'] for r in reports)
    checks['unique_ordered_source_mapping'] = len(mapping) >= minimum and mapping == [[i] for i in range(len(mapping))]
    checks['distinct_decoded_pixels'] = checks['all_nefs_decode'] and len({r['decoded_sha256'] for r in reports}) == len(reports)
    held_samples = [r for r in data.get('pipeline_samples', []) if full_at is not None
                    and full_at <= r['virtual_seconds'] < released_at]
    def jobs(row):
        models = row.get('capture_models', {})
        dual = models.get('engine1540-alternate-bank-state')
        return sum(b['jobs'] for b in dual['banks']) if dual else models.get('engine1540-frame-pass-state', {}).get('jobs', 0)
    checks['multiple_raw_outputs_during_hold'] = max(map(jobs, held_samples), default=0) >= minimum
    progress = held_progress(held_samples, full_at, released_at, jobs, max_idle)
    checks['raw_progress_throughout_hold'] = progress['passed']
    before_hold = [r for r in data.get('pipeline_samples', [])
                   if full_at is not None and r['virtual_seconds'] < full_at]
    checks['no_raw_outputs_before_full'] = bool(before_hold) and all(jobs(r) == 0 for r in before_hold)
    writes = [e for e in data.get('release_property_events', []) if 'ids' in e
              and full_at is not None and e['virtual_seconds'] < full_at]
    props = {}
    for event in writes:
        props.update(zip(event['ids'], event['values']))
    cl_request = all(
        props.get(k) == v for k, v in ((0x06000108, 1), (0x0600010a, 0), (0x06000109, 0)))
    # The burst contract is mode-independent: one held gesture must produce
    # distinct native files. Separately qualify the particular CL property
    # path when requested; a HUD label or dial delta cannot establish it.
    if require_cl:
        checks['native_continuous_l_request_observed'] = cl_request
    final_time = data.get('final_virtual_seconds', 0)
    tail = [r for r in data.get('pipeline_samples', [])
            if released_at is not None and r['virtual_seconds'] >= max(released_at, final_time - 5)]
    checks['quiescent_after_release'] = len(tail) >= 2 and all(
        jobs(r) == len(entries) and r['d980']['frames'] == len(entries) for r in tail)
    result = dict(passed=all(checks.values()), checks=checks, files=reports,
                  minimum_files=minimum, auditor_sha256=sha(Path(__file__)),
                  held_progress=progress,
                  directory=listing, firmware_sha256=data['firmware_sha256'],
                  qemu_sha256=data['qemu_sha256'], full_request=full_at, full_release=released_at,
                  unknown_events=re.findall(r'Z8_UNKNOWN[^\n]*', log),
                  native_error_panel_frames=error_frames,
                  native_error_callbacks=error_callbacks,
                  mode_evidence={'cl_property_request_observed': cl_request,
                                 'properties': {hex(k): v for k, v in props.items()},
                                 'events': writes, 'required_for_this_audit': require_cl},
                  rawpy=rawpy.__version__, libraw=list(rawpy.libraw_version),
                  scope='Bounded Z8 functional-model RAW burst; no physical-camera claim')
    (run / 'burst-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--minimum', type=int, default=2)
    parser.add_argument('--require-cl', action='store_true', help='Also require an observed native CL property request')
    parser.add_argument('--max-idle-seconds', type=float, default=2.0,
                        help='Maximum observed RAW-output gap during FULL, including both ends (guest seconds)')
    args = parser.parse_args()
    if args.minimum < 2:
        parser.error('--minimum must be at least 2')
    if not 0 < args.max_idle_seconds < float('inf'):
        parser.error('--max-idle-seconds must be finite and positive')
    result = audit(args.output.resolve(), args.minimum, args.require_cl, args.max_idle_seconds)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
