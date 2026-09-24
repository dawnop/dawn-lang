#!/usr/bin/env python3
"""Measure production parse/index method entries in a private JVM artifact.

Host bytecode instrumentation preserves the portable compiler and its source
proof. These are API invocation counts, not loader or end-to-end cost evidence.
"""
import argparse
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from cold import ROOT, edit, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asm-jar', type=Path)
    args = parser.parse_args()
    asm = args.asm_jar
    if asm is None:
        cache = Path.home() / '.cache/coursier/v1/https'
        candidates = sorted(cache.glob('**/org/ow2/asm/asm/9.7.1/asm-9.7.1.jar'))
        if not candidates:
            parser.error('provide --asm-jar from the existing compiler host dependency')
        asm = candidates[0]
    if not asm.is_file():
        parser.error('--asm-jar must name an existing file')
    here = Path(__file__).resolve().parent
    source = (ROOT / 'selfhost/src/check/source_snapshot.dawn').read_text()
    anchor = '  let (syntax, diagnostics, cps, toks) = parser.parse_module_lexed(text)'
    guard = '  if not capture || diagnostics != [] { return result }'
    variants = [
        ('duplicate-parse', edit(source, anchor,
         '  let _ = parser.parse_module_lexed(text)\n' + anchor), 'clean_on', '[2, 1, 1]'),
        ('eager-index', edit(source, guard,
         '  if not capture { let _ = source_projection.index_cps(text, cps) }\n' + guard),
         'clean_off', '[1, 1, 0]'),
        ('eager-projection', edit(source, guard,
         '  if not capture {\n'
         '    let eager = source_projection.index_cps(text, cps)\n'
         '    let spans: List[(Int, Int, Int)] = []\n'
         '    let _ = source_projection.tokens_from(eager, toks, spans)\n'
         '  }\n' + guard), 'clean_off', '[1, 1, 1]'),
    ]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='dawn-source-parse-counts-') as temp:
        root = Path(temp)
        classes = root / 'host'
        classes.mkdir()
        subprocess.run(['javac', '--release', '21', '-cp', str(asm), '-d', str(classes),
                        str(here / 'SourceParseCounts.java')], check=True)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        fixture = root / 'scripts/incremental-semantics-contract'
        (fixture / 'src').mkdir(parents=True)
        shutil.copy(here / 'dawn.toml', fixture / 'dawn.toml')
        (fixture / 'src/source_parse_counts.dawn').write_text((here / 'source-parse-counts.dawn.txt').read_text())
        # a project's entry module is src/main.dawn (spec §10.5); the fixture's own
        # `main` is an ordinary function now, so a two-line entry forwards to it
        (fixture / "src/main.dawn").write_text("use source_parse_counts\n\npub fn main() -> Unit !io = source_parse_counts.main()\n")
        jar = root / 'subject.jar'
        for name, text, sample, actual in [('positive', source, None, None)] + variants:
            before = time.monotonic()
            (root / 'selfhost/src/check/source_snapshot.dawn').write_text(text)
            status, output = run('build', fixture, '-o', jar)
            if status:
                raise RuntimeError(name + ' did not compile\n' + output)
            if name == 'positive':
                with zipfile.ZipFile(jar) as archive:
                    print('Subject targets: ' + repr([entry for entry in archive.namelist()
                          if entry.endswith('/parser.class') or entry.endswith('/source_projection.class')]), flush=True)
            result = subprocess.run(['java', '-Xss64m', '-Xmx2g', '-cp',
                                     os.pathsep.join([str(classes), str(asm)]),
                                     'contract.SourceParseCounts', str(jar)], cwd=ROOT,
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
            output = result.stdout
            if name == 'positive':
                if result.returncode or 'PASS  source_parse_counts :: source parse invocation counts' not in output:
                    raise RuntimeError('Counter positive failed\n' + output)
            else:
                expected = '[1, 1, 1]' if sample == 'clean_on' else '[1, 0, 0]'
                owner = re.search(r'^FAIL  source_parse_counts :: source parse invocation counts\n'
                                  r'  assertion failed: ' + sample + r' expected=' + re.escape(expected) + r' actual=' +
                                  re.escape(actual) + r'$', output, re.M)
                bad = re.search(r'Exception|Error|panic:|^error:', output, re.M)
                if not result.returncode or not owner or bad:
                    raise RuntimeError(name + ' missed its exact count assertion\n' + output)
            print(output.strip(), flush=True)
            print(f'OK: source parse counts {name}; elapsed={time.monotonic()-before:.2f}s', flush=True)
    print(f'OK: production parse-count positive and 3 compiling controls; elapsed={time.monotonic()-started:.2f}s')


if __name__ == '__main__':
    main()
