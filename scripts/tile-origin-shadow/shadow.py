#!/usr/bin/env python3
"""Hold the compiler's call identity against the hand written call marks.

    python3 scripts/tile-origin-shadow/shadow.py --compiler build/dawn-selfhost.jar --out DIR

Every golden kernel (and the Playground's flash_attn sample) is recorded once
more inside a `std/provenance` observation. The observation's snapshot is
projected by `tileir/origin` and compared with the `Call` rows the marks of
dev.dawn gave for the same recording. The projection may show more than the
marks (a helper that records nothing, a host call) and never less; the extra
calls are listed by category. A missing mark row, a different parent, two
executions folded into one node, or a helper call outside its definition fails
the run. Nothing here edits tileir or the marks: the program under test is
instrumented by text, as scripts/effect-provenance-contract does.
"""
import argparse
import collections
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/'scripts/effect-provenance-contract'))
from golden_observe import prepare_index  # noqa: E402

DUMP = ''
HEAD = '''use std/map as shmap
use tileir/origin as origin
use tileir/origin.{OriginCall, Kind, Api, Helper, Host, Default, Perform, Body, SourceUnit}
use std/provenance as prov
use std/provenance.{TraceSnapshot}
use provenance_source as shadow_source
use shadow_text
'''


def ensure(text, module, names):
    """Make `names` importable from `module`, extending its list or adding one."""
    pattern = re.compile(r'^use ' + re.escape(module) + r'\.\{([^}]*)\}', re.M)
    found = pattern.findall(text)
    if len(found) == 1:
        members = [n.strip() for n in found[0].split(',') if n.strip()]
        members += [n for n in names if n not in members]
        return pattern.sub(lambda m: 'use ' + module + '.{' + ', '.join(members) + '}', text, count=1)
    if found or re.search(r'^use ' + re.escape(module) + r'\s*$', text, re.M) and names:
        raise ValueError(f'{module}: cannot extend this import')
    return 'use ' + module + '.{' + ', '.join(names) + '}\n' + text


def qualified(text, module):
    if re.search(r'^use ' + re.escape(module) + r'\s*$', text, re.M):
        return text
    if re.search(r'^use ' + re.escape(module) + r'\.', text, re.M):
        raise ValueError(f'{module} is imported selectively; the shadow code needs it qualified')
    return 'use ' + module + '\n' + text


ITEM = re.compile(r'^(?:pub(?:\([a-z]+\))? )?(?:fn|type|const|impl|test|effect|trait|alias|opaque type)\b')
FN = re.compile(r'^(?:pub(?:\([a-z]+\))? )?fn ([A-Za-z_0-9]+)\b')
IDENT = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')


def items(text):
    """(preamble, [item text]): each top level declaration with the comment
    lines above it."""
    lines = text.split('\n')
    starts = [i for i, l in enumerate(lines) if ITEM.match(l)]
    cuts = []
    for i in starts:
        j = i
        while j > 0 and lines[j-1].startswith('#'):
            j -= 1
        cuts.append(j)
    pre = '\n'.join(lines[:cuts[0]]) + '\n'
    out = []
    for n, c in enumerate(cuts):
        end = cuts[n+1] if n + 1 < len(cuts) else len(lines)
        out.append('\n'.join(lines[c:end]) + '\n')
    return pre, out


def fn_name(item):
    for line in item.split('\n'):
        m = FN.match(line)
        if m:
            return m[1]
    return None


def prune(text, roots):
    """Drop functions nothing reachable from `roots` calls, so that code the
    shadow run never executes (and does not type check as `!io`) is gone."""
    pre, parts = items(text)
    named = {fn_name(p): p for p in parts if fn_name(p)}
    keep, todo = set(), [r for r in roots if r in named]
    while todo:
        n = todo.pop()
        if n in keep:
            continue
        keep.add(n)
        todo += [w for w in set(IDENT.findall(named[n])) if w in named and w not in keep]
    return pre + ''.join(p for p in parts if not fn_name(p) or fn_name(p) in keep)


def fix_unused(project, compiler, java):
    """Remove the imports the compiler calls unused, until the program checks.
    The compiler knows which names bring constructors; no guess is made here."""
    source = project/'src/main.dawn'
    for _ in range(8):
        text = re.sub(r'^(use [^\n{]*\.\{[^}]*\})', lambda m: m[1].replace('\n', ' '), source.read_text(), flags=re.M)
        source.write_text(text)
        r = subprocess.run([java, '-Xss512m', '-Xmx3g', '-jar', str(compiler), 'check', '--std', str(ROOT/'std'), str(project)],
                           capture_output=True, text=True)
        found = re.findall(r'error: unused import: (\S+)\n\s+--> \S+main\.dawn:(\d+):', r.stderr + r.stdout)
        if not found:
            if r.returncode:
                sys.exit('instrumented program does not check:\n' + (r.stderr + r.stdout)[:4000])
            return
        lines = text.split('\n')
        for name, line in found:
            i = int(line) - 1
            m = re.match(r'^use ([^\n{]*)\.\{([^}]*)\}$', lines[i])
            if not m:
                lines[i] = ''
                continue
            kept = [n.strip() for n in m[2].split(',') if n.strip() and n.strip() != name]
            lines[i] = 'use ' + m[1] + '.{' + ', '.join(kept) + '}' if kept else ''
        source.write_text('\n'.join(lines))
    sys.exit('unused imports remain')


def head_end(chunk):
    """Index of the `=` that ends a function's signature (not a default's)."""
    depth, started = 0, False
    for i, ch in enumerate(chunk):
        if ch in '([':
            depth += 1
            started = True
        elif ch in ')]':
            depth -= 1
        elif ch == '=' and started and depth == 0 and chunk[i-1] not in '=!<>' and chunk[i+1:i+2] not in ('=', '>'):
            return i
    raise ValueError('no signature end')


def make_io(text):
    """Every function that reaches a shadow call becomes `!io`, to a fixpoint."""
    pre, parts = items(text)
    names = [fn_name(p) for p in parts]
    body = lambda c: c[head_end(c)+1:]
    fns = [(n, p) for n, p in zip(names, parts) if n]
    changed = {n for n, c in fns if not n.startswith('shadow') and re.search(r'\bshadow(?:[1-6]|_kernel)\(', body(c))}
    changed |= {n for n, c in fns if not n.startswith('shadow') and 'fn() -> TileProg' in c[:head_end(c)]}
    while True:
        more = {n for n, c in fns if n not in changed and not n.startswith('shadow')
                and any(re.search(r'\b' + x + r'\(', body(c)) for x in changed)}
        if not more:
            break
        changed |= more
    out = []
    for n, p in zip(names, parts):
        if n in changed:
            p = p.replace('fn() -> TileProg', 'fn() -> TileProg !io')
            at = head_end(p)
            if not re.search(r'!io\s*$', p[:at]):
                p = p[:at].rstrip() + ' !io ' + p[at:]
        out.append(p)
    return pre + ''.join(out)


def instrument(project, compiler, java, goldens):
    source = project/'src/main.dawn'
    text = source.read_text()
    text = re.sub(r'\btrace([1-6])\(', r'shadow\1(', text)
    text = re.sub(r'\btrace_kernel\(', 'shadow_kernel(', text)
    support = (HERE/'support.dawn').read_text().replace('__DUMP__', DUMP)
    if goldens:
        # the harness runs the dispatch itself: the original `main` and what
        # only it reaches go, so no caller of `trace` outside the run remains
        text = text.replace('pub fn main() -> Unit !io = match args() {', 'pub fn kernels_main() -> Unit !io = match args() {', 1)
        text += support + '\npub fn main() -> Unit !io = {\n  for name in args() {\n    println("CASE\\t${name}")\n    let _p = trace(name)\n  }\n}\n'
        text = prune(text, ['main'] + [f'shadow{i}' for i in range(1, 7)] + ['shadow_kernel'])
    else:
        text += support
    text = ensure(text, 'tileir/prog', ['Arg', 'Marker', 'KParam', 'Call', 'TileProg', 'trace_calls', 'trace_kernel', 'erase',
                                        'In', 'Out', 'Shared', 'Scalar'] + [f'trace{i}' for i in range(1, 7)])
    text = ensure(text, 'tileir/dev', ['Dev', 'Param', 'param', 'ByArch', 'EntryHints'])
    text = ensure(text, 'std/dtype', ['Dtype'])
    text = ensure(text, 'std/gpu', [f'Entry{i}' for i in range(1, 7)])
    for module in ('std/list', 'std/str', 'std/loc'):
        text = qualified(text, module)
    text = make_io(text)
    text = HEAD + text
    source.write_text(text)
    # stand-ins let the program check while its imports are settled; the real
    # index is generated from the settled text
    shutil.copyfile(ROOT/'scripts/effect-provenance-contract/preview.dawn', project/'src/provenance_preview.dawn')
    (project/'src/provenance_source.dawn').write_text('use std/map\nuse std/set\nuse provenance_preview.{SourceIndex}\n'
        'pub fn make() -> SourceIndex = SourceIndex { revision = "", declarations = map.empty(), spans = set.empty() }\n')
    (project/'src/shadow_text.dawn').write_text('pub fn lines() -> String = ""\n')
    fix_unused(project, compiler, java)
    prepare_index(project, compiler, java)
    offsets = [0]
    for m in re.finditer('\n', source.read_text()):
        offsets.append(m.end())
    (project/'src/shadow_text.dawn').write_text('pub fn lines() -> String = "' + ','.join(map(str, offsets)) + '"\n')


def project_for(out, name, source_text, deps):
    project = out/name
    (project/'src').mkdir(parents=True, exist_ok=True)
    (project/'src/main.dawn').write_text(source_text)
    (project/'dawn.toml').write_text('schema = 1\nname = "' + name.replace('-', '_') + '"\n[deps]\n'
        + ''.join(f'{d} = {json.dumps(str(ROOT/"packages"/d))}\n' for d in deps))
    return project


def run_project(compiler, java, project, args, timeout):
    command = [java, '-Xss512m', '-Xmx3g', '-jar', str(compiler), 'run', '--std', str(ROOT/'std'), str(project)]
    if args:
        command += ['--'] + args
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def parse(stdout):
    shadows, extras, problems, twice = {}, collections.Counter(), [], []
    case = None
    for line in stdout.splitlines():
        f = line.split('\t')
        if f[0] == 'CASE':
            case = f[1]
        elif f[0] == 'SHADOW':
            shadows.setdefault(case or f[1], []).append({k: int(v) for k, v in (x.split('=') for x in f[2:])})
        elif f[0] == 'EXTRA':
            extras[f[2]] += int(f[3])
        elif f[0] == 'TWICE':
            twice.append(f[1:])
        elif f[0] in ('FAIL', 'MISSING', 'PARENT', 'OUTSIDE'):
            problems.append(line)
    return shadows, extras, problems, twice


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--compiler', type=Path, default=ROOT/'build/dawn-selfhost.jar')
    ap.add_argument('--java', default='java')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--timeout', type=int, default=1800)
    ap.add_argument('--only', choices=['goldens', 'sample'])
    ap.add_argument('--dump', default='')
    args = ap.parse_args()
    global DUMP
    DUMP = args.dump
    args.out.mkdir(parents=True, exist_ok=True)
    report = {}
    if args.only in (None, 'goldens'):
        project = project_for(args.out, 'goldens', (ROOT/'scripts/tile-golden/kernels.dawn').read_text(), ['tileir', 'tileref'])
        instrument(project, args.compiler, args.java, True)
        names = sorted(p.stem for p in (ROOT/'scripts/tile-golden').glob('*.tilebc'))
        r = run_project(args.compiler, args.java, project, names, args.timeout)
        (args.out/'goldens.stdout').write_text(r.stdout)
        (args.out/'goldens.stderr').write_text(r.stderr)
        if r.returncode:
            print(r.stderr[-4000:])
            sys.exit('goldens did not run')
        report['goldens'] = (names, *parse(r.stdout))
    if args.only in (None, 'sample'):
        sample = (ROOT/'site/play-ui/samples/flash_attn.dawn').read_text()
        project = project_for(args.out, 'sample', sample, ['tileir', 'tileinterp'])
        instrument(project, args.compiler, args.java, False)
        r = run_project(args.compiler, args.java, project, [], args.timeout)
        (args.out/'sample.stdout').write_text(r.stdout)
        (args.out/'sample.stderr').write_text(r.stderr)
        if r.returncode:
            print(r.stderr[-4000:])
            sys.exit('sample did not run')
        report['sample'] = (['flash_attn_bf16_demo'], *parse(r.stdout))
    failed = False
    for label, (names, shadows, extras, problems, twice) in report.items():
        cases = sum(len(v) for v in shadows.values())
        old = sum(x['old'] for v in shadows.values() for x in v)
        new = sum(x['new'] for v in shadows.values() for x in v)
        bad = list(problems)
        for v in shadows.values():
            for x in v:
                if x['missing'] or x['dup'] or x['outside']:
                    bad.append(str(x))
        print(f'{label}: {len(shadows)} cases ({cases} recordings), marks rows {old}, projected calls {new}')
        print(f'  helper declarations called more than once in a recording: {len(twice)}')
        by_kind = collections.Counter()
        for key, count in extras.items():
            by_kind['|'.join(key.split('|')[:2])] += count
        for key, count in sorted(by_kind.items()):
            print(f'  new only {key}: {count}')
        if label == 'goldens':
            absent = [n for n in names if n not in shadows]
            print(f'  cases with no shadow recording: {len(absent)}')
        if bad:
            failed = True
            print('FAIL', *bad[:40], sep='\n  ')
    (args.out/'summary.json').write_text(json.dumps(
        {k: {'cases': len(v[1]), 'extras': dict(v[2]), 'problems': v[3], 'twice': v[4]} for k, v in report.items()}, indent=1))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
