#!/usr/bin/env python3
"""Independently observe actual execution and every scalar replay product field.

Instrument a private canonical checker, never production source or reported
executor counts. A disguised cold execution must fail even when its output and
claimed cache hits match. The reflection oracle does not use generated Dawn Eq.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from cold import ROOT, HERE, edit, run


def main():
    started = time.monotonic()
    checker = (ROOT / 'selfhost/src/check/checker.dawn').read_text()
    for name in ('check_fn', 'check_fn_inferred', 'check_const_init', 'check_trait_default', 'check_test'):
        pattern = r'(pub fn ' + name + r'\([^{}]*?!io = \{\n)'
        checker, count = re.subn(pattern, r'\1  ScalarReplaySnapshot.enter()\n', checker)
        if count != 1:
            raise RuntimeError('Canonical entry anchor drifted: ' + name)
    checker = 'use java "contract.ScalarReplaySnapshot"\n' + checker
    original = (ROOT / 'selfhost/src/check/scalar_replay.dawn').read_text()
    variants = [
        ('disguised-cold',
         'Some(after) -> (Counts { ..count, reused: count.reused + 1 }, after, product.tree)',
         'Some(after) -> {\n            let (ignored, checked, tree) = cold.function(count, cx, d, sig)\n'
         '            (Counts { ..count, reused: count.reused + 1 }, checked, tree)\n          }'),
        ('lost-current-symbols', '}, after, product.tree)',
         '}, Cx { ..after, syms: map.empty() }, product.tree)'),
        ('stale-source', 'let moved = body_product.project(view, p, cx.next_id)?',
         'let moved = BodyProduct { ..p, allocation_start: cx.next_id }'),
        ('header-only-ids', 'let view = View { ids: plan.ids,',
         'let view = View { ids: prepared.ids,'),
        ('missing-local-symbols', 'symbols: symbols, assertion:',
         'symbols: map.empty(), assertion:'),
        ('lost-local-journal', 'Some(_) -> moved.body_writes',
         'Some(_) -> Some([])'),
        ('unpaired-body',
         'if not scalar_shape.same(prior.body, d.body, set.from(prior_sig.param_names)) { return None }',
         'if false { return None }'),
    ]
    with tempfile.TemporaryDirectory(prefix='dawn-scalar-oracle-') as temp:
        root = Path(temp)
        classes = root / 'classes'
        classes.mkdir()
        subprocess.run(['javac', '--release', '21', '-d', str(classes),
                        str(HERE / 'SemanticSnapshot.java'), str(HERE / 'ScalarReplaySnapshot.java')], check=True)
        oracle = root / 'snapshot.jar'
        subprocess.run(['jar', 'cf', str(oracle), '-C', str(classes), '.'], check=True)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        (root / 'selfhost/src/check/checker.dawn').write_text(checker)
        fixture = root / 'scripts/incremental-semantics-contract'
        (fixture / 'src').mkdir(parents=True)
        shutil.copyfile(HERE / 'dawn.toml', fixture / 'dawn.toml')
        shutil.copyfile(HERE / 'scalar-oracle.dawn.txt', fixture / 'src/reference.dawn')
        for name, source in [('positive', original)] + [
                (name, edit(original, old, new)) for name, old, new in variants]:
            (root / 'selfhost/src/check/scalar_replay.dawn').write_text(source)
            status, output = run('build', '--cp', oracle, fixture, '-o', root / 'subject.jar')
            if status:
                raise RuntimeError(name + ' failed to compile\n' + output)
            result = subprocess.run(['java', '-Xss64m', '-Xmx2g', '-cp',
                                     str(oracle) + os.pathsep + str(root / 'subject.jar'),
                                     'contract.ScalarReplaySnapshot'], cwd=ROOT, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            if name == 'positive':
                if result.returncode or 'PASS: scalar full products' not in result.stdout:
                    raise RuntimeError('Positive failed\n' + result.stdout)
            else:
                owner = ('FAIL: scalar independent execution count'
                         if name in ('disguised-cold', 'header-only-ids', 'missing-local-symbols',
                                     'unpaired-body')
                         else 'FAIL: scalar full product')
                if not result.returncode or owner not in result.stdout:
                    raise RuntimeError(name + ' missed independent oracle\n' + result.stdout)
            print('OK: scalar oracle ' + name, flush=True)
    print(f'OK: 32 complete replay products and {len(variants)} compiling controls, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()
