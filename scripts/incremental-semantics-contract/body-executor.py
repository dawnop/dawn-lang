#!/usr/bin/env python3
"""Require the real body scheduler to consume every executor result.

Private compiling mutations bypass each role or discard its threaded state.
Assertions must fail in the ordered scheduler fixture, not during compilation
or through an unrelated exception. The frozen-loop gate owns cold equivalence.
"""
import re
import runpy
import shutil
import tempfile
import time
from pathlib import Path

from cold import HERE, ROOT, apply, owned, run


def main():
    started = time.monotonic()
    original = (ROOT / 'selfhost/src/check/checker.dawn').read_text()
    owner = 'body executor threads current state through every scheduled role'
    # The controls are the body-executor group of mutate.py, where the
    # preflight proves their anchors before any build: each role bypassed,
    # each role reset to the module's initial state, and the inferred
    # groups entered with the header context.
    group = owned(runpy.run_path(str(HERE / 'mutate.py'))['MUTATIONS'], 'body-executor')
    subjects = [('positive', original)] + [
        (name, apply(original, edits, 'selfhost/src/check/checker.dawn')) for name, edits in group.items()]
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
