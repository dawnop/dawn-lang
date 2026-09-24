#!/usr/bin/env python3
"""Decide whether a tagged commit carries evidence that the gate set passed.

Why this is a script and not the jq it replaced: release.yml's `verified` job
used to ask one question (did ci.yml succeed on this sha?) and a dozen lines
of shell answered it. Since the external evidence protocol (docs/bootstrap.md)
there are two acceptable answers, and the second one has enough ways to be
counterfeit that its checks need names, tests and a place to be read. The
logic lives here so it can be run against a stub `gh` on a laptop; the
workflow only calls it.

The two sources of evidence, either of which is enough:

1. ci.yml has a completed, successful run whose head_sha is this commit,
   triggered by a push to the default branch. Only that run is the whole
   gate set. Until 2026-09-23 any successful run would do, on any branch or
   event, because ci.yml called the same gates.yml everywhere and every run
   was the whole set. The two-tier CI (#168) ended that: a pull_request run
   executes only the jobs scripts/gate-map/plan.py names for its diff, and
   the rest report as skipped, which GitHub counts as success. The Actions
   API files a pull request run under the pull request's head sha, so a
   commit that went green as a pull request head and was then pushed to main
   unchanged (a fast-forward) would pass with `any(success)` on the strength
   of a subset, even if main's full run of the same sha was red. So the run
   must say event `push` and head_branch the default branch; plan.py answers
   `all` for every event that is not a pull request, which is what makes
   such a run the whole set. Refused runs are still listed, each with the
   reason, so a red guard shows what it did find. Matching on head_sha alone
   is also what Envoy's workflow policy warns against: head_sha is a key a
   pull request author controls.

2. The latest commit status with context `gates/maintainer` on this commit is
   `success`, and it was written by verify-external.yml on this repository's
   default branch, in a run that itself succeeded. A commit status is not
   evidence on its own: anyone with write access can POST one with any
   context and any target_url. So the status is only accepted when all of
   these hold, each of which a forger would have to arrange separately:

     * its creator is `github-actions[bot]`, the identity of GITHUB_TOKEN,
       not a person's token;
     * its target_url is exactly <server>/<this repo>/actions/runs/<id>, not
       another repository's run and not some other page;
     * that run, read back from this repository's API, is the workflow file
       .github/workflows/verify-external.yml, triggered by workflow_dispatch,
       on the default branch (so the verifier and allowed_signers are the
       reviewed ones, not a branch's copy), completed with conclusion
       success;
     * the status was created inside that run's time window
       (run_started_at .. updated_at). The Actions API does not return a
       dispatch run's inputs, so this is how the status is tied to the run
       that wrote it rather than to any successful verify run a forger could
       point at.

   Taking the latest `gates/maintainer` status rather than any successful one
   is GitHub's own rule for a context: a later failure supersedes an earlier
   success.

What this does not do is re-verify the signed note itself. verify-external.yml
did that on a GitHub-hosted runner from the default branch's verifier, and the
checks above establish that it is that run's verdict being read. Anyone who
wants to repeat the cryptography can run verify_note.py (see README.md).

The tagged commit supplies both release.yml and this script, so a commit that
edits them can skip the guard; that was already true of the jq, since a push
event runs the workflow file at the pushed ref. The guard holds the release
procedure to itself, it is not a defence against the maintainer.

Exit status: 0 when either source holds, 1 when neither does, 2 when the API
could not be read (which is not a verdict).

    release_evidence.py --repo OWNER/NAME --sha SHA --default-branch main
    release_evidence.py --selftest
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

CONTEXT = "gates/maintainer"
VERIFY_WORKFLOW = ".github/workflows/verify-external.yml"
BOT = "github-actions[bot]"


class ApiError(Exception):
    """The API could not be read; no verdict either way."""


def gh_api(path):
    """GET one API path through `gh api --paginate`, as a list of pages."""
    proc = subprocess.run(["gh", "api", "--paginate", path],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ApiError(f"gh api {path} failed ({proc.returncode}): {proc.stderr.strip()}")
    # --paginate concatenates one JSON document per page; decode them in turn.
    pages, text, pos = [], proc.stdout, 0
    decoder = json.JSONDecoder()
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            break
        try:
            page, pos = decoder.raw_decode(text, pos)
        except json.JSONDecodeError as error:
            raise ApiError(f"gh api {path}: not JSON: {error}")
        pages.append(page)
    return pages


def parse_time(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def ci_refusal(run, default_branch):
    """Why a ci.yml run cannot stand for the whole gate set, or None."""
    if run.get("event") != "push":
        return f"event {run.get('event')}, not push (a pull request runs a subset)"
    if run.get("head_branch") != default_branch:
        return f"pushed to {run.get('head_branch')}, not {default_branch}"
    return None


def ci_evidence(api, repo, sha, default_branch):
    """(ok, pending, lines) for source 1."""
    pages = api(f"repos/{repo}/actions/workflows/ci.yml/runs?head_sha={sha}&per_page=100")
    runs = [run for page in pages for run in page.get("workflow_runs", [])]
    lines, ok, pending = [], False, False
    for run in runs:
        refusal = ci_refusal(run, default_branch)
        lines.append(f"  {run.get('status')}\t{run.get('conclusion') or 'pending'}\t"
                     f"{run.get('event')}\t{run.get('head_branch')}\t{run.get('html_url')}"
                     + (f"\trefused: {refusal}" if refusal else ""))
        if refusal:
            continue
        if run.get("status") == "completed" and run.get("conclusion") == "success":
            ok = True
        elif run.get("status") != "completed":
            pending = True
    return ok, pending, lines or ["  (none)"]


def external_evidence(api, repo, sha, default_branch, server):
    """(ok, lines) for source 2."""
    pages = api(f"repos/{repo}/commits/{sha}/statuses?per_page=100")
    statuses = [s for page in pages for s in page if s.get("context") == CONTEXT]
    if not statuses:
        return False, [f"  no {CONTEXT} status on this commit"]
    # The API lists a commit's statuses newest first; sort anyway so the
    # verdict does not rest on that ordering.
    latest = max(statuses, key=lambda s: (s.get("created_at") or "", s.get("id") or 0))
    creator = (latest.get("creator") or {}).get("login")
    target = latest.get("target_url") or ""
    lines = [f"  latest {CONTEXT}: state {latest.get('state')}, creator {creator}, "
             f"created {latest.get('created_at')}, target {target or '(none)'}"]
    problems = []
    if latest.get("state") != "success":
        problems.append(f"state is {latest.get('state')}, not success")
    if creator != BOT:
        problems.append(f"written by {creator}, not {BOT}")
    match = re.fullmatch(re.escape(f"{server}/{repo}/actions/runs/") + r"(\d+)", target)
    if not match:
        problems.append(f"target_url is not a run of {repo}")
    if problems:
        return False, lines + [f"  refused: {p}" for p in problems]

    run_id = match.group(1)
    run = api(f"repos/{repo}/actions/runs/{run_id}")[0]
    lines.append(f"  run {run_id}: {run.get('path')}, {run.get('event')} on "
                 f"{run.get('head_branch')}, {run.get('status')}/{run.get('conclusion')}")
    if (run.get("repository") or {}).get("full_name") != repo:
        problems.append(f"run {run_id} belongs to {(run.get('repository') or {}).get('full_name')}")
    if run.get("path") != VERIFY_WORKFLOW:
        problems.append(f"run {run_id} is {run.get('path')}, not {VERIFY_WORKFLOW}")
    if run.get("event") != "workflow_dispatch":
        problems.append(f"run {run_id} was triggered by {run.get('event')}")
    if run.get("head_branch") != default_branch:
        problems.append(f"run {run_id} ran on {run.get('head_branch')}, not {default_branch}")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        problems.append(f"run {run_id} is {run.get('status')}/{run.get('conclusion')}")
    try:
        written = parse_time(latest["created_at"])
        start, end = parse_time(run["run_started_at"]), parse_time(run["updated_at"])
        if not start <= written <= end:
            problems.append(f"the status was written at {latest['created_at']}, outside run "
                            f"{run_id} ({run['run_started_at']} .. {run['updated_at']})")
    except (KeyError, TypeError, ValueError) as error:
        problems.append(f"cannot place the status inside run {run_id}: {error}")
    if problems:
        return False, lines + [f"  refused: {p}" for p in problems]
    return True, lines


def decide(api, repo, sha, default_branch, server, out):
    """Print both checks and return the exit status."""
    ci_ok, pending, ci_lines = ci_evidence(api, repo, sha, default_branch)
    ext_ok, ext_lines = external_evidence(api, repo, sha, default_branch, server)
    print(f"check 1, ci.yml push runs on {default_branch} at {sha} "
          "(status, conclusion, event, branch, url):", file=out)
    for line in ci_lines:
        print(line, file=out)
    print(f"  -> {'green' if ci_ok else f'no successful push run on {default_branch}'}",
          file=out)
    print(f"check 2, {CONTEXT} status written by {VERIFY_WORKFLOW} on {default_branch}:",
          file=out)
    for line in ext_lines:
        print(line, file=out)
    print(f"  -> {'accepted' if ext_ok else 'not accepted'}", file=out)
    if ci_ok or ext_ok:
        which = " and ".join(n for n, ok in (("ci.yml", ci_ok), ("gates/maintainer", ext_ok)) if ok)
        print(f"OK: the gates are green on {sha} ({which})", file=out)
        return 0
    if pending:
        print(f"::error::neither check holds on {sha}, and ci is still running there; wait for "
              "that run to go green (or publish external evidence), then re-run this release "
              "workflow", file=out)
    else:
        print(f"::error::neither check holds on {sha}: no successful ci.yml push run on "
              f"{default_branch} and no accepted "
              f"{CONTEXT} status. Get ci green on this commit or publish signed external "
              "evidence (scripts/gates-external/publish.py), then re-run this release "
              "workflow, or delete the tag and push it again at a verified commit.", file=out)
    return 1


# ------------------------------------------------------------------ self-test

def _fake(tables):
    def api(path):
        for prefix, pages in tables.items():
            if path.startswith(prefix):
                return pages
        raise ApiError(f"unexpected path {path}")
    return api


def self_test():
    import io
    repo, sha, other = "o/r", "a" * 40, "x/y"
    runs_ci = f"repos/{repo}/actions/workflows/ci.yml/runs"
    stats = f"repos/{repo}/commits/{sha}/statuses"
    run_path = f"repos/{repo}/actions/runs/7"
    main_push = {"status": "completed", "conclusion": "success", "event": "push",
                 "head_branch": "main", "html_url": "u"}
    ci_green = {"workflow_runs": [main_push]}
    ci_none = {"workflow_runs": []}
    good_status = {"context": CONTEXT, "state": "success", "id": 1,
                   "created_at": "2026-09-24T10:00:30Z", "creator": {"login": BOT},
                   "target_url": f"https://github.com/{repo}/actions/runs/7"}
    good_run = {"repository": {"full_name": repo}, "path": VERIFY_WORKFLOW,
                "event": "workflow_dispatch", "head_branch": "main", "status": "completed",
                "conclusion": "success", "run_started_at": "2026-09-24T10:00:00Z",
                "updated_at": "2026-09-24T10:01:00Z"}

    def case(ci, statuses, run=good_run):
        return _fake({runs_ci: [ci], stats: [statuses], run_path: [run]})

    cases = {
        "only ci green": (case(ci_green, []), 0),
        "only external green": (case(ci_none, [good_status]), 0),
        "neither": (case(ci_none, []), 1),
        "status pointing at another repo": (
            case(ci_none, [dict(good_status,
                                target_url=f"https://github.com/{other}/actions/runs/7")]), 1),
        "status pointing at another workflow": (
            case(ci_none, [good_status], dict(good_run, path=".github/workflows/ci.yml")), 1),
        "status written by a person": (
            case(ci_none, [dict(good_status, creator={"login": "someone"})]), 1),
        "verify run on a branch": (case(ci_none, [good_status], dict(good_run, head_branch="x")), 1),
        "verify run failed": (case(ci_none, [good_status], dict(good_run, conclusion="failure")), 1),
        "status outside the run": (
            case(ci_none, [dict(good_status, created_at="2026-09-24T11:00:00Z")]), 1),
        "later failure supersedes": (
            case(ci_none, [dict(good_status, state="failure", id=2,
                                created_at="2026-09-24T10:00:50Z"), good_status]), 1),
        "ci pending only": (case({"workflow_runs": [dict(main_push, status="in_progress",
                                                        conclusion=None)]}, []), 1),
        # Since the two-tier CI (#168) only a push run on the default branch is
        # the whole gate set; a pull request run is a subset whatever it says.
        # Its head_branch is the pull request's head branch, which is `main`
        # for a fork's main, so the branch test alone does not refuse it.
        "pull request run green": (
            case({"workflow_runs": [dict(main_push, event="pull_request")]}, []), 1),
        "push run on another branch green": (
            case({"workflow_runs": [dict(main_push, head_branch="feature")]}, []), 1),
        "main push green beside a pull request run": (
            case({"workflow_runs": [dict(main_push, event="pull_request",
                                         head_branch="feature", conclusion="failure"),
                                    main_push]}, []), 0),
    }
    failures = []
    for label, (api, want) in cases.items():
        got = decide(api, repo, sha, "main", "https://github.com", io.StringIO())
        if got != want:
            failures.append(f"{label}: exit {got}, want {want}")
    for line in failures:
        print(f"FAIL release_evidence self-test: {line}", file=sys.stderr)
    if failures:
        return 1
    print(f"OK: release_evidence self-test, {len(cases)} cases")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo")
    parser.add_argument("--sha")
    parser.add_argument("--default-branch")
    parser.add_argument("--server", default=os.environ.get("GITHUB_SERVER_URL",
                                                           "https://github.com"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return self_test()
    if not (args.repo and args.sha and args.default_branch):
        parser.error("--repo, --sha and --default-branch are required")
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error(f"--sha must be 40 lowercase hex, got {args.sha!r}")
    try:
        return decide(gh_api, args.repo, args.sha, args.default_branch,
                      args.server.rstrip("/"), sys.stdout)
    except ApiError as error:
        print(f"::error::could not read the evidence: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
