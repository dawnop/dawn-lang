#!/usr/bin/env python3
"""Exercise real scalar executor admission with compiling negative controls.

Unsupported bodies remain cold. These controls must reach the replay assertions;
parser, type-checker and JVM linkage failures do not establish their coverage.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    path = 'selfhost/src/check/scalar_replay.dawn'
    original = (ROOT / path).read_text()
    variants = [
        ('disable-replay', 'Some(p) -> candidate(p, cx, d, sig)', 'Some(p) -> None'),
        ('source-owner', 'not snapshot_matches(old, old_source)', 'false'),
        ('observer-mode', 'Some(_) -> moved.function_reads', 'Some(_) -> None'),
        ('current-isolation', 'isolated: cx.frame.isolated', 'isolated: false'),
        ('current-test-mode', 'in_test: cx.in_test', 'in_test: false'),
        ('current-handler-cell', 'take_cell: cx.take_cell', 'take_cell: None'),
        ('current-constant-cutoff', 'const_cutoff: cx.const_cutoff', 'const_cutoff: None'),
        ('current-loop-jumps', 'loop_jumps: cx.loop_jumps', 'loop_jumps: set.empty()'),
        ('unpaired-body',
         'if not scalar_shape.same(prior.body, d.body, bound) { return None }',
         'if false { return None }'),
        ('alias-shadowed-binders', 'if map.has(cx.module_aliases, name) { return None }',
         'if false { return None }'),
        # The record-time half of admission. Its verdicts are what the replay
        # path stops recomputing, so each one needs its own control.
        ('recorded-binders', 'let names = scalar_shape.binders(prior.body, prior_sig.param_names)?',
         'let names: List[String] = []'),
        ('header-only-interval',
         'let ids = allocation.reserved_plan(prepared.reserver, key,\n'
         '    p.allocation_start, p.allocation_count, cx.next_id, prior_sig, sig, [])?',
         'let ids = allocation.reserver_ids(prepared.reserver)'),
    ]
    with tempfile.TemporaryDirectory(prefix='dawn-scalar-replay-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        for name, source in [('positive', original)] + [
                (name, edit(original, old, new)) for name, old, new in variants]:
            (root / path).write_text(source)
            status, output = run('test', root / path)
            if name == 'positive':
                if status or 'test(s) passed' not in output:
                    raise RuntimeError('Positive failed\n' + output)
            elif not status or not re.search(
                    r'^FAIL\s+check/scalar_replay :: scalar replay [^\n]*\n\s+assertion failed:',
                    output, re.M) or re.search(r'^error:', output, re.M):
                raise RuntimeError(name + ' missed its assertion owner\n' + output)
            print('OK: scalar replay ' + name, flush=True)
    print(f'OK: {len(variants)} compiling scalar replay controls, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()
