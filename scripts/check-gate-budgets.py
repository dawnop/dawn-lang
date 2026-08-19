#!/usr/bin/env python3
"""Hold every CI job's timeout to the budget rule its comment claims.

The rule the workflow already states in prose: a job's `timeout-minutes` is at
least three times its worst observed run, so a slow runner is a slow run and
not a killed one. Seconds-scale jobs take a floor instead, because 3x six
seconds is a bound no runner could meet.

Until now that rule lived only in the prose. It drifted: after the 2026-08-10
redistribution two jobs sat three seconds under 3x for a day, and nothing
noticed -- the numbers in the comments were right, the arithmetic was nobody's
job. Prose cannot be the enforcement surface, so each timeout now carries one
machine-readable line directly above it:

    # budget: 3x 533s worst observed
    timeout-minutes: 27

    # budget: floor (seconds-scale job; 3x its own time is unmeetable)
    timeout-minutes: 10

The prose above it stays as it is -- that is where the reasoning belongs, and
this line deliberately carries no reasoning, only the number the arithmetic
needs. Raising a timeout without restating the observation it came from is the
drift this catches.

gates.yml additionally carries one file-level line:

    # run-pole: 660s (the worst figure any job's budget line may claim)

The run's wall clock is its longest job, and the 3x rule already forces every
job's worst observation into its budget line -- so capping the worst claim
caps the run, and the speedup that bought the current pole is held by a
machine instead of by memory. A job that regresses past the pole must restate
its budget (the 3x rule), the restatement collides with the pole, and raising
the pole is a visible, reviewable edit. What this pins is the per-job claims,
not the literal run wall clock: queueing, dispatch delay and the coverage
guard's tail are outside it, and a checker cannot read a future run. ci.yml
and release.yml are not under the pole -- their jobs (the secrets scan, the
release pipeline) are not part of the every-push gate run whose length the
pole exists to hold.

Run with --selftest to see each rule refuse a mutated input; a checker whose
red has never been observed is a checker nobody can rely on.
"""

import re
import sys
from pathlib import Path

WORKFLOWS = ["gates.yml", "ci.yml", "release.yml"]
TIMEOUT_RE = re.compile(r"^(\s*)timeout-minutes:\s*(\d+)\s*$")
BUDGET_RE = re.compile(r"^\s*#\s*budget:\s*(.+?)\s*$")
THREE_X_RE = re.compile(r"^3x\s+(\d+)s\b")
FLOOR_RE = re.compile(r"^floor\b")
JOB_RE = re.compile(r"^  ([A-Za-z][\w-]*):\s*$")
RUN_POLE_RE = re.compile(r"^#\s*run-pole:\s*(\d+)s\b")

MULTIPLE = 3
RUN_POLE_FILE = "gates.yml"


def check_text(text, name):
    """Return a list of complaints about one workflow file's text."""
    lines = text.splitlines()
    problems = []
    job = "?"
    for i, line in enumerate(lines):
        job_match = JOB_RE.match(line)
        if job_match:
            job = job_match.group(1)
            continue
        timeout_match = TIMEOUT_RE.match(line)
        if not timeout_match:
            continue
        minutes = int(timeout_match.group(2))
        where = f"{name}:{i + 1} ({job})"

        if i == 0:
            problems.append(f"{where}: timeout-minutes with no budget line above it")
            continue
        budget_match = BUDGET_RE.match(lines[i - 1])
        if not budget_match:
            problems.append(
                f"{where}: the line above timeout-minutes is not a `# budget:` line"
            )
            continue
        claim = budget_match.group(1)

        if FLOOR_RE.match(claim):
            continue
        three_x = THREE_X_RE.match(claim)
        if not three_x:
            problems.append(
                f"{where}: budget `{claim}` is neither `3x <N>s ...` nor `floor ...`"
            )
            continue
        seconds = int(three_x.group(1))
        if minutes * 60 < MULTIPLE * seconds:
            short = MULTIPLE * seconds - minutes * 60
            problems.append(
                f"{where}: {minutes}min is {short}s short of {MULTIPLE}x {seconds}s"
                f" -- raise the timeout to {-(-MULTIPLE * seconds // 60)}min"
                f" or restate the observation"
            )
    return problems


def check_run_pole(text, name):
    """Return the complaints about the file-level run-pole cap.

    Applied to gates.yml only (see the module docstring for why the other
    workflows are exempt). Exactly one `# run-pole: <N>s` line must exist,
    and no job's `3x <N>s` budget claim may exceed it; floor budgets are
    outside it for the reason they are outside the 3x rule.
    """
    lines = text.splitlines()
    poles = []
    for i, line in enumerate(lines):
        pole_match = RUN_POLE_RE.match(line)
        if pole_match:
            poles.append((i + 1, int(pole_match.group(1))))
    if not poles:
        return [
            f"{name}: no `# run-pole:` line -- the cap on what any job's"
            " budget may claim is gone"
        ]
    if len(poles) > 1:
        where = ", ".join(str(line_number) for line_number, _pole in poles)
        return [
            f"{name}: {len(poles)} `# run-pole:` lines (lines {where});"
            " exactly one may exist"
        ]
    pole = poles[0][1]

    problems = []
    job = "?"
    for i, line in enumerate(lines):
        job_match = JOB_RE.match(line)
        if job_match:
            job = job_match.group(1)
            continue
        budget_match = BUDGET_RE.match(line)
        if not budget_match:
            continue
        three_x = THREE_X_RE.match(budget_match.group(1))
        if not three_x:
            continue
        seconds = int(three_x.group(1))
        if seconds > pole:
            problems.append(
                f"{name}:{i + 1} ({job}): budget claims 3x {seconds}s, over the"
                f" {pole}s run-pole -- either this job now outlasts the run's"
                " agreed longest or the pole must be raised, and both are"
                " reviewable edits, not silent ones"
            )
    return problems


def selftest(root):
    """Every rule must be seen refusing something before its silence means pass."""
    good = """
jobs:
  slow:
    # budget: 3x 100s worst observed
    timeout-minutes: 5
  quick:
    # budget: floor (seconds-scale job)
    timeout-minutes: 10
"""
    mutants = [
        ("timeout one second under 3x", good.replace("timeout-minutes: 5", "timeout-minutes: 4")),
        ("budget line removed", good.replace("    # budget: 3x 100s worst observed\n", "")),
        ("budget line pushed away from the value",
         good.replace("    # budget: 3x 100s worst observed\n    timeout-minutes: 5",
                      "    # budget: 3x 100s worst observed\n    # a note that got in between\n    timeout-minutes: 5")),
        ("budget claim in neither form", good.replace("3x 100s worst observed", "about a minute")),
        ("floor spelled as prose", good.replace("floor (seconds-scale job)", "it is fast")),
    ]

    pole_good = """\
# run-pole: 660s (the worst figure any job's budget line may claim)
jobs:
  long:
    # budget: 3x 557s worst observed
    timeout-minutes: 28
  quick:
    # budget: floor (seconds-scale job)
    timeout-minutes: 10
"""
    pole_mutants = [
        ("a budget claim over the run-pole", pole_good.replace("3x 557s", "3x 700s")),
        ("the run-pole line removed",
         pole_good.replace(
             "# run-pole: 660s (the worst figure any job's budget line may claim)\n",
             "")),
        ("a second run-pole line",
         pole_good.replace("# run-pole: 660s", "# run-pole: 900s\n# run-pole: 660s")),
    ]

    failures = []
    if check_text(good, "good.yml"):
        failures.append("the unmutated input was refused: " + "; ".join(check_text(good, "good.yml")))
    for label, text in mutants:
        if not check_text(text, "mutant.yml"):
            failures.append(f"mutant not caught: {label}")
        else:
            print(f"  refused: {label}")

    if check_run_pole(pole_good, "good-pole.yml"):
        failures.append(
            "the unmutated run-pole input was refused: "
            + "; ".join(check_run_pole(pole_good, "good-pole.yml"))
        )
    for label, text in pole_mutants:
        if not check_run_pole(text, "mutant-pole.yml"):
            failures.append(f"mutant not caught: {label}")
        else:
            print(f"  refused: {label}")

    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print(
        f"selftest: {len(mutants) + len(pole_mutants)} mutant(s) refused, "
        "clean inputs accepted"
    )
    return 0


def main():
    root = Path(__file__).resolve().parent.parent
    if "--selftest" in sys.argv[1:]:
        return selftest(root)

    problems = []
    checked = 0
    for name in WORKFLOWS:
        path = root / ".github" / "workflows" / name
        if not path.exists():
            continue
        checked += 1
        text = path.read_text(encoding="utf-8")
        problems.extend(check_text(text, name))
        if name == RUN_POLE_FILE:
            problems.extend(check_run_pole(text, name))

    if not checked:
        print("no workflow files found -- this check saw nothing", file=sys.stderr)
        return 1
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        return 1

    rc = selftest(root)
    if rc:
        return rc
    print(f"OK: {checked} workflow file(s), every timeout backed by a budget line")
    return 0


if __name__ == "__main__":
    sys.exit(main())
