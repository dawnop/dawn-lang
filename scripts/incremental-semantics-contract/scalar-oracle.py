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

from cold import ROOT, HERE, edit, install_probe, run


def main():
    started = time.monotonic()
    checker = (ROOT / 'selfhost/src/check/checker.dawn').read_text()
    for name in ('check_fn', 'check_fn_inferred', 'check_const_init', 'check_trait_default', 'check_test'):
        pattern = r'(pub\(pkg\) fn ' + name + r'\([^{}]*?!io = \{\n)'
        checker, count = re.subn(pattern, r'\1  ScalarReplaySnapshot.enter()\n', checker)
        if count != 1:
            raise RuntimeError('Canonical entry anchor drifted: ' + name)
    checker = 'use java "contract.ScalarReplaySnapshot"\n' + checker
    original = (ROOT / 'selfhost/src/check/scalar_replay.dawn').read_text()
    variants = [
        ('disguised-cold',
         'Some(after) -> (reused(stepped), after, product.tree)\n'
         '          None -> cold.function(rejected(stepped), cx, d, sig)',
         'Some(after) -> {\n            let (ignored, checked, tree) = cold.function(stepped, cx, d, sig)\n'
         '            (reused(stepped), checked, tree)\n          }\n'
         '          None -> cold.function(rejected(stepped), cx, d, sig)'),
        # The inferred executor has a separate publication exit. Keep these
        # explicit-function controls at the entry this fixture actually uses.
        ('lost-current-symbols',
         'Some(after) -> (reused(stepped), after, product.tree)\n'
         '          None -> cold.function(rejected(stepped), cx, d, sig)',
         'Some(after) -> (reused(stepped), Cx { ..after, syms: map.empty() }, product.tree)\n'
         '          None -> cold.function(rejected(stepped), cx, d, sig)'),
        # `stale-source` stood here and turned the projection off, leaving the
        # recorded product where the projected one belongs. A product is
        # coordinate-free now -- every reference in it is the same integer in
        # the candidate revision -- so on an admitted body the projection is
        # the identity and the control cannot be told from production (K5).
        # Its two halves are still owned: the rebuilt read log by
        # `observer-mode` below, and the refusals by `header-only-admission`
        # and `changed-declaration-text` in `scalar-replay.py`.
        # `header-only-ids` handed the view the header relocation instead of
        # the body one. Both are `relocate.new()` now -- a relocation carries
        # no fields at all, because a binder is `identity.pack` of its
        # declaration and its slot -- so the two are the same value and the
        # control is the identity (K5). What the admission it came from still
        # decides is held by `header-only-admission` in `scalar-replay.py`.
        ('missing-local-symbols', 'symbols: saved.symbols,', 'symbols: map.empty(),'),
        ('lost-local-journal', 'Some(_) -> moved.body_writes',
         'Some(_) -> Some([])'),
        # The declaration's own bytes. This is the whole pairing of the two
        # bodies now, and the control that owns admission on the source side.
        ('changed-declaration-text',
         'if not source_projection.same_text(prepared.old_tokens, prepared.tokens,\n'
         '    prior.lo, prior.hi, d.lo, d.hi) { return None }',
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
        fixture = install_probe(root, {'reference': (HERE / 'scalar-oracle.dawn.txt').read_text()})
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
                                     'changed-declaration-text')
                         else 'FAIL: scalar full product')
                if not result.returncode or owner not in result.stdout:
                    raise RuntimeError(name + ' missed independent oracle\n' + result.stdout)
            print('OK: scalar oracle ' + name, flush=True)
    print(f'OK: 34 complete replay products and {len(variants)} compiling controls, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()
