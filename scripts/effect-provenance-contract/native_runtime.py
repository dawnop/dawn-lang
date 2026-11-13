"""Reuse one verified runtime object inside a single temporary invocation."""
import hashlib
import os
from pathlib import Path
import shutil
import shlex
import time


class RuntimeObject:
    def __init__(self, runtime, out, command):
        self.runtime = Path(runtime)
        self.object = Path(out) / 'verified-runtime.o'
        self.command = command
        self.key = self.object_hash = None
        self.dependencies = []
        self.requests = self.builds = 0
        self.compile_seconds = self.identity_seconds = 0.0

    def identity(self, prefix):
        start = time.monotonic()
        digest = hashlib.sha256()
        def add(value):
            digest.update(len(value).to_bytes(8, 'big'))
            digest.update(value)
        for argument in prefix:
            add(str(argument).encode())
        compiler = Path(shutil.which(str(prefix[0]))).resolve(strict=True)
        add(str(compiler).encode())
        add(str(compiler.stat().st_mode).encode())
        add(compiler.read_bytes())
        for path in sorted(self.runtime.rglob('*')):
            if not path.is_file() and not path.is_symlink():
                continue
            add(str(path.relative_to(self.runtime)).encode())
            add(str(path.lstat().st_mode).encode())
            add(os.readlink(path).encode() if path.is_symlink() else b'')
            add(path.read_bytes())
        for path in self.dependencies:
            add(str(path).encode())
            add(str(path.lstat().st_mode).encode())
            add(os.readlink(path).encode() if path.is_symlink() else b'')
            add(path.read_bytes())
        self.identity_seconds += time.monotonic() - start
        return digest.hexdigest()

    def check_object(self):
        start = time.monotonic()
        if not self.object.is_file() or hashlib.sha256(self.object.read_bytes()).hexdigest() != self.object_hash:
            raise RuntimeError('The verified runtime object changed')
        self.identity_seconds += time.monotonic() - start

    def get(self, prefix):
        self.requests += 1
        key = self.identity(prefix)
        if key != self.key:
            start = time.monotonic()
            dependencies = self.command('runtime-object-dependencies',
                                        [*prefix, '-M', '-MT', 'runtime-object', self.runtime/'dawn_rt.c'])
            self.identity_seconds += time.monotonic() - start
            if dependencies.returncode != 0:
                raise RuntimeError(('Runtime dependency discovery failed', dependencies.stderr))
            if self.identity(prefix) != key:
                raise RuntimeError('Runtime inputs changed during dependency discovery')
            text = dependencies.stdout.replace('\\\n', ' ')
            if not text.startswith('runtime-object:'):
                raise RuntimeError('Invalid runtime dependency record')
            self.dependencies = sorted({Path(p) for p in shlex.split(text.split(':', 1)[1])})
            if self.runtime/'dawn_rt.c' not in self.dependencies:
                raise RuntimeError('The runtime source is missing from its dependency record')
            key = self.identity(prefix)
            pending = self.object.with_suffix('.pending.o')
            start = time.monotonic()
            result = self.command('runtime-object-build',
                                  [*prefix, '-c', self.runtime / 'dawn_rt.c', '-o', pending])
            self.compile_seconds += time.monotonic() - start
            if result.returncode != 0:
                raise RuntimeError(('Runtime object compilation failed', result.stderr))
            if self.identity(prefix) != key:
                raise RuntimeError('Runtime inputs changed during compilation')
            object_hash = hashlib.sha256(pending.read_bytes()).hexdigest()
            pending.replace(self.object)
            self.key, self.object_hash = key, object_hash
            self.builds += 1
        self.check_object()
        return self.object

    def confirm(self, prefix):
        if self.identity(prefix) != self.key:
            raise RuntimeError('Runtime inputs changed during linking')
        self.check_object()

    def metadata(self):
        return dict(identity=self.key, object_sha256=self.object_hash,
                    requests=self.requests, builds=self.builds,
                    compile_seconds=self.compile_seconds,
                    identity_seconds=self.identity_seconds)
