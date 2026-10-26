#!/usr/bin/env python3
"""Measure the generic builder separately from the frozen U0/U1 protocol.

Each independent process warms thirty batches and measures fifty. Reuse the
frozen bootstrap statistic; retain every process and use its median as one
sample. This reports recording cost without claiming tile corpus coverage.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT/'scripts/effect-provenance-bench/measure.py'
SPEC = importlib.util.spec_from_file_location('frozen_provenance_statistics', FROZEN)
STAT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAT)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(artifact, java, n, rounds, out):
    out.mkdir(parents=True, exist_ok=False)
    rng = random.Random(20261025)
    codes = dict(zip(['A0', 'A1', 'B'], rng.sample(['P', 'Q', 'R'], 3)))
    prefix = [str(java), '-Xms256m', '-Xmx256m', '-XX:+UseSerialGC', '-XX:-UsePerfData', '-jar', str(artifact)] if java else [str(artifact)]
    commands = {label: prefix+['observed' if label == 'B' else 'plain', str(n)] for label in codes}
    manifest = {'artifact': str(artifact), 'artifact_sha256': digest(artifact),
                'source_sha256': digest(ROOT/'scripts/effect-provenance-contract/observed_bench.dawn'),
                'driver_sha256': digest(Path(__file__)), 'statistics_sha256': digest(FROZEN),
                'commands': commands, 'rounds': rounds, 'seed': 20261025,
                'affinity': sorted(os.sched_getaffinity(0)), 'load': os.getloadavg()}
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    samples = []
    for round_no in range(rounds):
        order = list(commands)
        rng.shuffle(order)
        for blind, label in enumerate(order):
            stem = f'{round_no:02d}-{blind}'
            before = time.monotonic()
            result = subprocess.run(['/usr/bin/time', '-f', '%e %U %S %M', '-o', str(out/(stem+'.time')), *commands[label]], capture_output=True,
                                    env=dict(os.environ, LC_ALL='C', TZ='UTC'))
            wall = time.monotonic()-before
            (out/(stem+'.stdout')).write_bytes(result.stdout)
            (out/(stem+'.stderr')).write_bytes(result.stderr)
            result.check_returncode()
            assert result.stderr == b'', result.stderr
            rows = [list(map(int, line.split())) for line in result.stdout.splitlines()]
            assert len(rows) == 50
            for batch, row in enumerate(rows):
                assert len(row) == 4 and row[0] == batch and row[1] >= 0 and row[2] == n*n, row
                assert (row[3] > 0) == (label == 'B'), row
            durations = sorted(row[1] for row in rows)
            sample = {'round': round_no, 'blind': blind, 'label': codes[label], 'wall': wall,
                      'exit': result.returncode, 'command': commands[label],
                      'hot': STAT.summary(durations), 'p95': durations[47],
                      'recorded_bytes': STAT.summary([row[3] for row in rows]),
                      'resources': (out/(stem+'.time')).read_text().strip(),
                      'stdout_sha256': hashlib.sha256(result.stdout).hexdigest(),
                      'stderr_sha256': hashlib.sha256(result.stderr).hexdigest(), 'load': os.getloadavg()}
            samples.append(sample)
            with (out/'raw.jsonl').open('a') as file:
                file.write(json.dumps(sample)+'\n')
    (out/'unblind.json').write_text(json.dumps(codes, indent=2)+'\n')
    report = {}
    for label in ['A1', 'B']:
        ratios = []
        for round_no in range(rounds):
            paired = {next(k for k, v in codes.items() if v == row['label']): row for row in samples if row['round'] == round_no}
            ratios.append(paired[label]['hot']['median']/paired['A0']['hot']['median'])
        interval = STAT.interval(ratios)
        report[label] = {**STAT.summary(ratios), 'ci95': [interval[0], interval[2]], 'upper95': interval[1], 'ratios': ratios}
    report['process_medians'] = {label: STAT.summary([row['hot']['median'] for row in samples if row['label'] == codes[label]]) for label in codes}
    report['recorded_bytes'] = STAT.summary([row['recorded_bytes']['median'] for row in samples if row['label'] == codes['B']])
    report['expected_frames'] = 4*n+4
    report['expected_notes'] = 2*n
    report['validated_batches'] = rounds*3*50
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'out': str(out), 'result': report}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--java', type=Path)
    parser.add_argument('--n', type=int, nargs='+', default=[1000, 2000])
    parser.add_argument('--rounds', type=int, default=31)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    for n in args.n:
        measure(args.artifact.resolve(), args.java, n, args.rounds, args.out.resolve()/str(n))


if __name__ == '__main__':
    main()
