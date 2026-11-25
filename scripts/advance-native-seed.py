#!/usr/bin/env python3
"""Move the native seed lock: initial, promote, rollback, revoke, set-chain.

Why a sibling of advance-seed.sh and not a mode of it: the JAR protocol moves
three files that a launcher compares byte for byte, this one appends to a hash
chain. Sharing code would couple two trust records that should fail
independently, and the JAR protocol is deliberately untouched by this change.

The discipline is the same: verify everything about the future seed before
touching a file, write history first and move the lock last, and let a rerun
after any interruption converge (scripts/native_seed/lockchain.py commit_step).

  initial  --qualification DIR        turn the historical candidate into lock 1
  promote  TAG --qualification DIR    lock a released, qualified tag
  rollback SEQUENCE --reason WORD     return to an earlier qualified seed
  revoke   SHA256 --reason WORD       distrust a seed digest
  set-chain jar|native --reason WORD  change the default chain, as a recorded step

A qualification directory is the output of scripts/native-seed-qualify.py `run`
(reason seed-promotion, or initial-seed for the first lock) after `verify` has
run on it independently. Without both there is no promotion: the receipt is
evidence about a seed, and a lock that names none is not a lock.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from native_seed import builder, contract as c, inputs, lockchain, provenance, toolchain  # noqa: E402
import native_release as nr  # noqa: E402
import repo_env  # noqa: E402

RUN_STEPS = ['capture', 'cold', 'fixtures', 'real', 'transactions', 'jvm', 'dual', 'native-fixpoint',
             'native-cli-diff', 'seal', 'structure', 'verify-cold', 'verify-package']
VERIFY_STEPS = ['verify-cold', 'verify-package']
CANDIDATE = HERE / 'native-seed-candidate-v0.104.0.json'


def qualification_receipt(directory, reason):
    """The receipt digest of a complete, independently verified qualification. Strict."""
    directory = Path(directory)
    request = c.read_json(directory / 'request.json')
    c.fields(request, 'schema kind commit reason entry_sha256 seed_lock_sha256 execution', 'qualification request')
    c.require(request['schema'] == 1 and request['kind'] == 'native-qualification-request' and
              request['reason'] == reason, 'lock-qualification',
              f'the qualification must have been run for the reason {reason}')
    c.oid(request['commit'], 'qualification commit')
    provenance.verify(request['execution'], request['commit'], hosted=True)
    receipt_bytes = c.regular_bytes(directory / 'receipt.json')
    receipt = c.read_json(directory / 'receipt.json')
    c.require(type(receipt) is dict and receipt.get('kind') == 'native-qualification-package' and
              receipt.get('source_commit') == request['commit'] and
              receipt.get('execution') == request['execution'] and
              receipt.get('coverage') == ['Q' + str(i) for i in range(1, 11)],
              'lock-qualification', 'the receipt does not describe this qualification')
    subject = c.read_lock(directory / 'cold/seed-lock.json')
    c.require(request['seed_lock_sha256'] == c.digest(c.canonical(subject)) and
              receipt.get('seed_lock_sha256') == request['seed_lock_sha256'] and
              receipt.get('qualified_seed_sha256') == subject['seed']['sha256'] and
              receipt.get('compilation_sha256') == c.digest(c.canonical(receipt.get('compilation'))) and
              receipt['compilation'].get('seed') == inputs.seed_identity(subject),
              'lock-qualification', 'qualification is bound to another input lock or ELF')
    for name, steps in (('completed.json', RUN_STEPS), ('verified.json', VERIFY_STEPS)):
        done = c.read_json(directory / name)
        c.require(type(done) is dict and done.get('receipt_sha256') == c.digest(receipt_bytes) and
                  done.get('source_commit') == request['commit'] and
                  done.get('production_authorized') is False and
                  [row.get('name') for row in done.get('checks', [])] == steps and
                  all(row.get('exit_code') == 0 for row in done['checks']),
                  'lock-qualification', f'{name} is missing, incomplete or from another receipt')
    return c.digest(receipt_bytes), request['commit']


def verify_subject(directory, repo, commit, seed, std, runtime):
    """Match the promoted bytes and current compilation inputs without a future lock hash."""
    directory = Path(directory)
    receipt = c.read_json(directory / 'receipt.json')
    subject = c.read_lock(directory / 'cold/seed-lock.json')
    expected = dict(subject, seed=seed, std=std, runtime=runtime)
    tc = toolchain.verify_record(c.read_json(directory / 'cold/toolchain/toolchain.json'))
    _, files = builder.source_files(repo, commit)
    c.require(inputs.seed_identity(subject) == inputs.seed_identity(expected) and
              receipt['qualified_seed_sha256'] == seed['sha256'] and
              receipt['compilation'] == inputs.compilation(files, expected, tc) and
              receipt['compilation_sha256'] == inputs.compilation_sha(files, expected, tc),
              'lock-qualification', 'promoted ELF, pair or compilation inputs differ; rerun qualification')


def release_base():
    base = os.environ.get('DAWN_RELEASE_BASE_URL') or \
        'https://github.com/' + repo_env.github_repo() + '/releases/download'
    c.require('\n' not in base, 'seed-fetch', 'release base URL must fit on one line')
    return base


def download_assets(tag, destination):
    destination.mkdir(parents=True)
    for name in nr.UPLOAD_ORDER:
        try:
            with urllib.request.urlopen(f'{release_base()}/{tag}/{name}', timeout=300) as response:
                (destination / name).write_bytes(response.read())
        except OSError as exc:
            raise c.Rejected(f'seed-fetch: cannot download {name}: {exc}') from exc


def evidence_from_assets(assets, tag, commit, lock_path, repo):
    """The seed, std, runtime and registration a promotion records, from nine verified assets."""
    info = nr.aggregate(assets, tag, lock_path)
    c.require(info['release']['commit'] == commit, 'release-lineage',
              'release metadata names another commit than the tag')
    payload = (Path(assets) / c.ASSET).read_bytes()
    native = info['native']
    version = f'dawnc {tag[1:]} (native)'
    c.verify_elf(payload)
    c.require(native['sha256'] == c.digest(payload) and native['size'] == len(payload), 'seed-digest',
              'payload differs from its metadata')
    probed, build_id = c.probe_seed(payload, version)
    c.require((probed, build_id) == (version, native['build_id']), 'seed-identity',
              'version or build ID differs from the metadata')
    seed = {'kind': 'native-elf', 'tag': tag, 'commit': commit, 'asset': c.ASSET, 'sha256': native['sha256'],
            'size': native['size'], 'target': c.TARGET, 'version': version, 'build_id': build_id}
    _, source = c.git_files(repo, commit)
    std = c.identity(commit, c.subtree(source, 'std'))
    runtime = c.identity(commit, c.subtree(source, 'runtime/c'))
    registration = {'kind': 'release', 'metadata': 'present',
                    'evidence_sha256': c.digest((Path(assets) / 'dawn-toolchain.json').read_bytes())}
    return seed, std, runtime, registration


def resolve_tag(repo, origin, tag):
    """Fresh from the origin; the caller asks again afterwards, so a moved tag is caught."""
    def once():
        out = subprocess.run(['git', '-C', str(repo), 'ls-remote', origin, f'refs/tags/{tag}',
                              f'refs/tags/{tag}^{{}}'], capture_output=True, text=True)
        c.require(out.returncode == 0, 'seed-tag', 'cannot read the tag from the origin')
        refs = {line.split()[1]: line.split()[0] for line in out.stdout.splitlines()}
        commit = refs.get(f'refs/tags/{tag}^{{}}', refs.get(f'refs/tags/{tag}'))
        c.require(commit is not None, 'seed-tag', 'tag not found on the origin')
        c.oid(commit, 'tag commit')
        return commit
    return once(), once


def promote(args):
    lock_path = lockchain.paths(args.scripts_dir)[0]
    loaded = lockchain.load(args.scripts_dir)
    tag = args.target
    c.require(lockchain.version_key(tag) > max(lockchain.version_key(i[0]['seed']['tag']) for i in loaded.chain),
              'lock-version', 'a promotion needs a tag above every seed ever locked')
    c.require(args.qualification is not None, 'lock-qualification', 'promotion requires --qualification')
    commit, again = resolve_tag(args.repo, args.origin, tag)
    receipt, receipt_commit = qualification_receipt(args.qualification, 'seed-promotion')
    # Compilation identity is checked below; a control-only commit needs no new qualification.
    ref = f'refs/dawn-advance-native-seed/{tag}'
    fetched = subprocess.run(['git', '-C', str(args.repo), 'fetch', '--no-tags', '--quiet', args.origin,
                              f'+refs/tags/{tag}:{ref}'])
    c.require(fetched.returncode == 0, 'seed-tag', 'cannot fetch the tag')
    try:
        ancestor = subprocess.run(['git', '-C', str(args.repo), 'merge-base', '--is-ancestor', commit, 'HEAD'])
        c.require(ancestor.returncode == 0, 'seed-tag', 'the tag is not an ancestor of HEAD')
        with tempfile.TemporaryDirectory(prefix='advance-native-seed-') as work:
            assets = Path(args.assets) if args.assets else Path(work) / 'assets'
            if not args.assets:
                download_assets(tag, assets)
            seed, std, runtime, registration = evidence_from_assets(assets, tag, commit, lock_path, args.repo)
    finally:
        subprocess.run(['git', '-C', str(args.repo), 'update-ref', '-d', ref], capture_output=True)
    verify_subject(args.qualification, args.repo, commit, seed, std, runtime)
    c.require(again() == commit, 'seed-tag', 'the tag moved while the promotion ran')
    lockchain.promote(args.scripts_dir, seed, std, runtime, receipt, registration)
    print(f'promoted {tag} as native seed lock {loaded.lock["sequence"] + 1}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('initial', 'promote', 'rollback', 'revoke', 'set-chain'))
    parser.add_argument('target', nargs='?')
    parser.add_argument('--qualification', type=Path)
    parser.add_argument('--reason')
    parser.add_argument('--scripts-dir', type=Path)
    parser.add_argument('--repo', type=Path, default=HERE.parent)
    parser.add_argument('--origin', default=os.environ.get('DAWN_SEED_ORIGIN', 'origin'))
    parser.add_argument('--assets', type=Path, help='nine already downloaded assets, for a local rehearsal')
    args = parser.parse_args()
    try:
        if args.command == 'initial':
            c.require(args.target is None and args.qualification is not None, 'arguments',
                      'initial takes only --qualification')
            receipt, _ = qualification_receipt(args.qualification, 'initial-seed')
            candidate = c.read_lock(CANDIDATE)
            verify_subject(args.qualification, args.repo, c.git(args.repo, 'rev-parse', 'HEAD').decode().strip(),
                           candidate['seed'], candidate['std'], candidate['runtime'])
            lock = lockchain.initial(args.scripts_dir, CANDIDATE, receipt)
            print(f'native seed lock {lock["sequence"]} written for {lock["seed"]["tag"]}')
            return 0
        c.require(args.target is not None, 'arguments', 'a target is required')
        if args.command == 'promote':
            promote(args)
        elif args.command == 'rollback':
            c.require(args.reason, 'lock-reason', '--reason is required')
            lock = lockchain.rollback(args.scripts_dir, int(args.target), args.reason)
            print(f'rolled back to sequence {lock["lineage"]["rolled_back_to"]} as lock {lock["sequence"]}')
        elif args.command == 'revoke':
            c.require(args.reason, 'revoked', '--reason is required')
            lockchain.revoke(args.scripts_dir, args.target, args.reason)
            print('revoked ' + args.target)
        else:
            c.require(args.reason, 'lock-reason', '--reason is required')
            lock = lockchain.set_chain(args.scripts_dir, args.target, args.reason)
            print(f'default chain is now {lock["chain"]} (lock {lock["sequence"]})')
    except (c.Rejected, OSError, ValueError) as exc:
        print(f'REJECT {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
