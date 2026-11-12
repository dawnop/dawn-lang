#!/usr/bin/env python3
"""Explicit final-input qualification. Never called by the push light gate."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

from native_seed import cold, contract as c

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'verify'))
    parser.add_argument('--commit', required=True, help='full final source commit')
    parser.add_argument('--reason', choices=('final-inputs', 'initial-seed', 'seed-promotion'))
    parser.add_argument('--out', type=Path, required=True)
    for name in ('seed', 'seed-tree', 'toolchain', 'java21', 'java26', 'seed-cache'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    try:
        c.oid(args.commit, 'qualification source')
        c.require(c.git(ROOT, 'rev-parse', 'HEAD').decode().strip() == args.commit,
                  'qualification-input', 'entry checkout must be the requested final commit')
        implementation = c.regular_bytes(Path(__file__))
        c.require(c.git(ROOT, 'show', args.commit + ':scripts/native-seed-qualify.py') == implementation,
                  'qualification-input', 'qualification entry differs from the committed implementation')
        out = args.out.absolute()
        seed_cli = [sys.executable, '-B', str(ROOT / 'scripts/native-seed.py')]
        k4 = [sys.executable, '-B', str(ROOT / 'scripts/native-seed-k4-test.py'), '--repo', str(ROOT)]
        common = ['--repo', str(ROOT)]
        lock = ROOT / 'scripts/native-seed-candidate-v0.104.0.json'
        if args.command == 'run':
            c.require(args.reason and all((args.seed, args.seed_tree, args.toolchain,
                      args.java21, args.java26, args.seed_cache)), 'arguments',
                      'explicit reason, seed, paired tree, toolchain, JDKs and JVM seed cache required')
            cold.new_directory(out)
            commands = [
                ('capture', seed_cli + ['capture', *common, '--commit', args.commit, '--lock', str(lock),
                                       '--out', str(out / 'capture')]),
                ('cold', seed_cli + ['cold-run', *common, '--lock', str(lock),
                    '--receipt', str(out / 'capture/inputs.json'), '--source', str(out / 'capture/source'),
                    '--seed', str(args.seed.absolute()), '--seed-tree', str(args.seed_tree.absolute()),
                    '--toolchain', str(args.toolchain.absolute()), '--out', str(out / 'cold')]),
                ('fixtures', k4 + ['fixtures', '--out', str(out / 'fixtures')]),
                ('real', k4 + ['real-controls', '--cold', str(out / 'cold'), '--out', str(out / 'real')]),
                ('transactions', k4 + ['transactions', '--cold', str(out / 'cold'), '--out', str(out / 'transactions')]),
                ('jvm', k4 + ['jvm-chain', '--java', str(args.java21.absolute()),
                    '--java26', str(args.java26.absolute()), '--seed-cache', str(args.seed_cache.absolute()),
                    '--commit', args.commit, '--out', str(out / 'jvm')]),
                ('dual', k4 + ['dual', '--cold', str(out / 'cold'), '--java', str(args.java21.absolute()),
                               '--jar', str(out / 'jvm/jdk-21.jar'), '--out', str(out / 'dual')]),
                ('native-fixpoint', [str(out / 'jvm/source-21/scripts/native-fixpoint.sh')]),
                ('native-cli-diff', ['env', 'DAWNC_BIN=' + str(out / 'cold/root-1/B/dawnc'),
                                     str(out / 'jvm/source-21/scripts/native-cli-diff.sh')]),
                ('seal', k4 + ['seal', '--out', str(out)]),
                ('structure', [sys.executable, '-B', str(ROOT / 'scripts/native-seed-light.py'),
                    '--receipt', str(out / 'cold/inputs.json'), '--commit', args.commit,
                    '--cold-receipt', str(out / 'cold/receipt.json'), '--package-receipt', str(out / 'receipt.json')])]
            c.atomic_json(out / 'request.json', {'schema': 1, 'kind': 'native-qualification-request',
                          'commit': args.commit, 'reason': args.reason,
                          'entry_sha256': c.digest(implementation)})
        else:
            request = c.read_json(out / 'request.json')
            c.fields(request, 'schema kind commit reason entry_sha256', 'qualification request')
            c.require(request['schema'] == 1 and request['kind'] == 'native-qualification-request' and
                      request['commit'] == args.commit and request['entry_sha256'] == c.digest(implementation) and
                      request['reason'] in ('final-inputs', 'initial-seed', 'seed-promotion'),
                      'qualification-input', 'qualification request identity differs')
            prior = c.read_json(out / 'invocations.json')
            c.require([row['name'] for row in prior] ==
                      ['capture', 'cold', 'fixtures', 'real', 'transactions', 'jvm', 'dual',
                       'native-fixpoint', 'native-cli-diff', 'seal', 'structure', 'verify-cold', 'verify-package'] and
                      all(row['exit_code'] == 0 for row in prior),
                      'qualification-coverage', 'qualification steps are incomplete or duplicated')
            for row in prior:
                c.logical(row['name'])
                c.require(c.digest(c.regular_bytes(out / (row['name'] + '.log'))) == row['log_sha256'],
                          'qualification-input', 'qualification log differs')
            commands = []
        commands += [('verify-cold', seed_cli + ['verify-cold', *common, '--out', str(out / 'cold')]),
                     ('verify-package', k4 + ['verify-package', '--out', str(out)])]
        rows = []
        env = dict(os.environ, CC_JOBS='1')
        for name, argv in commands:
            print('qualification: ' + name, flush=True)
            log_name = name + ('.independent.log' if args.command == 'verify' else '.log')
            selected_env = env
            if name in ('native-fixpoint', 'native-cli-diff'):
                selected_env = {'PATH': str(args.java21.absolute().parent) + ':/usr/bin:/bin',
                                'JAVA_HOME': str(args.java21.absolute().parent.parent),
                                'HOME': str(out / 'jvm/home-21'), 'TMPDIR': str(out / 'jvm/tmp-21'),
                                'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'TZ': 'UTC',
                                'CC': '/usr/lib/llvm-18/bin/clang', 'CC_JOBS': '1',
                                'DAWN_SEED_CACHE': str(out / 'jvm/seed-cache'),
                                'COURSIER_CACHE': str(out / 'jvm/coursier')}
            with (out / log_name).open('xb') as log:
                result = subprocess.run(argv, cwd=ROOT, env=selected_env, stdout=log, stderr=subprocess.STDOUT)
            rows.append({'name': name, 'argv': argv, 'exit_code': result.returncode,
                         'log_sha256': c.digest((out / log_name).read_bytes())})
            if args.command == 'run':
                temporary = out / 'invocations.pending.json'
                temporary.write_bytes(c.canonical(rows))
                os.replace(temporary, out / 'invocations.json')
            c.require(result.returncode == 0, 'qualification-step', name + ': see saved log')
        c.atomic_json(out / ('verified.json' if args.command == 'verify' else 'completed.json'),
                      {'source_commit': args.commit, 'receipt_sha256': c.digest(c.regular_bytes(out / 'receipt.json')),
                       'checks': rows, 'production_authorized': False})
        print('OK explicit qualification; production seed unchanged')
    except (c.Rejected, OSError, ValueError) as exc:
        print(f'REJECT {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
