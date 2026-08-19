#!/usr/bin/env python3
"""Run every gallery entry point against its byte-exact registry contract."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import signal
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = Path(__file__).with_name("registry.json")
TIMEOUT_SECONDS = 120
GROUP_TERM_SECONDS = 0.25
GROUP_KILL_SECONDS = 5.0

TOP_LEVEL_FIELDS = {"schema", "targets"}
TARGET_FIELDS = {"target", "cases"}
CASE_FIELDS = {"name", "argv", "stdin", "stdout", "stderr", "exit"}


class ContractError(Exception):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ContractError(f"registry repeats key {key!r}")
        out[key] = value
    return out


def load_registry() -> dict[str, Any]:
    try:
        with REGISTRY.open(encoding="utf-8") as source:
            value = json.load(source, object_pairs_hook=reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot read {REGISTRY.relative_to(ROOT)}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError("registry root must be an object")
    require_fields("registry root", value, TOP_LEVEL_FIELDS)
    if type(value["schema"]) is not int or value["schema"] != 1:
        raise ContractError("registry schema must be the integer 1")
    if not isinstance(value["targets"], list):
        raise ContractError("registry targets must be a list")
    return value


def require_fields(where: str, value: dict[str, Any], expected: set[str]) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details = []
    if missing:
        details.append(f"missing {missing}")
    if extra:
        details.append(f"unknown {extra}")
    raise ContractError(f"{where} has invalid fields: {', '.join(details)}")


def normalized_target(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{where} target must be a non-empty string")
    path = PurePosixPath(value)
    if path.is_absolute() or path.parts[:1] != ("examples",):
        raise ContractError(f"{where} target must be relative and start with examples/")
    if any(part in {"", ".", ".."} for part in path.parts) or str(path) != value:
        raise ContractError(f"{where} target is not normalized: {value!r}")
    return value


def validate_case(value: Any, target: str, index: int, names: set[str]) -> dict[str, Any]:
    where = f"{target} case #{index + 1}"
    if not isinstance(value, dict):
        raise ContractError(f"{where} must be an object")
    require_fields(where, value, CASE_FIELDS)
    name = value["name"]
    if not isinstance(name, str) or not name:
        raise ContractError(f"{where} name must be a non-empty string")
    if name in names:
        raise ContractError(f"case name {name!r} is not unique")
    names.add(name)
    argv = value["argv"]
    if not isinstance(argv, list) or any(not isinstance(arg, str) for arg in argv):
        raise ContractError(f"{where} argv must be a list of strings")
    if any("\0" in arg for arg in argv):
        raise ContractError(f"{where} argv contains a NUL byte")
    for field in ("stdin", "stdout", "stderr"):
        if not isinstance(value[field], str):
            raise ContractError(f"{where} {field} must be a string")
    if type(value["exit"]) is not int:
        raise ContractError(f"{where} exit must be an integer")
    return value


def validate_targets(registry: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    targets: dict[str, list[dict[str, Any]]] = {}
    names: set[str] = set()
    for index, value in enumerate(registry["targets"]):
        where = f"registry target #{index + 1}"
        if not isinstance(value, dict):
            raise ContractError(f"{where} must be an object")
        require_fields(where, value, TARGET_FIELDS)
        target = normalized_target(value["target"], where)
        if target in targets:
            raise ContractError(f"registry repeats target {target}")
        cases = value["cases"]
        if not isinstance(cases, list) or not cases:
            raise ContractError(f"{target} must register at least one case")
        validated_cases = [
            validate_case(case, target, case_index, names)
            for case_index, case in enumerate(cases)
        ]
        if not any(case["exit"] == 0 for case in validated_cases):
            raise ContractError(f"{target} must register at least one successful case")
        targets[target] = validated_cases
    return targets


def discover_gallery_units() -> set[str]:
    examples = ROOT / "examples"
    if not examples.is_dir():
        raise ContractError("examples/ is missing or is not a directory")
    found: set[str] = set()
    try:
        groups = sorted(examples.iterdir())
        for group in groups:
            if not group.is_dir():
                continue
            for entry in sorted(group.iterdir()):
                if entry.is_file() and entry.suffix == ".dawn":
                    target = entry
                elif entry.is_dir() and (entry / "src").is_dir():
                    target = entry
                else:
                    continue
                found.add(target.relative_to(ROOT).as_posix())
    except OSError as error:
        raise ContractError(f"cannot discover gallery units: {error}") from error
    return found


def check_bijection(
    registered: dict[str, list[dict[str, Any]]], discovered: set[str]
) -> None:
    missing = sorted(set(discovered) - set(registered))
    ghosts = sorted(set(registered) - set(discovered))
    if not missing and not ghosts:
        return
    details = []
    if missing:
        details.append("unregistered gallery unit(s): " + ", ".join(missing))
    if ghosts:
        details.append("registry target(s) with no gallery unit: " + ", ".join(ghosts))
    raise ContractError("; ".join(details))


def process_group_exists(group_id: int) -> bool:
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    return True


def wait_for_process_group(group_id: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while process_group_exists(group_id):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def cleanup_residual_process_group(group_id: int) -> str | None:
    if not process_group_exists(group_id):
        return None
    try:
        os.killpg(group_id, signal.SIGTERM)
    except ProcessLookupError:
        return None
    except OSError as error:
        return f"could not terminate residual process group {group_id}: {error}"
    if wait_for_process_group(group_id, GROUP_TERM_SECONDS):
        return None
    try:
        os.killpg(group_id, signal.SIGKILL)
    except ProcessLookupError:
        return None
    except OSError as error:
        return f"could not kill residual process group {group_id}: {error}"
    if wait_for_process_group(group_id, GROUP_KILL_SECONDS):
        return None
    return f"residual process group {group_id} survived SIGKILL"


def kill_process_group(group_id: int) -> str | None:
    try:
        os.killpg(group_id, signal.SIGKILL)
    except ProcessLookupError:
        return None
    except OSError as error:
        return f"could not kill process group {group_id}: {error}"
    return None


def run_case(target: str, case: dict[str, Any]) -> list[str]:
    command = [str(ROOT / "bin" / "dawn"), "run", target]
    if case["argv"]:
        command.extend(["--", *case["argv"]])
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(
            input=case["stdin"].encode("utf-8"), timeout=TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        cleanup_problem = kill_process_group(process.pid)
        stdout, stderr = process.communicate()
        if cleanup_problem is None and not wait_for_process_group(
            process.pid, GROUP_KILL_SECONDS
        ):
            cleanup_problem = f"process group {process.pid} survived SIGKILL"
        problems = [
            f"timed out after {TIMEOUT_SECONDS}s; killed process group {process.pid}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        ]
        if cleanup_problem is not None:
            problems.append(cleanup_problem)
        return problems
    except BaseException:
        kill_process_group(process.pid)
        process.communicate()
        raise

    failures = []
    cleanup_problem = cleanup_residual_process_group(process.pid)
    if cleanup_problem is not None:
        failures.append(cleanup_problem)
    expected_stdout = case["stdout"].encode("utf-8")
    expected_stderr = case["stderr"].encode("utf-8")
    if stdout != expected_stdout:
        failures.append(f"stdout expected {expected_stdout!r}, got {stdout!r}")
    if stderr != expected_stderr:
        failures.append(f"stderr expected {expected_stderr!r}, got {stderr!r}")
    if process.returncode != case["exit"]:
        failures.append(f"exit expected {case['exit']}, got {process.returncode}")
    return failures


def main() -> int:
    # `--target` runs one registered entry and nothing else. It exists for
    # settlement: when selfhost-run-diff.sh accepts a declared `run ... example`
    # difference, it holds that settlement to this registry with exactly this
    # mode, because the registry pin is an in-repo expectation no Emit-Change
    # declaration can cover (ab116b1 declared the chars change, run-diff noted
    # it, and the stale pin in registry.json still red CI a day later).
    argv = sys.argv[1:]
    only: str | None = None
    if argv:
        if len(argv) == 2 and argv[0] == "--target":
            only = argv[1]
        else:
            print("usage: run.py [--target examples/<group>/<unit>]", file=sys.stderr)
            return 2

    try:
        registered = validate_targets(load_registry())
        if only is None:
            discovered = discover_gallery_units()
            check_bijection(registered, discovered)
        elif only in registered:
            registered = {only: registered[only]}
        else:
            raise ContractError(
                f"no registry entry pins {only}; a changed example output needs "
                "its scripts/example-main-contract/registry.json entry updated "
                "in the same batch"
            )
    except ContractError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    failures = 0
    cases = 0
    for target, target_cases in registered.items():
        for case in target_cases:
            cases += 1
            label = f"{target} :: {case['name']}"
            print(f"== {label}")
            try:
                problems = run_case(target, case)
            except OSError as error:
                problems = [f"could not start dawn: {error}"]
            if problems:
                failures += 1
                for problem in problems:
                    print(f"FAIL: {label}: {problem}", file=sys.stderr)

    if failures:
        print(f"FAIL: {failures}/{cases} example main contract(s) failed", file=sys.stderr)
        return 1
    if only is None:
        print(
            f"OK: {cases} case(s) cover {len(discovered)} gallery unit(s); "
            "stdout, stderr, and exit matched exactly"
        )
    else:
        print(
            f"OK: {cases} case(s) pin {only}; "
            "stdout, stderr, and exit matched exactly"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
