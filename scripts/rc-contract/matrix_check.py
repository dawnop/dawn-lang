#!/usr/bin/env python3
"""Keep every field of the RC contract's mutant matrix executable.

The matrix is only worth reading if a wrong entry is refused rather than
believed, so this validates the file's shape (run.sh separately compares the
recorded red sets against observed ones) and carries a negative control: a
self-test that synthesises one wrong matrix per rule and requires each to be
refused. A validator nobody has seen say no is a validator nobody has tested.
"""

from pathlib import Path
import sys


BASE = """assert\ta
assert\tb
assert\tc

control\tc

role\tm1\tcounted
owner\tm1\ta
red\tm1\ta
red\tm1\tb

role\tm2\trecorded
red\tm2\ta
red\tm2\tb
"""


class MatrixError(ValueError):
    pass


def parse(text: str):
    """(asserts, controls, roles, owners, reds) with every rule enforced."""
    asserts: list[str] = []
    controls: list[str] = []
    roles: dict[str, str] = {}
    owners: dict[str, str] = {}
    reds: dict[str, list[str]] = {}
    arity = {"assert": 1, "control": 1, "role": 2, "owner": 2, "red": 2}

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
        elif record == "control":
            if fields[0] in controls:
                raise MatrixError(f"line {number}: duplicate control {fields[0]!r}")
            controls.append(fields[0])
        elif record == "role":
            if fields[0] in roles:
                raise MatrixError(f"line {number}: duplicate role for {fields[0]!r}")
            if fields[1] not in ("counted", "recorded"):
                raise MatrixError(f"line {number}: unknown role {fields[1]!r}")
            roles[fields[0]] = fields[1]
        elif record == "owner":
            if fields[0] in owners:
                raise MatrixError(f"line {number}: duplicate owner for {fields[0]!r}")
            owners[fields[0]] = fields[1]
        else:
            reds.setdefault(fields[0], []).append(fields[1])

    known = set(asserts)
    for name in controls:
        if name not in known:
            raise MatrixError(f"control {name!r} is not an assertion")
    for mutation, role in roles.items():
        if mutation not in reds:
            raise MatrixError(f"{mutation!r} has a role but reddens nothing")
        if role == "counted" and mutation not in owners:
            raise MatrixError(f"counted mutant {mutation!r} has no owner")
        if role == "recorded" and mutation in owners:
            raise MatrixError(f"recorded mutant {mutation!r} may not own an assertion")
    for mutation, listed in reds.items():
        if mutation not in roles:
            raise MatrixError(f"{mutation!r} reddens something without a role")
        for name in listed:
            if name not in known:
                raise MatrixError(f"{mutation!r} reddens unknown assertion {name!r}")
        if len(set(listed)) != len(listed):
            raise MatrixError(f"{mutation!r} lists an assertion twice")
        for name in controls:
            if name in listed and roles[mutation] == "counted":
                raise MatrixError(f"counted mutant {mutation!r} reddens control {name!r}")
    for mutation, name in owners.items():
        if mutation not in roles:
            raise MatrixError(f"{mutation!r} owns an assertion without a role")
        if name not in known:
            raise MatrixError(f"{mutation!r} owns unknown assertion {name!r}")
        if name not in reds.get(mutation, []):
            raise MatrixError(f"{mutation!r} owns {name!r} without reddening it")
    owned = [name for mutation, name in owners.items() if roles[mutation] == "counted"]
    if len(set(owned)) != len(owned):
        raise MatrixError("two counted mutants own the same assertion")
    if not asserts:
        raise MatrixError("the assertion roster is empty")
    return asserts, controls, roles, owners, reds


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
        "duplicate control": BASE + "control\tc\n",
        "duplicate role": BASE + "role\tm1\tcounted\n",
        "unknown role": replaced("role\tm1\tcounted", "role\tm1\tobserved"),
        "duplicate owner": BASE + "owner\tm1\tb\n",
        "control is not an assertion": replaced("control\tc", "control\tz"),
        "role reddens nothing": BASE + "role\tm3\tcounted\n",
        "counted mutant has no owner": replaced("owner\tm1\ta\n", ""),
        "recorded mutant owns something": BASE + "owner\tm2\ta\n",
        "red without a role": BASE + "red\tm3\ta\n",
        "red names an unknown assertion": replaced("red\tm1\tb", "red\tm1\tz"),
        "red lists an assertion twice": BASE + "red\tm1\ta\n",
        "counted mutant reddens a control": BASE + "red\tm1\tc\n",
        "owner names an unknown assertion": replaced("owner\tm1\ta", "owner\tm1\tz"),
        "owner is not in the red set": replaced("owner\tm1\ta", "owner\tm1\tc"),
        "two counted mutants own one assertion": (
            replaced("role\tm2\trecorded", "role\tm2\tcounted") + "owner\tm2\ta\n"
        ),
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
