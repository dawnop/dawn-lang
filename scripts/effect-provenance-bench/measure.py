#!/usr/bin/env python3
"""Freeze and measure paired compiler artifacts with blind same-artifact controls.

Process medians are the sampling units. Batch p95 is descriptive, never used
as extra independent data. This manual harness records evidence, not a CI gate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import statistics as st
import subprocess
import time


def digest(data):
    return hashlib.sha256(data).hexdigest()


def summary(values):
    mid = st.median(values)
    return dict(median=mid, minimum=min(values), maximum=max(values),
                mad=st.median(abs(x-mid) for x in values))


def interval(ratios):
    rng = random.Random(20261025)
    samples = sorted(st.median(rng.choices(ratios, k=len(ratios))) for _ in range(20000))
    return [samples[500], samples[19000], samples[19500]]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--a', type=Path)
    p.add_argument('--b', type=Path)
    p.add_argument('--commands', type=Path)
    p.add_argument('--java', type=Path)
    p.add_argument('--native', action='store_true')
    p.add_argument('--rounds', type=int, default=15)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261025)
    names = ['arithmetic', 'direct', 'function', 'trait', 'higher', 'container']
    if args.commands:
        commands = json.loads(args.commands.read_text())
        variants = {'A0': commands['A'], 'A1': commands['A'], 'B': commands['B']}
        artifacts = {}
        names = ['process']
    else:
        if not args.a or not args.b: p.error('--a and --b are required without --commands')
        artifacts = {'A0': args.a.resolve(), 'A1': args.a.resolve(), 'B': args.b.resolve()}
        variants = {k: ([str(args.java), '-Xms256m', '-Xmx256m', '-XX:+UseSerialGC', '-XX:-UsePerfData', '-jar', str(v)]
                        if args.java else [str(v)] + (['native'] if args.native else [])) for k, v in artifacts.items()}
    # Random codes hide the control assignment in the raw timing stream. The
    # key is written only after collection, before computing the paired report.
    codes = dict(zip(variants, rng.sample(['P', 'Q', 'R'], 3)))
    env = dict(os.environ, LC_ALL='C', TZ='UTC')
    samples = []
    manifest = dict(os=platform.platform(), cpu=Path('/proc/cpuinfo').read_text(),
                    affinity=sorted(os.sched_getaffinity(0)), load=os.getloadavg(),
                    artifacts={k: dict(path=str(v), sha256=digest(v.read_bytes()), size=v.stat().st_size)
                               for k,v in artifacts.items()},
                    harness={p.name: digest(p.read_bytes()) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in {".dawn", ".py", ".toml"}},
                    rounds=args.rounds, seed=20261025, commands_sha256=digest(args.commands.read_bytes()) if args.commands else None,
                    frequency_policy={str(p): p.read_text().strip() for p in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_governor")},
                    thresholds=dict(U0_upper95=1.02, compile_cold=1.05))
    (args.out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    for round_no in range(args.rounds):
        order = list(variants)
        rng.shuffle(order)
        for blind, label in enumerate(order):
            cmd = variants[label]
            stem = f'{round_no:02d}-{blind}'
            timing = args.out/(stem+'.time')
            before = time.monotonic()
            r = subprocess.run(['/usr/bin/time', '-f', '%e %U %S %M', '-o', str(timing), *cmd],
                               capture_output=True, env=env, check=True)
            elapsed = time.monotonic()-before
            (args.out/(stem+'.stdout')).write_bytes(r.stdout)
            if r.stderr and not args.commands: raise RuntimeError(r.stderr.decode())
            lines = [] if args.commands else [list(map(int, line.split())) for line in r.stdout.splitlines()]
            if not args.commands and len(lines) != 300: raise RuntimeError('expected six sets of fifty hot batches')
            checksums = digest(r.stdout) if args.commands else digest(json.dumps([(k,b,c) for k,b,t,c in lines]).encode())
            hot = {'process': dict(median=elapsed)} if args.commands else {name: summary([t for k,b,t,c in lines if k==i]) for i,name in enumerate(names)}
            for i,name in enumerate([] if args.commands else names):
                times=sorted(t for k,b,t,c in lines if k==i)
                hot[name]['p95']=times[47]
            sample=dict(round=round_no, blind=blind, label=codes[label], command=cmd, wall=elapsed,
                        resources=timing.read_text().strip(), stdout_sha256=digest(r.stdout), stderr_sha256=digest(r.stderr),
                        checksum_sha256=checksums, hot=hot, load=os.getloadavg())
            samples.append(sample)
            with (args.out/'raw.jsonl').open('a') as f: f.write(json.dumps(sample)+'\n')
    (args.out/'unblind.json').write_text(json.dumps(codes, indent=2)+'\n')
    if len({s['checksum_sha256'] for s in samples}) != 1: raise RuntimeError('output mismatch')
    report = {}
    for label in ('A1', 'B'):
        row={}
        for name in names:
            ratios=[]
            for round_no in range(args.rounds):
                pair={next(k for k,v in codes.items() if v==s['label']):s for s in samples if s['round']==round_no}
                ratios.append(pair[label]['hot'][name]['median']/pair['A0']['hot'][name]['median'])
            ci=interval(ratios)
            row[name]=dict(**summary(ratios), ci95=[ci[0],ci[2]], upper95=ci[1], ratios=ratios,
                           verdict=('pass' if st.median(ratios)<=1.05 else 'regression') if args.commands else ('pass' if ci[1]<=1.02 else 'inconclusive-or-regression'))
        report[label]=row
    (args.out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
