#!/usr/bin/env python3
"""Verify local deployment products before any server connection.

The compiler and runner have different entry points and build manifests. A
version match alone accepts stale products from the same release. Recompute
the native compiler's manifest with the existing portable source capture and
JVM emitter, and compare the runner with its current project manifest. This
does not reconstruct or qualify a release chain.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def command(argv):
    result = subprocess.run([str(x) for x in argv], cwd=ROOT,
                            env=dict(os.environ, DAWN_SEED_CHAIN='jar'),
                            capture_output=True, text=True, check=True)
    require(not result.stderr, 'unexpected diagnostic: ' + result.stderr)
    return result.stdout


def listing(text, version):
    lines = text.splitlines(keepends=True)
    require(len(lines) >= 3 and lines[0].endswith(': dawn ' + version + '\n'),
            'artifact toolchain version differs from the source version')
    rows = ''.join(lines[1:-1])
    build_id = 'b1:' + hashlib.sha256(rows.encode()).hexdigest()
    require(lines[-1] == '\tbuild\t' + build_id + '\n', 'invalid full build identity')
    return rows, build_id


def emitted_manifest(unit, version):
    # binfo.manifest_unit writes the same byte list for wasm and ELF. Read the
    # ELF arm only; refuse an absent or changed format instead of guessing it.
    arm = unit.split('#elif defined(__ELF__)\n')
    require(len(arm) == 2, 'missing ELF build manifest arm')
    values = re.findall(r'^  "\.byte ([0-9,]+)\\n"$', arm[1], re.M)
    require(values, 'missing emitted manifest bytes')
    raw = bytes(int(x) for row in values for x in row.split(',')).decode()
    prefix = 'dawn-build-info 1\ntoolchain\tdawn ' + version + '\n'
    require(raw.startswith(prefix), 'wrong emitted manifest schema or version')
    rows = raw[len(prefix):]
    return rows, 'b1:' + hashlib.sha256(rows.encode()).hexdigest()


def verify(native, runner):
    dawn = ROOT / 'bin/dawn'
    jar = ROOT / 'build/dawn-selfhost.jar'
    version_source = (ROOT / 'selfhost/src/version.dawn').read_text()
    match = re.search(r'^pub const VERSION: String = "([0-9.]+)"$', version_source, re.M)
    require(match is not None, 'missing source VERSION')
    version = match[1]
    version_line = command([dawn, '--version']).splitlines()[-1]
    require(jar.is_file() and jar.stat().st_size > 0, 'missing current JAR')
    jar_identity = listing(command([dawn, 'version', '-m', jar]), version)
    require(jar_identity == listing(command([dawn, 'version', '-m', 'selfhost']), version),
            'JAR is stale for the current checkout')
    require(version_line == f'dawn {version} (selfhost) {jar_identity[1][:15]}',
            'JVM version line does not match its JAR')
    native_identity = listing(command([dawn, 'version', '-m', native]), version)
    require(native_identity == listing(command([native, 'version', '-m', native]), version),
            'native and JVM manifest readers disagree')
    require(command([native, '--version']) == f'dawnc {version} (native) {native_identity[1][:15]}\n',
            'native version line does not match its full identity')
    with tempfile.TemporaryDirectory(prefix='deploy-preflight-') as temporary:
        work = Path(temporary)
        entry = command([sys.executable, ROOT / 'scripts/native-source-tree.py', work / 'source']).strip()
        unit = work / 'build-info.c'
        command([dawn, '__emitc', entry, '-o', work / 'compiler.c', '--build-info', unit])
        require(native_identity == emitted_manifest(unit.read_text(), version),
                'native compiler is stale for the current portable source')
    runner_identity = listing(command([dawn, 'version', '-m', runner]), version)
    require(runner_identity == listing(command([dawn, 'version', '-m', 'playground']), version),
            'runner is stale for the current playground project')
    products = {}
    for name, path, identity in (('jar', jar, jar_identity), ('native', native, native_identity),
                                 ('runner', runner, runner_identity)):
        products[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'build_id': identity[1]}
    return {'version': version, 'chain': 'jar', 'products': products}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--runner', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.native.resolve(), args.runner.resolve()), sort_keys=True))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('error: deployment preflight: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
