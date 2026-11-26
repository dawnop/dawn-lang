#!/usr/bin/env python3
"""Keep JVM oracles explicit while the source launcher's default changes.

Each registered selection runs against a launcher whose default is native.
Removing that selection must fail the same capability probe. These probes do
not compile a second compiler or confuse a native subject with its JVM oracle.
The integration controls also drive the real site and copied shell boundaries.
"""

import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / 'scripts/seed-consumers.json'


def run(argv, env, **kwargs):
    return subprocess.run(argv, env=env, capture_output=True, text=True, **kwargs)


def selections(root):
    rows = json.loads((root / 'scripts/seed-consumers.json').read_text())
    for row in rows:
        source = (root / row['path']).read_text()
        pin = row['selection']
        expected = row.get('occurrences', 1)
        if source.count(pin) != expected:
            raise AssertionError(f"{row['path']}: selection must occur {expected} time(s)")
        if row['path'].endswith('.py'):
            nodes = ast.walk(ast.parse(source))
            assert any(ast.get_source_segment(source, node) == pin for node in nodes), (
                row['path'] + ': selection must be Python code, not a comment or string')
        else:
            assert any(pin in line and not line.lstrip().startswith('#')
                       for line in source.splitlines()), row['path'] + ': commented selection'
        yield row, source


def check(root):
    count = 0
    with tempfile.TemporaryDirectory(prefix='seed-consumers-') as temporary:
        work = Path(temporary)
        compiler = work / 'dawn'
        compiler.write_text('#!/bin/sh\n'
                            '[ "${DAWN_SEED_CHAIN:-native}" = jar ] || {\n'
                            ' echo "native default cannot serve JVM capability" >&2; exit 42; }\n'
                            'printf "jar oracle\\n"\n')
        compiler.chmod(0o755)
        env = dict(os.environ, PATH=str(work) + os.pathsep + os.environ['PATH'])
        env.pop('DAWN_SEED_CHAIN', None)
        for row, source in selections(root):
            pin = row['selection']
            # Execute the selection itself, then a capability that the native
            # default refuses. No inherited jar setting may mask a missing pin.
            if row['kind'] == 'shell':
                lines = source.splitlines(keepends=True)
                end = next(i + 1 for i, line in enumerate(lines) if pin in line)
                prefix = ''.join(lines[:end])
                command = ['bash', '-euc', prefix + '\nexec dawn __emit']
                mutant = ['bash', '-euc', prefix.replace(pin, '', 1) + '\nexec dawn __emit']
            elif row['kind'] == 'python':
                lines = source.splitlines(keepends=True)
                end = next(i + 1 for i, line in enumerate(lines) if pin in line)
                prefix = ''.join(lines[:end])
                tail = '\nimport subprocess\nraise SystemExit(subprocess.call(["dawn", "__emit"]))'
                command = [sys.executable, '-c', prefix + tail]
                mutant = [sys.executable, '-c', prefix.replace(pin, '', 1) + tail]
            elif row['kind'] == 'inline':
                assert 'DAWN_SEED_CHAIN=jar' in pin
                command = ['bash', '-euc', 'DAWN_SEED_CHAIN=jar dawn __emit']
                mutant = ['bash', '-euc', 'dawn __emit']
            elif row['kind'] == 'yaml-env':
                assert pin.split(':', 1) == ['DAWN_SEED_CHAIN', ' jar'], pin
                command = ['bash', '-euc', 'DAWN_SEED_CHAIN=jar dawn __emit']
                mutant = ['bash', '-euc', 'dawn __emit']
            elif row['kind'] == 'python-env':
                import re
                assert re.search(r'DAWN_SEED_CHAIN["\x27]?\]?\s*=\s*["\x27]jar["\x27]', pin), pin
                setup = ('import os, subprocess\nstate={"env":dict(os.environ)}\n'
                         'env=dict(os.environ)\nclean=dict(os.environ)\n')
                statement = 'env=' + pin if pin.startswith('dict(') else pin
                selected = 'clean' if pin.startswith('clean[') else 'env'
                command = [sys.executable, '-c',
                           setup + statement + '\nraise SystemExit(subprocess.call(["dawn", "__emit"], '
                           'env=' + selected + '))']
                mutant = ['bash', '-euc', 'dawn __emit']
            else:
                raise AssertionError('unknown selection kind: ' + row['kind'])
            good = run(command, env)
            bad = run(mutant, env)
            assert good.returncode == 0 and good.stdout == 'jar oracle\n', (row['path'], good.stderr)
            assert bad.returncode == 42 and not bad.stdout, row['path'] + ': missing selection survived'
            count += 1
        # Use the actual site helper, including its command substitution, with
        # a native-default launcher. Cache hits must not bypass the stamp leg.
        (work / 'bin').mkdir()
        (work / 'bin/dawn').symlink_to(compiler)
        (work / 'runtime/c').mkdir(parents=True)
        (work / 'runtime/c/input').write_text('runtime')
        helper = root / 'site/dawnc.sh'
        probe = run(['bash', '-euc', '. "$1"; site_dawnc_stamp', '_', str(helper)], env, cwd=work)
        assert probe.returncode == 0 and probe.stdout.startswith('jar oracle/'), probe.stderr
    print(f'OK: {count} JVM consumer selections; {count} native-default removal controls; site stamp boundary')


def prototype_free(root):
    retired = 'scripts/' + 'native-seed-' + 'prototype'
    assert not (root / retired).exists(), 'retired protocol prototype still exists'
    names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).decode().split('\0')
    for name in filter(None, names):
        path = root / name
        if path.is_file() and not path.is_symlink():
            assert retired.encode() not in path.read_bytes(), 'retired prototype reference: ' + name
    print('OK: retired prototype directory and tracked references are absent')


def prototype_control():
    with tempfile.TemporaryDirectory(prefix='prototype-reference-') as temporary:
        root = Path(temporary)
        subprocess.run(['git', '-C', str(root), 'init', '-q'], check=True)
        (root / 'leftover.sh').write_text('# scripts/' + 'native-seed-' + 'prototype/rehearse.py\n')
        subprocess.run(['git', '-C', str(root), 'add', 'leftover.sh'], check=True)
        try:
            prototype_free(root)
        except AssertionError as exc:
            assert 'reference: leftover.sh' in str(exc), str(exc)
        else:
            raise AssertionError('a retired prototype reference survived the guard')
    print('OK: a residual reference is refused even when the prototype directory is absent')


def preflight_controls(root):
    from unittest.mock import patch
    import hashlib
    spec = importlib.util.spec_from_file_location('deploy_preflight', root / 'playground/deploy/preflight.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='deploy-identity-') as temporary:
        work = Path(temporary)
        for name in ('selfhost/src', 'build'):
            (work / name).mkdir(parents=True)
        (work / 'selfhost/src/version.dawn').write_text('pub const VERSION: String = "1.2.3"\n')
        jar = work / 'build/dawn-selfhost.jar'
        native, runner = work / 'compiler', work / 'runner'
        for path in (jar, native, runner):
            path.write_bytes(b'artifact fixture')
        rows = {name: '\tmain\t' + name + '\t(devel)\ts1:' + 'a' * 64 + '\n'
                for name in ('jar', 'native', 'runner', 'stale')}
        def identity(name):
            return 'b1:' + hashlib.sha256(rows[name].encode()).hexdigest()
        def listed(name):
            return 'fixture: dawn 1.2.3\n' + rows[name] + '\tbuild\t' + identity(name) + '\n'
        def emitted(name):
            raw = ('dawn-build-info 1\ntoolchain\tdawn 1.2.3\n' + rows[name]).encode()
            return '#elif defined(__ELF__)\n  ".byte ' + ','.join(map(str, raw)) + '\\n"\n'
        current = {}
        def command(argv):
            argv = list(map(str, argv))
            if argv[0] == sys.executable:
                return str(work / 'portable/selfhost/src/nmain.dawn') + '\n'
            if '__emitc' in argv:
                Path(argv[argv.index('--build-info') + 1]).write_text(emitted('native'))
                return ''
            if argv[1:] == ['--version']:
                if argv[0] == str(native):
                    return f'dawnc 1.2.3 (native) {identity(current.get(str(native), "native"))[:15]}\n'
                return f'dawn 1.2.3 (selfhost) {identity("jar")[:15]}\n'
            assert argv[1:3] == ['version', '-m'], argv
            name = {str(jar): 'jar', 'selfhost': 'jar', str(native): 'native',
                    str(runner): 'runner', 'playground': 'runner'}[argv[-1]]
            return listed(current.get(argv[-1], name))
        with patch.object(module, 'ROOT', work), patch.object(module, 'command', command):
            result = module.verify(native, runner)
            assert {v['build_id'] for v in result['products'].values()} == {identity(n) for n in ('jar', 'native', 'runner')}
            for target, reason in ((str(jar), 'JAR'), (str(native), 'native'), (str(runner), 'runner')):
                current[target] = 'stale'
                try:
                    module.verify(native, runner)
                except ValueError as exc:
                    assert reason.lower() in str(exc).lower() and 'stale' in str(exc), str(exc)
                else:
                    raise AssertionError('accepted stale ' + reason + ' with the same version')
                current.clear()
        try:
            module.listing(listed('native').replace(identity('native'), 'b1:' + '0' * 64), '1.2.3')
        except ValueError:
            pass
        else:
            raise AssertionError('accepted corrupt full build identity')
    print('OK: distinct JAR/native/runner identities; same-version stale products and corrupt manifests refused')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--prototype-only', action='store_true')
    args = parser.parse_args()
    if not args.prototype_only:
        check(args.root.resolve())
        preflight_controls(args.root.resolve())
    prototype_free(args.root.resolve())
    prototype_control()


if __name__ == '__main__':
    main()
