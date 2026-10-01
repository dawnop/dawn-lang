#!/usr/bin/env python3
"""Has this exact git tree already passed tile.yml? Answer from the Actions API.

tile.yml runs its six shards on every push to main that touches its paths.
In the week of 2026-09-22 .. 09-29 that was 19 pushes, and 17 of them ran on
a git tree that a pull_request run of tile.yml had verified green about half
an hour earlier: a rebase merge gives the commit a new SHA but leaves the
tree byte for byte the same (research-nightly-231, section two). None of the
19 changed a tile golden. Each re-run cost about 4,800 job-seconds.

So the workflow records a verified tree and a push asks for the record first.
The record is an artifact named `<prefix><tree>` (tile.yml sets the prefix,
`tile-verified-v1-`), uploaded by tile-shards-complete only after all six
shards and the union check are green. This script is the question:

    tile-verified.py lookup --repo R --repo-id N --tree T --prefix P --event E
                            [--sha S]

prints one line for the step summary and, under GITHUB_OUTPUT, writes
`skip=true|false` and `run=<id>`. It is fail-open: any API error, and any
event other than `push`, is `skip=false`, so the shards run. The only way to
skip is a record that passes every test below.

Why a tree and not a narrower key. A key of tile inputs alone (what
scripts/tile-gpu-diff/inputs.py digests) leaves out the compiler, and the
tile goldens are rendered by the compiler on both backends, so that would
drop exactly the emit-side coupling tile.yml's header names. A key of the
toolchain jar is the compiler plus everything else, and it changed on 31 of
that week's 57 pushes, more often than the path filter fires. The tree holds
the compiler, the goldens, the workflow file, the tileiras pin and the
composite actions at once, and it is what a rebase merge preserves.

What a record must be to count, each one a test in --self-test:

* named for this tree, with this prefix. The prefix is an environment
  version: bump it when the runner image or a floating action tag moves, and
  every tree runs again.
* not expired (`expired` false and `expires_at` in the future).
* produced in this repository by a run whose head repository is also this
  repository (the artifact's `workflow_run.repository_id` and
  `head_repository_id`). A fork's pull_request run executes the fork's copy
  of tile.yml, so its green is not this workflow's green.
* produced by a run of `.github/workflows/tile.yml` whose conclusion is
  `success`. The artifact is uploaded before its run concludes, so a run
  still in progress or later cancelled does not count.

The trust boundary is write access to this repository. A same-repository
branch can upload an artifact under any name, so it could record a tree it
never verified, but a branch with write access can already edit this
workflow or push to main, so the record claims nothing that access does not
already grant. What it keeps out is a fork, by the head repository tests.

Not actions/cache: a cache written on a pull request belongs to
refs/pull/N/merge, which main cannot read, and an unread entry is evicted in
seven days (GitHub's dependency caching reference).

Why pull_request, schedule and workflow_dispatch never skip: the whole set
runs on the pull request and on the daily schedule, and the schedule is the
backstop for environment drift that the tree cannot see. Only the push
re-run is the duplicate.

WAITING FOR THE PULL REQUEST'S OWN RUN (2026-10-01). A push is often merged
before its pull request's tile run has finished: nothing makes a merge wait
for tile.yml (main has no required status checks, and a path-triggered
required check would leave every pull request that misses the paths stuck at
"Expected"). On 09-30 .. 10-01 four of the eight pushes that still ran the
shards were exactly that: the pull_request run on the same tree concluded
success 5.5 to 9.5 minutes after the push asked, and the push had already
spent about 4,700 job-seconds verifying it again. So when the first lookup
finds no record that counts, and the push names its commit (`--sha`):

* `commits/<sha>/pulls` gives the merged pull requests of this repository
  that carry the commit, and `actions/workflows/tile.yml/runs` gives their
  pull_request runs at each head SHA;
* while any of those runs is queued or in progress, the lookup polls it every
  30 seconds, for at most 15 minutes (a tile pull_request run takes about 25
  minutes end to end, and the four races had 5.5 to 9.5 left; 15 keeps a
  full wait plus the job itself under the 950s run pole, so tile.yml's budget
  line can claim the worst case rather than a typical one);
* then it asks for the record again, under every rule above. A green record
  skips the shards and the summary names the run and the seconds waited;
  anything else runs them.

A pull request whose last run verified another tree (main moved while it
ran, and the rebase made a tree nobody verified) waits for nothing useful,
and its push runs the shards: that run is the only verification of the
combined tree, and the other four of those eight pushes were that. The
waiting is fail-open like the rest: an API error while finding the pull
request or polling its run means the shards run. A newer push to main
cancels this run while it waits (tile.yml's concurrency group), which is what
it did before the wait too.

    tile-verified.py --self-test     the rules above against JSON fixtures,
                                     no network
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

WORKFLOW_PATH = ".github/workflows/tile.yml"
DEDUPED_EVENTS = ("push",)
WAIT_LIMIT = 15 * 60   # seconds a push waits for its pull request's run
WAIT_POLL = 30         # seconds between two polls of that run
UNFINISHED = ("queued", "in_progress", "waiting", "requested", "pending")


def gh_json(path):
    """GET one Actions API path through `gh api`, proxy variables cleared."""
    env = dict(os.environ)
    for key in ("https_proxy", "http_proxy", "all_proxy", "HTTPS_PROXY", "HTTP_PROXY"):
        env.pop(key, None)
    proc = subprocess.run(["gh", "api", path], capture_output=True, text=True,
                          env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"gh api {path} failed ({proc.returncode}):"
                           f" {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def when(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def find(fetch, repo, repo_id, name, now):
    """-> (run, None) for the first record that counts, or (None, why not).

    `fetch(path)` returns the parsed JSON of one API GET; the self-test hands
    in fixtures instead of the network.
    """
    listing = fetch(f"repos/{repo}/actions/artifacts?name={name}&per_page=100")
    refusals = []
    for artifact in listing.get("artifacts", []):
        if artifact.get("name") != name:
            refusals.append(f"artifact {artifact.get('id')}: named"
                            f" {artifact.get('name')!r}")
            continue
        expires = artifact.get("expires_at")
        if artifact.get("expired") or not expires or when(expires) <= now:
            refusals.append(f"artifact {artifact.get('id')}: expired")
            continue
        origin = artifact.get("workflow_run") or {}
        if (origin.get("repository_id") != repo_id
                or origin.get("head_repository_id") != repo_id):
            refusals.append(f"artifact {artifact.get('id')}: from run"
                            f" {origin.get('id')} of another repository")
            continue
        run = fetch(f"repos/{repo}/actions/runs/{origin.get('id')}")
        if run.get("path") != WORKFLOW_PATH:
            refusals.append(f"run {run.get('id')}: is {run.get('path')!r},"
                            f" not {WORKFLOW_PATH}")
            continue
        if ((run.get("repository") or {}).get("id") != repo_id
                or (run.get("head_repository") or {}).get("id") != repo_id):
            refusals.append(f"run {run.get('id')}: head repository is not"
                            " this one")
            continue
        if run.get("conclusion") != "success":
            refusals.append(f"run {run.get('id')}: concluded"
                            f" {run.get('conclusion')!r}")
            continue
        return run, None
    return None, "; ".join(refusals) or "no record"


def unfinished_runs(fetch, repo, repo_id, sha):
    """-> ids of the tile.yml pull_request runs, still running, of the merged
    pull requests of this repository that carry `sha`."""
    pending = []
    for pull in fetch(f"repos/{repo}/commits/{sha}/pulls"):
        head = pull.get("head") or {}
        if (not pull.get("merged_at")
                or ((head.get("repo") or {}).get("id")) != repo_id):
            continue
        listing = fetch(f"repos/{repo}/actions/workflows/tile.yml/runs"
                        f"?event=pull_request&head_sha={head.get('sha')}"
                        "&per_page=100")
        for run in listing.get("workflow_runs", []):
            if (run.get("status") in UNFINISHED
                    and run.get("path") == WORKFLOW_PATH
                    and (run.get("head_repository") or {}).get("id") == repo_id):
                pending.append(run["id"])
    return pending


def wait_for(fetch, repo, pending, sleep, clock, limit, poll):
    """Poll each run in `pending` until none is unfinished or `limit` seconds
    have passed. -> the seconds waited."""
    start = clock()
    while pending and clock() - start < limit:
        sleep(min(poll, max(0, limit - (clock() - start))))
        pending = [ident for ident in pending
                   if fetch(f"repos/{repo}/actions/runs/{ident}").get("status")
                   in UNFINISHED]
    return int(clock() - start)


def lookup(fetch, repo, repo_id, tree, prefix, event, now, sha=None,
           sleep=time.sleep, clock=time.monotonic, limit=WAIT_LIMIT,
           poll=WAIT_POLL):
    """-> (skip, run id or None, the step summary line).

    `now` is a function returning the current UTC time; `sleep` and `clock`
    are time.sleep and time.monotonic outside the self-test.
    """
    if event not in DEDUPED_EVENTS:
        return False, None, (f"tile: {event} runs every shard; tree {tree}"
                             " is not looked up")
    name = f"{prefix}{tree}"
    try:
        run, why = find(fetch, repo, repo_id, name, now())
    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        return False, None, (f"tile: tree {tree} not looked up ({error});"
                             " running every shard")
    if run is not None:
        return True, run["id"], (f"tile: tree {tree} already verified by run"
                                 f" {run['id']} ({run.get('event')},"
                                 f" {run.get('head_branch')})")
    if sha is None:
        return False, None, f"tile: tree {tree} not verified yet ({why})"
    try:
        pending = unfinished_runs(fetch, repo, repo_id, sha)
        if not pending:
            return False, None, (f"tile: tree {tree} not verified yet ({why});"
                                 " no pull request run of it in progress")
        waited = wait_for(fetch, repo, pending, sleep, clock, limit, poll)
        run, why = find(fetch, repo, repo_id, name, now())
    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        return False, None, (f"tile: tree {tree} not verified yet ({why});"
                             f" waiting for its pull request run failed"
                             f" ({error}); running every shard")
    runs = ", ".join(str(ident) for ident in pending)
    if run is None:
        return False, None, (f"tile: tree {tree} not verified after waiting"
                             f" {waited}s for pull request run {runs} ({why})")
    return True, run["id"], (f"tile: tree {tree} verified by run {run['id']}"
                             f" ({run.get('event')}, {run.get('head_branch')})"
                             f" after waiting {waited}s for it")


# --- self-test -------------------------------------------------------------

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
REPO = "dawnop/dawn-lang"
REPO_ID = 1297375990
FORK_ID = 4242
TREE = "a" * 40
OTHER = "b" * 40
PREFIX = "tile-verified-v1-"


def _artifact(ident, run, tree=TREE, expired=False, expires="2026-12-01T00:00:00Z",
              repo_id=REPO_ID, head_id=REPO_ID):
    return {"id": ident, "name": f"{PREFIX}{tree}", "expired": expired,
            "expires_at": expires,
            "workflow_run": {"id": run, "repository_id": repo_id,
                             "head_repository_id": head_id,
                             "head_branch": "x", "head_sha": "0" * 40}}


def _run(ident, conclusion="success", path=WORKFLOW_PATH, head_id=REPO_ID,
         event="pull_request", branch="ci/topic"):
    return {"id": ident, "path": path, "conclusion": conclusion,
            "event": event, "head_branch": branch,
            "repository": {"id": REPO_ID}, "head_repository": {"id": head_id}}


def _fetcher(artifacts, runs):
    """A fetch() over fixtures: the listing filtered by name, as the API does."""
    def fetch(path):
        if path.startswith(f"repos/{REPO}/actions/artifacts?name="):
            name = path.split("name=", 1)[1].split("&", 1)[0]
            return {"artifacts": [a for a in artifacts if a["name"] == name]}
        if path.startswith(f"repos/{REPO}/actions/runs/"):
            ident = int(path.rsplit("/", 1)[1])
            if ident not in runs:
                raise RuntimeError(f"HTTP 404 for {path}")
            return runs[ident]
        raise RuntimeError(f"unexpected path {path}")
    return fetch


def selftest():
    good_runs = {1: _run(1)}
    cases = [
        # (label, artifacts, runs, tree, event, want skip)
        ("the same tree, green run of this repository", [_artifact(10, 1)],
         good_runs, TREE, "push", True),
        ("a different tree", [_artifact(10, 1)], good_runs, OTHER, "push", False),
        ("the run failed", [_artifact(10, 2)], {2: _run(2, "failure")},
         TREE, "push", False),
        ("the run is still in progress", [_artifact(10, 3)], {3: _run(3, None)},
         TREE, "push", False),
        ("the run was cancelled", [_artifact(10, 4)], {4: _run(4, "cancelled")},
         TREE, "push", False),
        ("the artifact came from a fork's run",
         [_artifact(10, 5, head_id=FORK_ID)], {5: _run(5, head_id=FORK_ID)},
         TREE, "push", False),
        ("the artifact says this repository, the run says a fork",
         [_artifact(10, 6)], {6: _run(6, head_id=FORK_ID)}, TREE, "push", False),
        ("the artifact is marked expired", [_artifact(10, 1, expired=True)],
         good_runs, TREE, "push", False),
        ("the artifact's expiry has passed",
         [_artifact(10, 1, expires="2026-09-30T11:59:59Z")], good_runs,
         TREE, "push", False),
        ("the run is another workflow", [_artifact(10, 7)],
         {7: _run(7, path=".github/workflows/gates.yml")}, TREE, "push", False),
        ("a red record, then a green one", [_artifact(10, 2), _artifact(11, 1)],
         {1: _run(1), 2: _run(2, "failure")}, TREE, "push", True),
        ("a pull request never skips", [_artifact(10, 1)], good_runs,
         TREE, "pull_request", False),
        ("a schedule never skips", [_artifact(10, 1)], good_runs,
         TREE, "schedule", False),
        ("a dispatch never skips", [_artifact(10, 1)], good_runs,
         TREE, "workflow_dispatch", False),
        ("the API is down", [_artifact(10, 99)], {}, TREE, "push", False),
    ]
    failures = []
    for label, artifacts, runs, tree, event, want in cases:
        skip, run, line = lookup(_fetcher(artifacts, runs), REPO, REPO_ID, tree,
                                 PREFIX, event, lambda: NOW)
        if skip != want:
            failures.append(f"{label}: expected skip={want}, got {skip} ({line})")
        else:
            print(f"  {'skipped' if want else 'runs'}: {label}")
    _, _, line = lookup(_fetcher([_artifact(10, 1)], good_runs), REPO, REPO_ID,
                        TREE, PREFIX, "push", lambda: NOW)
    wanted = f"tile: tree {TREE} already verified by run 1 (pull_request, ci/topic)"
    if line != wanted:
        failures.append(f"summary line is {line!r}, not {wanted!r}")
    waits = wait_selftest(failures)
    for failure in failures:
        print(f"SELF-TEST FAIL: {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"self-test: {len(cases)} records and {waits} waits judged as"
          " documented")
    return 0


SHA = "c" * 40
PR_HEAD = "d" * 40


class _Timeline:
    """A clock, a sleep that moves it, and an API whose answers depend on it.

    `pr_runs` is {id: (finishes at second, conclusion, tree it verified)}.
    Each run uploads its record a minute before it concludes, as tile.yml's
    tile-shards-complete does, and only when it is going to conclude success.
    `pulls` is the commits/<sha>/pulls answer, or an exception to raise.
    """

    def __init__(self, pulls, pr_runs):
        self.t = 0
        self.slept = 0
        self.pulls = pulls
        self.pr_runs = pr_runs

    def clock(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds
        self.slept += seconds

    def run(self, ident):
        finish, conclusion, _ = self.pr_runs[ident]
        done = self.t >= finish
        return dict(_run(ident, conclusion if done else None),
                    status="completed" if done else "in_progress",
                    head_sha=PR_HEAD)

    def fetch(self, path):
        if path == f"repos/{REPO}/commits/{SHA}/pulls":
            if isinstance(self.pulls, Exception):
                raise self.pulls
            return self.pulls
        if path.startswith(f"repos/{REPO}/actions/workflows/tile.yml/runs?"):
            assert f"head_sha={PR_HEAD}" in path and "event=pull_request" in path
            return {"workflow_runs": [self.run(i) for i in self.pr_runs]}
        if path.startswith(f"repos/{REPO}/actions/artifacts?name="):
            name = path.split("name=", 1)[1].split("&", 1)[0]
            made = [_artifact(100 + i, i, tree=tree)
                    for i, (finish, conclusion, tree) in self.pr_runs.items()
                    if conclusion == "success" and self.t >= finish - 60]
            return {"artifacts": [a for a in made if a["name"] == name]}
        if path.startswith(f"repos/{REPO}/actions/runs/"):
            return self.run(int(path.rsplit("/", 1)[1]))
        raise RuntimeError(f"unexpected path {path}")


def _pull(merged=True, head_id=REPO_ID):
    return {"number": 290, "merged_at": "2026-09-30T20:05:53Z" if merged else None,
            "head": {"sha": PR_HEAD, "repo": {"id": head_id}}}


def wait_selftest(failures):
    """The push that waits for its pull request's run. -> cases judged."""
    cases = [
        # (label, pulls, pr runs, want skip, want seconds slept)
        ("the pull request's run is in progress and turns green",
         [_pull()], {7: (300, "success", TREE)}, True, 300),
        ("the pull request's run is in progress and turns red",
         [_pull()], {7: (300, "failure", TREE)}, False, 300),
        ("the pull request's run is in progress and is cancelled",
         [_pull()], {7: (300, "cancelled", TREE)}, False, 300),
        ("the pull request's run outlasts the 15 minute limit",
         [_pull()], {7: (WAIT_LIMIT + 300, "success", TREE)}, False, WAIT_LIMIT),
        ("no pull request carries the commit", [], {}, False, 0),
        ("the pull request lookup fails",
         RuntimeError("gh api commits/pulls failed (1): HTTP 502"),
         {7: (300, "success", TREE)}, False, 0),
        ("the pull request's run turns green on another tree",
         [_pull()], {7: (300, "success", OTHER)}, False, 300),
        ("the pull request's run already finished red, nothing to wait for",
         [_pull()], {7: (-60, "failure", TREE)}, False, 0),
        ("the pull request came from a fork", [_pull(head_id=FORK_ID)],
         {7: (300, "success", TREE)}, False, 0),
    ]
    for label, pulls, pr_runs, want, want_slept in cases:
        timeline = _Timeline(pulls, pr_runs)
        skip, _, line = lookup(timeline.fetch, REPO, REPO_ID, TREE, PREFIX,
                               "push", lambda: NOW, sha=SHA,
                               sleep=timeline.sleep, clock=timeline.clock)
        if skip != want or timeline.slept != want_slept:
            failures.append(f"{label}: expected skip={want} after"
                            f" {want_slept}s, got {skip} after"
                            f" {timeline.slept}s ({line})")
        else:
            print(f"  {'skipped' if want else 'runs'} after {want_slept}s:"
                  f" {label}")
    timeline = _Timeline([_pull()], {7: (300, "success", TREE)})
    _, _, line = lookup(timeline.fetch, REPO, REPO_ID, TREE, PREFIX, "push",
                        lambda: NOW, sha=SHA, sleep=timeline.sleep,
                        clock=timeline.clock)
    wanted = (f"tile: tree {TREE} verified by run 7 (pull_request, ci/topic)"
              " after waiting 300s for it")
    if line != wanted:
        failures.append(f"waited summary line is {line!r}, not {wanted!r}")
    return len(cases)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="command")
    lk = sub.add_parser("lookup", help="is this tree verified? (writes GITHUB_OUTPUT)")
    lk.add_argument("--repo", required=True)
    lk.add_argument("--repo-id", type=int, required=True)
    lk.add_argument("--tree", required=True)
    lk.add_argument("--prefix", required=True)
    lk.add_argument("--event", required=True)
    lk.add_argument("--sha", help="the pushed commit; with it, a push waits for"
                    " its pull request's tile run still in progress")
    args = ap.parse_args()
    if args.self_test:
        return selftest()
    if args.command != "lookup":
        ap.error("give --self-test or lookup")
    skip, run, line = lookup(gh_json, args.repo, args.repo_id, args.tree,
                             args.prefix, args.event,
                             lambda: datetime.now(timezone.utc), sha=args.sha)
    print(line)
    for name in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
        target = os.environ.get(name)
        if not target:
            continue
        with open(target, "a", encoding="utf-8") as out:
            if name == "GITHUB_OUTPUT":
                out.write(f"skip={'true' if skip else 'false'}\n")
                out.write(f"run={run or ''}\n")
            else:
                out.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
