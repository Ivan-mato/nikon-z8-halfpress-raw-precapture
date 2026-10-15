#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the public static CLIs against real and deliberately invalid inputs.

Inputs are user-supplied firmware; outputs must remain private. No firmware runs.
Uses a fresh output directory, preserves receipts, and never edits input files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--package', type=Path, required=True)
    ap.add_argument('--stock', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    args = ap.parse_args()
    here = Path(__file__).resolve().parent
    out = args.output_dir.resolve()
    if out.exists() or out.is_relative_to(here.parent):
        ap.error('Choose a new output directory outside this repository')
    for label, path in [('package', args.package), ('stock MAIN', args.stock)]:
        if not path.is_file():
            ap.error(f'input missing: {label}: {path}')
    out.mkdir(parents=True, exist_ok=False)
    cases = []
    report = {'scope': 'public static CLI regression tests; no firmware execution',
              'all_expected_results_observed': False, 'cases': cases,
              'python': sys.version, 'firmware_executed': False}
    base = ['--package', str(args.package.resolve()), '--stock', str(args.stock.resolve())]

    def run(name, tool, arguments, expected_success, *, flags=(), error_text=None):
        command = [sys.executable, *flags, str(here / tool), *map(str, arguments)]
        proc = subprocess.run(command, capture_output=True, timeout=180)
        stdout = out / (name + '.stdout.txt')
        stderr = out / (name + '.stderr.txt')
        stdout.write_bytes(proc.stdout)
        stderr.write_bytes(proc.stderr)
        matched = ((proc.returncode == 0) == expected_success and
                   (error_text is None or error_text.encode() in proc.stderr))
        cases.append({'case': name, 'expected_success': expected_success,
                      'returncode': proc.returncode, 'test_pass': matched,
                      'python_flags': list(flags), 'stdout_sha256': sha(stdout),
                      'stderr_sha256': sha(stderr)})
        print(f'{name}: {"expected result" if matched else "FAILED"}', flush=True)
        if not matched:
            raise ValueError(f'Unexpected outcome: {name}; inspect private logs')
        return proc

    try:
        builddir = out / 'build'
        run('build-positive', 'build_candidate.py', base + ['--output-dir', builddir], True)
        candidate = builddir / 'route4-half-native-nef.model-payload'
        original_identity = sha(candidate)
        verify = base + ['--candidate', candidate]
        run('verify-positive', 'verify_candidate.py', verify, True)
        run('verify-positive-optimized', 'verify_candidate.py', verify, True, flags=['-O'])
        run('verify-isolated', 'verify_candidate.py', verify, True, flags=['-I', '-S'])
        for flags, suffix in [([], ''), (['-O'], '-optimized')]:
            run('existing-output' + suffix, 'build_candidate.py', base + ['--output-dir', builddir], False,
                flags=flags, error_text='output directory already exists')
        absentout = out / 'missing-must-not-exist'
        run('missing-input', 'build_candidate.py', ['--package', args.package.resolve(),
            '--stock', out / 'absent.bin', '--output-dir', absentout], False, error_text='input missing')
        wrong_package = out / 'wrong-package.bin'
        wrong_package.write_bytes(b'not a firmware package')
        run('wrong-package-optimized', 'verify_candidate.py', ['--package', wrong_package,
            '--stock', args.stock.resolve(), '--candidate', candidate], False,
            flags=['-O'], error_text='package length mismatch')
        mutant = out / 'mutant.model-payload'
        shutil.copyfile(candidate, mutant)

        def flip(offset, mask):
            with mutant.open('r+b') as stream:
                stream.seek(offset)
                value = stream.read(1)
                if len(value) != 1:
                    raise ValueError('Mutation offset out of range')
                stream.seek(offset)
                stream.write(bytes([value[0] ^ mask]))

        flip(0, 1)
        for flags, suffix in [([], ''), (['-O'], '-optimized')]:
            run('extra-byte' + suffix, 'verify_candidate.py', base + ['--candidate', mutant], False,
                flags=flags, error_text='changed instruction sites differ')
        badstockout = out / 'bad-stock-must-not-exist'
        run('wrong-stock-optimized', 'build_candidate.py', ['--package', args.package.resolve(),
            '--stock', mutant, '--output-dir', badstockout], False,
            flags=['-O'], error_text='stock MAIN SHA-256 mismatch')
        flip(0, 1)
        branch_offset = 0x40FD93BC - 0x40160000
        flip(branch_offset, 1)
        run('wrong-branch', 'verify_candidate.py', base + ['--candidate', mutant], False,
            error_text='wrong patched branch target')
        flip(branch_offset, 1)
        flip(0x40FD94C0 - 0x40160000 + 1, 4)
        run('store-writeback-optimized', 'verify_candidate.py', base + ['--candidate', mutant], False,
            flags=['-O'], error_text='bridge must use integer byte unscaled store without writeback')
        if absentout.exists() or badstockout.exists() or sha(candidate) != original_identity:
            raise ValueError('Rejected build left output or original candidate changed')
        report.update(all_expected_results_observed=True, candidate_sha256=original_identity,
                      tool_sha256={name: sha(here / name) for name in
                                   ['build_candidate.py', 'verify_candidate.py', 'test_static_tools.py']})
        print('PASS: all 13 expected static test outcomes observed', flush=True)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    finally:
        (out / 'test-results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
