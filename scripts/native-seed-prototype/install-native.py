#!/usr/bin/env python3
"""Local schema 2 installer prototype; verifies downloaded B, not its unprovided builder."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_seed import contract as c
import identity


def install(directory, prefix, tag):
    value = identity.metadata(c.read_json(directory / 'dawn-toolchain.json'), tag)
    data = identity.payload(directory, value)
    destination = c.safe_destination(prefix / 'bin/dawn')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-prototype-', dir=destination.parent) as temporary:
        candidate = Path(temporary) / 'dawn'
        candidate.write_bytes(data)
        candidate.chmod(0o755)
        with candidate.open('rb') as stream:
            os.fsync(stream.fileno())
        env = {'PATH': '/nonexistent', 'HOME': temporary, 'LANG': 'C.UTF-8'}
        version = subprocess.run([str(candidate), '--version'], env=env, capture_output=True, timeout=30)
        expected = f"dawnc {value['release']['version']} (native) {value['native']['build_id'][:15]}\n".encode()
        c.require(version.returncode == 0 and version.stdout == expected and not version.stderr,
                  'prototype-version', 'native version differs')
        listing = subprocess.run([str(candidate), 'version', '-m', str(candidate)],
                                 env=env, capture_output=True, timeout=30)
        c.require(listing.returncode == 0 and not listing.stderr and
                  re.findall(rb'^\tbuild\t(b1:[0-9a-f]{64})$', listing.stdout, re.M) ==
                  [value['native']['build_id'].encode()], 'prototype-version', 'full build ID differs')
        os.replace(candidate, destination)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-dir', type=Path, required=True)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    try:
        install(args.from_dir, args.prefix, args.tag)
    except (c.Rejected, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f'REJECT {exc}', file=sys.stderr)
        sys.exit(1)
