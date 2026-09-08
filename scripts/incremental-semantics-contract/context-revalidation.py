#!/usr/bin/env python3
"""Prevent candidate validation from silently skipping a supported query.

Each private subject changes only the revalidator, leaving canonical query
helpers and the fixture capture intact. Negatives must compile and reach a
named assertion, never merely crash on a removed declaration.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    original = (ROOT / 'selfhost/src/check/cx.dawn').read_text()
    start = original.index('pub fn revalidate_context_read(')
    end = original.index('\ntest ', start)
    body = original[start:end]
    owner = 'context revalidation recomputes every supported query family'
    variants = []
    arms = re.findall(r'(semantic_reads\.\w+\([^\n]+ -> \{ let \(next, _\) = ([a-z_]+)\([^\n]+\n      next \})', body)
    if len(arms) != 20:
        raise RuntimeError(f'Expected 20 canonical dispatch arms, found {len(arms)}')
    for anchor, helper in arms:
        variants.append(('discard-' + helper, anchor, anchor.replace('\n      next }', '\n      initial }'), owner))
    variants.extend([
        ('accept-changed', 'Some(observed.function_reads == Some([fact]))', 'Some(true)', owner),
        ('accept-removed-nominal', 'if not map.has(initial.adts, id) { return Some(false) }',
         'if not map.has(initial.adts, id) { return Some(true) }',
         'context revalidation rejects removed nominal IDs and invalid slots'),
        ('accept-invalid-slot', 'if slot < 0 || slot >= len(info.ctors) { return Some(false) }',
         'if slot < 0 || slot >= len(info.ctors) { return Some(true) }',
         'context revalidation rejects removed nominal IDs and invalid slots'),
        ('accept-unsupported', '_ -> return None', '_ -> return Some(true)',
         'context revalidation rejects changed misses and scope answers'),
    ])
    subjects = [('positive', 'cx', original, None)] + [
        (name, 'cx', original[:start] + edit(body, old, new) + original[end:], test)
        for name, old, new, test in variants
    ]
    checker = (ROOT / 'selfhost/src/check/checker.dawn').read_text()
    dispatch_start = checker.index('pub fn revalidate_read(')
    dispatch_end = checker.index('pub fn revalidate_witness_read(', dispatch_start)
    dispatch = checker[dispatch_start:dispatch_end]
    dispatch_variants = [
        ('discard-context-result', 'None -> revalidate_context_read(candidate, fact)', 'None -> None'),
        ('accept-witness-refusal', 'Some(answer) -> Some(answer)', 'Some(answer) -> Some(true)'),
        ('accept-unknown-query', 'None -> revalidate_context_read(candidate, fact)', 'None -> Some(true)'),
    ]
    subjects.append(('dispatch-positive', 'checker', checker, None))
    subjects.extend((name, 'checker', checker[:dispatch_start] + edit(dispatch, old, new) + checker[dispatch_end:],
                     'candidate revalidation dispatches queries without accepting unknown facts')
                    for name, old, new in dispatch_variants)
    with tempfile.TemporaryDirectory(prefix='dawn-context-revalidation-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        for name, module, text, test in subjects:
            (root / 'selfhost/src/check/cx.dawn').write_text(original)
            (root / 'selfhost/src/check/checker.dawn').write_text(checker)
            target = root / f'selfhost/src/check/{module}.dawn'
            target.write_text(text)
            status, output = run('test', target)
            if test is None:
                if status or 'test(s) passed' not in output:
                    raise RuntimeError('Positive failed\n' + output)
            else:
                failure = re.compile(r'^FAIL\s+check/' + module + r' :: ' + re.escape(test) +
                                     r'\n\s+assertion failed:', re.M)
                if not status or not failure.search(output) or re.search(r'^error:', output, re.M):
                    raise RuntimeError(name + ' missed its assertion owner\n' + output)
            print('OK: context revalidation ' + name, flush=True)
    print(f'OK: {len(variants) + len(dispatch_variants)} compiling context controls, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()
