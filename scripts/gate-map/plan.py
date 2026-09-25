#!/usr/bin/env python3
"""Which gates.yml jobs a pull request has to run.

    scripts/gate-map/plan.py --event pull_request --base <sha>
    scripts/gate-map/plan.py --selftest
    scripts/gate-map/plan.py --check-wiring

## Why this exists

Every pull request used to run every gate: 39 jobs and about 23,600
job-seconds against an account ceiling of 20 concurrent runners, so one run
spans about 25 minutes and three pull requests queued together take about an
hour. #163 changed two paragraphs of documentation and ran all of it. The
question "which gate can see this diff" already has a tool that answers it
from the tree (gatemap.py, next to this file), so the pull-request tier asks
that tool and runs only the jobs holding a gate that can see the change.

That makes CI two tiers, and the second tier is what keeps the first one
honest. A push to main still runs every job: this script answers `all` for
any event that is not a pull request, and release.yml's `verified` guard
(scripts/gates-external/release_evidence.py) only accepts a successful
ci.yml run whose event is `push` and whose branch is main, refusing a pull
request run of the same sha by its event. So a pull request's subset is an
early answer, never the verdict a release stands on. Whatever
the subset misses is found on main, one push later, by the full run.

One answer is decided before this script runs. gates.yml's plan job first
asks scripts/gates-external/release_evidence.py --external-only whether the
head commit carries a verified `gates/maintainer` status, and when it does
it writes `all=false`, `jobs=[]` and never calls this: the whole gate set of
that exact commit already passed off GitHub. That is the evidence tier
(docs/gates-external-design.md). It is a shell step rather than a rule here
because it is not about the diff, and because every fallback below must
stay a way to run more, never less. `--check-wiring` holds the step in
place and `--selftest` runs it against a stub `gh`.

This imports gatemap rather than parsing its text output. The text is for a
person and its layout is free to change; the Map object is what the text is
printed from.

## When the answer is `all`

The subset is only as good as the map's premise, so every case where that
premise is not known to hold falls back to the whole gate set. None of these
may be dropped, and the self-test proves each one is load-bearing by removing
it and requiring some case to go red.

  event      The event is not `pull_request`. A push to main is the verdict
             release.yml reads, so it is never a subset.
  base       There is no base sha, or git cannot resolve it. Without a base
             there is no diff, and "no diff" must not read as "nothing to run".
  diff       git failed or timed out computing the diff. Same reason.
  empty      The diff is empty. A pull request with no changed path is either
             a merge-ref oddity or a base that already contains the head, and
             neither is a reason to skip every gate.
  forced     The diff touches a path whose effect gatemap cannot bound:
               selfhost/, std/, compiler-plan/, packages/, bin/
                   the compiler, its standard library, its planner and the
                   packages it bundles. Every gate runs a compiler built from
                   these (the dawn-toolchain action builds it), so the honest
                   answer is every gate even where gatemap names fewer.
               .github/
                   the workflows and the toolchain action define the gates
                   themselves. gatemap reads its gate list out of them, so a
                   diff here changes the map it is being asked about.
               scripts/gate-map/
                   this script, gatemap and its ratchet. A change to the
                   planner must not be judged by the planner it changes.
               scripts/seed-*, scripts/build-release-jar.sh,
               scripts/selfhost-*.sh
                   the seed pins, the release recipe and the bootstrap and
                   differential drivers. They decide which compiler every
                   other gate runs and what it is compared against.
  gatemap    Importing gatemap or building its map raised, reported a
             problem of its own, or took longer than MAP_TIMEOUT seconds. A
             map that could not be built says nothing about who can see what.
  unseen     A changed path is one gatemap records as watched by no gate at
             exact or coarse strength (the paths in unseen.txt). A subset
             computed from "nobody watches this" is the empty set, which is
             the failure gatemap exists to prevent, one level up.
             The one exception is a path of kind `unread`: a file in a harness
             directory under scripts/ that gatemap has read every script run
             from that directory for, and found none that imports, sources or
             names it (a README, a benchmark CI does not run). There the empty
             set is the measured answer rather than a gap, so it contributes
             no job and does not force the whole set.
  deleted    A changed path is not in the head tree (a deletion, or the old
             side of a rename). gatemap's map is built from the head tree, so
             it has no record of who read a file that is gone; only the base
             tree's map could say, and building a second map would double
             this job. Deletions are rare enough to take the whole set.

`deleted` is not in the task that commissioned this script; it is here
because without it a deleted file would contribute no job at all, which reads
as "nobody could see it" when the truth is "nobody asked".

## What a selected job means

A job is selected when one of its steps is an `exact`, `coupled` or `coarse`
observer of some changed path. `blind` is not an observer by definition.
Observers from other workflows (tile.yml, editor-grammar.yml, ci.yml) select
nothing here: those workflows have their own `paths:` triggers or run on
every event anyway. A job whose `needs:` names a selected job is selected too
(mutant-shards-complete reassembles the shards it needs), so the selection is
closed over the needs graph.

The residual risk, stated rather than hidden: gatemap's `coarse` is a claim
that a gate reads a path, derived from what the gate's scripts name. A gate
that reads a path through something gatemap cannot see (a compiled program
opening a file by a computed name) is missing from that path's observers. If
another gate does see the path, the path is not unseen and the subset skips
the invisible reader. main's full run is what catches that, one push late.

## The wiring check

`--check-wiring` holds gates.yml to the shape this plan depends on: a `plan`
job first, exposing `all` and `jobs`; every other job `needs: plan` and has
an `if:` that runs it when `all` is true or its own id is in `jobs`. A job
that forgot either half would silently run on every pull request (no needs)
or never (an `if` naming another job), and neither shows up as a red.
The same goes for the evidence tier's pieces: ci.yml passing `head` and the
two token scopes, the plan job's evidence step before its planning step,
and the planning step reading the evidence step's answer. Losing any of them
reddens nothing on its own; the tier just stops happening.
"""

import argparse
import fnmatch
import json
import re
import signal
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

GATES = ".github/workflows/gates.yml"
CI = ".github/workflows/ci.yml"
GATES_NAME = "gates.yml"
PLAN_JOB = "plan"

# Measured 7.5s locally for the whole map on 2026-09-23; a runner is about
# twice that. Past this the plan says `all` rather than hold every gate back.
MAP_TIMEOUT = 40.0
GIT_TIMEOUT = 30

OBSERVING_LEVELS = ("exact", "coupled", "coarse")

# (pattern, why). A pattern ending in "/" is a directory prefix; anything else
# is an fnmatch glob over the whole path. The reasons are the header's.
FORCED = (
    ("selfhost/", "the compiler every gate runs"),
    ("std/", "the standard library every compiled program links"),
    ("compiler-plan/", "the compiler's source and package planner"),
    ("packages/", "packages the compiler and its gates build"),
    ("bin/", "the launcher every gate starts the compiler through"),
    (".github/", "the workflows and actions that define the gates"),
    ("scripts/gate-map/", "the planner and the map it reads"),
    ("scripts/seed-*", "the seed pins"),
    ("scripts/build-release-jar.sh", "the release recipe"),
    ("scripts/selfhost-*.sh", "the bootstrap and differential drivers"),
)

RULES = ("event", "base", "diff", "empty", "forced", "gatemap", "unseen", "deleted")


class MapTimeout(Exception):
    pass


def forced_reason(path):
    for pattern, why in FORCED:
        if pattern.endswith("/"):
            if path.startswith(pattern):
                return f"{path} is under {pattern} ({why})"
        elif fnmatch.fnmatchcase(path, pattern):
            return f"{path} matches {pattern} ({why})"
    return None


# ---- gates.yml structure ----------------------------------------------

JOB_RE = re.compile(r"^  ([A-Za-z][\w-]*):\s*$")
KEY_RE = re.compile(r"^    ([A-Za-z][\w-]*):\s*(.*?)\s*$")
LIST_ITEM_RE = re.compile(r"^      - ([A-Za-z][\w-]*)\s*$")
OUTPUT_KEY_RE = re.compile(r"^      ([A-Za-z][\w-]*):")


def parse_jobs(text):
    """-> [(job id, {"needs": [...], "if": str|None, "outputs": [...]})].

    A scanner over the subset of YAML gates.yml uses, for the reason
    check-gate-budgets.py gives: this runs before any toolchain, and PyYAML is
    not something a bare runner is promised to have.
    """
    jobs = []
    in_jobs = False
    current = None
    key = None
    lines = text.splitlines()
    for line in lines:
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line and not line.startswith(" ") and not line.startswith("#"):
            in_jobs = False
            continue
        m = JOB_RE.match(line)
        if m:
            current = {"needs": [], "if": None, "outputs": []}
            jobs.append((m.group(1), current))
            key = None
            continue
        if current is None:
            continue
        m = KEY_RE.match(line)
        if m:
            key, value = m.group(1), m.group(2)
            if key == "needs" and value:
                if value.startswith("["):
                    current["needs"] = [
                        v.strip() for v in value.strip("[]").split(",") if v.strip()
                    ]
                else:
                    current["needs"] = [value]
            elif key == "if":
                current["if"] = value
            continue
        if line.startswith("    ") and not line.startswith("     ") and line.strip():
            key = None
            continue
        if key == "needs":
            m = LIST_ITEM_RE.match(line)
            if m:
                current["needs"].append(m.group(1))
        elif key == "if" and line.strip() and current["if"] is not None:
            current["if"] = (current["if"] + " " + line.strip()).strip()
        elif key == "outputs":
            m = OUTPUT_KEY_RE.match(line)
            if m:
                current["outputs"].append(m.group(1))
    return jobs


def needs_closure(selected, jobs):
    """Add every job whose needs (plan aside) name a selected job."""
    selected = set(selected)
    changed = True
    while changed:
        changed = False
        for job, info in jobs:
            if job in selected or job == PLAN_JOB:
                continue
            if any(n in selected for n in info["needs"] if n != PLAN_JOB):
                selected.add(job)
                changed = True
    return selected


def wiring_problems(gates_text, ci_text):
    """Everything about the two workflow files this plan depends on."""
    problems = []
    jobs = parse_jobs(gates_text)
    if not jobs:
        return [f"{GATES}: no jobs found"]
    first, plan = jobs[0]
    if first != PLAN_JOB:
        problems.append(
            f"{GATES}: the first job is `{first}`, not `{PLAN_JOB}`; the plan "
            "is defined first so that it is dispatched first"
        )
    by_id = dict(jobs)
    plan = by_id.get(PLAN_JOB)
    if plan is None:
        return problems + [f"{GATES}: no `{PLAN_JOB}` job"]
    if plan["needs"]:
        problems.append(f"{GATES} ({PLAN_JOB}): the plan needs nothing, it has "
                        f"`needs: {plan['needs']}`")
    for out in ("all", "jobs"):
        if out not in plan["outputs"]:
            problems.append(f"{GATES} ({PLAN_JOB}): no `{out}` output")
    for job, info in jobs:
        if job == PLAN_JOB:
            continue
        if PLAN_JOB not in info["needs"]:
            problems.append(
                f"{GATES} ({job}): does not `needs: {PLAN_JOB}`, so it runs "
                "on every pull request whatever the plan says"
            )
        cond = info["if"] or ""
        if "needs.plan.outputs.all == 'true'" not in cond:
            problems.append(
                f"{GATES} ({job}): its `if:` does not run it when "
                "needs.plan.outputs.all == 'true'"
            )
        own = f"contains(fromJSON(needs.plan.outputs.jobs), '{job}')"
        if own not in cond:
            problems.append(
                f"{GATES} ({job}): its `if:` does not test its own id, "
                f"`{own}`"
            )
    for needle in (
        "event: ${{ github.event_name }}",
        "base: ${{ github.event.pull_request.base.sha }}",
        HEAD_INPUT,
    ):
        if needle not in ci_text:
            problems.append(f"{CI}: does not pass `{needle}` to {GATES_NAME}")
    for needle in ("inputs:", "event:", "base:", "head:"):
        head = gates_text.split("\njobs:", 1)[0]
        if not re.search(r"^\s+" + re.escape(needle), head, re.M):
            problems.append(f"{GATES}: workflow_call declares no `{needle}`")
    problems += evidence_problems(gates_text, ci_text)
    return problems


# The evidence tier (docs/gates-external-design.md): the plan job reads the
# head commit's gates/maintainer status before it plans. Each needle is one
# piece a deletion would silently lose: the read itself, the step that turns
# an acceptance into the empty plan, the token scopes the read needs in
# both files, and the head sha it reads about. Losing any of them does not
# redden a run: the tier just stops happening, or (without the scopes) the
# read fails and counts as no evidence. That is why it is held here.
HEAD_INPUT = "head: ${{ github.event.pull_request.head.sha || github.sha }}"
EVIDENCE_NEEDLES = (
    ("the evidence read", "release_evidence.py --external-only"),
    ("the evidence step's output", 'echo "accepted=true" >> "$GITHUB_OUTPUT"'),
    ("the plan reading it", "ACCEPTED: ${{ steps.evidence.outputs.accepted }}"),
    ("the empty plan on acceptance", 'if [ "$ACCEPTED" = true ]; then'),
    ("the head sha", "HEAD_SHA: ${{ inputs.head }}"),
    ("statuses: read", "statuses: read"),
    ("actions: read", "actions: read"),
)


def job_block(text, job):
    """The lines of one job in a workflow file, or "" when absent."""
    m = re.search(r"^  " + re.escape(job) + r":\s*$", text, re.M)
    if not m:
        return ""
    nxt = re.search(r"^  [A-Za-z][\w-]*:\s*$", text[m.end():], re.M)
    return text[m.start(): m.end() + nxt.start()] if nxt else text[m.start():]


def evidence_problems(gates_text, ci_text):
    problems = []
    block = job_block(gates_text.split("\njobs:", 1)[-1], PLAN_JOB)
    for what, needle in EVIDENCE_NEEDLES:
        if needle not in block:
            problems.append(f"{GATES} ({PLAN_JOB}): lost {what}, `{needle}`")
    if block and block.find("id: evidence") > block.find("id: plan"):
        problems.append(f"{GATES} ({PLAN_JOB}): the evidence step does not come "
                        "before the planning step")
    caller = job_block(ci_text.split("\njobs:", 1)[-1], "test")
    for scope in ("statuses: read", "actions: read"):
        if scope not in caller:
            problems.append(f"{CI} (test): does not grant `{scope}`, which the "
                            "plan's evidence read needs")
    return problems


# ---- the plan ------------------------------------------------------------

def git(args, timeout=GIT_TIMEOUT):
    return subprocess.run(
        ["git", "-C", str(ROOT)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def changed_paths(base, head):
    """-> (paths, error). Both sides of a rename, as gatemap's --changed."""
    try:
        ok = git(["cat-file", "-e", f"{base}^{{commit}}"])
        if ok.returncode != 0:
            return None, f"base {base} is not a commit here: {ok.stderr.strip()}"
        proc = git(["diff", "--no-renames", "--name-only", base, head])
    except subprocess.TimeoutExpired:
        return None, "git diff timed out"
    if proc.returncode != 0:
        return None, f"git diff failed: {proc.stderr.strip()}"
    return [p for p in proc.stdout.split("\n") if p], None


class MapView:
    """What the plan needs from gatemap, built under a timeout."""

    def __init__(self, gm, base_std_modules, gate_jobs, unread_exempt=True):
        self.gm = gm
        self.base_std_modules = base_std_modules
        self.gate_jobs = gate_jobs
        # gatemap's `unread` kind, spelled the same way as its check
        self.unread = {
            p for p in gm.unseen()
            if p in gm.unread and not gm.by_path.get(p)
        }
        self.unseen = set(gm.unseen()) - (self.unread if unread_exempt else set())
        self.files = gm.tree.fileset
        self.workflow_of = {}
        for gate in gm.gates:
            self.workflow_of.setdefault(gate.id, set()).add(gate.workflow)

    def jobs_for(self, path):
        jobs = set()
        for o in self.gm.verdict(path, self.base_std_modules):
            if o.level not in OBSERVING_LEVELS:
                continue
            if GATES_NAME not in self.workflow_of.get(o.gate_id, ()):
                continue
            job = o.gate_id.split(" / ", 1)[0]
            if job in self.gate_jobs:
                jobs.add(job)
        return jobs


def build_view(base):
    sys.path.insert(0, str(HERE))
    import gatemap

    gm = gatemap.Map(gatemap.Tree(gatemap.ROOT))
    if gm.problems:
        raise RuntimeError("gatemap reports: " + "; ".join(gm.problems[:3]))
    base_std = gatemap.std_modules_at_revision(base) if base else None
    gate_jobs = [j for j, _ in parse_jobs(read(GATES)) if j != PLAN_JOB]
    return MapView(gm, base_std, gate_jobs)


def load_map(base, timeout=MAP_TIMEOUT, build=build_view):
    """Build the gate map of the checked-out tree under a timer, or raise."""

    def expire(signum, frame):
        raise MapTimeout(f"the gate map took longer than {timeout}s")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        return build(base)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def decide(event, base, paths, error, get_map, jobs, skip=()):
    """-> (all, sorted job ids, reason). Pure over its arguments.

    `get_map` is called only once every cheaper fallback has passed, so a
    push never imports gatemap. `skip` names fallback rules to leave out; only
    the self-test's mutants pass it.
    """
    everything = sorted(j for j, _ in jobs if j != PLAN_JOB)

    def full(rule, why):
        return True, everything, f"{rule}: {why}"

    if "event" not in skip and event != "pull_request":
        return full("event", f"event is {event or '(none)'}, not pull_request")
    if "base" not in skip and not base:
        return full("base", "no base sha")
    if "diff" not in skip and paths is None:
        return full("diff", error or "no diff")
    paths = paths or []
    if "empty" not in skip and not paths:
        return full("empty", "the diff is empty")
    if "forced" not in skip:
        for path in paths:
            why = forced_reason(path)
            if why:
                return full("forced", why)
    try:
        view = get_map()
    except Exception as e:  # noqa: BLE001 -- any failure means no map
        if "gatemap" not in skip:
            return full("gatemap", f"{type(e).__name__}: {e}")
        view = None
    selected = set()
    for path in paths:
        if view is None:
            continue
        if "deleted" not in skip and path not in view.files:
            return full("deleted", f"{path} is not in the head tree")
        if "unseen" not in skip and path in view.unseen:
            return full("unseen", f"{path} is watched by no gate (unseen.txt)")
        selected |= view.jobs_for(path)
    selected = needs_closure(selected, jobs)
    return False, sorted(selected), f"subset: {len(selected)} of {len(everything)} job(s)"


def plan(event, base, head="HEAD"):
    jobs = parse_jobs(read(GATES))
    paths, error = (None, None)
    if event == "pull_request" and base:
        paths, error = changed_paths(base, head)
    return decide(event, base, paths, error, lambda: load_map(base), jobs)


# ---- self-test -------------------------------------------------------------

def selftest():
    """Every fallback rule, and every rule shown to be load-bearing.

    The cases run against the real tree's map. Then each rule is removed in
    turn and the cases are run again: a rule whose removal reddens no case is
    a rule nothing tests, and is refused. That is the same argument gatemap's
    mutant matrix makes, at the size this file needs.
    """
    jobs = parse_jobs(read(GATES))
    everything = sorted(j for j, _ in jobs if j != PLAN_JOB)
    cache = {}

    def real_map():
        if "view" not in cache:
            cache["view"] = load_map("HEAD")
        return cache["view"]

    view = real_map()
    unseen = sorted(p for p in view.unseen if not forced_reason(p))
    if not unseen:
        print("SELFTEST FAIL: unseen.txt has no path outside the forced "
              "prefixes, so the unseen rule cannot be exercised", file=sys.stderr)
        return 1
    unread = sorted(p for p in view.unread if not forced_reason(p))
    if not unread:
        print("SELFTEST FAIL: gatemap records no `unread` path outside the "
              "forced prefixes, so the unread exemption cannot be exercised",
              file=sys.stderr)
        return 1
    docs = ["docs/incremental-semantics-design.md", "docs/session-body-replay-design.md"]
    for d in docs:
        if d not in view.files:
            print(f"SELFTEST FAIL: {d} is gone; repoint the docs case", file=sys.stderr)
            return 1

    def boom():
        raise RuntimeError("gatemap import failed (simulated)")

    def slow():
        # load_map's own timer, with a budget the build cannot meet
        import time
        return load_map("HEAD", timeout=0.05, build=lambda base: time.sleep(2))

    PR = "pull_request"
    ALL = {"all": True, "jobs": everything}
    cases = [
        # (name, event, base, paths, error, get_map, expected, rule)
        ("docs-only diff", PR, "b", docs, None, real_map,
         {"all": False, "jobs": ["docs"]}, "subset"),
        ("a push", "push", "b", docs, None, real_map, ALL, "event"),
        ("no base sha", PR, "", docs, None, real_map, ALL, "base"),
        ("git diff failed", PR, "b", None, "git diff failed (simulated)",
         real_map, ALL, "diff"),
        ("empty diff", PR, "b", [], None, real_map, ALL, "empty"),
        ("selfhost/src", PR, "b", docs + ["selfhost/src/main.dawn"], None,
         real_map, ALL, "forced"),
        (".github", PR, "b", [".github/workflows/gates.yml"], None,
         real_map, ALL, "forced"),
        ("scripts/selfhost-*.sh", PR, "b", ["scripts/selfhost-prev-diff.sh"],
         None, real_map, ALL, "forced"),
        ("gatemap raised", PR, "b", docs, None, boom, ALL, "gatemap"),
        ("gatemap timed out", PR, "b", docs, None, slow, ALL, "gatemap"),
        (f"unseen path {unseen[0]}", PR, "b", docs + [unseen[0]], None,
         real_map, ALL, "unseen"),
        (f"unread path {unread[0]}", PR, "b", docs + [unread[0]], None,
         real_map, {"all": False, "jobs": ["docs"]}, "subset"),
        ("deleted path", PR, "b", docs + ["docs/removed-by-the-selftest.md"],
         None, real_map, ALL, "deleted"),
    ]

    def run_cases(skip, verbose):
        red = []
        for name, event, base, paths, error, get_map, expected, rule in cases:
            is_all, got, reason = decide(event, base, paths, error, get_map,
                                         jobs, skip)
            ok = ({"all": is_all, "jobs": got} == expected
                  and reason.split(":", 1)[0] == rule)
            if not ok:
                red.append(f"{name}: expected {rule} {json.dumps(expected)[:80]}, "
                           f"got {reason!r} {json.dumps({'all': is_all, 'jobs': got})[:80]}")
            elif verbose:
                print(f"  PASS  {name} -> {reason}")
        return red

    failures = run_cases((), True)
    for f in failures:
        print(f"SELFTEST FAIL: {f}", file=sys.stderr)

    for rule in RULES:
        if not run_cases((rule,), False):
            failures.append(rule)
            print(f"SELFTEST FAIL: removing the `{rule}` fallback reddens no "
                  "case, so nothing tests it", file=sys.stderr)
        else:
            print(f"  refused: the plan without its `{rule}` fallback")

    # The unread exemption is load-bearing too: a view that treats unread
    # paths as unseen must redden the unread case, and only that case.
    strict = MapView(view.gm, view.base_std_modules, view.gate_jobs,
                     unread_exempt=False)
    saved = [c for c in cases]
    cases[:] = [c[:5] + ((lambda: strict),) + c[6:] if c[5] is real_map else c
                for c in cases]
    reds = run_cases((), False)
    cases[:] = saved
    if [r.split(":", 1)[0] for r in reds] != [f"unread path {unread[0]}"]:
        failures.append("unread-exemption")
        print("SELFTEST FAIL: without the unread exemption the red cases are "
              f"{reds!r}, not exactly the unread case", file=sys.stderr)
    else:
        print("  refused: the plan without its unread exemption")

    # The needs closure, on a graph small enough to read.
    graph = [("plan", {"needs": [], "if": None, "outputs": []}),
             ("a", {"needs": ["plan"], "if": None, "outputs": []}),
             ("b", {"needs": ["plan"], "if": None, "outputs": []}),
             ("agg", {"needs": ["plan", "a", "b"], "if": None, "outputs": []})]
    if needs_closure({"a"}, graph) != {"a", "agg"}:
        failures.append("closure")
        print("SELFTEST FAIL: a selected job does not select the job that "
              "needs it", file=sys.stderr)
    elif needs_closure(set(), graph) != set():
        failures.append("closure-empty")
        print("SELFTEST FAIL: the closure selects a job nothing asked for",
              file=sys.stderr)
    else:
        print("  PASS  the needs closure selects the aggregator of a selected shard")

    failures += wiring_selftest()
    failures += evidence_step_selftest()
    if failures:
        return 1
    print(f"selftest: {len(cases)} case(s), {len(RULES)} fallback(s) each "
          "shown load-bearing, wiring check refuses its mutants")
    return 0


def wiring_selftest():
    gates_text, ci_text = read(GATES), read(CI)
    failures = []
    clean = wiring_problems(gates_text, ci_text)
    if clean:
        for p in clean:
            print(f"SELFTEST FAIL: the real workflows are refused: {p}", file=sys.stderr)
        return ["wiring-clean"]
    jobs = parse_jobs(gates_text)
    victim = jobs[1][0]
    other = jobs[2][0]
    victim_at = gates_text.index(f"\n  {victim}:\n")
    tail = gates_text[victim_at:]
    need = "    needs: [plan]\n"
    own = f"contains(fromJSON(needs.plan.outputs.jobs), '{victim}')"
    mutants = [
        (f"`{victim}` without `needs: [plan]`",
         gates_text[:victim_at] + tail.replace(need, "", 1), ci_text),
        (f"`{victim}`'s `if:` testing `{other}`",
         gates_text[:victim_at] + tail.replace(own, own.replace(victim, other), 1),
         ci_text),
        ("ci.yml not passing the event",
         gates_text, ci_text.replace("event: ${{ github.event_name }}", "")),
        ("the plan job moved below a gate",
         gates_text.replace("\n  plan:\n", "\n  plan-moved:\n", 1), ci_text),
        ("ci.yml not passing the head sha",
         gates_text, ci_text.replace(HEAD_INPUT, "")),
        ("the plan job without its evidence step",
         drop_evidence_step(gates_text), ci_text),
        ("the plan job without `statuses: read`",
         gates_text.replace("      statuses: read", "      statuses: none", 1), ci_text),
        ("ci.yml's test job without `actions: read`",
         gates_text, ci_text.replace("      actions: read\n", "", 1)),
    ]
    for label, g, c in mutants:
        if g == gates_text and c == ci_text:
            print(f"SELFTEST FAIL: wiring mutant anchor drifted: {label}", file=sys.stderr)
            failures.append(label)
        elif not wiring_problems(g, c):
            print(f"SELFTEST FAIL: wiring mutant not refused: {label}", file=sys.stderr)
            failures.append(label)
        else:
            print(f"  refused: {label}")
    return failures


def plan_step_scripts(gates_text):
    """-> {step id: its `run: |` block, dedented} for the plan job's steps."""
    block = job_block(gates_text.split("\njobs:", 1)[-1], PLAN_JOB)
    scripts = {}
    for m in re.finditer(r"^      - name: .*\n((?:        .*\n|\s*\n)*)", block, re.M):
        body = m.group(1)
        sid = re.search(r"^        id: (\S+)", body, re.M)
        run = re.search(r"^        run: \|\n((?:          .*\n|\s*\n)*)", body, re.M)
        if sid and run:
            scripts[sid.group(1)] = "".join(
                line[10:] + "\n" for line in run.group(1).splitlines())
    return scripts


# A stand-in for `gh api --paginate PATH`: answers from a JSON table keyed by
# path prefix, or fails like an unreachable API when the table says "FAIL".
STUB_GH = """#!/usr/bin/env python3
import json, os, sys
table = json.load(open(os.environ["STUB_GH_TABLE"]))
args = sys.argv[1:]
path = args[-1] if args[:1] == ["api"] else None
for prefix, answer in table.items():
    if path and path.startswith(prefix):
        if answer == "FAIL":
            sys.stderr.write("HTTP 502: stub outage\\n")
            sys.exit(1)
        print(json.dumps(answer))
        sys.exit(0)
sys.stderr.write("stub gh: unexpected call %r\\n" % (args,))
sys.exit(1)
"""


def evidence_step_selftest():
    """Run the plan job's own two shell steps against a stub `gh`.

    This is the plan job as GitHub runs it, less GitHub: the step text is
    read out of gates.yml, each step gets its own GITHUB_OUTPUT file, and the
    only thing replaced is `gh`. An accepted status must leave the plan
    step's output as exactly `all=false` and `jobs=[]`; every refusal must
    fall through to the planner (a push, so it answers `all` without a map)
    and say why in the log.
    """
    import os
    import shutil
    import tempfile

    failures = []
    scripts = plan_step_scripts(read(GATES))
    if set(scripts) != {"evidence", "plan"}:
        print(f"SELFTEST FAIL: the plan job's steps are {sorted(scripts)}, not "
              "evidence and plan", file=sys.stderr)
        return ["evidence-steps"]
    if not shutil.which("bash"):
        print("SELFTEST FAIL: no bash to run the plan job's steps", file=sys.stderr)
        return ["evidence-bash"]
    repo, sha = "o/r", "a" * 40
    status = {"context": "gates/maintainer", "state": "success", "id": 1,
              "created_at": "2026-09-24T10:00:30Z",
              "creator": {"login": "github-actions[bot]"},
              "target_url": f"https://github.com/{repo}/actions/runs/7"}
    run = {"repository": {"full_name": repo},
           "path": ".github/workflows/verify-external.yml",
           "event": "workflow_dispatch", "head_branch": "main",
           "status": "completed", "conclusion": "success",
           "run_started_at": "2026-09-24T10:00:00Z",
           "updated_at": "2026-09-24T10:01:00Z"}
    stats = f"repos/{repo}/commits/{sha}/statuses"
    runp = f"repos/{repo}/actions/runs/7"
    cases = [
        # (label, head, table, accepted, needle in the log)
        ("accepted", sha, {stats: [status], runp: run}, True, "accepted:"),
        ("a person's status", sha,
         {stats: [dict(status, creator={"login": "someone"})], runp: run},
         False, "refused: written by someone"),
        ("target_url at a ci.yml run", sha,
         {stats: [status], runp: dict(run, path=".github/workflows/ci.yml",
                                     event="pull_request")},
         False, "refused: run 7 is .github/workflows/ci.yml"),
        ("no status", sha, {stats: []}, False, "refused: no gates/maintainer status"),
        ("API outage", sha, {stats: "FAIL"}, False, "exit 2"),
        ("no head sha", "", {}, False, "no head sha passed"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        bindir = Path(tmp) / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(STUB_GH)
        (bindir / "gh").chmod(0o755)
        for number, (label, head, table, accepted, needle) in enumerate(cases):
            case_dir = Path(tmp) / f"case{number}"
            case_dir.mkdir()
            (case_dir / "table.json").write_text(json.dumps(table))
            env = dict(os.environ, PATH=f"{bindir}:{os.environ.get('PATH', '')}",
                       STUB_GH_TABLE=str(case_dir / "table.json"),
                       RUNNER_TEMP=str(case_dir), GITHUB_STEP_SUMMARY=str(case_dir / "summary"),
                       GH_TOKEN="stub", HEAD_SHA=head, REPO=repo, DEFAULT_BRANCH="main",
                       EVENT="push", BASE="")
            outs, log = {}, ""
            for sid in ("evidence", "plan"):
                out = case_dir / f"{sid}.out"
                out.write_text("")
                env["GITHUB_OUTPUT"] = str(out)
                if sid == "plan":
                    env["ACCEPTED"] = outs["evidence"].get("accepted", "")
                proc = subprocess.run(["bash", "-e", "-c", scripts[sid]], cwd=ROOT, env=env,
                                      capture_output=True, text=True, timeout=120)
                log += proc.stdout + proc.stderr
                if proc.returncode != 0:
                    failures.append(f"{label}: step {sid} exited {proc.returncode}")
                raw = out.read_text()
                outs[sid] = dict(ln.split("=", 1) for ln in raw.splitlines() if "=" in ln)
                outs[sid + "-raw"] = raw
            want = "all=false\njobs=[]\n" if accepted else None
            got = outs["plan-raw"]
            if accepted and got != want:
                failures.append(f"{label}: the plan wrote {got!r}, not {want!r}")
            elif not accepted and outs["plan"].get("all") != "true":
                failures.append(f"{label}: fell through but the plan wrote {got!r}")
            if (outs["evidence"].get("accepted") == "true") != accepted:
                failures.append(f"{label}: evidence step wrote {outs['evidence-raw']!r}")
            if needle not in log:
                failures.append(f"{label}: the log does not say {needle!r}: {log[-400:]!r}")
            if not [f for f in failures if f.startswith(label + ":")]:
                print(f"  PASS  plan job steps, stub gh, {label} -> "
                      + ("all=false jobs=[]" if accepted else "planner (all=true on a push)"))
    for f in failures:
        print(f"SELFTEST FAIL: evidence tier: {f}", file=sys.stderr)
    return failures


def drop_evidence_step(gates_text):
    """gates.yml with the plan job's evidence step cut out, as a mutant."""
    start = gates_text.find("      - name: accept verified external evidence")
    end = gates_text.find("      - name: plan which gate jobs this run needs")
    if start < 0 or end < start:
        return gates_text
    return gates_text[:start] + gates_text[end:]


def main(argv=None):
    ap = argparse.ArgumentParser(description="which gates.yml jobs a pull request runs")
    ap.add_argument("--event", default="", help="github.event_name")
    ap.add_argument("--base", default="", help="the pull request's base sha")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--github-output", metavar="FILE",
                    help="also append all=/jobs= to this file ($GITHUB_OUTPUT)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--check-wiring", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest or args.check_wiring:
        rc = 0
        if args.check_wiring:
            problems = wiring_problems(read(GATES), read(CI))
            for p in problems:
                print(f"FAIL: {p}", file=sys.stderr)
            if problems:
                rc = 1
            else:
                print(f"OK: every {GATES_NAME} job needs {PLAN_JOB} and tests its own id")
        if args.selftest and selftest():
            rc = 1
        return rc

    is_all, jobs, reason = plan(args.event, args.base, args.head)
    print(reason, file=sys.stderr)
    out = {"all": is_all, "jobs": jobs}
    print(json.dumps(out))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as f:
            f.write(f"all={'true' if is_all else 'false'}\n")
            f.write(f"jobs={json.dumps(jobs, separators=(',', ':'))}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
