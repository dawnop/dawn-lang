#!/usr/bin/env python3
"""Check delivered types and actual environments through both compiler frontends.

The manifest distinguishes ordinary type hiding from real resources, witnesses
and invariant storage. Refusals name the owning rule so an unrelated parser or
setup failure cannot stand in for a semantic result.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "cases.json").read_text())


def observe(run, compiler, case, output, expected=None, diagnostic=None, std=None):
    source = HERE / "cases" / (case + ".dawn")
    wanted = CASES[case]["exit"] if expected is None else expected
    result, _ = run([*compiler, "check", "--std", (std or HERE.parents[1] / "std"), source],
                    output, expected=wanted)
    if wanted:
        fragment = CASES[case].get("diagnostic", "") if diagnostic is None else diagnostic
        if not fragment or fragment not in result.stdout or str(source) + ":" not in result.stdout:
            raise RuntimeError(f"{case}: the owning source refusal was not observed:\n{result.stdout}")
    return result


def matrix(run, compilers, out):
    rows = []
    for backend, compiler in compilers:
        for name, contract in CASES.items():
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
            rows.append(dict(backend=backend, case=name, checked=True, ran=True,
                             exit=contract["exit"]))
            (out / "summary-cases.json").write_text(json.dumps(rows, indent=2) + "\n")
            print(f"PASS {backend} {name}: check and run", flush=True)
