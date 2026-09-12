#!/usr/bin/env python3
"""Keep scheduler recording transparent and reject unowned body entries.

These controls mutate only the recorder, leaving the canonical checker and
the inline assertions intact. Runtime linkage failures are not valid negatives.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    original = (ROOT / 'selfhost/src/check/body_execution.dawn').read_text()
    start = original.index('pub fn record(')
    end = original.index('\ntest ', start)
    implementation = original[:end]
    variants = [
        ('drop-functions', 'if set.has(allowed, k) {', 'if false {'),
        ('drop-constants', 'if set.has(admitted, key) {', 'if false {'),
        ('accept-unowned', 'if set.has(allowed, k) {', 'if true {'),
        ('ignore-source', '&& path_matches {', '&& true {'),
        ('drop-observer-prefix', 'Some(prefix ++ entries)', 'Some(entries)'),
        ('leak-private-log', 'let reads = match before.function_reads {\n    None -> None',
         'let reads = match before.function_reads {\n    None -> after.function_reads'),
        ('drop-write-prefix', 'Some(prefix ++ keys)', 'Some(keys)'),
        ('leak-private-writes', 'let writes = match before.body_writes {\n    None -> None',
         'let writes = match before.body_writes {\n    None -> after.body_writes'),
        ('drop-trace', 'let start = observed(cx)', 'let start = cx'),
    ]
    subjects = [('positive', original)]
    for name, old, new in variants:
        if name == 'drop-trace':
            if implementation.count(old) != 6:
                raise RuntimeError('Expected six recording boundaries')
            changed = implementation.replace(old, new)
        else:
            changed = edit(implementation, old, new)
        subjects.append((name, changed + original[end:]))
    with tempfile.TemporaryDirectory(prefix='dawn-body-recording-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        target = root / 'selfhost/src/check/body_execution.dawn'
        for name, source in subjects:
            target.write_text(source)
            status, output = run('test', target)
            if name == 'positive':
                if status or 'test(s) passed' not in output:
                    raise RuntimeError('Positive failed\n' + output)
            else:
                failure = re.compile(r'^FAIL\s+check/body_execution :: body recording [^\n]+\n\s+assertion failed:', re.M)
                if not status or not failure.search(output) or re.search(r'^error:', output, re.M):
                    raise RuntimeError(name + ' missed its assertion owner\n' + output)
            print('OK: body recording ' + name, flush=True)
    print(f'OK: {len(variants)} compiling body recording controls, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()
