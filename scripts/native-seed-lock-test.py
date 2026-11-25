#!/usr/bin/env python3
"""Controls for the qualified native seed lock (scripts/native_seed/lockchain.py).

Why mutants of the checker and not only refused inputs: a refusal test passes
just as well when the input was refused for the wrong reason, or when a second
check hides the one under test. Each invariant below is therefore also broken in
a copy of the module, and the suite must then fail. A control that cannot go red
is not a control (the same rule as scripts/bootstrap-guards).

Runs in the light gate. It builds three tiny static ELF files with `cc` (the
only external tool) and otherwise works in a temporary directory.
"""

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from native_seed import contract as c  # noqa: E402
from native_seed import lockchain as real_lockchain  # noqa: E402

CANDIDATE = HERE / 'native-seed-candidate-v0.104.0.json'
CHAIN_CLI = HERE / 'native-seed-chain.py'
ADVANCE = HERE / 'advance-native-seed.py'
passed = 0


def ok(condition, name):
    global passed
    if not condition:
        raise AssertionError(name)
    passed += 1


def refuses(name, code, thunk):
    try:
        thunk()
    except c.Rejected as exc:
        ok(str(exc).startswith(code + ':'), f'{name}: expected {code}, got {exc}')
        return
    raise AssertionError(f'{name} was accepted')


def sha(label):
    return c.digest(label.encode())


def seed_for(minor, label=None):
    tag = f'v0.{minor}.0'
    commit = c.digest(f'commit {tag}'.encode())[:40]
    return ({'kind': 'native-elf', 'tag': tag, 'commit': commit, 'asset': c.ASSET, 'sha256': sha('elf ' + tag),
             'size': 1000 + minor, 'target': c.TARGET, 'version': f'dawnc 0.{minor}.0 (native)',
             'build_id': 'b1:' + sha('build ' + tag)},
            c.identity(commit, sha('std ' + tag)), c.identity(commit, sha('runtime ' + tag)),
            {'kind': 'release', 'metadata': 'present', 'evidence_sha256': sha('metadata ' + tag)})


def promote(L, scripts, minor, hook=None, qualification=''):
    seed, std, runtime, registration = seed_for(minor)
    if qualification == '':
        qualification = sha('receipt %d' % minor)
    return L.promote(scripts, seed, std, runtime, qualification, registration, hook)


def fresh(L, tmp, name='s'):
    scripts = Path(tmp) / name
    scripts.mkdir()
    L.initial(scripts, CANDIDATE, sha('receipt initial'))
    return scripts


def read_all(scripts):
    return {str(p.relative_to(scripts)): p.read_bytes() for p in sorted(scripts.rglob('*')) if p.is_file()}


def edit_lock(scripts, change, canonical=True):
    path = scripts / 'native-seed-lock.json'
    value = json.loads(path.read_bytes())
    change(value)
    path.write_bytes(c.canonical(value) if canonical else json.dumps(value, indent=1).encode())


class Interrupt(Exception):
    pass


def interrupt_at(point):
    def hook(name):
        if name == point:
            raise Interrupt(name)
    return hook


def suite(L, tmp):
    """Every transition rule and every record check, against the module `L`."""
    # --- the happy path and the lineage it leaves
    scripts = fresh(L, tmp, 'happy')
    loaded = L.load(scripts)
    ok(loaded.lock['sequence'] == 1 and loaded.lock['chain'] == 'jar' and loaded.lock['seed']['tag'] == 'v0.104.0',
       'the initial lock restates the candidate and keeps the JAR default')
    promote(L, scripts, 105)
    promote(L, scripts, 106)
    loaded = L.load(scripts)
    ok(loaded.lock['sequence'] == 3 and sorted(p.name for p in (scripts / 'native-seed-history').iterdir()) ==
       ['0.json', '1.json', '2.json'], 'two promotions leave three history records')
    ok((scripts / 'native-seed-history/0.json').read_bytes() == CANDIDATE.read_bytes(),
       'history 0 is the candidate, byte for byte')
    L.set_chain(scripts, 'native', 'p4-default')
    ok(L.load(scripts).lock['chain'] == 'native', 'the default chain is a lock field, changed by a recorded step')
    L.set_chain(scripts, 'jar', 'back-to-jar')
    L.rollback(scripts, 2, 'bad-release')
    rolled = L.load(scripts).lock
    ok(rolled['seed']['tag'] == 'v0.105.0' and rolled['lineage']['rolled_back_from'] == 5 and
       rolled['lineage']['rolled_back_to'] == 2, 'a rollback names the abandoned and the restored sequence')
    refuses('promoting the abandoned tag after a rollback', 'lock-version', lambda: promote(L, scripts, 106))
    promote(L, scripts, 107)
    ok(L.load(scripts).lock['sequence'] == 7, 'a newer tag is accepted after a rollback')

    # --- monotonic promotion
    scripts = fresh(L, tmp, 'mono')
    promote(L, scripts, 106)
    refuses('the same tag again', 'lock-version', lambda: promote(L, scripts, 106))
    refuses('a lower tag', 'lock-version', lambda: promote(L, scripts, 105))
    seed, std, runtime, registration = seed_for(107)
    seed['sha256'] = L.load(scripts).lock['seed']['sha256']
    refuses('a new tag carrying an old seed digest', 'lock-version',
            lambda: L.promote(scripts, seed, std, runtime, sha('r'), registration))
    refuses('a promotion without a qualification receipt', 'lock-qualification',
            lambda: promote(L, scripts, 107, qualification=None))
    ok(L.load(scripts).lock['sequence'] == 2, 'a refused promotion leaves the lock where it was')

    # --- sequence and parent chain on a hand-built step
    scripts = fresh(L, tmp, 'steps')
    loaded = L.load(scripts)
    seed, std, runtime, registration = seed_for(105)
    good = L.new_lock(loaded.chain, 'promote', chain='jar', seed=seed, std=std, runtime=runtime,
                      registration=registration,
                      lineage={'parent_receipt_sha256': loaded.lock['lineage']['qualification_sha256'],
                               'qualification_sha256': sha('r')})
    for name, code, change in (
            ('a skipped sequence number', 'lock-sequence', lambda x: x.update(sequence=3)),
            ('a forged parent digest', 'lock-parent', lambda x: x['lineage'].update(parent_lock_sha256=sha('x'))),
            ('a wrong parent receipt', 'lock-parent', lambda x: x['lineage'].update(parent_receipt_sha256=sha('y'))),
            ('a null qualification', 'lock-qualification', lambda x: x['lineage'].update(qualification_sha256=None)),
            ('an unknown chain', 'lock-chain', lambda x: x.update(chain='both')),
            ('a promotion that switches the chain', 'lock-chain', lambda x: x.update(chain='native')),
            ('a boolean sequence', 'lock-sequence', lambda x: x.update(sequence=True)),
            ('an unknown field', 'schema', lambda x: x.update(extra=1)),
            ('a candidate state', 'lineage', lambda x: x.update(state='candidate')),
            ('an initial transition after the first', 'lock-transition',
             lambda x: x['lineage'].update(transition='initial', parent_receipt_sha256=None)),
            ('a rollback field on a promotion', 'lock-rollback', lambda x: x['lineage'].update(rolled_back_to=1))):
        bad = copy.deepcopy(good)
        change(bad)
        refuses(name, code, lambda bad=bad: L.commit_step(scripts, loaded.chain, bad))
    ok(L.load(scripts).lock['sequence'] == 1, 'refused steps wrote nothing')

    # --- rollback rules
    scripts = fresh(L, tmp, 'rollback')
    promote(L, scripts, 105)
    promote(L, scripts, 106)
    for name, target in (('a rollback to the current sequence', 3), ('a rollback to a sequence that does not exist', 9),
                         ('a rollback to the candidate', 0)):
        refuses(name, 'lock-rollback', lambda target=target: L.rollback(scripts, target, 'bad'))
    loaded = L.load(scripts)
    old = loaded.chain[1][0]
    hand = L.new_lock(loaded.chain, 'rollback', chain='jar', seed=old['seed'], std=old['std'], runtime=old['runtime'],
                      registration=old['registration'],
                      lineage={'parent_receipt_sha256': loaded.lock['lineage']['qualification_sha256'],
                               'qualification_sha256': old['lineage']['qualification_sha256']})
    hand['lineage'].update(rolled_back_from=3, rolled_back_to=1, reason='bad')
    for name, change in (('a rollback naming the wrong abandoned sequence', {'rolled_back_from': 2}),
                         ('a rollback to its own sequence', {'rolled_back_to': 3})):
        broken = copy.deepcopy(hand)
        broken['lineage'].update(change)
        refuses(name, 'lock-rollback', lambda broken=broken: L.commit_step(scripts, loaded.chain, broken))
    broken = copy.deepcopy(hand)
    broken.update(seed=loaded.chain[2][0]['seed'], std=loaded.chain[2][0]['std'], runtime=loaded.chain[2][0]['runtime'],
                  registration=loaded.chain[2][0]['registration'])
    refuses('a rollback that restores a different seed than it names', 'lock-rollback',
            lambda: L.commit_step(scripts, loaded.chain, broken))
    refuses('a rollback without a reason keyword', 'lock-reason', lambda: L.rollback(scripts, 2, 'Bad Reason'))
    first = L.load(scripts).chain[1][0]['seed']
    L.revoke(scripts, first['sha256'], 'compromised')
    refuses('a rollback to a revoked seed', 'seed-revoked', lambda: L.rollback(scripts, 1, 'bad'))

    # --- revocation: a revoked digest never becomes the seed again, and one in force stops everything
    scripts = fresh(L, tmp, 'revoke')
    promote(L, scripts, 105)
    seed, std, runtime, registration = seed_for(106)
    L.revoke(scripts, seed['sha256'], 'withdrawn')
    refuses('promoting a revoked digest', 'seed-revoked',
            lambda: L.promote(scripts, seed, std, runtime, sha('r'), registration))
    ok(L.load(scripts).lock['sequence'] == 2, 'the refused promotion left the lock')
    L.revoke(scripts, L.load(scripts).lock['seed']['sha256'], 'withdrawn')
    refuses('the seed in force being revoked', 'seed-revoked', lambda: L.load(scripts))
    refuses('a duplicate revocation', 'revoked', lambda: L.revoke(scripts, seed['sha256'], 'again'))
    (scripts / 'native-seed-revoked.txt').write_bytes(b'')
    for name, raw in (('an unsorted list', f'{"f" * 64} a\n{"0" * 64} b\n'.encode()),
                      ('a missing final newline', f'{"0" * 64} a'.encode()),
                      ('a malformed line', b'not a digest reason\n'),
                      ('a duplicated digest', f'{"0" * 64} a\n{"0" * 64} a\n'.encode())):
        (scripts / 'native-seed-revoked.txt').write_bytes(raw)
        refuses(name, 'revoked', lambda: L.load(scripts))
    (scripts / 'native-seed-revoked.txt').write_bytes(b'')

    # --- tampering with the records
    scripts = fresh(L, tmp, 'tamper')
    promote(L, scripts, 105)
    promote(L, scripts, 106)
    pristine = read_all(scripts)

    def reset():
        shutil.rmtree(scripts)
        for rel, data in pristine.items():
            (scripts / rel).parent.mkdir(parents=True, exist_ok=True)
            (scripts / rel).write_bytes(data)

    def tamper(name, code, change):
        reset()
        change()
        refuses(name, code, lambda: L.load(scripts))
        reset()

    lock_path = scripts / 'native-seed-lock.json'
    hist = scripts / 'native-seed-history'
    ok(L.load(scripts).lock['sequence'] == 3, 'the pristine records load')
    tamper('a re-printed lock', 'lock-canonical', lambda: edit_lock(scripts, lambda v: None, canonical=False))
    tamper('a duplicate key in the lock', 'schema',
           lambda: lock_path.write_bytes(lock_path.read_bytes().replace(b'"chain":"jar"', b'"chain":"jar","chain":"jar"')))
    tamper('an extra lock field', 'schema', lambda: edit_lock(scripts, lambda v: v.update(extra=1)))
    tamper('a lock with a lower sequence', 'lock-history', lambda: edit_lock(scripts, lambda v: v.update(sequence=2)))
    tamper('a lock with a forged parent', 'lock-parent',
           lambda: edit_lock(scripts, lambda v: v['lineage'].update(parent_lock_sha256=sha('forged'))))
    tamper('a history record with one byte changed', 'lock-parent',
           lambda: (hist / '2.json').write_bytes((hist / '2.json').read_bytes().replace(b'"chain":"jar"', b'"chain": "jar"')))
    tamper('a deleted history record', 'lock-history', lambda: (hist / '1.json').unlink())
    tamper('a deleted history record 0', 'lock-history', lambda: (hist / '0.json').unlink())
    tamper('a foreign history file', 'lock-history', lambda: (hist / 'extra.json').write_bytes(b'{}'))
    tamper('a history directory gone', 'lock-history', lambda: shutil.rmtree(hist))
    tamper('a history record from the future', 'lock-history', lambda: (hist / '3.json').write_bytes(b'{}'))
    tamper('a lock turned into a candidate', 'lineage',
           lambda: edit_lock(scripts, lambda v: v.update(state='candidate')))
    tamper('the lock missing while history exists', 'lock-missing', lambda: lock_path.unlink())
    tamper('a symbolic link for the lock', 'source-type',
           lambda: (lock_path.rename(scripts / 'real.json'), lock_path.symlink_to('real.json')))
    reset()
    ok(L.load(scripts).lock['sequence'] == 3, 'the records load again after the controls')

    # --- interruption: every cut point converges to the clean result
    clean = fresh(L, tmp, 'clean')
    promote(L, clean, 105)
    expected = read_all(clean)
    for point in ('before-history', 'after-history', 'after-lock'):
        scripts = fresh(L, tmp, 'cut-' + point)
        try:
            promote(L, scripts, 105, hook=interrupt_at(point))
            raise AssertionError('the hook did not fire')
        except Interrupt:
            pass
        ok(L.load(scripts).lock['sequence'] in (1, 2), f'the records verify after a cut at {point}')
        promote(L, scripts, 105) if L.load(scripts).lock['sequence'] == 1 else None
        ok(read_all(scripts) == expected, f'a cut at {point} converges to the uninterrupted result')
    scripts = fresh(L, tmp, 'pollute')
    (scripts / 'native-seed-history/1.json').write_bytes(b'{"polluted":true}')
    refuses('a history record that differs before the step', 'lock-history', lambda: L.load(scripts))
    scripts = Path(tmp) / 'pollute-initial'
    (scripts / 'native-seed-history').mkdir(parents=True)
    (scripts / 'native-seed-history/0.json').write_bytes(b'{"polluted":true}')
    refuses('an initial step over a different record 0', 'lock-history',
            lambda: L.initial(scripts, CANDIDATE, sha('receipt initial')))
    scripts = fresh(L, tmp, 'lost-history')
    promote(L, scripts, 105)
    (scripts / 'native-seed-history/1.json').unlink()
    refuses('a lock swapped in with its history missing', 'lock-history', lambda: L.load(scripts))

    # --- growth since a base revision: an edit of the newest lock in place, or a dropped revocation
    scripts = fresh(L, tmp, 'base')
    promote(L, scripts, 105)
    base_lock = (scripts / 'native-seed-lock.json').read_bytes()
    L.revoke(scripts, sha('some old seed'), 'withdrawn')
    base_revoked = (scripts / 'native-seed-revoked.txt').read_bytes()
    promote(L, scripts, 106)
    grown = L.load(scripts)
    L.check_base(grown, base_lock, base_revoked)
    L.check_base(grown, None, None)
    ok(True, 'records that only grew pass the base comparison, and a base without records constrains nothing')
    edited = fresh(L, tmp, 'base-edited')
    promote(L, edited, 105)
    edit_lock(edited, lambda v: v['registration'].update(evidence_sha256=sha('forged')))
    refuses('the newest lock edited in place after the base', 'lock-base',
            lambda: L.check_base(L.load(edited), base_lock, None))
    (scripts / 'native-seed-revoked.txt').write_bytes(f'{sha("another old seed")} withdrawn\n'.encode())
    refuses('a revocation dropped after the base', 'revoked-base',
            lambda: L.check_base(L.load(scripts), None, base_revoked))
    (scripts / 'native-seed-revoked.txt').write_bytes(f'{sha("some old seed")} reworded\n'.encode())
    refuses('a revocation reworded after the base', 'revoked-base',
            lambda: L.check_base(L.load(scripts), None, base_revoked))

    # --- a release lock is never a candidate
    empty = Path(tmp) / 'release-empty'
    empty.mkdir()
    shutil.copyfile(CANDIDATE, empty / 'native-seed-lock.json')
    refuses('a candidate under the lock name', 'lock-canonical', lambda: L.release_lock(empty / 'native-seed-lock.json'))
    (empty / 'native-seed-lock.json').write_bytes(c.canonical(json.loads(CANDIDATE.read_bytes())))
    refuses('a canonical candidate under the lock name', 'schema', lambda: L.release_lock(empty / 'native-seed-lock.json'))
    refuses('no lock at all', 'lock-missing', lambda: L.release_lock(empty / 'nothing' / 'native-seed-lock.json'))
    refuses('a lock under another name', 'lock-missing', lambda: L.release_lock(CANDIDATE))


# ---------------------------------------------------------------- seeds (ELF)

FAKE = r'''
#include <stdio.h>
#include <string.h>
int main(int n, char **v) {
  if (n == 2 && !strcmp(v[1], "--version")) { puts("dawnc " VERSION " (native) " SHORT); return 0; }
  if (n == 4 && !strcmp(v[1], "version") && !strcmp(v[2], "-m")) { printf("\tbuild\t" FULL "\n"); return 0; }
  return 2;
}
'''


def fake_elf(work, version, build):
    source = work / 'fake.c'
    source.write_text(FAKE)
    binary = work / f'fake-{version}-{build[3:7]}'
    subprocess.run(['cc', '-static', '-O0', f'-DVERSION="{version}"', f'-DSHORT="{build[:15]}"',
                    f'-DFULL="{build}"', str(source), '-o', str(binary)], check=True, capture_output=True)
    return binary.read_bytes()


def seed_suite(L, tmp, elf, wrong_version, wrong_build):
    build = 'b1:' + 'd' * 64
    lock = {'seed': {'kind': 'native-elf', 'tag': 'v0.105.0', 'commit': 'a' * 40, 'asset': c.ASSET,
                     'sha256': c.digest(elf), 'size': len(elf), 'target': c.TARGET,
                     'version': 'dawnc 0.105.0 (native)', 'build_id': build}}
    calls = []

    def fetch(seed, data=elf):
        calls.append(seed['tag'])
        return data

    cache = Path(tmp) / 'cache'
    path = L.cached_seed(lock, cache, fetch)
    ok(path == cache / 'v0.105.0' / c.ASSET and calls == ['v0.105.0'], 'the locked seed is fetched into its tag directory')
    ok(L.cached_seed(lock, cache, fetch) == path and len(calls) == 1, 'a verified cache hit does not fetch again')
    os.chmod(path, 0o755)
    path.write_bytes(elf[:-1] + bytes([elf[-1] ^ 1]))
    refuses('a cache whose bytes were changed', 'seed-digest', lambda: L.cached_seed(lock, cache, fetch))
    ok(len(calls) == 1, 'a tampered cache is an error, not a reason to download again')
    for name, data, code in (('a download of other bytes', elf[:-1] + bytes([elf[-1] ^ 1]), 'seed-digest'),
                             ('a download that is a jar', b'PK\x03\x04' + b'\0' * 100, 'seed-digest'),
                             ('a download truncated', elf[:100], 'seed-digest')):
        refuses(name, code, lambda data=data: L.cached_seed(lock, Path(tmp) / ('c-' + name), lambda s: data))
        ok(not (Path(tmp) / ('c-' + name) / 'v0.105.0' / c.ASSET).exists(), name + ' leaves nothing in the cache')
    for name, data, field, code in (
            ('a seed whose version banner differs from the lock', wrong_version, 'sha256', 'seed-identity'),
            ('a seed whose build ID differs from the lock', wrong_build, 'sha256', 'seed-identity')):
        other = copy.deepcopy(lock)
        other['seed'].update(sha256=c.digest(data), size=len(data))
        refuses(name, code, lambda other=other, data=data: L.cached_seed(other, Path(tmp) / ('c-' + name),
                                                                       lambda s: data))
    # DAWN_NATIVE_SEED takes an ELF and refuses a jar
    jar = Path(tmp) / 'seed.jar'
    jar.write_bytes(b'PK\x03\x04' + b'\0' * 100)
    refuses('a jar given as the native seed', 'seed-override', lambda: L.override_seed(jar))
    link = Path(tmp) / 'link'
    link.symlink_to(path)
    refuses('a symbolic link as the native seed', 'seed-override', lambda: L.override_seed(link))
    ok(L.override_seed(path) == path, 'an ELF file is accepted as the native seed override')


def qualification_suite(tmp):
    spec = importlib.util.spec_from_file_location('advance_native_seed', ADVANCE)
    adv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adv)
    commit = 'c' * 40
    from native_seed import inputs
    subject = c.read_lock(CANDIDATE)
    compilation = {'seed': inputs.seed_identity(subject)}
    receipt = c.canonical({'kind': 'native-qualification-package', 'source_commit': commit,
                           'compilation': compilation, 'compilation_sha256': c.digest(c.canonical(compilation)),
                           'qualified_seed_sha256': subject['seed']['sha256'],
                           'seed_lock_sha256': c.digest(c.canonical(subject)), 'coverage': ['Q' + str(i) for i in range(1, 11)]})

    def build(name, reason='seed-promotion', mutate=None):
        directory = Path(tmp) / name
        directory.mkdir()
        files = {'request.json': {'schema': 1, 'kind': 'native-qualification-request', 'commit': commit,
                                  'reason': reason, 'entry_sha256': sha('entry'),
                                  'seed_lock_sha256': c.digest(c.canonical(subject))},
                 'cold/seed-lock.json': subject,
                 'completed.json': {'source_commit': commit, 'receipt_sha256': c.digest(receipt),
                                    'checks': [{'name': n, 'exit_code': 0} for n in adv.RUN_STEPS],
                                    'production_authorized': False},
                 'verified.json': {'source_commit': commit, 'receipt_sha256': c.digest(receipt),
                                   'checks': [{'name': n, 'exit_code': 0} for n in adv.VERIFY_STEPS],
                                   'production_authorized': False}}
        if mutate:
            mutate(files)
        for file, value in files.items():
            if value is not None:
                (directory / file).parent.mkdir(parents=True, exist_ok=True)
                (directory / file).write_bytes(c.canonical(value))
        (directory / 'receipt.json').write_bytes(receipt)
        return directory

    ok(adv.qualification_receipt(build('q-good'), 'seed-promotion') == (c.digest(receipt), commit),
       'a complete verified qualification yields its receipt digest')
    refuses('a qualification run for another reason', 'lock-qualification',
            lambda: adv.qualification_receipt(build('q-reason', reason='final-inputs'), 'seed-promotion'))
    refuses('a qualification that was never independently verified', 'source-missing',
            lambda: adv.qualification_receipt(build('q-unverified', mutate=lambda f: f.update({'verified.json': None})),
                                              'seed-promotion'))
    refuses('a step that failed', 'lock-qualification', lambda: adv.qualification_receipt(
        build('q-failed', mutate=lambda f: f['completed.json']['checks'][3].update(exit_code=1)), 'seed-promotion'))
    refuses('a step that is missing', 'lock-qualification', lambda: adv.qualification_receipt(
        build('q-short', mutate=lambda f: f['completed.json']['checks'].pop()), 'seed-promotion'))
    refuses('another receipt', 'lock-qualification', lambda: adv.qualification_receipt(
        build('q-other', mutate=lambda f: f['verified.json'].update(receipt_sha256=sha('other'))), 'seed-promotion'))
    refuses('production authorized by the evidence', 'lock-qualification', lambda: adv.qualification_receipt(
        build('q-auth', mutate=lambda f: f['completed.json'].update(production_authorized=True)), 'seed-promotion'))


# -------------------------------------------------------------------- mutants

MUTANTS = (
    ('monotonic promotion', "c.require(version_key(child['seed']['tag']) > newest,", "c.require(True,"),
    ('reuse of an old seed digest', "c.require(all(child['seed']['sha256'] != s['sha256'] for s in seeds),",
     "c.require(True,"),
    ('revocation at load', "c.require(current['seed']['sha256'] not in revoked,", "c.require(True,"),
    ('parent digest chaining', "c.require(lineage['parent_lock_sha256'] == c.digest(parent_raw),", "c.require(True,"),
    ('sequence numbering', "c.require(child['sequence'] == index,", "c.require(True,"),
    ('canonical form', "c.require(raw == c.canonical(value), 'lock-canonical'", "c.require(True, 'lock-canonical'"),
    ('exact history', "c.require(sorted(names) == sorted(expected), 'lock-history'", "c.require(True, 'lock-history'"),
    ('unreferenced history record', "c.require(history_bytes(history_dir, sequence) == raw, 'lock-history',",
     "c.require(True, 'lock-history',"),
    ('qualification required', "c.require(lineage['qualification_sha256'] is not None, 'lock-qualification',",
     "c.require(True, 'lock-qualification',"),
    ('rollback target range', "c.require(lineage['rolled_back_from'] == index - 1 and 1 <= target < index - 1,",
     "c.require(True,"),
    ('rollback restores the seed', "c.require(child[key] == old[key], 'lock-rollback',", "c.require(True, 'lock-rollback',"),
    ('history written before the lock', "write_atomic(record, old_raw)", "pass"),
    ('pollution of an existing record', "c.require(c.regular_bytes(record) == old_raw, 'lock-history',",
     "c.require(True, 'lock-history',"),
    ('base: lock still in the chain',
     "c.require(base['sequence'] < len(loaded.chain) and loaded.chain[base['sequence']][1] == base_lock_raw,",
     "c.require(True,"),
    ('base: revocations kept',
     "c.require(all(loaded.revoked.get(k) == v for k, v in base_revoked.items()), 'revoked-base',",
     "c.require(True, 'revoked-base',"),
    ('revocation list order', "c.require(match[1] > previous,", "c.require(True,"),
    ('cache re-verification', "verify_seed_bytes(c.regular_bytes(target), lock)", "pass"),
    ('seed digest', "c.require(len(data) == seed['size'] and c.digest(data) == seed['sha256'], 'seed-digest',",
     "c.require(True, 'seed-digest',"),
    ('seed identity', "c.require((version, build_id) == (seed['version'], seed['build_id']), 'seed-identity',",
     "c.require(True, 'seed-identity',"),
    ('override must be an ELF', "c.require(head == b'\\x7fELF', 'seed-override',", "c.require(True, 'seed-override',"),
)


def load_mutant(source, name, tmp):
    path = Path(tmp) / f'lockchain_{name}.py'
    path.write_text(source)
    spec = importlib.util.spec_from_file_location('native_seed.lockchain_mutant', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_all(L, tmp, elf_inputs):
    suite(L, tmp)
    seed_suite(L, tmp, *elf_inputs)


def main():
    with tempfile.TemporaryDirectory(prefix='native-seed-lock-test-') as temporary:
        tmp = Path(temporary)
        work = tmp / 'elf'
        work.mkdir()
        elf = fake_elf(work, '0.105.0', 'b1:' + 'd' * 64)
        inputs = (elf, fake_elf(work, '0.105.1', 'b1:' + 'd' * 64), fake_elf(work, '0.105.0', 'b1:' + 'e' * 64))
        (tmp / 'base').mkdir()
        run_all(real_lockchain, tmp / 'base', inputs)
        qualification_suite(tmp)
        source = (HERE / 'native_seed/lockchain.py').read_text()
        # The only environment these three files read is the release origin and
        # the seed override; a new DAWN_* name would be a new way around a check.
        import re
        allowed = {'DAWN_RELEASE_BASE_URL', 'DAWN_NATIVE_SEED', 'DAWN_SEED_ORIGIN', 'DAWN_SEED_CHAIN', 'DAWN_SEED'}
        for name in ('native_seed/lockchain.py', 'native-seed-chain.py', 'advance-native-seed.py'):
            names = set(re.findall(r'DAWN_[A-Z_]+', (HERE / name).read_text()))
            ok(names <= allowed, f'{name} reads no environment variable beyond the documented ones: {names - allowed}')
            text = (HERE / name).read_text().upper()
            for word in ('UNVERIFIED', 'INSECURE', 'NO_VERIFY', 'NOVERIFY'):
                ok(word not in text, f'{name} has no {word.lower()} switch')
        for number, (name, old, new) in enumerate(MUTANTS):
            ok(source.count(old) == 1, f'mutant anchor for {name} matches once')
            (tmp / f'm{number}').mkdir()
            mutant = load_mutant(source.replace(old, new), str(number), tmp)
            try:
                run_all(mutant, tmp / f'm{number}', inputs)
            except (AssertionError, c.Rejected, OSError, KeyError, ValueError):
                ok(True, f'mutant "{name}" turns the suite red')
            else:
                raise AssertionError(f'mutant "{name}" survived: the suite does not guard it')
    print(f'OK: {passed} native seed lock assertions, {len(MUTANTS)} mutants')


if __name__ == '__main__':
    main()
