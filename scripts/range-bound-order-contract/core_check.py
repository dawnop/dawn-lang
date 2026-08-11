#!/usr/bin/env python3
"""Check range-bound order and once-before-loop shape in a Core dump."""

from pathlib import Path
import re
import sys


CALLS = (
    "range_lower_empty",
    "range_upper_empty",
    "range_lower_nonempty",
    "range_upper_nonempty",
)


class CoreError(ValueError):
    pass


def main_body(text: str) -> list[str]:
    lines = text.splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(r"fn\s+\S*eval_order\.main\s+->\s+Unit", line)
    ]
    if len(starts) != 1:
        raise CoreError(f"expected one eval_order.main, found {len(starts)}")
    start = starts[0]
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("fn ")),
        len(lines),
    )
    return lines[start:end]


def positions(body: list[str]) -> tuple[dict[str, int], list[int]]:
    found: dict[str, int] = {}
    for name in CALLS:
        matches = [
            index
            for index, line in enumerate(body)
            if re.search(rf"\bcall direct \S*eval_order\.{name}\s+:\s+Int$", line)
        ]
        if len(matches) != 1:
            raise CoreError(f"expected one call to {name}, found {len(matches)}")
        found[name] = matches[0]
    loops = [
        index for index, line in enumerate(body) if re.fullmatch(r"\s+loop L\d+", line)
    ]
    if len(loops) != 2:
        raise CoreError(f"expected two range loops in main, found {len(loops)}")
    return found, loops


def check_order(text: str) -> None:
    found, _loops = positions(main_body(text))
    if found["range_lower_empty"] >= found["range_upper_empty"]:
        raise CoreError("empty range binds upper before lower")
    if found["range_lower_nonempty"] >= found["range_upper_nonempty"]:
        raise CoreError("nonempty range binds upper before lower")


def check_control(text: str) -> None:
    found, loops = positions(main_body(text))
    empty = (found["range_lower_empty"], found["range_upper_empty"])
    nonempty = (found["range_lower_nonempty"], found["range_upper_nonempty"])
    if max(empty) >= loops[0]:
        raise CoreError("an empty-range bound is not before its loop")
    if min(nonempty) <= loops[0] or max(nonempty) >= loops[1]:
        raise CoreError("a nonempty-range bound is not before its loop")


GOOD = """fn eval_order.main -> Unit
  block : Unit
    let v0 : Int
      call direct eval_order.range_lower_empty : Int
    let v1 : Int
      call direct eval_order.range_upper_empty : Int
    loop L0
    let v2 : Int
      call direct eval_order.range_lower_nonempty : Int
    let v3 : Int
      call direct eval_order.range_upper_nonempty : Int
    loop L1
"""


def must_fail(name: str, text: str, check) -> None:
    try:
        check(text)
    except CoreError:
        return
    raise AssertionError(f"core self-test mutant stayed green: {name}")


def self_test() -> None:
    check_order(GOOD)
    check_control(GOOD)
    upper_first = GOOD.replace(
        "    let v0 : Int\n"
        "      call direct eval_order.range_lower_empty : Int\n"
        "    let v1 : Int\n"
        "      call direct eval_order.range_upper_empty : Int\n",
        "    let v1 : Int\n"
        "      call direct eval_order.range_upper_empty : Int\n"
        "    let v0 : Int\n"
        "      call direct eval_order.range_lower_empty : Int\n",
        1,
    )
    must_fail("upper first", upper_first, check_order)
    check_control(upper_first)
    duplicate = GOOD.replace(
        "    loop L0\n",
        "      call direct eval_order.range_lower_empty : Int\n    loop L0\n",
        1,
    )
    must_fail("duplicate lower", duplicate, check_control)
    late = GOOD.replace(
        "    let v1 : Int\n"
        "      call direct eval_order.range_upper_empty : Int\n"
        "    loop L0\n",
        "    loop L0\n"
        "    let v1 : Int\n"
        "      call direct eval_order.range_upper_empty : Int\n",
        1,
    )
    must_fail("upper after loop", late, check_control)
    print("core self-test: 3 mutant(s) refused")


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    if len(sys.argv) != 3 or sys.argv[1] not in ("order", "control"):
        raise SystemExit("usage: core_check.py [--self-test | order|control dump.core]")
    text = Path(sys.argv[2]).read_text(encoding="utf-8")
    try:
        if sys.argv[1] == "order":
            check_order(text)
        else:
            check_control(text)
    except CoreError as error:
        raise SystemExit(f"invalid range-bound Core: {error}") from error


if __name__ == "__main__":
    main()
