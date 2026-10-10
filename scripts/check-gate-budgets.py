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
header now carries the replacement. The pole was set at the QUEUE FLOOR --
total job-seconds divided by the account's 20 concurrent runners -- so it was
the figure a single job may claim before it, alone, becomes the run's
critical path. By 2026-09-25 the total had grown past it (a floor of about
1,080s against the 950s pole) with every rule here green, which is what the
push total below is for; the pole stays, as the cap on one job. Everything else about it is unchanged: a job that regresses
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
                        (once per workflow: ci.yml's report and tile.yml's)

The file is written by scripts/gate-observations.py, which reads the Actions
API. That is why this mode is not in CI: a gate that needs the network and a
token is a gate that goes red for the network. It is the audit to run by hand
before restating a budget line, and it is what a restatement cites:

    scripts/gate-observations.py --since 2026-09-02T00:00:00Z --out /tmp/obs.json
    scripts/gate-observations.py --workflow tile.yml --allow-empty \
        --since 2026-09-02T00:00:00Z --out /tmp/tile-obs.json
    scripts/check-gate-budgets.py --observed /tmp/obs.json \
        --observed /tmp/tile-obs.json

A `3x <N>s` claim is refused when the observed maximum is above N. A `floor`
claim is refused when three times the observation no longer fits inside the
timeout the floor was granted -- the floor exists because 3x six seconds is a
bound no runner could meet, and a job that grew to minutes is no longer
covered by that reason. A job with no observation (a shard whose first run has
not happened) is reported and not refused; its budget line says "planning
value" for exactly that reason. The default invocation is unchanged: it is
what CI runs, and it does not read this file.

HOW TO RESTATE A CLAIM (2026-10-06). New figure = the worst run whose steps
digest is the job's own, plus the larger of a tenth of it and one standard
deviation of that job's runs in the same window, rounded up to 5s; timeout 3x
the figure. A flat tenth loses to runner jitter: 95e7c21c restated
native-diff-2 to 470s (426s plus a tenth) and a run took 488s a day later,
while one deviation (66s) over 426s would have covered it. The check itself
only requires claim >= worst; this is how to pick the number.

WHICH RUNS A CLAIM IS HELD TO (issue #244). By steps, not by name. A
gates.yml job's runs are the ones whose steps digest (gate-observations.py
records it per run, from gates.yml at the run's own commit, through
scripts/gates-external/steps_lock.py's job_digests) equals the job's digest
in this tree, whatever the job was called when it ran. Keyed by name, a job
split in place kept a week of its old, larger shape's runs: round two of the
ratchet (#242) lowered syntax-mutants-1 from 902s to 718s for a third of the
mutants, and the audit held that to 914s of the two-shard job until round
two renamed every split job out of the way. Keyed by steps, the reshard
starts a fresh window and a rename that keeps the steps keeps its history.
A run whose digest matches no job in this tree is counted on one summary
line and compared with nothing. Jobs gatesplan does not model (gates.yml's
`plan`) and the jobs of other workflows (ci.yml's `secrets`) have no digest
and are still matched by name. --observed therefore needs PyYAML; the
default invocation and --selftest do not.

TILE.YML'S SHARDS (2026-10-10, issue #274). tile.yml's jobs are keyed by
steps digest as well, by the plain reader steps_lock.plain_job_digests (the
multiset of a job's `run:` texts, no composite expanded). A tile-golden shard's
run text is `run.sh --shard I/N`, so dealing the matrix seven ways and then
eight keeps the job names and changes the digests: the 7-way runs of the
window are counted on the "older shape" line and compared with no claim, and
only runs of the shape a claim is about hold it. Before this, the eighth
shard would have been audited against a week of 7-way observations under the
same names. A report written before tile.yml carried digests ("steps": {}) is
read as having none, so its jobs are not compared; regenerate it with
gate-observations.py (or --restep).

WHOSE RUNS (2026-10-03). Each file is held to one workflow's report:
gates.yml's and ci.yml's claims to ci.yml's runs (gates.yml is called from
ci.yml, so its jobs are ci.yml's), tile.yml's to tile.yml's own, and any
other file to ci.yml's by name, as before. Until then the audit took one
report, ci.yml's, and tile.yml's jobs are never in it: for a week every one
of its eight claims read "no observation in this window" while its shards
ran past them (980s on main against 827s), and the nightly stayed green. So
--observed is given once per workflow, and a file whose workflow has no
report is refused rather than noted, since an omitted report and a quiet
week otherwise print the same lines. A report with no runs in it (written
with gate-observations.py --allow-empty) is the quiet week, and is a note
per claim. tile.yml's jobs are not modelled by gatesplan, so they are
matched by name.

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

# Whose runs each file's claims are held to under --observed. gates.yml is a
# workflow ci.yml calls, so its jobs run, and are listed, as ci.yml's; tile.yml
# runs as itself. Any other file is read against ci.yml's runs by name, as it
# always was. Every workflow named here must arrive as a report of its own:
# until 2026-10-03 the nightly audit read ci.yml only, and tile.yml's eight
# claims printed "no observation in this window" every night for a week in
# which its shards ran up to 980s on main against an 827s claim.
OBSERVED_FROM = {"ci.yml": "ci.yml", "gates.yml": "ci.yml", "tile.yml": "tile.yml"}
DEFAULT_SOURCE = "ci.yml"
# Which files' claims are held to runs by steps digest rather than by name:
# gates.yml's through gatesplan's digests, tile.yml's through the plain
# reader's (a tile-golden shard's digest carries its `--shard I/N`).
KEYED_FILES = {"gates.yml": "ci.yml", "tile.yml": "tile.yml"}
TILE_PATH = ".github/workflows/tile.yml"


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


class ShapedObservations:
    """The worst run of each job, keyed by steps where a job has them.

    Built from a gate-observations.py report and {job: steps digest} of the
    jobs this tree's gates.yml defines. `for_file(name)` returns the lookup
    check_observed reads with `.get(job)`: for gates.yml a modelled job
    resolves through its digest, and anything else resolves by name among
    the observations that carry no digest.
    """

    def __init__(self, report, digests):
        self.digests = dict(digests)
        self.by_digest = {}
        self.by_name = {}
        self.old_shape = 0
        self.old_shape_runs = set()
        self.unreadable = 0
        self.unreadable_runs = set()
        self.renamed = {}
        self.runs = 0
        today = set(self.digests.values())
        current_name = {digest: job for job, digest in self.digests.items()}
        for record in report.get("per_run", []):
            if "steps" not in record:
                raise SystemExit(
                    "the observation report has no per-run steps digests; it was"
                    " written before issue #244. Regenerate it with the current"
                    " scripts/gate-observations.py, or attach them with its"
                    " --restep <report> --out <file>")
            self.runs += 1
            steps = record["steps"]
            for job, seconds in record["jobs"].items():
                digest = steps.get(job) if steps is not None else None
                if digest is not None:
                    if digest not in today:
                        self.old_shape += 1
                        self.old_shape_runs.add(record["id"])
                        continue
                    if current_name[digest] != job:
                        self.renamed.setdefault((job, current_name[digest]), 0)
                        self.renamed[(job, current_name[digest])] += 1
                    self._keep(self.by_digest, digest, seconds)
                elif steps is None and job in self.digests:
                    # gates.yml at that commit could not be read, and this is
                    # a modelled job today: its shape then is unknown.
                    self.unreadable += 1
                    self.unreadable_runs.add(record["id"])
                else:
                    self._keep(self.by_name, job, seconds)

    @staticmethod
    def _keep(table, key, seconds):
        if seconds > table.get(key, -1):
            table[key] = seconds

    def for_file(self, name):
        digests = self.digests if name in KEYED_FILES else {}
        by_digest, by_name = self.by_digest, self.by_name

        class Lookup:
            @staticmethod
            def get(job):
                if job in digests:
                    return by_digest.get(digests[job])
                return by_name.get(job)

        return Lookup()

    def summary(self):
        """The lines that say what was left out, never one per run."""
        lines = [
            f"{self.old_shape} observation(s) in {len(self.old_shape_runs)}"
            " run(s) carry steps no job in this tree has (an older shape),"
            " so no claim was compared with them"
        ]
        if self.unreadable:
            lines.append(
                f"{self.unreadable} observation(s) in {len(self.unreadable_runs)}"
                " run(s) whose gates.yml gatesplan could not read, so their"
                " shape is unknown and no claim was compared with them")
        for (then, now), count in sorted(self.renamed.items()):
            lines.append(f"{count} run(s) of `{then}` count for `{now}`:"
                         " the same steps under another name")
        return lines


def load_reports(reports, digests):
    """[gate-observations.py report] -> {workflow: ShapedObservations}.

    `digests` is {workflow: {job: steps digest}} (current_digests).

    A report says which workflow it read ("workflow"; ci.yml when absent,
    which is what every report written before 2026-10-03 was). Only the
    report that gates.yml's jobs arrive through is keyed by steps, and so is
    tile.yml's (its shards' `--shard I/N` is in the digest); anything else is
    matched by name.
    Two reports of one workflow are refused: which window wins would be an
    accident of argument order.
    """
    observed = {}
    for report in reports:
        workflow = report.get("workflow") or DEFAULT_SOURCE
        if workflow in observed:
            raise SystemExit(
                f"two observation reports read {workflow}; pass one per"
                " workflow so it is clear which window the claims are held to")
        keyed = digests.get(workflow, {})
        observed[workflow] = ShapedObservations(report, keyed)
    return observed


def audit_observed(texts, observed):
    """-> (problems, notes) of every file's claims against its own runs.

    `texts` is {file: workflow text}, `observed` what load_reports returns.
    A file whose source workflow has no report is refused rather than noted:
    an omitted report looks exactly like a quiet week, every claim reading
    "no observation", and that is how tile.yml went unaudited. A report with
    no runs in it (gate-observations.py --allow-empty) is the quiet week, and
    stays a note per claim.
    """
    problems = []
    notes = []
    for name, text in texts.items():
        records = collect_budgets(text, name)
        if not records:
            continue
        source = OBSERVED_FROM.get(name, DEFAULT_SOURCE)
        if source not in observed:
            problems.append(
                f"{name}: its {len(records)} budget line(s) are held to"
                f" {source} runs, and no {source} report was given, so every"
                " one of them would read as unobserved. Pass --observed a"
                f" report from `gate-observations.py --workflow {source}"
                " --allow-empty` as well")
            continue
        found, said = check_observed(
            records, observed[source].for_file(name), name)
        problems.extend(found)
        notes.extend(said)
    return problems, notes


def current_digests():
    """{workflow: {job: steps digest}} of this tree, via steps_lock.py:
    gates.yml's jobs under ci.yml (the workflow that calls it) and tile.yml's
    under tile.yml.

    The module directory is spelled from this file and not as a join on the
    repository root: gate-map's rule B reads a root join as this checker
    reading the whole directory, and the invocation CI runs reads none of it
    (only --observed imports steps_lock).
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent / "gates-external"))
    import steps_lock
    return {"ci.yml": steps_lock.current_job_digests(),
            "tile.yml": steps_lock.current_plain_job_digests(TILE_PATH)}


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

    # Issue #244: runs are held to a claim by steps digest, not by name.
    # Digests are plain labels here so that this stays free of PyYAML (CI
    # runs it before the step that provides it); the digest itself is
    # steps_lock.py's, and its self-test holds a rename to the same digest.
    shaped_text = observed_good
    today = {"slow": "slow-3-shards", "quick": "quick-steps"}

    def shaped(*runs):
        return {"per_run": [
            {"id": i, "jobs": jobs, "steps": steps}
            for i, (jobs, steps) in enumerate(runs)]}

    current_run = ({"slow": 550, "quick": 8},
                   {"slow": "slow-3-shards", "quick": "quick-steps"})
    old_same_name = ({"slow": 914}, {"slow": "slow-2-shards"})
    old_other_name = ({"slow-1": 917}, {"slow-1": "slow-2-shards"})
    renamed_regressed = ({"slow-old-name": 700},
                         {"slow-old-name": "slow-3-shards"})
    unreadable = ({"slow": 999}, None)
    unmodelled = ({"quick": 400}, {})

    def audit(text, report, digests):
        seen = ShapedObservations(report, digests)
        found, _notes = check_observed(
            collect_budgets(text, "shaped.yml"), seen.for_file(RUN_POLE_FILE),
            RUN_POLE_FILE)
        return found, seen

    shaped_cases = [
        # (label, text, report, digests, want red, check on the lookup)
        ("an older shape's runs under the job's own name and another are"
         " not held to it",
         shaped_text, shaped(current_run, old_same_name, old_other_name,
                             unreadable), today, False,
         lambda seen: seen.old_shape == 2 and seen.unreadable == 1),
        ("the same runs are held to it when its steps are that shape",
         shaped_text, shaped(current_run, old_same_name, old_other_name),
         {**today, "slow": "slow-2-shards"}, True, None),
        ("a renamed job with the same steps keeps its history",
         shaped_text, shaped(current_run, renamed_regressed), today, True,
         lambda seen: seen.renamed == {("slow-old-name", "slow"): 1}),
        ("a claim lowered past the job's current-shape run",
         shaped_text.replace("3x 600s", "3x 500s"), shaped(current_run),
         today, True, None),
        ("an unmodelled job is still matched by name",
         shaped_text, shaped(current_run, unmodelled),
         {"slow": "slow-3-shards"}, True, None),
    ]
    for label, text, report, digests, want_red, extra in shaped_cases:
        found, seen = audit(text, report, digests)
        if bool(found) != want_red:
            failures.append(
                f"steps-keyed audit: {label}: expected"
                f" {'red' if want_red else 'green'}, got {found or 'green'}")
        elif extra is not None and not extra(seen):
            failures.append(f"steps-keyed audit: {label}: counts are wrong")
        else:
            print(f"  {'refused' if want_red else 'accepted'}: {label}")
    try:
        ShapedObservations({"per_run": [{"id": 1, "jobs": {"slow": 1}}]}, today)
        failures.append("a report with no steps digests was read by name")
    except SystemExit:
        print("  refused: a report written before steps digests existed")

    # 2026-10-03: whose runs a file is held to. tile.yml's jobs never appear
    # in ci.yml's runs, so with ci.yml's report alone every tile.yml claim
    # read "no observation" and the audit stayed green over shards that ran
    # past them. The first case reproduces that reading, so the cases after
    # it are known to be about the fix and not about a blind spot that went
    # away by itself.
    tile_text = """\
jobs:
  shard:
    # budget: 3x 827s planning value
    timeout-minutes: 42
"""
    ci_report = shaped(current_run)

    def tile_report(seconds):
        return {"workflow": "tile.yml",
                "per_run": [{"id": 9, "jobs": {"shard": seconds}, "steps": {}}]}

    alone = ShapedObservations(ci_report, today)
    blind_found, blind_notes = check_observed(
        collect_budgets(tile_text, "tile.yml"), alone.for_file("tile.yml"),
        "tile.yml")
    if blind_found or len(blind_notes) != 1:
        failures.append(
            "ci.yml's runs alone no longer read a tile.yml claim as unobserved;"
            " the cases below no longer show what they claim to")
    else:
        print("  shown: ci.yml's runs alone read a tile.yml claim as unobserved")
    source_files = {RUN_POLE_FILE: shaped_text, "tile.yml": tile_text}
    source_cases = [
        # (label, reports, want red, text a refusal must carry)
        ("a tile.yml claim under its own run, ci.yml's report beside it",
         [ci_report, tile_report(980)], True, "declares 827s but ran 980s"),
        ("the tile.yml report left out",
         [ci_report], True, "no tile.yml report was given"),
        ("the ci.yml report left out",
         [tile_report(800)], True, "no ci.yml report was given"),
        ("a tile.yml run within its claim",
         [ci_report, tile_report(800)], False, None),
        ("a week with no tile.yml run (an --allow-empty report)",
         [ci_report, {"workflow": "tile.yml", "per_run": []}], False, None),
    ]
    for label, reports, want_red, says in source_cases:
        found, _notes = audit_observed(
            source_files, load_reports(reports, {"ci.yml": today}))
        if bool(found) != want_red or (
                says is not None and not any(says in f for f in found)):
            failures.append(
                f"per-workflow audit: {label}: expected"
                f" {'red with ' + repr(says) if want_red else 'green'},"
                f" got {found or 'green'}")
        else:
            print(f"  {'refused' if want_red else 'accepted'}: {label}")
    # 2026-10-10 (issue #274): tile.yml's shards keep their names when the
    # matrix is dealt another way, so a name does not say which deal a run
    # measured. The digest carries `--shard I/N`; an observation of the 7-way
    # shard must not be held against the 8-way claim, and the 8-way one must.
    tile_now = {"tile-golden-1": "shard-1-of-8"}
    tile_claim = """\
jobs:
  tile-golden-1:
    # budget: 3x 865s planning value
    timeout-minutes: 44
"""

    def tile_shaped(seconds, digest):
        return {"workflow": "tile.yml", "per_run": [
            {"id": 7, "jobs": {"tile-golden-1": seconds},
             "steps": {"tile-golden-1": digest}}]}

    tile_cases = [
        ("a 7-way tile-golden-1 run under the 8-way claim's name",
         tile_shaped(968, "shard-1-of-7"), False),
        ("an 8-way tile-golden-1 run over the 8-way claim",
         tile_shaped(900, "shard-1-of-8"), True),
        ("an 8-way tile-golden-1 run within the 8-way claim",
         tile_shaped(800, "shard-1-of-8"), False),
    ]
    for label, report, want_red in tile_cases:
        found, _notes = audit_observed(
            {"tile.yml": tile_claim},
            load_reports([ci_report, report],
                         {"ci.yml": today, "tile.yml": tile_now}))
        if bool(found) != want_red:
            failures.append(
                f"tile shard shape: {label}: expected"
                f" {'red' if want_red else 'green'}, got {found or 'green'}")
        else:
            print(f"  {'refused' if want_red else 'accepted'}: {label}")
    try:
        load_reports([ci_report, tile_report(800), tile_report(900)],
                     {"ci.yml": today})
        failures.append("two tile.yml reports were both accepted")
    except SystemExit:
        print("  refused: two reports of one workflow")

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
             + len(totals_mutants)
             + sum(1 for case in shaped_cases if case[4]) + 1
             + sum(1 for case in source_cases if case[2]) + 1)
    print(f"selftest: {count} mutant(s) refused, clean inputs accepted")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument(
        "--observed",
        type=Path,
        action="append",
        default=None,
        help="a scripts/gate-observations.py report, once per workflow (ci.yml"
        " and tile.yml); refuse every claim under the maximum its own"
        " workflow's report records (the nightly audit, not run on a push)",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    if args.selftest:
        return selftest(root)

    observations = None
    if args.observed:
        reports = [json.loads(path.read_text(encoding="utf-8"))
                   for path in args.observed]
        observations = load_reports(reports, current_digests())
        for report in reports:
            workflow = report.get("workflow") or DEFAULT_SOURCE
            keyed = ("by steps digest"
                     if workflow in KEYED_FILES.values() else "by name")
            print(
                f"observations: {workflow}: {len(report['jobs'])} job name(s)"
                f" over {observations[workflow].runs} run(s)"
                f" ({report.get('oldest_run_created', '?')}"
                f" .. {report.get('newest_run_created', '?')}),"
                f" held to claims {keyed}"
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
    budgeted = {}
    for name in workflows:
        path = workflow_path(root, name)
        checked += 1
        text = path.read_text(encoding="utf-8")
        budgeted[name] = text
        problems.extend(check_text(text, name))
        if pole is not None and name not in POLE_EXEMPT:
            problems.extend(check_claims_under_pole(text, name, pole))
    if observations is not None:
        found, said = audit_observed(budgeted, observations)
        problems.extend(found)
        notes.extend(said)

    if not checked:
        print("no workflow files found -- this check saw nothing", file=sys.stderr)
        return 1
    texts = workflow_texts(root)
    problems.extend(check_totals(texts))
    for note in notes:
        print(f"note: {note}")
    if observations is not None:
        for workflow, seen in sorted(observations.items()):
            if workflow != OBSERVED_FROM[RUN_POLE_FILE]:
                continue  # matched by name: no shape to have left anything out
            for line in seen.summary():
                print(f"note: {workflow}: {line}")
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
