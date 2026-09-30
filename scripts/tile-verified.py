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

    tile-verified.py --self-test     the rules above against JSON fixtures,
                                     no network
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

WORKFLOW_PATH = ".github/workflows/tile.yml"
DEDUPED_EVENTS = ("push",)


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


def lookup(fetch, repo, repo_id, tree, prefix, event, now):
    """-> (skip, run id or None, the step summary line)."""
    if event not in DEDUPED_EVENTS:
        return False, None, (f"tile: {event} runs every shard; tree {tree}"
                             " is not looked up")
    name = f"{prefix}{tree}"
    try:
        run, why = find(fetch, repo, repo_id, name, now)
    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        return False, None, (f"tile: tree {tree} not looked up ({error});"
                             " running every shard")
    if run is None:
        return False, None, f"tile: tree {tree} not verified yet ({why})"
    return True, run["id"], (f"tile: tree {tree} already verified by run"
                             f" {run['id']} ({run.get('event')},"
                             f" {run.get('head_branch')})")


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
                                 PREFIX, event, NOW)
        if skip != want:
            failures.append(f"{label}: expected skip={want}, got {skip} ({line})")
        else:
            print(f"  {'skipped' if want else 'runs'}: {label}")
    _, _, line = lookup(_fetcher([_artifact(10, 1)], good_runs), REPO, REPO_ID,
                        TREE, PREFIX, "push", NOW)
    wanted = f"tile: tree {TREE} already verified by run 1 (pull_request, ci/topic)"
    if line != wanted:
        failures.append(f"summary line is {line!r}, not {wanted!r}")
    for failure in failures:
        print(f"SELF-TEST FAIL: {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"self-test: {len(cases)} records judged as documented")
    return 0


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
    args = ap.parse_args()
    if args.self_test:
        return selftest()
    if args.command != "lookup":
        ap.error("give --self-test or lookup")
    skip, run, line = lookup(gh_json, args.repo, args.repo_id, args.tree,
                             args.prefix, args.event, datetime.now(timezone.utc))
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
