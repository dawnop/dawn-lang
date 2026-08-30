#!/usr/bin/env python3
"""Keep every field of the RC contract's mutant matrix executable.

The matrix is only worth reading if a wrong entry is refused rather than
believed, so this validates the file's shape (run.sh separately compares the
recorded red sets against observed ones) and carries a negative control: a
self-test that synthesises one wrong matrix per rule and requires each to be
refused. A validator nobody has seen say no is a validator nobody has tested.
"""

from itertools import combinations
from pathlib import Path
import sys


BASE = """assert\ta
assert\tb
assert\tc

probe\tp
probe\tq

tail\tt

control\tc

role\tm1\tcounted
owner\tm1\ta
red\tm1\ta
red\tm1\tb

role\tm2\trecorded
red\tm2\ta
red\tm2\tb

role\tm3\tpoisoned
owner\tm3\tp
red\tm3\tp
red\tm3\tq

role\tm6\tbenign

role\tm7\ttail
owner\tm7\tt
red\tm7\tt
"""

# The roles, and which roster each one is read off. A mutant of the
# allocator's behaviour is observed on a plain build through rc_test.c's
# assertions; a mutant of its poisoning is observed on a sanitized build
# through poison_probe.c's probes, because a plain build has no poisoning in
# it to break; a mutant of the batch-tail boundary is observed on a build
# with a 1024-byte batch through slab_batch_tail.c, because the production
# batch of 32KiB never reaches that boundary at all. Mixing rosters in one
# red set would record an observation the harness never makes, so the roster
# a role may name is part of the role.
ROSTER_OF = {
    "counted": "assert",
    "recorded": "assert",
    "poisoned": "probe",
    "benign": "assert",
    "tail": "tail",
}
OWNING = {"counted", "poisoned", "tail"}
# The one role whose whole claim is a green. A positive control is a real
# edit to a production file that changes no property anyone is entitled to,
# so it reddens nothing -- and the file has to say so, because "reddens
# nothing" and "was never run" produce the same empty red set otherwise.
BENIGN = {"benign"}


class MatrixError(ValueError):
    pass


def parse(text: str):
    """(asserts, probes, tails, controls, roles, owners, reds), rules enforced."""
    asserts: list[str] = []
    probes: list[str] = []
    tails: list[str] = []
    controls: list[str] = []
    roles: dict[str, str] = {}
    owners: dict[str, str] = {}
    reds: dict[str, list[str]] = {}
    arity = {
        "assert": 1,
        "probe": 1,
        "tail": 1,
        "control": 1,
        "role": 2,
        "owner": 2,
        "red": 2,
    }

    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.startswith("#"):
            continue
        record, *fields = raw.split("\t")
        if record not in arity:
            raise MatrixError(f"line {number}: unknown record {record!r}")
        if len(fields) != arity[record]:
            raise MatrixError(
                f"line {number}: {record} takes {arity[record]} field(s), "
                f"got {len(fields)}"
            )
        if record == "assert":
            if fields[0] in asserts:
                raise MatrixError(f"line {number}: duplicate assertion {fields[0]!r}")
            asserts.append(fields[0])
        elif record == "probe":
            if fields[0] in probes:
                raise MatrixError(f"line {number}: duplicate probe {fields[0]!r}")
            probes.append(fields[0])
        elif record == "tail":
            if fields[0] in tails:
                raise MatrixError(f"line {number}: duplicate tail check {fields[0]!r}")
            tails.append(fields[0])
        elif record == "control":
            if fields[0] in controls:
                raise MatrixError(f"line {number}: duplicate control {fields[0]!r}")
            controls.append(fields[0])
        elif record == "role":
            if fields[0] in roles:
                raise MatrixError(f"line {number}: duplicate role for {fields[0]!r}")
            if fields[1] not in ROSTER_OF:
                raise MatrixError(f"line {number}: unknown role {fields[1]!r}")
            roles[fields[0]] = fields[1]
        elif record == "owner":
            if fields[0] in owners:
                raise MatrixError(f"line {number}: duplicate owner for {fields[0]!r}")
            owners[fields[0]] = fields[1]
        else:
            reds.setdefault(fields[0], []).append(fields[1])

    rosters = {"assert": set(asserts), "probe": set(probes), "tail": set(tails)}
    for left, right in combinations(sorted(rosters), 2):
        both = rosters[left] & rosters[right]
        if both:
            raise MatrixError(
                f"{sorted(both)[0]!r} is on both the {left} and {right} roster"
            )
    known = set().union(*rosters.values())
    for name in controls:
        if name not in known:
            raise MatrixError(f"control {name!r} is on no roster")
    for mutation, role in roles.items():
        if role in BENIGN:
            if mutation in reds:
                raise MatrixError(f"benign mutant {mutation!r} reddens something")
        elif mutation not in reds:
            raise MatrixError(f"{mutation!r} has a role but reddens nothing")
        if role in OWNING and mutation not in owners:
            raise MatrixError(f"{role} mutant {mutation!r} has no owner")
        if role not in OWNING and mutation in owners:
            raise MatrixError(f"{role} mutant {mutation!r} may not own an assertion")
    for mutation, listed in reds.items():
        if mutation not in roles:
            raise MatrixError(f"{mutation!r} reddens something without a role")
        roster = ROSTER_OF[roles[mutation]]
        for name in listed:
            if name not in known:
                raise MatrixError(f"{mutation!r} reddens unknown assertion {name!r}")
            if name not in rosters[roster]:
                raise MatrixError(
                    f"{roles[mutation]} mutant {mutation!r} reddens {name!r}, "
                    f"which is not on its {roster} roster"
                )
        if len(set(listed)) != len(listed):
            raise MatrixError(f"{mutation!r} lists an assertion twice")
        for name in controls:
            if name in listed and roles[mutation] in OWNING:
                raise MatrixError(f"{mutation!r} reddens control {name!r}")
    for mutation, name in owners.items():
        if mutation not in roles:
            raise MatrixError(f"{mutation!r} owns an assertion without a role")
        if name not in known:
            raise MatrixError(f"{mutation!r} owns unknown assertion {name!r}")
        if name not in reds.get(mutation, []):
            raise MatrixError(f"{mutation!r} owns {name!r} without reddening it")
    owned = [name for mutation, name in owners.items() if roles[mutation] in OWNING]
    if len(set(owned)) != len(owned):
        raise MatrixError("two mutants own the same assertion")
    if not asserts:
        raise MatrixError("the assertion roster is empty")
    return asserts, probes, tails, controls, roles, owners, reds


def replaced(old: str, new: str) -> str:
    if BASE.count(old) != 1:
        raise AssertionError(f"self-test anchor is not unique: {old!r}")
    return BASE.replace(old, new)


def self_test() -> None:
    parse(BASE)
    mutants = {
        "unknown record": BASE + "note\tsomething\n",
        "wrong arity": replaced("role\tm1\tcounted", "role\tm1"),
        "duplicate assertion": BASE + "assert\ta\n",
        "duplicate probe": BASE + "probe\tp\n",
        "duplicate tail check": BASE + "tail\tt\n",
        "one name on the assert and probe rosters": BASE + "probe\ta\n",
        "one name on the assert and tail rosters": BASE + "tail\ta\n",
        "one name on the probe and tail rosters": BASE + "tail\tp\n",
        "duplicate control": BASE + "control\tc\n",
        "duplicate role": BASE + "role\tm1\tcounted\n",
        "unknown role": replaced("role\tm1\tcounted", "role\tm1\tobserved"),
        "duplicate owner": BASE + "owner\tm1\tb\n",
        "control is neither": replaced("control\tc", "control\tz"),
        "role reddens nothing": BASE + "role\tm4\tcounted\n",
        "counted mutant has no owner": replaced("owner\tm1\ta\n", ""),
        "poisoned mutant has no owner": replaced("owner\tm3\tp\n", ""),
        "tail mutant has no owner": replaced("owner\tm7\tt\n", ""),
        "recorded mutant owns something": BASE + "owner\tm2\ta\n",
        "red without a role": BASE + "red\tm4\ta\n",
        "red names an unknown assertion": replaced("red\tm1\tb", "red\tm1\tz"),
        "red lists an assertion twice": BASE + "red\tm1\ta\n",
        "counted mutant reddens a control": BASE + "red\tm1\tc\n",
        "counted mutant reddens a probe": replaced("red\tm1\tb", "red\tm1\tp"),
        "poisoned mutant reddens an assertion": replaced("red\tm3\tq", "red\tm3\tb"),
        "counted mutant reddens a tail check": replaced("red\tm1\tb", "red\tm1\tt"),
        "tail mutant reddens an assertion": BASE + "red\tm7\ta\n",
        "owner names an unknown assertion": replaced("owner\tm1\ta", "owner\tm1\tz"),
        "owner is not in the red set": replaced("owner\tm1\ta", "owner\tm1\tc"),
        "two counted mutants own one assertion": (
            replaced("role\tm2\trecorded", "role\tm2\tcounted") + "owner\tm2\ta\n"
        ),
        "two poisoned mutants own one probe": (
            BASE + "role\tm5\tpoisoned\nowner\tm5\tp\nred\tm5\tp\n"
        ),
        "two tail mutants own one tail check": (
            BASE + "role\tm8\ttail\nowner\tm8\tt\nred\tm8\tt\n"
        ),
        "benign mutant reddens something": BASE + "red\tm6\ta\n",
        "benign mutant owns an assertion": BASE + "owner\tm6\ta\n",
        "empty roster": "",
    }
    for name, mutant in mutants.items():
        try:
            parse(mutant)
        except MatrixError:
            continue
        raise AssertionError(f"matrix self-test mutant stayed green: {name}")
    print(f"matrix self-test: {len(mutants)} mutant(s) refused")


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    if len(sys.argv) != 2:
        raise SystemExit("usage: matrix_check.py [--self-test | matrix.txt]")
    try:
        parse(Path(sys.argv[1]).read_text())
    except MatrixError as error:
        raise SystemExit(f"invalid rc contract matrix: {error}") from error


if __name__ == "__main__":
    main()
