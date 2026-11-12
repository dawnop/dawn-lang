#!/usr/bin/env python3
"""Prepare inputs and run explicit offline native qualification without changing a default seed."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from native_seed import contract as c
import repo_env


def historical_registration(repo, assets, destination):
    """The only historical import; normal readers never infer missing metadata."""
    destination = c.safe_destination(destination)
    c.require(not destination.exists() and not destination.is_symlink(), 'destination', 'new directory required')
    data = c.regular_bytes(Path(assets) / c.ASSET)
    c.require(len(data) == c.HISTORICAL_SIZE and c.digest(data) == c.HISTORICAL_SHA,
              'seed-digest', 'historical seed bytes differ; execution refused')
    checksum = c.regular_bytes(Path(assets) / (c.ASSET + '.sha256'))
    c.require(checksum == f'{c.HISTORICAL_SHA}  {c.ASSET}\n'.encode('ascii'),
              'seed-digest', 'historical sidecar mismatch')
    c.verify_elf(data)
    coordinate = repo_env.github_repo()
    remote = subprocess.run(['git', 'ls-remote', 'https://github.com/' + coordinate + '.git',
                             'refs/tags/v0.104.0', 'refs/tags/v0.104.0^{}'],
                            capture_output=True, text=True, timeout=60)
    c.require(remote.returncode == 0, 'seed-tag', 'remote tag lookup failed')
    refs = dict(line.split()[::-1] for line in remote.stdout.splitlines())
    commit = refs.get('refs/tags/v0.104.0^{}', refs.get('refs/tags/v0.104.0'))
    c.require(commit == c.HISTORICAL_COMMIT, 'seed-tag', 'remote historical tag moved or missing')
    release = subprocess.run(['gh', 'api', f'repos/{coordinate}/releases/tags/v0.104.0'],
                             capture_output=True, timeout=60)
    c.require(release.returncode == 0, 'seed-release', 'release lookup failed')
    info = json.loads(release.stdout, object_pairs_hook=c.no_duplicates)
    c.require(info.get('tag_name') == 'v0.104.0' and info.get('draft') is False and
              info.get('prerelease') is False, 'seed-release', 'unexpected historical release')
    names = [asset['name'] for asset in info['assets']]
    c.require(len(names) == len(set(names)) and 'dawn-toolchain.json' not in names,
              'seed-release', 'unexpected historical asset identity')
    expected_assets = {c.ASSET, c.ASSET + '.sha256', 'dawn-selfhost.jar',
                       'dawn-selfhost.jar.sha256', 'dawn-pub-api.json', 'dawn-pub-api-diff.md'}
    c.require(set(names) == expected_assets, 'seed-release', 'historical assets missing or changed')
    asset = next(a for a in info['assets'] if a['name'] == c.ASSET)
    c.require(asset['size'] == len(data) and asset['digest'] == 'sha256:' + c.digest(data),
              'seed-digest', 'release API and actual bytes differ')
    version, build_id = c.probe_seed(data)
    _, source = c.git_files(repo, commit)
    std = c.identity(commit, c.subtree(source, 'std'))
    runtime = c.identity(commit, c.subtree(source, 'runtime/c'))
    evidence = {'kind': 'historical-native-registration', 'schema': 2, 'tag': 'v0.104.0',
                'commit': commit, 'asset': c.ASSET, 'sha256': c.digest(data), 'size': len(data),
                'sidecar_sha256': c.digest(checksum), 'target': c.TARGET,
                'version': version, 'build_id': build_id, 'metadata': 'absent',
                'std': std, 'runtime': runtime}
    lock = {'kind': 'native-seed-lock', 'schema': 2, 'state': 'candidate', 'sequence': 0,
            'seed': {'kind': 'native-elf', 'tag': 'v0.104.0', 'commit': commit, 'asset': c.ASSET,
                     'sha256': c.digest(data), 'size': len(data), 'target': c.TARGET,
                     'version': version, 'build_id': build_id}, 'std': std, 'runtime': runtime,
            'lineage': {'parent_lock_sha256': None, 'parent_receipt_sha256': None,
                        'qualification_sha256': None},
            'registration': {'kind': 'historical-v0.104.0', 'metadata': 'absent',
                             'evidence_sha256': c.digest(c.canonical(evidence))}}
    c.validate_lock(lock)
    destination.mkdir(parents=True, exist_ok=False)
    paired = {p: x for p, x in source.items() if p.startswith(('std/', 'runtime/c/'))}
    paired['dawnc'] = ('100755', data)
    c.write_tree(destination / 'seed', paired)
    c.atomic_json(destination / 'registration.json', evidence)
    # The lock is the last commit point. A partial directory is never a seed.
    c.atomic_json(destination / 'native-seed.lock.json', lock)
    return lock


def capture(repo, commit, destination, lock):
    destination = c.safe_destination(destination)
    c.require(not destination.exists() and not destination.is_symlink(), 'destination', 'new directory required')
    source, files = c.source_description(repo, commit)
    c.verify_generated(files)
    receipt = {'kind': 'native-bootstrap-inputs', 'schema': 2,
               'seed_lock_sha256': c.digest(c.canonical(lock)), 'source': source,
               'stages': c.stages(lock, source)}
    c.validate_receipt(receipt, lock)
    destination.mkdir(parents=True, exist_ok=False)
    c.write_tree(destination / 'source', files)
    c.atomic_json(destination / 'inputs.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    register = sub.add_parser('register-v0.104.0', help='one-time historical candidate import')
    register.add_argument('--repo', type=Path, required=True)
    register.add_argument('--assets', type=Path, required=True)
    register.add_argument('--out', type=Path, required=True)
    cap = sub.add_parser('capture', help='capture committed portable qualification inputs')
    cap.add_argument('--repo', type=Path, required=True)
    cap.add_argument('--commit', required=True, help='full commit object ID')
    cap.add_argument('--lock', type=Path, required=True)
    cap.add_argument('--out', type=Path, required=True)
    verify = sub.add_parser('verify', help='recheck actual seed and all committed inputs')
    verify.add_argument('--repo', type=Path, required=True)
    verify.add_argument('--lock', type=Path, required=True)
    verify.add_argument('--receipt', type=Path, required=True)
    verify.add_argument('--source', type=Path, required=True)
    verify.add_argument('--seed-tree', type=Path, required=True)
    verify.add_argument('--seed', type=Path, help='native ELF; otherwise DAWN_NATIVE_SEED is required')
    compile_cmd = sub.add_parser('compile-stage', help='compile with an explicit verified stage recipe')
    for name in ('repo', 'lock', 'receipt', 'source', 'seed-tree', 'std', 'runtime',
                 'cc', 'units', 'build-info', 'out', 'recipe-out'):
        compile_cmd.add_argument('--' + name, type=Path, required=True)
    compile_cmd.add_argument('--stage', choices=('A', 'B', 'C'), required=True)
    compile_cmd.add_argument('--jobs', type=int, choices=(1, 2), required=True)
    tool = sub.add_parser('prepare-toolchain', help='snapshot the offline qualification C toolchain')
    tool.add_argument('--cc', type=Path, required=True)
    tool.add_argument('--out', type=Path, required=True)
    cold = sub.add_parser('cold-run', help='run two offline native-only qualification roots')
    for name in ('repo', 'lock', 'receipt', 'source', 'seed-tree', 'seed', 'toolchain', 'out'):
        cold.add_argument('--' + name, type=Path, required=True)
    check = sub.add_parser('verify-cold', help='independently recheck cold execution and outputs')
    check.add_argument('--repo', type=Path, required=True)
    check.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'register-v0.104.0':
            historical_registration(args.repo, args.assets, args.out)
            print('OK historical native candidate registered; qualification pending')
        elif args.command == 'capture':
            capture(args.repo, args.commit, args.out, c.read_lock(args.lock))
            print('OK committed native inputs captured')
        elif args.command == 'compile-stage':
            from native_seed.recipe import compile_stage
            compile_stage(args)
            print('OK explicit native stage compiled; qualification pending')
        elif args.command == 'prepare-toolchain':
            from native_seed.toolchain import prepare
            prepare(args.cc, args.out)
            print('OK offline C toolchain snapshot prepared')
        elif args.command in ('cold-run', 'verify-cold'):
            from native_seed import cold
            if args.command == 'cold-run':
                cold.run(args)
            else:
                cold.verify(args.repo, args.out)
            print('OK native cold chain and two-root fixed point verified; qualification pending')
        else:
            seed = args.seed or os.environ.get('DAWN_NATIVE_SEED')
            c.require(bool(seed), 'seed-missing', '--seed or DAWN_NATIVE_SEED is required')
            c.verify_inputs(args.repo, args.source, c.read_lock(args.lock), c.read_json(args.receipt),
                            seed, args.seed_tree)
            print('OK native seed, source and stage pairings verified; qualification pending')
    except (c.Rejected, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f'REJECT {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
