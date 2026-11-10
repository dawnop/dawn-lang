#!/usr/bin/env python3
"""Collect verifiable Actions observations for the manual budget audit.

Read original runs and every attempt separately, retaining the raw run and job
responses and checking page totals against distinct IDs. A fixed --since /
--until window includes running and failed runs and is never cut by --runs.
Use --branch '' to include PRs and other branches. Every attempt uses its own
run_started_at and jobs endpoint; inherited successes are not new execution.

The version 2 report records successful, failed, executed and unexecuted
cancellations, skipped, right censored and invalid clock records separately.
D is job execution, W is budgeted job-seconds, Q is scheduling wait, S is
attempt wall time, and span starts at original run creation. P50/P95/max and
identity groups distinguish first attempts from reruns, event, actual runner
image/version, steps and source input. A source SHA is not a cache or hardware
identity and does not prove the checkout of a PR merge was identical.

StepsAt reads gates.yml and the toolchain action at each run's source SHA.
PlainStepsAt reads other workflows. Both retain the existing steps_lock
semantics, including rename continuity and reshard separation. Unknown images
and invalid times are data quality errors. Raw values are never repaired.
Legacy reports lack the timestamps needed to verify these properties and must
be collected again; --restep only refreshes version 2 reports.

    scripts/gate-observations.py --since 2026-11-03T18:00:00Z \
        --until 2026-11-10T18:00:00Z --out /tmp/ci.json
    scripts/gate-observations.py --selftest
    scripts/check-gate-budgets.py --observed /tmp/ci.json --observed /tmp/tile.json

The compatible per_run view contains attempt 1 only, and a partial run cannot
claim full success. The observed audit recomputes from raw records rather than
trusting derived maxima. This collector needs a token and remains a manual or
scheduled audit; its offline selftest needs neither a token nor a network.
"""

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone

import repo_env  # scripts/repo_env.py, the reader of scripts/repo.env


# `gh api` against a 5xx or a dropped connection is the server's trouble, not
# an answer: the nightly of 2026-10-07 died on one HTTP 502 for
# runs/37270212284/jobs, a run whose jobs the same call returned a few hours
# later (#610). A refusal that says anything else (404, 403, a bad argument)
# is final and is not repeated.
GH_ATTEMPTS = 3
GH_RETRY_WAIT = 5  # seconds before the second try, doubled for the third
_TRANSIENT = (
    "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "Server Error",
    "connection reset", "timeout", "timed out", "EOF",
)


def _gh(args, *, binary=False):
    """Run `gh` with the proxy vars cleared, retrying a transient failure;
    -> the stdout, or a SystemExit naming the last failure."""
    env = dict(os.environ)
    for key in (
        "https_proxy", "http_proxy", "all_proxy", "HTTPS_PROXY", "HTTP_PROXY"
    ):
        env.pop(key, None)
    for attempt in range(1, GH_ATTEMPTS + 1):
        proc = subprocess.run(
            args, capture_output=True, text=not binary, env=env, check=False
        )
        if proc.returncode == 0:
            return proc.stdout
        error = (proc.stderr.decode("utf-8", "replace")
                 if isinstance(proc.stderr, bytes) else proc.stderr)
        transient = any(t in error for t in _TRANSIENT)
        if not transient or attempt == GH_ATTEMPTS:
            break
        time.sleep(GH_RETRY_WAIT * 2 ** (attempt - 1))
    raise SystemExit(
        f"{' '.join(args)} failed ({proc.returncode}) after {attempt}"
        f" attempt(s):\n{error.strip()}"
    )


def gh_json(args):
    """Run `gh` and parse its stdout as JSON."""
    return json.loads(_gh(args))


def gh_text(args):
    """Run `gh` and return its stdout."""
    return _gh(args)


def gh_bytes(args):
    """Read an attempt's log archive without decoding compressed bytes."""
    return _gh(args, binary=True)


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
                    {**{"plan": self.steps_lock.plain_job_digests(gates)["plan"]},
                     **self.steps_lock.job_digests(gates, action)}, None)
            except self.gatesplan.PlanError as error:
                self.reads["refused"] += 1
                self.by_blobs[key] = (None, str(error))
        self.by_commit[sha] = self.by_blobs[key]
        return self.by_commit[sha]


class PlainStepsAt:
    """{job: steps digest} of one workflow gatesplan does not model, at a commit.

    The same idea as StepsAt for a file with no composite action in it
    (tile.yml): the digest is steps_lock.plain_job_digests of the workflow
    text at the run's commit, read once per distinct blob.
    """

    def __init__(self, repo, workflow, git_dir=HERE.parent):
        sys.path.insert(0, str(GATES_EXTERNAL))
        import steps_lock
        self.steps_lock = steps_lock
        self.repo = repo
        self.path = f".github/workflows/{workflow}"
        self.git_dir = git_dir
        self.by_blob = {}
        self.by_commit = {}
        self.reads = {"commits": 0, "parsed": 0, "api": 0, "refused": 0}

    def _git(self, *args):
        proc = subprocess.run(
            ["git", "-C", str(self.git_dir), *args],
            capture_output=True, text=True, check=False)
        return proc.stdout if proc.returncode == 0 else None

    def at(self, sha):
        """-> ({job: digest}, None) or (None, why the file was refused)."""
        if sha in self.by_commit:
            return self.by_commit[sha]
        self.reads["commits"] += 1
        blob = self._git("rev-parse", "--verify", "-q", f"{sha}:{self.path}")
        text = self._git("cat-file", "blob", blob.strip()) if blob else None
        key = blob.strip() if text is not None else ("commit", sha)
        if key not in self.by_blob:
            if text is None:
                self.reads["api"] += 1
                text = gh_text([
                    "gh", "api", "-H", "Accept: application/vnd.github.raw",
                    f"repos/{self.repo}/contents/{self.path}?ref={sha}"])
            self.reads["parsed"] += 1
            try:
                self.by_blob[key] = (self.steps_lock.plain_job_digests(text), None)
            except Exception as error:  # a file yaml or the shape refuses
                self.reads["refused"] += 1
                self.by_blob[key] = (None, str(error))
        self.by_commit[sha] = self.by_blob[key]
        return self.by_commit[sha]


def steps_reader(repo, workflow):
    """The StepsAt for gates.yml's workflow (ci.yml), PlainStepsAt otherwise."""
    return StepsAt(repo) if workflow == "ci.yml" else PlainStepsAt(repo, workflow)


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


def read_pages(repo, endpoint, field, fetch=None):
    """Retain every response and verify total_count against distinct IDs."""
    from gate_observation_data import read_pages as fetch_pages
    return fetch_pages(repo, endpoint, field, fetch or gh_json)


def collect(repo, branch, workflow, runs, since, allow_empty=False, until=None):
    """Read original runs, then every attempt's own detail and paged jobs."""
    from gate_observation_data import rebuild, classify, headers_from_archive
    until = until or datetime.now(timezone.utc)
    query = "created=" + (since.strftime("%Y-%m-%dT%H:%M:%SZ") if since else "*")
    query += ".." + until.strftime("%Y-%m-%dT%H:%M:%SZ")
    if branch:
        query += f"&branch={branch}"
    pages = read_pages(repo, f"actions/workflows/{workflow}/runs?{query}", "workflow_runs")
    listed = [run for page in pages for run in page["workflow_runs"]]
    listed.sort(key=lambda r: parse_time(r["created_at"]), reverse=True)
    # A fixed window is complete, even when it contains more than --runs.
    picked = listed if since else listed[:runs]
    if not picked and not allow_empty:
        raise SystemExit(f"no {workflow} runs matched the observation window")
    steps_at = steps_reader(repo, workflow)
    raw = []
    image_reads = {"attempt_archives": 0, "job_fallbacks": 0}
    for original in picked:
        rid = original["id"]
        for attempt in range(1, original.get("run_attempt", 1) + 1):
            endpoint = f"actions/runs/{rid}/attempts/{attempt}"
            run = gh_json(["gh", "api", f"repos/{repo}/{endpoint}"])
            jobs_pages = read_pages(repo, endpoint + "/jobs?", "jobs")
            steps, steps_error = steps_at.at(run["head_sha"])
            expected = sorted(set(steps or {}) | ({"plan"} if workflow == "ci.yml" else set()))
            logs = {}
            jobs = [job for page in jobs_pages for job in page["jobs"]]
            fresh = {job["id"] for job in jobs if classify(
                job, run, until.timestamp(), set())[0] in
                ("success", "failure", "cancelled_executed")}
            headers, archive_sha, archive_error = {}, None, None
            if fresh:
                image_reads["attempt_archives"] += 1
                try:
                    payload = gh_bytes([
                        "gh", "api", "--allow-escape-sequences",
                        f"repos/{repo}/{endpoint}/logs"])
                    headers = headers_from_archive(payload)
                    archive_sha = hashlib.sha256(payload).hexdigest()
                except (SystemExit, zipfile.BadZipFile, ValueError) as error:
                    archive_error = str(error)
            for page in jobs_pages:
                for job in page["jobs"]:
                    if job["name"] in headers:
                        logs[str(job["id"])] = headers[job["name"]]
                        continue
                    if job["id"] not in fresh:
                        continue
                    image_reads["job_fallbacks"] += 1
                    try:
                        # The image identity is at the start of this raw log.
                        logs[str(job["id"])] = gh_text([
                            "gh", "api", "--allow-escape-sequences",
                            f"repos/{repo}/actions/jobs/{job['id']}/logs"])[:16384]
                    except SystemExit:
                        logs[str(job["id"])] = ""
            raw.append({"run": run, "jobs_pages": jobs_pages, "steps": steps,
                        "steps_error": steps_error, "expected_jobs": expected,
                        "input": run["head_sha"], "image_logs": logs,
                        "image_archive_sha256": archive_sha,
                        "image_archive_error": archive_error})
    report = {"schema": 2, "generated": datetime.now(timezone.utc).isoformat(),
              "repo": repo, "branch": branch, "workflow": workflow,
              "since": since.isoformat() if since else None, "until": until.isoformat(),
              "raw_run_pages": pages, "selected_run_ids": [r["id"] for r in picked],
              "raw_attempts": raw, "runs": [r["id"] for r in picked],
              "oldest_run_created": picked[-1]["created_at"] if picked else None,
              "newest_run_created": picked[0]["created_at"] if picked else None,
              "steps_reads": steps_at.reads, "image_reads": image_reads}
    return rebuild(report)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=repo_env.github_repo())
    ap.add_argument("--branch", default="main", help="empty string reads all branches")
    ap.add_argument("--workflow", default="ci.yml")
    ap.add_argument("--runs", type=int, default=25,
                    help="sample limit without --since; a fixed window is never truncated")
    ap.add_argument("--since", help="start of the complete creation window (ISO timestamp)")
    ap.add_argument("--until", help="fixed observation cutoff (ISO timestamp)")
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--allow-empty", action="store_true")
    ap.add_argument("--restep", type=pathlib.Path)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        import gate_observation_test
        return gate_observation_test.selftest()
    if args.out is None:
        ap.error("--out is required")
    from gate_observation_data import rebuild, summary_lines
    if args.restep:
        report = json.loads(args.restep.read_text(encoding="utf-8"))
        if report.get("schema") != 2:
            raise SystemExit("legacy reports lack raw timestamps; regenerate instead of --restep")
        reader = steps_reader(report["repo"], report["workflow"])
        for entry in report["raw_attempts"]:
            entry["steps"], entry["steps_error"] = reader.at(entry["run"]["head_sha"])
            entry["expected_jobs"] = sorted(set(entry["steps"] or {}) |
                                            ({"plan"} if report["workflow"] == "ci.yml" else set()))
        report = rebuild(report)
    else:
        report = collect(args.repo, args.branch, args.workflow, args.runs,
                         parse_since(args.since) if args.since else None,
                         args.allow_empty, parse_since(args.until) if args.until else None)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(report['runs'])} original runs, "
          f"{len(report['attempts'])} attempts; pagination counts verified")
    print(f"image reads: {report.get('image_reads', 'not recorded')}")
    for line in summary_lines(report):
        print(line)
    for issue in report["data_quality_errors"]:
        print(f"data quality error: {issue}", file=sys.stderr)
    return int(bool(report["data_quality_errors"]))


if __name__ == "__main__":
    sys.exit(main())
