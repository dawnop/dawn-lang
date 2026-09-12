#!/usr/bin/env python3
"""Require the real body scheduler to consume every executor result.

Private compiling mutations bypass each role or discard its threaded state.
Assertions must fail in the ordered scheduler fixture, not during compilation
or through an unrelated exception. The frozen-loop gate owns cold equivalence.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    original = (ROOT / 'selfhost/src/check/checker.dawn').read_text()
    owner = 'body executor threads current state through every scheduled role'
    calls = [
        ('inferred', 'executor.inferred_body(state, cx1, d, sigs[idx])',
         '{ let (next, _, tree) = check_fn_inferred(cx1, d, sigs[idx])\n (state, next, tree) }'),
        ('constant', 'executor.constant(state, cx1, d, declared, visible)',
         '{ let (next, tree) = check_const_init(cx1, d, declared, visible)\n (state, next, tree) }'),
        ('function', 'executor.function(state, cx1, d, sigs[i])',
         '{ let (next, tree) = check_fn(cx1, d, sigs[i])\n (state, next, tree) }'),
        ('method', 'executor.method(state, cx1, imd.trait_name, imd.subject, strip_param_defaults(me), ms)',
         '{ let (next, tree) = check_fn(cx1, strip_param_defaults(me), ms)\n (state, next, tree) }'),
        ('default', 'executor.default_body(state, cx1, t, me, s2, b)',
         '{ let (next, tree) = check_trait_default(cx1, me, s2, b)\n (state, next, tree) }'),
        ('test', 'executor.test_body(state, cx1, t.name, t.body)',
         '{ let (next, tree) = check_test(cx1, t.name, t.body)\n (state, next, tree) }'),
    ]
    subjects = [('positive', original)]
    for role, call, bypass in calls:
        subjects.append(('bypass-' + role, edit(original, call, bypass)))
        subjects.append(('reset-state-' + role, edit(original, call, call.replace('(state,', '(initial,'))))
    subjects.append(('stale-inferred-context', edit(original, calls[0][1], calls[0][1].replace('cx1,', 'headers.cx,'))))
    with tempfile.TemporaryDirectory(prefix='dawn-body-executor-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        target = root / 'selfhost/src/check/checker.dawn'
        for name, source in subjects:
            target.write_text(source)
            status, output = run('test', target)
            if name == 'positive':
                if status or 'test(s) passed' not in output:
                    raise RuntimeError('Positive failed\n' + output)
            else:
                failure = re.compile(r'^FAIL\s+check/checker :: ' + re.escape(owner) +
                                     r'\n\s+assertion failed:', re.M)
                if not status or not failure.search(output) or re.search(r'^error:', output, re.M):
                    raise RuntimeError(name + ' missed its assertion owner\n' + output)
            print('OK: body executor ' + name, flush=True)
    print(f'OK: {len(subjects) - 1} compiling body executor controls, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()
