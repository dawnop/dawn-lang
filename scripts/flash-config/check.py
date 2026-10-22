#!/usr/bin/env python3
"""Keep the kernel's offline choices tied to the measurements that selected them.

The table is Dawn source beside the kernel. This reader accepts only its
literal fa_config and mm_config rows, holds their complete row sets to the ledger,
and compares configurations and rounded selection timings. It never chooses
or tunes a kernel. Self tests delete evidence, change a tile, change a time,
and exercise both rejected cliff configurations and their allowed boundaries.
"""
import copy
import itertools
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
KERNELS = ROOT / "scripts/tile-golden/kernels.dawn"
LEDGER = Path(__file__).with_name("ledger.json")
ROW = re.compile(r'^\s*(.*?) -> fa_config\((\d+), (\d+), (\d+), (\d+), "([a-z0-9]+)", ([0-9.]+), ([0-9.]+)\)$', re.M)
MM_ROW = re.compile(r'^\s*(.*?) -> mm_config\((\d+), (\d+), (\d+), (\d+), (\d+), "([a-z0-9]+)", ([0-9.]+), ([0-9.]+)\)$', re.M)


def cliff(arch, bq, cga):
    return (cga == 2 and bq < 128) or (arch == "sm_90" and bq == 256 and cga != 2)


def check(source, ledger):
    problems = []
    rows = []
    for name, dtype in [("fa_cfg", "bf16"), ("fa64_cfg", "f64")]:
        match = re.search(r'^fn ' + name + r'\([^\n]+ = match [^\n]+ \{\n(.*?)^\}', source, re.M | re.S)
        if not match:
            problems.append(f"missing literal {name} table")
            continue
        text = match[1]
        found = list(ROW.finditer(text))
        if len(found) != len([line for line in text.splitlines() if line.strip()]):
            problems.append(f"unreadable row in {name}")
        for m in found:
            key, bq, bk, occ, cga, evidence, med, base = m.groups()
            arch = "default" if key == "_" else re.search(r'"(sm_\d+)"', key)[1]
            d = int(re.search(r', (\d+)\)', key)[1]) if dtype == "bf16" and key != "_" else 0
            cfg = dict(bq=int(bq), bk=int(bk), occupancy=int(occ), cga=int(cga))
            if cliff(arch, cfg['bq'], cfg['cga'] or 1):
                problems.append(f"{evidence}: rejected cliff configuration")
            rows.append(evidence)
            records = [r for r in ledger["rows"] if r["id"] == evidence]
            if len(records) != 1:
                problems.append(f"{evidence}: expected exactly one measurement, got {len(records)}")
                continue
            r = records[0]
            if (r["table_arch"], r["table_d"], r["dtype"], r["config"]) != (arch, d, dtype, cfg):
                problems.append(f"{evidence}: table configuration differs from measurement")
            for literal, field in [(med, "median_ms"), (base, "baseline_ms")]:
                digits = len(literal.split('.')[1])
                if float(literal) != round(r[field], digits):
                    problems.append(f"{evidence}: {field} differs from measurement")
            if r["tileiras"] != "13.4.92" or r["opt_level"] != 3 or r["p90_ms"] < r["median_ms"]:
                problems.append(f"{evidence}: incomplete measurement metadata")
            if not r["round_medians"] or not r["baseline_round_medians"]:
                problems.append(f"{evidence}: missing paired rounds")
    selected = [r["id"] for r in ledger["rows"] if r["selected"]]
    if len(rows) != 8 or len(set(rows)) != 8 or sorted(rows) != sorted(selected):
        problems.append("the eight table cells and selected ledger rows are not one to one")
    alternate = [r for r in ledger["rows"] if not r["selected"]]
    if len(alternate) != 1 or alternate[0]["id"] != "bf100d64single":
        problems.append("missing sm_100 d64 single-head alternative")
    return problems


def self_test(source, ledger):
    changed = copy.deepcopy(ledger)
    changed["rows"].pop(0)
    assert check(source, changed), "a missing ledger row stayed green"
    assert check(source.replace('fa_config(64, 128, 2, 0, "bf90d64"', 'fa_config(64, 64, 2, 0, "bf90d64"'), ledger), "a changed table tile stayed green"
    assert check(source.replace('"bf90d64", 0.1520', '"bf90d64", 0.1530'), ledger), "a changed timing stayed green"
    assert cliff("sm_100", 64, 2) and cliff("sm_90", 256, 1)
    assert not cliff("sm_100", 128, 2) and not cliff("sm_90", 256, 2)
    print("PASS flash config negative controls: missing row, changed tile, changed time, cliff boundaries")



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


def check_matmul(source, ledger, data, dtype="f64"):
    """Extend the same source-to-evidence gate to the existing GEMM formats.

    The complete filtered grid stays here, including the runners up. Shapes
    measure a single architecture choice; they never become selection keys.
    """
    problems = []
    table = re.search(r'^fn mm_cfg\([^\n]+ = match [^\n]+ \{\n(.*?)^\}', source, re.M | re.S)
    if not table:
        return ['missing literal mm_cfg table']
    lines = table[1].strip().splitlines()
    all_found = list(MM_ROW.finditer(table[1]))
    found = [m for m in all_found if re.fullmatch(r'\(("sm_\d+"|_), "' + dtype + r'"\)', m[1].strip())]
    ledger = dict(ledger, rows=[r for r in ledger['rows'] if r['dtype'] == dtype])
    if len(found) != 3 or len(all_found) != 9 or lines[-1].strip() != '_ -> panic("matmul: available dtypes are f64, f16 and i8")' or len(lines) != 10:
        problems.append('unreadable matmul table or unsupported dtype fallback')
    expected_keys = {('sm_90', dtype), ('sm_100', dtype), ('default', dtype)}
    actual_keys, ids = [], []
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
    for m in found:
        key, tm, tn, tk, occ, cga, evidence, med, base = m.groups()
        key_match = re.fullmatch(r'\(("sm_\d+"|_), "(' + dtype + r')"\)', key.strip())
        if not key_match:
            problems.append('unknown matmul selection key')
            continue
        arch = key_match[1].strip('"') if key_match[1] != '_' else 'default'
        actual_keys.append((arch, key_match[2]))
        ids.append(evidence)
        records = [r for r in ledger['rows'] if r['id'] == evidence]
        if len(records) != 1:
            problems.append(f'{evidence}: expected exactly one matmul measurement')
            continue
        r = records[0]
        cfg = dict(tm=int(tm), tn=int(tn), tk=int(tk), occupancy=int(occ), cga=int(cga))
        if (r['table_arch'], r['dtype'], r['config']) != (arch, dtype, cfg) or cliff(arch, cfg['tm'], cfg['cga'] or 1):
            problems.append(f'{evidence}: matmul table configuration differs from measurement')
        for literal, field in [(med, 'median_ms'), (base, 'baseline_ms')]:
            if float(literal) != round(r[field], len(literal.split('.')[1])):
                problems.append(f'{evidence}: matmul {field} differs from measurement')
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


def matmul_self_test(source, ledger, data):
    changed = copy.deepcopy(ledger)
    changed['rows'].pop(0)
    assert check_matmul(source, changed, data), 'missing matmul evidence stayed green'
    assert check_matmul(source.replace('mm_config(16, 64, 16, 2, 0, "mmf6490"', 'mm_config(32, 64, 16, 2, 0, "mmf6490"'), ledger, data), 'changed matmul tile stayed green'
    assert check_matmul(source.replace('"mmf6490", 6.287264', '"mmf6490", 6.297264'), ledger, data), 'changed matmul timing stayed green'
    changed_data = copy.deepcopy(data)
    changed_data['cases'][0]['results'].pop(0)
    assert check_matmul(source, ledger, changed_data), 'missing matmul grid cell stayed green'
    changed_data = copy.deepcopy(data)
    changed_data['cutile_tileiras'] = '13.3.36'
    assert check_matmul(source, ledger, changed_data), 'wrong matmul comparator compiler stayed green'
    print('PASS matmul config negative controls: missing evidence, changed tile, changed time, missing grid cell, wrong compiler')


def matmul_format_self_test(source, ledger, data, dtype):
    row = next(r for r in ledger['rows'] if r['dtype'] == dtype and r['table_arch'] == 'sm_90')
    changed = copy.deepcopy(ledger)
    changed['rows'] = [r for r in changed['rows'] if r['id'] != row['id']]
    assert check_matmul(source, changed, data, dtype), 'missing format evidence stayed green'
    cfg = row['config']
    literal = f'mm_config({cfg["tm"]}, {cfg["tn"]}, {cfg["tk"]}, {cfg["occupancy"]}, {cfg["cga"]}, "{row["id"]}"'
    bad = literal.replace(f'({cfg["tm"]},', f'({cfg["tm"] * 2},', 1)
    assert literal in source
    assert check_matmul(source.replace(literal, bad), ledger, data, dtype), 'changed format tile stayed green'
    changed_data = copy.deepcopy(data)
    changed_data['cases'][0]['results'].pop(0)
    assert check_matmul(source, ledger, changed_data, dtype), 'missing format grid cell stayed green'
    changed_data = copy.deepcopy(data)
    changed_data['cases'][0]['results'][0]['max_abs_err'] = 0.001
    assert check_matmul(source, ledger, changed_data, dtype), 'inexact corpus stayed green'
    print(f'PASS {dtype} matmul negative controls: missing evidence, changed tile, missing grid cell, inexact corpus')


def main():
    source, ledger = KERNELS.read_text(), json.loads(LEDGER.read_text())
    data = json.loads(LEDGER.with_name("measurements.json").read_text())
    display = (ROOT / "site/gpu-map/flash-perf.tsv").read_text()
    problems = (check(source, ledger) + check_measurements(data, ledger, display) +
                check_matmul(source, ledger['matmul'], data['matmul']) +
                check_matmul(source, ledger['matmul'], data['matmul_f16'], 'f16') +
                check_matmul(source, ledger['matmul'], data['matmul_i8'], 'i8'))
    for p in problems:
        print(f"FAIL flash config: {p}")
    if problems:
        return 1
    if sys.argv[1:] == ["--self-test"]:
        self_test(source, ledger)
        matmul_self_test(source, ledger['matmul'], data['matmul'])
        for dtype in ['f16', 'i8']:
            matmul_format_self_test(source, ledger['matmul'], data['matmul_' + dtype], dtype)
        assert check_measurements(data, ledger, display + "changed"), "changed page timings stayed green"
        changed = copy.deepcopy(data)
        next(r for r in changed['alignment_adopted'] if r['name'] == 'kt_approx')['median_ms'] *= 1.2
        assert any('neutral range' in p for p in check_measurements(changed, ledger, display)), "a changed alignment measurement stayed green"
        wrong_compiler = copy.deepcopy(data)
        wrong_compiler['cutile_tileiras'] = '13.3.36'
        assert any('toolchain' in p for p in check_measurements(wrong_compiler, ledger, display)), "a mismatched comparator compiler stayed green"
        print("PASS flash timings: page values and configurations match all 12 same-round cases")
    elif sys.argv[1:]:
        return 2
    print("PASS flash config: eight table cells match eight measured rows; one alternative retained")
    print("PASS matmul config: nine table cells match complete grids for three dtypes, two architectures and two shapes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
