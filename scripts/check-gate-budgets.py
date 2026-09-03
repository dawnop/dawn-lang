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

Both halves of that arithmetic read the same file the claim lives in, so
neither can notice a claim that has simply stopped being true: a job can
double in cost while its timeout stays three times a number nobody remeasured.
On 2026-09-03 twenty-one of gates.yml's budget lines were under their job's
own worst run since 09-02, native-diff's by 562s, and every gate was green.

    --observed <file>   compare each claim with what the job actually took

The file is written by scripts/gate-observations.py, which reads the Actions
API. That is why this mode is not in CI: a gate that needs the network and a
token is a gate that goes red for the network. It is the audit to run by hand
before restating a budget line, and it is what a restatement cites:

    scripts/gate-observations.py --since 2026-09-02T00:00:00Z --out /tmp/obs.json
    scripts/check-gate-budgets.py --observed /tmp/obs.json

A `3x <N>s` claim is refused when the observed maximum is above N. A `floor`
claim is refused when three times the observation no longer fits inside the
timeout the floor was granted -- the floor exists because 3x six seconds is a
bound no runner could meet, and a job that grew to minutes is no longer
covered by that reason. A job with no observation (a shard whose first run has
not happened) is reported and not refused; its budget line says "planning
value" for exactly that reason. The default invocation is unchanged: it is
what CI runs, and it does not read this file.

Run with --selftest to see each rule refuse a mutated input; a checker whose
red has never been observed is a checker nobody can rely on.
"""

import argparse
import json
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


def collect_budgets(text, name):
    """Every budgeted timeout in one file: (job, line_number, claim, minutes).

    The same walk check_text does, kept as its own function because the
    observation audit asks a different question of the same records and must
    not change what CI's walk refuses.
    """
    lines = text.splitlines()
    records = []
    job = "?"
    for i, line in enumerate(lines):
        job_match = JOB_RE.match(line)
        if job_match:
            job = job_match.group(1)
            continue
        timeout_match = TIMEOUT_RE.match(line)
        if not timeout_match or i == 0:
            continue
        budget_match = BUDGET_RE.match(lines[i - 1])
        if not budget_match:
            continue
        records.append((job, i + 1, budget_match.group(1), int(timeout_match.group(2))))
    return records


def check_observed(records, observations, name):
    """Return (problems, notes) from comparing declared values with real runs.

    A claim is a claim about the worst case, so the comparison is against the
    maximum, not the median: an average puts a routinely-observed run inside
    the kill window, which is the reasoning the 3x rule already carries.
    """
    problems = []
    notes = []
    for job, line_number, claim, minutes in records:
        where = f"{name}:{line_number} ({job})"
        seconds = observations.get(job)
        if seconds is None:
            notes.append(f"{where}: no observation in this window")
            continue
        three_x = THREE_X_RE.match(claim)
        if three_x:
            declared = int(three_x.group(1))
            if seconds > declared:
                problems.append(
                    f"{where}: declares {declared}s but ran {seconds}s"
                    f" -- {seconds - declared}s of the worst case is undeclared;"
                    f" restate the line as 3x {seconds}s and take the timeout to"
                    f" {-(-MULTIPLE * seconds // 60)}min"
                )
            continue
        if FLOOR_RE.match(claim):
            if MULTIPLE * seconds > minutes * 60:
                problems.append(
                    f"{where}: claims the floor but ran {seconds}s, and"
                    f" {MULTIPLE}x that is over the {minutes}min it was granted"
                    " -- the floor is for jobs whose own 3x no runner could"
                    " meet, so this one has outgrown it and owes a real"
                    " observation"
                )
            continue
    return problems, notes


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

    # The observation audit. Its whole point is that the two numbers come from
    # different places, so the mutants move the observation as well as the
    # claim: a claim under the run is refused, a claim over it is not, and a
    # floor granted to a seconds-scale job is refused once the job is not one.
    observed_good = """\
jobs:
  slow:
    # budget: 3x 600s worst observed
    timeout-minutes: 30
  quick:
    # budget: floor (seconds-scale job)
    timeout-minutes: 10
"""
    observed_runs = {"slow": 550, "quick": 8}
    observed_mutants = [
        ("a claim under the job's own worst run",
         observed_good, {"slow": 700, "quick": 8}),
        ("a claim one second under it",
         observed_good, {"slow": 601, "quick": 8}),
        ("a floor on a job that grew to minutes",
         observed_good, {"slow": 550, "quick": 400}),
        ("a claim restated downwards past the run",
         observed_good.replace("3x 600s", "3x 300s"), observed_runs),
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

    clean_found, clean_notes = check_observed(
        collect_budgets(observed_good, "good-observed.yml"), observed_runs,
        "good-observed.yml")
    if clean_found:
        failures.append(
            "the unmutated observation input was refused: "
            + "; ".join(clean_found)
        )
    if clean_notes:
        failures.append(
            "a job with an observation was reported as unobserved: "
            + "; ".join(clean_notes)
        )
    for label, text, runs in observed_mutants:
        found, _notes = check_observed(
            collect_budgets(text, "mutant-observed.yml"), runs,
            "mutant-observed.yml")
        if not found:
            failures.append(f"mutant not caught: {label}")
        else:
            print(f"  refused: {label}")

    # A job the observation window never saw is a note, not a refusal: the
    # shard whose first run has not happened yet is exactly the case, and
    # refusing it would make the audit unrunnable on the tree that needs it.
    _found, unseen = check_observed(
        collect_budgets(observed_good, "unseen.yml"), {"quick": 8}, "unseen.yml")
    if _found:
        failures.append("an unobserved job was refused rather than reported")
    elif len(unseen) != 1:
        failures.append(f"an unobserved job was not reported: {unseen}")
    else:
        print("  reported (not refused): a job with no observation in the window")

    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print(
        f"selftest: {len(mutants) + len(pole_mutants) + len(observed_mutants)}"
        " mutant(s) refused, clean inputs accepted"
    )
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument(
        "--observed",
        type=Path,
        default=None,
        help="a scripts/gate-observations.py report; refuse every claim under"
        " the maximum it records (manual audit, not run in CI)",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    if args.selftest:
        return selftest(root)

    observations = None
    if args.observed is not None:
        report = json.loads(args.observed.read_text(encoding="utf-8"))
        observations = report["jobs"]
        print(
            f"observations: {len(observations)} job(s) over"
            f" {len(report.get('runs', []))} run(s)"
            f" ({report.get('oldest_run_created', '?')}"
            f" .. {report.get('newest_run_created', '?')})"
        )

    problems = []
    notes = []
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
        if observations is not None:
            found, said = check_observed(
                collect_budgets(text, name), observations, name
            )
            problems.extend(found)
            notes.extend(said)

    if not checked:
        print("no workflow files found -- this check saw nothing", file=sys.stderr)
        return 1
    for note in notes:
        print(f"note: {note}")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1

    rc = selftest(root)
    if rc:
        return rc
    if observations is not None:
        print(
            "OK: every budget line is at or above the worst run in the"
            " observation file"
        )
    print(f"OK: {checked} workflow file(s), every timeout backed by a budget line")
    return 0


if __name__ == "__main__":
    sys.exit(main())
