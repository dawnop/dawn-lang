#!/usr/bin/env python3
"""Count real loader parsing and prepared-consumer work in private artifacts.

Each compiling mutation preserves the fixture's semantics but must change its
exact invocation vector. Production compiler sources never import the observer.
"""
import argparse
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, install_probe, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asm-jar', type=Path)
    args = parser.parse_args()
    candidates = sorted((Path.home() / '.cache/coursier/v1/https').glob(
        '**/org/ow2/asm/asm/9.7.1/asm-9.7.1.jar'))
    asm = args.asm_jar or (candidates[0] if candidates else None)
    if asm is None or not asm.is_file():
        parser.error('provide --asm-jar from the existing compiler host dependency')
    here = Path(__file__).resolve().parent
    original = (ROOT / 'selfhost/src/driver/analyze.dawn').read_text()
    seed = '          let parsed = source_snapshot.parse(text, capture)\n          let m = parsed.syntax'
    dependency = '              let parsed = source_snapshot.parse(text, capture)\n              let m2p = parsed.syntax'
    capture = 'source_snapshot.parse(text, capture)'
    if original.count(capture) != 3:
        raise RuntimeError('Expected both loader parse sites and standalone preparation')
    variants = [
        ('duplicate-seed', edit(original, seed,
         '          let _ = parser.parse_module(text)\n' + seed), 'project_on', '[3, 3, 3]', '[4, 3, 3]'),
        ('duplicate-dependency', edit(original, dependency,
         '              let _ = parser.parse_module(text)\n' + dependency), 'project_on', '[3, 3, 3]', '[5, 3, 3]'),
        ('eager-cold-capture', original.replace(capture, 'source_snapshot.parse(text, true)'),
         'project_off', '[3, 0, 0]', '[3, 3, 3]'),
        ('reparse-prepared-consumer', edit(original, 'match prepared_snapshot {',
         'let ignored_prepared: Option[Option[source_snapshot.Snapshot]] = None\n'
         '          match ignored_prepared {'), 'session_consumer', '[0, 0, 0]', '[2, 2, 2]'),
    ]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='dawn-prepared-parse-counts-') as temp:
        root = Path(temp)
        host = root / 'host'
        host.mkdir()
        subprocess.run(['javac', '--release', '21', '-cp', str(asm), '-d', str(host),
                        str(here / 'SourceParseCounts.java'), str(here / 'PreparedParseCounts.java')], check=True)
        oracle = root / 'host.jar'
        subprocess.run(['jar', 'cf', str(oracle), '-C', str(host), '.'], check=True)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        fixture = install_probe(root, {'prepared_parse_counts': (here / 'prepared-parse-counts.dawn.txt').read_text()},
                                entry='prepared_parse_counts')
        jar = root / 'subject.jar'
        for name, text, sample, expected, actual in [('positive', original, None, None, None)] + variants:
            before = time.monotonic()
            (root / 'selfhost/src/driver/analyze.dawn').write_text(text)
            status, output = run('build', '--cp', oracle, fixture, '-o', jar)
            if status:
                raise RuntimeError(name + ' did not compile\n' + output)
            result = subprocess.run(['java', '-Xss64m', '-Xmx2g', '-cp',
                                     os.pathsep.join([str(host), str(asm)]),
                                     'contract.PreparedParseCounts', str(jar)], cwd=ROOT, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
            output = result.stdout
            if name == 'positive':
                if result.returncode or 'PASS  prepared_parse_counts :: prepared parse invocation counts' not in output:
                    raise RuntimeError('Prepared counter positive failed\n' + output)
            else:
                owner = re.search(r'^FAIL  prepared_parse_counts :: prepared parse invocation counts\n'
                                  r'  assertion failed: ' + sample + r' expected=' + re.escape(expected) +
                                  r' actual=' + re.escape(actual) + r'$', output, re.M)
                if not result.returncode or not owner or re.search(r'Exception|Error|panic:|^error:', output, re.M):
                    raise RuntimeError(name + ' missed its exact count assertion\n' + output)
            print(output.strip(), flush=True)
            print(f'OK: prepared parse counts {name}; elapsed={time.monotonic()-before:.2f}s', flush=True)
    print(f'OK: prepared parse-count positive and 4 compiling controls; elapsed={time.monotonic()-started:.2f}s')


if __name__ == '__main__':
    main()
