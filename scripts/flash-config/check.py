#!/usr/bin/env python3
"""Keep the kernel's offline choices tied to the measurements that selected them.

Execute the selectors beside the kernel and inspect the actual recorded IR.
Plans carry tiles and optional hints; historical timings stay in this audit
directory. P4-b history is pinned separately from P4-c and A2. Matmul keeps
its original measured grid and winner checks. No selector is reimplemented
here, and absent hints are never treated as explicit ones.
"""
import argparse
import copy
import itertools
import hashlib
import subprocess
import tempfile
import json
import math
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
KERNELS = ROOT / "scripts/tile-golden/kernels.dawn"
LEDGER = Path(__file__).with_name("ledger.json")
# P4-b selection history is distinct from the later P4-c measurements.
# This pin proves that the archived record did not change, not that the
# measurements are true. It includes tools, shapes, configs and all rounds.
P4B_SELECTION_SHA256 = "d1258bec5f8d70baaacaccd6b43fb35b33ac35ae64133eb6dafe9f4533a98834"
ARCHES = ("sm_90", "sm_100", "default", "sm_86", "sm_120")


def manifest(source):
    """Execute Dawn selectors and actual recorders, never evaluate Dawn in Python."""
    with tempfile.TemporaryDirectory(prefix="flash-config-") as work:
        project = Path(work)
        (project / "src").mkdir()
        (project / "src/main.dawn").write_text(source)
        (project / "dawn.toml").write_text(
            'schema = 1\nname = "config_audit"\n[deps]\n'
            f'tileir = "{ROOT / "packages/tileir"}"\n'
            f'tileref = "{ROOT / "packages/tileref"}"\n')
        run = subprocess.run([str(ROOT / "bin/dawn"), "run", str(project), "--", "--config-manifest"],
                             capture_output=True, text=True, check=True)
        return parse_manifest(run.stdout)


def parse_manifest(output):
    if output and not output.endswith("END\n"):
        raise ValueError("unterminated config manifest")
    records = []
    for block in output.split("END\n"):
        if not block:
            continue
        header, ir = block.split("\n", 1)
        fields = header.split("\t")
        if fields[0] != "BEGIN" or fields[1] not in ("flash", "matmul"):
            raise ValueError("invalid config manifest header")
        family, arch, dtype = fields[1:4]
        if family == "flash":
            d, bh, bq, bk = map(int, fields[4:8])
            cfg = dict(bq=bq, bk=bk)
            key = (family, arch, dtype, d, bh)
        else:
            tm, tn, tk = map(int, fields[4:7])
            cfg = dict(tm=tm, tn=tn, tk=tk)
            key = (family, arch, dtype)
        records.append(dict(key=key, config=cfg, hints=fields[-1], ir=ir))
    return records


def expected_hints(arch, cfg):
    if not cfg['occupancy'] and not cfg['cga']:
        return ""
    return f"{arch}:{cfg['occupancy'] or 'none'}:{cfg['cga'] or 'none'}:none"


def wiring(record):
    """Check what the recorder emitted, independently of manifest plan fields."""
    key, cfg, ir = record['key'], record['config'], record['ir']
    problems = []
    hint_fields = []
    for item in filter(None, record['hints'].split(',')):
        arch, occ, cga, warps = item.split(':')
        attrs = [f"{name} = {value}" for name, value in
                 [('num_cta_in_cga', cga), ('num_worker_warps_per_cta', warps), ('occupancy', occ)] if value != 'none']
        hint_fields.append(f"{arch} = {{{', '.join(attrs)}}}")
    want = ' optimization_hints=<' + ', '.join(hint_fields) + '>' if hint_fields else ''
    entry = ir.splitlines()[1]
    actual = entry[entry.index(' optimization_hints='):entry.rindex(' {')] if ' optimization_hints=' in entry else ''
    if actual != want:
        problems.append(f"{key}: recorded hints differ from plan")
    if key[0] == 'flash':
        _, _, dtype, d, bh = key
        q, k = cfg['bq'], cfg['bk']
        acc = 'f32' if dtype == 'bf16' else 'f64'
        shapes = []
        mma = f': tile<{q}x{d}x{dtype}>, tile<{d}x{k}x{dtype}>, tile<{q}x{k}x{acc}>'
        storage = f'shape = [{bh}, 512, {d}], strides = [{512 * d}, {d}, 1]'
        views = [line for line in ir.splitlines() if ' = make_tensor_view ' in line]
        parts = [line for line in ir.splitlines() if ' = make_partition_view ' in line]
        if len(views) != 4 or any(storage not in line for line in views):
            problems.append(f"{key}: recorded storage differs from domain")
        if len(parts) != 4 or any('dim_map=[0, 1, 2]' not in line for line in parts) or [
                sum(f'tile=(1x{size}x{d})' in line for line in parts) for size in set((q, k))] != [
                (4 if q == k else 2) for size in set((q, k))]:
            problems.append(f"{key}: recorded three dimensional partition differs from plan")
        problems += flash_indices(key, ir, q, k, d, dtype, acc)
        problems += flash_memory(key, ir)
    else:
        dtype = key[2]
        q, n, k = cfg['tm'], cfg['tn'], cfg['tk']
        acc = 'i32' if dtype == 'i8' else dtype
        shapes = [(q, k), (k, n), (q, n)]
        mma = f': tile<{q}x{k}x{dtype}>, tile<{k}x{n}x{dtype}>, tile<{q}x{n}x{acc}>'
    if any(f'tile=({a}x{b})' not in ir for a, b in shapes) or mma not in ir:
        problems.append(f"{key}: recorded view/MMA tiles differ from plan")
    return problems


def flash_memory(key, ir):
    """Follow recorded view provenance, independently of cell size or order."""
    _, arch, dtype, d, _bh = key
    target = arch == 'sm_90' and dtype == 'bf16' and d == 64
    origins = {f'%arg{k}': k for k in range(4)}
    accesses = []
    for line in ir.splitlines():
        definition = re.search(r'(%\d+) = (?:assume div_by<\d+>,|make_tensor_view|make_partition_view) (%\w+)', line)
        if definition:
            dst, src = definition.groups()
            if src in origins:
                origins[dst] = origins[src]
        load = re.search(r'= load_view_tko weak (%\d+)\[', line)
        store = re.search(r'= store_view_tko weak %\d+, (%\d+)\[', line)
        if load or store:
            view = (load or store).group(1)
            param = origins.get(view)
            hint = re.search(r' optimization_hints=<([^>]+)>', line)
            actual = hint.group(1) if hint else ''
            want = 'sm_90 = {latency = 3}' if target and load and param in (1, 2) else ''
            accesses.append((bool(load), param))
            if actual != want:
                return [f'{key}: parameter view memory policy differs at {param}']
    if len(accesses) != 4 or set(accesses) != {(False, 3), (True, 0), (True, 1), (True, 2)}:
        return [f'{key}: parameter view memory provenance differs']
    return []


def flash_indices(key, ir, bq, bk, d, dtype, acc):
    """Follow the emitted SSA edges, including singleton boundary reshapes."""
    errors = []
    axes = {}
    for match in re.finditer(r'(%\d+), (%\d+), (%\d+) = get_tile_block_id', ir):
        axes.update({value: axis for axis, value in enumerate(match.groups())})
    loops = list(re.finditer(r'for (%\d+) in \((%\d+) to (%\d+), step (%\d+)\)', ir))
    constants = dict(re.findall(r'(%\d+) = constant <i32: (-?\d+)>', ir))
    if len(loops) != 1:
        return [f"{key}: recorded key loop count differs"]
    iv, lower, upper, step = loops[0].groups()
    if [constants.get(value) for value in (lower, upper, step)] != ['0', str(512 // bk), '1']:
        errors.append(f"{key}: recorded storage dim 1 loop bound differs")
    loads = re.findall(r'(%\d+), %\d+ = load_view_tko weak %\d+\[([^]]+)\].* -> tile<([^>]+)>', ir)
    stores = re.findall(r'store_view_tko weak (%\d+), %\d+\[([^]]+)\]', ir)
    reshapes = dict((dst, (src, before, after)) for dst, src, before, after in re.findall(
        r'(%\d+) = reshape (%\d+) : tile<([^>]+)> -> tile<([^>]+)>', ir))
    if len(loads) != 3 or len(stores) != 1:
        return errors + [f"{key}: recorded memory boundary count differs"]
    for j, (value, indices, shape) in enumerate(loads):
        ix = indices.split(', ')
        expected = [2, 0 if j == 0 else None, 1]
        if len(ix) != 3 or any(axes.get(x) != axis for x, axis in zip(ix, expected) if axis is not None) or (j > 0 and ix[1] != iv):
            errors.append(f"{key}: recorded head/query/key index dataflow differs")
        rows = bq if j == 0 else bk
        if shape != f'1x{rows}x{d}x{dtype}' or sum(
                src == value and before == shape and after == f'{rows}x{d}x{dtype}'
                for src, before, after in reshapes.values()) != 1:
            errors.append(f"{key}: recorded load projection differs")
    value, indices = stores[0]
    ix = indices.split(', ')
    if len(ix) != 3 or [axes.get(x) for x in ix] != [2, 0, 1]:
        errors.append(f"{key}: recorded output head/query index differs")
    if value not in reshapes or reshapes[value][1:] != (f'{bq}x{d}x{acc}', f'1x{bq}x{d}x{acc}'):
        errors.append(f"{key}: recorded store inverse projection differs")
    if re.search(r' = (?:divi|muli|addi) ', ir):
        errors.append(f"{key}: unexpected head integer arithmetic")
    return errors


def cliff(arch, bq, cga):
    return (cga == 2 and bq < 128) or (arch == "sm_90" and bq == 256 and cga != 2)


def check(records, ledger):
    problems = []
    historical = {k: v for k, v in ledger.items() if k != 'matmul'}
    digest = hashlib.sha256(json.dumps(historical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if digest != P4B_SELECTION_SHA256:
        problems.append('P4B_SELECTION_SHA256: archived tools, configurations or timings changed')
    if records is None:
        return problems
    expected = {('flash', a, dt, d, bh) for a in ARCHES for dt in ['f64', 'bf16']
                for d in [32, 64, 128, 256] for bh in [1, 2]}
    flash = [r for r in records if r['key'][0] == 'flash']
    if {r['key'] for r in flash} != expected or len(flash) != len(expected):
        problems.append('flash selector manifest has missing or duplicate domain cases')
    selected = [r for r in ledger['rows'] if r['selected']]
    used = set()
    for actual in flash:
        _, arch, dtype, d, _bh = actual['key']
        # Audit keys describe evidence coverage, not executable selection code.
        rows = [r for r in selected if r['dtype'] == dtype and r['table_arch'] == arch
                and r['table_d'] == (d if dtype == 'bf16' else 0)]
        if not rows:
            rows = [r for r in selected if r['dtype'] == dtype and r['table_arch'] == 'default']
        if len(rows) != 1:
            problems.append(f"{actual['key']}: expected one historical evidence association")
            continue
        row = rows[0]
        used.add(row['id'])
        cfg = row['config']
        if actual['config'] != {k: cfg[k] for k in ['bq', 'bk']} or actual['hints'] != expected_hints(arch, cfg):
            problems.append(f"{actual['key']}: actual plan differs from evidence {row['id']}")
        problems += wiring(actual)
    if used != {r['id'] for r in selected} or len(used) != 8:
        problems.append('eight logical flash audit keys must all be covered')
    return problems


def self_test(records, ledger):
    for field in ['median_ms', 'tileiras', 'measured_arch']:
        changed = copy.deepcopy(ledger)
        changed['rows'][0][field] = 0 if field == 'median_ms' else 'changed'
        assert any('P4B_SELECTION_SHA256' in p for p in check(records, changed)), field
    changed = copy.deepcopy(ledger)
    changed['rows'].pop(0)
    assert check(records, changed), 'missing evidence stayed green'
    if records is None:
        print("PASS flash history controls: missing evidence, median, compiler and measured arch")
        return
    for field, value in [('config', dict(bq=32, bk=16)), ('hints', 'sm_90:1:none:none')]:
        changed = copy.deepcopy(records)
        target = next(r for r in changed if r['key'] == ('flash', 'sm_90', 'bf16', 64, 1))
        target[field] = value
        assert any('actual plan differs' in p for p in check(changed, ledger)), field
    changed = copy.deepcopy(records)
    target = next(r for r in changed if r['key'] == ('flash', 'sm_100', 'bf16', 64, 1))
    target['ir'] = target['ir'].replace('num_cta_in_cga = 2, ', '')
    assert any('recorded hints' in p for p in check(changed, ledger)), 'lost trace hints stayed green'
    target['ir'] = target['ir'].replace('tile=(1x256x64)', 'tile=(1x128x64)')
    assert any('partition' in p for p in check(changed, ledger)), 'lost tile wiring stayed green'
    target_key = ('flash', 'sm_90', 'bf16', 64, 1)
    changed = copy.deepcopy(records)
    target = next(r for r in changed if r['key'] == target_key)
    target['ir'] = target['ir'].replace(' optimization_hints=<sm_90 = {latency = 3}>', '')
    assert any('memory policy' in p for p in check(changed, ledger)), 'missing host read policy stayed green'
    changed = copy.deepcopy(records)
    target = next(r for r in changed if r['key'] == target_key)
    target['ir'] = target['ir'].replace('token=%0 : partition_view', 'token=%0 optimization_hints=<sm_90 = {latency = 3}> : partition_view', 1)
    assert any('memory policy' in p for p in check(changed, ledger)), 'Q inherited K/V policy'
    print('PASS flash audit controls: missing evidence, median, compiler, measured arch, tile, absent hint and actual IR wiring')



def display_rows(data):
    lines = ["# Card\tformat\tworkload\ttoolchain\tconfiguration\tbefore median/p90\tafter median/p90\tcuTile median/p90\tSDPA median/p90"]
    for case in data['cases']:
        rs = {r['name']: r for r in case['results']}
        cfg = case['config']
        timing = lambda r: f"{r['median_ms']:.4f} / {r['p90_ms']:.4f}"
        ct = [r for r in case['results'] if r['name'].startswith('cutile_')]
        row = [f"{case['card']} {case['arch']}", case['dtype'], f"B*H={case['bh']} S={case['s']} d={case['d']}",
               f"{data['tileiras']} -O{data['opt_level']}",
               f"q{cfg['bq']} k{cfg['bk']} occ={cfg['occupancy'] or 'none'} cga={cfg['cga'] or 'none'}",
               timing(rs['base']), timing(rs['tuned']), timing(min(ct, key=lambda r:r['median_ms'])) if ct else 'N/A',
               timing(rs['torch_sdpa']) if 'torch_sdpa' in rs else 'N/A']
        lines.append('\t'.join(row))
    return '\n'.join(lines) + '\n'


def check_measurements(data, ledger, displayed):
    problems = []
    expected = {(arch, dtype, d, bh, s) for arch in ['sm_90', 'sm_100']
                for dtype, bh, s in [('bf16', 1, 16384), ('bf16', 32, 4096), ('f64', 1, 16384)] for d in [64, 128]}
    actual = {(c['arch'], c['dtype'], c['d'], c['bh'], c['s']) for c in data['cases']}
    if actual != expected or len(data['cases']) != 12:
        problems.append('missing or duplicate same-round timing case')
    for c in data['cases']:
        choices = [r for r in ledger['rows'] if r['selected'] and r['table_arch'] == c['arch'] and r['dtype'] == c['dtype']
                   and r['table_d'] == (c['d'] if c['dtype'] == 'bf16' else 0)]
        if len(choices) != 1 or choices[0]['config'] != c['config']:
            problems.append('measured configuration differs from the table')
        rs = {r['name']: r for r in c['results']}
        if not {'base', 'tuned', 'torch_sdpa'} <= rs.keys() or (c['dtype'] == 'bf16' and
                (not {'tuned_exact', 'kt_fixed', 'kt_old', 'torch_sdpa'} <= rs.keys() or
                 len([n for n in rs if n.startswith('cutile_')]) != 4)):
            problems.append('missing same-round baseline or control')
        for r in c['results']:
            if r['n'] <= 0 or len(r['round_medians']) != 5 or r['median_ms'] <= 0 or r['p90_ms'] < r['median_ms']:
                problems.append('incomplete timing samples')
    if data.get('flash_output_dtype') != 'f64':
        problems.append('historical P4-c timings must retain their f64 output format')
    if len(data['accuracy']) != 8 or any(r['miss'] > 1.0 for r in data['accuracy']):
        problems.append('approximate division exceeded the existing tolerance or lacks a comparison')
    if (data['tileiras'] != '13.4.92' or data['cutile_tileiras'] != '13.4.92' or
            not data['compiler_verified_in_each_process'] or data['opt_level'] != 3):
        problems.append('missing timing toolchain')
    for arch, dtype, dim, bh, seq in expected:
        if dtype != 'bf16':
            continue
        key = f"bf_bh{bh}_s{seq}_d{dim}"
        rs = {r['name']: r for r in data['alignment_adopted'] if r['arch'] == arch and r['set'] == key}
        if set(rs) != {'tuned', 'tuned_exact', 'kt_fixed', 'kt_old', 'kt_approx'}:
            problems.append('missing adopted-division alignment comparison')
        elif not 0.98 <= rs['kt_approx']['median_ms'] / rs['tuned']['median_ms'] <= 1.02:
            problems.append('aligned transposed K is outside the measured neutral range')
    if len(data['alignment_tma']) != 16 or any(r['failed_selections'] != (2 if r['name'].endswith('kt_old') else 0) for r in data['alignment_tma']):
        problems.append('missing before and after TMA selection evidence')
    if len(data['alignment_tma_approx']) != 8 or any(r['failed_tma'] for r in data['alignment_tma_approx']):
        problems.append('missing TMA selection evidence for the adopted division')
    if displayed != display_rows(data):
        problems.append('GPU page timing numbers differ from the measured rows')
    return problems


def check_matmul(records, ledger, data, dtype="f64"):
    """Extend the same source-to-evidence gate to the existing GEMM formats.

    The complete filtered grid stays here, including the runners up. Shapes
    measure a single architecture choice; they never become selection keys.
    """
    problems = []
    ledger = dict(ledger, rows=[r for r in ledger['rows'] if r['dtype'] == dtype])
    found = [r for r in ledger['rows'] if r['selected']]
    expected_keys = {('sm_90', dtype), ('sm_100', dtype), ('default', dtype)}
    actual_keys, ids = [], []
    actual = [] if records is None else [r for r in records if r['key'][0] == 'matmul' and r['key'][2] == dtype]
    if records is not None and ({r['key'] for r in actual} != {('matmul', a, dtype) for a in ARCHES} or len(actual) != len(ARCHES)):
        problems.append('matmul selector manifest has missing or duplicate domain cases')
    for item in actual:
        arch = item['key'][1]
        rows = [r for r in found if r['table_arch'] == arch]
        if not rows:
            rows = [r for r in found if r['table_arch'] == 'default']
        if len(rows) != 1:
            problems.append('missing matmul evidence association')
            continue
        cfg = rows[0]['config']
        if item['config'] != {k: cfg[k] for k in ['tm', 'tn', 'tk']} or item['hints'] != expected_hints(arch, cfg):
            problems.append(f"{item['key']}: actual matmul plan differs from evidence")
        problems += wiring(item)
    cases = data['cases']
    if {(c['arch'], c['shape']) for c in cases} != {(a, s) for a in ['sm_90', 'sm_100'] for s in ['square', 'skinny']} or len(cases) != 4:
        problems.append('missing or duplicate matmul shape')
    grid = (dict(tm=[16, 32, 64, 128, 256], tn=[16, 32, 64], tk=[16, 32], occupancy=[0, 2], cga=[0, 2]) if dtype == 'f64' else
            dict(tm=[32, 64, 128, 256], tn=[32, 64, 128], tk=[32, 64, 128], occupancy=[0, 2], cga=[0, 2]))
    baseline_name = 'm64n64k32o0c0' if dtype == 'f64' else 'm32n32k32o0c0'
    if data['grid'] != grid or data['rounds'] != 5 or data['warmup'] != 10:
        problems.append('changed matmul measurement grid or method')
    if (data['tileiras'], data['cutile_tileiras'], data['opt_level'], data['compiler_verified_in_each_process'], data['dtype']) != ('13.4.92', '13.4.92', 3, True, dtype):
        problems.append('missing matmul timing toolchain')
    rejected = set()
    for c in cases:
        arch, shape = c['arch'], c['shape']
        expected_shape = (((2048, 2048, 2048) if shape == 'square' else (4096, 256, 2048)) if dtype == 'f64' else
                          ((4096, 4096, 4096) if shape == 'square' else (8192, 256, 4096)))
        if (c['m'], c['n'], c['k']) != expected_shape or c['dtype'] != dtype or c['card'] != ('H200' if arch == 'sm_90' else 'B200'):
            problems.append('changed matmul workload or card')
        allowed = set()
        for tm, tn, tk, occ, cga in itertools.product(*grid.values()):
            name = f'm{tm}n{tn}k{tk}o{occ}c{cga}'
            if cliff(arch, tm, cga or 1):
                rejected.add((arch, shape, name))
            else:
                allowed.add(name)
        dawn = [r for r in c['results'] if r['kind'] == 'dawn']
        if {r['name'] for r in dawn} != allowed or len(dawn) != len(allowed):
            problems.append('missing or duplicate filtered matmul grid cell')
        for r in c['results']:
            if (r['arch'], r['shape'], r['m'], r['n'], r['k']) != (arch, shape, *expected_shape):
                problems.append('matmul timing belongs to another case')
            if (len(r['round_medians']) != 5 or r['n_samples'] < 15 or
                    not 0 < r['median_ms'] <= r['p90_ms'] or
                    not all(math.isfinite(x) and x > 0 for x in r['round_medians']) or
                    not math.isfinite(r['miss']) or not 0 <= r['miss'] <= 1):
                problems.append('incomplete or incorrect matmul timing')
            if dtype != 'f64' and r.get('dtype') != dtype:
                problems.append('matmul timing belongs to another dtype')
            if dtype != 'f64' and (r['miss'] != 0 or r['max_abs_err'] != 0):
                problems.append('matmul exact corpus differs from its reference')
            if r['kind'] in ['dawn', 'cutile']:
                cfg = r['config']
                name = f"m{cfg['tm']}n{cfg['tn']}k{cfg['tk']}o{cfg['occupancy']}c{cfg['cga']}"
                if r['name'] != ('cutile_' if r['kind'] == 'cutile' else '') + name or cliff(arch, cfg['tm'], cfg['cga'] or 1):
                    problems.append('matmul timing configuration differs from its name or violates a filter')
        if len([r for r in c['results'] if r['kind'] == 'torch' and r['name'] == 'torch_matmul']) != 1 or len([r for r in c['results'] if r['kind'] == 'cutile']) != 6:
            problems.append('missing same-round matmul comparator')
    actual_rejected = [(r['arch'], r['shape'], r['name']) for r in data['filtered']]
    if set(actual_rejected) != rejected or len(actual_rejected) != len(rejected):
        problems.append('matmul recording filter inventory differs from the grid')
    for r in found:
        arch, evidence, cfg = r['table_arch'], r['id'], r['config']
        actual_keys.append((arch, dtype))
        ids.append(evidence)
        if cliff(arch, cfg['tm'], cfg['cga'] or 1):
            problems.append(f'{evidence}: rejected matmul cliff configuration')
        if (r['tileiras'], r['opt_level']) != ('13.4.92', 3):
            problems.append(f'{evidence}: missing matmul toolchain')
        selected_cases = [c for c in cases if c['arch'] == r['measured_arch']]
        if not selected_cases or (arch != 'default' and r['measured_arch'] != arch):
            problems.append(f'{evidence}: missing measured matmul architecture')
        for c in selected_cases:
            rs = {x['name']: x for x in c['results'] if x['kind'] == 'dawn'}
            chosen, baseline = rs.get(r['case_name']), rs.get(baseline_name)
            if not chosen or not baseline or chosen['config'] != cfg:
                problems.append(f'{evidence}: missing measured matmul configuration')
                continue
            if c['shape'] == 'square':
                for field in ['median_ms', 'p90_ms', 'round_medians']:
                    if r[field] != chosen[field] or r[{'median_ms': 'baseline_ms', 'p90_ms': 'baseline_p90_ms', 'round_medians': 'baseline_round_medians'}[field]] != baseline[field]:
                        problems.append(f'{evidence}: matmul selection timing differs from grid')
            if arch != 'default' and min(b / t for b, t in zip(baseline['round_medians'], chosen['round_medians'])) < 1.05:
                problems.append(f'{evidence}: matmul improvement is below five percent')
        if arch != 'default' and len(selected_cases) == 2:
            maps = [{x['name']: x for x in c['results'] if x['kind'] == 'dawn'} for c in selected_cases]
            common = set(maps[0]) & set(maps[1])
            best = [min(x['median_ms'] for x in rs.values()) for rs in maps]
            score = lambda name: (max(rs[name]['median_ms'] / b for rs, b in zip(maps, best)),
                                  math.prod(rs[name]['median_ms'] / b for rs, b in zip(maps, best)))
            if not common or r['case_name'] != min(common, key=score):
                problems.append(f'{evidence}: matmul choice differs from the cross-shape winner')
    if set(actual_keys) != expected_keys or len(set(ids)) != 3 or sorted(ids) != sorted(r['id'] for r in ledger['rows'] if r['selected']):
        problems.append('the three matmul table cells and selected evidence are not one to one')
    final = data['final_cases']
    if len(final) != 4 or {(c['arch'], c['shape']) for c in final} != {(c['arch'], c['shape']) for c in cases}:
        problems.append('missing final paired matmul case')
    for c in final:
        rs = {r['name']: r for r in c['results']}
        choices = [r for r in ledger['rows'] if r['table_arch'] == c['arch']]
        if len(choices) != 1:
            problems.append('missing final matmul selection evidence')
            continue
        choice = choices[0]
        selected = rs.get(choice['case_name'])
        matching = rs.get('cutile_' + choice['case_name'])
        base = rs.get(baseline_name)
        if (len(rs) != 12 or len(c['results']) != 12 or not selected or not matching or not base or
                'torch_matmul' not in rs or len([r for r in rs.values() if r['kind'] == 'cutile']) != 8):
            problems.append('missing final matmul baseline, matched cuTile candidate or torch')
            continue
        if selected['config'] != choice['config'] or matching['config'] != choice['config']:
            problems.append('final matmul configuration differs from selection')
        for r in rs.values():
            if (r['shape'], r['arch'], r['m'], r['n'], r['k']) != (c['shape'], c['arch'], c['m'], c['n'], c['k']):
                problems.append('final matmul timing belongs to another workload')
            if (len(r['round_medians']) != 5 or r['n_samples'] < 15 or not 0 < r['median_ms'] <= r['p90_ms'] or
                    not math.isfinite(r['miss']) or not 0 <= r['miss'] <= 1):
                problems.append('incomplete or incorrect final matmul timing')
            if dtype != 'f64' and r.get('dtype') != dtype:
                problems.append('matmul timing belongs to another dtype')
            if dtype != 'f64' and (r['miss'] != 0 or r['max_abs_err'] != 0):
                problems.append('final matmul exact corpus differs from its reference')
        if min(b / t for b, t in zip(base['round_medians'], selected['round_medians'])) < 1.05:
            problems.append('final paired matmul improvement is below five percent')
    return problems


def matmul_self_test(records, ledger, data, dtype='f64'):
    changed = copy.deepcopy(ledger)
    changed['rows'] = [r for r in changed['rows'] if not (r['dtype'] == dtype and r['table_arch'] == 'sm_90')]
    assert check_matmul(records, changed, data, dtype), 'missing matmul evidence stayed green'
    for field in ['median_ms', 'tileiras']:
        changed = copy.deepcopy(ledger)
        row = next(r for r in changed['rows'] if r['dtype'] == dtype)
        row[field] = 0 if field == 'median_ms' else 'changed'
        assert check_matmul(records, changed, data, dtype), field
    if records is not None:
        changed = copy.deepcopy(records)
        target = next(r for r in changed if r['key'] == ('matmul', 'sm_90', dtype))
        target['config']['tk'] *= 2
        assert check_matmul(changed, ledger, data, dtype), 'changed matmul tile stayed green'
    changed_data = copy.deepcopy(data)
    changed_data['cases'][0]['results'].pop(0)
    assert check_matmul(records, ledger, changed_data, dtype), 'missing matmul grid cell stayed green'
    if dtype != 'f64':
        changed_data = copy.deepcopy(data)
        changed_data['cases'][0]['results'][0]['max_abs_err'] = 0.001
        assert check_matmul(records, ledger, changed_data, dtype), 'inexact corpus stayed green'
    print(f'PASS {dtype} matmul controls: evidence, tile, time, compiler and measured grid')


def check_output_migration(data, ledger):
    """Keep A2 evidence separate from the historical configuration search."""
    problems = []
    expected = {(arch, d, bh, n) for arch in ['sm_90', 'sm_100']
                for d in [64, 128] for bh, n in [(1, 16384), (32, 4096)]}
    cases = data['cases']
    actual = {(c['key'].split('_bh')[0], c['d'], c['bh'], c['n']) for c in cases}
    if actual != expected or len(cases) != len(expected):
        problems.append('A2 requires exactly eight paired output cases')
    if (data['old_output_dtype'], data['new_output_dtype']) != ('f64', 'f32'):
        problems.append('A2 evidence must distinguish old f64 and new f32 output')
    if len(data['metadata']) != 2 or {m['arch'] for m in data['metadata']} != {'sm_90', 'sm_100'} or any(
            (m['tileiras'], m['rounds'], m['reps'], m['warmup']) != ('13.4.92', 5, 80, 10)
            for m in data['metadata']):
        problems.append('A2 paired timing toolchain or method is incomplete')
    for c in cases:
        arch = c['key'].split('_bh')[0]
        rows = [r for r in ledger['rows'] if r['selected'] and r['table_arch'] == arch and r['table_d'] == c['d']]
        if len(rows) != 1 or rows[0]['config'] != c['config']:
            problems.append(f"A2 {c['key']}: selected configuration changed")
        n = c['bh'] * c['n'] * c['d']
        h = c['host_contract']
        if (h['elements'], h['old_bytes'], h['new_bytes']) != (n, 8*n, 4*n):
            problems.append(f"A2 {c['key']}: downloaded output byte contract changed")
        if c['neq'] != 0 or c['max_delta'] != 0:
            problems.append(f"A2 {c['key']}: finite host Float output equality failed")
        if set(c['reference_miss']) != {'old', 'new'} or any(not math.isfinite(v) or not 0 <= v <= 1 for v in c['reference_miss'].values()):
            problems.append(f"A2 {c['key']}: independent reference exceeded the unchanged bound")
        rounds = c['round_medians']
        if len(rounds) != 5 or len(c['round_new_over_old']) != 5:
            problems.append(f"A2 {c['key']}: missing paired rounds")
        else:
            if any(not math.isclose(r['new']/r['old'], ratio) for r, ratio in zip(rounds, c['round_new_over_old'])):
                problems.append(f"A2 {c['key']}: paired ratio differs from measurements")
            if min(c['round_new_over_old']) > 1.05:
                reviews = [r for r in data['regression_reviews'] if r['key'] == c['key']]
                if len(reviews) != 1 or not reviews[0]['repeat_round_medians'] or not reviews[0]['sass']:
                    problems.append(f"A2 {c['key']}: sustained regression lacks repeat and code review")
        if any(not 0 < t['median_ms'] <= t['p90_ms'] for t in c['timings'].values()):
            problems.append(f"A2 {c['key']}: invalid timing distribution")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--history-only', action='store_true', help='text-only archived evidence checks for tree-policy')
    group.add_argument('--manifest', type=Path, help='actual JVM/native manifest produced by tile-golden')
    args = parser.parse_args()
    records = (None if args.history_only else parse_manifest(args.manifest.read_text())
               if args.manifest else manifest(KERNELS.read_text()))
    ledger = json.loads(LEDGER.read_text())
    data = json.loads(LEDGER.with_name("measurements.json").read_text())
    display = (ROOT / "scripts/flash-config/p4c-display.tsv").read_text()
    output = json.loads(LEDGER.with_name("a2-output.json").read_text())
    problems = (check(records, ledger) + check_measurements(data, ledger, display) +
                check_matmul(records, ledger['matmul'], data['matmul']) +
                check_matmul(records, ledger['matmul'], data['matmul_f16'], 'f16') +
                check_matmul(records, ledger['matmul'], data['matmul_i8'], 'i8') +
                check_output_migration(output, ledger))
    for p in problems:
        print(f"FAIL flash config: {p}")
    if problems:
        return 1
    if args.self_test:
        changed_output = copy.deepcopy(output)
        changed_output['cases'].pop()
        assert check_output_migration(changed_output, ledger), 'missing A2 case stayed green'
        changed_output = copy.deepcopy(output)
        changed_output['cases'][0]['host_contract']['new_bytes'] *= 2
        assert any('byte contract' in p for p in check_output_migration(changed_output, ledger)), 'old output width stayed green'
        print('PASS A2 evidence controls: missing case and old output width rejected')
        self_test(records, ledger)
        matmul_self_test(records, ledger['matmul'], data['matmul'])
        for dtype in ['f16', 'i8']:
            matmul_self_test(records, ledger['matmul'], data['matmul_' + dtype], dtype)
        assert check_measurements(data, ledger, display + "changed"), "changed archived timings stayed green"
        changed = copy.deepcopy(data)
        next(r for r in changed['alignment_adopted'] if r['name'] == 'kt_approx')['median_ms'] *= 1.2
        assert any('neutral range' in p for p in check_measurements(changed, ledger, display)), "a changed alignment measurement stayed green"
        wrong_compiler = copy.deepcopy(data)
        wrong_compiler['cutile_tileiras'] = '13.3.36'
        assert any('toolchain' in p for p in check_measurements(wrong_compiler, ledger, display)), "a mismatched comparator compiler stayed green"
        print("PASS flash timings: archived display values and configurations match all 12 same-round cases")
    print("PASS A2 output migration: eight paired cases, host byte contracts, equality and independent reference")
    if records is None:
        print("PASS flash history: archived P4-b, P4-c and A2 evidence; executable plan checks run in tile-golden")
    else:
        print("PASS flash config: eight logical audit keys match actual plans and recorded IR; historical alternatives retained")
    print("PASS matmul history: nine choices match complete measured grids for three dtypes" if records is None else
          "PASS matmul config: nine choices match actual plans, IR and complete measured grids for three dtypes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
