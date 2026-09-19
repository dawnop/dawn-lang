#!/usr/bin/env python3
"""Pin dictionary constructor and slot identity with compiling mutants.

Run the actual lowering test in private subjects. A missing dictionary suffix
and a missing slot suffix are separate defects: the former mislinks the
constructor, while the latter can reuse code that reads another class's fields.
Compilation failures do not count as detecting either defect.
"""
import os
from pathlib import Path
import re
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
    variants = [
        ('dictionary-shape', 'let key = dict_key(tid, subject) ++ dict_shape_suffix(nargs)',
         'let key = dict_key(tid, subject)'),
        ('constructor-arity', 'nargs: nargs,', 'nargs: 0,'),
    ]
    for kind in ('bridge', 'prim'):
        old = ('let name = "' + kind + '$" ++ to_string(tid) ++ "$" ++ ty_key_inst(subject) ++ "$" ++ method ++\n'
               '    dict_shape_suffix(if param { len(goals) } else { 0 })')
        variants.append((kind + '-shape', old, old.split(' ++\n')[0]))
    subjects = [('positive', original)]
    for name, old, new in variants:
        if original.count(old) != 1:
            raise RuntimeError(f'{name}: expected one mutation anchor in {SUBJECT}')
        subjects.append((name, original.replace(old, new)))
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
