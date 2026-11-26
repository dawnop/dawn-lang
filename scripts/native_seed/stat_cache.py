"""Development-only digest proxies, never a qualification or release input.

Every reuse binds all stat fields and rejects racy timestamps. The self digest
catches damaged cache state; it is not an authenticity signature. A generation
marker and the ordinary receipt checks remain the authority for execution.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import tempfile
import time

from native_seed import contract as c

# Conservative for second-resolution filesystems as well as nanosecond ones.
GRAIN_NS = 1_000_000_000


def index_integrity(payload_raw, expected):
    return c.digest(payload_raw) == expected


def full_link(raw, prefix, suffix, expected):
    return (raw.startswith(prefix) and raw.endswith(suffix) and len(raw) > len(prefix) + len(suffix) and
            c.digest(raw[len(prefix):-len(suffix)] + b'\n') == expected)


@dataclass(frozen=True)
class Content:
    path: str
    size: int
    sha256: str

    def __len__(self):
        return self.size

    def decode(self, *args, **kwargs):
        data = c.regular_bytes(self.path)
        c.require(len(data) == self.size and c.digest(data) == self.sha256,
                  'stat-cache-race', 'content changed while decoding')
        return data.decode(*args, **kwargs)


def key(value):
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_mode]


def replace_json(path, value):
    path = c.safe_destination(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
            temporary = Path(out.name)
            out.write(c.canonical(value))
            out.flush()
            os.fsync(out.fileno())
        temporary.chmod(0o444)
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class DigestCache:
    def __init__(self, entries=None, written_ns=0, probes=None):
        self.entries = entries or {}
        self.probes = probes
        self.written_ns = written_ns
        self.observed = {}
        self.parents = set()
        self.parent_keys = {}
        self.links = {}
        self.resolved = {}
        self.resolved_status = {}
        self.directories = {}
        self.hashes = 0
        self.changed = False
        self.compact = False
        self.full_raw = None
        self.generation = None

    @classmethod
    def load(cls, path, generation):
        raw = c.regular_bytes(path)
        if raw.startswith(b'{"index":'):
            loaded = cls.load_hot(path, generation, raw=raw)
            value = c.read_json(path, raw=raw)
            full = cls.from_payload(value['payload'], generation)
            c.require(all(full.entries.get(p) == row for p, row in loaded.entries.items()) and
                      full.probes == loaded.probes and full.written_ns == loaded.written_ns,
                      'stat-cache', 'compact projection differs from the full cache')
            full.full_raw = loaded.full_raw
            return full
        value = c.read_json(path, raw=raw)
        c.fields(value, 'payload sha256', 'stat cache')
        # Authenticate the exact payload bytes before interpreting its proxies.
        # The envelope is fixed by our canonical writer, so this avoids two
        # complete re-serializations of the multi-megabyte entry map.
        prefix = b'{"payload":'
        suffix = b',"sha256":' + c.canonical(value['sha256']).rstrip(b'\n') + b'}\n'
        c.require(raw.startswith(prefix) and raw.endswith(suffix), 'stat-cache', 'invalid envelope')
        payload_raw = raw[len(prefix):-len(suffix)]
        payload = value['payload']
        c.require(c.digest(payload_raw + b'\n') == value['sha256'], 'stat-cache', 'integrity digest differs')
        return cls.from_payload(payload, generation)

    @classmethod
    def from_payload(cls, payload, generation, compact=False):
        if compact:
            c.sha(payload['full_sha256'], 'full stat cache')
            payload = {k: v for k, v in payload.items() if k != 'full_sha256'}
        c.fields(payload, 'schema generation written_ns entries' + (' probes' if 'probes' in payload else ''), 'stat cache payload')
        c.require(payload.get('probes') is None or type(payload['probes']) is dict,
                  'stat-cache', 'invalid tool query record')
        c.require(payload['schema'] == 1 and payload['generation'] == generation and
                  type(payload['written_ns']) is int and payload['written_ns'] > 0 and
                  type(payload['entries']) is dict, 'stat-cache', 'invalid cache generation')
        for path, row in payload['entries'].items():
            c.fields(row, 'key sha256 racy', 'stat cache entry')
            c.require(os.path.isabs(path) and type(row['key']) is list and len(row['key']) == 6 and
                      all(type(v) is int for v in row['key']), 'stat-cache', 'invalid stat key')
            c.sha(row['sha256'], 'stat cache entry')
            c.require(type(row['racy']) is bool, 'stat-cache', 'invalid race flag')
        loaded = cls(payload['entries'], payload['written_ns'], payload.get('probes'))
        loaded.generation = generation
        loaded.compact = compact
        return loaded

    @classmethod
    def load_hot(cls, path, generation, raw=None):
        raw = c.regular_bytes(path) if raw is None else raw
        if not raw.startswith(b'{"index":'):
            return cls.load(path, generation)
        # Decode only the first, compact JSON value. The full payload stays
        # opaque but every byte is authenticated against the reverse link.
        text = raw.decode('utf-8')
        decoder = json.JSONDecoder(object_pairs_hook=c.no_duplicates,
                                   parse_constant=lambda _: (_ for _ in ()).throw(c.Rejected('stat-cache: invalid JSON constant')))
        try:
            index, end = decoder.raw_decode(text, len('{"index":'))
        except json.JSONDecodeError as exc:
            raise c.Rejected('stat-cache: invalid compact index') from exc
        c.fields(index, 'payload sha256', 'compact stat index')
        payload = index['payload']
        c.fields(payload, 'schema generation written_ns entries probes full_sha256', 'compact stat index payload')
        index_raw = raw[len(b'{"index":'):len(text[:end].encode('utf-8'))]
        index_prefix = b'{"payload":'
        index_suffix = b',"sha256":' + c.canonical(index['sha256'])[:-1] + b'}'
        c.require(index_raw.startswith(index_prefix) and index_raw.endswith(index_suffix),
                  'stat-cache', 'invalid compact index envelope')
        payload_raw = index_raw[len(index_prefix):-len(index_suffix)] + b'\n'
        c.require(index_integrity(payload_raw, index['sha256']), 'stat-cache', 'compact index integrity differs')
        prefix = b'{"index":' + index_raw + b',"index_sha256":' + c.canonical(index['sha256'])[:-1] + b',"payload":'
        suffix = b',"sha256":' + c.canonical(payload['full_sha256'])[:-1] + b'}\n'
        c.require(full_link(raw, prefix, suffix, payload['full_sha256']),
                  'stat-cache', 'full cache and compact index digests differ')
        loaded = cls.from_payload(payload, generation, compact=True)
        loaded.full_raw = raw[len(prefix):-len(suffix)] + b'\n'
        return loaded

    def read(self, path, status=None):
        path = os.path.abspath(path)
        parent = os.path.dirname(path)
        if parent not in self.parents:
            for part in (Path(parent), *Path(parent).parents):
                part = str(part)
                if part not in self.parent_keys:
                    parent_stat = os.stat(part, follow_symlinks=False)
                    c.require(stat.S_ISDIR(parent_stat.st_mode), 'source-type', 'symlink parent forbidden')
                    self.parent_keys[part] = (parent_stat.st_dev, parent_stat.st_ino, parent_stat.st_mode)
            self.parents.add(parent)
        before = os.stat(path, follow_symlinks=False) if status is None else status
        c.require(stat.S_ISREG(before.st_mode), 'source-type', 'regular cached file required')
        proxy = key(before)
        row = self.entries.get(path)
        # A future timestamp is also unsafe. Never age a racy entry without
        # reading its bytes, even when every metadata field still matches.
        racy = self.racy(before.st_mtime_ns) or (row is not None and row['racy'])
        if row is None or row['key'] != proxy or racy:
            with open(path, 'rb') as source:
                c.require(key(os.fstat(source.fileno())) == proxy,
                          'stat-cache-race', 'file replaced before hashing')
                digest = c.digest(source.read())
                c.require(key(os.fstat(source.fileno())) == proxy,
                          'stat-cache-race', 'file changed during hashing')
            c.require(key(os.stat(path, follow_symlinks=False)) == proxy,
                      'stat-cache-race', 'file replaced during hashing')
            row = {'key': proxy, 'sha256': digest, 'racy': False}
            self.entries[path] = row
            self.hashes += 1
            self.changed = True
        self.observed[path] = proxy
        return Content(path, before.st_size, row['sha256'])

    def racy(self, mtime_ns):
        return mtime_ns >= self.written_ns - GRAIN_NS

    def resolve(self, path):
        path = os.path.abspath(path)
        if path in self.resolved:
            return self.resolved[path]
        if path == '/':
            return path
        parent = self.resolve(os.path.dirname(path))
        target = os.path.join(parent, os.path.basename(path))
        status = os.stat(target, follow_symlinks=False)
        if stat.S_ISLNK(status.st_mode):
            self.links[target] = key(status)
            target = self.resolve(os.path.join(parent, os.readlink(target)))
        if not stat.S_ISLNK(status.st_mode):
            self.resolved_status[target] = status
        self.resolved[path] = target
        return target

    def watch_directory(self, path):
        path = os.path.abspath(path)
        value = os.stat(path, follow_symlinks=False)
        c.require(stat.S_ISDIR(value.st_mode), 'source-type', 'regular directory required')
        self.directories.setdefault(path, key(value))

    def recheck(self):
        for path, proxy in self.parent_keys.items():
            status = os.stat(path, follow_symlinks=False)
            c.require((status.st_dev, status.st_ino, status.st_mode) == proxy,
                      'stat-cache-race', 'input parent changed before execution')
        for path, proxy in self.links.items():
            c.require(key(os.stat(path, follow_symlinks=False)) == proxy,
                      'stat-cache-race', 'toolchain symlink changed before execution')
        for path, proxy in self.directories.items():
            c.require(key(os.stat(path, follow_symlinks=False)) == proxy,
                      'stat-cache-race', 'input directory set changed before execution')
        for path, proxy in self.observed.items():
            c.require(key(os.stat(path, follow_symlinks=False)) == proxy,
                      'stat-cache-race', 'observed file changed before execution')

    def save(self, path, generation, compact_paths=None):
        self.recheck()
        written_ns = time.time_ns()
        known = self.entries
        if compact_paths is not None and self.full_raw is not None and self.generation == generation:
            previous = self.from_payload(c.read_json(path, raw=self.full_raw), generation)
            known = dict(previous.entries, **self.entries)
        entries = {path: dict(row, racy=row['racy'] or row['key'][3] >= written_ns - GRAIN_NS)
                   for path, row in known.items()
                   if path in self.observed or (compact_paths is not None and self.generation == generation)}
        probes = self.probes
        if probes is not None:
            rows = [probes['binding']['clang'], *probes['binding']['files'].values(),
                    *probes['binding']['gcc'].values(),
                    *(row['stat'] for row in probes['binding']['directories'].values())]
            probes = dict(probes, racy=probes['racy'] or any(row['key'] is not None and
                          row['key'][3] >= written_ns - GRAIN_NS for row in rows))
        payload = {'schema': 1, 'generation': generation, 'written_ns': written_ns,
                   'entries': entries, 'probes': probes}
        full_sha = c.digest(c.canonical(payload))
        envelope = {'payload': payload, 'sha256': full_sha}
        if compact_paths is not None:
            hot = dict(payload, entries={p: row for p, row in entries.items() if p in compact_paths}, full_sha256=full_sha)
            index = {'payload': hot, 'sha256': c.digest(c.canonical(hot))}
            envelope.update(index=index, index_sha256=index['sha256'])
        replace_json(path, envelope)
        self.entries = entries if compact_paths is None else hot['entries']
        self.probes = probes
        self.written_ns = written_ns
        self.changed = False
        self.compact = compact_paths is not None
        self.generation = generation
        self.full_raw = c.canonical(payload) if compact_paths is not None else None
