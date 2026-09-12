#!/usr/bin/env python3
"""Reject compiling bypasses at canonical body writer call sites.

The injected fixture executes all six real scheduler roles and compares journal
replay with both the strict extractor and the actual resulting tables. Explicit
evidence/dictionary event checks cover repeated and unchanged writes too.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    originals = {name: (ROOT / f'selfhost/src/check/{name}.dawn').read_text()
                 for name in ('checker', 'cx', 'body_execution')}
    fixture = (Path(__file__).with_name('journal-consumers.dawn.txt')).read_text()
    variants = [
        ('declare', 'checker', 'var cx3 = write_symbol(cx2, id, sym)',
         'var cx3 = Cx { ..cx2, syms: map.insert(cx2.syms, id, sym) }'),
        ('evidence-update', 'checker', 'write_symbol(cx1, sid, Sym { ..sym, ev_of: Some(key) })',
         'Cx { ..cx1, syms: map.insert(cx1.syms, sid, Sym { ..sym, ev_of: Some(key) }) }'),
        ('dictionary', 'checker', 'cx1 = write_symbol(Cx {\n            ..cx2,',
         'cx1 = Cx { ..write_symbol(Cx {\n            ..cx2,'),
        ('bounds', 'checker', 'entry = write_bounds(entry, tvid, bounds_of(s, ti))',
         'entry = Cx { ..entry, current_tparam_bounds: map.insert(entry.current_tparam_bounds, tvid, bounds_of(s, ti)) }'),
        ('inferred-signature', 'checker', 'cx3 = write_signature(cx3, d.name, sealed)',
         'cx3 = Cx { ..cx3, fns: map.insert(cx3.fns, d.name, sealed) }'),
        ('lazy-alias', 'cx', 'cx3 = write_alias(cx3, al.name, t)',
         'cx3 = Cx { ..cx3, alias_resolved: map.insert(cx3.alias_resolved, al.name, t) }'),
    ]
    with tempfile.TemporaryDirectory(prefix='dawn-journal-consumers-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        for name, module, old, new in [('positive', None, None, None), *variants]:
            for owner, source in originals.items():
                if owner == 'body_execution':
                    source = 'use check/tast as journal_tast\n' + source + '\n' + fixture
                (root / f'selfhost/src/check/{owner}.dawn').write_text(source)
            if module:
                source = edit(originals[module], old, new)
                if name == 'dictionary':
                    source = edit(source, '}, sid, sym)\n', '}, sid, sym), body_writes: cx2.body_writes }\n')
                (root / f'selfhost/src/check/{module}.dawn').write_text(source)
            status, output = run('test', root / 'selfhost/src/check/body_execution.dawn')
            if name == 'positive':
                if status or 'test(s) passed' not in output:
                    raise RuntimeError('Positive failed\n' + output)
            elif not status or not re.search(r'^FAIL\s+check/body_execution :: journal consumers [^\n]*\n\s+assertion failed:', output, re.M) or re.search(r'^error:', output, re.M):
                raise RuntimeError(name + ' missed its assertion owner\n' + output)
            print('OK: journal consumer ' + name, flush=True)
    print(f'OK: {len(variants)} compiling consumer controls, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()
