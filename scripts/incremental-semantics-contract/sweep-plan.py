#!/usr/bin/env python3
"""The Python side of sweep.sh: derive the contract invocations from gates.yml.

Local tooling only. Nothing in CI reads this file, and gates.yml does not know
it exists.

The invocation list is parsed out of .github/workflows/gates.yml on every run
rather than written down here, so a harness added to one of the incremental
jobs is swept without anyone remembering to edit a second list. A list that has
to be kept by hand is the failure this whole script exists to avoid: harness
mutation anchors are literal source strings, they drift silently, and a sweep
that quietly runs a subset is worth less than no sweep at all.

The order is longest-first, because the sweep is tail-bound: at eight-way
parallelism the four slowest harnesses run 810s, 665s, 625s and 623s, so one of
them starting late is the whole wall clock. Durations come from the previous
sweep's log where there is one, and otherwise from the static table below.

Modes:
  (default)        one TAB-separated `name<TAB>command` line per deduplicated
                   invocation, longest hint first.
  --jobs           the incremental job names, one per line.
  --raw-count      the pre-deduplication invocation count.
  --default-log    the log path sweep.sh writes, and the fallback hint source.
  --hints PATH     prefer this log as the duration hints (with any mode).
  --show-hints     the plan as `seconds<TAB>name<TAB>command`, after a
                   comment line naming which hint source was used.
  --self-test      parse checks; sweep.sh --self-test additionally compares
                   these numbers against a plain grep of the same file. The
                   checks are over the set and the count, never the order: the
                   order is a scheduling hint and is allowed to move.
  --anchor-report  read a failed harness's output, print the mutation anchor it
                   was looking for and where that literal lives in its source.
"""

import argparse
import ast
import os
import re
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GATES = ROOT / ".github/workflows/gates.yml"

# A job whose name starts with this is part of the incremental-semantics
# contract family. That is the same prefix the plain-grep cross-check in
# sweep.sh uses, and the two are compared against each other by --self-test.
JOB_PREFIX = "incremental"

JOB_HEADER = re.compile(r"^  (" + JOB_PREFIX + r"[-a-z0-9]*):$", re.M)
COMMAND_LINE = re.compile(
    r"^ +(run: )?(python3 scripts/incremental-semantics-contract/"
    r"|\./bin/dawn test scripts/incremental-semantics-contract)",
    re.M,
)

# Every invocation must look like one of these. The guard matters because the
# plan splits a block scalar on newlines: a `run:` step that used a shell
# continuation, a pipeline or `&&` would be silently torn into fragments, and
# the fragments would still look like a plausible plan.
COMMAND_PREFIXES = ("python3 scripts/incremental-semantics-contract/", "./bin/dawn ")

# A sweep log line: status, name, seconds.
LOG_LINE = re.compile(r"^(?:PASS|FAIL)\s+(\S+)\s+([0-9]+(?:\.[0-9]+)?)s\s*$", re.M)

# The ten slowest harnesses of the 8-way run of 2026-09-13, in seconds under
# that run's own contention. Used only until a real sweep log exists at the
# default path, which is the first run on a machine. Everything absent from
# this table is "not one of the long ones", which is what silence means in a
# table that is deliberately only the tail; silence in a real log means
# something else and is handled differently in hints() below.
STATIC_HINTS = {
    "prefix": 811,
    "local-value-reads": 665,
    "diagnostic-reads-shards-3-shard-0": 625,
    "diagnostic-reads-shards-3-shard-2": 623,
    "type-reads": 592,
    "diagnostic-reads-shards-3-shard-1": 561,
    "body-probe-typed-typed-all": 555,
    "function-reads": 467,
    "java-oracle-reads": 434,
    "java-member-reads": 393,
}


def default_log():
    """Where sweep.sh writes, and where hints are read from by default.

    Spelled here rather than in sweep.sh so the two cannot drift apart; sweep.sh
    asks for it with --default-log.
    """
    return Path(os.environ.get("TMPDIR", "/tmp")) / "dawn-incremental-sweep/sweep.log"


def hints(explicit=None):
    """Duration hints and how complete they are, as (dict, census).

    census is True when the hints came from a sweep log, which lists every
    harness that ran, so a name missing from it is genuinely new. It is False
    for the static table, where a missing name only means "not one of the ten
    longest". That distinction is what unknown names are scheduled by.
    """
    for candidate in (explicit, default_log()):
        if candidate is None:
            continue
        path = Path(candidate)
        if not path.is_file():
            continue
        found = {
            name: float(seconds) for name, seconds in LOG_LINE.findall(path.read_text())
        }
        if found:
            return found, True
    return dict(STATIC_HINTS), False


def unknown_hint(table, census):
    """What to assume about a harness the hints do not mention.

    From a real log, an absent name is one nobody has run yet and could be the
    next tail, so it is scheduled at the median and starts mid-pack rather than
    last. From the static table, an absent name is one the table says is not
    long, so it goes after the ten that are.
    """
    if census and table:
        return statistics.median(table.values())
    return 0.0


def load_jobs():
    """The incremental jobs from gates.yml, in file order, as (name, job)."""
    document = yaml.safe_load(GATES.read_text())
    return [
        (name, job)
        for name, job in document["jobs"].items()
        if name.startswith(JOB_PREFIX)
    ]


def invocations():
    """Every `run:` command line in those jobs, pre-deduplication.

    Returns (job_name, command) pairs in the order gates.yml lists them.
    """
    found = []
    for job_name, job in load_jobs():
        for step in job.get("steps") or []:
            run = step.get("run")
            if not run:
                continue
            for line in run.splitlines():
                command = line.strip()
                if not command:
                    continue
                if not command.startswith(COMMAND_PREFIXES):
                    raise SystemExit(
                        f"sweep-plan: {job_name} step {step.get('name')!r} has a "
                        f"command this parser cannot split safely: {command!r}"
                    )
                if command.endswith("\\") or "&&" in command or "|" in command:
                    raise SystemExit(
                        f"sweep-plan: {job_name} step {step.get('name')!r} is a "
                        f"compound command, not one invocation: {command!r}"
                    )
                found.append((job_name, command))
    return found


def is_path_like(token):
    return "/" in token or "$" in token


def name_for(command):
    """A filesystem-safe name for an invocation.

    The script's stem plus the flags that distinguish two invocations of the
    same script. Path and variable arguments are dropped along with the flag
    that introduced them: they are the same for every harness and only make the
    names longer.
    """
    tokens = command.split()
    if tokens[0] == "python3":
        tokens = tokens[1:]
    parts = [Path(tokens[0]).stem]
    rest = tokens[1:]
    index = 0
    while index < len(rest):
        token = rest[index]
        if token.startswith("-") and index + 1 < len(rest) and is_path_like(rest[index + 1]):
            index += 2
            continue
        if not is_path_like(token):
            parts.append(token.lstrip("-"))
        index += 1
    name = "-".join(parts)
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")


def deduplicated():
    """The invocation set, in gates.yml order, as (name, command, [job, ...])."""
    order = []
    by_command = {}
    for job_name, command in invocations():
        if command not in by_command:
            by_command[command] = []
            order.append(command)
        by_command[command].append(job_name)
    entries = [(name_for(command), command, by_command[command]) for command in order]
    names = [name for name, _, _ in entries]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise SystemExit(f"sweep-plan: two invocations share a name: {duplicates}")
    return entries


def plan(explicit_hints=None):
    """The invocation set again, longest hint first, as (name, command, hint).

    Ties keep gates.yml order, so the plan is stable and a machine with no
    hints at all still produces the list it always produced.
    """
    entries = deduplicated()
    table, census = hints(explicit_hints)
    fallback = unknown_hint(table, census)
    scored = [
        (index, name, command, table.get(name, fallback))
        for index, (name, command, _) in enumerate(entries)
    ]
    scored.sort(key=lambda item: (-item[3], item[0]))
    return [(name, command, hint) for _, name, command, hint in scored]


def script_for(command):
    """The harness source file an invocation runs, if it is a Python harness."""
    for token in command.split():
        if token.endswith(".py"):
            return ROOT / token
    return None


def anchor_report(name, output_path):
    """Explain a mutation-anchor drift without making the fixer dig for it.

    Harnesses raise `RuntimeError("<something> anchor drifted: <repr>")` from
    their own edit() helper, so the anchor is in the failure output as a Python
    repr. Print it, and point at the line of the harness source that spells it,
    which is the line that has to be re-fitted to the moved subject.
    """
    text = Path(output_path).read_text(errors="replace")
    raw_matches = re.findall(r"^.*anchor drifted: (.*)$", text, re.M)
    # The traceback quotes the `raise` line itself, so the f-string source
    # matches this pattern too. Only a real repr survives literal_eval.
    anchors = []
    for raw in raw_matches:
        try:
            value = ast.literal_eval(raw.strip())
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, str):
            anchors.append((raw.strip(), value))
    if not anchors:
        return False
    print(f"  {name}: mutation anchor drifted")
    entry = next((item for item in deduplicated() if item[0] == name), None)
    source = script_for(entry[1]) if entry else None
    for anchor, value in anchors:
        print(f"    looking for: {anchor}")
        if source is None or not source.exists():
            continue
        needle = value.split("\n")[0]
        if not needle:
            continue
        for number, line in enumerate(source.read_text().splitlines(), 1):
            if needle in line:
                print(f"    {source.relative_to(ROOT)}:{number}: {line.strip()}")
                break
        else:
            print(f"    not found in {source.relative_to(ROOT)}")
    return True


def self_test():
    text = GATES.read_text()
    failures = []

    parsed_jobs = [name for name, _ in load_jobs()]
    grepped_jobs = JOB_HEADER.findall(text)
    if parsed_jobs != grepped_jobs:
        failures.append(f"jobs: parser {parsed_jobs} vs header scan {grepped_jobs}")
    if not parsed_jobs:
        failures.append("jobs: the parser found none")

    raw = invocations()
    grepped = len(COMMAND_LINE.findall(text))
    if len(raw) != grepped:
        failures.append(f"invocations: parser {len(raw)} vs line scan {grepped}")

    entries = deduplicated()
    if len(entries) > len(raw):
        failures.append("dedup produced more entries than it was given")
    for _, command, _ in entries:
        source = script_for(command)
        if source is not None and not source.exists():
            failures.append(f"missing harness: {source}")

    covered = {job for _, _, jobs in entries for job in jobs}
    if covered != set(parsed_jobs):
        failures.append(f"jobs with no swept invocation: {sorted(set(parsed_jobs) - covered)}")

    # Ordering is a scheduling hint, so this asserts the set and the count and
    # deliberately says nothing about the order. A reordering that dropped or
    # duplicated an entry is the failure worth catching, under every hint
    # source there is.
    expected = sorted(name for name, _, _ in entries)
    for label, table in (("live", None), ("static", Path(os.devnull))):
        ordered = [name for name, _, _ in plan(table)]
        if sorted(ordered) != expected:
            failures.append(f"{label} hints changed the plan set, not just its order")
        if len(ordered) != len(entries):
            failures.append(f"{label} hints changed the plan length to {len(ordered)}")

    for line in failures:
        print(f"FAIL sweep-plan self-test: {line}", file=sys.stderr)
    if failures:
        return 1
    print(
        f"OK: sweep-plan self-test, {len(parsed_jobs)} jobs, "
        f"{len(raw)} invocations, {len(entries)} after dedup"
    )
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hints", help="a previous sweep log to take durations from")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--jobs", action="store_true", help="print the incremental job names")
    group.add_argument("--raw-count", action="store_true", help="print the pre-dedup count")
    group.add_argument("--default-log", action="store_true", help="print the default log path")
    group.add_argument("--show-hints", action="store_true", help="print the plan with hints")
    group.add_argument("--self-test", action="store_true", help="check the parser against a scan")
    group.add_argument(
        "--anchor-report",
        nargs=2,
        metavar=("NAME", "OUTPUT"),
        help="explain a mutation-anchor drift in a harness output file",
    )
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.jobs:
        for name, _ in load_jobs():
            print(name)
        return 0
    if args.raw_count:
        print(len(invocations()))
        return 0
    if args.default_log:
        print(default_log())
        return 0
    if args.anchor_report:
        return 0 if anchor_report(*args.anchor_report) else 1
    if args.show_hints:
        table, census = hints(args.hints)
        source = "a sweep log" if census else "the static table"
        print(f"# hints from {source}")
        for name, command, hint in plan(args.hints):
            print(f"{hint:.1f}\t{name}\t{command}")
        return 0
    for name, command, _ in plan(args.hints):
        print(f"{name}\t{command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
