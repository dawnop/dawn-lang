#!/usr/bin/env python3
"""What the launcher and the release workflow ask of the native seed lock.

Why a script and not shell in bin/dawn: the lock is a hash chain with
revocation, which shell cannot read strictly (duplicate keys, canonical form,
digest chaining). The launcher keeps only what is about its own environment,
the DAWN_SEED_CHAIN and seed-variable conflicts, and asks this file everything
about the records.

  default   verify the records and print the default chain (jar or native);
            prints nothing and fails when the records are corrupt or revoked
  check     verify the records for a release: a qualified lock must exist
  check --base REV
            as `check`, and also prove the records only grew since REV: the
            lock at REV is still in the chain byte for byte and no revocation
            was dropped (an in-place edit of the newest lock is otherwise
            invisible, since nothing points at it yet)
  seed      verify the locked seed ELF (cached, fetched once, re-verified on
            every use) and print its path; DAWN_NATIVE_SEED replaces it
  contract-fixture DIR
            write a qualified lock tree for protocol tests. The qualification
            digest in it is a label, not evidence; nothing reads DIR except a
            test that names it.

There is no switch that skips a digest and no fallback to the other chain.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from native_seed import contract as c, lockchain  # noqa: E402
import repo_env  # noqa: E402

CANDIDATE = HERE / 'native-seed-candidate-v0.104.0.json'
FIXTURE_QUALIFICATION = c.digest(b'contract fixture, not a qualification receipt\n')


def fetch(seed):
    base = os.environ.get('DAWN_RELEASE_BASE_URL') or \
        'https://github.com/' + repo_env.github_repo() + '/releases/download'
    c.require('\n' not in base, 'seed-fetch', 'release base URL must fit on one line')
    url = f'{base}/{seed["tag"]}/{c.ASSET}'
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read(seed['size'] + 1)
    except (OSError, ValueError) as exc:
        raise c.Rejected(f'seed-fetch: cannot download the locked seed: {exc}') from exc
    return data


def base_file(revision, name):
    """The record at a git revision, or None when that revision had none."""
    known = subprocess.run(['git', '-C', str(HERE), 'rev-parse', '--verify', '--quiet', revision + '^{commit}'],
                           capture_output=True)
    c.require(known.returncode == 0, 'lock-base', f'unknown base revision {revision}')
    out = subprocess.run(['git', '-C', str(HERE), 'show', f'{revision}:scripts/{name}'], capture_output=True)
    if out.returncode == 0:
        return out.stdout
    exists = subprocess.run(['git', '-C', str(HERE), 'cat-file', '-e', f'{revision}:scripts/{name}'],
                            capture_output=True)
    c.require(exists.returncode != 0, 'lock-base', f'cannot read {name} at {revision}')
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('default', 'check', 'seed', 'contract-fixture'))
    parser.add_argument('directory', nargs='?')
    parser.add_argument('--scripts-dir', type=Path)
    parser.add_argument('--cache-root', type=Path)
    parser.add_argument('--base', help='a git revision to compare the records with (check only)')
    args = parser.parse_args()
    try:
        if args.command == 'contract-fixture':
            c.require(args.directory is not None, 'arguments', 'a destination directory is required')
            out = c.safe_destination(args.directory)
            c.require(not out.exists(), 'destination', 'fixture directory must be new')
            lockchain.initial(out, CANDIDATE, FIXTURE_QUALIFICATION)
            print(out / lockchain.LOCK_NAME)
        elif args.command == 'default':
            print(lockchain.load(args.scripts_dir).lock['chain'])
        elif args.command == 'check':
            loaded = lockchain.load(args.scripts_dir)
            lock = loaded.lock
            if args.base:
                lockchain.check_base(loaded, base_file(args.base, lockchain.LOCK_NAME),
                                     base_file(args.base, lockchain.REVOKED_NAME))
            print(f'OK native seed lock: sequence {lock["sequence"]}, {lock["seed"]["tag"]}, chain {lock["chain"]}')
        else:
            override = os.environ.get('DAWN_NATIVE_SEED')
            if override:
                print(lockchain.override_seed(override))
            else:
                loaded = lockchain.load(args.scripts_dir)
                root = args.cache_root or (HERE.parent / '.dawn/native-seeds')
                print(lockchain.cached_seed(loaded.lock, root, fetch))
    except (c.Rejected, OSError, ValueError, KeyError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
