#!/usr/bin/env python3
"""What the launcher and the release workflow ask of the native seed lock.

Why a script and not shell in bin/dawn: the lock is a hash chain with
revocation, which shell cannot read strictly (duplicate keys, canonical form,
digest chaining). The launcher keeps only what is about its own environment,
the DAWN_SEED_CHAIN and seed-variable conflicts, and asks this file everything
about the records.

  launch -- ARGS
            verify/build a native generation, then exec current B
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
  build --lock FILE --seed-elf ELF --out DIR
            build S -> A -> B without a launcher cache; --seed-tree supplies
            an already prepared pair, otherwise materialize it from seed commit
  prepare-pair --lock FILE --out DIR
            materialize and verify the seed commit's std/runtime (offline)
  describe-seed --seed-elf ELF --seed-commit COMMIT --out FILE
            describe a complete local input. An eligible proposal also needs
            --chain-receipt, --origin-lock and --origin-builder. Without origin
            it is a development input, never a qualification or promotion.
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
from native_seed import builder, contract as c, lockchain  # noqa: E402
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
    # Keep application arguments opaque to argparse, including empty strings.
    if sys.argv[1:2] == ['launch']:
        from native_seed import launcher
        try:
            c.require(sys.argv[2:3] == ['--'], 'arguments', 'launch requires -- before application arguments')
            return launcher.launch(HERE.parent, sys.argv[3:], fetch)
        except (c.Rejected, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            print(f'error: {exc}; native launch refused, no fallback to jar', file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('default', 'check', 'seed', 'describe-seed', 'prepare-pair', 'build', 'contract-fixture'))
    parser.add_argument('directory', nargs='?')
    parser.add_argument('--scripts-dir', type=Path)
    parser.add_argument('--cache-root', type=Path)
    parser.add_argument('--base', help='a git revision to compare the records with (check only)')
    parser.add_argument('--lock', type=Path)
    parser.add_argument('--seed-elf', type=Path)
    parser.add_argument('--seed-commit')
    parser.add_argument('--chain-receipt', type=Path)
    parser.add_argument('--origin-lock', type=Path)
    parser.add_argument('--origin-builder', type=Path)
    parser.add_argument('--seed-tree', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--cc', default='/usr/lib/llvm-18/bin/clang')
    parser.add_argument('--jobs', type=int, choices=(1,), default=1)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--development-cc', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'describe-seed':
            c.require(args.seed_elf and args.seed_commit and args.out, 'arguments',
                      '--seed-elf, --seed-commit and --out required')
            c.oid(args.seed_commit, 'seed commit')
            _, files = c.git_files(HERE.parent, args.seed_commit)
            data = c.regular_bytes(args.seed_elf)
            c.verify_elf(data)
            banner, build_id = builder.identity(args.seed_elf)
            version = banner.split()[1]
            registration = {'kind': 'local-development', 'metadata': 'absent', 'evidence_sha256': c.digest(data)}
            if any((args.chain_receipt, args.origin_lock, args.origin_builder)):
                c.require(all((args.chain_receipt, args.origin_lock, args.origin_builder)),
                          'arguments', 'origin receipt, lock and A are required together')
                record = c.read_json(args.chain_receipt)
                builder.verify_receipt(args.chain_receipt, HERE.parent, builder.load_lock(args.origin_lock),
                                       args.seed_elf, args.origin_builder,
                                       require_c='C' in record['stages'], hosted=True)
                c.require(args.seed_commit == record['source_commit'], 'chain-source', 'seed commit differs from origin')
                registration = {'kind': 'proposed-seed', 'metadata': 'absent',
                                'evidence_sha256': c.digest(c.canonical(record))}
            subject = {'schema': 2, 'kind': 'native-seed-lock', 'state': 'proposed', 'sequence': 0,
                'seed': {'kind': 'native-elf', 'tag': 'v' + version, 'commit': args.seed_commit,
                         'asset': c.ASSET, 'sha256': c.digest(data), 'size': len(data),
                         'target': c.TARGET, 'version': banner, 'build_id': build_id},
                'std': c.identity(args.seed_commit, c.subtree(files, 'std')),
                'runtime': c.identity(args.seed_commit, c.subtree(files, 'runtime/c')),
                'lineage': {'parent_lock_sha256': None, 'parent_receipt_sha256': None, 'qualification_sha256': None},
                'registration': registration}
            c.validate_lock(subject)
            c.atomic_json(args.out, subject)
            print(args.out)
        elif args.command == 'prepare-pair':
            c.require(args.lock and args.out, 'arguments', '--lock and --out required')
            builder.prepare_pair(HERE.parent, builder.load_lock(args.lock), args.out)
            print(args.out)
        elif args.command == 'build':
            c.require(args.lock and args.seed_elf and args.out, 'arguments', '--lock, --seed-elf and --out required')
            receipt = builder.build(HERE.parent, args.lock, args.seed_elf, args.seed_tree, args.out,
                                    args.cc, args.jobs, live=args.live, development_cc=args.development_cc)
            print(c.digest(c.canonical(receipt)))
        elif args.command == 'contract-fixture':
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
    except (c.Rejected, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
