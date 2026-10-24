#!/usr/bin/env python3
"""Hold the IO probe boundary through the real parser and HTTP/job path.

Successful fallback output alone also passes with an illegal probe. The tool
wrappers therefore save parse dumps and build inputs before the runner removes
its projects. Every boundary fixture must first pass the original Check.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('runner', type=Path)
parser.add_argument('dawnc', type=Path)
parser.add_argument('--out', type=Path)
parser.add_argument('--only', choices=['boundary', 'positive', 'error', 'warm'])
parser.add_argument('--fixture', choices=['host', 'unicode', 'local', 'callback', 'annotated', 'with', 'nested'])
parser.add_argument('--sample', choices=['vadd', 'flash'])
args = parser.parse_args()


def normalized(raw):
    return re.sub(rb'"ms":\d+', b'"ms":0', raw).replace(b'"cached":true', b'"cached":false')


def clean(raw, work):
    for secret in [b'@@tile', b'explore_probe', b'not declared !io',
                   b'initializer is fn', b'tile probe did not compile', b'internal checker detail', str(work).encode()]:
        assert secret not in raw, ('probe detail leaked', secret, raw)


def fixtures():
    host = (ROOT / 'site/play-ui/samples/host_launch.dawn').read_text()
    start = host.index('fn vadd_prog()')
    end = host.index('\nfn floats', start)
    helper = host[start:end].strip()
    expr = helper.split('= ', 1)[1]
    without = host[:start] + host[end:]
    callback = without.replace('vadd_prog()', expr)
    local = without.replace('pub fn main() -> Unit !io = {',
                            'pub fn main() -> Unit !io = {\n  ' + helper.replace('\n', '\n  '))
    with_lambda = without.replace('pub fn main() -> Unit !io = {',
        'fn pass_prog(f: fn(Unit) -> TileProg) -> TileProg = f(())\n\n'
        'pub fn main() -> Unit !io = {\n  let program = {\n'
        '    with _u <- pass_prog()\n' + expr[1:-1] + '\n  }').replace('vadd_prog()', 'program')
    nested = callback.replace('map.get(map.from([("vadd", {',
                             'map.get(map.from([("vadd", (() => {').replace('\n})]), name)', '\n})())]), name)')
    return {
        'host': (host, 'pure function `vadd_prog`'),
        'unicode': ('# ' + 'π🙂' * 30 + ' 原始位置\n' + host, 'pure function `vadd_prog`'),
        'local': (local, 'pure function `vadd_prog`'),
        'callback': (callback.replace('TileProg, ', ''), 'in lambda'),
        'annotated': (callback.replace('let progs =', 'let progs: fn(String) -> Option[TileProg] ='), 'in lambda'),
        'with': (with_lambda, 'in lambda'),
        'nested': (nested.replace('TileProg, ', ''), 'in lambda'),
    }


with tempfile.TemporaryDirectory(prefix='tile-probe-contract.') as tmp:
    work = Path(tmp)
    evidence = args.out or work / 'evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    for name in ['work', 'slots', 'empty']:
        (work / name).mkdir()
    dawn = Path(os.environ.get('DAWN_BIN', ROOT / 'bin/dawn')).resolve()
    dawnc = args.dawnc.resolve()
    runner = str(args.runner.resolve())
    env = dict(os.environ, PLAY_UNSAFE_LOCAL='1', PLAY_PACKAGES=str(ROOT / 'packages'),
               PLAY_WORK_ROOT=str(work / 'work'), PLAY_SLOT_DIR=str(work / 'slots'),
               PLAY_ANSWERS=str(work / 'empty'))
    if not env.get('PLAY_TOOLCHAIN_ID'):
        version = subprocess.check_output([str(dawn), '--version'], text=True).strip().splitlines()[-1]
        env['PLAY_TOOLCHAIN_ID'] = version.removeprefix('dawn ').replace(' (selfhost)', '')
    # Wrappers inspect the compiler input before exec, rather than inferring
    # project creation from a diagnostic that could have been silenced.
    for kind, tool in [('jvm', dawn), ('native', dawnc)]:
        spy = work / kind
        spy.write_text('''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
a = sys.argv[1:]
p = pathlib.Path(os.environ['PLAY_PROBE_CASE'])
kind, tool = ''' + repr((kind, str(tool))) + '''
entry = {'tool': kind, 'command': a[0]}
if a[0] == 'build':
    root = pathlib.Path(a[1])
    entry['main'] = (root / 'src/main.dawn' if root.is_dir() else root).read_text()
    entry['probe'] = root.is_dir() and (root / 'src/explore_probe.dawn').exists()
    if entry['probe']:
        entry['probe_source'] = (root / 'src/explore_probe.dawn').read_text()
with open(str(p) + '.calls', 'a') as f:
    f.write(json.dumps(entry) + '\\n')
if a[0] == 'parse':
    r = subprocess.run([tool] + a, capture_output=True)
    pathlib.Path(str(p) + '.dump').write_bytes(r.stdout)
    sys.stdout.buffer.write(r.stdout)
    sys.stderr.buffer.write(r.stderr)
    sys.exit(r.returncode)
if a[0] == 'build' and entry['probe'] and os.environ.get('PLAY_PROBE_FAULT'):
    print('error: injected unexpected probe failure @@tile explore_probe internal checker detail')
    sys.exit(1)
os.execv(tool, [tool] + a)
''')
        spy.chmod(0o755)
    env.update(DAWN_BIN=str(work / 'jvm'), DAWNC_BIN=str(work / 'native'))

    def request(name, code, route='compile', mode='native', changes=None, binary=None):
        case = evidence / name
        (evidence / (name + '.dawn')).write_text(code)
        body = json.dumps({'code': code, 'target': 'tile'}).encode()
        wire = (f'POST /{route} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n'
                f'Content-Length: {len(body)}\r\n\r\n').encode() + body
        e = env | {'PLAY_PROBE_CASE': str(case)}
        if mode == 'jvm':
            e['DAWNC_BIN'] = '/nonexistent/tile-probe-dawnc'
        e.update(changes or {})
        Path(str(case) + '.calls').write_text('')
        p = subprocess.run([binary or runner, 'serve'], input=wire, capture_output=True,
                           env=e, cwd=ROOT, timeout=180)
        Path(str(case) + '.request').write_bytes(wire)
        Path(str(case) + '.http').write_bytes(p.stdout)
        Path(str(case) + '.log').write_bytes(p.stderr)
        assert p.returncode == 0, (name, p.stderr)
        header, raw = p.stdout.split(b'\r\n\r\n', 1)
        assert header.startswith(b'HTTP/1.1 200 '), (name, header, raw)
        clean(raw, work)
        calls = [json.loads(l) for l in Path(str(case) + '.calls').read_text().splitlines()]
        return json.loads(raw), raw, calls, p.stderr

    def parse_builds(calls, mode, probe, code):
        parses = [(c['tool'], c['command']) for c in calls if c['command'] == 'parse']
        assert parses == [('native' if mode == 'native' else 'jvm', 'parse')], parses
        builds = [c for c in calls if c['command'] == 'build']
        assert len(builds) == 1 and builds[0]['probe'] is probe, ('probe build audit', builds)
        if not probe:
            assert builds[0]['main'] == code, 'fallback compiled modified source'

    def compare_dumps(a, b):
        # Only the staging path in the dump's first header differs.
        dump = lambda n: Path(str(evidence / n) + '.dump').read_bytes().split(b'\n', 1)[1]
        assert dump(a) == dump(b), ('native/JVM AST mismatch', a, b)

    cases = fixtures()
    host, _ = cases['host']
    expected = (ROOT / 'site/play-ui/samples/host_launch.out').read_text()
    if args.only in (None, 'boundary'):
        for name, (code, reason) in cases.items():
            if args.fixture and args.fixture != name:
                continue
            responses = []
            for mode in ['native', 'jvm']:
                d, _, _, _ = request(f'{name}-{mode}-check', code, 'check', mode)
                assert d['ok'] and d['phase'] == 'check', ('original Check failed', name, d)
                d, _, _, _ = request(f'{name}-{mode}-run', code, 'run', mode)
                assert d['ok'] and d['output'] == expected and d['exit'] == 0, (name, d)
                d, raw, calls, log = request(f'{name}-{mode}-tile', code, mode=mode)
                parse_builds(calls, mode, False, code)
                assert d['ok'] and d['cached'] is False and 'calls' not in d, (name, d)
                assert '\n'.join(d['pane']['text']) + '\n' == expected, (name, d)
                assert reason in d['unmapped'], (name, d)
                line = code[:code.index('trace3("vadd"')].count('\n') + 1
                assert f'at line {line} ' in d['unmapped'], ('original position', name, d)
                if reason == 'in lambda':
                    assert 'IO context cannot be confirmed from the parse tree' in d['unmapped'], d
                assert b'tile probe did not compile' not in log, log
                responses.append(raw)
            assert normalized(responses[0]) == normalized(responses[1]), name
            compare_dumps(f'{name}-native-tile', f'{name}-jvm-tile')
            print(f'OK: {name}: original Check/Run; native/JVM reason/AST/wire; one parse, original build, zero probe', flush=True)

    vadd = (ROOT / 'playground/test/tile_vadd.dawn').read_text()
    flash = (ROOT / 'site/play-ui/samples/flash_attn.dawn').read_text()
    if args.only in (None, 'positive'):
        for name, code in [('vadd', vadd), ('flash', flash)]:
            if args.sample and args.sample != name:
                continue
            responses, programs = [], []
            for mode in ['native', 'jvm']:
                d, raw, calls, _ = request(f'{name}-{mode}', code, mode=mode)
                assert d['ok'] and not d['cached'] and 'unmapped' not in d, (name, d)
                assert d['gaps']['count'] == 0 and d['calls_total'] == len(d['calls']) > 0, d
                parents = {c['id']: c['parent'] for c in d['calls']}
                assert {o['call'] for o in d['pane']['outs']} == set(parents), d
                assert len(d['pane']['outs']) == len(parents), d
                assert any(o['lines'] for o in d['pane']['outs']), d
                assert all(1 <= lo < hi <= d['pane']['total'] + 1
                           for o in d['pane']['outs'] for lo, hi in o['lines']), d
                for call in parents:
                    seen = set()
                    while call != -1:
                        assert call in parents and call not in seen, ('invalid parent tree', parents)
                        seen.add(call)
                        call = parents[call]
                parse_builds(calls, mode, True, code)
                programs.append([c['main'] for c in calls if c['command'] == 'build'])
                responses.append(raw)
                reference = os.environ.get('PLAY_TEST_TILE_REFERENCE')
                if reference:
                    _, ref, _, _ = request(f'{name}-{mode}-baseline', code, mode=mode, binary=reference)
                    assert normalized(raw) == normalized(ref), ('baseline mapping changed', name)
            assert programs[0] == programs[1] and normalized(responses[0]) == normalized(responses[1]), name
            compare_dumps(f'{name}-native', f'{name}-jvm')
            print(f'OK: {name}: {d["calls_total"]} calls, parent/span/outs/IR parity, gaps=0', flush=True)

    if args.only in (None, 'error'):
        broken = host.replace('  p\n}', '  nope\n}', 1)
        for mode in ['native', 'jvm']:
            d, _, _, _ = request(f'broken-{mode}-check', broken, 'check', mode)
            assert not d['ok'] and 'nope' in d['output'], d
            checked = d['output']
            d, _, calls, _ = request(f'broken-{mode}-tile', broken, mode=mode)
            assert not d['ok'] and d['phase'] == 'compile' and 'pane' not in d and d['output'] == checked, d
            parse_builds(calls, mode, False, broken)
            d, _, calls, log = request(f'fault-{mode}', vadd, mode=mode, changes={'PLAY_PROBE_FAULT': '1'})
            assert d['ok'] and d['unmapped'] == 'the instrumented program did not compile' and 'calls' not in d, d
            assert b'tile probe did not compile: error: injected unexpected probe failure' in log, ('missing operator log', log)
            builds = [c for c in calls if c['command'] == 'build']
            assert [b['probe'] for b in builds] == [True, False] and builds[1]['main'] == vadd, builds
        print('OK: original diagnostics and unexpected probe failure classification/log; no internal detail in API', flush=True)

    if args.only in (None, 'warm'):
        store = work / 'fresh-answers'
        assert not store.exists(), 'warm must start from a fresh directory'
        cold, raw, calls, _ = request('warm-cold', host)
        assert cold['ok'] and not cold['cached'] and 'pure function `vadd_prog` at line 26' in cold['unmapped'], cold
        parse_builds(calls, 'native', False, host)
        warm_env = env | {'PLAY_PROBE_CASE': str(evidence / 'warm')}
        Path(str(evidence / 'warm') + '.calls').write_text('')
        p = subprocess.run([runner, 'warm', str(ROOT / 'site/play-ui/samples'), str(store)],
                           env=warm_env, capture_output=True, cwd=ROOT, timeout=900)
        (evidence / 'warm.stdout').write_bytes(p.stdout)
        (evidence / 'warm.log').write_bytes(p.stderr)
        assert p.returncode == 0, ('full sidebar warm failed', p.stdout, p.stderr)
        saved = {p.name: p.read_bytes() for p in store.iterdir()}
        samples = list((ROOT / 'site/play-ui/samples').glob('*.dawn'))
        wanted = sum(3 + ('use tileir/' in p.read_text()) for p in samples)
        assert len(saved) == wanted, ('missing sidebar answers', len(saved), wanted)
        # Preserve raw store answers, including the reason and target key.
        (evidence / 'warm-answers.json').write_text(json.dumps({k: v.decode() for k, v in saved.items()}, indent=2))
        for mode in ['native', 'jvm']:
            d, hit, calls, _ = request(f'warm-hit-{mode}', host, mode=mode, changes={'PLAY_ANSWERS': str(store)})
            assert d['cached'] is True and normalized(hit) == normalized(raw), ('fresh reason/cache mismatch', d, cold)
            assert not any(c['command'] in ('parse', 'build') for c in calls), calls
        # Keep native_ready's release version from the canonical compiler ID.
        # Flipping one hex digit guarantees a miss even for an all-zero digest.
        version, digest = env['PLAY_TOOLCHAIN_ID'].split(' b1:')
        miss_digest = ('0' if digest[0] != '0' else '1') + digest[1:]
        miss_toolchain = f'{version} b1:{miss_digest}'
        for name, code, changes in [('byte', host + ' ', {}), ('toolchain', host, {'PLAY_TOOLCHAIN_ID': miss_toolchain})]:
            d, _, calls, _ = request(f'warm-miss-{name}', code, changes={'PLAY_ANSWERS': str(store)} | changes)
            assert not d['cached'] and d['unmapped'] == cold['unmapped'], d
            parse_builds(calls, 'native', False, code)
        assert saved == {p.name: p.read_bytes() for p in store.iterdir()}, 'serve wrote the answer store'
        print(f'OK: full sidebar fresh warm: {len(saved)} answers; exact cold/hot reason/wire; hit has zero parse/build; byte/toolchain misses', flush=True)
    assert not list((work / 'empty').iterdir()), 'cold requests wrote answers'
    assert not list((work / 'work').iterdir()), 'request projects leaked'
print('OK: tile probe IO contract', flush=True)
