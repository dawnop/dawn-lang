"""Bind development tool queries to the same complete stat identities as digests.

The session is installed only by the source launcher. Cold builders and hosted
consumers keep subprocess.run, including their independent final probes. Query
outputs share the generation cache's integrity seal; file inventories and ELF
verification remain independent of these answers.
"""

from concurrent.futures import Future
from contextlib import contextmanager
from contextvars import ContextVar
import base64
import os
from pathlib import Path
import subprocess
from threading import Lock

from native_seed import contract as c
from native_seed.stat_cache import key

ACTIVE = ContextVar('native_tool_queries', default=None)


def runner():
    session = ACTIVE.get()
    return subprocess.run if session is None else session.run


def same_binding(left, right):
    return left == right


class Queries:
    def __init__(self, cache, cc, pinned, *, recipe_paths=None, gcc_directory=None,
                 linker=None, driver_paths=(), actual=None, allow_reuse=True):
        self.cache = cache
        self.allow_reuse = allow_reuse
        self.cc_input = os.path.abspath(cc)
        self.cc = os.path.realpath(cc)
        self.pinned = pinned
        scripts = Path(__file__).resolve().parents[1]
        self.recipe_paths = recipe_paths or [scripts / 'cc-units.sh', scripts / 'native_seed/recipe.py',
                                             scripts / 'native_seed/toolchain.py', Path(__file__)]
        self.gcc = os.path.abspath(gcc_directory or '/usr/lib/gcc/x86_64-linux-gnu/13')
        self.linker = os.path.abspath(linker or '/usr/bin/ld.bfd')
        self.driver_paths = list(map(str, driver_paths))
        self.actual = actual or subprocess.run
        self.memo, self.results = {}, {}
        self.lock = Lock()
        self.previous = cache.probes if allow_reuse else None
        self.paths, self.directories = [], []
        self.expected = None
        self.reuse = False
        if self.previous is not None:
            c.fields(self.previous, 'binding paths directories results racy', 'tool query record')
            self.paths = self.previous['paths']
            self.directories = self.previous['directories']
            now = self.binding(self.paths, self.directories)
            self.reuse = (not self.previous['racy'] and same_binding(now, self.previous['binding']) and
                          not self.is_racy(now))
            if self.reuse:
                self.expected = now

    @contextmanager
    def activate(self):
        token = ACTIVE.set(self)
        try:
            yield self
        finally:
            ACTIVE.reset(token)

    @staticmethod
    def signature(path):
        path = os.path.abspath(path)
        try:
            value = os.stat(path)
        except FileNotFoundError:
            return {'path': path, 'key': None}
        return {'path': path, 'key': key(value)}

    def binding(self, paths, directories):
        paths = set(map(str, paths))
        files = {str(path): self.signature(path) for path in sorted(set(paths) |
                 set(self.driver_paths) | {self.linker}) if os.path.realpath(path) != self.cc}
        gcc = {}
        if os.path.isdir(self.gcc):
            for parent, children, names in os.walk(self.gcc, followlinks=True):
                gcc[parent] = self.signature(parent)
                for name in names:
                    path = os.path.join(parent, name)
                    gcc[path] = self.signature(path)
        else:
            gcc[self.gcc] = self.signature(self.gcc)
        sets = {}
        for path in sorted(set(map(str, directories))):
            try:
                names = sorted(os.listdir(path))
            except FileNotFoundError:
                names = None
            sets[path] = {'stat': self.signature(path), 'names': names}
        return {'clang': self.signature(os.path.realpath(self.cc_input)), 'files': files, 'gcc': gcc, 'directories': sets,
                'recipe': c.digest(c.canonical([c.digest(c.regular_bytes(p)) for p in self.recipe_paths])),
                'pinned': self.pinned}

    def is_racy(self, binding):
        rows = [binding['clang'], *binding['files'].values(), *binding['gcc'].values(),
                *(row['stat'] for row in binding['directories'].values())]
        return any(row['key'] is not None and self.cache.racy(row['key'][3]) for row in rows)

    def run(self, argv, **kwargs):
        query = c.digest(c.canonical({'argv': list(map(str, argv)), 'env': kwargs.get('env'),
                                     'text': bool(kwargs.get('text')), 'cwd': kwargs.get('cwd')}))
        with self.lock:
            future = self.memo.get(query) if self.allow_reuse else None
            owner = future is None
            if owner:
                future = Future()
                if self.allow_reuse:
                    self.memo[query] = future
        if not owner:
            return future.result()
        try:
            # ldd still resolves the live loader search space on every start.
            # Its dependency list is part of the binding for the cached clang
            # and linker answers, rather than a substitute for resolution.
            persistent = os.path.basename(str(argv[0])) != 'ldd'
            saved = self.previous['results'].get(query) if self.reuse and persistent else None
            if saved is None:
                value = self.actual(argv, **kwargs)
                binary = isinstance(value.stdout, bytes)
                encode = lambda data: base64.b64encode(data if isinstance(data, bytes) else data.encode()).decode('ascii')
                saved = {'stdout': encode(value.stdout), 'stderr': encode(value.stderr),
                         'returncode': value.returncode, 'binary': binary}
            c.fields(saved, 'stdout stderr returncode binary', 'tool query answer')
            decode = lambda data: base64.b64decode(data, validate=True)
            stdout, stderr = decode(saved['stdout']), decode(saved['stderr'])
            if not saved['binary']:
                stdout, stderr = stdout.decode(), stderr.decode()
            value = subprocess.CompletedProcess(argv, saved['returncode'], stdout=stdout, stderr=stderr)
            if persistent:
                self.results[query] = saved
            future.set_result(value)
            return value
        except BaseException as exc:
            future.set_exception(exc)
            raise

    def finish(self, paths, directories):
        paths = sorted(set(map(str, paths)))
        directories = sorted(set(map(str, directories)))
        binding = self.binding(paths, directories)
        if self.reuse:
            c.require(same_binding(binding, self.expected), 'stat-cache-race', 'tool query binding changed')
        self.paths, self.directories, self.expected = paths, directories, binding
        record = {'binding': binding, 'paths': paths, 'directories': directories,
                  'results': self.results, 'racy': False}
        if record != self.cache.probes:
            self.cache.changed = True
        self.cache.probes = record

    def restart(self):
        self.reuse = False
        self.memo.clear()
        self.results = {}
        self.expected = None

    def recheck(self):
        if self.expected is not None:
            c.require(same_binding(self.binding(self.paths, self.directories), self.expected),
                      'stat-cache-race', 'tool query inputs changed before execution')
