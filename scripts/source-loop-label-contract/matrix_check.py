#!/usr/bin/env python3
"""Keep every source-loop contract matrix field executable and fail closed."""

from pathlib import Path
import sys


MUTATION = "drop-terminal-loop-jump-guard"
OWNER = "source_loop_target_is_retained"
CONTROL = "match_unloop_is_retained"
EXPECTED = {
    "role": (MUTATION, "counted"),
    "owner": (MUTATION, OWNER),
    "red": (MUTATION, OWNER),
    "control": (CONTROL,),
}
BASE = """role\tdrop-terminal-loop-jump-guard\tcounted
owner\tdrop-terminal-loop-jump-guard\tsource_loop_target_is_retained
red\tdrop-terminal-loop-jump-guard\tsource_loop_target_is_retained
control\tmatch_unloop_is_retained
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
            "role\tdrop-terminal-loop-jump-guard\tcounted",
            "role\tother-mutant\tcounted",
        ),
        "role stops being counted": replaced(
            "role\tdrop-terminal-loop-jump-guard\tcounted",
            "role\tdrop-terminal-loop-jump-guard\trecorded",
        ),
        "owner mutation lies": replaced(
            "owner\tdrop-terminal-loop-jump-guard\tsource_loop_target_is_retained",
            "owner\tother-mutant\tsource_loop_target_is_retained",
        ),
        "owner assertion lies": replaced(
            "owner\tdrop-terminal-loop-jump-guard\tsource_loop_target_is_retained",
            "owner\tdrop-terminal-loop-jump-guard\tmatch_unloop_is_retained",
        ),
        "red mutation lies": replaced(
            "red\tdrop-terminal-loop-jump-guard\tsource_loop_target_is_retained",
            "red\tother-mutant\tsource_loop_target_is_retained",
        ),
        "red assertion lies": replaced(
            "red\tdrop-terminal-loop-jump-guard\tsource_loop_target_is_retained",
            "red\tdrop-terminal-loop-jump-guard\tmatch_unloop_is_retained",
        ),
        "control lies": replaced(
            "control\tmatch_unloop_is_retained",
            "control\tsource_loop_target_is_retained",
        ),
        "role is duplicated": BASE + "role\tdrop-terminal-loop-jump-guard\tcounted\n",
        "owner is missing": replaced(
            "owner\tdrop-terminal-loop-jump-guard\tsource_loop_target_is_retained\n",
            "",
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
        validate(Path(sys.argv[1]).read_text())
    except MatrixError as error:
        raise SystemExit(f"invalid source-loop contract matrix: {error}") from error


if __name__ == "__main__":
    main()
