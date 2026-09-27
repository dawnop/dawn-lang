#!/usr/bin/env python3
"""Build and verify the evidence bundle of an external gate run.

The bundle is what a maintainer can hand to someone else as "these gates ran
on this tree and this is what they said". Two properties make it worth
handing over, and this file is where both are enforced:

1. It says nothing about the machine. The schema is a whitelist: tree,
   gates_blob, substitutions, steps, toolchain, complete, and inside those
   only the fields listed in SCHEMA. Durations, core counts, memory, GPUs,
   host and user names, paths, image names and environment variables have no
   field to live in. A whitelist alone is not enough, because a whitelisted
   string can still carry a path, so every string value also passes a leak
   filter: a value containing `/`, a host-name shape, an IP shape, an `@`, or
   this machine's host or user name is refused and no file is written.

   Commands, step names and `uses:` references legitimately contain `/`
   (a script path, `actions/checkout@v4`). They are exempt only when the
   exact string occurs in gates.yml at the bundle's own tree, which is public
   text the verifier re-reads; a free-text value never gets the exemption.

2. `complete` cannot be argued with. It is recomputed from gates.yml at the
   tree, never trusted from the producer: the multiset of (job, run text)
   pairs of every run step must equal the multiset of executed steps, and
   every executed step must have exit code 0. A missing step, an extra step,
   an unexecuted step and a non-zero step each make it false. Skipping is not
   success. The comparison is a multiset because the same command may
   legitimately appear more than once (until 2026-09-27 diagnostic-reads.py
   --self-test ran in three jobs).

Modes:
  bundle.py --selftest                  every refusal, proved one by one
  bundle.py verify BUNDLE [--repo DIR]  schema, leaks, blob and complete,
                                        recomputed from git; exit 0 only when
                                        the bundle is valid AND complete
"""

import argparse
import collections
import copy
import getpass
import hashlib
import json
import re
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gatesplan  # noqa: E402

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

# Every field the bundle may carry. Anything else, at any depth, is refused.
TOP_FIELDS = {"tree", "gates_blob", "substitutions", "steps", "toolchain", "complete"}
SUBSTITUTION_FIELDS = {"subject", "replacement"}
STEP_FIELDS = {"job", "name", "command", "exit_code", "stdout_sha256",
               "stderr_sha256", "executed"}
TOOLCHAIN_FIELDS = {"seed_jar_sha256", "java", "cc", "python", "node"}

REPLACEMENTS = ({r for r, _ in gatesplan.SUBSTITUTIONS.values()}
                | set(gatesplan.ADJUSTMENTS.values()) | {gatesplan.PLAN_REPLACEMENT})
ADJUSTMENT_SUBJECTS = set(gatesplan.ADJUSTMENTS) | {gatesplan.PLAN_JOB}

# Leak shapes for free text. A host name is dotted labels ending in letters
# (`build-7.corp.example`); version strings end in digits and pass. An IPv4
# address is four dotted numbers; IPv6 is hex groups joined by colons.
HOST_SHAPE = re.compile(
    r"(?i)\b[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}\b")
IPV4_SHAPE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
IPV6_SHAPE = re.compile(r"(?i)\b[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,}\b")
FREE_TEXT_MAX = 200


class BundleError(Exception):
    """The bundle would leak or break the schema; nothing is written."""


def local_identities():
    """This machine's host and user names, refused wherever they appear."""
    names = set()
    for probe in (socket.gethostname, socket.getfqdn, getpass.getuser):
        try:
            value = probe()
        except Exception:
            continue
        if value and len(value) >= 3:
            names.add(value.lower())
            names.add(value.split(".")[0].lower())
    return {n for n in names if len(n) >= 3}


def leak_reason(value, identities):
    """Why a free-text value may not leave the machine, or None."""
    if "/" in value or "\\" in value:
        return "contains a path separator"
    if "@" in value:
        return "contains an address shape"
    if IPV4_SHAPE.search(value):
        return "contains an IPv4 shape"
    if IPV6_SHAPE.search(value):
        return "contains an IPv6 shape"
    if HOST_SHAPE.search(value):
        return "contains a host-name shape"
    lowered = value.lower()
    for name in identities:
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", lowered):
            return "contains this machine's host or user name"
    if len(value) > FREE_TEXT_MAX:
        return f"is longer than {FREE_TEXT_MAX} characters"
    if any(ord(c) < 32 for c in value):
        return "contains a control character"
    return None


def vocabulary(jobs):
    """Strings the bundle may repeat verbatim because gates.yml says them."""
    commands, names, job_ids, uses = set(), set(), set(), set()
    for job in jobs:
        job_ids.add(job["id"])
        for action in job["actions"]:
            if action["name"] is not None:
                names.add(action["name"])
            if action["kind"] == "run":
                commands.add(action["command"])
            else:
                uses.add(action["uses"])
    uses.add("actions/cache@v4")  # the composite's caches, see substitution_rows
    return {"command": commands, "name": names, "job": job_ids, "uses": uses}


def _string(where, value, allowed, identities, errors):
    """A string field: verbatim from gates.yml, or clean free text."""
    if not isinstance(value, str):
        errors.append(f"{where}: not a string")
        return
    if allowed is not None and value in allowed:
        return
    reason = leak_reason(value, identities)
    if reason:
        errors.append(f"{where}: value {value!r} {reason}")


def validate(bundle, jobs, identities=None):
    """Every schema and leak error in a bundle, as a list of strings."""
    identities = local_identities() if identities is None else identities
    vocab = vocabulary(jobs)
    errors = []
    if not isinstance(bundle, dict):
        return ["bundle: not an object"]
    for key in set(bundle) - TOP_FIELDS:
        errors.append(f"bundle: field {key!r} is not in the schema")
    for key in TOP_FIELDS - set(bundle):
        errors.append(f"bundle: field {key!r} is missing")
    for key in ("tree", "gates_blob"):
        if key in bundle and not (isinstance(bundle[key], str) and HEX40.match(bundle[key])):
            errors.append(f"{key}: not a 40-hex object name")
    if "complete" in bundle and not isinstance(bundle["complete"], bool):
        errors.append("complete: not a boolean")

    for i, row in enumerate(bundle.get("substitutions") or []):
        where = f"substitutions[{i}]"
        if not isinstance(row, dict):
            errors.append(f"{where}: not an object")
            continue
        for key in set(row) - SUBSTITUTION_FIELDS:
            errors.append(f"{where}: field {key!r} is not in the schema")
        subject = row.get("subject")
        if subject not in vocab["uses"] and subject not in ADJUSTMENT_SUBJECTS:
            _string(f"{where}.subject", subject, None, identities, errors)
            errors.append(f"{where}.subject: {subject!r} is neither a gates.yml "
                          f"reference nor a known adjustment")
        if row.get("replacement") not in REPLACEMENTS:
            _string(f"{where}.replacement", row.get("replacement"), None, identities, errors)
            errors.append(f"{where}.replacement: {row.get('replacement')!r} is not a "
                          f"known replacement id")
    if not isinstance(bundle.get("substitutions", []), list):
        errors.append("substitutions: not a list")

    steps = bundle.get("steps", [])
    if not isinstance(steps, list):
        errors.append("steps: not a list")
        steps = []
    for i, step in enumerate(steps):
        where = f"steps[{i}]"
        if not isinstance(step, dict):
            errors.append(f"{where}: not an object")
            continue
        for key in set(step) - STEP_FIELDS:
            errors.append(f"{where}: field {key!r} is not in the schema")
        for key in STEP_FIELDS - set(step):
            errors.append(f"{where}: field {key!r} is missing")
        _string(f"{where}.job", step.get("job"), vocab["job"], identities, errors)
        if step.get("name") is not None:
            _string(f"{where}.name", step.get("name"), vocab["name"], identities, errors)
        _string(f"{where}.command", step.get("command"), vocab["command"], identities, errors)
        executed = step.get("executed")
        if not isinstance(executed, bool):
            errors.append(f"{where}.executed: not a boolean")
        code = step.get("exit_code")
        if executed:
            if not isinstance(code, int) or isinstance(code, bool):
                errors.append(f"{where}.exit_code: an executed step needs an integer")
            for key in ("stdout_sha256", "stderr_sha256"):
                if not (isinstance(step.get(key), str) and HEX64.match(step[key])):
                    errors.append(f"{where}.{key}: an executed step needs a sha256")
        elif executed is False:
            for key in ("exit_code", "stdout_sha256", "stderr_sha256"):
                if step.get(key) is not None:
                    errors.append(f"{where}.{key}: must be null for an unexecuted step")

    toolchain = bundle.get("toolchain", {})
    if not isinstance(toolchain, dict):
        errors.append("toolchain: not an object")
        toolchain = {}
    for key in set(toolchain) - TOOLCHAIN_FIELDS:
        errors.append(f"toolchain: field {key!r} is not in the schema")
    for key in TOOLCHAIN_FIELDS - set(toolchain):
        errors.append(f"toolchain: field {key!r} is missing")
    seed = toolchain.get("seed_jar_sha256")
    if seed is not None and not (isinstance(seed, str) and HEX64.match(seed)):
        errors.append("toolchain.seed_jar_sha256: not a sha256")
    for key in ("java", "cc", "python", "node"):
        if toolchain.get(key) is not None:
            _string(f"toolchain.{key}", toolchain[key], None, identities, errors)
    return errors


def multiset_diff(expected_pairs, steps):
    """(missing, extra) as sorted lists of (job, command) pairs."""
    want = collections.Counter(expected_pairs)
    got = collections.Counter((s["job"], s["command"]) for s in steps if s.get("executed"))
    missing = sorted((want - got).elements())
    extra = sorted((got - want).elements())
    return missing, extra


def completeness(jobs, steps):
    """(complete, reasons). Recomputed, never read from a bundle."""
    reasons = []
    missing, extra = multiset_diff(gatesplan.run_commands(jobs), steps)
    for job, command in missing:
        reasons.append(f"not executed: {job}: {first_line(command)}")
    for job, command in extra:
        reasons.append(f"executed but not in gates.yml: {job}: {first_line(command)}")
    for step in steps:
        if step.get("executed") and step.get("exit_code") != 0:
            reasons.append(f"exit {step.get('exit_code')}: {step['job']}: "
                           f"{first_line(step['command'])}")
    return not reasons, reasons


def first_line(command):
    lines = [line for line in command.strip().splitlines() if line.strip()]
    suffix = f" (+{len(lines) - 1} lines)" if len(lines) > 1 else ""
    return (lines[0] if lines else "") + suffix


def build(plan, steps, toolchain, identities=None):
    """The bundle, or BundleError naming every refused field."""
    complete, _ = completeness(plan["jobs"], steps)
    bundle = {
        "tree": plan["tree"],
        "gates_blob": plan["gates_blob"],
        "substitutions": gatesplan.substitution_rows(plan["jobs"]),
        "steps": steps,
        "toolchain": toolchain,
        "complete": complete,
    }
    errors = validate(bundle, plan["jobs"], identities)
    if errors:
        raise BundleError("\n".join(errors))
    return bundle


def write(bundle, path):
    Path(path).write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(bundle, repo, identities=None):
    """Everything checkable about a bundle, recomputed from git at its tree.

    -> (plan or None, errors, complete, reasons). `errors` are reasons the
    bundle is invalid (schema, leaks, a blob or table that is not this tree's,
    a `complete` claim that recomputation contradicts); `complete` and
    `reasons` are the recomputed verdict and why it is false. This is the one
    implementation: `verify` below prints it, publish.py refuses on it, and
    verify_note.py runs it on GitHub after checking the signature.

    `identities` is the set of host and user names the leak filter refuses.
    The producer passes None (this machine's own); a verifier on another
    machine passes an empty set, because it cannot know the producer's names
    and its own would only make the check depend on where it runs. The shape
    rules (paths, host names, addresses) apply either way.
    """
    if not isinstance(bundle, dict):
        return None, ["bundle: not an object"], False, []
    try:
        plan = gatesplan.plan_at(repo, str(bundle.get("tree", "")))
    except gatesplan.PlanError as error:
        return None, [f"tree: {error}"], False, []
    errors = validate(bundle, plan["jobs"], identities)
    if bundle.get("gates_blob") != plan["gates_blob"]:
        errors.append(f"gates_blob: bundle says {bundle.get('gates_blob')}, "
                      f"the tree has {plan['gates_blob']}")
    want_subs = gatesplan.substitution_rows(plan["jobs"])
    if bundle.get("substitutions") != want_subs:
        errors.append("substitutions: not the table this tree's gates.yml produces")
    steps = bundle.get("steps")
    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
        errors.append("steps: not a list of objects, completeness not computed")
        return plan, errors, False, []
    complete, reasons = completeness(plan["jobs"], steps)
    if bundle.get("complete") != complete:
        errors.append(f"complete: bundle says {bundle.get('complete')}, recomputed {complete}")
    return plan, errors, complete, reasons


def verify(path, repo):
    """Re-derive everything checkable from git; print why it is not complete."""
    bundle = json.loads(Path(path).read_text())
    plan, errors, complete, reasons = check(bundle, repo)
    if plan is None:
        print(f"verify: {errors[0]}", file=sys.stderr)
        return 2
    for line in errors:
        print(f"INVALID {line}", file=sys.stderr)
    for line in reasons:
        print(f"INCOMPLETE {line}")
    if errors:
        return 2
    print(f"{'COMPLETE' if complete else 'NOT COMPLETE'}: tree {plan['tree']}, "
          f"{sum(1 for s in bundle['steps'] if s['executed'])} of "
          f"{len(gatesplan.run_commands(plan['jobs']))} run steps executed")
    return 0 if complete else 1


# ------------------------------------------------------------------ self-test

# A gates.yml small enough to read, with one command repeated across jobs and
# one multi-line block. verify_note.py commits it to a scratch repository for
# its own self-test, so it is a module constant rather than a local.
FIXTURE_GATES_YML = """
name: gates
on:
  workflow_call:
jobs:
  alpha:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - name: first contract
        run: ./scripts/first/run.sh
      - name: repeated self-test
        run: python3 scripts/shared.py --self-test
  beta:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - name: repeated self-test
        run: python3 scripts/shared.py --self-test
      - name: second contract
        run: |
          ./scripts/second/run.sh
          ./scripts/second/run.sh --more
"""


def _fixture_plan():
    jobs = gatesplan.parse(FIXTURE_GATES_YML)
    return {"tree": "1" * 40, "gates_blob": "2" * 40, "jobs": jobs}


def _fixture_steps(plan):
    return [{"job": job, "name": name, "command": command, "exit_code": 0,
             "stdout_sha256": "a" * 64, "stderr_sha256": "b" * 64, "executed": True}
            for job, name, command in (
                (j["id"], a["name"], a["command"])
                for j in plan["jobs"] for a in j["actions"] if a["kind"] == "run")]


TOOLCHAIN_OK = {"seed_jar_sha256": "c" * 64,
                "java": "21.0.2+13-jvmci-23.1-b30",
                "cc": "cc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0",
                "python": "3.12.3", "node": "v24.8.0"}


def selftest():
    identities = {"testhost-7", "builder"}
    plan = _fixture_plan()
    failures = []
    passed = 0

    def expect_refused(label, bundle_or_mutator, needle):
        nonlocal passed
        steps = _fixture_steps(plan)
        toolchain = dict(TOOLCHAIN_OK)
        base = build(plan, steps, toolchain, identities)
        mutated = copy.deepcopy(base)
        bundle_or_mutator(mutated)
        errors = validate(mutated, plan["jobs"], identities)
        if not any(needle in e for e in errors):
            failures.append(f"not refused: {label} (errors: {errors})")
        else:
            passed += 1
            print(f"  refused  {label}: {next(e for e in errors if needle in e)}")

    # 0. the clean bundle passes and is complete
    clean = build(plan, _fixture_steps(plan), dict(TOOLCHAIN_OK), identities)
    if not clean["complete"] or validate(clean, plan["jobs"], identities):
        failures.append("the clean fixture is not a valid complete bundle")
    else:
        print("  accepted clean fixture: complete=true")

    # 1. every forbidden field, one at a time, at the top and inside a step
    #    and the toolchain: the whitelist has no room for any of them.
    forbidden = ["duration", "duration_seconds", "nproc", "memory", "peak_memory",
                 "gpu", "hostname", "host", "user", "username", "path", "cwd",
                 "image", "env", "environment"]
    for name in forbidden:
        expect_refused(f"top-level {name}", lambda b, n=name: b.__setitem__(n, "x"),
                       f"field {name!r} is not in the schema")
        expect_refused(f"step {name}", lambda b, n=name: b["steps"][0].__setitem__(n, "x"),
                       f"field {name!r} is not in the schema")
        expect_refused(f"toolchain {name}", lambda b, n=name: b["toolchain"].__setitem__(n, "x"),
                       f"field {name!r} is not in the schema")
        expect_refused(f"substitution {name}",
                       lambda b, n=name: b["substitutions"][0].__setitem__(n, "x"),
                       f"field {name!r} is not in the schema")

    # 2. leaks through whitelisted free-text fields
    leaks = {
        "a path in toolchain.java": ("java", "/home/someone/tools/graalvm", "path separator"),
        "a relative path in toolchain.cc": ("cc", "bin/cc 13", "path separator"),
        "a host name in toolchain.cc": ("cc", "cc on build-7.corp.example", "host-name shape"),
        "an IPv4 address in toolchain.python": ("python", "3.12 10.0.0.12", "IPv4 shape"),
        "an IPv6 address in toolchain.node": ("node", "v24 fe80::1:2", "IPv6 shape"),
        "an email in toolchain.node": ("node", "v24 ops@corp", "address shape"),
        "this host's name in toolchain.cc": ("cc", "cc testhost-7 13.3", "host or user name"),
        "this user's name in toolchain.java": ("java", "21 builder edition", "host or user name"),
    }
    for label, (key, value, needle) in leaks.items():
        expect_refused(label, lambda b, k=key, v=value: b["toolchain"].__setitem__(k, v), needle)
    expect_refused("a path as a step command not in gates.yml",
                   lambda b: b["steps"][0].__setitem__("command", "/home/someone/run.sh"),
                   "path separator")
    expect_refused("a path as a step name not in gates.yml",
                   lambda b: b["steps"][0].__setitem__("name", "ran in /home/someone"),
                   "path separator")
    expect_refused("a machine path as a substitution subject",
                   lambda b: b["substitutions"][0].__setitem__("subject", "/opt/cache"),
                   "path separator")
    expect_refused("an unknown replacement id",
                   lambda b: b["substitutions"][0].__setitem__("replacement", "skipped"),
                   "not a known replacement id")
    expect_refused("a non-hex tree", lambda b: b.__setitem__("tree", "main"), "40-hex")
    expect_refused("an unexecuted step carrying an exit code",
                   lambda b: b["steps"][0].update(executed=False),
                   "must be null for an unexecuted step")

    # 3. the generator itself refuses, and writes nothing
    try:
        build(plan, _fixture_steps(plan), dict(TOOLCHAIN_OK, java="/usr/lib/jvm/21"), identities)
        failures.append("build() accepted a path in the toolchain")
    except BundleError as error:
        passed += 1
        print(f"  refused  build() with a path: {str(error).splitlines()[0]}")

    # 4. completeness: the multiset in both directions, and exit codes
    def complete_after(label, mutate, want_reason):
        nonlocal passed
        steps = _fixture_steps(plan)
        mutate(steps)
        ok, reasons = completeness(plan["jobs"], steps)
        bundle = build(plan, steps, dict(TOOLCHAIN_OK), identities)
        if ok or bundle["complete"] or not any(want_reason in r for r in reasons):
            failures.append(f"still complete: {label} ({reasons})")
        else:
            passed += 1
            print(f"  red      {label}: {next(r for r in reasons if want_reason in r)}")

    complete_after("one run step missing", lambda s: s.pop(1), "not executed: alpha")
    complete_after("one of two identical commands missing",
                   lambda s: s.pop(2), "not executed: beta: python3 scripts/shared.py")
    complete_after("one extra copy of a command",
                   lambda s: s.append(dict(s[0])), "executed but not in gates.yml: alpha")
    complete_after("a command moved to another job",
                   lambda s: s[0].__setitem__("job", "beta"), "not executed: alpha")
    complete_after("one step unexecuted",
                   lambda s: s[3].update(executed=False, exit_code=None,
                                         stdout_sha256=None, stderr_sha256=None),
                   "not executed: beta: ./scripts/second/run.sh (+1 lines)")
    complete_after("one step exited non-zero",
                   lambda s: s[0].__setitem__("exit_code", 3), "exit 3: alpha")
    complete_after("one step timed out", lambda s: s[2].__setitem__("exit_code", 124),
                   "exit 124: beta")

    # 5. `complete` in a bundle is never trusted
    lied = build(plan, [s for s in _fixture_steps(plan)][1:], dict(TOOLCHAIN_OK), identities)
    lied["complete"] = True
    recomputed, _ = completeness(plan["jobs"], lied["steps"])
    if recomputed:
        failures.append("a bundle's own complete=true survived recomputation")
    else:
        passed += 1
        print("  red      a bundle claiming complete=true with a step missing")

    for line in failures:
        print(f"FAIL bundle selftest: {line}", file=sys.stderr)
    if failures:
        return 1
    print(f"OK: bundle selftest, {passed} refusals and reds observed")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selftest", action="store_true")
    sub = parser.add_subparsers(dest="mode")
    v = sub.add_parser("verify")
    v.add_argument("bundle")
    v.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.mode == "verify":
        return verify(args.bundle, args.repo)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
