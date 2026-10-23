#!/usr/bin/env python3
"""Compare C views by source identity, preserving the paired oracle's output.

A C-only parent can change ownership. Record each identity and both local
id/parent pairs rather than silently discarding those fields to get equality.
"""
import json
import sys
from pathlib import Path


def read(path):
    calls, outs, gaps = {}, {}, []
    for line in path.read_text().splitlines():
        w = line.split()
        if w[0] == 'call':
            calls[int(w[1])] = (int(w[2]), tuple(w[3:]))
        elif w[0:2] == ['out', 'c']:
            outs[int(w[2])] = ' '.join(w[3:])
    return calls, outs


old, new = map(Path, sys.argv[1:])
for name in (old / 'programs.txt').read_text().splitlines():
    a, ao = read(old / f'{name}.xmap')
    b, bo = read(new / f'{name}.xmap')
    assert (old / f'{name}.c.txt').read_bytes() == (new / f'{name}.c.txt').read_bytes(), name
    ai = {identity: (i, parent) for i, (parent, identity) in a.items()}
    bi = {identity: (i, parent) for i, (parent, identity) in b.items()}
    assert ai.keys() <= bi.keys(), (name, 'paired call missing from C-only')
    rows = []
    for identity, (i, parent) in bi.items():
        prev = ai.get(identity)
        before = None if prev is None else [prev[0], None if prev[1] == -1 else a[prev[1]][1]]
        after = [i, None if parent == -1 else b[parent][1]]
        changed = prev is not None and ao[prev[0]] != bo[i]
        # With the same identity tree, own lines and marks must be byte equal.
        if ai.keys() == bi.keys():
            assert before == after and not changed, (name, identity, before, after)
        rows.append({'identity': identity, 'paired': before, 'c': after, 'ownership_changed': changed})
    print('C-only diff ' + json.dumps({'sample': name, 'paired': len(a), 'c': len(b), 'rows': rows}, separators=(',', ':')))
print('OK: C text byte-identical; every common identity and parent/ownership accounted for')
