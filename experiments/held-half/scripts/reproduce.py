#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Portable preparation, clean build and two-case held-HALF model replay."""
from pathlib import Path
import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile

EXPERIMENT = Path(__file__).resolve().parents[1]
REPO = EXPERIMENT.parents[1]
LOCK = json.loads((EXPERIMENT/'source-lock.json').read_text())

def require(ok, message):
    if not ok:
        raise ValueError(message)

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def save(path, data):
    with Path(path).open('x') as f:
        json.dump(data, f, indent=2)
        f.write('\n')

def verify_model(root):
    for rel, expected in LOCK['model_files'].items():
        require(sha(root/rel) == expected, 'Model identity mismatch: '+rel)

def clean_env():
    env = {k:v for k,v in os.environ.items() if not k.startswith(('Z8_', 'QEMU_', 'PYTHONOPTIMIZE'))}
    env.update(OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')
    return env

def outside_repo(path):
    path = path.resolve()
    require(not path.is_relative_to(REPO), 'Keep private output outside the repository')
    require(',' not in str(path) and ':' not in str(path), 'Linux paths without comma or colon required')
    require(not str(path).startswith('/mnt/'), 'Use a native Linux filesystem for active runs and sparse cards')
    return path

def prepare(a):
    work = outside_repo(a.work)
    require(not work.exists(), 'Choose a new, nonexistent workspace')
    archive = a.qemu_archive.resolve()
    require(archive.stat().st_size == LOCK['qemu']['bytes'] and sha(archive) == LOCK['qemu']['sha256'],
            'Wrong QEMU archive; see source-lock.json')
    verify_model(EXPERIMENT/'model')
    require(sha(EXPERIMENT/'synthetic-inputs.zip') == LOCK['fixture_archive_sha256'], 'Wrong fixture archive')
    work.mkdir(parents=True)
    shutil.copytree(EXPERIMENT/'model', work/'model')
    (work/'fixtures').mkdir()
    with zipfile.ZipFile(EXPERIMENT/'synthetic-inputs.zip') as z:
        require(sorted(z.namelist()) == sorted(LOCK['fixtures']), 'Unexpected fixture entries')
        for name, expected in LOCK['fixtures'].items():
            data = z.read(name)
            require(len(data) == 614432 and hashlib.sha256(data).hexdigest() == expected, 'Wrong fixture '+name)
            (work/'fixtures'/name).write_bytes(data)
    source = work/'qemu-source'
    source.mkdir()
    skipped = []
    with tarfile.open(archive) as tar:
        for member in tar:
            if member.name.rstrip('/') == 'qemu-11.1.1':
                continue
            require(member.name.startswith('qemu-11.1.1/'), 'Unexpected QEMU archive prefix')
            member.name = member.name[len('qemu-11.1.1/'):]
            if member.issym() and member.linkname.startswith('/'):
                require((member.name,member.linkname) ==
                        ('roms/edk2/EmulatorPkg/Unix/Host/X11IncludeHack','/opt/X11/include'),
                        'Unexpected absolute archive link')
                skipped.append(member.name)
                continue
            tar.extract(member, source, filter='data')
    save(work/'preparation.json', dict(source_lock_sha256=sha(EXPERIMENT/'source-lock.json'),
        qemu_archive_sha256=sha(archive), skipped_unused_symlinks=skipped,
        model_files=LOCK['model_files'], fixture_files=LOCK['fixtures']))
    print(json.dumps(dict(prepared=str(work), frozen_model_files=len(LOCK['model_files']))), flush=True)

def build(a):
    work = outside_repo(a.work)
    preparation = json.loads((work/'preparation.json').read_text())
    require(preparation['source_lock_sha256'] == sha(EXPERIMENT/'source-lock.json'), 'Preparation lock differs')
    verify_model(work/'model')
    require(not (work/'build').exists(), 'A clean, nonexistent build directory is required')
    require(1 <= a.jobs <= 64, 'Use 1..64 build jobs')
    command = [sys.executable, str(work/'model/tools/build.py'), '--qemu-source', str(work/'qemu-source'),
               '--build-dir', str(work/'build'), '--jobs', str(a.jobs)]
    started = time.monotonic()
    with (work/'build.log').open('x') as log:
        code = subprocess.call(command, stdout=log, stderr=subprocess.STDOUT, env=clean_env())
    receipt = dict(exit_code=code, command=command, elapsed_seconds=time.monotonic()-started,
                   source_lock_sha256=sha(EXPERIMENT/'source-lock.json'), clean_build=True)
    if code == 0:
        receipt['binary_sha256'] = sha(work/'build/qemu-system-aarch64')
        receipt['overlay'] = json.loads((work/'build/z8-build-receipt.json').read_text())['overlay']
        reference = json.loads((EXPERIMENT/'evidence/independent-build.json').read_text())['data']['overlay']
        require(receipt['overlay'] == reference, 'Prepared overlay differs from the reviewed model')
    save(work/'build-result.json', receipt)
    print(json.dumps(receipt), flush=True)
    require(code == 0, 'Build failed; preserve build.log')

def model_tests(a):
    work = outside_repo(a.work)
    target = work/'test-harness-copy'
    verify_model(work/'model')
    require(not target.exists(), 'Preserve earlier test results; use a fresh workspace')
    shutil.copytree(work/'model', target)
    p = target/'tests/test_raw_owners.py'
    original = p.read_text()
    needle = '#define MEMTX_OK 0\n'
    require(original.count(needle) == 1, 'Unexpected test harness')
    fixed = original.replace(needle, needle+'#define QEMU_CLOCK_VIRTUAL 0\n'
        'static uint64_t qemu_clock_get_ns(int clock)\n'
        '{ (void)clock; return 0; } /* Diagnostic timestamp only. */\n')
    p.write_text(fixed)
    command = [sys.executable, str(target/'tests/run.py')]
    with (work/'model-tests.log').open('x') as log:
        code = subprocess.call(command, stdout=log, stderr=subprocess.STDOUT, env=clean_env())
    save(work/'model-tests.json', dict(exit_code=code, original_suite_requires_clock_stub=True,
        changed_file='tests/test_raw_owners.py', original_sha256=LOCK['model_files']['tests/test_raw_owners.py'],
        repaired_sha256=sha(p), model_and_capture_driver_unchanged=True, command=command))
    require(code == 0, 'Model tests failed; see model-tests.log')
    print('PASS isolated model tests with documented clock stub; frozen model unchanged', flush=True)

def run(a):
    work = outside_repo(a.work)
    output = outside_repo(a.output)
    require(not output.exists(), 'A new output directory is required')
    verify_model(work/'model')
    build_receipt = json.loads((work/'build-result.json').read_text())
    binary = work/'build/qemu-system-aarch64'
    require(build_receipt['exit_code'] == 0 and build_receipt['binary_sha256'] == sha(binary), 'Build identity mismatch')
    require(build_receipt['source_lock_sha256'] == sha(EXPERIMENT/'source-lock.json'), 'Build source lock mismatch')
    fixtures = [work/'fixtures'/name for name in sorted(LOCK['fixtures'])]
    for path in fixtures:
        require(sha(path) == LOCK['fixtures'][path.name], 'Fixture mismatch '+path.name)
    require(sha(a.stock) == LOCK['stock_sha256'], 'Wrong stock MAIN')
    output.mkdir(parents=True)
    # These existing tools independently check the exact package, MAIN and seven edits.
    subprocess.run([sys.executable, str(REPO/'tools/build_candidate.py'), '--package', str(a.package.resolve()),
        '--stock', str(a.stock.resolve()), '--output-dir', str(output/'candidate-payload')], check=True)
    candidate = output/'candidate-payload/route4-half-native-nef.model-payload'
    subprocess.run([sys.executable, str(REPO/'tools/verify_candidate.py'), '--package', str(a.package.resolve()),
        '--stock', str(a.stock.resolve()), '--candidate', str(candidate)], check=True)
    template = output/'empty-card.raw'
    subprocess.run([sys.executable, str(work/'model/tools/make_card.py'), '--output', str(template)], check=True)
    def execute(stock):
        name = 'stock' if stock else 'candidate'
        out = output/name
        command = [sys.executable, str(EXPERIMENT/'scripts/guarded_capture.py'), str(work/'model'),
            '--firmware', str(a.stock.resolve() if stock else candidate), '--qemu', str(binary),
            '--raw', str(fixtures[0]), '--card-template', str(template), '--output', str(out),
            '--seconds', '1200', '--settle', '12' if stock else '85', '--hold-seconds', '14',
            '--halfpress-held', '--release-mode-steps', '1', '--experimental-preparation-profile',
            '--experimental-capture-selector5', '--experimental-timed-single', '--experimental-multiframe',
            '--menu-actions', 'menu,down,down,down,down,down,down,down,down,down,down,ok,up,ok,menu,menu']
        for fixture in fixtures[1:]:
            command.extend(['--raw-frame', str(fixture)])
        if stock:
            command.append('--stock-half-control')
        started = time.monotonic()
        with (output/(name+'-controller.log')).open('x') as log:
            code = subprocess.call(command, stdout=log, stderr=subprocess.STDOUT, env=clean_env())
        save(output/(name+'-exit.json'), dict(exit_code=code, command=command,
            elapsed_seconds=time.monotonic()-started, binary_sha256=sha(binary),
            source_lock_sha256=sha(EXPERIMENT/'source-lock.json')))
        print(json.dumps(dict(case=name, driver_exit=code)), flush=True)
        require(code == 0, name+' driver failed; do not count an aborted run as a negative control')
        return name
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        cases = list(pool.map(execute, (False, True)))
    for name in cases:
        subprocess.run([sys.executable, str(EXPERIMENT/'scripts/audit_run.py'), '--run', str(output/name),
            '--kind', name, '--fixtures', str(work/'fixtures'), '--output', str(output/(name+'-audit'))],
            check=True, env=clean_env())
    print('PASS candidate 27 / stock 0, including complete source-to-NEF comparison; see audit reports', flush=True)

def main():
    require(not sys.flags.optimize, 'Do not use python -O; inherited checks use assertions')
    require(sys.version_info >= (3,12), 'Python 3.12+ required for this Linux reproduction recipe')
    require(sys.platform.startswith('linux'), 'Use Linux / WSL2 with native Linux output paths')
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    s = sub.add_parser('prepare'); s.add_argument('--work', type=Path, required=True)
    s.add_argument('--qemu-archive', type=Path, required=True); s.set_defaults(func=prepare)
    s = sub.add_parser('build'); s.add_argument('--work', type=Path, required=True)
    s.add_argument('--jobs', type=int, default=2); s.set_defaults(func=build)
    s = sub.add_parser('test-model'); s.add_argument('--work', type=Path, required=True); s.set_defaults(func=model_tests)
    s = sub.add_parser('run'); s.add_argument('--work', type=Path, required=True)
    for name in ('package','stock','output'):
        s.add_argument('--'+name, type=Path, required=True)
    s.set_defaults(func=run)
    a = p.parse_args(); a.func(a)

if __name__ == '__main__':
    main()
