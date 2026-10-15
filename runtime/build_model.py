#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build only the locked model in a NEW build directory; never runs its firmware."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
from prepare_model import HERE, require, sha, verify_files


def command_version(command):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
    return result.stdout.splitlines()[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    try:
        require(sys.platform == 'linux', 'build on Linux (including a functioning WSL Linux distribution)')
        require(1 <= args.jobs <= 32, 'jobs must be 1..32')
        workspace = args.workspace.resolve()
        lock_path = HERE / 'model-source-lock.json'
        lock = json.loads(lock_path.read_text(encoding='utf-8'))
        prepared = json.loads((workspace / 'source-preparation.json').read_text(encoding='utf-8'))
        require(prepared['source_lock_sha256'] == sha(lock_path), 'preparation uses a different source lock')
        source, upstream, build = workspace / 'qemu-source', workspace / 'z8-source', workspace / 'build'
        require(not build.exists(), 'build directory already exists; never reuse prior compiled objects')
        require((source / 'configure').is_file(), 'complete QEMU source is missing')
        verify_files(upstream, lock['rdwing']['files_after'])
        verify_files(source, lock['qemu']['prepared_files'])
        require(shutil.which('ninja') is not None, 'ninja is required')
        versions = {'python': sys.version.split()[0], 'compiler': command_version(['cc', '--version']),
                    'ninja': command_version(['ninja', '--version']), 'platform': platform.platform()}
        configure = [str(source / 'configure')] + lock['qemu']['configure_args']
        compile_command = ['ninja', '-C', str(build), '-j', str(args.jobs), lock['qemu']['ninja_target']]
        # These are runtime observers. Keep them absent even during configuration subprocesses.
        env = dict(os.environ)
        for name in lock['runtime_environment']['unset']:
            env.pop(name, None)
        build.mkdir()
        with (workspace / 'build.log').open('x', encoding='utf-8') as log:
            subprocess.run(configure, cwd=build, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            subprocess.run(compile_command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        binary = build / 'qemu-system-aarch64'
        receipt = {'schema': 'route4-model-build-v1', 'source_lock_sha256': sha(lock_path),
                   'source_preparation_sha256': sha(workspace / 'source-preparation.json'),
                   'qemu_version': lock['qemu']['version'], 'overlay': lock['qemu']['prepared_files'],
                   'binary_sha256': sha(binary), 'binary_bytes': binary.stat().st_size,
                   'historical_binary_sha256': lock['historical_binary']['sha256'],
                   'binary_matches_historical': sha(binary) == lock['historical_binary']['sha256'],
                   'configure_args': lock['qemu']['configure_args'], 'target': lock['qemu']['ninja_target'],
                   'jobs': args.jobs, 'toolchain': versions, 'build_log_sha256': sha(workspace / 'build.log'),
                   'builder_sha256': sha(Path(__file__)), 'runtime_acceptance_performed': False,
                   'qualification': 'Clean source build only. Actual three-run firmware/NEF acceptance is separate.'}
        (build / 'z8-build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(receipt, indent=2))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print('ERROR: ' + str(error) + '; inspect the preserved build.log', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
