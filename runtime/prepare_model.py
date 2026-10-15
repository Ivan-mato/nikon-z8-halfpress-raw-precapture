#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare locked public model sources in a NEW private workspace; never runs QEMU."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_files(root, expected):
    actual = {}
    for relative, wanted in expected.items():
        p = root / relative
        require(p.is_file() and not p.is_symlink(), 'missing/nonregular locked file: ' + relative)
        got = sha(p)
        require(got == wanted, 'source identity mismatch: ' + relative)
        actual[relative] = got
    return actual


def archive_file(explicit, cache, record):
    path = explicit or cache / record['name']
    if not path.exists():
        require(explicit is None, 'specified archive missing: ' + str(path))
        cache.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + '.part')
        with urllib.request.urlopen(record['url'], timeout=120) as source, partial.open('xb') as dest:
            shutil.copyfileobj(source, dest)
        require(partial.stat().st_size == record['bytes'] and sha(partial) == record['sha256'],
                'download differs from source lock; partial retained: ' + str(partial))
        partial.rename(path)
    require(path.is_file() and path.stat().st_size == record['bytes'] and sha(path) == record['sha256'],
            'archive identity mismatch: ' + str(path))
    return path


def member_target(root, name, prefix):
    posix = PurePosixPath(name)
    require(not posix.is_absolute() and '..' not in posix.parts and '\\' not in name,
            'unsafe archive member')
    require(posix.parts and posix.parts[0] == prefix, 'unexpected archive root')
    relative = posix.parts[1:]
    target = root.joinpath(*relative)
    require(target.resolve().is_relative_to(root.resolve()), 'archive escape')
    return target


def extract_zip(archive, root, prefix):
    root.mkdir()
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            target = member_target(root, member.filename, prefix)
            mode = member.external_attr >> 16
            require((mode & 0o170000) != 0o120000, 'unexpected ZIP symlink')
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst)


def plan_archive_links(actual, expected):
    """Authenticate every link and resolve chains without following host paths."""
    by_path = {row['path']: row for row in actual}
    policy = {row['path']: row for row in expected}
    require(len(by_path) == len(actual) and len(policy) == len(expected), 'duplicate archive link')
    require(set(by_path) == set(policy), 'archive link inventory differs from locked policy')
    for name, row in by_path.items():
        wanted = policy[name]
        require((row['type'], row['target']) == (wanted['type'], wanted['target']),
                'archive link identity mismatch: ' + name)
        require(wanted['action'] in ('create', 'omit'), 'unknown link policy')
    for name, wanted in policy.items():
        if wanted['action'] == 'omit':
            require((name, wanted['type'], wanted['target']) ==
                    ('roms/edk2/EmulatorPkg/Unix/Host/X11IncludeHack', 'symlink', '/opt/X11/include'),
                    'unreviewed omitted archive link: ' + name)
            continue
        require(wanted['type'] == 'symlink', 'unsupported locked hardlink')
        require('\\' not in wanted['target'], 'non-POSIX archive symlink: ' + name)
        # Resolve every intermediate symbolic-link component in the archive graph.
        pending = list(PurePosixPath(posixpath.dirname(name)).parts) + list(PurePosixPath(wanted['target']).parts)
        require(not PurePosixPath(wanted['target']).is_absolute(), 'absolute archive symlink: ' + name)
        resolved = []
        expansions = 0
        while pending:
            part = pending.pop(0)
            if part in ('', '.'):
                continue
            if part == '..':
                require(bool(resolved), 'archive symlink escape: ' + name)
                resolved.pop()
                continue
            resolved.append(part)
            node = '/'.join(resolved)
            if node in policy:
                link = policy[node]
                require(link['action'] == 'create', 'link traverses an omitted external bridge: ' + name)
                require(link['type'] == 'symlink' and not PurePosixPath(link['target']).is_absolute(),
                        'indirect unsafe archive symlink: ' + name)
                expansions += 1
                require(expansions <= len(policy), 'archive symlink cycle: ' + name)
                resolved.pop()
                pending = list(PurePosixPath(link['target']).parts) + pending
    return {row['path']: row['action'] for row in expected}


def extract_tar(archive, root, prefix, link_policy):
    root.mkdir()
    links = []
    with tarfile.open(archive, 'r|xz') as source:
        for member in source:
            target = member_target(root, member.name, prefix)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                target.chmod(member.mode & 0o777)
            elif member.issym() or member.islnk():
                links.append((member, target))
            else:
                raise ValueError('unsupported archive object: ' + member.name)
    actual_links = [{'path': PurePosixPath(member.name).relative_to(prefix).as_posix(),
                     'type': 'symlink' if member.issym() else 'hardlink', 'target': member.linkname}
                    for member, target in links]
    actions = plan_archive_links(actual_links, link_policy)
    omitted = []
    for member, target in links:
        relative = PurePosixPath(member.name).relative_to(prefix).as_posix()
        if actions[relative] == 'omit':
            omitted.append({'path': relative, 'target': member.linkname})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if member.issym():
            require(not Path(member.linkname).is_absolute(), 'absolute archive symlink')
            resolved = (target.parent / member.linkname).resolve()
            require(resolved.is_relative_to(root.resolve()), 'archive symlink escape')
            target.symlink_to(member.linkname)
        else:
            origin = member_target(root, member.linkname, prefix)
            require(origin.is_file(), 'invalid archive hardlink')
            os.link(origin, target)
    return {'archive_links': len(actual_links), 'created_links': len(actual_links) - len(omitted),
            'omitted_external_links': omitted}


def apply_patch(tree, record):
    patch = HERE / record['file']
    require(sha(patch) == record['sha256'], 'distributed patch identity mismatch')
    verify_files(tree, {row['path']: row['before_sha256'] for row in record['files']})
    command = ['git', '-c', 'core.autocrlf=false', 'apply', '--whitespace=nowarn']
    subprocess.run(command + ['--check', str(patch)], cwd=tree, check=True)
    subprocess.run(command + [str(patch)], cwd=tree, check=True)
    return verify_files(tree, {row['path']: row['after_sha256'] for row in record['files']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--rdwing-archive', type=Path)
    parser.add_argument('--qemu-archive', type=Path)
    args = parser.parse_args()
    try:
        workspace = args.workspace.resolve()
        require(not workspace.exists(), 'workspace exists; use a new directory')
        require(not workspace.is_relative_to(HERE.parent), 'keep source/build workspace outside publication repository')
        require(shutil.which('git') is not None, 'Git is required for verified patch application')
        lock_path = HERE / 'model-source-lock.json'
        lock = json.loads(lock_path.read_text(encoding='utf-8'))
        rdwing_archive = archive_file(args.rdwing_archive, args.cache.resolve(), lock['rdwing']['archive'])
        qemu_archive = archive_file(args.qemu_archive, args.cache.resolve(), lock['qemu']['archive'])
        workspace.mkdir(parents=True)
        rdwing, qemu = workspace / 'z8-source', workspace / 'qemu-source'
        extract_zip(rdwing_archive, rdwing, lock['rdwing']['archive_root'])
        verify_files(rdwing, lock['rdwing']['files_before'])
        apply_patch(rdwing, lock['patches']['overlay'])
        verify_files(rdwing, lock['rdwing']['files_after'])
        extraction = extract_tar(qemu_archive, qemu, lock['qemu']['archive_root'], lock['qemu']['archive_links'])
        require((qemu / 'VERSION').read_text().strip() == lock['qemu']['version'], 'QEMU version mismatch')
        # This authenticated upstream helper is source preparation, not firmware or QEMU execution.
        spec = importlib.util.spec_from_file_location('locked_z8_prepare', rdwing / 'qemu/prepare_source.py')
        module = importlib.util.module_from_spec(spec)
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
        module.prepare(qemu)
        apply_patch(qemu, lock['patches']['qemu_core'])
        prepared = verify_files(qemu, lock['qemu']['prepared_files'])
        receipt = {'schema': 'route4-source-preparation-v1', 'source_lock_sha256': sha(lock_path),
                   'rdwing_commit': lock['rdwing']['commit'], 'qemu_version': lock['qemu']['version'],
                   'source_directories': {'rdwing': 'z8-source', 'qemu': 'qemu-source'},
                   'prepared_qemu_files': prepared, 'build_performed': False,
                   'qemu_extraction': extraction,
                   'qemu_or_firmware_execution_performed': False,
                   'preparer_sha256': sha(Path(__file__))}
        (workspace / 'source-preparation.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(receipt, indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
