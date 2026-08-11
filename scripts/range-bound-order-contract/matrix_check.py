#!/usr/bin/env python3
"""Keep every range-bound contract matrix field executable and fail closed."""

from pathlib import Path
import sys


MUTATION = "restore-upper-first"
OWNER = "range_bound_order_is_lower_first"
CONTROL = "range_bounds_are_once_before_loop"
EXPECTED = {
    "role": (MUTATION, "counted"),
    "owner": (MUTATION, OWNER),
    "red": (MUTATION, OWNER),
    "control": (CONTROL,),
}
BASE = """role\trestore-upper-first\tcounted
owner\trestore-upper-first\trange_bound_order_is_lower_first
red\trestore-upper-first\trange_bound_order_is_lower_first
control\trange_bounds_are_once_before_loop
"""


class MatrixError(ValueError):
    pass


def validate(text: str) -> None:
    seen: set[str] = set()
    for line_number, raw in enumerate(text.splitlines(), 1):
        if not raw or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        record = fields[0]
        if record not in EXPECTED:
            raise MatrixError(f"line {line_number}: unknown record {record!r}")
        if record in seen:
            raise MatrixError(f"line {line_number}: duplicate {record} record")
        seen.add(record)
        actual = tuple(fields[1:])
        if actual != EXPECTED[record]:
            raise MatrixError(
                f"line {line_number}: {record} fields are {actual!r}, "
                f"expected {EXPECTED[record]!r}"
            )
    missing = EXPECTED.keys() - seen
    if missing:
        raise MatrixError(f"missing record(s): {', '.join(sorted(missing))}")


def replaced(old: str, new: str) -> str:
    if BASE.count(old) != 1:
        raise AssertionError(f"self-test anchor is not unique: {old!r}")
    return BASE.replace(old, new)


def self_test() -> None:
    validate(BASE)
    mutants = {
        "role mutation lies": replaced(
            "role\trestore-upper-first\tcounted",
            "role\tother-mutant\tcounted",
        ),
        "role kind lies": replaced(
            "role\trestore-upper-first\tcounted",
            "role\trestore-upper-first\trecorded",
        ),
        "owner mutation lies": replaced(
            "owner\trestore-upper-first\trange_bound_order_is_lower_first",
            "owner\tother-mutant\trange_bound_order_is_lower_first",
        ),
        "owner assertion lies": replaced(
            "owner\trestore-upper-first\trange_bound_order_is_lower_first",
            "owner\trestore-upper-first\trange_bounds_are_once_before_loop",
        ),
        "red mutation lies": replaced(
            "red\trestore-upper-first\trange_bound_order_is_lower_first",
            "red\tother-mutant\trange_bound_order_is_lower_first",
        ),
        "red assertion lies": replaced(
            "red\trestore-upper-first\trange_bound_order_is_lower_first",
            "red\trestore-upper-first\trange_bounds_are_once_before_loop",
        ),
        "control lies": replaced(
            "control\trange_bounds_are_once_before_loop",
            "control\trange_bound_order_is_lower_first",
        ),
        "role is duplicated": BASE + "role\trestore-upper-first\tcounted\n",
        "owner is duplicated": BASE + (
            "owner\trestore-upper-first\trange_bound_order_is_lower_first\n"
        ),
        "red is duplicated": BASE + (
            "red\trestore-upper-first\trange_bound_order_is_lower_first\n"
        ),
        "control is duplicated": BASE + "control\trange_bounds_are_once_before_loop\n",
        "role is missing": replaced("role\trestore-upper-first\tcounted\n", ""),
        "owner is missing": replaced(
            "owner\trestore-upper-first\trange_bound_order_is_lower_first\n", ""
        ),
        "red is missing": replaced(
            "red\trestore-upper-first\trange_bound_order_is_lower_first\n", ""
        ),
        "control is missing": replaced(
            "control\trange_bounds_are_once_before_loop\n", ""
        ),
        "record is unknown": BASE + "note\tnot-a-contract-record\n",
    }
    for name, mutant in mutants.items():
        try:
            validate(mutant)
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
        validate(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except MatrixError as error:
        raise SystemExit(f"invalid range-bound contract matrix: {error}") from error


if __name__ == "__main__":
    main()
