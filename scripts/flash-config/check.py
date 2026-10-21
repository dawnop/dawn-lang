#!/usr/bin/env python3
"""Keep the kernel's offline choices tied to the measurements that selected them.

The table is Dawn source beside the kernel. This reader accepts only its
literal fa_config rows, holds both functions' complete row sets to the ledger,
and compares configurations and rounded selection timings. It never chooses
or tunes a kernel. Self tests delete evidence, change a tile, change a time,
and exercise both rejected cliff configurations and their allowed boundaries.
"""
import copy
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
KERNELS = ROOT / "scripts/tile-golden/kernels.dawn"
LEDGER = Path(__file__).with_name("ledger.json")
ROW = re.compile(r'^\s*(.*?) -> fa_config\((\d+), (\d+), (\d+), (\d+), "([a-z0-9]+)", ([0-9.]+), ([0-9.]+)\)$', re.M)


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


def main():
    source, ledger = KERNELS.read_text(), json.loads(LEDGER.read_text())
    data = json.loads(LEDGER.with_name("measurements.json").read_text())
    display = (ROOT / "site/gpu-map/flash-perf.tsv").read_text()
    problems = check(source, ledger) + check_measurements(data, ledger, display)
    for p in problems:
        print(f"FAIL flash config: {p}")
    if problems:
        return 1
    if sys.argv[1:] == ["--self-test"]:
        self_test(source, ledger)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
