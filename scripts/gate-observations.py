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
reads every job's start and finish, keeps the maximum per job name, and writes
a JSON file that `check-gate-budgets.py --observed` compares the declared
values against.

    scripts/gate-observations.py --out /tmp/observed.json
    scripts/check-gate-budgets.py --observed /tmp/observed.json

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
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
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


def strip_caller(name):
    """`test / native-diff` -> `native-diff`; a bare name is unchanged."""
    return name.rsplit(" / ", 1)[-1].strip()


def parse_time(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def collect(repo, branch, workflow, runs, since):
    listed = gh_json([
        "gh", "run", "list",
        "--repo", repo,
        "--workflow", workflow,
        "--branch", branch,
        "--limit", str(max(runs * 2, runs)),
        "--json", "databaseId,status,conclusion,createdAt,headSha",
    ])
    picked = []
    for run in listed:
        if run["status"] != "completed":
            continue
        if since and run["createdAt"] < since:
            continue
        picked.append(run)
        if len(picked) >= runs:
            break
    if not picked:
        raise SystemExit(
            f"no completed {workflow} runs on {branch} matched"
            f"{' since ' + since if since else ''}"
        )

    seconds = {}
    where = {}
    for run in picked:
        payload = gh_json([
            "gh", "api",
            f"repos/{repo}/actions/runs/{run['databaseId']}/jobs?per_page=100",
        ])
        for job in payload.get("jobs", []):
            if job.get("conclusion") != "success":
                continue
            if not job.get("started_at") or not job.get("completed_at"):
                continue
            took = int(
                (parse_time(job["completed_at"]) - parse_time(job["started_at"]))
                .total_seconds()
            )
            name = strip_caller(job["name"])
            if took > seconds.get(name, -1):
                seconds[name] = took
                where[name] = run["databaseId"]
    return picked, seconds, where


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
    args = ap.parse_args()

    picked, seconds, where = collect(
        args.repo, args.branch, args.workflow, args.runs, args.since
    )
    report = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": args.repo,
        "branch": args.branch,
        "workflow": args.workflow,
        "runs": [run["databaseId"] for run in picked],
        "oldest_run_created": picked[-1]["createdAt"],
        "newest_run_created": picked[0]["createdAt"],
        "worst_run": where,
        "jobs": dict(sorted(seconds.items())),
    }
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {args.out}: {len(seconds)} job(s) over {len(picked)} run(s)"
        f" ({picked[-1]['createdAt']} .. {picked[0]['createdAt']})"
    )
    for name, took in sorted(seconds.items(), key=lambda kv: -kv[1]):
        print(f"  {took:5d}s  {name}  (run {where[name]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
