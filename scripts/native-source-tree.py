#!/usr/bin/env python3
"""Materialize the current compiler's portable source project without links.

This live-source helper serves existing native tests. Qualification snapshots
use native-seed.py capture and its committed Git inventory instead.
"""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

# runpy callers do not necessarily put this script's directory on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_seed.contract as c


def capture(destination):
    root = Path(__file__).resolve().parents[1]
    destination = c.safe_destination(destination)
    c.require(not destination.exists(), 'destination', 'new directory required')
    # A conservative project superset, not a second dependency resolver.
    projects = [root / 'selfhost', root / 'compiler-plan']
    packages = root / 'packages'
    c.require(packages.is_dir() and not packages.is_symlink(),
              'source-type', 'packages must be a regular directory')
    projects.extend(sorted(packages.iterdir()))
    files = {}
    for project in projects:
        c.require(project.is_dir() and not project.is_symlink(),
                  'source-type', f'project must be a regular directory: {project.name}')
        prefix = project.relative_to(root).as_posix()
        for name in ('dawn.toml', 'dawn.lock'):
            path = project / name
            if path.exists() or path.is_symlink() or name == 'dawn.toml':
                files[prefix + '/' + name] = ('100644', c.regular_bytes(path))
        for path, value in c.scan(project / 'src').items():
            files[prefix + '/src/' + path] = value
    files = c.portable(files)
    c.require('selfhost/src/nmain.dawn' in files, 'source-missing', 'native entry missing')
    c.write_tree(destination, files, readonly=False)
    return destination / 'selfhost/src/nmain.dawn'


def selftest():
    manifests = []
    with tempfile.TemporaryDirectory(prefix='native-source-capture-') as work:
        for name in ('first', 'second'):
            root = Path(work) / name
            for project in ('selfhost', 'compiler-plan', 'packages/inflate'):
                (root / project / 'src').mkdir(parents=True)
                (root / project / 'dawn.toml').write_text('schema = 1\nname = "fixture"\n')
            (root / 'selfhost/dawn.toml').write_text(
                'schema = 1\nname = "selfhost"\n[java-deps]\na = "g:a:1"\n'
                '[deps]\np = "../compiler-plan"\n')
            (root / 'compiler-plan/dawn.toml').write_text(
                'schema = 1\nname = "plan"\n[deps]\np = "../packages/inflate"\n')
            source = b'pub fn main() -> Unit !io = ()\n'
            (root / 'selfhost/src/nmain.dawn').write_bytes(source)
            script = root / 'scripts/capture.py'
            with patch.dict(capture.__globals__, {'__file__': str(script)}):
                entry = capture(Path(work) / ('captured-' + name))
            assert entry.read_bytes() == source
            captured = entry.parents[2]
            assert not any(p.is_symlink() for p in captured.rglob('*'))
            assert (captured / 'packages/inflate/dawn.toml').is_file()
            manifests.append((entry.parents[1] / 'dawn.toml').read_bytes())
        assert manifests[0] == manifests[1], 'captured manifest depends on checkout location'
    print('OK portable compiler source capture is materialized and independent of checkout location')


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        selftest()
    else:
        print(capture(sys.argv[1]))
