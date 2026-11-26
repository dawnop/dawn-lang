"""Count actual query execution across compiler, GCC and recipe mutations.

Small private files stand in for the toolchain, keeping the stat invalidation
controls independent of an installed compiler or administrator permissions.
"""

import os
from pathlib import Path
import subprocess
from unittest.mock import patch

from native_seed import contract as c
from native_seed.stat_cache import DigestCache, GRAIN_NS


def run(work):
    from native_seed.probes import Queries
    root = work / 'probe-controls'
    root.mkdir()
    gcc = root / 'gcc'
    gcc.mkdir()
    cc, ld, recipe = [root / name for name in ('clang', 'ld', 'recipe')]
    selected, extra = gcc / 'libgcc.a', gcc / 'cc1'
    for path in (cc, ld, recipe, selected, extra):
        path.write_bytes(b'original')
    (gcc / 'include').mkdir()
    unused = gcc / 'include/unused.h'
    unused.write_bytes(b'unused')
    def age(path):
        value = path.stat()
        os.utime(path, ns=(value.st_atime_ns, value.st_mtime_ns - 3 * GRAIN_NS))
    for path in (cc, ld, recipe, selected, extra, gcc):
        age(path)
    calls = []
    def actual(argv, **kwargs):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 0, stdout='actual\n', stderr='')
    state = root / 'cache.json'
    def capture(cache):
        queries = Queries(cache, str(cc), pinned=False, recipe_paths=[recipe],
                          gcc_directory=gcc, linker=ld, driver_paths=[selected], actual=actual)
        for _ in range(2):
            result = queries.run([str(cc), '--version'], text=True, env={}, capture_output=True)
            assert result.stdout == 'actual\n'
        assert queries.binding([cc, ld, selected], []) == queries.binding([str(cc), str(ld), str(selected)], [])
        queries.finish([cc, ld, selected], [])
        queries.recheck()
        cache.save(state, 'a' * 64)
        return queries
    capture(DigestCache())
    assert len(calls) == 1, 'duplicate query executed twice'
    capture(DigestCache.load(state, 'a' * 64))
    assert len(calls) == 1, 'unchanged query missed the persistent cache'
    unused.write_bytes(b'changed unused header')
    capture(DigestCache.load(state, 'a' * 64))
    assert len(calls) == 1, 'unused GCC header invalidated cached recipe probes'
    print('OK tool queries run once and unchanged bindings reuse their result')
    replacement = root / 'replacement'
    replacement.write_bytes(cc.read_bytes())
    age(replacement)
    os.replace(replacement, cc)
    capture(DigestCache.load(state, 'a' * 64))
    assert len(calls) == 2, 'clang inode/ctime change did not trigger actual probes'
    print('OK replaced clang triggers actual probes')
    extra.write_bytes(b'changed!')
    age(extra)
    capture(DigestCache.load(state, 'a' * 64))
    assert len(calls) == 3, 'GCC installation change did not trigger actual probes'
    print('OK changed GCC installation file triggers actual probes')
    recipe.write_bytes(b'new recipe')
    age(recipe)
    capture(DigestCache.load(state, 'a' * 64))
    assert len(calls) == 4, 'recipe change did not trigger actual probes'
    print('OK changed recipe triggers actual probes')
    # Matching metadata in the write bucket still requires a real query.
    cache = DigestCache.load(state, 'a' * 64)
    with patch('native_seed.stat_cache.time.time_ns', return_value=cc.stat().st_mtime_ns):
        cache.save(state, 'a' * 64)
    capture(DigestCache.load(state, 'a' * 64))
    assert len(calls) == 5, 'racy tool binding reused cached probes'
    print('OK racy probe binding triggers actual probes')
    for _ in range(2):
        cache = DigestCache.load(state, 'a' * 64)
        queries = Queries(cache, str(cc), pinned=False, recipe_paths=[recipe],
                          gcc_directory=gcc, linker=ld, driver_paths=[selected], actual=actual)
        queries.run([str(cc), '--version'], text=True, env={}, capture_output=True)
        for _ in range(2):
            queries.run(['/usr/bin/ldd', str(cc)], text=True, env={}, capture_output=True)
        assert queries.binding([cc, ld, selected], []) == queries.binding([str(cc), str(ld), str(selected)], [])
        queries.finish([cc, ld, selected], [])
        cache.save(state, 'a' * 64)
    assert len(calls) == 7, 'ldd resolution was cached across launches or duplicated within one'
    print('OK ldd resolves every launch and runs once within each launch')
    before = len(calls)
    queries = Queries(DigestCache.load(state, 'a' * 64), str(cc), pinned=False,
                      recipe_paths=[recipe], gcc_directory=gcc, linker=ld,
                      driver_paths=[selected], actual=actual, allow_reuse=False)
    for _ in range(2):
        queries.run([str(cc), '--version'], text=True, env={}, capture_output=True)
    assert len(calls) == before + 2, 'cold collection consumed a cached answer'
    print('OK cold collection always executes actual queries')
