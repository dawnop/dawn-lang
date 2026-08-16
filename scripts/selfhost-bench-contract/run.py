#!/usr/bin/env python3
"""Exercise strict schema, recursive /proc sampling, and source mutants."""

from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from types import ModuleType
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BENCH = ROOT / "scripts/selfhost-bench.py"
MATRIX = HERE / "matrix.txt"
MUTATE = HERE / "mutate.py"
ASSERTIONS = (
    "bench.descendants_recursive",
    "bench.heap_exact",
    "bench.tree_rss_sums_simultaneous",
    "bench.overlap_requires_all_roles",
    "bench.sampling_targets_two_ms",
    "bench.starttime_identity_preserved",
    "bench.vmhwm_reads_proc",
    "bench.exception_cleanup",
    "bench.identity_rechecks",
    "bench.same_jdk",
    "bench.final_source_snapshot",
)

# The `-Xmx` the fixture tree is launched with, so `heap_exact` can say what it
# wanted as well as what it got.
PARENT_HEAP_BYTES = 64 * 1024 * 1024
CHILD_HEAP_BYTES = 96 * 1024 * 1024


class MatrixError(ValueError):
    pass


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def mutator_keys() -> tuple[str, ...]:
    result = subprocess.run(
        [sys.executable, os.fspath(MUTATE), "--list"],
        check=True,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
    )
    keys = tuple(result.stdout.splitlines())
    if not keys or any(not key or "\t" in key for key in keys):
        raise MatrixError("mutator registry returned an invalid key")
    if len(keys) != len(set(keys)):
        raise MatrixError("mutator registry returned duplicate keys")
    return keys


def parse_matrix(
    text: str, mutations: Sequence[str]
) -> dict[tuple[str, str], tuple[str, ...]]:
    mutation_set = set(mutations)
    if len(mutation_set) != len(mutations):
        raise MatrixError("executable mutator keys are duplicated")
    records: dict[tuple[str, str], tuple[str, ...]] = {}
    for line_number, raw in enumerate(text.splitlines(), 1):
        if not raw or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) < 3:
            raise MatrixError(f"line {line_number}: too few fields")
        record, mutation, *values = fields
        if record not in {"role", "owner", "red", "control"}:
            raise MatrixError(f"line {line_number}: unknown record {record!r}")
        if mutation not in mutation_set:
            raise MatrixError(f"line {line_number}: unknown mutation {mutation!r}")
        key = (record, mutation)
        if key in records:
            raise MatrixError(f"line {line_number}: duplicate {record} for {mutation}")
        records[key] = tuple(values)
    expected = {
        (record, mutation)
        for mutation in mutations
        for record in ("role", "owner", "red", "control")
    }
    missing = expected - set(records)
    unknown = set(records) - expected
    if missing:
        raise MatrixError(f"missing records: {sorted(missing)!r}")
    if unknown:
        raise MatrixError(f"unknown records: {sorted(unknown)!r}")
    owners: list[str] = []
    for mutation in mutations:
        if records[("role", mutation)] != ("counted",):
            raise MatrixError(f"role for {mutation} must be exactly counted")
        owner = records[("owner", mutation)]
        red = records[("red", mutation)]
        control = records[("control", mutation)]
        if len(owner) != 1 or owner[0] not in ASSERTIONS:
            raise MatrixError(f"owner for {mutation} must name one known assertion")
        if red != owner:
            raise MatrixError(f"red for {mutation} must equal its owner")
        if len(control) != 1 or control[0] not in ASSERTIONS:
            raise MatrixError(f"control for {mutation} must name one known assertion")
        if control == owner:
            raise MatrixError(f"control for {mutation} must differ from its owner")
        owners.append(owner[0])
    if len(owners) != len(set(owners)):
        raise MatrixError("counted mutants must have unique owners")
    if set(owners) != set(ASSERTIONS):
        raise MatrixError("matrix owners must cover the complete assertion set")
    return records


def matrix_selftest(text: str, mutations: tuple[str, ...]) -> None:
    parse_matrix(text, mutations)
    lines = text.splitlines()
    first = next(line for line in lines if line and not line.startswith("#"))
    first_mutation = mutations[0]
    owner_line = next(line for line in lines if line.startswith(f"owner\t{first_mutation}\t"))
    owner = owner_line.split("\t")[2]
    changed_owner = next(assertion for assertion in ASSERTIONS if assertion != owner)
    mutants = {
        "unknown record": text.replace("role\t", "scope\t", 1),
        "duplicate record": text + first + "\n",
        "missing record": "\n".join(lines[:-1]) + "\n",
        "changed owner": text.replace(owner_line, f"owner\t{first_mutation}\t{changed_owner}"),
    }
    for name, mutant in mutants.items():
        try:
            parse_matrix(mutant, mutations)
        except MatrixError:
            print(f"PASS  matrix refuses {name}")
        else:
            raise AssertionError(f"matrix accepted {name}")
    try:
        parse_matrix(text, mutations + ("unrecorded-mutator",))
    except MatrixError:
        print("PASS  matrix refuses an executable mutator without membership")
    else:
        raise AssertionError("matrix accepted an executable mutator without membership")


def valid_baseline(module: ModuleType) -> dict[str, object]:
    weight_samples = 3
    startup_samples = 5
    ratio_samples = [
        {
            "pass_a_user_ms": 100,
            "pass_b_user_ms": 104,
            "pass_c_user_ms": 109,
            "ratio": 1.09,
        },
        {
            "pass_a_user_ms": 100,
            "pass_b_user_ms": 105,
            "pass_c_user_ms": 110,
            "ratio": 1.10,
        },
        {
            "pass_a_user_ms": 100,
            "pass_b_user_ms": 106,
            "pass_c_user_ms": 111,
            "ratio": 1.11,
        },
    ]
    workloads: dict[str, object] = {}
    for workload_index, (name, roles) in enumerate(module.WORKLOAD_ROLES.items(), 1):
        samples: list[dict[str, object]] = []
        for sample_index in range(weight_samples):
            role_map: dict[str, object] = {}
            for role_index, role in enumerate(roles, 1):
                role_map[role] = {
                    "process_count": 1,
                    "rss_hwm_bytes": 10_000_000 + workload_index * 1000 + sample_index,
                    "vas_peak_bytes": 20_000_000 + role_index * 1000 + sample_index,
                    "max_heap_bytes": (
                        67_108_864 + role_index * 1024 if role in module.JAVA_ROLES else None
                    ),
                }
            samples.append(
                {
                    "wall_time_ns": 30_000_000 + sample_index,
                    "tree_peak_rss_bytes": 40_000_000 + sample_index,
                    "complete_overlap_samples": 2 + sample_index,
                    "roles": role_map,
                }
            )
        workloads[name] = {
            "expected_roles": list(roles),
            "samples": samples,
            "summary": module.workload_summary(samples, roles),
        }
    startup = {}
    for index, name in enumerate(module.STARTUP_TARGETS, 1):
        samples = [index * 1_000_000 + offset for offset in range(startup_samples)]
        startup[name] = {
            "samples_ns": samples,
            "median_ns": module.median_int(samples),
        }
    value = {
        "schema": module.SCHEMA,
        "kind": module.KIND,
        "recorded_at_utc": "2026-08-12T00:00:00Z",
        "source": {"commit": "1" * 40, "tree": "clean"},
        "platform": {
            "system": "Linux",
            "machine": "x86_64",
            "kernel": "contract",
            "locale": "C.UTF-8",
            "java_version": "contract java",
            "java_runtime": "contract runtime",
        },
        "seed": {"tag": "v0.64.0", "sha256": "2" * 64},
        "parameters": {
            "weight_samples": weight_samples,
            "startup_samples": startup_samples,
            "max_rounds": 3,
            "proc_interval_ms": module.PROC_INTERVAL_NS / 1_000_000,
            "noise_threshold": 0.15,
            "bootstrap_ratio_tolerance": 0.15,
        },
        "artifacts": {
            "release_jar": {"sha256": "3" * 64, "bytes": 100},
            "native_compiler": {"sha256": "4" * 64, "bytes": 200},
        },
        "bootstrap_cpu": {
            "rounds": [
                {
                    "samples": ratio_samples,
                    "summary": module.ratio_summary(ratio_samples),
                    "status": "conclusive",
                }
            ],
            "selected_round": 1,
        },
        "workloads": workloads,
        "startup": startup,
    }
    return module.validate_baseline_data(value)


def expect_schema_red(module: ModuleType, name: str, value: object) -> None:
    try:
        if isinstance(value, str):
            module.validate_baseline_data(module.parse_json_strict(value))
        else:
            module.validate_baseline_data(value)
    except module.SchemaError:
        print(f"PASS  schema refuses {name}")
    else:
        raise AssertionError(f"schema accepted {name}")


def schema_contract(module: ModuleType) -> None:
    base = valid_baseline(module)
    module.validate_baseline_data(copy.deepcopy(base))
    print("PASS  strict baseline accepts its canonical fixture")

    text = module.stable_json(base)
    duplicate = text.replace("{\n", "{\n  \"schema\": 1,\n", 1)
    expect_schema_red(module, "duplicate key", duplicate)

    mutations: list[tuple[str, object]] = []
    unknown = copy.deepcopy(base)
    unknown["unknown"] = 1
    mutations.append(("unknown field", unknown))
    missing = copy.deepcopy(base)
    del missing["kind"]
    mutations.append(("missing field", missing))
    zero = copy.deepcopy(base)
    zero["artifacts"]["release_jar"]["bytes"] = 0
    mutations.append(("zero value", zero))
    negative = copy.deepcopy(base)
    negative["artifacts"]["native_compiler"]["bytes"] = -1
    mutations.append(("negative value", negative))
    denominator = copy.deepcopy(base)
    denominator["bootstrap_cpu"]["rounds"][0]["samples"][0]["pass_a_user_ms"] = 0
    mutations.append(("zero denominator", denominator))
    boolean = copy.deepcopy(base)
    boolean["parameters"]["weight_samples"] = True
    mutations.append(("bool as integer", boolean))
    stale = copy.deepcopy(base)
    stale["startup"]["direct_jar"]["median_ns"] += 1
    mutations.append(("stale summary", stale))
    even = copy.deepcopy(base)
    even["parameters"]["weight_samples"] = 4
    mutations.append(("even schema sample count", even))
    for name, mutant in mutations:
        expect_schema_red(module, name, mutant)

    nan_text = text.replace('"noise_threshold": 0.15', '"noise_threshold": NaN')
    infinity_text = text.replace(
        '"noise_threshold": 0.15', '"noise_threshold": Infinity'
    )
    expect_schema_red(module, "NaN", nan_text)
    expect_schema_red(module, "Infinity", infinity_text)

    cli_mutants = {
        "conflicting modes": ["--record", "--check"],
        "missing sample value": ["--weight-samples"],
        "zero samples": ["--weight-samples", "0"],
        "negative samples": ["--weight-samples", "-3"],
        "even samples": ["--weight-samples", "4"],
        "non-integer samples": ["--weight-samples", "three"],
        "too few startup samples": ["--startup-samples", "3"],
        "too many rounds": ["--max-rounds", "4"],
        "duplicate option": ["--weight-samples", "3", "--weight-samples", "5"],
    }
    for name, argv in cli_mutants.items():
        try:
            module.parse_cli(argv)
        except module.CliError:
            print(f"PASS  CLI refuses {name}")
        else:
            raise AssertionError(f"CLI accepted {name}")
    def ratio_sample(pass_a: int, pass_c: int) -> dict[str, object]:
        return {
            "pass_a_user_ms": pass_a,
            "pass_b_user_ms": pass_a,
            "pass_c_user_ms": pass_c,
            "ratio": pass_c / pass_a,
        }

    boundary = module.ratio_summary(
        [ratio_sample(100, 100), ratio_sample(100, 100), ratio_sample(100, 115)]
    )
    if module.noise_state(boundary["spread"]) != "inconclusive":
        raise AssertionError(
            f"raw ratios 1.0, 1.0, 1.15 produced {boundary['spread']!r} "
            "without becoming inconclusive"
        )
    print("PASS  raw ratios 1.0, 1.0, 1.15 are inconclusive")

    below = module.ratio_summary(
        [
            ratio_sample(10_000, 10_000),
            ratio_sample(10_000, 10_000),
            ratio_sample(10_000, 11_499),
        ]
    )
    if module.noise_state(below["spread"]) != "conclusive":
        raise AssertionError(
            f"raw spread below 15% produced {below['spread']!r} "
            "without staying conclusive"
        )
    print("PASS  raw spread 14.99% remains conclusive")

    with tempfile.TemporaryDirectory(prefix="bench-stage-schema-") as raw:
        path = Path(raw) / "times"
        path.write_text("A\t1.000\t0.100\nB\t1.100\t0.100\nC\t1.200\t0.100\n", encoding="ascii")
        if module.parse_stage_timings(path) != {"A": 1000, "B": 1100, "C": 1200}:
            raise AssertionError("stage timing parser changed valid values")
        stage_mutants = {
            "missing stage": "A\t1.000\t0.100\nB\t1.100\t0.100\n",
            "duplicate stage": "A\t1.000\t0.100\nA\t1.100\t0.100\nC\t1.200\t0.100\n",
            "unknown stage": "A\t1.000\t0.100\nB\t1.100\t0.100\nD\t1.200\t0.100\n",
            "non-finite stage": "A\tNaN\t0.100\nB\t1.100\t0.100\nC\t1.200\t0.100\n",
        }
        for name, payload in stage_mutants.items():
            path.write_text(payload, encoding="ascii")
            try:
                module.parse_stage_timings(path)
            except module.BenchError:
                print(f"PASS  stage timings refuse {name}")
            else:
                raise AssertionError(f"stage timings accepted {name}")


def wait_for_ready(work: Path, names: Sequence[str]) -> dict[str, int]:
    paths = {name: work / f"ready.{name}" for name in names}
    deadline = time.monotonic() + 15
    while True:
        pids: dict[str, int] = {}
        for name, path in paths.items():
            try:
                raw = path.read_text(encoding="ascii")
                pid = int(raw)
            except (FileNotFoundError, OSError, ValueError):
                continue
            if pid > 0:
                pids[name] = pid
        if len(pids) == len(paths):
            return pids
        if time.monotonic() >= deadline:
            raise AssertionError(f"HeapTree roles did not become ready: {list(names)!r}")
        time.sleep(0.01)


def direct_starttime(pid: int) -> int:
    raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    close = raw.rfind(")")
    if close < 0:
        raise AssertionError(f"invalid independent stat for {pid}")
    fields = raw[close + 2 :].split()
    if len(fields) < 20:
        raise AssertionError(f"short independent stat for {pid}")
    return int(fields[19])


def direct_status(pid: int) -> dict[str, int]:
    values: dict[str, int] = {}
    for raw in Path(f"/proc/{pid}/status").read_text(encoding="ascii").splitlines():
        if ":" not in raw:
            continue
        key, rest = raw.split(":", 1)
        if key not in {"VmRSS", "VmHWM"}:
            continue
        fields = rest.split()
        if len(fields) != 2 or fields[1] != "kB":
            raise AssertionError(f"invalid independent {key} for {pid}")
        values[key] = int(fields[0]) * 1024
    if set(values) != {"VmRSS", "VmHWM"}:
        raise AssertionError(f"missing independent status values for {pid}")
    return values


def capture_tree_and_release(
    work: Path, oracle: dict[str, object], failures: list[BaseException]
) -> None:
    try:
        pids = wait_for_ready(work, ("parent", "child", "grandchild", "sibling"))
        statuses = {name: direct_status(pid) for name, pid in pids.items()}
        oracle["parent_identity"] = (pids["parent"], direct_starttime(pids["parent"]))
        oracle["parent_hwm"] = statuses["parent"]["VmHWM"]
        time.sleep(10)
    except BaseException as error:
        failures.append(error)
    finally:
        (work / "release.tree").touch()
        (work / "release.sibling").touch()


def capture_sum_and_release(
    work: Path, oracle: dict[str, int], failures: list[BaseException]
) -> None:
    try:
        pids = wait_for_ready(work, ("sum-parent", "sum-child"))
        statuses = [direct_status(pid) for pid in pids.values()]
        oracle["rss_sum"] = sum(status["VmRSS"] for status in statuses)
        oracle["max_rss"] = max(status["VmRSS"] for status in statuses)
        time.sleep(0.8)
    except BaseException as error:
        failures.append(error)
    finally:
        (work / "release.sum").touch()


def release_single(work: Path, failures: list[BaseException]) -> None:
    try:
        wait_for_ready(work, ("single",))
        time.sleep(0.5)
    except BaseException as error:
        failures.append(error)
    finally:
        (work / "release.single").touch()


def identity_is_live(identity: object) -> bool:
    try:
        raw = Path(f"/proc/{identity.pid}/stat").read_text(encoding="ascii")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return False
    close = raw.rfind(")")
    if close < 0:
        return False
    fields = raw[close + 2 :].split()
    if len(fields) < 20:
        return False
    try:
        starttime = int(fields[19])
    except ValueError:
        return False
    return starttime == identity.starttime and fields[0] not in {"X", "Z"}


def wait_identity_gone(identity: object, timeout: float = 3) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not identity_is_live(identity):
            return True
        time.sleep(0.01)
    return not identity_is_live(identity)


def force_cleanup(root: object | None) -> None:
    if root is None:
        return
    try:
        os.killpg(root.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        os.waitpid(root.pid, 0)
    except ChildProcessError:
        pass


def exception_cleanup_probe(
    module: ModuleType, classes: Path, java: Path, jcmd: Path, env: dict[str, str]
) -> bool:
    with tempfile.TemporaryDirectory(prefix="selfhost-bench-exception-") as raw:
        work = Path(raw)
        captured: dict[str, object] = {}

        def explode_on_child(view: object, root: object) -> str | None:
            captured["root"] = root
            role = module.heap_tree_classifier(view, root)
            if role == "child":
                captured["child"] = view.identity
                raise RuntimeError("forced sampler failure")
            return role

        raised = False
        try:
            module.profile_command(
                [java, "-Xmx64m", "-cp", classes, "HeapTree", "parent", work],
                cwd=ROOT,
                env=env,
                classifier=explode_on_child,
                expected_roles=("parent", "child", "grandchild"),
                java_roles=set(),
                jcmd=jcmd,
                timeout=20,
            )
        except RuntimeError as error:
            raised = str(error) == "forced sampler failure"
        finally:
            child = captured.get("child")
            child_gone = child is not None and wait_identity_gone(child)
            root = captured.get("root")
            root_gone = root is not None and wait_identity_gone(root)
            force_cleanup(root)
        return raised and child_gone and root_gone


def capture_failure_identities(
    module: ModuleType,
    work: Path,
    identities: dict[str, object],
    failures: list[BaseException],
) -> None:
    try:
        pids = wait_for_ready(work, ("failure-parent", "failure-child"))
        for name, pid in pids.items():
            stat = module.read_process_stat(pid)
            if stat is None:
                raise AssertionError(f"could not capture {name} identity")
            identities[name] = stat.identity
    except BaseException as error:
        failures.append(error)


def nonzero_cleanup_probe(
    module: ModuleType, classes: Path, java: Path, jcmd: Path, env: dict[str, str]
) -> bool:
    with tempfile.TemporaryDirectory(prefix="selfhost-bench-nonzero-") as raw:
        work = Path(raw)
        identities: dict[str, object] = {}
        failures: list[BaseException] = []
        observer = threading.Thread(
            target=capture_failure_identities,
            args=(module, work, identities, failures),
            daemon=True,
        )
        observer.start()
        result = None
        try:
            result = module.profile_command(
                [
                    java,
                    "-Xmx64m",
                    "-cp",
                    classes,
                    "HeapTree",
                    "failure-parent",
                    work,
                ],
                cwd=ROOT,
                env=env,
                classifier=module.heap_tree_classifier,
                expected_roles=("failure-parent", "failure-child"),
                java_roles=set(),
                jcmd=jcmd,
                timeout=20,
            )
            observer.join(timeout=5)
            child = identities.get("failure-child")
            root = identities.get("failure-parent")
            child_gone = child is not None and wait_identity_gone(child)
            root_gone = root is not None and wait_identity_gone(root)
        finally:
            (work / "release.failure").touch()
            force_cleanup(identities.get("failure-parent"))
            observer.join(timeout=5)
        if failures:
            raise failures[0]
        return (
            result is not None
            and result.returncode == 7
            and not observer.is_alive()
            and child_gone
            and root_gone
        )


def main_tree_probe(
    module: ModuleType, classes: Path, java: Path, jcmd: Path, env: dict[str, str]
) -> tuple[object, object, dict[str, object]]:
    with tempfile.TemporaryDirectory(prefix="selfhost-bench-tree-") as raw:
        work = Path(raw)
        sibling = subprocess.Popen(
            [java, "-Xmx96m", "-cp", classes, "HeapTree", "sibling", work],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        sibling_stat = None
        deadline = time.monotonic() + 2
        while sibling_stat is None and time.monotonic() < deadline:
            sibling_stat = module.read_process_stat(sibling.pid)
            time.sleep(0.001)
        if sibling_stat is None:
            raise AssertionError("could not observe sibling identity")
        oracle: dict[str, object] = {}
        failures: list[BaseException] = []
        releaser = threading.Thread(
            target=capture_tree_and_release,
            args=(work, oracle, failures),
            daemon=True,
        )
        releaser.start()
        try:
            result = module.profile_command(
                [java, "-Xmx64m", "-cp", classes, "HeapTree", "parent", work],
                cwd=ROOT,
                env=env,
                classifier=module.heap_tree_classifier,
                expected_roles=("parent", "child", "grandchild"),
                java_roles={"parent", "child", "grandchild"},
                jcmd=jcmd,
                timeout=20,
            )
        finally:
            (work / "release.tree").touch()
            (work / "release.sibling").touch()
            try:
                sibling.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(sibling.pid, signal.SIGKILL)
                sibling.wait(timeout=5)
            releaser.join(timeout=5)
        if failures:
            raise failures[0]
        if releaser.is_alive():
            raise AssertionError("tree releaser did not finish")
        if result.returncode != 0:
            raise AssertionError(
                f"HeapTree parent failed: {result.stdout!r} {result.stderr!r}"
            )
        return result, sibling_stat, oracle


def tree_sum_probe(
    module: ModuleType, classes: Path, java: Path, jcmd: Path, env: dict[str, str]
) -> bool:
    with tempfile.TemporaryDirectory(prefix="selfhost-bench-sum-") as raw:
        work = Path(raw)
        oracle: dict[str, int] = {}
        failures: list[BaseException] = []
        releaser = threading.Thread(
            target=capture_sum_and_release,
            args=(work, oracle, failures),
            daemon=True,
        )
        releaser.start()
        try:
            result = module.profile_command(
                [java, "-Xmx64m", "-cp", classes, "HeapTree", "sum-parent", work],
                cwd=ROOT,
                env=env,
                classifier=module.heap_tree_classifier,
                expected_roles=("sum-parent", "sum-child"),
                java_roles=set(),
                jcmd=jcmd,
                timeout=20,
            )
        finally:
            (work / "release.sum").touch()
            releaser.join(timeout=5)
        if failures:
            raise failures[0]
        return (
            result.returncode == 0
            and oracle["rss_sum"] > oracle["max_rss"]
            and result.tree_peak_rss_bytes >= oracle["rss_sum"]
        )


def overlap_probe(
    module: ModuleType, classes: Path, java: Path, jcmd: Path, env: dict[str, str]
) -> bool:
    with tempfile.TemporaryDirectory(prefix="selfhost-bench-overlap-") as raw:
        work = Path(raw)
        failures: list[BaseException] = []
        releaser = threading.Thread(
            target=release_single, args=(work, failures), daemon=True
        )
        releaser.start()
        try:
            result = module.profile_command(
                [java, "-Xmx64m", "-cp", classes, "HeapTree", "single", work],
                cwd=ROOT,
                env=env,
                classifier=module.heap_tree_classifier,
                expected_roles=("single", "missing"),
                java_roles=set(),
                jcmd=jcmd,
                timeout=20,
            )
        finally:
            (work / "release.single").touch()
            releaser.join(timeout=5)
        if failures:
            raise failures[0]
        return result.returncode == 0 and result.complete_overlap_samples == 0


def process_assertions(
    module: ModuleType, classes: Path, java: Path, jcmd: Path
) -> tuple[dict[str, bool], dict[str, object]]:
    env = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    env["JAVA_HOME"] = os.fspath(java.parent.parent)
    result, sibling_stat, oracle = main_tree_probe(module, classes, java, jcmd, env)
    recursive = (
        set(result.roles) == {"parent", "child", "grandchild"}
        and result.complete_overlap_samples > 0
        and sibling_stat.identity not in result.observed_identities
    )
    parent_heap = result.roles.get("parent", {}).get("max_heap_bytes")
    child_heap = result.roles.get("child", {}).get("max_heap_bytes")
    heap_exact = parent_heap == PARENT_HEAP_BYTES and child_heap == CHILD_HEAP_BYTES
    parent_pid, parent_starttime = oracle["parent_identity"]
    identity_exact = module.ProcessIdentity(parent_pid, parent_starttime)
    starttime_exact = identity_exact in result.observed_identities
    parent_hwm = result.roles.get("parent", {}).get("rss_hwm_bytes")
    hwm_exact = isinstance(parent_hwm, int) and parent_hwm >= oracle["parent_hwm"]
    scheduled = (
        result.sampling_attempts >= 20
        and result.sampling_attempts * 50_000_000 >= result.wall_time_ns
    )
    exception_cleanup = exception_cleanup_probe(module, classes, java, jcmd, env)
    nonzero_cleanup = nonzero_cleanup_probe(module, classes, java, jcmd, env)
    verdicts = {
        "bench.descendants_recursive": recursive,
        "bench.heap_exact": heap_exact,
        "bench.tree_rss_sums_simultaneous": tree_sum_probe(
            module, classes, java, jcmd, env
        ),
        "bench.overlap_requires_all_roles": overlap_probe(
            module, classes, java, jcmd, env
        ),
        "bench.sampling_targets_two_ms": scheduled,
        "bench.starttime_identity_preserved": starttime_exact,
        "bench.vmhwm_reads_proc": hwm_exact,
        "bench.exception_cleanup": exception_cleanup and nonzero_cleanup,
        "bench.identity_rechecks": identity_rechecks_probe(module),
        "bench.same_jdk": same_jdk_probe(module, java, jcmd),
        "bench.final_source_snapshot": final_source_snapshot_probe(module),
    }
    # What the sampler actually saw, so a failure can be read rather than
    # guessed at. Every number a verdict above compares is here, next to what
    # it was compared against.
    evidence = {
        "roles": {role: dict(metrics) for role, metrics in result.roles.items()},
        "roles_expected": sorted(("parent", "child", "grandchild")),
        "heap_expected": {
            "parent": PARENT_HEAP_BYTES,
            "child": CHILD_HEAP_BYTES,
        },
        "parent_hwm_floor": oracle["parent_hwm"],
        "sampling_attempts": result.sampling_attempts,
        "wall_time_ns": result.wall_time_ns,
        "complete_overlap_samples": result.complete_overlap_samples,
        "parent_identity_expected": repr(identity_exact),
        "identities_observed": sorted(repr(item) for item in result.observed_identities),
        "sibling_identity": repr(sibling_stat.identity),
    }
    return verdicts, evidence


def describe_failure(
    verdicts: Mapping[str, bool], evidence: Mapping[str, object]
) -> str:
    """The report for a failed run: which verdicts, and what was behind them.

    A bare `{name: False}` table is what this replaced, and it cost a whole
    diagnosis: `bench.heap_exact` went false once on a CI runner, could not be
    reproduced anywhere, and by then the two numbers it had compared were gone.
    Five of the eleven verdicts are computed from the one tree observation
    below; the other six each run their own probe, and for those the name is
    the whole of what there is to say.
    """
    failed = sorted(name for name, ok in verdicts.items() if not ok)
    if not failed:
        return ""
    return "real sampler failed: {}\nobserved: {}".format(
        ", ".join(failed),
        json.dumps(evidence, indent=2, sort_keys=True, default=repr),
    )


def failure_report_selftest() -> None:
    if describe_failure(dict.fromkeys(ASSERTIONS, True), {"roles": {}}):
        raise AssertionError("a run with nothing failed must report nothing")
    verdicts = {**dict.fromkeys(ASSERTIONS, True), "bench.heap_exact": False}
    evidence = {
        "roles": {"parent": {"max_heap_bytes": 67108863}},
        "heap_expected": {"parent": PARENT_HEAP_BYTES},
    }
    report = describe_failure(verdicts, evidence)
    for needle in ("bench.heap_exact", "67108863", str(PARENT_HEAP_BYTES)):
        if needle not in report:
            raise AssertionError(f"the failure report does not name {needle}: {report}")
    if "bench.same_jdk" in report:
        raise AssertionError(f"the failure report named a passing verdict: {report}")
    print("PASS  a failed verdict is reported with the numbers behind it")


def sequence_reader(values: Sequence[object]):
    remaining = iter(values)

    def read(pid: int) -> object:
        del pid
        return next(remaining)

    return read


def identity_rechecks_probe(module: ModuleType) -> bool:
    identity = module.ProcessIdentity(4242, 100)
    same = module.ProcessStat(identity, 1)
    changed = module.ProcessStat(module.ProcessIdentity(4242, 101), 1)
    status_calls = 0
    cmdline_calls = 0

    def status_reader(pid: int) -> tuple[int, int, int]:
        nonlocal status_calls
        del pid
        status_calls += 1
        return 10, 20, 30

    def cmdline_reader(pid: int) -> tuple[str, ...]:
        nonlocal cmdline_calls
        del pid
        cmdline_calls += 1
        return ("java",)

    before_status = module.read_stable_process_view(
        same,
        identity_reader=sequence_reader((changed,)),
        status_reader=status_reader,
        cmdline_reader=cmdline_reader,
    )
    if before_status is not None or status_calls != 0 or cmdline_calls != 0:
        return False

    after_status = module.read_stable_process_view(
        same,
        identity_reader=sequence_reader((same, changed)),
        status_reader=status_reader,
        cmdline_reader=cmdline_reader,
    )
    if after_status is not None or status_calls != 1 or cmdline_calls != 0:
        return False

    after_cmdline = module.read_stable_process_view(
        same,
        identity_reader=sequence_reader((same, same, changed)),
        status_reader=status_reader,
        cmdline_reader=cmdline_reader,
    )
    if after_cmdline is not None or status_calls != 2 or cmdline_calls != 1:
        return False

    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="-XX:MaxHeapSize=67108864\n", stderr=""
    )

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return completed

    try:
        module.query_max_heap(
            Path("/contract/jcmd"),
            identity,
            identity_reader=sequence_reader((same, changed)),
            runner=runner,
        )
    except module.BenchError:
        return True
    return False


def same_jdk_probe(module: ModuleType, java: Path, jcmd: Path) -> bool:
    rejected = False
    try:
        module.reject_pollution({"JAVA_HOME": "/tmp/fake-java-home"})
    except module.BenchError:
        rejected = True
    toolchain = module.Toolchain(
        java=java.resolve(),
        jcmd=jcmd.resolve(),
        java_version="contract java",
        java_runtime="contract runtime",
    )
    env = module.measurement_environment(toolchain)
    launcher_java = (Path(env["JAVA_HOME"]) / "bin/java").resolve()
    return rejected and launcher_java == toolchain.java


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def initialize_contract_repo(root: Path) -> str:
    git("init", "-q", cwd=root)
    git("config", "user.name", "Contract", cwd=root)
    git("config", "user.email", "contract@example.invalid", cwd=root)
    (root / "tracked.txt").write_text("one\n", encoding="ascii")
    git("add", "tracked.txt", cwd=root)
    git("commit", "-q", "-m", "Initialize contract repository", cwd=root)
    return git("rev-parse", "HEAD", cwd=root)


def final_source_snapshot_probe(module: ModuleType) -> bool:
    measured = valid_baseline(module)
    options = module.Options("record", 3, 5, 3)
    cases = ("tracked", "untracked", "head")
    passed = True
    for case in cases:
        with tempfile.TemporaryDirectory(prefix=f"selfhost-bench-snapshot-{case}-") as raw:
            root = Path(raw)
            expected = initialize_contract_repo(root)
            baseline_path = root / "baseline.json"
            baseline_path.write_text("sentinel\n", encoding="ascii")
            if case == "tracked":
                (root / "tracked.txt").write_text("changed\n", encoding="ascii")
            elif case == "untracked":
                (root / "untracked.txt").write_text("new\n", encoding="ascii")
            else:
                (root / "tracked.txt").write_text("two\n", encoding="ascii")
                git("add", "tracked.txt", cwd=root)
                git("commit", "-q", "-m", "Advance contract repository", cwd=root)
            output = io.StringIO()
            errors = io.StringIO()
            try:
                with redirect_stdout(output), redirect_stderr(errors):
                    module.publish_measurement(
                        options,
                        expected,
                        measured,
                        None,
                        root=root,
                        baseline_path=baseline_path,
                    )
            except module.BenchError:
                refused = True
            else:
                refused = False
            if not refused:
                passed = False
            if output.getvalue() or errors.getvalue():
                passed = False
            if baseline_path.read_text(encoding="ascii") != "sentinel\n":
                passed = False
    return passed


def compile_fixture(toolchain: object, work: Path) -> Path:
    javac = toolchain.java.parent / "javac"
    if not javac.is_file():
        raise AssertionError(f"same-JDK javac is missing beside {toolchain.java}")
    classes = work / "classes"
    classes.mkdir()
    subprocess.run(
        [os.fspath(javac), "-d", os.fspath(classes), os.fspath(HERE / "HeapTree.java")],
        check=True,
        cwd=ROOT,
    )
    return classes


def mutation_contract(
    module: ModuleType,
    matrix: dict[tuple[str, str], tuple[str, ...]],
    mutations: Sequence[str],
) -> None:
    toolchain = module.resolve_toolchain()
    with tempfile.TemporaryDirectory(prefix="selfhost-bench-contract-") as raw:
        work = Path(raw)
        classes = compile_fixture(toolchain, work)
        baseline, evidence = process_assertions(
            module, classes, toolchain.java, toolchain.jcmd
        )
        report = describe_failure(baseline, evidence)
        if report:
            raise AssertionError(report)
        for assertion in ASSERTIONS:
            print(f"PASS  {assertion}")

        for mutation in mutations:
            source = work / f"{mutation}.py"
            shutil.copy2(BENCH, source)
            subprocess.run(
                [sys.executable, os.fspath(MUTATE), mutation, os.fspath(source)],
                check=True,
                cwd=ROOT,
            )
            subprocess.run(
                [sys.executable, "-m", "py_compile", os.fspath(source)],
                check=True,
                cwd=ROOT,
            )
            mutant = load_module(source, "selfhost_bench_mutant_" + mutation.replace("-", "_"))
            observed, _ = process_assertions(
                mutant, classes, toolchain.java, toolchain.jcmd
            )
            if set(observed) != set(ASSERTIONS):
                raise AssertionError(
                    f"{mutation} ran {sorted(observed)}, expected {sorted(ASSERTIONS)}"
                )
            reds = {name for name, passed in observed.items() if not passed}
            expected_reds = {matrix[("red", mutation)][0]}
            if reds != expected_reds:
                raise AssertionError(
                    f"{mutation} red set is {sorted(reds)}, expected {sorted(expected_reds)}"
                )
            owner = matrix[("owner", mutation)][0]
            control = matrix[("control", mutation)][0]
            if owner not in reds or not observed[control]:
                raise AssertionError(f"{mutation} did not keep owner/control unique")
            print(f"PASS  {mutation} turns only {owner} red")


def shell_contract() -> None:
    help_result = subprocess.run(
        [ROOT / "scripts/selfhost-bench.sh", "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if help_result.returncode != 0 or not help_result.stdout.startswith("usage:"):
        raise AssertionError("shell entry did not return strict help")
    conflict = subprocess.run(
        [ROOT / "scripts/selfhost-bench.sh", "--record", "--check"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if conflict.returncode != 2 or "conflicting modes" not in conflict.stderr:
        raise AssertionError("shell entry did not preserve CLI exit 2")
    print("PASS  shell entry preserves strict help and usage failure")


def main() -> int:
    synthetic_only = sys.argv[1:] == ["--synthetic-only"]
    if sys.argv[1:] not in ([], ["--synthetic-only"]):
        raise SystemExit("usage: run.py [--synthetic-only]")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    module = load_module(BENCH, "selfhost_bench_contract_target")
    mutations = mutator_keys()
    matrix_text = MATRIX.read_text(encoding="utf-8")
    matrix_selftest(matrix_text, mutations)
    matrix = parse_matrix(matrix_text, mutations)
    failure_report_selftest()
    schema_contract(module)
    shell_contract()
    mutation_contract(module, matrix, mutations)
    if not synthetic_only:
        module.load_baseline(ROOT / "scripts/selfhost-bench.baseline")
        print("PASS  tracked compiler-weight baseline satisfies the strict schema")
    print("OK: compiler-weight schema, synthetic probe and mutant matrix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
