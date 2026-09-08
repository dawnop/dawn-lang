#!/usr/bin/env python3
"""Require canonical witness dependencies and candidate recomputation.

Each mutation must compile and fail its specific assertion owner. The private
subject preserves the workspace; this gate does not enable body caching.
"""
import re
import shutil
import tempfile
from pathlib import Path

from cold import ROOT, edit, run


def main():
    source = (ROOT / 'selfhost/src/check/checker.dawn').read_text()
    owner = 'witness revalidation recomputes candidate facts and refuses unknown queries'
    structural = 'witness reads preserve nominal recursion guards and substituted first gaps'
    variants = [
        ('accept-changed-answer', 'Some(observed.function_reads == Some([fact]))', 'Some(true)', owner),
        ('accept-missing-trait', 'if not map.has(initial.traits, id) { return Some(false) }',
         'if not map.has(initial.traits, id) { return Some(true) }', owner),
        ('ignore-candidate-owner', 'let initial = Cx { ..candidate, function_reads: Some([]) }',
         'let initial = Cx { ..candidate, owner_class: Some("m"), function_reads: Some([]) }',
         'unification revalidation checks candidate opacity and complete answers'),
        ('drop-recursion-guard-context', 'if set.has(seen, a.name) { return (cx, None) }',
         'if set.has(seen, a.name) { return (initial, None) }', structural),
        ('ignore-substituted-field', 'structural_gap_read(cx, tid, subst(f.ty, m, em), seen2)',
         'structural_gap_read(cx, tid, TyInt, seen2)', structural),
        ('drop-constructor-count-context', 'cx = count_cx', 'cx = cx', structural),
    ]
    subjects = [('positive', source, None)] + [
        (name, edit(source, old, new), test) for name, old, new, test in variants
    ]
    with tempfile.TemporaryDirectory(prefix='dawn-witness-revalidation-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        target = root / 'selfhost/src/check/checker.dawn'
        for name, text, test in subjects:
            target.write_text(text)
            status, output = run('test', target)
            if test is None:
                if status or 'test(s) passed' not in output:
                    raise RuntimeError('Positive failed\n' + output)
            else:
                failure = re.compile(r'^FAIL\s+check/checker :: ' + re.escape(test) +
                                     r'\n\s+assertion failed:', re.M)
                if not status or not failure.search(output) or re.search(r'^error:', output, re.M):
                    raise RuntimeError(name + ' did not compile and reach its owner\n' + output)
            print('OK: witness revalidation ' + name, flush=True)


if __name__ == '__main__':
    main()
