#!/usr/bin/env python3
"""Each refusal of tileir/origin must be one a test would notice.

    python3 scripts/tile-origin-shadow/mutants.py

Every mutant removes one refusal (a stale or missing source revision, a
declaration of another length, a span that is no syntax node, a missing or later
parent, an unknown boundary) or folds the two executions of one helper into one
instance. The package's own tests must then fail; a mutant that leaves them green
means the refusal has no negative control and the run fails.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = 'src/origin.dawn'

# (label, text to find, replacement, the test that has to go red)
MUTANTS = [
    ('stale revision accepted', 'else if u.revision != recorded {', 'else if false {', 'stale, missing or unknown source revision'),
    ('missing recorded revision accepted', 'if recorded == "" { return Err(', 'if false { return Err(', 'stale, missing or unknown source revision'),
    ('unit without revision accepted', 'if u.revision == "" {', 'if false {', 'stale, missing or unknown source revision'),
    ('definition length unchecked', 'if d.role == "function" && not (', 'if false && not (', 'another length'),
    ('definition outside the unit accepted', 'if d.start < 0 || d.end < d.start || lo + d.end > hi {', 'if false {', 'another length'),
    ('non syntax span accepted', 'if not set.has(u.spans, (lo + s.start, lo + s.end)) {', 'if false {', 'another length'),
    ('missing parent accepted', 'if row > 0 && r.parent == -1 {', 'if false {', 'missing or later parent'),
    ('later parent accepted', 'if r.parent < -1 || r.parent >= row {', 'if r.parent < -1 {', 'missing or later parent'),
    ('unknown boundary accepted', 'if r.boundary != Known {', 'if false {', 'missing or later parent'),
    ('nameless row accepted', 'if row > 0 && r.site == None && r.definition == None {', 'if false {', 'missing or later parent'),
    ('two helper executions folded into one instance',
     'key = r.key, parent = above', 'key = InvocationKey { scope = 1, epoch = 1, instance = 0 }, parent = above',
     'two calls of one helper'),
]


def run(copy):
    return subprocess.run([str(ROOT/'bin/dawn'), 'test', str(copy)], capture_output=True, text=True, cwd=ROOT)


def main():
    source = (ROOT/'packages/tileir'/ORIGIN).read_text()
    failed = False
    with tempfile.TemporaryDirectory(prefix='origin-mutants.') as work:
        base = Path(work)/'tileir'
        shutil.copytree(ROOT/'packages/tileir', base)
        green = run(base)
        if green.returncode:
            sys.exit('the unmutated package does not pass its own tests:\n' + green.stdout[-2000:] + green.stderr[-2000:])
        for label, old, new, test in MUTANTS:
            if source.count(old) != 1:
                sys.exit(f'{label}: the text to mutate occurs {source.count(old)} times')
            (base/ORIGIN).write_text(source.replace(old, new))
            result = run(base)
            red = [l for l in result.stdout.splitlines() if l.startswith('FAIL') and 'origin ::' in l and test in l]
            if result.returncode == 0 or not red:
                failed = True
                print(f'ESCAPED {label}: no origin test named `{test}` went red')
            else:
                print(f'KILLED  {label}: {red[0].strip()}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
