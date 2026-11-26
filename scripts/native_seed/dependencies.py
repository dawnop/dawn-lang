"""Keep development invalidation proportional to the headers actually compiled.

Compiler depfiles bind header bytes, while search-directory identities also
detect a newly introduced earlier match. Full build receipts retain the entire
environment; this narrower check is only installed by the development launcher.
"""

import os
from pathlib import Path
import subprocess

from native_seed import contract as c
from native_seed.stat_cache import key


def parse(text):
    text = text.replace('\\\n', '')
    target, separator, body = text.partition(':')
    c.require(separator and target == 'dawn-native-deps', 'depfile', 'unexpected dependency target')
    words, word, escaped = [], [], False
    for char in body:
        if escaped:
            word.append(char)
            escaped = False
        elif char == '\\':
            escaped = True
        elif char.isspace():
            if word:
                words.append(''.join(word).replace('$$', '$'))
                word = []
        else:
            word.append(char)
    c.require(not escaped, 'depfile', 'unterminated dependency escape')
    if word:
        words.append(''.join(word).replace('$$', '$'))
    c.require(words and all(os.path.isabs(path) for path in words), 'depfile', 'absolute dependency paths required')
    return words


def record(headers, search, depfiles_sha256=None):
    headers = sorted(set(map(os.path.abspath, headers)))
    roots = sorted(set(map(os.path.abspath, search)))
    directories = set(roots)
    for header in headers:
        # Every relative header spelling can be shadowed at an earlier root.
        # Watch existing intermediate directories too, without walking a tree.
        for origin in roots:
            if header.startswith(origin + '/'):
                relative = os.path.relpath(os.path.dirname(header), origin)
                for root in roots:
                    parent = root
                    for name in (() if relative == '.' else relative.split('/')):
                        parent = os.path.join(parent, name)
                        if not os.path.isdir(parent):
                            break
                        directories.add(parent)
    return {'schema': 1, 'files': {path: c.digest(c.regular_bytes(path)) for path in headers},
            'directories': {path: {'key': key(os.stat(path)),
                                   'members_sha256': c.digest(c.canonical(sorted(os.listdir(path))))}
                            for path in sorted(directories)},
            'depfiles_sha256': depfiles_sha256 or c.digest(b'')}


def validate(value):
    c.fields(value, 'schema files directories depfiles_sha256', 'compiler dependencies')
    c.require(value['schema'] == 1 and type(value['files']) is dict and
              type(value['directories']) is dict, 'depfile', 'invalid compiler dependency record')
    c.sha(value['depfiles_sha256'], 'depfiles digest')
    for path, digest in value['files'].items():
        c.require(os.path.isabs(path), 'depfile', 'absolute header path required')
        c.sha(digest, 'header digest')
    for path, row in value['directories'].items():
        c.fields(row, 'key members_sha256', 'include directory')
        proxy = row['key']
        c.require(os.path.isabs(path) and type(proxy) is list and len(proxy) == 6 and
                  all(type(item) is int for item in proxy), 'depfile', 'invalid include directory key')
        c.sha(row['members_sha256'], 'include directory members')


def unchanged(value, cache):
    validate(value)
    try:
        for path, row in value['directories'].items():
            proxy = row['key']
            resolved = cache.resolve(path)
            if key(os.stat(resolved)) != proxy:
                return False
            if cache.racy(proxy[3]):
                if c.digest(c.canonical(sorted(os.listdir(resolved)))) != row['members_sha256']:
                    return False
                cache.changed = True
            cache.watch_directory(resolved)
        for path, digest in value['files'].items():
            if c.digest(cache.read(cache.resolve(path))) != digest:
                return False
    except (FileNotFoundError, NotADirectoryError):
        return False
    return True


def capture(directory, tc):
    directory = Path(directory).absolute()
    headers, depfiles = set(), {}
    for stage in ('A', 'B', 'C'):
        output = directory / stage
        if not output.exists():
            continue
        files = sorted((output / 'deps').glob('*.d'))
        units = list((output / 'units').glob('tu*.c')) or list((output / 'units').glob('main.c'))
        c.require(len(files) == len(units) + 2, 'depfile', 'every unit, runtime and build-info needs a depfile')
        for path in files:
            raw = c.regular_bytes(path)
            depfiles[path.relative_to(directory).as_posix()] = c.digest(raw)
            headers.update(path for path in parse(raw.decode()) if not path.startswith(str(directory) + '/'))
    c.require(depfiles, 'depfile', 'compiler dependency outputs missing')
    run = subprocess.run([tc['compiler']['executable'], *tc['driver']['flags'],
                          '-std=c11', '-pthread', '-E', '-x', 'c', '-v', '/dev/null'],
                         env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'},
                         capture_output=True, text=True, timeout=20)
    c.require(run.returncode == 0, 'depfile', 'compiler include search probe failed')
    search, active = [], False
    for line in run.stderr.splitlines():
        if line == '#include <...> search starts here:':
            active = True
        elif line == 'End of search list.':
            active = False
        elif active:
            path = line.strip()
            c.require(os.path.isabs(path) and os.path.isdir(path), 'depfile', 'invalid include search directory')
            search.append(path)
    c.require(search, 'depfile', 'empty compiler include search path')
    result = record(headers, search, c.digest(c.canonical(depfiles)))
    inventory = {row['path']: row['sha256'] for row in tc['inventory']}
    c.require(all(inventory.get(path.lstrip('/')) == digest for path, digest in result['files'].items()),
              'depfile', 'actual compiler header was not captured in the full environment')
    return result
