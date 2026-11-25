"""The qualified native seed lock: one strict reader, one transition checker.

Why one checker for both reading and writing: a lock is trustworthy because
every step from the historical candidate to today's file satisfies the same
rules, so the launcher, the release workflow, the light gate and the promotion
tool all call `load`, and every transition (initial, promote, rollback, chain)
is validated by running that same verification over the chain extended by the
proposed lock. A transition rule that only the writer enforced would be one
hand edit away from a lock the reader accepts.

Why the lock is the only truth for the default chain: the `chain` field is
read here and nowhere else. The environment variable DAWN_SEED_CHAIN is an
explicit override handled by the launcher; nothing falls back from one chain
to the other (docs/native-seed-cutover-design.md section 10, item 5).

Why history holds original bytes and the next lock names their digest:
`lineage.parent_lock_sha256` makes the files a hash chain, so editing any
history file, or the current lock without a matching next record, is visible
without a signature. The lock must also be in canonical form, so a re-printed
file (whitespace, key order) is a change rather than an equivalent spelling.

Why a revocation list is checked at load, not only at promotion: a seed that
becomes untrusted after it was promoted must stop being usable even though no
lock transition has happened yet. The remedy is a rollback to an earlier,
unrevoked seed; the launcher never picks a different one by itself.
"""

import os
from pathlib import Path
import re
import stat
import tempfile

from native_seed import contract as c

SCRIPTS = Path(__file__).resolve().parents[1]
LOCK_NAME = 'native-seed-lock.json'
HISTORY_NAME = 'native-seed-history'
REVOKED_NAME = 'native-seed-revoked.txt'
CHAINS = ('jar', 'native')
TRANSITIONS = ('initial', 'promote', 'rollback', 'chain')
LOCK_FIELDS = 'schema kind state sequence chain seed std runtime lineage registration'
LINEAGE_FIELDS = ('parent_lock_sha256 parent_receipt_sha256 qualification_sha256 transition '
                  'rolled_back_from rolled_back_to reason')
SEED_FIELDS = 'kind tag commit asset sha256 size target version build_id'
TAG = re.compile(r'v([0-9]+)\.([0-9]+)\.([0-9]+)')
REASON = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')


def paths(scripts_dir=None):
    base = Path(scripts_dir) if scripts_dir is not None else SCRIPTS
    return base / LOCK_NAME, base / HISTORY_NAME, base / REVOKED_NAME


def version_key(tag):
    match = TAG.fullmatch(tag)
    c.require(match is not None, 'seed-identity', f'not a release tag: {tag!r}')
    return tuple(int(x) for x in match.groups())


def is_int(value):
    return type(value) is int


def parse_json(raw, label):
    import json
    try:
        value = json.loads(raw, object_pairs_hook=c.no_duplicates,
                           parse_constant=lambda x: (_ for _ in ()).throw(c.Rejected(f'schema: invalid constant {x}')))
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, c.Rejected):
            raise
        raise c.Rejected(f'schema: {label} is not JSON: {exc}') from exc
    return value


def validate_seed(seed):
    c.fields(seed, SEED_FIELDS, 'seed')
    c.require(seed['kind'] == 'native-elf' and seed['asset'] == c.ASSET, 'seed-kind', 'expected the native ELF asset')
    c.require(seed['target'] == c.TARGET, 'seed-target', 'unsupported seed target')
    c.require(type(seed['tag']) is str and TAG.fullmatch(seed['tag']) and
              seed['version'] == f'dawnc {seed["tag"][1:]} (native)', 'seed-identity', 'seed tag/version mismatch')
    c.oid(seed['commit'], 'seed commit')
    c.sha(seed['sha256'], 'seed')
    c.require(is_int(seed['size']) and seed['size'] > 0, 'schema', 'invalid seed size')
    c.require(type(seed['build_id']) is str and re.fullmatch('b1:[0-9a-f]{64}', seed['build_id']),
              'seed-identity', 'invalid full build ID')


def validate_qualified(value):
    """Shape only. Whether the steps between locks are legal is `verify_chain`."""
    c.fields(value, LOCK_FIELDS, 'lock')
    c.require(is_int(value['schema']) and value['schema'] == 2 and value['kind'] == 'native-seed-lock',
              'schema', 'expected native-seed-lock schema 2')
    c.require(value['state'] == 'qualified', 'lineage', 'a consumed lock must be qualified')
    c.require(is_int(value['sequence']) and value['sequence'] >= 1, 'lock-sequence', 'sequence starts at 1')
    c.require(value['chain'] in CHAINS, 'lock-chain', 'chain must be jar or native')
    validate_seed(value['seed'])
    for key in ('std', 'runtime'):
        c.validate_identity(value[key], key)
        c.require(value[key]['commit'] == value['seed']['commit'], key + '-pairing', 'seed commit mismatch')
    lineage = value['lineage']
    c.fields(lineage, LINEAGE_FIELDS, 'lineage')
    c.sha(lineage['parent_lock_sha256'], 'parent lock')
    c.require(lineage['qualification_sha256'] is not None, 'lock-qualification',
              'a qualified lock names its qualification receipt')
    c.sha(lineage['qualification_sha256'], 'qualification')
    if lineage['parent_receipt_sha256'] is not None:
        c.sha(lineage['parent_receipt_sha256'], 'parent receipt')
    transition = lineage['transition']
    c.require(transition in TRANSITIONS, 'lock-transition', 'unknown transition')
    for key in ('rolled_back_from', 'rolled_back_to'):
        c.require((lineage[key] is None) == (transition != 'rollback') and
                  (lineage[key] is None or (is_int(lineage[key]) and lineage[key] >= 1)),
                  'lock-rollback', key + ' belongs to rollback only')
    c.require(lineage['reason'] is None if transition in ('initial', 'promote') else
              type(lineage['reason']) is str and REASON.fullmatch(lineage['reason']) is not None,
              'lock-reason', 'rollback and chain transitions carry a reason keyword')
    c.require((transition == 'initial') == (lineage['parent_receipt_sha256'] is None),
              'lineage', 'only the first qualified lock has no parent receipt')
    registration = value['registration']
    c.fields(registration, 'kind metadata evidence_sha256', 'registration')
    c.sha(registration['evidence_sha256'], 'registration evidence')
    c.require((registration['kind'], registration['metadata']) in
              (('historical-v0.104.0', 'absent'), ('release', 'present')),
              'schema', 'unknown registration')


def parse_revoked(raw):
    c.require(type(raw) is bytes and (raw == b'' or raw.endswith(b'\n')), 'revoked', 'list must be newline terminated')
    entries = {}
    previous = ''
    for line in raw.decode('utf-8', errors='strict').splitlines():
        match = re.fullmatch('([0-9a-f]{64}) ([a-z0-9][a-z0-9-]*)', line)
        c.require(match is not None, 'revoked', f'malformed line: {line!r}')
        c.require(match[1] > previous, 'revoked', 'list must be sorted by digest and free of duplicates')
        previous = match[1]
        entries[match[1]] = match[2]
    return entries


def read_revoked(revoked_path):
    path = Path(revoked_path)
    if not path.exists() and not path.is_symlink():
        return {}
    return parse_revoked(c.regular_bytes(path))


def history_bytes(history_dir, sequence):
    return c.regular_bytes(Path(history_dir) / f'{sequence}.json')


def verify_step(chain, index, revoked):
    """Check item `index` of `chain` (list of (value, raw)) against everything before it."""
    (parent, parent_raw), (child, _) = chain[index - 1], chain[index]
    lineage = child['lineage']
    c.require(child['sequence'] == index, 'lock-sequence', f'sequence {child["sequence"]} where {index} expected')
    c.require(lineage['parent_lock_sha256'] == c.digest(parent_raw), 'lock-parent',
              'parent digest does not match the preceding record')
    transition = lineage['transition']
    if index == 1:
        c.require(transition == 'initial' and parent['state'] == 'candidate', 'lock-transition',
                  'the first qualified lock must follow the candidate')
        c.require(child['chain'] == 'jar', 'lock-chain', 'the first qualified lock keeps the JAR chain as default')
        for key in ('seed', 'std', 'runtime'):
            c.require(child[key] == parent[key], 'lock-initial', f'the initial lock changes {key}')
        c.require(child['registration']['kind'] == parent['registration']['kind'] and
                  child['registration']['evidence_sha256'] == parent['registration']['evidence_sha256'],
                  'lock-initial', 'the initial lock changes the registration')
        return
    c.require(transition != 'initial', 'lock-transition', 'initial is only the first transition')
    c.require(lineage['parent_receipt_sha256'] == parent['lineage']['qualification_sha256'], 'lock-parent',
              'parent receipt is not the preceding qualification')
    seeds = [item[0]['seed'] for item in chain[:index]]
    if transition == 'promote':
        newest = max(version_key(s['tag']) for s in seeds)
        c.require(version_key(child['seed']['tag']) > newest, 'lock-version',
                  'a promotion needs a tag above every seed ever locked')
        c.require(all(child['seed']['sha256'] != s['sha256'] for s in seeds), 'lock-version',
                  'a promotion cannot reuse an earlier seed')
        c.require(child['chain'] == parent['chain'], 'lock-chain', 'a promotion keeps the chain')
        c.require(child['registration']['kind'] == 'release', 'lock-registration',
                  'a promoted seed comes from a registered release')
    elif transition == 'rollback':
        target = lineage['rolled_back_to']
        c.require(lineage['rolled_back_from'] == index - 1 and 1 <= target < index - 1, 'lock-rollback',
                  'rollback must name the abandoned sequence and an earlier qualified one')
        old = chain[target][0]
        for key in ('seed', 'std', 'runtime', 'registration'):
            c.require(child[key] == old[key], 'lock-rollback', f'rollback does not restore {key}')
        c.require(child['seed']['sha256'] != parent['seed']['sha256'], 'lock-rollback', 'rollback to the same seed')
        c.require(lineage['qualification_sha256'] == old['lineage']['qualification_sha256'], 'lock-rollback',
                  'rollback keeps the restored seed\'s own qualification')
        c.require(child['chain'] == parent['chain'], 'lock-chain', 'a rollback keeps the chain')
    else:
        for key in ('seed', 'std', 'runtime', 'registration'):
            c.require(child[key] == parent[key], 'lock-chain', f'a chain change cannot touch {key}')
        c.require(lineage['qualification_sha256'] == parent['lineage']['qualification_sha256'], 'lock-chain',
                  'a chain change keeps the qualification')
        c.require(child['chain'] != parent['chain'], 'lock-chain', 'a chain change must change the chain')


def verify_chain(chain, revoked):
    """chain[0] is the candidate; the last item is the lock in force."""
    candidate = chain[0][0]
    c.validate_lock(candidate)
    for index, (value, _) in enumerate(chain[1:], 1):
        validate_qualified(value)
        verify_step(chain, index, revoked)
    current = chain[-1][0]
    c.require(current['seed']['sha256'] not in revoked, 'seed-revoked',
              f'the seed in force ({current["seed"]["tag"]}) is revoked ({revoked.get(current["seed"]["sha256"])})')


class Loaded:
    def __init__(self, scripts_dir, chain, revoked):
        self.scripts_dir, self.chain, self.revoked = Path(scripts_dir), chain, revoked

    @property
    def lock(self):
        return self.chain[-1][0]

    @property
    def raw(self):
        return self.chain[-1][1]


def present(scripts_dir=None):
    """Any of the three records exists: the launcher must then verify them."""
    return any(p.exists() or p.is_symlink() for p in paths(scripts_dir))


def load(scripts_dir=None):
    lock_path, history_dir, revoked_path = paths(scripts_dir)
    c.require(lock_path.exists() or lock_path.is_symlink(), 'lock-missing',
              'no qualified native seed lock (scripts/' + LOCK_NAME + ')')
    raw = c.regular_bytes(lock_path)
    value = parse_json(raw, LOCK_NAME)
    c.require(raw == c.canonical(value), 'lock-canonical', 'the lock is not in canonical form')
    validate_qualified(value)
    sequence = value['sequence']
    c.require(history_dir.is_dir() and not history_dir.is_symlink(), 'lock-history', 'history directory missing')
    names = sorted(p.name for p in history_dir.iterdir())
    expected = [f'{i}.json' for i in range(sequence)]
    # A promotion writes history before it swaps the lock, so a crash leaves
    # exactly one extra record: this lock's own bytes. Anything else is foreign.
    if f'{sequence}.json' in names:
        c.require(history_bytes(history_dir, sequence) == raw, 'lock-history',
                  'an unreferenced history record differs from the lock')
        expected.append(f'{sequence}.json')
    c.require(sorted(names) == sorted(expected), 'lock-history', 'history is not exactly records 0 to sequence-1')
    chain = []
    for index in range(sequence):
        item = history_bytes(history_dir, index)
        chain.append((parse_json(item, f'{index}.json'), item))
    chain.append((value, raw))
    revoked = read_revoked(revoked_path)
    verify_chain(chain, revoked)
    return Loaded(scripts_dir or SCRIPTS, chain, revoked)


def release_lock(lock_path):
    """What a release may be built from: the verified lock in force, never a candidate."""
    lock_path = Path(lock_path)
    c.require(lock_path.name == LOCK_NAME, 'lock-missing', f'a release lock is named {LOCK_NAME}')
    loaded = load(lock_path.parent)
    c.require(loaded.lock['lineage']['qualification_sha256'] is not None, 'lock-qualification',
              'a release needs a qualified seed')
    return loaded.lock


# --------------------------------------------------------------- transitions

def write_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix='.native-seed.')
    try:
        with os.fdopen(handle, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    except BaseException:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def commit_step(scripts_dir, chain, child, hook=None):
    """Validate `child` as the next link, then history first, lock last."""
    lock_path, history_dir, revoked_path = paths(scripts_dir)
    validate_qualified(child)
    raw = c.canonical(child)
    revoked = read_revoked(revoked_path)
    extended = chain + [(child, raw)]
    verify_chain(extended, revoked)
    old_value, old_raw = chain[-1]
    record = history_dir / f'{old_value["sequence"]}.json'
    if record.exists():
        c.require(c.regular_bytes(record) == old_raw, 'lock-history', 'history already holds different bytes')
    else:
        if hook:
            hook('before-history')
        write_atomic(record, old_raw)
    if hook:
        hook('after-history')
    write_atomic(lock_path, raw)
    if hook:
        hook('after-lock')
    return child


def new_lock(parent_chain, transition, **parts):
    parent, parent_raw = parent_chain[-1]
    lock = {'schema': 2, 'kind': 'native-seed-lock', 'state': 'qualified',
            'sequence': (parent['sequence'] + 1) if parent['state'] == 'qualified' else 1}
    lock.update(parts)
    lock['lineage'] = dict(parent_lock_sha256=c.digest(parent_raw), rolled_back_from=None,
                           rolled_back_to=None, reason=None, transition=transition, **lock['lineage'])
    return lock


def start_chain(scripts_dir, candidate_path):
    """The chain as stored, or just the candidate when no lock exists yet."""
    lock_path = paths(scripts_dir)[0]
    if lock_path.exists() or lock_path.is_symlink():
        return load(scripts_dir).chain
    raw = c.regular_bytes(candidate_path)
    return [(parse_json(raw, 'candidate'), raw)]


def initial(scripts_dir, candidate_path, qualification_sha256, hook=None):
    chain = start_chain(scripts_dir, candidate_path)
    c.require(len(chain) == 1, 'lock-transition', 'a lock already exists; initial is only the first transition')
    candidate = chain[0][0]
    c.validate_lock(candidate)
    child = new_lock(chain, 'initial', chain='jar', seed=candidate['seed'], std=candidate['std'],
                     runtime=candidate['runtime'], registration=candidate['registration'],
                     lineage={'parent_receipt_sha256': None, 'qualification_sha256': qualification_sha256})
    return commit_step(scripts_dir, chain, child, hook)


def promote(scripts_dir, seed, std, runtime, qualification_sha256, registration, hook=None):
    loaded = load(scripts_dir)
    parent = loaded.lock
    child = new_lock(loaded.chain, 'promote', chain=parent['chain'], seed=seed, std=std, runtime=runtime,
                     registration=registration,
                     lineage={'parent_receipt_sha256': parent['lineage']['qualification_sha256'],
                              'qualification_sha256': qualification_sha256})
    return commit_step(scripts_dir, loaded.chain, child, hook)


def rollback(scripts_dir, target, reason, hook=None):
    loaded = load(scripts_dir)
    parent = loaded.lock
    c.require(is_int(target) and 1 <= target < parent['sequence'], 'lock-rollback',
              'rollback needs an earlier qualified sequence that exists in history')
    old = loaded.chain[target][0]
    c.require(old['seed']['sha256'] not in loaded.revoked, 'seed-revoked', 'a revoked seed cannot be restored')
    child = new_lock(loaded.chain, 'rollback', chain=parent['chain'], seed=old['seed'], std=old['std'],
                     runtime=old['runtime'], registration=old['registration'],
                     lineage={'parent_receipt_sha256': parent['lineage']['qualification_sha256'],
                              'qualification_sha256': old['lineage']['qualification_sha256']})
    child['lineage'].update(rolled_back_from=parent['sequence'], rolled_back_to=target, reason=reason)
    return commit_step(scripts_dir, loaded.chain, child, hook)


def set_chain(scripts_dir, chain_name, reason, hook=None):
    loaded = load(scripts_dir)
    parent = loaded.lock
    child = new_lock(loaded.chain, 'chain', chain=chain_name, seed=parent['seed'], std=parent['std'],
                     runtime=parent['runtime'], registration=parent['registration'],
                     lineage={'parent_receipt_sha256': parent['lineage']['qualification_sha256'],
                              'qualification_sha256': parent['lineage']['qualification_sha256']})
    child['lineage']['reason'] = reason
    return commit_step(scripts_dir, loaded.chain, child, hook)


def revoke(scripts_dir, digest, reason):
    """Append one line. Only ever grows: an existing digest is never rewritten."""
    c.sha(digest, 'revoked seed')
    c.require(REASON.fullmatch(reason) is not None, 'revoked', 'reason is a lowercase keyword')
    _, _, revoked_path = paths(scripts_dir)
    entries = read_revoked(revoked_path)
    c.require(digest not in entries, 'revoked', 'already revoked')
    entries[digest] = reason
    write_atomic(revoked_path, ''.join(f'{k} {entries[k]}\n' for k in sorted(entries)).encode('ascii'))


# ----------------------------------------------------------- seed resolution

def verify_seed_bytes(data, lock, probe_cache=None):
    seed = lock['seed']
    c.require(len(data) == seed['size'] and c.digest(data) == seed['sha256'], 'seed-digest',
              'seed bytes differ from the lock; execution refused')
    c.verify_elf(data)
    version, build_id = c.probe_seed(data, seed['version'], probe_cache=probe_cache)
    c.require((version, build_id) == (seed['version'], seed['build_id']), 'seed-identity',
              'version or build ID differs from the lock')


def cached_seed(lock, cache_root, fetch, probe_cache=None):
    """The locked ELF under cache_root/<tag>/, fetched once, re-verified on every use.

    A cache hit is recomputed from its bytes like a download: a tampered cache
    is an error, not a reason to fetch again and hide it.
    """
    seed = lock['seed']
    directory = Path(cache_root) / seed['tag']
    target = directory / c.ASSET
    if target.exists() or target.is_symlink():
        verify_seed_bytes(c.regular_bytes(target), lock, probe_cache=probe_cache)
        return target
    data = fetch(seed)
    verify_seed_bytes(data, lock, probe_cache=probe_cache)
    directory.mkdir(parents=True, exist_ok=True)
    write_atomic(target, data)
    os.chmod(target, 0o555)
    return target


def override_seed(path):
    """DAWN_NATIVE_SEED: any ELF, never a jar. Its identity is the caller's responsibility."""
    path = Path(path)
    c.require(not path.is_symlink() and path.is_file() and stat.S_ISREG(path.lstat().st_mode),
              'seed-override', 'DAWN_NATIVE_SEED must name a regular, non-symlink file')
    with path.open('rb') as handle:
        head = handle.read(4)
    c.require(head == b'\x7fELF', 'seed-override', 'DAWN_NATIVE_SEED is not an ELF file (a jar belongs to DAWN_SEED)')
    c.verify_elf(c.regular_bytes(path))
    return path


def check_base(loaded, base_lock_raw, base_revoked_raw):
    """The records only grew since a base revision (a pull request's merge base).

    `load` proves the records are a valid chain; it cannot see that the newest
    lock was edited in place, because nothing yet points at it. Against the
    base revision that is visible: the base lock must still be in the chain, at
    its own sequence and byte for byte, and no revocation may have been dropped
    or reworded. None means the base revision had no such record.
    """
    if base_lock_raw is not None:
        base = parse_json(base_lock_raw, 'base lock')
        validate_qualified(base)
        c.require(base['sequence'] < len(loaded.chain) and loaded.chain[base['sequence']][1] == base_lock_raw,
                  'lock-base', 'the lock at the base revision is not in the chain (edited in place or dropped)')
    if base_revoked_raw is not None:
        base_revoked = parse_revoked(base_revoked_raw)
        c.require(all(loaded.revoked.get(k) == v for k, v in base_revoked.items()), 'revoked-base',
                  'a revocation present at the base revision was removed or changed')
