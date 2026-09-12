#!/usr/bin/env python3
"""Compare the recording executor with an independently frozen body scheduler.

Keep the reference loop unchanged when production scheduling changes. Negative
controls must compile and differ in the full-product oracle, not merely crash.
"""
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from cold import ROOT, HERE, edit, run


def main():
    started = time.monotonic()
    original = (ROOT / 'selfhost/src/check/checker.dawn').read_text()
    reference = (HERE / 'reference-body-scheduler.dawn.txt').read_text()
    variants = [
        ('allocation', 'var cx1 = headers.cx\n  let sigs = headers.sigs',
         'var cx1 = Cx { ..headers.cx, next_id: headers.cx.next_id + 1 }\n  let sigs = headers.sigs'),
        ('constant-visibility', 'executor.constant(state, cx1, d, declared, visible)',
         'executor.constant(state, cx1, d, declared, set.empty())'),
        ('method-tag', 'TFun { ..tf, impl_of: imp_key }', 'TFun { ..tf, impl_of: None }'),
        ('default-tag', 'TFun { ..tf, default_of: Some(t) }', 'TFun { ..tf, default_of: None }'),
        ('diagnostic-order', '(state, ModuleBodies { cx: cx1, functions: fns_out, constants: tconsts,',
         '(state, ModuleBodies { cx: Cx { ..cx1, diags: list.reverse(cx1.diags) }, functions: fns_out, constants: tconsts,'),
    ]
    with tempfile.TemporaryDirectory(prefix='dawn-body-scheduler-') as temp:
        root = Path(temp)
        classes = root / 'classes'
        classes.mkdir()
        subprocess.run(['javac', '--release', '21', '-d', str(classes),
                        str(HERE / 'SemanticSnapshot.java'), str(HERE / 'BodySchedulerSnapshot.java')], check=True)
        oracle = root / 'snapshot.jar'
        subprocess.run(['jar', 'cf', str(oracle), '-C', str(classes), '.'], check=True)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        fixture = root / 'scripts/incremental-semantics-contract'
        (fixture / 'src').mkdir(parents=True)
        shutil.copyfile(HERE / 'dawn.toml', fixture / 'dawn.toml')
        shutil.copyfile(HERE / 'body-scheduler-tests.dawn.txt', fixture / 'src/reference.dawn')
        target = root / 'selfhost/src/check/checker.dawn'
        subjects = [('positive', original)] + [(n, edit(original, a, b)) for n, a, b in variants]
        for name, source in subjects:
            target.write_text(source + '\n' + reference)
            status, output = run('build', '--cp', oracle, fixture, '-o', root / 'subject.jar')
            if status:
                raise RuntimeError(name + ' did not compile\n' + output)
            result = subprocess.run(['java', '-Xss64m', '-Xmx2g', '-cp',
                                     str(oracle) + os.pathsep + str(root / 'subject.jar'),
                                     'contract.BodySchedulerSnapshot'], cwd=ROOT, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            if name == 'positive':
                if result.returncode or 'PASS: frozen body scheduler' not in result.stdout:
                    raise RuntimeError('Positive failed\n' + result.stdout)
            elif not result.returncode or 'FAIL: frozen body scheduler' not in result.stdout:
                raise RuntimeError(name + ' missed its product comparison\n' + result.stdout)
            print('OK: frozen body scheduler ' + name, flush=True)
    print(f'OK: full scheduler products and {len(variants)} compiling controls, {time.monotonic() - started:.2f}s')


if __name__ == '__main__':
    main()
