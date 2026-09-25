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

    # run-pole: 950s (the worst figure any job's budget line may claim)

The pole used to be a claim about the longest job, on the premise that the
run's wall clock is its longest job. That premise was measured false on
2026-09-10 (run 34484938024: span 1506s, longest job 670s) and gates.yml's
header now carries the replacement. The pole is the QUEUE FLOOR --
total job-seconds divided by the account's 20 concurrent runners -- so it is
the figure a single job may claim before it, alone, becomes the run's
critical path. Everything else about it is unchanged: a job that regresses
past the pole must restate its budget (the 3x rule), the restatement collides
with the pole, and raising the pole is a visible, reviewable edit. What this
pins is the per-job claims, not the literal run wall clock: queueing,
dispatch delay and the coverage guard's tail are outside it, and a checker
cannot read a future run. ci.yml and release.yml are not under the pole --
their jobs (the secrets scan, the release pipeline) are not part of the
every-push gate run whose length the pole exists to hold.

WHICH FILES THIS READS. Every .github/workflows/*.yml that carries at least
one `# budget:` line, discovered rather than listed. It used to be a list of
three names, and on 2026-09-11 a push's gate set stopped being three files:
editor-grammar.yml and tile.yml are gate workflows behind `paths:` triggers,
and a hand-kept list would have let their timeouts and their claims go
unchecked exactly the way a hand-kept gate list once let release.yml's subset
drift from ci.yml's. tile.yml in particular is where the tallest claim in the
repository now lives, so leaving it outside the pole would have made the pole
a statement about a strict subset of the gates.

A workflow with NO `# budget:` line is skipped whole, and the skipped files
are printed so the exemption is visible rather than silent. That is
nightly.yml's documented position: nothing waits on a scheduled run, so its
timeout is a runaway stop and not a claim about the work. It is also, plainly,
the way out of this check, which is why the names are printed every run.

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

THE TOTAL. Every rule above is about one job, and one month showed that no
set of per-job rules holds the sum. Between 2026-08-25 and 2026-09-24 the
median successful main push went from 7.2k to 21.6k job-seconds (360 ci.yml
runs read from the Actions API; agent research of 2026-09-25) while every
claim stayed under 3x its timeout and under the pole, and every gate was
green. The growth was new jobs, not slower ones: 09-23 alone added five. A
per-job rule cannot see a new job that is itself small, and on a run whose
span is set by the queue (gates.yml's header has the arithmetic) the total is
what the span follows. So two files carry one more file-level line each:

    # push-total: 29319s   (gates.yml: every job a push to main runs)
    # path-total: 5484s    (tile.yml: the gates behind a `paths:` trigger)

The sum of that file's `3x <N>s` claims may not exceed the figure. Claims and
not measurements, for the pole's reason: this runs offline, and the nightly
audit (`--observed`, below) already holds every claim at or above its job's
worst run, so the claims' sum bounds what a push really costs. Floor claims
are outside it, as they are outside the pole. The figure only goes down
without a word; raising it needs a `Gate-Budget(<name>): <old>s -> <new>s
<why>` line in the push that raises it, which
scripts/check-gate-budget-trailers.py holds in ci.yml's secrets job, because
that is the job that can see a push's commits and this one reads a tree.
editor-grammar.yml carries no total: its only claims are floors.

A total line that is missing, doubled, not a whole number of seconds, placed
in a file other than the one named above, or placed in a file with no `3x`
claim to add up is refused, each for the pole line's reason: a cap that has
quietly stopped being read is a cap that is gone.

Run with --selftest to see each rule refuse a mutated input; a checker whose
red has never been observed is a checker nobody can rely on.
"""

import argparse
import json
import re
import sys
from pathlib import Path

TIMEOUT_RE = re.compile(r"^(\s*)timeout-minutes:\s*(\d+)\s*$")
BUDGET_RE = re.compile(r"^\s*#\s*budget:\s*(.+?)\s*$")
THREE_X_RE = re.compile(r"^3x\s+(\d+)s\b")
FLOOR_RE = re.compile(r"^floor\b")
JOB_RE = re.compile(r"^  ([A-Za-z][\w-]*):\s*$")
RUN_POLE_RE = re.compile(r"^#\s*run-pole:\s*(\d+)s\b")

MULTIPLE = 3
RUN_POLE_FILE = "gates.yml"

# `# push-total: <N>s` / `# path-total: <N>s`, at the start of a line like the
# pole. The value is captured loosely so that a malformed one is refused by
# name instead of making the line invisible.
TOTAL_RE = re.compile(r"^#\s*(push-total|path-total):\s*(.*?)\s*$")
TOTAL_VALUE_RE = re.compile(r"^(\d+)s(?:\s|$)")
# Which file each total governs. The push total is gates.yml's because every
# job there runs on every push to main; the path total is tile.yml's because
# its gates run only on the pushes its `paths:` names, so adding it to the
# push total would count a cost most pushes do not pay.
TOTAL_FILES = {"push-total": "gates.yml", "path-total": "tile.yml"}

# Not part of the every-push gate run whose length the pole exists to hold, so
# their claims are checked against the 3x rule and not against the pole. Their
# timeouts are checked like everyone else's.
POLE_EXEMPT = {"ci.yml", "release.yml"}


def workflow_path(root, name):
    """Where a workflow file lives.

    Spelled as one literal join chain and called from everywhere else,
    because gate-map's rule B reads `root / "a" / "b"` chains and this one is
    the only reason anything in this repository watches .github/workflows.
    Its negative control is gatemap's `drop-the-one-path-join` mutant, which
    replaces this expression with `root` and requires the coupling to
    vanish -- so there has to stay exactly one of these in this file.
    """
    return root / ".github" / "workflows" / name


def budgeted_workflows(root):
    """-> (files carrying a `# budget:` line, files skipped for carrying none).

    Both halves are returned because the caller prints the second one. A
    workflow can leave this check by having no budget line, and that is a
    real decision some workflow will want to make; what it may not do is make
    it quietly.
    """
    carried, skipped = [], []
    for path in sorted(workflow_path(root, ".").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        (carried if any(BUDGET_RE.match(ln) for ln in text.splitlines())
         else skipped).append(path.name)
    return carried, skipped


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


def find_run_pole(text, name):
    """-> (problems, the pole in seconds or None).

    The line lives in gates.yml and governs every workflow that is part of a
    push's gate set, which since 2026-09-11 is more than one file. Exactly one
    `# run-pole: <N>s` line must exist.
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
        ], None
    if len(poles) > 1:
        where = ", ".join(str(line_number) for line_number, _pole in poles)
        return [
            f"{name}: {len(poles)} `# run-pole:` lines (lines {where});"
            " exactly one may exist"
        ], None
    return [], poles[0][1]


def check_claims_under_pole(text, name, pole):
    """No job's `3x <N>s` budget claim may exceed the pole.

    Floor budgets are outside it for the reason they are outside the 3x rule.
    """
    lines = text.splitlines()
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


def check_run_pole(text, name):
    """The pole line and this file's own claims, for the file that carries it."""
    problems, pole = find_run_pole(text, name)
    if pole is None:
        return problems
    return problems + check_claims_under_pole(text, name, pole)


def claim_total(text, name):
    """The sum of one file's `3x <N>s` claims, and how many there are.

    Read through collect_budgets, the walk the observation audit uses, so the
    claims this adds up are exactly the ones --observed holds to real runs.
    """
    seconds = []
    for _job, _line, claim, _minutes in collect_budgets(text, name):
        three_x = THREE_X_RE.match(claim)
        if three_x:
            seconds.append(int(three_x.group(1)))
    return sum(seconds), len(seconds)


def total_lines(text):
    """-> [(line_number, total name, raw value)] for every total line."""
    found = []
    for i, line in enumerate(text.splitlines()):
        total_match = TOTAL_RE.match(line)
        if total_match:
            found.append((i + 1, total_match.group(1), total_match.group(2)))
    return found


def read_total(text, name, total):
    """-> (problems, seconds or None) for the one `# <total>:` line of a file.

    Shared with scripts/check-gate-budget-trailers.py, which reads the same
    line at the two ends of a push and must not disagree with this about what
    the line says.
    """
    lines = [(n, raw) for n, which, raw in total_lines(text) if which == total]
    if not lines:
        return [
            f"{name}: no `# {total}:` line -- the cap on the sum of this"
            " file's budget claims is gone"
        ], None
    if len(lines) > 1:
        where = ", ".join(str(n) for n, _raw in lines)
        return [
            f"{name}: {len(lines)} `# {total}:` lines (lines {where});"
            " exactly one may exist"
        ], None
    line_number, raw = lines[0]
    value = TOTAL_VALUE_RE.match(raw)
    if not value:
        return [
            f"{name}:{line_number}: `# {total}: {raw}` is not a whole number"
            " of seconds (`<N>s`)"
        ], None
    return [], int(value.group(1))


def check_totals(texts):
    """Every total rule over {file name: text} of the workflow directory."""
    problems = []
    for name, text in sorted(texts.items()):
        for line_number, which, _raw in total_lines(text):
            if TOTAL_FILES[which] != name:
                problems.append(
                    f"{name}:{line_number}: a `# {which}:` line belongs in"
                    f" {TOTAL_FILES[which]}, and one anywhere else is a cap"
                    " nothing reads"
                )
    for total, name in sorted(TOTAL_FILES.items()):
        if name not in texts:
            problems.append(f"{name} is missing, so its `# {total}:` line is too")
            continue
        text = texts[name]
        found, cap = read_total(text, name, total)
        problems.extend(found)
        if cap is None:
            continue
        seconds, count = claim_total(text, name)
        if not count:
            problems.append(
                f"{name}: carries `# {total}: {cap}s` and no `3x <N>s` claim"
                " for it to cap"
            )
        elif seconds > cap:
            problems.append(
                f"{name}: its {count} budget claims sum to {seconds}s,"
                f" {seconds - cap}s over the {cap}s {total} -- retire or slim"
                f" a job, or raise the line with a `Gate-Budget({total}):"
                f" {cap}s -> {seconds}s <why>` line in the commit message"
            )
    return problems


def workflow_texts(root):
    """{file name: text} of every workflow, budget line or not.

    The totals are read from all of them and not only the budgeted ones, so
    that a total line moved into a file this check otherwise skips is still
    seen and refused.
    """
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(workflow_path(root, ".").glob("*.yml"))
    }


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

    # The pole now governs files that do not carry it, so the claim check has
    # to be seen refusing one on its own. Without this, a bug that only ever
    # compared a file with its own pole line would pass every case above.
    borrowed_good = """\
jobs:
  long:
    # budget: 3x 900s worst observed
    timeout-minutes: 45
"""
    if check_claims_under_pole(borrowed_good, "good-borrowed.yml", 950):
        failures.append(
            "a claim under a pole read from another file was refused"
        )
    else:
        print("  accepted: a claim under a pole read from another file")
    if not check_claims_under_pole(
        borrowed_good.replace("3x 900s", "3x 1000s"), "mutant-borrowed.yml", 950
    ):
        failures.append(
            "mutant not caught: a claim over a pole read from another file"
        )
    else:
        print("  refused: a claim over a pole read from another file")

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

    # The totals. The clean tree is two files, each carrying its own line and
    # claims under it; every mutant moves one thing, and the claim that pushes
    # the sum over is the one a new job would be.
    totals_good = {
        "gates.yml": """\
# push-total: 1000s
jobs:
  long:
    # budget: 3x 600s worst observed
    timeout-minutes: 30
  short:
    # budget: 3x 400s worst observed
    timeout-minutes: 20
  quick:
    # budget: floor (seconds-scale job)
    timeout-minutes: 10
""",
        "tile.yml": """\
# path-total: 300s
jobs:
  shard:
    # budget: 3x 300s worst observed
    timeout-minutes: 15
""",
        "ci.yml": """\
jobs:
  secrets:
    # budget: floor (seconds-scale job)
    timeout-minutes: 10
""",
    }
    new_job = """  added:
    # budget: 3x 50s worst observed
    timeout-minutes: 3
"""

    def moved(name, text):
        return {**totals_good, name: text}

    totals_mutants = [
        ("a new claim that takes the push total over its line",
         moved("gates.yml", totals_good["gates.yml"] + new_job)),
        ("a claim restated past the path total",
         moved("tile.yml", totals_good["tile.yml"].replace("3x 300s", "3x 301s"))),
        ("the push-total line removed",
         moved("gates.yml", totals_good["gates.yml"].replace("# push-total: 1000s\n", ""))),
        ("a second push-total line",
         moved("gates.yml", "# push-total: 2000s\n" + totals_good["gates.yml"])),
        ("a push-total that is not a number of seconds",
         moved("gates.yml", totals_good["gates.yml"].replace("1000s", "about 1000s"))),
        ("a push-total line in a file with no claim to cap",
         moved("ci.yml", "# push-total: 1000s\n" + totals_good["ci.yml"])),
        ("the path total's file left with no claim under it",
         moved("tile.yml", "# path-total: 300s\njobs: {}\n")),
    ]
    if check_totals(totals_good):
        failures.append(
            "the unmutated totals input was refused: "
            + "; ".join(check_totals(totals_good))
        )
    if claim_total(totals_good["gates.yml"], "gates.yml") != (1000, 2):
        failures.append("the claim total no longer adds up the 3x claims only")
    for label, texts in totals_mutants:
        if not check_totals(texts):
            failures.append(f"mutant not caught: {label}")
        else:
            print(f"  refused: {label}")

    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    count = (len(mutants) + len(pole_mutants) + len(observed_mutants)
             + len(totals_mutants))
    print(f"selftest: {count} mutant(s) refused, clean inputs accepted")
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

    workflows, skipped = budgeted_workflows(root)
    if skipped:
        print(
            "note: no `# budget:` line, so not read: " + ", ".join(skipped)
        )
    if RUN_POLE_FILE not in workflows:
        print(
            f"{RUN_POLE_FILE} carries no budget line, so the run-pole line"
            " cannot be read -- the cap on what any job may claim is gone",
            file=sys.stderr,
        )
        return 1

    pole_problems, pole = find_run_pole(
        workflow_path(root, RUN_POLE_FILE).read_text(encoding="utf-8"),
        RUN_POLE_FILE,
    )

    problems = list(pole_problems)
    notes = []
    checked = 0
    for name in workflows:
        path = workflow_path(root, name)
        checked += 1
        text = path.read_text(encoding="utf-8")
        problems.extend(check_text(text, name))
        if pole is not None and name not in POLE_EXEMPT:
            problems.extend(check_claims_under_pole(text, name, pole))
        if observations is not None:
            found, said = check_observed(
                collect_budgets(text, name), observations, name
            )
            problems.extend(found)
            notes.extend(said)

    if not checked:
        print("no workflow files found -- this check saw nothing", file=sys.stderr)
        return 1
    texts = workflow_texts(root)
    problems.extend(check_totals(texts))
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
    print(
        f"OK: {checked} workflow file(s) under a {pole}s pole"
        f" ({', '.join(workflows)}), every timeout backed by a budget line"
    )
    for total, name in sorted(TOTAL_FILES.items()):
        _found, cap = read_total(texts[name], name, total)
        seconds, count = claim_total(texts[name], name)
        print(f"OK: {name}'s {count} claims sum to {seconds}s, within its"
              f" {cap}s {total} ({cap - seconds}s to spare)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
