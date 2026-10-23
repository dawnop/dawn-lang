#!/usr/bin/env python3
"""Compile isolated runner mutants, then demand the C contract catches each.

The C HTTP sentinel test is the positive control as well as the oracle. The
cross-target write mutant uses the route's recording-host test to distinguish
writes even when a normal sample happens to have equal C and paired tables.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
dawnc = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix='play-c-controls.') as work:
    for name in ('javap-before-c', 'paired-c-job', 'native-fallback', 'old-key', 'jvm-writes-c'):
        dest = Path(work) / name
        for directory in ('playground', 'packages'):
            shutil.copytree(root / directory, dest / directory, ignore=shutil.ignore_patterns('build', '__pycache__'))
        subprocess.run([sys.executable, root / 'scripts/play-c-only-contract/mutate.py', name, dest], check=True)
        binary = dest / 'play'
        built = subprocess.run([dawnc, 'build', dest / 'playground', '-o', binary], capture_output=True, timeout=180)
        assert built.returncode == 0, (name, 'mutant must compile', built.stderr[-3000:])
        if name == 'jvm-writes-c':
            command = [dawnc, 'test', dest / 'playground']
            expected = b'paired success and cacheable failure only write the requested schema key'
        else:
            command = [sys.executable, '-I', '-B', root / 'playground/test/c-only-contract.py', binary, dawnc]
            expected = b'AssertionError'
        tested = subprocess.run(list(map(str, command)), capture_output=True, timeout=180)
        assert tested.returncode != 0 and expected in tested.stdout + tested.stderr, (name, 'mutant was not caught', tested.stdout[-1000:], tested.stderr[-1000:])
        print(f'OK negative control: {name} compiled, then the corresponding contract went red', flush=True)
