#!/usr/bin/env python3
"""Compare independent C and retained JVM HTTP views against the paired runner.

The baseline is the dispatched source revision, built with the same compiler
and limits. Preserve all payload fields, map local ids through source identity,
and report interleaved measurements rather than asserting a speed multiplier.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time

BASE = 'fdebffc0aca84ef8346a550381488912cb247a89'
ROOT = Path(__file__).resolve().parents[2]
runner, dawnc = map(str, map(Path, sys.argv[1:3]))


def run(argv, **kw):
    p = subprocess.run(list(map(str, argv)), capture_output=True, timeout=180, **kw)
    assert p.returncode == 0, (argv[0:2], p.stderr.decode(errors='replace')[-3000:])
    return p.stdout


def norm(b):
    return re.sub(rb'"ms":\d+', b'"ms":0', b).replace(b'"cached":true', b'"cached":false')


def identity(c):
    return (c['name'], *(tuple(c[k]) for k in ('from', 'to', 'nfrom', 'nto')))


with tempfile.TemporaryDirectory(prefix='play-c-matrix.') as work:
    w = Path(work)
    baseline = w / 'baseline'
    baseline.mkdir()
    data = run(['git', '-C', ROOT, 'archive', BASE, 'playground', 'packages'])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(baseline, filter='data')
    old = w / 'old-play'
    run([ROOT / 'bin/dawn', '__emitc', baseline / 'playground', '--split', w / 'old-c'])
    run([ROOT / 'scripts/cc-units.sh', '-o', old, w / 'old-c'])
    empty = w / 'empty'
    empty.mkdir()
    env = dict(os.environ, DAWNC_BIN=dawnc, PLAY_ANSWERS=str(empty))

    def request(binary, code, target, answers=None):
        body = json.dumps({'code': code, 'target': target}).encode()
        http = b'POST /compile HTTP/1.1\r\nHost: x\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body
        started = time.monotonic_ns()
        response = run([binary, 'serve'], input=http, env=env | ({'PLAY_ANSWERS': str(answers)} if answers else {}))
        ms = (time.monotonic_ns() - started) / 1e6
        head, payload = response.split(b'\r\n\r\n', 1)
        assert int(head.split()[1]) == 200, response[:500]
        return json.loads(payload), payload, ms

    samples = sorted((ROOT / 'site/play-ui/samples').glob('*.dawn'))
    supplements = [ROOT / 'playground/test' / f'{n}.dawn' for n in ('tile_vadd', 'tile_hostif', 'tile_broken')]
    for source in samples + supplements:
        code = source.read_text()
        # Compare compiler artifacts before the view changes their table.
        raw = w / 'raw' / source.stem
        raw.mkdir(parents=True)
        project = 'use tileir/' in code
        target = raw / 'prog.dawn'
        if project:
            (raw / 'src').mkdir()
            target = raw / 'src/main.dawn'
            (raw / 'dawn.toml').write_text('schema = 1\nname = "tile"\nversion = "0.0.0"\n[deps]\n' +
                ''.join(f'{dep} = "{ROOT / "packages" / dep}"\n' for dep in ('tileir', 'tileref', 'tileinterp')))
        target.write_text(code)
        target = raw if project else target
        if source.stem != 'tile_broken':
            output, cmap = raw / 'out.c', raw / 'c.dawnmap'
            run([dawnc, 'emitc', target, '-o', output, '--map', cmap], env=env)
            native = (output.read_bytes(), cmap.read_bytes())
            run([ROOT / 'bin/dawn', '__emitc', target, '-o', output, '--map', cmap], env=env)
            assert native == (output.read_bytes(), cmap.read_bytes()), (source.stem, 'compiler C/map bytes differ')
            print('C artifacts ' + json.dumps({'sample': source.stem, 'form': 'project' if project else 'file',
                'c_sha256': hashlib.sha256(native[0]).hexdigest(), 'map_sha256': hashlib.sha256(native[1]).hexdigest()}), flush=True)
        ac, abc, _ = request(old, code, 'c')
        aj, abj, _ = request(old, code, 'jvm')
        bc, bbc, _ = request(runner, code, 'c')
        bj, bbj, _ = request(runner, code, 'jvm')
        assert norm(abj) == norm(bbj), (source.stem, 'JVM paired contract changed')
        if not ac['ok']:
            assert source.stem == 'tile_broken' and norm(abc) == norm(bbc), (source.stem, ac, bc)
            print('C matrix ' + json.dumps({'sample': source.stem, 'diagnostic_equal': True}))
            continue
        assert bc['ok'] and bc['gaps']['count'] == 0, (source.stem, 'C local gap', bc.get('gaps'))
        for field in ('src',):
            assert ac[field] == bc[field], (source.stem, field)
        for field in ('text', 'total', 'shown', 'truncated'):
            assert ac['pane'][field] == bc['pane'][field], (source.stem, 'C text', field)
        a = {identity(c): c for c in ac['calls']}
        b = {identity(c): c for c in bc['calls']}
        assert a.keys() <= b.keys(), (source.stem, 'lost paired identity')
        rows = []
        for ident, c in b.items():
            prev = a.get(ident)
            parent = lambda cs, c: None if c['parent'] == -1 else identity(cs[c['parent']])
            before = None if prev is None else [prev['id'], parent(ac['calls'], prev)]
            after = [c['id'], parent(bc['calls'], c)]
            ownership = False
            if prev is not None:
                ao = dict(ac['pane']['outs'][prev['id']]); ao.pop('call')
                bo = dict(bc['pane']['outs'][c['id']]); bo.pop('call')
                ownership = ao != bo
                old_children = {identity(k) for k in ac['calls'] if k['parent'] == prev['id']}
                new_children = {identity(k) for k in bc['calls'] if k['parent'] == c['id']}
                if old_children == new_children:
                    assert not ownership, (source.stem, ident, 'unexplained ownership difference')
            rows.append({'identity': ident, 'paired': before, 'c': after, 'ownership_changed': ownership})
        print('C matrix ' + json.dumps({'sample': source.stem, 'source_sha256': hashlib.sha256(code.encode()).hexdigest(),
              'paired': len(a), 'c': len(b), 'paired_gaps': ac['gaps'], 'c_gaps': bc['gaps'], 'rows': rows}, separators=(',', ':')), flush=True)

    # A real full warm, followed by both view hits for every sidebar source.
    warmed = w / 'warmed'
    run([runner, 'warm', ROOT / 'site/play-ui/samples', warmed], env=env)
    wanted = sum(3 + ('use tileir/' in p.read_text()) for p in samples)
    assert len(list(warmed.iterdir())) == wanted
    for source in samples:
        for target in ('c', 'jvm'):
            code = source.read_text()
            live, lb, _ = request(runner, code, target)
            hit, hb, _ = request(runner, code, target, warmed)
            assert not live['cached'] and hit['cached'] and norm(lb) == norm(hb), (source.stem, target, 'hit/live bytes')
    print(f'OK: {len(samples)} sidebar samples, {len(supplements)} project supplements, JVM byte oracle, full warm {wanted} answers, C/JVM byte-identical hits', flush=True)

    measurements = []
    for group in range(5):
        for name in ('hello', 'flash_attn', 'host_launch', 'refused'):
            code = (ROOT / 'site/play-ui/samples' / f'{name}.dawn').read_text()
            _, _, oc = request(old, code, 'c')
            _, _, nc = request(runner, code, 'c')
            _, _, oj = request(old, code, 'jvm')
            _, _, nj = request(runner, code, 'jvm')
            one = w / 'one-sample'
            one.mkdir(exist_ok=True)
            for p in one.iterdir(): p.unlink()
            (one / f'{name}.dawn').write_text(code)
            warm = []
            for binary in (old, runner):
                start = time.monotonic_ns()
                run([binary, 'warm', one, w / 'bench-answers'], env=env)
                warm.append((time.monotonic_ns() - start) / 1e6)
            row = {'group': group, 'sample': name, 'old_c_ms': oc, 'c_ms': nc,
                   'old_two_ms': oc + oj, 'two_ms': nc + nj, 'old_warm_ms': warm[0], 'warm_ms': warm[1]}
            measurements.append(row)
            print('C perf raw ' + json.dumps(row, separators=(',', ':')), flush=True)
    for name in ('hello', 'flash_attn', 'host_launch', 'refused'):
        rows = [r for r in measurements if r['sample'] == name]
        median = {k: statistics.median(r[k] for r in rows) for k in rows[0] if k.endswith('_ms')}
        print('C perf median ' + json.dumps({'sample': name, **median}, separators=(',', ':')), flush=True)
