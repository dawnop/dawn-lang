#!/usr/bin/env python3
"""Read the transcripts of the "interpreter against tileref" run and decide.

Why the judgement is made here rather than by each family's last line. A
family program ends `tile-gpu-diff: pass | blocked:<kind>@<stage> | fail`, and
one kernel the interpreter refuses makes a whole family `blocked`. What this
gate needs is finer: every case either agreed, or was blocked by a refusal the
interpreter made BEFORE running anything (`interp.unsupported_op`), and no case
differed or was stopped by anything else. So it reads each `  verdict` line,
and attributes to it the kernels the `interp ...` lines since the previous
verdict say were launched (glue.dawn prints one after every interpreted run).
`control ...` and `mutant ...` verdict lines (seq_diff runs its mutants on the
"device", which is the interpreter here) end an attribution window without
being judged: a mutant is supposed to differ.

Two other refusals are excused, each narrowly. `interp.ub` only for a kernel
listed in expected-ub.txt (its corpus reaches undefined behaviour on purpose),
and every kernel listed there must be refused that way. `gpu.fake_inexact`
only as the launch status it is: an i64 past 2^53 that the interpreter, which
takes buffers as Floats the way std/gpu's references do, refuses before
running (dtype_diff's one "big" corpus).

A kernel is COVERED when it ran without a refusal in a case that agreed.
covered.txt pins the covered set: the run must cover exactly it (a kernel
newly covered is a line to add, one no longer covered is a regression).

    verdicts.py <transcript dir> <family>... [--covered covered.txt] [--write]
                [--expected-ub expected-ub.txt]

Each family's transcript is <dir>/<family>.out, or .err for the families that
write it to standard error (assert_diff).
"""
import argparse
import re
import sys
from pathlib import Path

STDERR_FAMILIES = {"assert"}
AGREE = re.compile(r"^(identical|close:tolerance)")
EXCUSED = "blocked:interp.unsupported_op@launch"


def read_family(path: Path, fam: str):
    """(cases, problems): cases are (verdict, [(kernel, status)])."""
    cases, problems, window = [], [], []
    for line in path.read_text().splitlines():
        if line.startswith("interp "):
            for entry in line[len("interp "):].split(","):
                if entry:
                    k, _, st = entry.partition("=")
                    window.append((k, st))
        elif line.startswith("  verdict "):
            cases.append((line[len("  verdict "):].strip(), window))
            window = []
        elif re.match(r"^(control|mutant) .* verdict ", line):
            window = []
    if not cases:
        problems.append(f"{fam}: no `  verdict` line at all")
    return cases, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("families", nargs="+")
    ap.add_argument("--covered")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--expected-ub")
    a = ap.parse_args()
    d = Path(a.dir)
    expected_ub = set()
    if a.expected_ub:
        expected_ub = {ln.split()[0] for ln in Path(a.expected_ub).read_text().splitlines()
                       if ln.strip() and not ln.startswith("#")}
    seen_ub = set()
    covered, refused, problems, launched = set(), {}, [], set()
    agreed = blocked = 0
    for fam in a.families:
        path = d / (fam + (".err" if fam in STDERR_FAMILIES else ".out"))
        cases, probs = read_family(path, fam)
        problems += probs
        for verdict, launches in cases:
            launched |= {k for k, _st in launches}
            kinds = {st for _k, st in launches}
            if AGREE.match(verdict):
                agreed += 1
                bad = [f"{k}={st}" for k, st in launches if st != "ok"]
                if bad:
                    problems.append(f"{fam}: a case agreed although {', '.join(bad)}")
                covered |= {k for k, st in launches if st == "ok"}
            elif verdict == EXCUSED and "interp.unsupported_op" in kinds:
                blocked += 1
                for k, st in launches:
                    if st == "interp.unsupported_op":
                        refused.setdefault(k, fam)
            elif verdict == "blocked:interp.ub@launch" and launches and all(
                    st == "ok" or (st == "interp.ub" and k in expected_ub) for k, st in launches):
                blocked += 1
                seen_ub |= {k for k, st in launches if st == "interp.ub"}
            elif verdict.startswith("blocked:gpu.fake_inexact@") and any(st == "gpu.fake_inexact" for _k, st in launches):
                blocked += 1
            else:
                problems.append(f"{fam}: verdict `{verdict}` after launches {launches}")
    # a kernel that agreed somewhere and was refused elsewhere would mean the
    # refusal depends on the launch, which unsupported_in rules out
    both = sorted(set(refused) & covered)
    if both:
        problems.append(f"covered and refused at once: {' '.join(both)}")
    missing_ub = sorted((expected_ub & launched) - seen_ub)
    if missing_ub:
        problems.append(f"expected-ub kernels not refused as interp.ub: {' '.join(missing_ub)}")
    print(f"cases agreed={agreed} blocked={blocked}")
    print(f"ub-refused {len(seen_ub)}: {' '.join(sorted(seen_ub))}")
    print(f"covered {len(covered)}: {' '.join(sorted(covered))}")
    print(f"refused {len(refused)}: {' '.join(sorted(refused))}")
    if a.covered:
        cp = Path(a.covered)
        if a.write:
            body = [ln for ln in cp.read_text().splitlines() if ln.startswith("#")] if cp.exists() else []
            cp.write_text("\n".join(body + sorted(covered)) + "\n")
            print(f"wrote {cp}")
        else:
            want = {ln.strip() for ln in cp.read_text().splitlines() if ln.strip() and not ln.startswith("#")}
            if covered - want:
                problems.append(f"covered but not in {cp.name}: {' '.join(sorted(covered - want))}")
            if want - covered:
                problems.append(f"in {cp.name} but not covered: {' '.join(sorted(want - covered))}")
    for p in problems:
        print(f"FAIL  {p}")
    if problems:
        print("tileinterp-diff: fail")
        sys.exit(1)
    print("tileinterp-diff: pass")


if __name__ == "__main__":
    main()
