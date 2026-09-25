#!/usr/bin/env python3
"""Sign a complete gate bundle, attach it to its commit, and ask GitHub to check it.

Why this exists: an external gate run ends with bundle.json on the machine
that ran it. For anyone else to rely on it, it has to be signed by the
maintainer's gate key, stored where a verifier can find it (a note on the
commit, refs/notes/gates), and checked somewhere the maintainer does not
control the verdict (verify-external.yml on a GitHub-hosted runner, which
writes the `gates/maintainer` commit status). Every connection goes out from
this machine; GitHub never connects back.

What it refuses, before anything leaves this machine:
  * a bundle that `bundle.check` finds invalid (schema, leak, a table or
    multiset that is not the commit's), with this machine's own host and user
    names in the leak filter, as when the bundle was built;
  * a bundle that is not complete. Red evidence is not published: there is
    nothing a signed "the gates failed" would let anyone do that the absence
    of a green status does not already say;
  * a bundle whose tree is not the commit named on the command line;
  * an envelope that verify_note.py would not accept against this checkout's
    allowed_signers, so a wrong key is caught here and not on GitHub.

Steps, in order: verify, sign, `git notes --ref=gates add -f`, `git push
<remote> refs/notes/gates`, `gh workflow run verify-external.yml -f sha=<sha>`.

With --rerun-ci it then closes the loop the evidence tier opens (gates.yml's
plan job skips every gate of a commit whose `gates/maintainer` status it
accepts, docs/gates-external-design.md). ci.yml starts the moment a commit
is pushed, before any evidence exists, so that first run plans a subset or
the whole set and holds GitHub's runners for it. --rerun-ci waits for the
verify-external run it dispatched (`gh run list` for the run, `gh run watch`
until it ends), and only when that run succeeded and the status it wrote
passes the same acceptance the plan job will make
(release_evidence.external_evidence), finds this repository's ci.yml runs of
the sha (pull_request events only, since a push never reads evidence; never
a fork's), cancels one still running and re-runs the newest. The re-run plans again, finds
the status, and skips. A failed verify, a status the plan would refuse, or
no ci run at all re-runs nothing: the first two because the re-run would
plan exactly as before, the last because the next push or pull request will
find the status by itself.

    publish.py <sha> --bundle <file> [--key ~/.ssh/dawn-gates-sign]
               [--repo DIR] [--remote origin]
               [--dry-run]            sign and write the note locally; print
                                      the push and the dispatch, run neither
               [--dry-run-dispatch]   push the note; print the dispatch only
               [--rerun-ci]           after the dispatch, wait for the verify
                                      run and re-run this sha's ci.yml runs
    publish.py --selftest             the refusals and a push to a scratch
                                      bare repository, with a throwaway key,
                                      then the --rerun-ci cases
    publish.py --selftest-rerun-ci    the --rerun-ci cases alone: a stub gh,
                                      no git, no ssh-keygen (what tree-policy
                                      runs; ssh-keygen refuses a uid with no
                                      passwd entry, which is how the external
                                      runner executes jobs)

--remote takes anything `git push` does, so a local bare repository stands in
for GitHub in tests. The dispatch always targets the repository `gh` resolves
from the checkout, so it is never run unless the remote is the real one; with
a path as --remote it is refused rather than sent somewhere unrelated.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bundle as bundle_mod  # noqa: E402
import release_evidence  # noqa: E402
import verify_note  # noqa: E402

DEFAULT_KEY = Path("~/.ssh/dawn-gates-sign")
WORKFLOW = "verify-external.yml"


class Refused(Exception):
    """Nothing was published."""


def git(repo, *args, env=None):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                            text=True, env=env)
    if result.returncode != 0:
        raise Refused(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def prepare(repo, sha, bundle, key, allowed_signers, identities=None):
    """-> the envelope text, after every refusal above. Writes nothing."""
    if not verify_note.HEX40.match(sha):
        sha = git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}")
    plan, errors, complete, reasons = bundle_mod.check(bundle, repo, identities)
    if errors:
        raise Refused("the bundle is invalid:\n  " + "\n  ".join(errors))
    if not complete or bundle.get("complete") is not True:
        raise Refused("the bundle is not complete; red evidence is not published:\n  "
                      + "\n  ".join(reasons[:20])
                      + (f"\n  (+{len(reasons) - 20} more)" if len(reasons) > 20 else ""))
    if bundle.get("tree") != sha:
        raise Refused(f"the bundle is for {bundle.get('tree')}, not {sha}")
    text = verify_note.envelope_text(bundle, verify_note.sign(bundle, key))
    ok, lines = verify_note.verify_envelope(repo, sha, text, allowed_signers)
    if not ok:
        raise Refused("the signed envelope does not verify here (wrong key?):\n  "
                      + "\n  ".join(ln for ln in lines if ln.startswith("FAIL")))
    return sha, text


def publish(repo, sha, text, remote, push, dispatch, env=None):
    """Write the note, then push and dispatch as asked. Prints each step."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        handle.write(text)
        note_file = handle.name
    try:
        git(repo, "notes", f"--ref={verify_note.NOTES_REF}", "add", "-f", "-F", note_file,
            sha, env=env)
    finally:
        Path(note_file).unlink()
    print(f"note: {verify_note.NOTES_REF} on {sha}")
    push_cmd = ["git", "-C", str(repo), "push", remote, verify_note.NOTES_REF]
    dispatch_cmd = ["gh", "workflow", "run", WORKFLOW, "-f", f"sha={sha}"]
    if not push:
        print("dry run, not pushed: " + " ".join(push_cmd))
    else:
        result = subprocess.run(push_cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            raise Refused(f"push failed (the note is written locally): "
                          f"{result.stderr.strip()}\nIf the remote notes moved, "
                          f"fetch them into a separate ref and merge with "
                          f"`git notes --ref=gates merge` before retrying.")
        print(f"pushed: {verify_note.NOTES_REF} to {remote}")
    if not dispatch:
        print("dry run, not dispatched: " + " ".join(dispatch_cmd))
        return
    result = subprocess.run(dispatch_cmd, cwd=repo, capture_output=True, text=True)
    if result.returncode != 0:
        raise Refused(f"dispatch failed (the note is pushed): {result.stderr.strip()}")
    print(f"dispatched: {WORKFLOW} for {sha}; the status context is gates/maintainer")


# ------------------------------------------------------------ --rerun-ci

# Pull requests only: a push run never reads evidence (ci.yml passes no
# head sha on a push), so re-running one would re-run the whole set.
CI_EVENTS = ("pull_request",)
# How far the dispatch's own clock may lead GitHub's when picking the run it
# started out of `gh run list`; and how long to wait for that run to appear
# and for a cancelled ci run to settle before re-running it.
CLOCK_SLACK = timedelta(seconds=60)
APPEAR_TIMEOUT = 180
SETTLE_TIMEOUT = 180
POLL = 10


def run_gh(args, cwd):
    """`gh <args>` in the checkout; its stdout, or Refused."""
    result = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Refused(f"gh {' '.join(args)} failed ({result.returncode}): "
                      f"{result.stderr.strip()}")
    return result.stdout


def parse_stamp(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def rerun_ci(repo, sha, dispatched_at, gh=run_gh, sleep=time.sleep, clock=time.monotonic,
             out=sys.stdout):
    """Wait for the verify run, then re-run this sha's ci.yml runs. -> exit status.

    `gh` is `(args, cwd) -> stdout`, raising Refused; the self-test swaps it.
    """
    info = json.loads(gh(["repo", "view", "--json", "nameWithOwner,defaultBranchRef"], repo))
    nwo, default_branch = info["nameWithOwner"], info["defaultBranchRef"]["name"]

    # The dispatched run. The Actions API does not return a dispatch's inputs,
    # so it is the newest dispatch run created after this dispatch; the status
    # check below is what ties the verdict to this sha either way.
    listing = ["run", "list", "--workflow", WORKFLOW, "--event", "workflow_dispatch",
               "--limit", "10", "--json", "databaseId,createdAt,status,conclusion"]
    deadline = clock() + APPEAR_TIMEOUT
    run_id = None
    while run_id is None:
        runs = [r for r in json.loads(gh(listing, repo))
                if parse_stamp(r["createdAt"]) >= dispatched_at - CLOCK_SLACK]
        if runs:
            run_id = max(runs, key=lambda r: r["createdAt"])["databaseId"]
        elif clock() > deadline:
            print(f"rerun-ci: no {WORKFLOW} run appeared within {APPEAR_TIMEOUT}s; "
                  "not re-running ci", file=out)
            return 1
        else:
            sleep(POLL)
    print(f"rerun-ci: watching {WORKFLOW} run {run_id}", file=out)
    try:
        gh(["run", "watch", str(run_id), "--exit-status", "--interval", str(POLL)], repo)
    except Refused:
        pass  # --exit-status fails on a failed run; the conclusion below says which
    view = json.loads(gh(["run", "view", str(run_id), "--json", "status,conclusion"], repo))
    if view.get("status") != "completed" or view.get("conclusion") != "success":
        print(f"rerun-ci: {WORKFLOW} run {run_id} is {view.get('status')}/"
              f"{view.get('conclusion')}; not re-running ci", file=out)
        return 1

    def api(path):
        return release_evidence.decode_pages(gh(["api", "--paginate", path], repo), path)

    try:
        ok, lines = release_evidence.external_evidence(api, nwo, sha, default_branch,
                                                       "https://github.com")
    except release_evidence.ApiError as error:
        print(f"rerun-ci: could not read the status back: {error}; not re-running ci",
              file=out)
        return 1
    for line in lines:
        print(line, file=out)
    if not ok:
        print("rerun-ci: the plan job would not accept this status; not re-running ci",
              file=out)
        return 1

    pages = api(f"repos/{nwo}/actions/workflows/ci.yml/runs?head_sha={sha}&per_page=100")
    runs = [r for page in pages for r in page.get("workflow_runs", [])
            if r.get("event") in CI_EVENTS
            and (r.get("repository") or {}).get("full_name") == nwo
            and (r.get("head_repository") or {}).get("full_name") == nwo]
    newest = {}
    for r in runs:
        if r["event"] not in newest or r["id"] > newest[r["event"]]["id"]:
            newest[r["event"]] = r
    if not newest:
        print(f"rerun-ci: no ci.yml pull request run of this repository on {sha} yet; "
              "a pull request opened or pushed at it takes the evidence tier by itself",
              file=out)
        return 0
    for event in CI_EVENTS:
        r = newest.get(event)
        if r is None:
            continue
        rid = str(r["id"])
        if r.get("status") != "completed":
            gh(["run", "cancel", rid], repo)
            print(f"rerun-ci: cancelled ci.yml run {rid} ({event}, {r.get('status')})", file=out)
            settle = clock() + SETTLE_TIMEOUT
            while json.loads(gh(["run", "view", rid, "--json", "status"], repo)).get(
                    "status") != "completed":
                if clock() > settle:
                    print(f"rerun-ci: run {rid} did not finish cancelling within "
                          f"{SETTLE_TIMEOUT}s; re-run it by hand", file=out)
                    return 1
                sleep(POLL)
        gh(["run", "rerun", rid], repo)
        print(f"rerun-ci: re-running ci.yml run {rid} ({event}); its plan reads the status",
              file=out)
    return 0


def rerun_selftest():
    """--rerun-ci against a stub gh: which calls it makes, in which order."""
    import io
    nwo, sha = "o/r", "a" * 40
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    stamp = "2026-09-25T12:00:05Z"
    good_status = {"context": "gates/maintainer", "state": "success", "id": 1,
                   "created_at": "2026-09-25T12:00:30Z",
                   "creator": {"login": "github-actions[bot]"},
                   "target_url": f"https://github.com/{nwo}/actions/runs/7"}
    verify_run = {"repository": {"full_name": nwo},
                  "path": ".github/workflows/verify-external.yml",
                  "event": "workflow_dispatch", "head_branch": "main",
                  "status": "completed", "conclusion": "success",
                  "run_started_at": "2026-09-25T12:00:06Z",
                  "updated_at": "2026-09-25T12:01:00Z"}
    own = {"repository": {"full_name": nwo}, "head_repository": {"full_name": nwo}}
    fork = {"repository": {"full_name": nwo}, "head_repository": {"full_name": "f/r"}}

    def stub(conclusion="success", statuses=(good_status,), ci_runs=(), settle_after=1):
        calls, views = [], {"n": 0}

        def gh(args, cwd):
            calls.append(args)
            head = args[:2]
            if head == ["repo", "view"]:
                return json.dumps({"nameWithOwner": nwo,
                                   "defaultBranchRef": {"name": "main"}})
            if head == ["run", "list"]:
                return json.dumps([{"databaseId": 7, "createdAt": stamp,
                                    "status": "in_progress", "conclusion": ""}])
            if head == ["run", "watch"]:
                if conclusion != "success":
                    raise Refused("gh run watch: the run failed")
                return ""
            if head == ["run", "view"] and args[2] == "7":
                return json.dumps({"status": "completed", "conclusion": conclusion})
            if head == ["run", "view"]:
                views["n"] += 1
                done = views["n"] > settle_after
                return json.dumps({"status": "completed" if done else "in_progress"})
            if head in (["run", "cancel"], ["run", "rerun"]):
                return ""
            if args[0] == "api":
                path = args[-1]
                if path.startswith(f"repos/{nwo}/commits/{sha}/statuses"):
                    return json.dumps(list(statuses))
                if path.startswith(f"repos/{nwo}/actions/runs/7"):
                    return json.dumps(verify_run)
                if path.startswith(f"repos/{nwo}/actions/workflows/ci.yml/runs"):
                    return json.dumps({"workflow_runs": list(ci_runs)})
            raise Refused(f"stub gh: unexpected call {args}")
        return gh, calls

    def verbs(calls):
        return [" ".join(c[:3]) for c in calls if c[:2] in (["run", "cancel"], ["run", "rerun"])]

    cases = [
        # (label, stub kwargs, want exit, want cancel/rerun calls, needle)
        ("verify failed: nothing re-run", dict(conclusion="failure"), 1, [],
         "not re-running ci"),
        ("verify green, a person's status: nothing re-run",
         dict(statuses=[dict(good_status, creator={"login": "someone"})]), 1, [],
         "refused: written by someone"),
        ("verify green, no ci run: a hint only", dict(), 0, [], "no ci.yml pull request run"),
        ("verify green, ci running: cancel, then re-run",
         dict(ci_runs=[dict(own, id=50, event="pull_request", status="in_progress")]), 0,
         ["run cancel 50", "run rerun 50"], "cancelled ci.yml run 50"),
        ("verify green, ci finished: re-run the newest pull request run only",
         dict(ci_runs=[dict(own, id=40, event="pull_request", status="completed"),
                       dict(own, id=41, event="pull_request", status="completed"),
                       dict(fork, id=60, event="pull_request", status="completed"),
                       dict(own, id=45, event="push", status="completed")]), 0,
         ["run rerun 41"], "re-running ci.yml run 41"),
        ("verify green, only a push run: a hint only",
         dict(ci_runs=[dict(own, id=45, event="push", status="in_progress")]), 0, [],
         "no ci.yml pull request run"),
    ]
    failures = []
    for label, kwargs, want, want_calls, needle in cases:
        gh, calls = stub(**kwargs)
        buf = io.StringIO()
        ticks = iter(range(0, 10_000, 1))
        got = rerun_ci(Path("."), sha, now, gh=gh, sleep=lambda _s: None,
                       clock=lambda: next(ticks), out=buf)
        problems = []
        if got != want:
            problems.append(f"exit {got}, want {want}")
        if verbs(calls) != want_calls:
            problems.append(f"cancel/rerun calls {verbs(calls)}, want {want_calls}")
        if needle not in buf.getvalue():
            problems.append(f"output lacks {needle!r}: {buf.getvalue()!r}")
        if problems:
            failures.append(f"{label}: " + "; ".join(problems))
        else:
            print(f"  rerun-ci {label}")
    # The order matters in the running case: a re-run of a run still going
    # is refused by GitHub, so the cancel must have settled first.
    gh, calls = stub(ci_runs=[dict(own, id=50, event="pull_request", status="in_progress")],
                     settle_after=2)
    rerun_ci(Path("."), sha, now, gh=gh, sleep=lambda _s: None,
             clock=iter(range(10_000)).__next__, out=io.StringIO())
    order = [" ".join(c[:3]) for c in calls if c[:2] in (["run", "cancel"], ["run", "rerun"])
             or (c[:2] == ["run", "view"] and c[2] == "50")]
    if order != ["run cancel 50", "run view 50", "run view 50", "run view 50", "run rerun 50"]:
        failures.append(f"cancel, settle, re-run out of order: {order}")
    else:
        print("  rerun-ci waits for the cancel to settle before re-running")
    return failures


# ------------------------------------------------------------------ self-test

def selftest():
    failures = []
    shown = 0
    with tempfile.TemporaryDirectory() as tmp:
        repo, (sha, _sibling, _other) = verify_note.fixture_repo(tmp)
        env = verify_note._isolated_env()
        bare = Path(tmp) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env=env)
        key = verify_note.make_key(tmp, "throwaway-signer")
        stranger = verify_note.make_key(tmp, "throwaway-stranger")
        allowed = verify_note.allowed_signers_for(key, Path(tmp) / "allowed_signers")
        good = verify_note.fixture_bundle(repo, sha)
        red = verify_note.fixture_bundle(repo, sha, exit_code=1)

        def refused(label, bundle, needle, signer=key, target=sha):
            nonlocal shown
            try:
                prepare(repo, target, bundle, signer, allowed, identities=set())
            except Refused as error:
                if needle in str(error):
                    shown += 1
                    print(f"  refused  {label}: "
                          + " / ".join(ln.strip() for ln in str(error).splitlines()[:2]))
                    return
                failures.append(f"{label}: refused for the wrong reason: {error}")
                return
            failures.append(f"not refused: {label}")

        refused("complete=false", red, "not complete")
        lied = dict(red, complete=True)
        refused("complete=false claiming true", lied, "invalid")
        refused("a bundle for another commit", good, "is for", target=_sibling)
        refused("signed with a key not in allowed_signers", good, "does not verify",
                signer=stranger)

        # Green: the same bundle, the right key, pushed to the bare repository.
        # The dispatch is never run here.
        try:
            got_sha, text = prepare(repo, sha, good, key, allowed, identities=set())
            publish(repo, got_sha, text, str(bare), push=True, dispatch=False, env=env)
            clone = Path(tmp) / "clone"
            subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True,
                           env=env, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "push", "-q", str(bare), "main"],
                           check=True, env=env, capture_output=True)
            subprocess.run(["git", "-C", str(clone), "fetch", "-q", "origin", "main",
                            f"{verify_note.NOTES_REF}:{verify_note.NOTES_REF}"],
                           check=True, env=env, capture_output=True)
            ok, lines = verify_note.verify_commit(clone, sha, allowed)
            if not ok:
                failures.append("the published note did not verify in a clone: "
                                + " | ".join(lines))
            else:
                shown += 1
                print("  green    complete bundle published to a bare repository "
                      "and verified in a fresh clone")
        except Refused as error:
            failures.append(f"the complete bundle was refused: {error}")

    rerun_failures = rerun_selftest()
    shown += 7 - len(rerun_failures)
    failures += rerun_failures
    for line in failures:
        print(f"FAIL publish selftest: {line}", file=sys.stderr)
    if failures:
        return 1
    print(f"OK: publish selftest, {shown} cases")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sha", nargs="?")
    parser.add_argument("--bundle")
    parser.add_argument("--key", default=str(DEFAULT_KEY))
    parser.add_argument("--repo", default=str(HERE.parents[1]))
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--allowed-signers", default=str(verify_note.ALLOWED_SIGNERS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dry-run-dispatch", action="store_true")
    parser.add_argument("--rerun-ci", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--selftest-rerun-ci", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.selftest_rerun_ci:
        failures = rerun_selftest()
        for line in failures:
            print(f"FAIL publish --rerun-ci selftest: {line}", file=sys.stderr)
        if failures:
            return 1
        print("OK: publish --rerun-ci selftest, 7 cases")
        return 0
    if not args.sha or not args.bundle:
        parser.error("a sha and --bundle are required")
    dispatch = not (args.dry_run or args.dry_run_dispatch)
    if args.rerun_ci and not dispatch:
        parser.error("--rerun-ci waits for the dispatch, so it needs one (drop --dry-run*)")
    if dispatch and args.remote != "origin":
        print("publish: refusing to dispatch after pushing somewhere other than origin; "
              "add --dry-run-dispatch", file=sys.stderr)
        return 2
    try:
        bundle = json.loads(Path(args.bundle).read_text())
        sha, text = prepare(args.repo, args.sha, bundle, Path(args.key).expanduser(),
                            args.allowed_signers)
        dispatched_at = datetime.now(timezone.utc)
        publish(args.repo, sha, text, args.remote, push=not args.dry_run, dispatch=dispatch)
        if args.rerun_ci:
            return rerun_ci(args.repo, sha, dispatched_at)
    except Refused as error:
        print(f"publish: refused: {error}", file=sys.stderr)
        return 1
    except verify_note.EnvelopeError as error:
        print(f"publish: signing failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
