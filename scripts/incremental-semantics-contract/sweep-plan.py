#!/usr/bin/env python3
"""The Python side of sweep.sh: derive the contract invocations from gates.yml.

Local tooling only. Nothing in CI reads this file, and gates.yml does not know
it exists.

The invocation list is parsed out of .github/workflows/gates.yml on every run
rather than written down here, so a harness remains swept even when budget
balancing moves its command into an ordinary job. A list that has
to be kept by hand is the failure this whole script exists to avoid: harness
mutation anchors are literal source strings, they drift silently, and a sweep
that quietly runs a subset is worth less than no sweep at all.

The order is longest-first, because the sweep is tail-bound: at eight-way
parallelism the slowest harnesses run 665s, 625s, 623s and 592s, so one of them
starting late is the whole wall clock. Durations come from the previous sweep's
log where there is one, and otherwise from the static table below.

Modes:
  (default)        one TAB-separated `name<TAB>command` line per deduplicated
                   invocation, longest hint first.
  --jobs           the jobs containing swept contracts, one per line.
  --raw-count      the pre-deduplication invocation count.
  --default-log    the log path sweep.sh writes, and the fallback hint source.
  --hints PATH     prefer this log as the duration hints (with any mode).
  --show-hints     the plan as `seconds<TAB>name<TAB>command`, after a
                   comment line naming which hint source was used.
  --self-test      parse checks; sweep.sh --self-test additionally compares
                   these numbers against a line scan of the same file. The
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

# Dedicated jobs validate every command. Other jobs contribute relevant run
# steps, whose complete command blocks must also be supported. Unrelated setup
# steps stay outside the sweep; setup within a relevant block fails closed.
JOB_PREFIX = "incremental"
CONTRACT_PATH = "scripts/incremental-semantics-contract"

JOB_HEADER = re.compile(r"^  ([-a-zA-Z0-9_]+):$", re.M)
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

# The slowest harnesses of the 8-way run of 2026-09-13, in seconds under that
# run's own contention. Used only until a real sweep log exists at the default
# path, which is the first run on a machine. Everything absent from this table
# is "not one of the long ones", which is what silence means in a table that is
# deliberately only the tail; silence in a real log means something else and is
# handled differently in hints() below.
#
# It was that run's ten until 2026-09-13, when prefix.py's single 811s entry
# became its three shards. That 811s is not remeasured here: the run it came
# from no longer exists to be rerun, and prefix's subjects cost the same as
# each other (24.3 to 24.4s each, and 122.52s for the five-subject shard 0,
# measured alone on a 16 core machine at loadavg 3.5 to 4.9 on 2026-09-13), so
# the 811s divides by subject count: five thirteenths to shard 0, which keeps
# the positive subject, and four to each of the others. body-probe's typed
# entry left the table on 2026-09-27 with the replay engine it probed.
STATIC_HINTS = {
    "prefix-shards-3-shard-0": 312,
    "prefix-shards-3-shard-1": 250,
    "prefix-shards-3-shard-2": 250,
    "local-value-reads": 665,
    "diagnostic-reads-shards-3-shard-0": 625,
    "diagnostic-reads-shards-3-shard-2": 623,
    "type-reads": 592,
    "diagnostic-reads-shards-3-shard-1": 561,
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


def relevant(command):
    return not command.lstrip().startswith("#") and CONTRACT_PATH in command


def load_jobs(text=None):
    """Dedicated jobs and ordinary jobs containing contract commands."""
    document = yaml.safe_load(GATES.read_text() if text is None else text)
    return [
        (name, job)
        for name, job in document["jobs"].items()
        if name.startswith(JOB_PREFIX) or any(
            relevant(line)
            for step in job.get("steps") or []
            for line in (step.get("run") or "").splitlines()
        )
    ]


def invocations(text=None):
    """Every `run:` command line in those jobs, pre-deduplication.

    Returns (job_name, command) pairs in the order gates.yml lists them.
    """
    found = []
    for job_name, job in load_jobs(text):
        for step in job.get("steps") or []:
            run = step.get("run")
            if not run:
                continue
            dedicated = job_name.startswith(JOB_PREFIX)
            if not dedicated and not any(relevant(line) for line in run.splitlines()):
                continue
            # A preceding continuation or control structure changes the
            # meaning of an otherwise ordinary contract line. Refuse the
            # relevant block rather than discard its shell wrapper.
            for line in run.splitlines():
                command = line.strip()
                if not command or command.startswith("#"):
                    continue
                if (any(token in command for token in ("\\", ";", "&", "|", chr(96), "$(", "<", ">")) or
                        re.match(r"^(?:if|then|else|elif|fi|for|while|until|do|done|case|esac|function)\b", command) or
                        command in ("{", "}", "(", ")")):
                    raise SystemExit(
                        f"sweep-plan: {job_name} step {step.get('name')!r} has a "
                        f"compound command, not one invocation: {command!r}"
                    )
            for line in run.splitlines():
                command = line.strip()
                if not command or command.startswith("#"):
                    continue
                if not command.startswith(COMMAND_PREFIXES):
                    raise SystemExit(
                        f"sweep-plan: {job_name} step {step.get('name')!r} has a "
                        f"command this parser cannot split safely: {command!r}"
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


def scanned_jobs(text):
    """Independent line scan: job headers and non-comment contract references."""
    headers = list(JOB_HEADER.finditer(text))
    found = []
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[header.end():end]
        if header[1].startswith(JOB_PREFIX) or any(
                not line.lstrip().startswith("#") and CONTRACT_PATH in line
                for line in block.splitlines()):
            found.append(header[1])
    return found


def discovery_self_test():
    contract = "python3 scripts/incremental-semantics-contract/function-reads.py --suite observation"

    def fixture(job, run, extra_steps=None):
        return yaml.safe_dump({"jobs": {job: {"steps": (extra_steps or []) + [
            {"name": "contract", "run": run}]}}}, sort_keys=False)

    original = fixture("incremental-body", contract)
    relocated = fixture("ordinary-contract", "# contract invocation\n" + contract, [
        {"uses": "actions/checkout@v4"},
        {"run": "echo unrelated && echo setup"},
    ])
    assert invocations(original) == [("incremental-body", contract)]
    assert invocations(relocated) == [("ordinary-contract", contract)]
    assert [name for name, _ in load_jobs(relocated)] == ["ordinary-contract"]
    assert scanned_jobs(relocated) == ["ordinary-contract"]
    assert invocations(fixture("ordinary", "echo unrelated")) == []
    assert invocations(fixture("ordinary", "# " + contract)) == []
    mixed = yaml.safe_dump({"jobs": {
        "incremental-body": {"steps": [{"run": contract}]},
        "ordinary-contract": {"steps": [{"run": contract}]},
        "unrelated": {"steps": [{"run": "echo setup && echo done"}]},
    }}, sort_keys=False)
    assert invocations(mixed) == [
        ("incremental-body", contract), ("ordinary-contract", contract)]
    assert scanned_jobs(mixed) == ["incremental-body", "ordinary-contract"]
    dawn = "./bin/dawn test scripts/incremental-semantics-contract"
    assert invocations(fixture("ordinary", dawn)) == [("ordinary", dawn)]
    rejected = [
        "echo setup && " + contract, contract + " | tee result",
        contract + "; echo done", contract + " &", contract + " > result",
        "env FLAG=1 " + contract, "bash " + CONTRACT_PATH + "/probe.py",
        "echo setup\n" + contract,
        "cd other\n" + contract,
        "export MODE=changed\n" + contract,
        "echo setup \\\n" + contract,
        "if true; then\n" + contract + "\nfi",
        "(\n" + contract + "\n)",
    ]
    for job, run in [("ordinary", run) for run in rejected] + [
            ("incremental-body", "echo unsupported"),
            ("incremental-body", "echo setup\n" + contract)]:
        try:
            invocations(fixture(job, run))
        except SystemExit as error:
            assert "sweep-plan:" in str(error)
        else:
            raise AssertionError(f"accepted unsupported contract block: {job}: {run}")
    print("OK: sweep discovery follows relocated contracts and rejects shell wrappers")


def self_test():
    discovery_self_test()
    text = GATES.read_text()
    failures = []

    parsed_jobs = [name for name, _ in load_jobs()]
    grepped_jobs = scanned_jobs(text)
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
    group.add_argument("--jobs", action="store_true", help="print jobs containing swept contracts")
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
