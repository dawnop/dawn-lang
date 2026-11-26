"""Prove dependency selection and include shadowing with private compiler inputs.

The unused-header control rejects a full-tree implementation, while the other
controls reject an incomplete depfile or search-directory implementation.
"""

import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from native_seed import contract as c
from native_seed.stat_cache import DigestCache, GRAIN_NS


def run(work):
    from native_seed import dependencies
    root = work / 'dep-controls'
    root.mkdir()
    first, last = root / 'first', root / 'last'
    first.mkdir()
    last.mkdir()
    (first / 'nested').mkdir()
    (last / 'nested').mkdir()
    included, unused = last / 'nested/selected.h', last / 'unused.h'
    included.write_text('#define SELECTED 7\n')
    unused.write_text('unused\n')
    source = root / 'main.c'
    source.write_text('#include <nested/selected.h>\nint value = SELECTED;\n')
    dep = root / 'actual.d'
    subprocess.run(['/usr/lib/llvm-18/bin/clang', '-I', str(first), '-I', str(last),
                    '-MD', '-MF', str(dep), '-MT', 'dawn-native-deps', '-c', str(source),
                    '-o', str(root / 'main.o')], check=True, capture_output=True)
    paths = dependencies.parse(dep.read_text())
    assert str(included) in paths and str(unused) not in paths, 'actual depfile omitted its included header'
    assert dependencies.parse('dawn-native-deps: /a\\ b.h \\\n /c\\#d.h /cash$$.h\n') == ['/a b.h', '/c#d.h', '/cash$.h']
    def age(path):
        value = path.stat()
        os.utime(path, ns=(value.st_atime_ns, value.st_mtime_ns - 3 * GRAIN_NS))
    for path in (included, unused, first, last, first / 'nested', last / 'nested'):
        age(path)
    record = dependencies.record([str(included)], [str(first), str(last)])
    state = root / 'cache.json'
    def check():
        cache = DigestCache.load(state, 'd' * 64) if state.exists() else DigestCache()
        answer = dependencies.unchanged(record, cache)
        cache.save(state, 'd' * 64)
        return answer
    assert check()
    unused.write_text('changed unused header\n')
    assert check(), 'unused header invalidated the hot dependency set'
    print('OK an unused header edit preserves a warm hit')
    included.write_text('#define SELECTED 8\n')
    assert not check(), 'included header edit did not invalidate the hot dependency set'
    print('OK an actual included header edit invalidates a warm hit')
    included.write_text('#define SELECTED 7\n')
    assert check()
    prior = (first / 'nested').stat()
    (first / 'nested/selected.h').write_text('#define SELECTED 9\n')
    assert not check(), 'earlier nested include shadow did not invalidate the hot dependency set'
    print('OK an earlier same-name header invalidates a warm hit')
    actual_stat = os.stat
    def coarse_stat(path, *args, **kwargs):
        return prior if os.path.abspath(path) == str(first / 'nested') else actual_stat(path, *args, **kwargs)
    with patch('native_seed.dependencies.os.stat', side_effect=coarse_stat):
        assert not dependencies.unchanged(record, DigestCache(written_ns=prior.st_mtime_ns)), \
            'a racy directory reused its old member set'
    print('OK racy directory metadata still checks the member digest')
    # ldd can spell the same library through a compiler-relative ../lib path.
    # Exercise the entire warm branch so a false miss cannot hide behind the
    # launcher's full-capture fallback in its protocol fixture.
    from native_seed import toolchain
    cc, library = root / 'clang', root / 'library.so'
    cc.write_bytes(b'private compiler')
    library.write_bytes(b'private library')
    alias = str(first / '../library.so')
    programs = [str(cc), '/usr/bin/ld.bfd', '/bin/sh', '/bin/bash']
    probe = {'executable': str(cc)}
    driver = {'files': {'private': str(library)}}
    baseline = {'compiler': probe, 'driver': driver, 'linker': {'version': 'GNU ld fixture'},
                'inventory': [{'path': path.lstrip('/'), 'sha256': c.digest(Path(path).read_bytes())}
                              for path in [*programs, str(library)]]}
    def query(argv, **kwargs):
        output = 'GNU ld fixture\n' if argv[0] == '/usr/bin/ld.bfd' else ' lib => ' + alias + '\n'
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr='')
    def restarted():
        raise AssertionError('valid dependency paths fell back to full capture')
    session = SimpleNamespace(reuse=True, run=query, restart=restarted, directories=[],
                              paths=[*programs, '/usr/bin/ldd', '/etc/ld.so.cache', '/etc/ld.so.preload',
                                     str(library), alias], finish=lambda *args: None)
    token = toolchain.ACTIVE.set(session)
    try:
        with patch.object(toolchain, 'TOOLS', ()), patch.object(toolchain, 'compiler_probe', return_value=probe), \
             patch.object(toolchain, 'driver_inputs', return_value=driver):
            assert toolchain.warm(str(cc), baseline, dependencies.record([], []), False, DigestCache()) == baseline
    finally:
        toolchain.ACTIVE.reset(token)
    print('OK compiler-relative ldd paths retain the validated warm branch')
