#!/usr/bin/env python3
"""Exercise strict schema, recursive /proc sampling, and source mutants."""

from __future__ import annotations

import copy
import importlib.util
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


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BENCH = ROOT / "scripts/selfhost-bench.py"
MATRIX = HERE / "matrix.txt"
MUTATE = HERE / "mutate.py"
MUTATIONS = ("descendants-one-hop", "heap-mismatch-passes")
ASSERTIONS = ("bench.descendants_recursive", "bench.heap_exact")
EXPECTED = {
    ("role", "descendants-one-hop"): ("counted",),
    ("owner", "descendants-one-hop"): ("bench.descendants_recursive",),
    ("red", "descendants-one-hop"): ("bench.descendants_recursive",),
    ("control", "descendants-one-hop"): ("bench.heap_exact",),
    ("role", "heap-mismatch-passes"): ("counted",),
    ("owner", "heap-mismatch-passes"): ("bench.heap_exact",),
    ("red", "heap-mismatch-passes"): ("bench.heap_exact",),
    ("control", "heap-mismatch-passes"): ("bench.descendants_recursive",),
}


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


def parse_matrix(text: str) -> dict[tuple[str, str], tuple[str, ...]]:
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
        if mutation not in MUTATIONS:
            raise MatrixError(f"line {line_number}: unknown mutation {mutation!r}")
        key = (record, mutation)
        if key in records:
            raise MatrixError(f"line {line_number}: duplicate {record} for {mutation}")
        records[key] = tuple(values)
    missing = set(EXPECTED) - set(records)
    unknown = set(records) - set(EXPECTED)
    if missing:
        raise MatrixError(f"missing records: {sorted(missing)!r}")
    if unknown:
        raise MatrixError(f"unknown records: {sorted(unknown)!r}")
    for key, expected in EXPECTED.items():
        if records[key] != expected:
            raise MatrixError(
                f"{key[0]} for {key[1]} is {records[key]!r}, expected {expected!r}"
            )
    return records


def matrix_selftest(text: str) -> None:
    parse_matrix(text)
    lines = text.splitlines()
    first = next(line for line in lines if line and not line.startswith("#"))
    mutants = {
        "unknown record": text.replace("role\t", "scope\t", 1),
        "duplicate record": text + first + "\n",
        "missing record": "\n".join(lines[:-1]) + "\n",
        "changed owner": text.replace(
            "owner\tdescendants-one-hop\tbench.descendants_recursive",
            "owner\tdescendants-one-hop\tbench.heap_exact",
        ),
    }
    for name, mutant in mutants.items():
        try:
            parse_matrix(mutant)
        except MatrixError:
            print(f"PASS  matrix refuses {name}")
        else:
            raise AssertionError(f"matrix accepted {name}")


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
            "proc_interval_ms": 2.0,
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


def wait_and_release(work: Path, failure: list[BaseException]) -> None:
    try:
        required = [work / f"ready.{name}" for name in ("parent", "child", "grandchild", "sibling")]
        deadline = time.monotonic() + 15
        while not all(path.is_file() for path in required):
            if time.monotonic() >= deadline:
                raise AssertionError("HeapTree roles did not all become ready")
            time.sleep(0.01)
        time.sleep(2)
        (work / "release.tree").touch()
        (work / "release.sibling").touch()
    except BaseException as error:
        failure.append(error)
        (work / "release.tree").touch()
        (work / "release.sibling").touch()


def process_assertions(module: ModuleType, classes: Path, java: Path, jcmd: Path) -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="selfhost-bench-proc-") as raw:
        work = Path(raw)
        sibling = subprocess.Popen(
            [
                os.fspath(java),
                "-Xmx96m",
                "-cp",
                os.fspath(classes),
                "HeapTree",
                "sibling",
                os.fspath(work),
            ],
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
        failures: list[BaseException] = []
        releaser = threading.Thread(
            target=wait_and_release, args=(work, failures), daemon=True
        )
        releaser.start()
        try:
            result = module.profile_command(
                [
                    java,
                    "-Xmx64m",
                    "-cp",
                    classes,
                    "HeapTree",
                    "parent",
                    work,
                ],
                cwd=ROOT,
                env={**os.environ, "LC_ALL": "C", "LANG": "C"},
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
        if result.returncode != 0:
            raise AssertionError(
                f"HeapTree parent failed: {result.stdout!r} {result.stderr!r}"
            )
        recursive = (
            set(result.roles) == {"parent", "child", "grandchild"}
            and result.complete_overlap_samples > 0
            and sibling_stat.identity not in result.observed_identities
        )
        parent_heap = result.roles.get("parent", {}).get("max_heap_bytes")
        child_heap = result.roles.get("child", {}).get("max_heap_bytes")
        heap_exact = (
            isinstance(parent_heap, int)
            and isinstance(child_heap, int)
            and module.heap_matches_expected(parent_heap, 64 * 1024 * 1024)
            and module.heap_matches_expected(child_heap, 96 * 1024 * 1024)
            and not module.heap_matches_expected(child_heap, 64 * 1024 * 1024)
        )
        return {
            "bench.descendants_recursive": recursive,
            "bench.heap_exact": heap_exact,
        }


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


def mutation_contract(module: ModuleType, matrix: dict[tuple[str, str], tuple[str, ...]]) -> None:
    toolchain = module.resolve_toolchain()
    with tempfile.TemporaryDirectory(prefix="selfhost-bench-contract-") as raw:
        work = Path(raw)
        classes = compile_fixture(toolchain, work)
        baseline = process_assertions(module, classes, toolchain.java, toolchain.jcmd)
        if not all(baseline.values()):
            raise AssertionError(f"real sampler failed its assertions: {baseline!r}")
        for assertion in ASSERTIONS:
            print(f"PASS  {assertion}")

        for mutation in MUTATIONS:
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
            observed = process_assertions(mutant, classes, toolchain.java, toolchain.jcmd)
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
    matrix_text = MATRIX.read_text(encoding="utf-8")
    matrix_selftest(matrix_text)
    matrix = parse_matrix(matrix_text)
    schema_contract(module)
    shell_contract()
    mutation_contract(module, matrix)
    if not synthetic_only:
        module.load_baseline(ROOT / "scripts/selfhost-bench.baseline")
        print("PASS  tracked compiler-weight baseline satisfies the strict schema")
    print("OK: compiler-weight schema, synthetic probe and mutant matrix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
