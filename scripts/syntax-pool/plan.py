#!/usr/bin/env python3
"""Validate the complete syntax deal and successful worker receipts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HARNESSES = ('syntax-small-contract', 'pattern-or-contract', 'for-pattern-contract')
SHARDS = 4
PUBLIC_SHARDS = (1, 2, 3)
WORKERS = 4
INPUTS = (
    'selfhost', 'compiler-plan', 'std', 'runtime', 'bin/dawn',
    'packages/fspath', 'packages/json', 'packages/sha2', 'packages/inflate',
    'scripts/seedjar.sh', 'scripts/seed-release.txt',
    'scripts/seed-checksums.txt', 'scripts/seed-std-checksums.txt',
    '.github/actions/dawn-toolchain', 'scripts/syntax-pool',
    'scripts/syntax-small-contract', 'scripts/pattern-or-contract',
    'scripts/for-pattern-contract', 'scripts/mutant-coverage/shard.sh',
    'scripts/mutant-coverage/check.py',
    'scripts/grammar-corpus/accept/bare_return_delimiters.dawn',
    'scripts/grammar-corpus/accept/or_patterns.dawn',
    'scripts/grammar-corpus/reject/declaration_recovery_opaque.dawn',
    'scripts/grammar-corpus/reject/or_pattern_bare_pipe_recovery.dawn',
    'scripts/checker-corpus/cases/builtin_alias_hint.dawn',
    'scripts/checker-corpus/cases/builtin_alias_hint.expected',
    'scripts/checker-corpus/cases/builtin_alias_boundary.dawn',
    'scripts/checker-corpus/cases/builtin_alias_boundary.expected',
    'scripts/checker-corpus/cases/or_pattern.dawn',
    'scripts/checker-corpus/cases/qualified_let.d',
    'scripts/spike-native/or_pattern.dawn', 'scripts/spike-native/or_pattern.expect',
    'scripts/spike-native/iter_for.dawn', 'scripts/spike-native/iter_for.expect',
)

def registry(root):
    result = {}
    for harness in HARNESSES:
        directory = {
            'syntax-small-contract': 'scripts/syntax-small-contract',
            'pattern-or-contract': 'scripts/pattern-or-contract',
            'for-pattern-contract': 'scripts/for-pattern-contract',
        }[harness]
        here = root / directory
        txt, tsv = here / 'matrix.txt', here / 'matrix.tsv'
        if txt.is_file() == tsv.is_file():
            raise ValueError(f'{harness}: expected exactly one matrix')
        if txt.is_file():
            names = [s.strip() for s in txt.read_text().splitlines()
                     if s.strip() and not s.lstrip().startswith('#')]
        else:
            names = [s.split('\t')[1] for s in tsv.read_text().splitlines()
                     if s.startswith('mutant\t')]
        if not names or len(set(names)) != len(names):
            raise ValueError(f'{harness}: empty or duplicate matrix')
        result[harness] = names
    return result

def load(root):
    expected = {(h, n) for h, names in registry(root).items() for n in names}
    entries = []
    path = root / 'scripts/syntax-pool/plan.tsv'
    lines = [s for s in path.read_text().splitlines() if s and not s.startswith('#')]
    if not lines or lines.pop(0) != 'schema\t2\tshards\t4\tworkers\t4\tpublic\t1,2,3':
        raise ValueError('wrong syntax plan schema or worker bound')
    for line in lines:
        fields = line.split('\t')
        if len(fields) != 4 or fields[0] not in HARNESSES:
            raise ValueError('unknown syntax plan entry')
        h, n, shard, lane = fields
        if not re.fullmatch(r'[1-4]', shard) or not re.fullmatch(r'[0-3]', lane):
            raise ValueError('out of range syntax shard or lane')
        entries.append((h, n, int(shard), int(lane)))
    actual = [(h, n) for h, n, _, _ in entries]
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError('syntax plan has missing, duplicate or unknown cases')
    for h in HARNESSES:
        for shard in range(1, SHARDS + 1):
            if not any(e[0] == h and e[2] == shard for e in entries):
                raise ValueError('empty syntax harness shard')
    for shard in range(1, SHARDS + 1):
        for lane in range(WORKERS):
            if not any(e[2:] == (shard, lane) for e in entries):
                raise ValueError('empty syntax worker lane')
    # Both complete selfhost test products write fixed temporary fixtures.
    # Different worker lanes in one job cannot isolate those fixture paths.
    full_products = {n: shard for h, n, shard, _ in entries
                     if h == 'syntax-small-contract' and n in (
                         'drop-opaque-anchor', 'drop-rbracket-return-boundary')}
    if len(set(full_products.values())) != 2:
        raise ValueError('complete selfhost test products must use separate jobs')
    for name in full_products:
        product = next(e for e in entries if e[0] == 'syntax-small-contract' and e[1] == name)
        if sum(e[2:] == product[2:] for e in entries) != 1:
            raise ValueError('complete selfhost test products must use an exclusive lane')
    return entries

def identity(root):
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    clean = subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *INPUTS], cwd=root)
    if clean.returncode:
        raise ValueError('syntax inputs differ from the declared commit')
    untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z', '--', *INPUTS], cwd=root).split(b'\0')
    unexpected = [p for p in untracked if p and b'__pycache__/' not in p and not p.endswith(b'.pyc')]
    if unexpected:
        raise ValueError('untracked syntax input')
    records = subprocess.check_output(['git', 'ls-tree', '-r', '-z', 'HEAD', '--', *INPUTS], cwd=root).split(b'\0')
    digest = hashlib.sha256()
    entries = [record.split(b'\t', 1) for record in records if record]
    for metadata, raw in sorted(entries, key=lambda entry: entry[1]):
        mode, kind, oid = metadata.split()
        name = raw.decode(); path = root / name
        if kind != b'blob' or mode not in (b'100644', b'100755') or not path.is_file() or path.is_symlink():
            raise ValueError(f'missing regular syntax input: {name}')
        body = path.read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest().encode()
        executable = bool(path.stat().st_mode & 0o111)
        if actual != oid or executable != (mode == b'100755'):
            raise ValueError(f'syntax input bytes or mode differ from the commit: {name}')
        digest.update(raw + b'\0' + (b'x' if executable else b'-') + b'\0')
        digest.update(hashlib.sha256(body).digest())
    return dict(input=head, producers=digest.hexdigest(), plan=hashlib.sha256((root / 'scripts/syntax-pool/plan.tsv').read_bytes()).hexdigest())

def expected_receipt(root, shard, context=None):
    if shard not in range(1, SHARDS + 1):
        raise ValueError('wrong syntax receipt index')
    entries, source = context if context is not None else (load(root), identity(root))
    selected = [(h, n, lane) for h, n, part, lane in entries if part == shard]
    return dict(schema=2, shard=shard, shards=SHARDS, workers=WORKERS,
                **source, public=list(HARNESSES) if shard in PUBLIC_SHARDS else [],
                completed=sorted(h + '/' + n for h, n, _ in selected)), selected

def prepare(root, shard, out):
    receipt, selected = expected_receipt(root, shard)
    out.mkdir()
    (out / 'expected.json').write_text(json.dumps(receipt, sort_keys=True) + '\n')
    (out / 'public').touch()
    print('context\t' + '\t'.join(receipt[k] for k in ('input', 'producers', 'plan')))
    for lane in range(WORKERS):
        (out / f'queue-{lane}').touch()
    for harness, name, lane in selected:
        print(f'{harness}\t{name}\t{lane}')

def complete(root, shard, out, coverage):
    expected, selected = expected_receipt(root, shard)
    if json.dumps(json.loads((out / 'expected.json').read_text()), sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError('syntax input changed during execution')
    if (out / 'public').read_text().splitlines() != expected['public']:
        raise ValueError('missing, duplicate or reordered complete public fixture')
    wanted = {(h, n, lane) for h, n, lane in selected}; actual = []
    for lane in range(WORKERS):
        path = out / f'complete-{lane}'
        for line in path.read_text().splitlines() if path.exists() else ():
            fields = line.split('\t')
            if len(fields) != 6 or fields[:3] != [expected['input'], expected['producers'], expected['plan']]:
                raise ValueError('wrong syntax completion identity')
            if fields[3] != str(lane):
                raise ValueError('wrong syntax completion lane')
            actual.append((fields[4], fields[5], lane))
    if len(set(actual)) != len(actual) or set(actual) != wanted:
        raise ValueError('missing, duplicate or unexpected successful syntax case')
    if coverage:
        coverage.mkdir(parents=True, exist_ok=True)
        target = coverage / f'syntax-pool-{shard}.json'
        if target.exists():
            raise ValueError('duplicate syntax receipt')
        pending = target.with_suffix('.pending')
        pending.write_text(json.dumps(expected, sort_keys=True) + '\n'); pending.replace(target)
    for case in expected['completed']:
        print(case.replace('/', '\t', 1))

def verify_coverage(root, coverage, harnesses):
    selected = set(harnesses) & set(HARNESSES)
    if not selected:
        return
    if selected != set(HARNESSES):
        raise ValueError('syntax dispatch requires all three complete harnesses')
    paths = sorted(coverage.rglob('syntax-pool-*.json')); wanted = set(range(1, SHARDS + 1)); seen = set()
    context = (load(root), identity(root))
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError('syntax receipt is not a regular file')
        receipt = json.loads(path.read_text())
        if not isinstance(receipt, dict):
            raise ValueError('wrong syntax receipt type')
        shard = receipt.get('shard')
        if type(shard) is not int:
            raise ValueError('wrong syntax receipt type')
        if shard not in wanted or shard in seen:
            raise ValueError('duplicate or unexpected syntax receipt')
        expected, _ = expected_receipt(root, shard, context=context)
        if json.dumps(receipt, sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise ValueError('wrong syntax receipt input, producers, plan or completed set')
        seen.add(shard)
    if seen != wanted:
        raise ValueError('missing complete syntax receipt')
    print(f'PASS  syntax pool: {len(seen)} complete input-bound receipts')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'complete'))
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--shard', required=True, type=int)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--coverage', type=Path)
    parser.add_argument('--plan-id')
    args = parser.parse_args()
    try:
        if args.mode == 'prepare':
            if not args.plan_id or not re.fullmatch('[0-9a-f]{64}', args.plan_id):
                parser.error('prepare requires --plan-id SHA256')
            actual = hashlib.sha256((args.root / 'scripts/syntax-pool/plan.tsv').read_bytes()).hexdigest()
            if actual != args.plan_id:
                parser.exit(2, 'FAIL: syntax plan identity differs from the required command\n')
        elif args.plan_id is not None:
            parser.error('--plan-id belongs to prepare')
        if args.mode == 'prepare': prepare(args.root, args.shard, args.out)
        else: complete(args.root, args.shard, args.out, args.coverage)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f'FAIL: {error}\n')

if __name__ == '__main__':
    main()
