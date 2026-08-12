#!/usr/bin/env python3
"""Check once-only iterable lowering and range induction separation in Core."""

from pathlib import Path
import re
import sys


class CoreError(ValueError):
    pass


def function_body(text: str, name: str) -> list[str]:
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line == f"fn {name} -> Unit"]
    if len(starts) != 1:
        raise CoreError(f"expected one {name}, found {len(starts)}")
    start = starts[0]
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("fn ")),
        len(lines),
    )
    return lines[start:end]


def count(body: list[str], pattern: str) -> int:
    regex = re.compile(pattern)
    return sum(1 for line in body if regex.search(line))


def check_source(text: str) -> None:
    body = function_body(text, "iter_core.main")
    found = count(body, r"\bcall direct iter_core\.source : List\[Pair\]$")
    if found != 1:
        raise CoreError(f"iterable source appears {found} times instead of once")


def check_start(text: str) -> None:
    body = function_body(text, "iter_core.main")
    found = count(body, r"\biter_start : ")
    if found != 1:
        raise CoreError(f"iter_start appears {found} times instead of once")


def check_get(text: str) -> None:
    body = function_body(text, "iter_core.main")
    found = count(body, r"\biter_get : ")
    if found != 1:
        raise CoreError(f"iter_get appears {found} times instead of once")


def check_range(text: str) -> None:
    body = function_body(text, "range_core.main")
    steps = [i for i, line in enumerate(body) if line.strip() == "step"]
    if len(steps) != 1:
        raise CoreError(f"expected one range step, found {len(steps)}")
    step = steps[0]
    after = body[step + 1 :]
    step_targets = [
        match.group(1)
        for line in after
        if (match := re.fullmatch(r"\s+assign v(\d+)", line))
    ]
    if len(step_targets) != 1:
        raise CoreError(f"expected one induction assignment, found {len(step_targets)}")
    induction = step_targets[0]
    before_targets = {
        match.group(1)
        for line in body[:step]
        if (match := re.fullmatch(r"\s+assign v(\d+)", line))
    }
    if induction in before_targets:
        raise CoreError("range induction local is also a pattern binding slot")


GOOD_ITER = """fn iter_core.main -> Unit
  block : Unit
    let v1 : List[Pair]
      call direct iter_core.source : List[Pair]
    let v2 : Int
      call impl std/list iter_start : Int
    loop L0
      call impl std/list iter_get : T
"""

GOOD_RANGE = """fn range_core.main -> Unit
  block : Unit
    loop L0
      block : Unit
        assign v3
          local v1 : Int
        assign v4
          bool true
      step
        block : Unit
          assign v1
            int 1
"""


def must_fail(label: str, text: str, check) -> None:
    try:
        check(text)
    except CoreError:
        return
    raise AssertionError(f"core self-test mutant stayed green: {label}")


def self_test() -> None:
    check_source(GOOD_ITER)
    check_start(GOOD_ITER)
    check_get(GOOD_ITER)
    check_range(GOOD_RANGE)
    must_fail(
        "duplicate source",
        GOOD_ITER.replace(
            "      call direct iter_core.source : List[Pair]\n",
            "      call direct iter_core.source : List[Pair]\n"
            "      call direct iter_core.source : List[Pair]\n",
        ),
        check_source,
    )
    must_fail(
        "duplicate iter_start",
        GOOD_ITER.replace(
            "      call impl std/list iter_start : Int\n",
            "      call impl std/list iter_start : Int\n"
            "      call impl std/list iter_start : Int\n",
        ),
        check_start,
    )
    must_fail(
        "duplicate iter_get",
        GOOD_ITER.replace(
            "      call impl std/list iter_get : T\n",
            "      call impl std/list iter_get : T\n"
            "      call impl std/list iter_get : T\n",
        ),
        check_get,
    )
    must_fail(
        "shared range slot",
        GOOD_RANGE.replace("          assign v1\n            int 1\n", "          assign v3\n            int 1\n"),
        check_range,
    )
    print("core self-test: 4 mutant(s) refused")


def main() -> None:
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return
    if len(sys.argv) != 3 or sys.argv[1] not in {"source", "start", "get", "range"}:
        raise SystemExit("usage: core_check.py [--self-test | source|start|get|range dump.core]")
    check = {
        "source": check_source,
        "start": check_start,
        "get": check_get,
        "range": check_range,
    }[sys.argv[1]]
    try:
        check(Path(sys.argv[2]).read_text(encoding="utf-8"))
    except CoreError as error:
        raise SystemExit(f"invalid for-pattern Core: {error}") from error


if __name__ == "__main__":
    main()
