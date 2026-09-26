#!/usr/bin/env python3
"""Collect how long each CI job actually took, so a budget can be audited.

`scripts/check-gate-budgets.py` holds every `timeout-minutes` to three times
the observation its `# budget:` line claims, and holds every claim under the
run pole. What it never did was ask whether the claim is still true. Both
halves of its arithmetic read the same file the claim lives in, so a job can
double in cost and stay green forever: the timeout is still 3x a number, the
number is just no longer the worst observation.

That is not hypothetical. On 2026-09-03 twenty-one of gates.yml's budget lines
were below the job's own worst run since 09-02, native-diff's by 562s, and no
gate said so. The observations were sitting in the Actions API the whole time.

This fetches them. For the last K completed runs of a workflow on a branch it
reads every job's start and finish, keeps the maximum per job name for a
person to read, and writes a JSON file that `check-gate-budgets.py
--observed` compares the declared values against, run by run and by steps
rather than by name (see WHICH JOB A RUN WAS below).

    scripts/gate-observations.py --out /tmp/observed.json
    scripts/check-gate-budgets.py --observed /tmp/observed.json
    scripts/gate-observations.py --restep /tmp/observed.json --out /tmp/o2.json

Neither runs in CI: this one needs the API (and a token), and a gate that
depends on the network is a gate that goes red for the network. It is the
manual audit to run before restating a budget line, and the report it writes
is what the restatement cites.

Two deliberate narrowings, both about what counts as an observation:

* only `conclusion == "success"` jobs. A job that failed, was cancelled or was
  killed by its own timeout stopped early; its duration is a fact about the
  failure, not about the work. (A timeout kill is the one loss that matters,
  and it is loud on its own -- the run is red.)
* duration is `completed_at - started_at`, so queueing is outside it, exactly
  as the pole's own note says the per-job claims are.

A reusable workflow's jobs are reported under `"<caller job> / <job>"`
(gates.yml's `native-diff` arrives as `test / native-diff`, because ci.yml
calls it from a job named `test`). The prefix is stripped so the names match
the keys in the workflow file; a bare name is kept as it is.

The report also keeps every run it read, under "per_run": its event, its
conclusion, each successful job's seconds and the run's span (creation to the
last job's finish, queueing included, unlike the per-job figure). The maximum
per job is what the budget audit needs; the per-run records are what
scripts/gate-totals.py adds up for the nightly report of job-seconds per push,
and keeping them here means that report reads the same API answers, through
the same reader, as the audit does. `--allow-empty` writes a report with no
runs instead of failing: a path-triggered workflow (tile.yml) can go a week
without a push that touches its paths, and that is an answer, not an error.

WHICH JOB A RUN WAS (issue #244). A job's name is not its identity. Until
2026-09-26 the audit held each budget line to the worst run of the job with
that name in the window, so a job split in place (syntax-mutants-1 going
from half the mutants to a third) inherited a week of the old shape's runs,
and round two of the budget ratchet had to rename every split job to get
out from under them. So every per-run record now also carries "steps":
{job: digest} for each job gates.yml defined at that run's own commit,
where the digest is scripts/gates-external/steps_lock.py's job_digests, the
multiset of the job's `run:` texts that steps.lock.json holds per family.
check-gate-budgets.py --observed compares a gates.yml budget line only with
runs whose digest equals the job's digest today, whatever the job was called
then: a reshard starts a fresh window by itself, and a rename that keeps the
steps keeps the history.

The file at a run's commit is read with git (`git rev-parse <sha>:<path>`,
then `git cat-file` once per distinct blob; 52 runs of 2026-09-19 ..
09-26 touched 26 distinct gates.yml blobs, parsed in 1.7s), so the checkout
this runs in needs the history (`fetch-depth: 0`). A commit git does not
have is read through the contents API instead, once per commit. A gates.yml
that gatesplan refuses leaves the run's "steps" null and says why under
"steps_error"; the audit counts those runs and compares nothing against them,
since a job whose shape is unknown cannot be said to be today's. Jobs that
gatesplan does not model (gates.yml's `plan`, and every job of another
workflow, such as ci.yml's `secrets`) carry no digest and are still matched
by name. The digests need PyYAML, as steps_lock.py does.
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone


def gh_json(args):
    """Run `gh` and parse its stdout as JSON, with the proxy vars cleared."""
    env = dict(os.environ)
    for key in (
        "https_proxy", "http_proxy", "all_proxy", "HTTPS_PROXY", "HTTP_PROXY"
    ):
        env.pop(key, None)
    proc = subprocess.run(
        args, capture_output=True, text=True, env=env, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"{' '.join(args)} failed ({proc.returncode}):\n{proc.stderr.strip()}"
        )
    return json.loads(proc.stdout)


def gh_text(args):
    """Run `gh` and return its stdout, with the proxy vars cleared."""
    env = dict(os.environ)
    for key in (
        "https_proxy", "http_proxy", "all_proxy", "HTTPS_PROXY", "HTTP_PROXY"
    ):
        env.pop(key, None)
    proc = subprocess.run(
        args, capture_output=True, text=True, env=env, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"{' '.join(args)} failed ({proc.returncode}):\n{proc.stderr.strip()}"
        )
    return proc.stdout


# Spelled from this file rather than as a join on the repository root, for
# the reason check-gate-budgets.py's current_digests gives.
HERE = pathlib.Path(__file__).resolve().parent
GATES_EXTERNAL = HERE / "gates-external"


class StepsAt:
    """{job: steps digest} of gates.yml at a commit, read once per content.

    Keyed by the (gates.yml, toolchain action) blob pair, because most
    commits in a week do not touch either and parsing is the only cost that
    grows with the window. `reads` counts what was done, for the report.
    """

    def __init__(self, repo, git_dir=HERE.parent):
        sys.path.insert(0, str(GATES_EXTERNAL))
        import gatesplan
        import steps_lock
        self.gatesplan = gatesplan
        self.steps_lock = steps_lock
        self.repo = repo
        self.git_dir = git_dir
        self.by_blobs = {}
        self.by_commit = {}
        self.reads = {"commits": 0, "parsed": 0, "api": 0, "refused": 0}

    def _git(self, *args):
        proc = subprocess.run(
            ["git", "-C", str(self.git_dir), *args],
            capture_output=True, text=True, check=False,
        )
        return proc.stdout if proc.returncode == 0 else None

    def _texts(self, sha):
        """-> (cache key, gates.yml text, action text) at sha."""
        paths = (self.gatesplan.GATES_PATH, self.gatesplan.TOOLCHAIN_PATH)
        blobs = [self._git("rev-parse", "--verify", "-q", f"{sha}:{path}")
                 for path in paths]
        if all(blobs):
            key = tuple(blob.strip() for blob in blobs)
            if key in self.by_blobs:
                return key, None, None
            texts = [self._git("cat-file", "blob", blob) for blob in key]
            if all(text is not None for text in texts):
                return key, texts[0], texts[1]
        self.reads["api"] += 1
        texts = [
            gh_text([
                "gh", "api", "-H", "Accept: application/vnd.github.raw",
                f"repos/{self.repo}/contents/{path}?ref={sha}",
            ])
            for path in paths
        ]
        return ("commit", sha), texts[0], texts[1]

    def at(self, sha):
        """-> ({job: digest}, None) or (None, why gatesplan refused it)."""
        if sha in self.by_commit:
            return self.by_commit[sha]
        self.reads["commits"] += 1
        key, gates, action = self._texts(sha)
        if key not in self.by_blobs:
            self.reads["parsed"] += 1
            try:
                self.by_blobs[key] = (
                    self.steps_lock.job_digests(gates, action), None)
            except self.gatesplan.PlanError as error:
                self.reads["refused"] += 1
                self.by_blobs[key] = (None, str(error))
        self.by_commit[sha] = self.by_blobs[key]
        return self.by_commit[sha]


def attach_steps(per_run, steps_at):
    """Give every per-run record its jobs' steps digests (or the refusal)."""
    for record in per_run:
        digests, error = steps_at.at(record["head_sha"])
        if digests is None:
            record["steps"] = None
            record["steps_error"] = error
        else:
            record["steps"] = {job: digests[job]
                               for job in record["jobs"] if job in digests}


def strip_caller(name):
    """`test / native-diff` -> `native-diff`; a bare name is unchanged."""
    return name.rsplit(" / ", 1)[-1].strip()


def parse_time(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def parse_since(text):
    """--since as an instant, or SystemExit naming what it could not read.

    This used to be compared with the API's createdAt as a string, which is
    only right when both are spelled the same way. `2026-9-23` sorts after
    every `2026-09-...` stamp and silently matched nothing (the failure then
    reads "no completed runs matched", as if the runs were missing), and an
    offset like `+08:00` was compared character by character with a `Z`
    stamp, so the window was off by the offset without a word. Now the value
    is parsed: a bare date means midnight UTC, a stamp without an offset is
    UTC, and anything else is refused.
    """
    try:
        when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(
            f"--since {text!r} is not an ISO 8601 date or timestamp "
            "(for example 2026-09-23 or 2026-09-23T00:00:00Z)"
        )
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when


def collect(repo, branch, workflow, runs, since, allow_empty=False):
    listed = gh_json([
        "gh", "run", "list",
        "--repo", repo,
        "--workflow", workflow,
        "--branch", branch,
        "--limit", str(max(runs * 2, runs)),
        "--json", "databaseId,status,conclusion,createdAt,headSha,event",
    ])
    picked = []
    for run in listed:
        if run["status"] != "completed":
            continue
        if since and parse_time(run["createdAt"]) < since:
            continue
        picked.append(run)
        if len(picked) >= runs:
            break
    if not picked and not allow_empty:
        raise SystemExit(
            f"no completed {workflow} runs on {branch} matched"
            f"{' since ' + since.isoformat() if since else ''}"
        )

    seconds = {}
    where = {}
    per_run = []
    for run in picked:
        payload = gh_json([
            "gh", "api",
            f"repos/{repo}/actions/runs/{run['databaseId']}/jobs?per_page=100",
        ])
        jobs = {}
        last = None
        for job in payload.get("jobs", []):
            if job.get("completed_at"):
                done = parse_time(job["completed_at"])
                last = done if last is None or done > last else last
            if job.get("conclusion") != "success":
                continue
            if not job.get("started_at") or not job.get("completed_at"):
                continue
            took = int(
                (parse_time(job["completed_at"]) - parse_time(job["started_at"]))
                .total_seconds()
            )
            name = strip_caller(job["name"])
            jobs[name] = took
            if took > seconds.get(name, -1):
                seconds[name] = took
                where[name] = run["databaseId"]
        per_run.append({
            "id": run["databaseId"],
            "created": run["createdAt"],
            "event": run.get("event"),
            "conclusion": run.get("conclusion"),
            "head_sha": run.get("headSha"),
            "span": (int((last - parse_time(run["createdAt"])).total_seconds())
                     if last else None),
            "jobs": dict(sorted(jobs.items())),
        })
    return picked, seconds, where, per_run


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default="dawnop/dawn-lang")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--workflow", default="ci.yml")
    ap.add_argument("--runs", type=int, default=25,
                    help="how many completed runs to read (newest first)")
    ap.add_argument("--since", default=None,
                    help="ignore runs created before this ISO timestamp")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--allow-empty", action="store_true",
                    help="write an empty report when no run matched, rather"
                    " than fail (for a path-triggered workflow)")
    ap.add_argument("--restep", type=pathlib.Path, default=None,
                    help="read no runs: take this earlier report, attach the"
                    " steps digests again from git and write it to --out")
    args = ap.parse_args()

    if args.restep is not None:
        report = json.loads(args.restep.read_text(encoding="utf-8"))
        steps_at = StepsAt(report.get("repo", args.repo))
        started = time.monotonic()
        attach_steps(report["per_run"], steps_at)
        report["steps_reads"] = {
            **steps_at.reads, "seconds": round(time.monotonic() - started, 2)}
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.out}: steps of {len(report['per_run'])} run(s),"
              f" {report['steps_reads']}")
        return 0

    since = parse_since(args.since) if args.since else None
    picked, seconds, where, per_run = collect(
        args.repo, args.branch, args.workflow, args.runs, since,
        args.allow_empty,
    )
    steps_at = StepsAt(args.repo)
    started = time.monotonic()
    attach_steps(per_run, steps_at)
    steps_seconds = time.monotonic() - started
    report = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": args.repo,
        "branch": args.branch,
        "workflow": args.workflow,
        "since": since.isoformat() if since else None,
        "runs": [run["databaseId"] for run in picked],
        "oldest_run_created": picked[-1]["createdAt"] if picked else None,
        "newest_run_created": picked[0]["createdAt"] if picked else None,
        "worst_run": where,
        "jobs": dict(sorted(seconds.items())),
        "steps_reads": {**steps_at.reads, "seconds": round(steps_seconds, 2)},
        "per_run": per_run,
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {args.out}: {len(seconds)} job(s) over {len(picked)} run(s)"
        f" ({report['oldest_run_created']} .. {report['newest_run_created']})"
    )
    for name, took in sorted(seconds.items(), key=lambda kv: -kv[1]):
        print(f"  {took:5d}s  {name}  (run {where[name]})")
    reads = steps_at.reads
    print(
        f"steps: {reads['commits']} commit(s), {reads['parsed']} distinct"
        f" gates.yml parsed, {reads['api']} read through the API,"
        f" {reads['refused']} refused by gatesplan, {steps_seconds:.2f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
