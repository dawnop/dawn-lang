#!/usr/bin/env python3
"""Hold the run steps of gates.yml to a checked-in expectation, per job family.

Why this exists (issue #167): gates.yml's jobs get split into shards and
merged back as the queue arithmetic moves (its header has the history), and
every such batch claims "no gate was dropped". Nothing checked that claim.
check-gate-budgets.py reads budget lines and timeouts only, and the external
runner's multiset check (bundle.py) compares what ran against gates.yml at
the same commit, so it cannot see gates.yml itself losing a step. Deleting
one `run:` from one shard kept every gate green.

A check that compares gates.yml with itself can never catch that, so the
expectation is a file in the tree, steps.lock.json next to this script. It
records, for each job family, the multiset of `run:` texts its jobs carry.
`check` compares the current gates.yml with it and names every command that
is missing or extra; `record` rewrites it. So removing a step is still
possible, it just has to be said: the same commit must re-record the lock,
and the lock's diff is where a reviewer sees which command went.

What a family is: a job id with one trailing `-<digits>` removed, so
`contracts-1` and `contracts-2` are the family `contracts`, `incremental-7-1`
and `incremental-7-2` are `incremental-7`, and `incremental-1`..`incremental-8`
are `incremental`. Within a family a command may move freely between jobs,
which is what a reshard does; across families it may not, because that is no
longer a reshard. A job without a numeric suffix is a family of one.

The same multiset, per job rather than per family, is also a job's identity
for the nightly budget audit (issue #244). `job_digests` hashes each job's
`run:` texts, sorted, so that scripts/gate-observations.py can record which
steps a run's job carried at that run's commit and
scripts/check-gate-budgets.py --observed can hold a budget line only to runs
of the steps the line is about. It lives here, and not in either of those,
so that "the same steps" means one thing in the repository: a job whose
digest changed is a job whose lock entry changed. The digest is of the run
texts only, as the lock is; a `uses:` or `with:` change alone keeps it.

What it does not re-implement: the parsing. The jobs and their run steps come
from gatesplan.parse, the same reader the external runner plans with, so a
gates.yml that reader refuses (an unmodelled construct, or a toolchain
composite that no longer matches its substitution) is refused here too. That
is deliberate: it is the moment the external runner could no longer run the
gate set either, and a push is the cheapest place to learn it. The `plan` job
is not in the lock for the reason gatesplan does not plan it: it gates
nothing about the tree.

Modes (paths default to this repository's working tree):

    steps_lock.py check      exit 1 and name each difference, 0 when equal
    steps_lock.py record     rewrite steps.lock.json from the current gates.yml
    steps_lock.py selftest   remove one command, add one to the lock, move one
                             across families, require each to be red
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import gatesplan

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOCK = HERE / "steps.lock.json"
SHARD_SUFFIX = re.compile(r"-\d+$")


def family(job_id):
    return SHARD_SUFFIX.sub("", job_id)


def job_steps(gates_text, action_text):
    """{job id: Counter of run texts} from one gates.yml."""
    out = {}
    for job_id, command in gatesplan.run_commands(gatesplan.parse(gates_text, action_text)):
        out.setdefault(job_id, Counter())[command] += 1
    return out


def families_of(gates_text, action_text):
    """{family: Counter of run texts} from one gates.yml."""
    out = {}
    for job_id, commands in job_steps(gates_text, action_text).items():
        out.setdefault(family(job_id), Counter()).update(commands)
    return out


def steps_digest(commands):
    """16 hex digits of sha256 over the sorted run texts of one job.

    Sorted because the lock is a multiset: moving a step within a job is not
    a new shape. JSON because a run text can hold any character, so plain
    joining could make two different lists spell the same bytes.
    """
    body = json.dumps(sorted(Counter(commands).elements()), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def job_digests(gates_text, action_text):
    """{job id: steps digest} for every job gatesplan models (not `plan`)."""
    return {job_id: steps_digest(commands)
            for job_id, commands in job_steps(gates_text, action_text).items()}


def current():
    gates = (ROOT / gatesplan.GATES_PATH).read_text(encoding="utf-8")
    action = (ROOT / gatesplan.TOOLCHAIN_PATH).read_text(encoding="utf-8")
    return families_of(gates, action)


def current_job_digests():
    """job_digests of this working tree's gates.yml."""
    return job_digests((ROOT / gatesplan.GATES_PATH).read_text(encoding="utf-8"),
                       (ROOT / gatesplan.TOOLCHAIN_PATH).read_text(encoding="utf-8"))


def to_lock(families):
    return {
        "note": "Written by steps_lock.py record. Re-record in the commit that "
                "removes, adds or moves a gates.yml run step across families, "
                "and say why in that commit.",
        "families": {name: sorted(commands.elements())
                     for name, commands in sorted(families.items())},
    }


def from_lock(doc):
    return {name: Counter(commands) for name, commands in doc["families"].items()}


def shown(command):
    lines = command.strip().splitlines()
    more = f" (+{len(lines) - 1} lines)" if len(lines) > 1 else ""
    return f"`{lines[0].strip()}`{more}"


def differences(locked, now):
    """One line per missing or extra command, per family."""
    out = []
    for name in sorted(set(locked) | set(now)):
        want, have = locked.get(name, Counter()), now.get(name, Counter())
        for command, n in sorted((want - have).items()):
            out.append(f"{name}: missing {n}x {shown(command)} "
                       f"(in the lock, not in gates.yml)")
        for command, n in sorted((have - want).items()):
            out.append(f"{name}: extra {n}x {shown(command)} "
                       f"(in gates.yml, not in the lock)")
    return out


def check():
    try:
        now = current()
    except gatesplan.PlanError as error:
        print(f"FAIL steps lock: gatesplan cannot read gates.yml: {error}", file=sys.stderr)
        return 1
    locked = from_lock(json.loads(LOCK.read_text(encoding="utf-8")))
    diff = differences(locked, now)
    for line in diff:
        print(f"FAIL steps lock: {line}", file=sys.stderr)
    if diff:
        print("A run step was removed, added or moved to another family. If that is "
              "intended, run `python3 scripts/gates-external/steps_lock.py record` and "
              "commit the lock with the change, saying why.", file=sys.stderr)
        return 1
    total = sum(sum(c.values()) for c in now.values())
    print(f"OK: steps lock, {total} run steps in {len(now)} families match")
    return 0


def record():
    LOCK.write_text(json.dumps(to_lock(current()), indent=1) + "\n", encoding="utf-8")
    print(f"wrote {LOCK.relative_to(ROOT)}")
    return 0


def selftest():
    gates = (ROOT / gatesplan.GATES_PATH).read_text(encoding="utf-8")
    action = (ROOT / gatesplan.TOOLCHAIN_PATH).read_text(encoding="utf-8")
    steps = job_steps(gates, action)
    now = {}
    for job_id, commands in steps.items():
        now.setdefault(family(job_id), Counter()).update(commands)
    locked = from_lock(to_lock(now))
    failures = []
    if differences(locked, now):
        failures.append("the lock recorded from gates.yml does not match gates.yml")
    fam = next(name for name in sorted(now) if len(now[name]) > 1)
    victim = sorted(now[fam])[0]

    dropped = {k: Counter(v) for k, v in now.items()}
    dropped[fam][victim] -= 1
    dropped[fam] = +dropped[fam]
    got = differences(locked, dropped)
    if not any("missing" in line and shown(victim) in line for line in got):
        failures.append(f"a removed step was not named: {got}")

    padded = {k: Counter(v) for k, v in locked.items()}
    padded[fam]["echo a step that is not in gates.yml"] += 1
    got = differences(padded, now)
    if not any("missing" in line and "echo a step" in line for line in got):
        failures.append(f"a step only in the lock was not named: {got}")

    other = next(name for name in sorted(now) if name != fam)
    moved = {k: Counter(v) for k, v in now.items()}
    moved[fam][victim] -= 1
    moved[fam] = +moved[fam]
    moved[other][victim] += 1
    got = differences(locked, moved)
    if len(got) != 2:
        failures.append(f"a step moved across families was not both missing and extra: {got}")

    if family("incremental-7-2") != "incremental-7" or family("tree-policy") != "tree-policy":
        failures.append("the family rule changed")

    # The per-job digest the budget audit keys on (issue #244): a rename that
    # keeps the steps keeps the digest, and a changed run text changes it.
    digests = {job_id: steps_digest(commands) for job_id, commands in steps.items()}
    if len(set(digests.values())) != len(digests):
        failures.append("two jobs share a steps digest, so the audit cannot tell them apart")
    job = next(j for j in sorted(steps) if re.search(r"-\d+$", j)
               and any("--shard" in c for c in steps[j]))
    renamed = job_digests(re.sub(rf"\b{re.escape(job)}\b", "renamed-by-selftest", gates), action)
    if renamed.get("renamed-by-selftest") != digests[job] or job in renamed:
        failures.append(f"renaming {job} changed its steps digest")
    command = next(c for c in sorted(steps[job]) if "--shard" in c)
    line = command.strip().splitlines()[0]
    resharded = job_digests(gates.replace(line, line + " --selftest-extra", 1), action)
    if resharded.get(job) == digests[job]:
        failures.append(f"changing a run text of {job} kept its steps digest")
    if steps_digest(["b", "a"]) != steps_digest(["a", "b"]) or steps_digest(["a"]) == steps_digest(["a", "a"]):
        failures.append("the steps digest is not a digest of the multiset")
    for line in failures:
        print(f"FAIL steps lock self-test: {line}", file=sys.stderr)
    if failures:
        return 1
    print("OK: steps lock self-test, removed / lock-only / moved steps are each named;"
          " a rename keeps a job's steps digest and a changed run text does not")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["check", "record", "selftest"])
    args = parser.parse_args()
    return {"check": check, "record": record, "selftest": selftest}[args.mode]()


if __name__ == "__main__":
    sys.exit(main())
