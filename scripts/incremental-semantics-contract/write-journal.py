#!/usr/bin/env python3
"""Require actual table writers and journal replay to retain every key.

The strict extractor remains independent of the journal. Its comparison fixture
updates existing keys, so unchanged table sizes cannot conceal a missing write.
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
                 for name in ('cx', 'write_journal', 'body_product')}
    variants = [
        ('symbol-owner', 'cx', 'write_journal.observe(cx.body_writes, write_journal.SymbolKey(id))', 'cx.body_writes'),
        ('signature-owner', 'cx', 'write_journal.observe(cx.body_writes, write_journal.SignatureKey(name))', 'cx.body_writes'),
        ('alias-owner', 'cx', 'write_journal.observe(cx.body_writes, write_journal.AliasKey(name))', 'cx.body_writes'),
        ('bounds-owner', 'cx', 'write_journal.observe(cx.body_writes, write_journal.BoundsKey(id))', 'cx.body_writes'),
        ('replay-journal', 'body_product', 'write_journal.append(current.body_writes, product.body_writes)?', 'current.body_writes'),
        ('product-projection', 'body_product',
         'write_journal.project(p.body_writes, id => relocate.local_id(v.ids, id), id => relocate.type_var(v.ids, id))?',
         'p.body_writes'),
        ('symbol-domain', 'write_journal', 'SymbolKey(local(id)?)', 'SymbolKey(binder(id)?)'),
        ('bounds-domain', 'write_journal', 'BoundsKey(binder(id)?)', 'BoundsKey(local(id)?)'),
    ]
    with tempfile.TemporaryDirectory(prefix='dawn-write-journal-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        for name, module, old, new in [('positive', None, None, None), *variants]:
            for owner, source in originals.items():
                (root / f'selfhost/src/check/{owner}.dawn').write_text(source)
            if module:
                (root / f'selfhost/src/check/{module}.dawn').write_text(edit(originals[module], old, new))
            status, output = run('test', root / 'selfhost/src/check/body_execution.dawn')
            if name == 'positive':
                if status or 'test(s) passed' not in output:
                    raise RuntimeError('Positive failed\n' + output)
            else:
                failure = re.compile(r'^FAIL\s+check/(?:body_product|write_journal) :: (?:[^\n]*journal[^\n]*|body product constants project[^\n]*)\n\s+assertion failed:', re.M)
                if not status or not failure.search(output) or re.search(r'^error:', output, re.M):
                    raise RuntimeError(name + ' missed its assertion owner\n' + output)
            print('OK: write journal ' + name, flush=True)
    print(f'OK: {len(variants)} compiling write-journal controls, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()
