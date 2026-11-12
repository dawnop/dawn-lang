#!/usr/bin/env python3
"""Fast Q1/Q2/Q3/Q6/Q7 controls over owned byte and Git fixtures."""

import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from native_seed import contract as c

ROOT = Path(__file__).resolve().parents[1]
CASES = []


def red(label, code, action):
    try:
        action()
    except c.Rejected as exc:
        assert str(exc).startswith(code + ':'), (label, code, str(exc))
        CASES.append({'case': label, 'expected': code, 'actual': str(exc)})
    else:
        raise AssertionError(f'{label}: guard accepted invalid inputs')


def edited(value, path, new):
    value = copy.deepcopy(value)
    parent = value
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = new
    return value


def elf():
    data = bytearray(256)
    data[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHIQQQIHHHHHH', data, 16, 2, 62, 1, 0x400080, 64, 192, 0,
                     64, 56, 2, 64, 1, 0)
    struct.pack_into('<IIQQQQQQ', data, 64, 1, 5, 0, 0x400000, 0, 256, 256, 4096)
    return data


def fixture(repo):
    files = {
        'selfhost/dawn.toml': b'schema = 1\nname = "selfhost"\n[java-deps]\nx = "a:b:1"\n[deps]\nplan = "../compiler-plan"\n',
        'selfhost/src/nmain.dawn': b'pub fn main() -> Unit = ()\n',
        'selfhost/src/embed/stdsrc.dawn': b'current std embed\n',
        'selfhost/src/embed/rtsrc.dawn': b'current runtime embed\n',
        'compiler-plan/dawn.toml': b'schema = 1\nname = "plan"\n[deps]\ninflate = "../packages/inflate"\n',
        'compiler-plan/src/main.dawn': b'pub fn main() -> Unit = ()\n',
        'packages/inflate/dawn.toml': b'schema = 1\nname = "inflate"\n',
        'packages/inflate/src/lib.dawn': b'pub fn inflate() -> Unit = ()\n',
        'std/VERSION': b'0.200.0\n', 'std/io.dawn': b'current std\n',
        'runtime/c/dawn_rt.h': b'current header\n',
        'runtime/c/dawn_rt.c': b'current runtime\n',
    }
    for name, data in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    c.git(repo, 'init', '-q')
    c.git(repo, 'add', '.')
    c.git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
          'commit', '-qm', 'Create input fixture')
    return c.git(repo, 'rev-parse', 'HEAD').decode().strip()


def main():
    lock = c.read_lock(ROOT / 'scripts/native-seed-candidate-v0.104.0.json')
    with tempfile.TemporaryDirectory(prefix='native-seed-contract-') as tmp:
        tmp = Path(tmp)
        repo = tmp / 'repo'
        repo.mkdir()
        commit = fixture(repo)
        source, files = c.source_description(repo, commit)
        receipt = {'schema': 2, 'kind': 'native-bootstrap-inputs',
                   'seed_lock_sha256': c.digest(c.canonical(lock)), 'source': source,
                   'stages': c.stages(lock, source)}
        c.validate_receipt(receipt, lock)
        capture = tmp / 'source'
        c.write_tree(capture, files, readonly=False)
        c.verify_tree(capture, source['inventory'])
        assert not (capture / 'selfhost/dawn.lock').exists()
        assert (capture / 'packages/inflate/src/lib.dawn').is_file()
        # Dirty and untracked checkout bytes never enter the object capture.
        (repo / 'std/io.dawn').write_bytes(b'dirty checkout')
        (repo / 'untracked').write_bytes(b'not an input')
        assert c.source_description(repo, commit) == (source, files)
        # Logical identity is independent of checkout/capture prefixes.
        other = tmp / 'second-source'
        c.write_tree(other, files, readonly=False)
        c.verify_tree(other, source['inventory'])
        assert c.inventory_sha(c.inventory(c.scan(other))) == source['inventory_sha256']
        bad = tmp / 'bad-seed'
        bad.write_bytes(b'same version text, different executable bytes')
        red('Q1 wrong seed bytes', 'seed-digest', lambda: c.verify_seed(bad, lock))
        red('Q1 another version with own sidecar', 'seed-identity', lambda: c.validate_lock(
            edited(lock, ['seed', 'tag'], 'v0.103.0')))
        red('Q1 same version different bytes', 'seed-digest', lambda: c.verify_seed(bad,
            edited(lock, ['seed', 'sha256'], '0' * 64)))
        red('Q2 seed std from current commit', 'std-pairing', lambda: c.validate_lock(
            edited(lock, ['std', 'commit'], commit)))
        for index in range(3):
            wrong = source['std'] if index == 0 else lock['std']
            red(f'Q2 stage {index} wrong std', 'std-pairing', lambda index=index, wrong=wrong:
                c.validate_receipt(edited(receipt, ['stages', index, 'std'], wrong), lock))
        changed = dict(files)
        changed['std/io.dawn'] = ('100644', b'wrong std')
        assert c.subtree(changed, 'std') != source['std']['sha256']
        std_dir = tmp / 'std'
        c.write_tree(std_dir, {'io.dawn': ('100644', b'changed')}, readonly=False)
        red('Q2 actual std module changed', 'std-pairing', lambda: c.verify_tree(
            std_dir, c.inventory({'io.dawn': ('100644', b'expected')}), 'std-pairing'))
        for target in ('aarch64-unknown-linux-gnu', 'x86_64-unknown-linux-musl'):
            red('Q3 declared ' + target, 'seed-target', lambda target=target: c.validate_lock(
                edited(lock, ['seed', 'target'], target)))
        valid_elf = elf()
        c.verify_elf(valid_elf)
        for label, offset, value in [('machine', 18, 183), ('class', 4, 1), ('endianness', 5, 2)]:
            data = bytearray(valid_elf)
            if offset == 18:
                struct.pack_into('<H', data, offset, value)
            else:
                data[offset] = value
            red('Q3 actual ELF ' + label, 'seed-target', lambda data=data: c.verify_elf(data))
        data = bytearray(valid_elf)
        struct.pack_into('<I', data, 120, 3)
        red('Q3 interpreter', 'seed-target', lambda: c.verify_elf(data))
        data = bytearray(valid_elf)
        struct.pack_into('<IIQQQQQQ', data, 120, 2, 0, 176, 0, 0, 16, 16, 8)
        struct.pack_into('<qQ', data, 176, 1, 0)
        red('Q3 shared dependency', 'seed-target', lambda: c.verify_elf(data))
        red('Q3 truncated ELF', 'seed-target', lambda: c.verify_elf(valid_elf[:100]))
        for index in range(3):
            wrong = source['runtime'] if index == 0 else lock['runtime']
            red(f'Q6 stage {index} wrong runtime', 'runtime-pairing', lambda index=index, wrong=wrong:
                c.validate_receipt(edited(receipt, ['stages', index, 'runtime'], wrong), lock))
        header = capture / 'runtime/c/dawn_rt.h'
        header.unlink()
        red('Q6 missing runtime header', 'runtime-pairing', lambda: c.verify_tree(
            capture / 'runtime/c', c.inventory({p[10:]: x for p, x in files.items()
                if p.startswith('runtime/c/')}), 'runtime-pairing'))
        header.write_bytes(files['runtime/c/dawn_rt.h'][1])
        embedded = capture / 'selfhost/src/embed/rtsrc.dawn'
        embedded.write_bytes(b'wrong embedded runtime')
        red('Q6 embedded runtime changed', 'source-inventory', lambda: c.verify_tree(capture, source['inventory']))
        embedded.write_bytes(files['selfhost/src/embed/rtsrc.dawn'][1])
        for name in ('packages/inflate/dawn.toml', 'compiler-plan/dawn.toml'):
            path = capture / name
            original = path.read_bytes()
            path.unlink()
            red('Q7 missing ' + name, 'source-inventory', lambda: c.verify_tree(capture, source['inventory']))
            path.write_bytes(original)
        path = capture / 'selfhost/dawn.lock'
        path.write_bytes(b'new lock')
        red('Q7 lock missing state changed', 'source-inventory', lambda: c.verify_tree(capture, source['inventory']))
        path.unlink()
        path = capture / 'packages/inflate/src/lib.dawn'
        original = path.read_bytes()
        path.unlink()
        path.symlink_to(repo / 'std/io.dawn')
        red('Q7 symlink escape', 'source-type', lambda: c.verify_tree(capture, source['inventory']))
        path.unlink()
        path.write_bytes(original)
        path.write_bytes(original + b'changed after capture')
        red('Q7 changed after capture', 'source-inventory', lambda: c.verify_tree(capture, source['inventory']))
        path.write_bytes(original)
        modified = copy.deepcopy(receipt)
        modified['source']['inventory'] = [r for r in source['inventory'] if not r['path'].startswith('packages/inflate/')]
        modified['source']['inventory_sha256'] = c.inventory_sha(modified['source']['inventory'])
        # Even a self-consistent receipt is bound to the committed object inventory.
        red('Q7 self-consistent forged receipt', 'source-inventory',
            lambda: c.verify_source(repo, capture, modified))
        raw = dict(files)
        del raw['packages/inflate/dawn.toml']
        # portable() expects the original Java-deps table before transformation.
        raw['selfhost/dawn.toml'] = c.git_files(repo, commit)[1]['selfhost/dawn.toml']
        red('Q7 absent transitive manifest before capture', 'source-missing', lambda: c.portable(raw))
        for replacement in (b'"/outside"', b'"../../outside"', b'{ git = "https://example.invalid/p" }'):
            raw = c.git_files(repo, commit)[1]
            raw['compiler-plan/dawn.toml'] = ('100644', b'schema = 1\n[deps]\np = ' + replacement + b'\n')
            red('Q7 forbidden dependency ' + replacement.decode(), 'source-path', lambda: c.portable(raw))
        for key, value in [('schema', 1), ('kind', 'native-bootstrap-proof'), ('complete', True)]:
            red('strict receipt ' + key, 'schema', lambda key=key, value=value:
                c.validate_receipt(edited(receipt, [key], value), lock))
        red('no qualification by flag', 'lineage', lambda: c.validate_lock(edited(lock, ['state'], 'qualified')))
        for rows in (source['inventory'][::-1], source['inventory'][:1] * 2,
                     [{'path': '../escape', 'kind': 'file',
                        'size': 1, 'sha256': c.digest(b'x'), 'executable': False}]):
            red('strict inventory ordering/path', 'source-path' if rows[0]['path'] == '../escape' else
                'source-inventory', lambda rows=rows: c.inventory_sha(rows))
        duplicate = tmp / 'duplicate.json'
        duplicate.write_bytes(b'{"schema":2,"schema":2}')
        red('duplicate JSON key', 'schema', lambda: c.read_json(duplicate))
        duplicate.write_bytes(b'{"schema":')
        red('truncated JSON', 'schema', lambda: c.read_json(duplicate))
        output = tmp / 'atomic.json'
        c.atomic_json(output, lock)
        before = output.read_bytes()
        red('no candidate overwrite', 'destination', lambda: c.atomic_json(output, {}))
        assert output.read_bytes() == before
        # A symlink in a tracked Git tree must be refused before writing capture output.
        (repo / 'link').symlink_to('/outside')
        c.git(repo, 'add', 'link')
        c.git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
              'commit', '-qm', 'Add forbidden link')
        linked = c.git(repo, 'rev-parse', 'HEAD').decode().strip()
        red('Q7 Git symlink', 'source-type', lambda: c.git_files(repo, linked))
        # The CLI must never reinterpret DAWN_SEED as a native executable.
        env = dict(os.environ, DAWN_SEED=str(bad))
        env.pop('DAWN_NATIVE_SEED', None)
        run = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/native-seed.py'), 'verify',
            '--repo', str(repo), '--lock', str(output), '--receipt', str(duplicate),
            '--source', str(capture), '--seed-tree', str(tmp)], env=env, capture_output=True)
        assert run.returncode == 1 and b'REJECT seed-missing:' in run.stderr, run.stderr
    print(json.dumps({'positive': 'Git objects, portable capture, schema, stage pairings, ELF',
                      'negative_count': len(CASES), 'negative': CASES}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
