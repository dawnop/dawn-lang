#!/usr/bin/env python3
"""Check delivered types and actual environments through both compiler frontends.

The manifest distinguishes ordinary type hiding from real resources, witnesses
and invariant storage. Refusals name the owning rule so an unrelated parser or
setup failure cannot stand in for a semantic result.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "cases.json").read_text())


def observe(run, compiler, case, output, expected=None, diagnostic=None, std=None,
            embedded=False):
    source = HERE / "cases" / (case + ".dawn")
    wanted = CASES[case]["exit"] if expected is None else expected
    args = [*compiler, "check"]
    if not embedded:
        args.extend(["--std", std or HERE.parents[1] / "std"])
    result, _ = run([*args, source], output, expected=wanted)
    if wanted:
        fragment = CASES[case].get("diagnostic", "") if diagnostic is None else diagnostic
        if not fragment or fragment not in result.stdout or str(source) + ":" not in result.stdout:
            raise RuntimeError(f"{case}: the owning source refusal was not observed:\n{result.stdout}")
    return result


def matrix(run, compilers, out, jobs=1, names=None):
    names = list(CASES) if names is None else list(names)
    if not names or len(set(names)) != len(names) or any(n not in CASES for n in names):
        raise ValueError('Empty, duplicate or unknown source case selector')
    rows = []
    for backend, compiler in compilers:
        def case(item):
            name, contract = item
            started = time.monotonic()
            work = out / (backend + "-" + name)
            work.mkdir()
            source = HERE / "cases" / (name + ".dawn")
            observe(run, compiler, name, work / "check.log")
            result, _ = run([*compiler, "run", "--std", HERE.parents[1] / "std", source],
                            work / "run.log", expected=contract["exit"])
            if contract["exit"] == 0:
                if result.stdout != contract["stdout"]:
                    raise RuntimeError(f"{backend} {name}: runtime output mismatch: {result.stdout!r}")
            elif contract["diagnostic"] not in result.stdout:
                raise RuntimeError(f"{backend} {name}: run did not retain the check refusal")
            return dict(backend=backend, case=name, checked=True, ran=True,
                        exit=contract["exit"], started=started, ended=time.monotonic())

        # A case owns its check, run and logs. Only completed whole cases may
        # report success; map retains registry order and joins all workers
        # before either the next backend or the caller's temporary cleanup.
        telemetry_seconds = 0.0
        with ThreadPoolExecutor(max_workers=jobs) as workers:
            for row in workers.map(case, [(n, CASES[n]) for n in names]):
                telemetry_start = time.monotonic()
                rows.append(row)
                (out / "summary-cases.json").write_text(json.dumps(rows, indent=2) + "\n")
                print("CAPTURE_TASK " + json.dumps(row, sort_keys=True), flush=True)
                print(f"PASS {backend} {row['case']}: check and run", flush=True)
                telemetry_seconds += time.monotonic() - telemetry_start
        print("CAPTURE_TELEMETRY " + json.dumps(dict(phase=backend + "_case_results", seconds=telemetry_seconds)), flush=True)
    return rows
