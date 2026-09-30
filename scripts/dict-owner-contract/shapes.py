#!/usr/bin/env python3
"""Pin dictionary constructor and slot identity with compiling mutants.

Run the actual lowering test in private subjects. A missing dictionary suffix
and a missing slot suffix are separate defects: the former mislinks the
constructor, while the latter can reuse code that reads another class's fields.
Compilation failures do not count as detecting either defect.

The mutation anchors live in mutate.py beside this script, where
mutation-anchor-preflight.py proves them exactly-once before any build; this
script reads them from there and applies them in memory, still refusing a
drifted one before it copies or builds anything.
"""
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
DAWN = os.environ.get('DAWN_BIN', str(ROOT / 'bin/dawn'))
SUBJECT = 'selfhost/src/ir/lower.dawn'
OWNER = 'dictionary constructors and slots keep their argument shape in either request order'


def main():
    started = time.monotonic()
    original = (ROOT / SUBJECT).read_text()
    variants = runpy.run_path(str(Path(__file__).with_name('mutate.py')))['MUTATIONS']
    subjects = [('positive', original)]
    for name, edits in variants.items():
        source = original
        for rel, old, new in edits:
            if rel != SUBJECT or source.count(old) != 1:
                raise RuntimeError(f'{name}: expected one mutation anchor in {SUBJECT}')
            source = source.replace(old, new)
        subjects.append((name, source))
    with tempfile.TemporaryDirectory(prefix='dawn-dictionary-shapes-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        for name, source in subjects:
            (root / SUBJECT).write_text(source)
            result = subprocess.run([DAWN, 'test', str(root / SUBJECT)], cwd=ROOT,
                                    text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=300)
            if name == 'positive':
                valid = result.returncode == 0 and 'test(s) passed' in result.stdout
            else:
                valid = (result.returncode != 0 and re.search(
                    r'^FAIL\s+ir/lower :: ' + re.escape(OWNER) + r'\n\s+assertion failed:',
                    result.stdout, re.M) and not re.search(r'^error:', result.stdout, re.M))
            if not valid:
                raise RuntimeError(f'{name}: did not reach its expected assertion\n{result.stdout}')
            print('OK: dictionary constructor ' + name, flush=True)
    print(f'OK: {len(variants)} compiling dictionary-shape controls, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()
