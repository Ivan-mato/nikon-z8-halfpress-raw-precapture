# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Regression for falsely accepting a few frames followed by a silent stall."""
from pathlib import Path
import ast

# Exercise the actual pure liveness check without requiring optional RAW codecs.
path = Path(__file__).resolve().parents[1] / 'tools/audit_burst.py'
tree = ast.parse(path.read_text())
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'held_progress')
scope = {}
exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), scope)
check = scope['held_progress']
def samples(times):
    return [dict(virtual_seconds=t, jobs=i+1) for i, t in enumerate(times)]
jobs = lambda r: r['jobs']
assert check(samples(range(1, 8)), 0, 8, jobs, 2)['passed']
assert not check(samples([.5, 1, 1.5]), 0, 8, jobs, 2)['passed']
assert not check(samples([5, 6, 7]), 0, 8, jobs, 2)['passed']
assert not check(samples([1, 2, 6, 7]), 0, 8, jobs, 2)['passed']
assert not check([], 0, 8, jobs, 2)['passed']
assert not check([], None, None, jobs, 2)['passed']
assert not check([dict(virtual_seconds=1,jobs=2),dict(virtual_seconds=2,jobs=1)], 0, 3, jobs, 2)['passed']
print('PASS burst liveness rejects early/mid/late stalls and counter regression')
