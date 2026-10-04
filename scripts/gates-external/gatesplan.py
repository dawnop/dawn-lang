#!/usr/bin/env python3
"""Derive the external gate run's command list from gates.yml at one commit.

Why this exists rather than a list: a maintainer running the gates outside
GitHub needs the SAME gate set CI would have run on that commit, and the only
definition of that set is .github/workflows/gates.yml at that commit. A copied
list drifts; this is the drift sweep-plan.py was written against for the
incremental family, and this parser covers every job instead of one family.
It reads the file out of git (`git show <sha>:...`), never the working tree,
so a run on sha X cannot be planned from a checkout that happens to be at Y.

Why it refuses so much: every construct it does not model is a construct whose
local meaning would be a guess. So the accepted shape is closed, and anything
outside it is an error before any job starts:

  * top-level keys: name, on, jobs
  * job keys: runs-on (ubuntu-latest), timeout-minutes, steps, needs, and
    an `if:` of exactly one of the shapes in JOB_CONDITIONS
  * step keys: name, id, run, uses, with, env, and an `if:` of the one shape
    `steps.<earlier id>.outputs.<key> == '<literal>'`
  * `${{ }}` expressions: `runner.temp`, `needs.<needed gate job>.result` and
    `steps.<earlier id>.outputs.<key>` in env values; `runner.temp` in
    `with.path`; `secrets.GITHUB_TOKEN` in the toolchain action's
    `github-token`; nothing else anywhere (and none inside `run:` text)

The pull-request tier (#168). gates.yml opens with a `plan` job that decides,
per pull request, which gate jobs the diff can reach; every gate job
`needs: [plan]` and runs when the plan says `all` or names it. The plan job
is not a gate: it gates nothing about the tree, it only thins a pull
request's run. An external run is by definition the whole set, so the plan
job is never executed here, it is recorded in the substitution table as
`plan -> external-all`, and each gate job's condition on the plan's outputs
is taken as satisfied. That is only sound while the condition is exactly the
wiring #168 wrote (`all == 'true'` or the job naming itself), so the
condition is matched against those shapes with the job's own id substituted,
and any other condition is refused. A job that names another job's id, or
adds a clause, is a different question and does not get the answer "all".
  * `uses:` references: exactly those in SUBSTITUTIONS, spelled with their
    version; a version bump is a new reference and is refused until someone
    reviews what the new version does

Each `uses:` step is replaced by an action the backend executes, named by a
replacement id. The id vocabulary is fixed here and copied into the bundle, so
a reader sees what each reference became.

The dawn-toolchain composite is substituted as a whole, which is only honest
while the composite is what the substitution assumes. Its action.yml is read
at the same commit and fingerprinted; a composite that grew a step, changed a
cache path or changed a default is refused rather than approximated.

Modes:
  gatesplan.py --sha SHA [--repo DIR]      print the plan as JSON
  gatesplan.py --self-test                  refusal cases and a line-scan
                                            cross-check of the parser
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# PyYAML is imported where a plan is parsed, not here: the prefix executor
# (prefix.py run-job) imports this module only for expand() and
# step_condition_holds(), and the prefix's interpreter carries no PyYAML.

GATES_PATH = ".github/workflows/gates.yml"
TOOLCHAIN_ACTION = "./.github/actions/dawn-toolchain"
TOOLCHAIN_PATH = ".github/actions/dawn-toolchain/action.yml"

# uses reference -> (replacement id, accepted `with:` keys).
# The replacement ids are the whole vocabulary the bundle may carry in
# substitutions[].replacement; bundle.py imports this table.
SUBSTITUTIONS = {
    "actions/checkout@v4": ("tree-worktree", {"fetch-depth"}),
    TOOLCHAIN_ACTION: ("dawn-toolchain-local", {"github-token", "build"}),
    "actions/cache@v4": ("noop", {"path", "key", "restore-keys"}),
    "actions/upload-artifact@v4": (
        "artifact-store-local", {"name", "path", "if-no-files-found", "retention-days"}),
    "actions/download-artifact@v4": ("artifact-fetch-local", {"pattern", "path"}),
    "actions/setup-node@v4": (
        "node-host", {"node-version", "cache", "cache-dependency-path"}),
    "actions/setup-java@v4": ("jdk21-host", {"distribution", "java-version"}),
}

# Adjustments the local backend makes that are not `uses:` substitutions but
# still change what a step sees. They go into the bundle's substitution table
# under these subjects so they are as visible as the `uses:` rows.
ADJUSTMENTS = {
    "adjust:runner-temp": "per-job-directory",
    "adjust:tmpdir": "per-job-directory",
    "adjust:literal-tmp-paths": "machine-wide-lock",
    "adjust:github-env-files": "per-step-files",
    # The ones below are made only inside a prefix (run.sh --prefix), and a
    # row appears only when the commit's gates.yml has something for them to
    # act on (ADJUSTMENT_WHEN): a commit whose wasi-sdk step does not read
    # WASI_SDK_TARBALL would carry a row describing nothing.
    "adjust:wasi-sdk-tarball": "input-pack-tarball",
    "adjust:npm-offline-cache": "input-pack-npm-cache",
}

# subject -> predicate over the planned jobs; subjects not named here are
# always in the table.
ADJUSTMENT_WHEN = {
    "adjust:wasi-sdk-tarball": lambda jobs: any(
        "WASI_SDK_TARBALL" in action["command"]
        for job in jobs for action in job["actions"] if action["kind"] == "run"),
    "adjust:npm-offline-cache": lambda jobs: any(
        action["kind"] == "use" and action["uses"] == "actions/setup-node@v4"
        for job in jobs for action in job["actions"]),
}

PLAN_JOB = "plan"
PLAN_REPLACEMENT = "external-all"

TOP_KEYS = {"name", True, "on", "jobs"}  # PyYAML reads the key `on` as True
JOB_KEYS = {"runs-on", "timeout-minutes", "steps", "needs", "if"}
STEP_KEYS = {"name", "id", "run", "uses", "with", "env", "if"}

# Job conditions, whitespace-normalised, with {job} standing for the job's
# own id. "legacy" is the pre-#168 mutant-shards-complete; the next two are
# #168's wiring. "plan-selected-not-cancelled" is the same fan-in guarded by
# `!cancelled()` instead of `always()`, so that a GitHub run cut short by
# cancel-in-progress skips it instead of reporting the cancelled shard's
# missing record as a failure. An external run is never cancelled part way
# (a dead controller resumes, it does not cancel), so there the two fan-in
# shapes mean the same thing. Older shapes stay admitted because a plan is
# derived from gates.yml at whatever commit is being gated. All four mean
# "run" in an external run: the first because the needed jobs always end,
# the others because the plan is `all` here.
_PLAN_SELECT = ("needs.plan.outputs.all == 'true' || "
                "contains(fromJSON(needs.plan.outputs.jobs), '{job}')")
JOB_CONDITIONS = {
    "legacy-always": "always()",
    "plan-selected": _PLAN_SELECT,
    "plan-selected-always": ("always() && needs.plan.result == 'success' && ("
                             + _PLAN_SELECT + ")"),
    "plan-selected-not-cancelled": ("!cancelled() && needs.plan.result == 'success' && ("
                                    + _PLAN_SELECT + ")"),
}
STEP_CONDITION = re.compile(
    r"^steps\.([A-Za-z_][\w-]*)\.outputs\.([A-Za-z_][\w-]*) == '([^']*)'$")
ENV_EXPR_NEEDS = re.compile(r"^needs\.([A-Za-z_][\w-]*)\.result$")
ENV_EXPR_STEPS = re.compile(r"^steps\.([A-Za-z_][\w-]*)\.outputs\.([A-Za-z_][\w-]*)$")
EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
RUNNER_TEMP_EXPR = re.compile(r"\$\{\{\s*runner\.temp\s*\}\}")


class PlanError(Exception):
    """The plan cannot be derived without guessing; nothing may run."""


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def read_at(repo, sha, path):
    """(text, blob sha) of one file at one commit."""
    try:
        blob = git(repo, "rev-parse", f"{sha}:{path}").strip()
        text = git(repo, "cat-file", "blob", blob)
    except subprocess.CalledProcessError as error:
        raise PlanError(f"{path} is not readable at {sha}: {error.stderr.strip()}")
    return text, blob


def resolve_sha(repo, sha):
    try:
        return git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}").strip()
    except subprocess.CalledProcessError:
        raise PlanError(f"not a commit: {sha}")


def _no_expr(where, value):
    if isinstance(value, str) and "${{" in value:
        raise PlanError(f"{where}: unsupported expression {value!r}")


def _check_expr(where, expr, needs, step_ids):
    """One `${{ }}` body in an env value: is it one this model can evaluate?"""
    if expr == "runner.temp":
        return
    match = ENV_EXPR_NEEDS.match(expr)
    if match:
        if match.group(1) == PLAN_JOB or match.group(1) not in needs:
            raise PlanError(f"{where}: `{expr}` does not name a needed gate job")
        return
    match = ENV_EXPR_STEPS.match(expr)
    if match:
        if match.group(1) not in step_ids:
            raise PlanError(f"{where}: `{expr}` does not name an earlier step id")
        return
    raise PlanError(f"{where}: unsupported expression `{expr}`")


def _env(where, env, needs=(), step_ids=()):
    """Step env with its expressions kept symbolic; `expand` evaluates them."""
    if env is None:
        return {}
    if not isinstance(env, dict):
        raise PlanError(f"{where}: env is not a mapping")
    out = {}
    for key, value in env.items():
        value = str(value)
        for expr in EXPR.findall(value):
            _check_expr(f"{where} env {key}", expr, needs, step_ids)
        out[str(key)] = value
    return out


def expand(value, runner_temp, needs_results, step_outputs):
    """Evaluate the expressions `_env` admitted, for a backend to use."""
    def one(match):
        expr = match.group(1)
        if expr == "runner.temp":
            return runner_temp
        m = ENV_EXPR_NEEDS.match(expr)
        if m:
            return needs_results[m.group(1)]
        m = ENV_EXPR_STEPS.match(expr)
        if m:
            return step_outputs.get(m.group(1), {}).get(m.group(2), "")
        raise PlanError(f"unplanned expression `{expr}`")
    return EXPR.sub(one, value)


def step_condition_holds(condition, step_outputs):
    """A step `if:` as gatesplan admitted it; None means no condition."""
    if condition is None:
        return True
    step_id, key, literal = STEP_CONDITION.match(condition).groups()
    return step_outputs.get(step_id, {}).get(key, "") == literal


def _normalise(condition):
    text = str(condition).strip()
    match = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", text, re.S)
    if match:
        text = match.group(1)
    return re.sub(r"\s+", " ", text).strip()


def job_condition_kind(job_id, condition, needs):
    """Which admitted shape a job `if:` is, or PlanError."""
    text = _normalise(condition)
    for kind, shape in JOB_CONDITIONS.items():
        if text != shape.replace("{job}", job_id):
            continue
        uses_plan = kind != "legacy-always"
        if uses_plan and PLAN_JOB not in needs:
            break
        if kind != "plan-selected" and not [n for n in needs if n != PLAN_JOB]:
            break  # a fan-in only means something with gate jobs to wait on
        if kind == "plan-selected" and needs != [PLAN_JOB]:
            break
        return kind
    raise PlanError(f"job {job_id}: unsupported job condition {condition!r}")


def check_toolchain_action(text):
    """Fingerprint the composite the dawn-toolchain substitution stands for.

    The substitution means: a local JDK 21 on JAVA_HOME and PATH, the seed
    cache restored from a shared cache, and `./bin/dawn --version` unless
    `build` is 'false'. It is only that while the composite is exactly the
    two setup-graalvm attempts, a retry note, the two caches and the build.
    """
    import yaml
    doc = yaml.safe_load(text)
    problems = []
    inputs = doc.get("inputs") or {}
    if set(inputs) != {"github-token", "java-version", "distribution", "build"}:
        problems.append(f"inputs are {sorted(inputs)}")
    defaults = {k: (v or {}).get("default") for k, v in inputs.items()}
    for key, want in (("java-version", "21"), ("distribution", "graalvm-community"),
                      ("build", "true")):
        if key in defaults and str(defaults[key]) != want:
            problems.append(f"input {key} defaults to {defaults[key]!r}, not {want!r}")
    runs = doc.get("runs") or {}
    if runs.get("using") != "composite":
        problems.append("not a composite action")
    uses = []
    run_steps = []
    for step in runs.get("steps") or []:
        if "uses" in step:
            uses.append(step["uses"])
            if step["uses"] == "actions/cache@v4":
                path = (step.get("with") or {}).get("path")
                if path not in (".dawn/seeds", "~/.cache/coursier"):
                    problems.append(f"a cache step now caches {path!r}")
        elif "run" in step:
            run_steps.append((str(step.get("if", "")).strip(), step["run"].strip()))
        else:
            problems.append(f"step {step.get('name')!r} is neither uses nor run")
    if sorted(uses) != sorted(["graalvm/setup-graalvm@v1"] * 2 + ["actions/cache@v4"] * 2):
        problems.append(f"uses references are {sorted(uses)}")
    build = [r for c, r in run_steps if r == "./bin/dawn --version"]
    notes = [r for c, r in run_steps
             if c == "steps.graalvm.outcome == 'failure'" and r.startswith('echo "::warning')]
    if len(build) != 1 or len(notes) != 1 or len(run_steps) != 2:
        problems.append(f"run steps are {[r.splitlines()[0] for _, r in run_steps]}")
    build_if = [c for c, r in run_steps if r == "./bin/dawn --version"]
    if build_if and build_if[0] != "inputs.build == 'true'":
        problems.append(f"the build step is guarded by {build_if[0]!r}")
    if problems:
        raise PlanError(
            "dawn-toolchain composite no longer matches its substitution: "
            + "; ".join(problems))


def parse(gates_text, action_text=None):
    """The plan: jobs in definition order, each with ordered actions.

    Each action is either
      {"kind": "run", "name", "command", "env"}
      {"kind": "use", "uses", "replacement", "with", "env"}
    """
    import yaml
    doc = yaml.safe_load(gates_text)
    if not isinstance(doc, dict):
        raise PlanError("gates.yml is not a mapping")
    extra = set(doc) - TOP_KEYS
    if extra:
        raise PlanError(f"unsupported top-level keys: {sorted(map(str, extra))}")
    jobs_doc = doc.get("jobs") or {}
    if not jobs_doc:
        raise PlanError("gates.yml has no jobs")
    jobs = []
    toolchain_seen = False
    has_plan = PLAN_JOB in jobs_doc
    if has_plan:
        plan_job = jobs_doc[PLAN_JOB]
        if not isinstance(plan_job, dict) or plan_job.get("needs") or "if" in plan_job:
            raise PlanError("job plan: the plan job must need nothing and be unconditional")
        outputs = plan_job.get("outputs") or {}
        if set(outputs) != {"all", "jobs"}:
            raise PlanError(f"job plan: outputs are {sorted(outputs)}, not all and jobs")
    for job_id, job in jobs_doc.items():
        where = f"job {job_id}"
        if job_id == PLAN_JOB:
            continue  # not a gate; substituted whole by `external-all`
        if not isinstance(job, dict):
            raise PlanError(f"{where} is not a mapping")
        extra = set(job) - JOB_KEYS
        if extra:
            raise PlanError(f"{where}: unsupported keys {sorted(extra)}")
        if job.get("runs-on") != "ubuntu-latest":
            raise PlanError(f"{where}: runs-on {job.get('runs-on')!r}")
        timeout = job.get("timeout-minutes")
        if not isinstance(timeout, int) or timeout <= 0:
            raise PlanError(f"{where}: timeout-minutes {timeout!r}")
        needs = job.get("needs") or []
        if isinstance(needs, str):
            needs = [needs]
        needs = list(needs)
        for need in needs:
            if need not in jobs_doc:
                raise PlanError(f"{where}: needs unknown job {need!r}")
        if has_plan and PLAN_JOB not in needs:
            raise PlanError(f"{where}: gates.yml has a plan job and this job does not need it")
        if "if" in job:
            job_condition_kind(job_id, job["if"], needs)
        elif PLAN_JOB in needs or len(needs) > 0:
            raise PlanError(f"{where}: `needs:` without an admitted condition")
        gate_needs = [n for n in needs if n != PLAN_JOB]
        actions = []
        step_ids = []
        for index, step in enumerate(job.get("steps") or []):
            swhere = f"{where} step {index + 1}"
            if not isinstance(step, dict):
                raise PlanError(f"{swhere} is not a mapping")
            extra = set(step) - STEP_KEYS
            if extra:
                raise PlanError(f"{swhere}: unsupported keys {sorted(extra)}")
            has_run, has_uses = "run" in step, "uses" in step
            if has_run == has_uses:
                raise PlanError(f"{swhere}: needs exactly one of run/uses")
            name = step.get("name")
            _no_expr(f"{swhere} name", name)
            env = _env(swhere, step.get("env"), gate_needs, step_ids)
            condition = None
            if "if" in step:
                condition = _normalise(step["if"])
                match = STEP_CONDITION.match(condition)
                if not match or match.group(1) not in step_ids:
                    raise PlanError(f"{swhere}: unsupported step condition {step['if']!r}")
            if "id" in step:
                step_id = str(step["id"])
                if not re.fullmatch(r"[A-Za-z_][\w-]*", step_id) or step_id in step_ids:
                    raise PlanError(f"{swhere}: bad or repeated step id {step_id!r}")
                step_ids.append(step_id)
            if has_run:
                if "with" in step:
                    raise PlanError(f"{swhere}: `with` on a run step")
                command = step["run"]
                if not isinstance(command, str) or not command.strip():
                    raise PlanError(f"{swhere}: empty run")
                _no_expr(f"{swhere} run", command)
                actions.append({"kind": "run", "name": name, "command": command, "env": env,
                                "id": step.get("id"), "if": condition})
                continue
            uses = step["uses"]
            if uses not in SUBSTITUTIONS:
                raise PlanError(
                    f"{swhere}: `uses: {uses}` has no substitution; add a reviewed "
                    f"row to SUBSTITUTIONS rather than skipping it")
            replacement, accepted = SUBSTITUTIONS[uses]
            with_ = step.get("with") or {}
            extra = set(with_) - accepted
            if extra:
                raise PlanError(f"{swhere}: {uses} with unsupported inputs {sorted(extra)}")
            clean = {}
            for key, value in with_.items():
                value = str(value)
                if uses == TOOLCHAIN_ACTION and key == "github-token":
                    if value.replace(" ", "") != "${{secrets.GITHUB_TOKEN}}":
                        raise PlanError(f"{swhere}: github-token is {value!r}")
                    continue  # never forwarded: the local backend has no token
                if key == "path":
                    _no_expr(f"{swhere} with.path", RUNNER_TEMP_EXPR.sub("", value))
                else:
                    _no_expr(f"{swhere} with.{key}", value)
                clean[key] = value
            if uses == TOOLCHAIN_ACTION:
                toolchain_seen = True
                if clean.get("build", "true") not in ("true", "false"):
                    raise PlanError(f"{swhere}: build is {clean['build']!r}")
            if uses == "actions/setup-java@v4":
                if clean.get("java-version") != "21":
                    raise PlanError(f"{swhere}: setup-java asks for {clean.get('java-version')!r}")
            actions.append({"kind": "use", "name": name, "uses": uses,
                            "replacement": replacement, "with": clean, "env": env,
                            "id": step.get("id"), "if": condition})
        if not actions:
            raise PlanError(f"{where}: no steps")
        jobs.append({"id": job_id, "timeout_minutes": timeout, "needs": gate_needs,
                     "actions": actions, "plan_substituted": PLAN_JOB in needs})
    if toolchain_seen:
        if action_text is None:
            raise PlanError("the toolchain composite was not read at this commit")
        check_toolchain_action(action_text)
    return jobs


def run_commands(jobs):
    """The (job, command) multiset of every run step, in gates.yml order."""
    return [(job["id"], action["command"])
            for job in jobs for action in job["actions"] if action["kind"] == "run"]


def substitution_rows(jobs):
    """Distinct (uses, replacement) rows in first-use order, then adjustments."""
    rows, seen = [], set()
    if any(job.get("plan_substituted") for job in jobs):
        rows.append({"subject": PLAN_JOB, "replacement": PLAN_REPLACEMENT})
    for job in jobs:
        for action in job["actions"]:
            if action["kind"] == "use" and action["uses"] not in seen:
                seen.add(action["uses"])
                rows.append({"subject": action["uses"], "replacement": action["replacement"]})
                if action["uses"] == TOOLCHAIN_ACTION:
                    # the composite's own caches are the other half of this row
                    seen.add("actions/cache@v4")
                    rows.append({"subject": "actions/cache@v4", "replacement": "noop"})
    for subject, replacement in ADJUSTMENTS.items():
        if subject in ADJUSTMENT_WHEN and not ADJUSTMENT_WHEN[subject](jobs):
            continue
        rows.append({"subject": subject, "replacement": replacement})
    return rows


def plan_at(repo, sha):
    """Everything the runner needs from one commit, read out of git."""
    tree = resolve_sha(repo, sha)
    gates_text, gates_blob = read_at(repo, tree, GATES_PATH)
    try:
        action_text, _ = read_at(repo, tree, TOOLCHAIN_PATH)
    except PlanError:
        action_text = None
    jobs = parse(gates_text, action_text)
    return {"tree": tree, "gates_blob": gates_blob, "gates_text": gates_text, "jobs": jobs}


# ------------------------------------------------------------------ self-test

RUN_KEY_LINE = re.compile(r"^\s*(?:-\s+)?run:", re.M)


JOB_HEADER = re.compile(r"^  ([-A-Za-z0-9_]+):\s*$")


def line_scan_count(text):
    """Independent count of gate `run:` keys, so the YAML walk cannot lose one.

    Lines are attributed to the last two-space-indented job header above them,
    and the plan job's lines are not counted, as the parser does not plan it.
    """
    count, job, in_jobs = 0, None, False
    for line in text.splitlines():
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        header = JOB_HEADER.match(line) if in_jobs else None
        if header:
            job = header.group(1)
            continue
        if line.lstrip().startswith("#") or not RUN_KEY_LINE.match(line):
            continue
        if job != PLAN_JOB:
            count += 1
    return count


def self_test(repo):
    failures = []
    ok_action = (Path(__file__).resolve().parents[2] / TOOLCHAIN_PATH).read_text()

    def job(steps, **extra):
        body = {"runs-on": "ubuntu-latest", "timeout-minutes": 5, "steps": steps}
        body.update(extra)
        return body

    def doc(jobs, **top):
        d = {"name": "gates", "on": {"workflow_call": None}, "jobs": jobs}
        d.update(top)
        import yaml
        return yaml.safe_dump(d, sort_keys=False)

    good = doc({"a": job([{"uses": "actions/checkout@v4"},
                          {"uses": TOOLCHAIN_ACTION,
                           "with": {"github-token": "${{ secrets.GITHUB_TOKEN }}"}},
                          {"name": "x", "run": "echo a",
                           "env": {"D": "${{ runner.temp }}/d"}}]),
                "b": job([{"run": "echo b"}], needs=["a"], **{"if": "${{ always() }}"})})
    try:
        plan = parse(good, ok_action)
        if run_commands(plan) != [("a", "echo a"), ("b", "echo b")]:
            failures.append(f"accepted plan has the wrong commands: {run_commands(plan)}")
    except PlanError as error:
        failures.append(f"refused a supported document: {error}")

    refused = {
        "unknown uses": doc({"a": job([{"uses": "actions/checkout@v5"}])}),
        "unknown third-party uses": doc({"a": job([{"uses": "someone/thing@v1"}])}),
        "step if other than a step output": doc({"a": job([{"run": "echo", "if": "success()"}])}),
        "step shell": doc({"a": job([{"run": "echo", "shell": "sh"}])}),
        "working-directory": doc({"a": job([{"run": "echo", "working-directory": "x"}])}),
        "continue-on-error": doc({"a": job([{"run": "echo", "continue-on-error": True}])}),
        "job strategy": doc({"a": job([{"run": "echo"}], strategy={"matrix": {"x": [1]}})}),
        "job services": doc({"a": job([{"run": "echo"}], services={})}),
        "job env": doc({"a": job([{"run": "echo"}], env={"A": "1"})}),
        "job condition other than always": doc({
            "a": job([{"run": "echo"}]),
            "b": job([{"run": "echo"}], needs=["a"], **{"if": "${{ success() }}"})}),
        "job condition without needs": doc({"a": job([{"run": "echo"}], **{"if": "always()"})}),
        "needs unknown job": doc({"a": job([{"run": "echo"}], needs=["zz"])}),
        "other runner": doc({"a": dict(job([{"run": "echo"}]), **{"runs-on": "windows-latest"})}),
        "expression in run": doc({"a": job([{"run": "echo ${{ github.sha }}"}])}),
        "other expression in env": doc({"a": job([{"run": "echo", "env": {"X": "${{ github.ref }}"}}])}),
        "unknown with input": doc({"a": job([{"uses": "actions/checkout@v4",
                                               "with": {"submodules": "true"}}])}),
        "setup-java other version": doc({"a": job([{"uses": "actions/setup-java@v4",
                                                     "with": {"java-version": "17"}}])}),
        "top-level env": doc({"a": job([{"run": "echo"}])}, env={"A": "1"}),
        "top-level defaults": doc({"a": job([{"run": "echo"}])}, defaults={"run": {"shell": "sh"}}),
        "run and uses": doc({"a": job([{"run": "echo", "uses": "actions/checkout@v4"}])}),
        "empty job": doc({"a": job([])}),
    }
    for label, text in refused.items():
        try:
            parse(text, ok_action)
        except PlanError:
            continue
        failures.append(f"accepted: {label}")

    # The #168 shape: a plan job, gate jobs selected by its outputs.
    plan_job = {"runs-on": "ubuntu-latest", "timeout-minutes": 3,
                "outputs": {"all": "${{ steps.plan.outputs.all }}",
                            "jobs": "${{ steps.plan.outputs.jobs }}"},
                "steps": [{"uses": "actions/checkout@v4"},
                          {"id": "plan", "run": "python3 scripts/gate-map/plan.py"}]}

    def selected(job_id):
        return ("${{ needs.plan.outputs.all == 'true' || "
                f"contains(fromJSON(needs.plan.outputs.jobs), '{job_id}') }}}}")

    def selected_always(job_id):
        return ("${{ always() && needs.plan.result == 'success' && "
                "(needs.plan.outputs.all == 'true' || "
                f"contains(fromJSON(needs.plan.outputs.jobs), '{job_id}')) }}}}")

    def selected_not_cancelled(job_id):
        return selected_always(job_id).replace("always()", "!cancelled()")

    tiered = doc({
        "plan": plan_job,
        "a": job([{"run": "echo a"}], needs=["plan"], **{"if": selected("a")}),
        "b": job([{"id": "fam", "run": "echo ran=true >> \"$GITHUB_OUTPUT\"",
                   "env": {"R": "${{ needs.a.result }}"}},
                  {"if": "${{ steps.fam.outputs.ran == 'true' }}", "run": "echo b",
                   "env": {"F": "${{ steps.fam.outputs.flags }}"}}],
                 needs=["plan", "a"], **{"if": selected_always("b")}),
    })
    try:
        plan = parse(tiered, ok_action)
        if [j["id"] for j in plan] != ["a", "b"]:
            failures.append(f"the plan job was not excluded: {[j['id'] for j in plan]}")
        if [j["needs"] for j in plan] != [[], ["a"]]:
            failures.append(f"plan was not dropped from needs: {[j['needs'] for j in plan]}")
        if substitution_rows(plan)[0] != {"subject": PLAN_JOB, "replacement": PLAN_REPLACEMENT}:
            failures.append("no plan -> external-all row")
    except PlanError as error:
        failures.append(f"refused the #168 shape: {error}")

    # The same fan-in guarded by !cancelled(), as mutant-shards-complete is.
    try:
        plan = parse(tiered.replace("always()", "!cancelled()"), ok_action)
        if [j["needs"] for j in plan] != [[], ["a"]]:
            failures.append(f"!cancelled() fan-in lost its needs: {[j['needs'] for j in plan]}")
    except PlanError as error:
        failures.append(f"refused the !cancelled() fan-in: {error}")

    # Conditional adjustment rows: present exactly when gates.yml gives them
    # something to act on.
    def subjects(text):
        return {row["subject"] for row in substitution_rows(parse(text, ok_action))}
    plain = subjects(doc({"a": job([{"run": "echo"}])}))
    hooked = subjects(doc({"a": job([{"run": 'cp "$WASI_SDK_TARBALL" x'},
                                     {"uses": "actions/setup-node@v4",
                                      "with": {"node-version": "lts/*"}}])}))
    for subject in ADJUSTMENT_WHEN:
        if subject in plain:
            failures.append(f"{subject} listed for a gates.yml with nothing for it to act on")
        if subject not in hooked:
            failures.append(f"{subject} missing where gates.yml has its hook")

    def tier_with(**jobs_over):
        base = {"plan": plan_job,
                "a": job([{"run": "echo a"}], needs=["plan"], **{"if": selected("a")})}
        base.update(jobs_over)
        return doc(base)

    refused.update({
        "a gate job naming another job's id": tier_with(
            a=job([{"run": "echo a"}], needs=["plan"], **{"if": selected("b")})),
        "a gate job condition with an extra clause": tier_with(
            a=job([{"run": "echo a"}], needs=["plan"],
                  **{"if": selected("a")[:-3] + " && github.event_name == 'push' }}"})),
        "a gate job condition on the plan's all only": tier_with(
            a=job([{"run": "echo a"}], needs=["plan"],
                  **{"if": "${{ needs.plan.outputs.all == 'true' }}"})),
        "a gate job that does not need plan": tier_with(a=job([{"run": "echo a"}])),
        "a plan-selected job that needs another gate job": tier_with(
            c=job([{"run": "echo c"}], needs=["plan", "a"], **{"if": selected("c")})),
        "always() without plan.result success": tier_with(
            c=job([{"run": "echo c"}], needs=["plan", "a"],
                  **{"if": selected_always("c").replace(
                      "needs.plan.result == 'success'", "needs.plan.result != 'x'")})),
        "!cancelled() without plan.result success": tier_with(
            c=job([{"run": "echo c"}], needs=["plan", "a"],
                  **{"if": selected_not_cancelled("c").replace(
                      "needs.plan.result == 'success'", "needs.plan.result != 'x'")})),
        "!cancelled() fan-in with no gate job to wait on": tier_with(
            c=job([{"run": "echo c"}], needs=["plan"],
                  **{"if": selected_not_cancelled("c")})),
        "a plan job with a needs": tier_with(plan=dict(plan_job, needs=["a"])),
        "a plan job with other outputs": tier_with(
            plan=dict(plan_job, outputs={"all": "x"})),
        "a step condition on something other than a step output": doc({
            "a": job([{"run": "echo", "if": "${{ github.event_name == 'push' }}"}])}),
        "a step condition on a later step id": doc({
            "a": job([{"run": "echo", "if": "${{ steps.x.outputs.y == 'z' }}"},
                      {"id": "x", "run": "echo"}])}),
        "env reading the plan's result": tier_with(
            c=job([{"run": "echo", "env": {"R": "${{ needs.plan.result }}"}}],
                  needs=["plan", "a"], **{"if": selected_always("c")})),
        "env reading a job not needed": tier_with(
            c=job([{"run": "echo", "env": {"R": "${{ needs.zz.result }}"}}],
                  needs=["plan", "a"], **{"if": selected_always("c")})),
    })
    for label in list(refused)[-14:]:
        try:
            parse(refused[label], ok_action)
        except PlanError:
            continue
        failures.append(f"accepted: {label}")

    drifted = ok_action.replace("path: .dawn/seeds", "path: .dawn")
    if drifted == ok_action:
        failures.append("the toolchain drift fixture did not change the action")
    else:
        try:
            parse(good, drifted)
            failures.append("accepted a drifted toolchain composite")
        except PlanError:
            pass

    head = resolve_sha(repo, "HEAD")
    live = plan_at(repo, head)
    parsed = len(run_commands(live["jobs"]))
    scanned = line_scan_count(live["gates_text"])
    if parsed != scanned:
        failures.append(f"HEAD gates.yml: parser found {parsed} run steps, line scan {scanned}")

    for line in failures:
        print(f"FAIL gatesplan self-test: {line}", file=sys.stderr)
    if failures:
        return 1
    print(f"OK: gatesplan self-test, {len(refused)} refusals, "
          f"{len(live['jobs'])} jobs and {parsed} run steps at {head[:12]}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sha")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test(args.repo)
    try:
        plan = plan_at(args.repo, args.sha)
    except PlanError as error:
        print(f"gatesplan: {error}", file=sys.stderr)
        return 2
    plan.pop("gates_text")
    json.dump(plan, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
