#!/usr/bin/env python3
"""Record and compare reproducible compiler-weight telemetry."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts/selfhost-bench.baseline"
SCHEMA = 1
KIND = "dawn-compiler-weight-baseline"

# The JVM options the toolchain actually ships with, repeated here because this
# script forks the release jar directly and never goes through bin/dawn. Keep
# identical to bin/dawn's DAWN_JVM_OPTS default and to child_java_cmd() in
# selfhost/src/main.dawn; a flag added there and not here leaves the recorded
# baseline measuring a configuration nobody runs, indefinitely and without any
# signal that it has. That is not hypothetical: the baseline replaced on
# 2026-08-17 had been describing a heap ceiling the tree stopped using five days
# earlier.
TOOLCHAIN_JVM_OPTS = ("-Xss512m", "-Xmx2g", "-XX:+UseSerialGC")

PROC_INTERVAL_NS = 2_000_000
MEASUREMENT_LOCALE = "C.UTF-8"
NOISE_THRESHOLD = 0.15
BOOTSTRAP_TOLERANCE = 0.15
DEFAULT_WEIGHT_SAMPLES = 3
DEFAULT_STARTUP_SAMPLES = 11
DEFAULT_MAX_ROUNDS = 3
MIN_WEIGHT_SAMPLES = 3
MIN_STARTUP_SAMPLES = 5
MAX_ROUNDS = 3
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
DESCENDANT_DEPTH_LIMIT: int | None = None

WORKLOAD_ROLES = {
    "jvm_build_fib": ("compiler",),
    "native_build_fib": ("native_compiler",),
    "test_stdlib": ("compiler", "test_main"),
    "test_selfhost": ("compiler", "dependency_reexec", "test_main"),
}
JAVA_ROLES = {"compiler", "dependency_reexec", "test_main"}
STARTUP_TARGETS = ("direct_jar", "bin_dawn", "native_compiler")
POLLUTING_ENV = (
    "DAWN_SEED",
    "DAWN_SEED_CACHE",
    "DAWN_SEED_ALLOW_UNVERIFIED",
    "DAWN_JVM_OPTS",
    "DAWN_SELFHOST_CP",
    "DAWN_PKG_CACHE",
    "DAWN_MAVEN_MIRROR",
    "DAWNC_BIN",
    "DAWN_INTERNAL_RELEASE_STAGE_TIMINGS",
    "JAVA_TOOL_OPTIONS",
    "JDK_JAVA_OPTIONS",
    "_JAVA_OPTIONS",
    "JAVA_HOME",
    "CLASSPATH",
    "COURSIER_CACHE",
    "CC",
    "CFLAGS",
    "LDFLAGS",
)

USAGE = """usage: scripts/selfhost-bench.sh [--measure | --record | --check]
       [--weight-samples N] [--startup-samples N] [--max-rounds N]

exit 0: success, 1: ratio budget failure, 2: usage/preflight failure,
exit 3: bootstrap noise is inconclusive
"""


class BenchError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class SchemaError(ValueError):
    pass


class CliError(ValueError):
    pass


class Inconclusive(BenchError):
    def __init__(self, rounds: list[dict[str, object]]) -> None:
        self.rounds = rounds
        super().__init__("bootstrap ratio remained inconclusive", 3)


@dataclass(frozen=True)
class Options:
    mode: str
    weight_samples: int
    startup_samples: int
    max_rounds: int


@dataclass(frozen=True)
class Toolchain:
    java: Path
    jcmd: Path
    java_version: str
    java_runtime: str


@dataclass(frozen=True)
class Preflight:
    commit: str
    seed_tag: str
    seed_path: Path
    seed_sha256: str
    toolchain: Toolchain


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    starttime: int


@dataclass(frozen=True)
class ProcessStat:
    identity: ProcessIdentity
    parent_pid: int


@dataclass(frozen=True)
class ProcessView:
    identity: ProcessIdentity
    parent_pid: int
    argv: tuple[str, ...]
    rss_bytes: int
    hwm_bytes: int
    peak_bytes: int


@dataclass
class RoleObservation:
    hwm_bytes: int = 0
    peak_bytes: int = 0


@dataclass(frozen=True)
class ProfileResult:
    returncode: int
    stdout: str
    stderr: str
    wall_time_ns: int
    tree_peak_rss_bytes: int
    complete_overlap_samples: int
    sampling_attempts: int
    roles: dict[str, dict[str, int | None]]
    observed_identities: frozenset[ProcessIdentity]


def parse_count(name: str, raw: str, minimum: int, odd: bool = True) -> int:
    if not re.fullmatch(r"[0-9]+", raw):
        raise CliError(f"{name} must be a decimal integer")
    value = int(raw)
    if value < minimum:
        raise CliError(f"{name} must be at least {minimum}")
    if odd and value % 2 == 0:
        raise CliError(f"{name} must be odd")
    return value


def parse_cli(argv: Sequence[str]) -> Options:
    mode = "measure"
    explicit_mode: str | None = None
    values = {
        "weight_samples": DEFAULT_WEIGHT_SAMPLES,
        "startup_samples": DEFAULT_STARTUP_SAMPLES,
        "max_rounds": DEFAULT_MAX_ROUNDS,
    }
    seen_options: set[str] = set()
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in {"--measure", "--record", "--check"}:
            selected = token[2:]
            if explicit_mode is not None:
                raise CliError(
                    f"conflicting modes: --{explicit_mode} and --{selected}"
                )
            explicit_mode = selected
            mode = selected
            index += 1
            continue
        option_map = {
            "--weight-samples": ("weight_samples", MIN_WEIGHT_SAMPLES, True),
            "--startup-samples": ("startup_samples", MIN_STARTUP_SAMPLES, True),
            "--max-rounds": ("max_rounds", 1, False),
        }
        if token not in option_map:
            raise CliError(f"unknown argument: {token}")
        key, minimum, odd = option_map[token]
        if key in seen_options:
            raise CliError(f"duplicate option: {token}")
        seen_options.add(key)
        if index + 1 >= len(argv):
            raise CliError(f"{token} requires a value")
        value = parse_count(token, argv[index + 1], minimum, odd)
        if key == "max_rounds" and value > MAX_ROUNDS:
            raise CliError(f"--max-rounds cannot exceed {MAX_ROUNDS}")
        values[key] = value
        index += 2
    return Options(mode=mode, **values)


def reject_constant(value: str) -> object:
    raise SchemaError(f"non-finite JSON number {value!r} is forbidden")


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SchemaError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_json_strict(text: str) -> object:
    try:
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as error:
        raise SchemaError(f"invalid JSON: {error.msg}") from error
    return value


def require_object(
    value: object, expected: set[str], where: str
) -> dict[str, object]:
    if type(value) is not dict:
        raise SchemaError(f"{where} must be an object")
    actual = set(value)
    missing = expected - actual
    unknown = actual - expected
    if missing:
        raise SchemaError(f"{where} is missing {', '.join(sorted(missing))}")
    if unknown:
        raise SchemaError(f"{where} has unknown {', '.join(sorted(unknown))}")
    return value


def require_list(value: object, where: str) -> list[object]:
    if type(value) is not list:
        raise SchemaError(f"{where} must be an array")
    return value


def require_string(value: object, where: str) -> str:
    if type(value) is not str or not value:
        raise SchemaError(f"{where} must be a non-empty string")
    return value


def require_positive_int(value: object, where: str) -> int:
    if type(value) is not int or value <= 0:
        raise SchemaError(f"{where} must be a positive integer")
    return value


def require_nonnegative_int(value: object, where: str) -> int:
    if type(value) is not int or value < 0:
        raise SchemaError(f"{where} must be a non-negative integer")
    return value


def require_finite_positive(value: object, where: str) -> float:
    if type(value) not in {int, float}:
        raise SchemaError(f"{where} must be a number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise SchemaError(f"{where} must be finite and positive")
    return number


def require_finite_nonnegative(value: object, where: str) -> float:
    if type(value) not in {int, float}:
        raise SchemaError(f"{where} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise SchemaError(f"{where} must be finite and non-negative")
    return number


def require_close(actual: object, expected: float, where: str) -> None:
    number = require_finite_nonnegative(actual, where)
    if not math.isclose(number, expected, rel_tol=1e-12, abs_tol=1e-12):
        raise SchemaError(f"{where} is {number}, recomputed value is {expected}")


def median_int(values: Sequence[int]) -> int:
    if not values or len(values) % 2 == 0:
        raise ValueError("median_int requires a non-empty odd sample")
    return int(statistics.median(values))


def ratio_summary(samples: Sequence[Mapping[str, object]]) -> dict[str, object]:
    exact: list[tuple[Fraction, Mapping[str, object]]] = []
    for sample in samples:
        pass_a = sample["pass_a_user_ms"]
        pass_c = sample["pass_c_user_ms"]
        if type(pass_a) is not int or pass_a <= 0:
            raise ValueError("pass A user CPU must be a positive integer")
        if type(pass_c) is not int or pass_c <= 0:
            raise ValueError("pass C user CPU must be a positive integer")
        exact.append((Fraction(pass_c, pass_a), sample))
    ordered = sorted(exact, key=lambda row: row[0])
    median_ratio_exact, median_sample = ordered[len(ordered) // 2]
    spread_exact = (ordered[-1][0] - ordered[0][0]) / median_ratio_exact
    return {
        "median_ratio": float(median_ratio_exact),
        "spread": float(spread_exact),
        "median_pass_a_user_ms": int(median_sample["pass_a_user_ms"]),
        "median_pass_c_user_ms": int(median_sample["pass_c_user_ms"]),
    }


def noise_state(spread: float) -> str:
    if not math.isfinite(spread) or spread < 0:
        raise ValueError("spread must be finite and non-negative")
    return "inconclusive" if spread >= NOISE_THRESHOLD else "conclusive"


def summarize_role_samples(
    samples: Sequence[Mapping[str, object]], role: str
) -> dict[str, int | None]:
    role_rows = [sample["roles"][role] for sample in samples]
    heaps = [row["max_heap_bytes"] for row in role_rows]
    if all(heap is None for heap in heaps):
        median_heap: int | None = None
    elif any(heap is None for heap in heaps):
        raise ValueError(f"mixed heap presence for role {role}")
    else:
        median_heap = median_int([int(heap) for heap in heaps])
    return {
        "rss_hwm_bytes": median_int(
            [int(row["rss_hwm_bytes"]) for row in role_rows]
        ),
        "vas_peak_bytes": median_int(
            [int(row["vas_peak_bytes"]) for row in role_rows]
        ),
        "max_heap_bytes": median_heap,
    }


def workload_summary(
    samples: Sequence[Mapping[str, object]], roles: Sequence[str]
) -> dict[str, object]:
    return {
        "median_wall_time_ns": median_int(
            [int(sample["wall_time_ns"]) for sample in samples]
        ),
        "median_tree_peak_rss_bytes": median_int(
            [int(sample["tree_peak_rss_bytes"]) for sample in samples]
        ),
        "roles": {
            role: summarize_role_samples(samples, role) for role in roles
        },
    }


def validate_ratio_round(
    value: object, weight_samples: int, where: str
) -> dict[str, object]:
    obj = require_object(value, {"samples", "summary", "status"}, where)
    samples = require_list(obj["samples"], f"{where}.samples")
    if len(samples) != weight_samples:
        raise SchemaError(
            f"{where}.samples has {len(samples)} rows, expected {weight_samples}"
        )
    checked: list[dict[str, object]] = []
    for index, raw in enumerate(samples):
        sample_where = f"{where}.samples[{index}]"
        sample = require_object(
            raw,
            {
                "pass_a_user_ms",
                "pass_b_user_ms",
                "pass_c_user_ms",
                "ratio",
            },
            sample_where,
        )
        pass_a = require_positive_int(
            sample["pass_a_user_ms"], f"{sample_where}.pass_a_user_ms"
        )
        require_positive_int(
            sample["pass_b_user_ms"], f"{sample_where}.pass_b_user_ms"
        )
        pass_c = require_positive_int(
            sample["pass_c_user_ms"], f"{sample_where}.pass_c_user_ms"
        )
        ratio = require_finite_positive(sample["ratio"], f"{sample_where}.ratio")
        expected_ratio = pass_c / pass_a
        if not math.isclose(ratio, expected_ratio, rel_tol=1e-12, abs_tol=1e-12):
            raise SchemaError(
                f"{sample_where}.ratio is {ratio}, recomputed value is {expected_ratio}"
            )
        checked.append(sample)
    expected_summary = ratio_summary(checked)
    summary = require_object(
        obj["summary"],
        {
            "median_ratio",
            "spread",
            "median_pass_a_user_ms",
            "median_pass_c_user_ms",
        },
        f"{where}.summary",
    )
    require_close(
        summary["median_ratio"],
        float(expected_summary["median_ratio"]),
        f"{where}.summary.median_ratio",
    )
    require_close(
        summary["spread"],
        float(expected_summary["spread"]),
        f"{where}.summary.spread",
    )
    for field in ("median_pass_a_user_ms", "median_pass_c_user_ms"):
        actual = require_positive_int(summary[field], f"{where}.summary.{field}")
        if actual != expected_summary[field]:
            raise SchemaError(
                f"{where}.summary.{field} is {actual}, "
                f"recomputed value is {expected_summary[field]}"
            )
    status = require_string(obj["status"], f"{where}.status")
    expected_status = noise_state(float(expected_summary["spread"]))
    if status != expected_status:
        raise SchemaError(
            f"{where}.status is {status!r}, recomputed value is {expected_status!r}"
        )
    return obj


def validate_role_metric(
    value: object, where: str, java_role: bool, summary: bool
) -> dict[str, object]:
    expected = {"rss_hwm_bytes", "vas_peak_bytes", "max_heap_bytes"}
    if not summary:
        expected.add("process_count")
    obj = require_object(value, expected, where)
    if not summary:
        count = require_positive_int(obj["process_count"], f"{where}.process_count")
        if count != 1:
            raise SchemaError(f"{where}.process_count must be exactly 1")
    require_positive_int(obj["rss_hwm_bytes"], f"{where}.rss_hwm_bytes")
    require_positive_int(obj["vas_peak_bytes"], f"{where}.vas_peak_bytes")
    heap = obj["max_heap_bytes"]
    if java_role:
        require_positive_int(heap, f"{where}.max_heap_bytes")
    elif heap is not None:
        raise SchemaError(f"{where}.max_heap_bytes must be null for a native role")
    return obj


def validate_workload(
    name: str, value: object, weight_samples: int
) -> dict[str, object]:
    where = f"workloads.{name}"
    obj = require_object(value, {"expected_roles", "samples", "summary"}, where)
    roles_raw = require_list(obj["expected_roles"], f"{where}.expected_roles")
    roles = tuple(require_string(role, f"{where}.expected_roles") for role in roles_raw)
    if roles != WORKLOAD_ROLES[name]:
        raise SchemaError(
            f"{where}.expected_roles is {roles!r}, expected {WORKLOAD_ROLES[name]!r}"
        )
    samples = require_list(obj["samples"], f"{where}.samples")
    if len(samples) != weight_samples:
        raise SchemaError(
            f"{where}.samples has {len(samples)} rows, expected {weight_samples}"
        )
    checked_samples: list[dict[str, object]] = []
    for index, raw in enumerate(samples):
        sample_where = f"{where}.samples[{index}]"
        sample = require_object(
            raw,
            {
                "wall_time_ns",
                "tree_peak_rss_bytes",
                "complete_overlap_samples",
                "roles",
            },
            sample_where,
        )
        require_positive_int(sample["wall_time_ns"], f"{sample_where}.wall_time_ns")
        require_positive_int(
            sample["tree_peak_rss_bytes"], f"{sample_where}.tree_peak_rss_bytes"
        )
        require_positive_int(
            sample["complete_overlap_samples"],
            f"{sample_where}.complete_overlap_samples",
        )
        role_map = require_object(sample["roles"], set(roles), f"{sample_where}.roles")
        for role in roles:
            validate_role_metric(
                role_map[role],
                f"{sample_where}.roles.{role}",
                role in JAVA_ROLES,
                False,
            )
        checked_samples.append(sample)
    expected_summary = workload_summary(checked_samples, roles)
    summary = require_object(
        obj["summary"],
        {"median_wall_time_ns", "median_tree_peak_rss_bytes", "roles"},
        f"{where}.summary",
    )
    for field in ("median_wall_time_ns", "median_tree_peak_rss_bytes"):
        actual = require_positive_int(summary[field], f"{where}.summary.{field}")
        if actual != expected_summary[field]:
            raise SchemaError(
                f"{where}.summary.{field} is {actual}, "
                f"recomputed value is {expected_summary[field]}"
            )
    summary_roles = require_object(
        summary["roles"], set(roles), f"{where}.summary.roles"
    )
    for role in roles:
        checked = validate_role_metric(
            summary_roles[role],
            f"{where}.summary.roles.{role}",
            role in JAVA_ROLES,
            True,
        )
        if checked != expected_summary["roles"][role]:
            raise SchemaError(
                f"{where}.summary.roles.{role} does not match raw samples"
            )
    return obj


def validate_startup(
    name: str, value: object, startup_samples: int
) -> dict[str, object]:
    where = f"startup.{name}"
    obj = require_object(value, {"samples_ns", "median_ns"}, where)
    raw_samples = require_list(obj["samples_ns"], f"{where}.samples_ns")
    if len(raw_samples) != startup_samples:
        raise SchemaError(
            f"{where}.samples_ns has {len(raw_samples)} rows, "
            f"expected {startup_samples}"
        )
    samples = [
        require_positive_int(sample, f"{where}.samples_ns[{index}]")
        for index, sample in enumerate(raw_samples)
    ]
    actual = require_positive_int(obj["median_ns"], f"{where}.median_ns")
    expected = median_int(samples)
    if actual != expected:
        raise SchemaError(f"{where}.median_ns is {actual}, recomputed value is {expected}")
    return obj


def validate_baseline_data(value: object) -> dict[str, object]:
    top = require_object(
        value,
        {
            "schema",
            "kind",
            "recorded_at_utc",
            "source",
            "platform",
            "seed",
            "parameters",
            "artifacts",
            "bootstrap_cpu",
            "workloads",
            "startup",
        },
        "baseline",
    )
    if top["schema"] != SCHEMA or type(top["schema"]) is not int:
        raise SchemaError(f"baseline.schema must be {SCHEMA}")
    if top["kind"] != KIND:
        raise SchemaError(f"baseline.kind must be {KIND!r}")
    recorded = require_string(top["recorded_at_utc"], "baseline.recorded_at_utc")
    try:
        parsed_time = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
    except ValueError as error:
        raise SchemaError("baseline.recorded_at_utc is not ISO-8601") from error
    if parsed_time.tzinfo is None or parsed_time.utcoffset() != timezone.utc.utcoffset(None):
        raise SchemaError("baseline.recorded_at_utc must carry UTC")

    source = require_object(top["source"], {"commit", "tree"}, "source")
    commit = require_string(source["commit"], "source.commit")
    if not COMMIT_RE.fullmatch(commit):
        raise SchemaError("source.commit must be a full lowercase Git hash")
    if source["tree"] != "clean":
        raise SchemaError("source.tree must be 'clean'")

    platform_obj = require_object(
        top["platform"],
        {"system", "machine", "kernel", "locale", "java_version", "java_runtime"},
        "platform",
    )
    for key in platform_obj:
        require_string(platform_obj[key], f"platform.{key}")
    if platform_obj["system"] != "Linux" or platform_obj["machine"] != "x86_64":
        raise SchemaError("baseline platform must be Linux x86_64")
    if platform_obj["locale"] != MEASUREMENT_LOCALE:
        raise SchemaError(f"baseline locale must be {MEASUREMENT_LOCALE}")

    seed = require_object(top["seed"], {"tag", "sha256"}, "seed")
    tag = require_string(seed["tag"], "seed.tag")
    if not TAG_RE.fullmatch(tag):
        raise SchemaError("seed.tag has an invalid release spelling")
    seed_sha = require_string(seed["sha256"], "seed.sha256")
    if not HASH_RE.fullmatch(seed_sha):
        raise SchemaError("seed.sha256 must be a lowercase SHA-256 digest")

    parameters = require_object(
        top["parameters"],
        {
            "weight_samples",
            "startup_samples",
            "max_rounds",
            "proc_interval_ms",
            "noise_threshold",
            "bootstrap_ratio_tolerance",
        },
        "parameters",
    )
    weight_samples = require_positive_int(
        parameters["weight_samples"], "parameters.weight_samples"
    )
    startup_samples = require_positive_int(
        parameters["startup_samples"], "parameters.startup_samples"
    )
    max_rounds = require_positive_int(parameters["max_rounds"], "parameters.max_rounds")
    if weight_samples < MIN_WEIGHT_SAMPLES or weight_samples % 2 == 0:
        raise SchemaError("parameters.weight_samples must be an odd value of at least 3")
    if startup_samples < MIN_STARTUP_SAMPLES or startup_samples % 2 == 0:
        raise SchemaError("parameters.startup_samples must be an odd value of at least 5")
    if max_rounds > MAX_ROUNDS:
        raise SchemaError(f"parameters.max_rounds cannot exceed {MAX_ROUNDS}")
    require_close(
        parameters["proc_interval_ms"], PROC_INTERVAL_NS / 1_000_000, "parameters.proc_interval_ms"
    )
    require_close(
        parameters["noise_threshold"], NOISE_THRESHOLD, "parameters.noise_threshold"
    )
    require_close(
        parameters["bootstrap_ratio_tolerance"],
        BOOTSTRAP_TOLERANCE,
        "parameters.bootstrap_ratio_tolerance",
    )

    artifacts = require_object(
        top["artifacts"], {"release_jar", "native_compiler"}, "artifacts"
    )
    for name in ("release_jar", "native_compiler"):
        artifact = require_object(
            artifacts[name], {"sha256", "bytes"}, f"artifacts.{name}"
        )
        digest = require_string(artifact["sha256"], f"artifacts.{name}.sha256")
        if not HASH_RE.fullmatch(digest):
            raise SchemaError(f"artifacts.{name}.sha256 is not a SHA-256 digest")
        require_positive_int(artifact["bytes"], f"artifacts.{name}.bytes")

    bootstrap = require_object(
        top["bootstrap_cpu"], {"rounds", "selected_round"}, "bootstrap_cpu"
    )
    rounds = require_list(bootstrap["rounds"], "bootstrap_cpu.rounds")
    if not rounds or len(rounds) > max_rounds:
        raise SchemaError("bootstrap_cpu.rounds must contain 1..max_rounds rows")
    checked_rounds = [
        validate_ratio_round(row, weight_samples, f"bootstrap_cpu.rounds[{index}]")
        for index, row in enumerate(rounds)
    ]
    selected = require_positive_int(
        bootstrap["selected_round"], "bootstrap_cpu.selected_round"
    )
    if selected != len(checked_rounds):
        raise SchemaError("bootstrap_cpu.selected_round must select the final recorded round")
    if checked_rounds[selected - 1]["status"] != "conclusive":
        raise SchemaError("bootstrap_cpu.selected_round must be conclusive")
    for prior in checked_rounds[: selected - 1]:
        if prior["status"] != "inconclusive":
            raise SchemaError("only inconclusive rounds may precede the selected round")

    workloads = require_object(top["workloads"], set(WORKLOAD_ROLES), "workloads")
    for name in WORKLOAD_ROLES:
        validate_workload(name, workloads[name], weight_samples)

    startup = require_object(top["startup"], set(STARTUP_TARGETS), "startup")
    for name in STARTUP_TARGETS:
        validate_startup(name, startup[name], startup_samples)
    return top


def load_baseline(path: Path = BASELINE) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SchemaError(f"cannot read baseline {path}: {error}") from error
    return validate_baseline_data(parse_json_strict(text))


def stable_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_baseline_atomic(path: Path, value: object) -> None:
    validate_baseline_data(value)
    payload = stable_json(value).encode("utf-8")
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def run_checked(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [os.fspath(part) for part in command],
        cwd=cwd,
        env=None if env is None else dict(env),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if result.returncode != 0:
        rendered = " ".join(os.fspath(part) for part in command)
        raise BenchError(
            f"command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout[-4000:]}\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    env["LC_ALL"] = MEASUREMENT_LOCALE
    env["LANG"] = MEASUREMENT_LOCALE
    env["TZ"] = "UTC"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def measurement_environment(toolchain: Toolchain) -> dict[str, str]:
    env = clean_environment()
    java_home = toolchain.java.parent.parent.resolve()
    home_java = (java_home / "bin/java").resolve()
    if home_java != toolchain.java:
        raise BenchError(
            f"resolved java {toolchain.java} does not match JAVA_HOME candidate {java_home}"
        )
    env["JAVA_HOME"] = os.fspath(java_home)
    return env


def reject_pollution(env: Mapping[str, str]) -> None:
    present = [name for name in POLLUTING_ENV if name in env]
    if present:
        raise BenchError(
            "measurement environment contains forbidden variable(s): "
            + ", ".join(present)
        )


def resolve_toolchain() -> Toolchain:
    java_name = shutil.which("java")
    if java_name is None:
        raise BenchError("java is required")
    java = Path(java_name).resolve()
    jcmd = java.parent / "jcmd"
    if not jcmd.is_file() or not os.access(jcmd, os.X_OK):
        raise BenchError(f"same-JDK jcmd is missing beside {java}")
    version = run_checked([java, "-version"], cwd=ROOT)
    lines = (version.stderr or version.stdout).splitlines()
    if not lines:
        raise BenchError("java -version produced no identity")
    runtime = lines[1] if len(lines) > 1 else lines[0]
    return Toolchain(java=java, jcmd=jcmd, java_version=lines[0], java_runtime=runtime)


def parse_seed_checksums(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 2:
            raise BenchError(f"{path}:{line_number}: expected digest and tag")
        digest, tag = fields
        if not HASH_RE.fullmatch(digest) or not TAG_RE.fullmatch(tag):
            raise BenchError(f"{path}:{line_number}: invalid seed checksum row")
        if tag in result:
            raise BenchError(f"{path}:{line_number}: duplicate seed tag {tag}")
        result[tag] = digest
    return result


def resolve_seed() -> tuple[str, Path, str]:
    tag = (ROOT / "scripts/seed-release.txt").read_text(encoding="utf-8").strip()
    if not TAG_RE.fullmatch(tag):
        raise BenchError("scripts/seed-release.txt must contain one release tag")
    checksums = parse_seed_checksums(ROOT / "scripts/seed-checksums.txt")
    if tag not in checksums:
        raise BenchError(f"seed checksum table has no row for {tag}")
    script = 'ROOT="$1"; . "$ROOT/scripts/seedjar.sh"; seed_jar'
    resolved = run_checked(
        ["bash", "-c", script, "selfhost-bench", os.fspath(ROOT)], cwd=ROOT
    )
    lines = [line for line in resolved.stdout.splitlines() if line]
    if len(lines) != 1:
        raise BenchError("seedjar.sh did not return exactly one seed path")
    seed_path = Path(lines[0]).resolve()
    if not seed_path.is_file():
        raise BenchError(f"resolved seed is not a file: {seed_path}")
    digest = sha256_file(seed_path)
    if digest != checksums[tag]:
        raise BenchError(
            f"seed {tag} digest mismatch: expected {checksums[tag]}, got {digest}"
        )
    return tag, seed_path, digest


def source_snapshot(root: Path = ROOT) -> str:
    before = run_checked(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    if not COMMIT_RE.fullmatch(before):
        raise BenchError("git rev-parse did not return a full commit hash")
    status = run_checked(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=root
    )
    if status.stdout:
        raise BenchError("record/check requires a clean committed worktree")
    after = run_checked(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    if after != before:
        raise BenchError("source HEAD changed while its snapshot was being verified")
    return after


def verify_final_source_snapshot(expected_commit: str, root: Path = ROOT) -> None:
    actual_commit = source_snapshot(root)
    if actual_commit != expected_commit:
        raise BenchError(
            f"source HEAD changed during measurement: expected {expected_commit}, "
            f"found {actual_commit}"
        )


def preflight(options: Options) -> tuple[Preflight, dict[str, object] | None]:
    reject_pollution(os.environ)
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise BenchError("hardware measurement is supported only on Linux x86_64")
    for command in ("bash", "git", "cc", "readelf", "sha256sum", "locale"):
        if shutil.which(command) is None:
            raise BenchError(f"required command is missing: {command}")
    commit = source_snapshot()
    locale_result = run_checked(
        ["locale", "charmap"], cwd=ROOT, env=clean_environment()
    ).stdout.strip()
    if locale_result.upper().replace("-", "") != "UTF8":
        raise BenchError(
            f"{MEASUREMENT_LOCALE} does not select UTF-8 (locale reported {locale_result!r})"
        )
    baseline = None
    if options.mode == "check":
        try:
            baseline = load_baseline()
        except SchemaError as error:
            raise BenchError(f"baseline preflight failed: {error}") from error
    toolchain = resolve_toolchain()
    seed_tag, seed_path, seed_sha = resolve_seed()
    if baseline is not None:
        baseline_seed = baseline["seed"]
        if baseline_seed["tag"] != seed_tag or baseline_seed["sha256"] != seed_sha:
            raise BenchError(
                "baseline seed provenance differs from the resolved seed; "
                "record a new baseline deliberately"
            )
    return (
        Preflight(
            commit=commit,
            seed_tag=seed_tag,
            seed_path=seed_path,
            seed_sha256=seed_sha,
            toolchain=toolchain,
        ),
        baseline,
    )


def parse_stage_timings(path: Path) -> dict[str, int]:
    rows: dict[str, int] = {}
    expected_order = ["A", "B", "C"]
    observed_order: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        fields = raw.split("\t")
        if len(fields) != 3:
            raise BenchError(f"stage timing line {line_number} is malformed")
        stage, user_raw, system_raw = fields
        if stage not in expected_order:
            raise BenchError(f"stage timing line {line_number} has unknown stage {stage!r}")
        if stage in rows:
            raise BenchError(f"stage timing line {line_number} duplicates stage {stage}")
        try:
            user = Decimal(user_raw)
            system = Decimal(system_raw)
        except InvalidOperation as error:
            raise BenchError(f"stage {stage} has invalid CPU timing") from error
        if not user.is_finite() or not system.is_finite() or user <= 0 or system < 0:
            raise BenchError(f"stage {stage} has non-finite or negative CPU timing")
        user_ms = int((user * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if user_ms <= 0:
            raise BenchError(f"stage {stage} rounded to zero user CPU")
        rows[stage] = user_ms
        observed_order.append(stage)
    if observed_order != expected_order:
        raise BenchError(
            f"stage timings are {observed_order!r}, expected {expected_order!r}"
        )
    return rows


def build_release_sample(
    work: Path, label: str, env: Mapping[str, str]
) -> tuple[dict[str, object], Path]:
    output = work / f"release-{label}.jar"
    timings = work / f"release-{label}.times"
    child_env = dict(env)
    child_env["DAWN_INTERNAL_RELEASE_STAGE_TIMINGS"] = os.fspath(timings)
    run_checked(
        [ROOT / "scripts/build-release-jar.sh", "-o", output],
        cwd=ROOT,
        env=child_env,
        timeout=1800,
    )
    if not output.is_file() or output.stat().st_size <= 0:
        raise BenchError("canonical release builder produced no JAR")
    stages = parse_stage_timings(timings)
    sample = {
        "pass_a_user_ms": stages["A"],
        "pass_b_user_ms": stages["B"],
        "pass_c_user_ms": stages["C"],
        "ratio": stages["C"] / stages["A"],
    }
    return sample, output


def measure_bootstrap(
    work: Path, options: Options, env: Mapping[str, str]
) -> tuple[list[dict[str, object]], Path]:
    warm = work / "release-warm.jar"
    print("bootstrap warm-up: canonical release builder", file=sys.stderr)
    run_checked(
        [ROOT / "scripts/build-release-jar.sh", "-o", warm],
        cwd=ROOT,
        env=env,
        timeout=1800,
    )
    rounds: list[dict[str, object]] = []
    selected_artifact: Path | None = None
    reference_digest: str | None = None
    for round_number in range(1, options.max_rounds + 1):
        samples: list[dict[str, object]] = []
        artifacts: list[Path] = []
        for sample_number in range(1, options.weight_samples + 1):
            sample, artifact = build_release_sample(
                work, f"r{round_number}-s{sample_number}", env
            )
            digest = sha256_file(artifact)
            if reference_digest is None:
                reference_digest = digest
            elif digest != reference_digest:
                raise BenchError("canonical release samples produced different JAR bytes")
            samples.append(sample)
            artifacts.append(artifact)
            print(
                "bootstrap "
                f"round {round_number} sample {sample_number}: "
                f"A={sample['pass_a_user_ms']}ms "
                f"B={sample['pass_b_user_ms']}ms "
                f"C={sample['pass_c_user_ms']}ms "
                f"ratio={float(sample['ratio']):.6f}",
                file=sys.stderr,
            )
        summary = ratio_summary(samples)
        state = noise_state(float(summary["spread"]))
        round_record = {"samples": samples, "summary": summary, "status": state}
        rounds.append(round_record)
        print(
            f"bootstrap round {round_number}: median="
            f"{float(summary['median_ratio']):.6f}, "
            f"spread={float(summary['spread']) * 100:.2f}%, {state}",
            file=sys.stderr,
        )
        if state == "conclusive":
            selected_artifact = artifacts[-1]
            break
    if selected_artifact is None:
        raise Inconclusive(rounds)
    return rounds, selected_artifact


def read_process_stat(pid: int) -> ProcessStat | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    close = raw.rfind(")")
    if close < 0:
        return None
    fields = raw[close + 2 :].split()
    if len(fields) < 20:
        return None
    try:
        parent_pid = int(fields[1])
        starttime = int(fields[19])
    except ValueError:
        return None
    return ProcessStat(ProcessIdentity(pid, starttime), parent_pid)


def read_status_bytes(pid: int) -> tuple[int, int, int] | None:
    values: dict[str, int] = {}
    try:
        lines = Path(f"/proc/{pid}/status").read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    for raw in lines:
        if ":" not in raw:
            continue
        key, rest = raw.split(":", 1)
        if key not in {"VmRSS", "VmHWM", "VmPeak"}:
            continue
        fields = rest.split()
        if len(fields) != 2 or fields[1] != "kB" or not fields[0].isdigit():
            return None
        values[key] = int(fields[0]) * 1024
    if set(values) != {"VmRSS", "VmHWM", "VmPeak"}:
        return None
    return values["VmRSS"], values["VmHWM"], values["VmPeak"]


def read_cmdline(pid: int) -> tuple[str, ...]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return ()
    return tuple(
        part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part
    )


IdentityReader = Callable[[int], ProcessStat | None]
StatusReader = Callable[[int], tuple[int, int, int] | None]
CmdlineReader = Callable[[int], tuple[str, ...]]


def identity_is_current(
    identity: ProcessIdentity, identity_reader: IdentityReader = read_process_stat
) -> bool:
    current = identity_reader(identity.pid)
    return current is not None and current.identity == identity


def read_stable_process_view(
    stat: ProcessStat,
    *,
    identity_reader: IdentityReader = read_process_stat,
    status_reader: StatusReader = read_status_bytes,
    cmdline_reader: CmdlineReader = read_cmdline,
) -> ProcessView | None:
    if not identity_is_current(stat.identity, identity_reader):
        return None
    status = status_reader(stat.identity.pid)
    if status is None or not identity_is_current(stat.identity, identity_reader):
        return None
    argv = cmdline_reader(stat.identity.pid)
    if not identity_is_current(stat.identity, identity_reader):
        return None
    rss, hwm, peak = status
    return ProcessView(
        identity=stat.identity,
        parent_pid=stat.parent_pid,
        argv=argv,
        rss_bytes=rss,
        hwm_bytes=hwm,
        peak_bytes=peak,
    )


def process_table() -> dict[int, ProcessStat]:
    table: dict[int, ProcessStat] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        stat = read_process_stat(int(entry.name))
        if stat is not None:
            table[stat.identity.pid] = stat
    return table


def descendant_stats(
    table: Mapping[int, ProcessStat], root: ProcessIdentity
) -> list[ProcessStat]:
    root_stat = table.get(root.pid)
    if root_stat is None or root_stat.identity != root:
        return []
    children: dict[int, list[ProcessStat]] = {}
    for stat in table.values():
        children.setdefault(stat.parent_pid, []).append(stat)
    result = [root_stat]
    frontier = [(root_stat, 0)]
    while frontier:
        parent, depth = frontier.pop(0)
        if DESCENDANT_DEPTH_LIMIT is not None and depth >= DESCENDANT_DEPTH_LIMIT:
            continue
        for child in children.get(parent.identity.pid, []):
            result.append(child)
            frontier.append((child, depth + 1))
    return result


def is_java_argv(argv: Sequence[str]) -> bool:
    return bool(argv) and Path(argv[0]).name in {"java", "java.exe"}


def parse_max_heap(output: str) -> int:
    matches = re.findall(r"(?:^|\s)-XX:MaxHeapSize=([0-9]+)(?=\s|$)", output)
    if len(matches) != 1:
        raise BenchError(f"jcmd VM.flags returned {len(matches)} MaxHeapSize values")
    value = int(matches[0])
    if value <= 0:
        raise BenchError("jcmd VM.flags returned a non-positive MaxHeapSize")
    return value


def query_max_heap(
    jcmd: Path,
    identity: ProcessIdentity,
    *,
    identity_reader: IdentityReader = read_process_stat,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    if not identity_is_current(identity, identity_reader):
        raise BenchError(f"Java process {identity.pid} exited before jcmd attach")
    result = runner(
        [os.fspath(jcmd), str(identity.pid), "VM.flags"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=8,
    )
    if not identity_is_current(identity, identity_reader):
        raise BenchError(f"Java process {identity.pid} changed identity during jcmd attach")
    if result.returncode != 0:
        raise BenchError(
            f"jcmd attach failed for {identity.pid}: "
            f"{(result.stdout + result.stderr)[-2000:]}"
        )
    return parse_max_heap(result.stdout)


def process_group_has_live_members(process_group: int) -> bool:
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text(encoding="ascii")
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            continue
        close = raw.rfind(")")
        if close < 0:
            continue
        fields = raw[close + 2 :].split()
        if len(fields) < 3:
            continue
        try:
            member_group = int(fields[2])
        except ValueError:
            continue
        if member_group == process_group and fields[0] not in {"X", "Z"}:
            return True
    return False


def wait_process_group_exit(
    process: subprocess.Popen[bytes], timeout: float
) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        process.poll()
        if not process_group_has_live_members(process.pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if wait_process_group_exit(process, 5):
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if not wait_process_group_exit(process, 5):
        raise BenchError("could not terminate profiled process group")


RoleClassifier = Callable[[ProcessView, ProcessIdentity], str | None]


def classify_stable_view(
    view: ProcessView,
    views_by_pid: Mapping[int, ProcessView],
    classifier: RoleClassifier,
    root: ProcessIdentity,
) -> str | None:
    """Classify one stable view, refusing the pre-exec image of a fork.

    Between fork and exec a child still shows its parent's argv, so a cmdline
    classifier reads the parent's role marker off a process that is about to
    become something else. The (pid, starttime) identity rechecks cannot catch
    it: exec changes neither. Release run 32274732375 red on exactly this --
    the fixture child was sampled inside that window on a loaded runner,
    counted as a second "parent", and its 96m heap failed bench.heap_exact.

    A view whose argv equals the argv of its live parent in the same sample is
    that fork image, so it gets no role (and, downstream, no jcmd attach --
    which would also fail on a process that has not exec'd into a JVM yet).
    The next sample sees the exec'd argv and classifies it as itself. No
    profiled tree runs a child whose real argv equals its parent's.
    """
    parent = views_by_pid.get(view.parent_pid)
    if parent is not None and view.argv and view.argv == parent.argv:
        return None
    return classifier(view, root)


def profile_command(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    env: Mapping[str, str],
    classifier: RoleClassifier,
    expected_roles: Sequence[str],
    java_roles: set[str],
    jcmd: Path,
    timeout: float,
) -> ProfileResult:
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        started = time.perf_counter_ns()
        process = subprocess.Popen(
            [os.fspath(part) for part in command],
            cwd=cwd,
            env=dict(env),
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=True,
        )
        completed_normally = False
        executor: ThreadPoolExecutor | None = None
        try:
            root: ProcessIdentity | None = None
            root_deadline = time.monotonic() + 2
            while root is None and time.monotonic() < root_deadline:
                stat = read_process_stat(process.pid)
                if stat is not None:
                    root = stat.identity
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.001)
            if root is None:
                raise BenchError(
                    "profiled command exited before its root identity was observed"
                )

            role_observations: dict[str, dict[ProcessIdentity, RoleObservation]] = {}
            observed_identities: set[ProcessIdentity] = set()
            heap_futures: dict[ProcessIdentity, Future[int]] = {}
            tree_peak = 0
            overlap_samples = 0
            sampling_attempts = 0
            deadline = time.monotonic() + timeout
            next_tick = time.perf_counter_ns()
            executor = ThreadPoolExecutor(max_workers=max(1, len(java_roles)))
            while True:
                sampling_attempts += 1
                table = process_table()
                stats = descendant_stats(table, root)
                complete = bool(stats)
                tree_rss = 0
                roles_now: set[str] = set()
                # Two passes: classification needs the whole sample's views so
                # a fork's pre-exec image can be told from the parent whose
                # argv it still carries (see classify_stable_view).
                views: dict[int, ProcessView] = {}
                stable: list[ProcessStat] = []
                for stat in stats:
                    view = read_stable_process_view(stat)
                    if view is None:
                        complete = False
                        continue
                    views[stat.identity.pid] = view
                    stable.append(stat)
                for stat in stable:
                    view = views[stat.identity.pid]
                    tree_rss += view.rss_bytes
                    observed_identities.add(stat.identity)
                    role = classify_stable_view(view, views, classifier, root)
                    if role is None:
                        continue
                    roles_now.add(role)
                    observation = role_observations.setdefault(role, {}).setdefault(
                        stat.identity, RoleObservation()
                    )
                    observation.hwm_bytes = max(observation.hwm_bytes, view.hwm_bytes)
                    observation.peak_bytes = max(observation.peak_bytes, view.peak_bytes)
                    if (
                        role in java_roles
                        and is_java_argv(view.argv)
                        and stat.identity not in heap_futures
                    ):
                        heap_futures[stat.identity] = executor.submit(
                            query_max_heap, jcmd, stat.identity
                        )
                if complete:
                    tree_peak = max(tree_peak, tree_rss)
                    if set(expected_roles).issubset(roles_now):
                        overlap_samples += 1
                if process.poll() is not None:
                    break
                if time.monotonic() >= deadline:
                    raise BenchError(f"profiled command exceeded {timeout:.0f}s")
                next_tick += PROC_INTERVAL_NS
                delay = (next_tick - time.perf_counter_ns()) / 1_000_000_000
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_tick = time.perf_counter_ns()

            ended = time.perf_counter_ns()
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read().decode("utf-8", errors="replace")
            stderr = stderr_file.read().decode("utf-8", errors="replace")

            heap_values: dict[ProcessIdentity, int] = {}
            for identity, future in heap_futures.items():
                try:
                    heap_values[identity] = future.result()
                except Exception as error:
                    if isinstance(error, BenchError):
                        raise error
                    raise BenchError(
                        f"jcmd attach failed for {identity.pid}: {error}"
                    ) from error

            roles: dict[str, dict[str, int | None]] = {}
            for role, identities in role_observations.items():
                heaps = [heap_values.get(identity) for identity in identities]
                if role in java_roles and any(heap is None for heap in heaps):
                    raise BenchError(f"role {role} is missing an actual MaxHeapSize")
                if role not in java_roles:
                    max_heap: int | None = None
                else:
                    max_heap = max(int(heap) for heap in heaps if heap is not None)
                roles[role] = {
                    "process_count": len(identities),
                    "rss_hwm_bytes": max(item.hwm_bytes for item in identities.values()),
                    "vas_peak_bytes": max(item.peak_bytes for item in identities.values()),
                    "max_heap_bytes": max_heap,
                }

            completed_normally = process.returncode == 0
            return ProfileResult(
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
                wall_time_ns=ended - started,
                tree_peak_rss_bytes=tree_peak,
                complete_overlap_samples=overlap_samples,
                sampling_attempts=sampling_attempts,
                roles=roles,
                observed_identities=frozenset(observed_identities),
            )
        finally:
            if not completed_normally:
                terminate_process_group(process)
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=False)


def workload_classifier(root_role: str) -> RoleClassifier:
    def classify(view: ProcessView, root: ProcessIdentity) -> str | None:
        if view.identity == root:
            return root_role
        if not is_java_argv(view.argv):
            return None
        if any(part.endswith("$TestMain") for part in view.argv):
            return "test_main"
        if "main" in view.argv and "-cp" in view.argv:
            return "dependency_reexec"
        return None

    return classify


def heap_tree_classifier(view: ProcessView, root: ProcessIdentity) -> str | None:
    del root
    if "HeapTree" not in view.argv:
        return None
    index = view.argv.index("HeapTree")
    if index + 1 >= len(view.argv):
        return None
    mode = view.argv[index + 1]
    return (
        mode
        if mode
        in {
            "parent",
            "child",
            "grandchild",
            "sibling",
            "single",
            "sum-parent",
            "sum-child",
            "failure-parent",
            "failure-child",
        }
        else None
    )


def require_profile(
    name: str, result: ProfileResult, expected_roles: Sequence[str]
) -> dict[str, object]:
    if result.returncode != 0:
        raise BenchError(
            f"{name} exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-4000:]}\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )
    if result.tree_peak_rss_bytes <= 0:
        raise BenchError(f"{name} recorded no complete process-tree RSS sample")
    if result.complete_overlap_samples <= 0:
        raise BenchError(f"{name} never showed all required roles at once")
    if set(result.roles) != set(expected_roles):
        raise BenchError(
            f"{name} roles are {sorted(result.roles)}, expected {sorted(expected_roles)}"
        )
    for role in expected_roles:
        metric = result.roles[role]
        if metric["process_count"] != 1:
            raise BenchError(f"{name} observed {metric['process_count']} {role} processes")
        if int(metric["rss_hwm_bytes"]) <= 0 or int(metric["vas_peak_bytes"]) <= 0:
            raise BenchError(f"{name} has incomplete {role} RSS/VAS metrics")
        if role in JAVA_ROLES and metric["max_heap_bytes"] is None:
            raise BenchError(f"{name} has no actual heap for Java role {role}")
        if role not in JAVA_ROLES and metric["max_heap_bytes"] is not None:
            raise BenchError(f"{name} assigned a Java heap to native role {role}")
    return {
        "wall_time_ns": result.wall_time_ns,
        "tree_peak_rss_bytes": result.tree_peak_rss_bytes,
        "complete_overlap_samples": result.complete_overlap_samples,
        "roles": result.roles,
    }


def build_native_release(
    work: Path, release_jar: Path, env: Mapping[str, str]
) -> Path:
    output = work / "dawnc-linux-x86_64"
    run_checked(
        [
            ROOT / "scripts/release-native.sh",
            "-o",
            output,
            "--jar",
            release_jar,
        ],
        cwd=ROOT,
        env=env,
        timeout=1800,
    )
    if not output.is_file() or not os.access(output, os.X_OK):
        raise BenchError("canonical native release builder produced no executable")
    return output


def workload_commands(
    work: Path, release_jar: Path, native: Path, java: Path, sample: int
) -> dict[str, tuple[list[Path | str], str]]:
    java_prefix: list[Path | str] = [java, *TOOLCHAIN_JVM_OPTS, "-jar", release_jar]
    return {
        "jvm_build_fib": (
            java_prefix
            + [
                "build",
                "examples/basics/fib.dawn",
                "-o",
                work / f"fib-jvm-{sample}.jar",
                "--std",
                "std",
            ],
            "compiler",
        ),
        "native_build_fib": (
            [
                native,
                "build",
                "examples/basics/fib.dawn",
                "-o",
                work / f"fib-native-{sample}.jar",
                "--std",
                "std",
            ],
            "native_compiler",
        ),
        "test_stdlib": (
            java_prefix + ["test", "--stdlib", "--std", "std"],
            "compiler",
        ),
        "test_selfhost": (
            java_prefix + ["test", "--std", "std", "selfhost"],
            "compiler",
        ),
    }


def measure_workloads(
    work: Path,
    options: Options,
    release_jar: Path,
    native: Path,
    pre: Preflight,
    env: Mapping[str, str],
) -> dict[str, object]:
    measured: dict[str, object] = {}
    for name, expected_roles in WORKLOAD_ROLES.items():
        samples: list[dict[str, object]] = []
        for sample_number in range(1, options.weight_samples + 1):
            command, root_role = workload_commands(
                work, release_jar, native, pre.toolchain.java, sample_number
            )[name]
            print(f"{name} sample {sample_number}/{options.weight_samples}", file=sys.stderr)
            profiled = profile_command(
                command,
                cwd=ROOT,
                env=env,
                classifier=workload_classifier(root_role),
                expected_roles=expected_roles,
                java_roles=JAVA_ROLES,
                jcmd=pre.toolchain.jcmd,
                timeout=1800,
            )
            samples.append(require_profile(name, profiled, expected_roles))
        measured[name] = {
            "expected_roles": list(expected_roles),
            "samples": samples,
            "summary": workload_summary(samples, expected_roles),
        }
    return measured


def make_deployed_launcher(work: Path, release_jar: Path) -> Path:
    deployment = work / "launcher"
    (deployment / "bin").mkdir(parents=True)
    (deployment / "build").mkdir()
    launcher = deployment / "bin/dawn"
    shutil.copy2(ROOT / "bin/dawn", launcher)
    shutil.copy2(release_jar, deployment / "build/dawn-selfhost.jar")
    launcher.chmod(0o755)
    return launcher


def time_startup(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    env: Mapping[str, str],
    samples: int,
) -> dict[str, object]:
    run_checked(command, cwd=cwd, env=env, timeout=30)
    values: list[int] = []
    for _ in range(samples):
        started = time.perf_counter_ns()
        run_checked(command, cwd=cwd, env=env, timeout=30)
        elapsed = time.perf_counter_ns() - started
        if elapsed <= 0:
            raise BenchError("startup timer returned a non-positive duration")
        values.append(elapsed)
    return {"samples_ns": values, "median_ns": median_int(values)}


def measure_startup(
    work: Path,
    options: Options,
    release_jar: Path,
    native: Path,
    pre: Preflight,
    env: Mapping[str, str],
) -> dict[str, object]:
    launcher = make_deployed_launcher(work, release_jar)
    commands: dict[str, Sequence[str | os.PathLike[str]]] = {
        # direct_jar exists to price bin/dawn's shell work against the same JVM
        # underneath it, so it has to be the same JVM: bin_dawn is a verbatim
        # copy of the launcher and picks up whatever DAWN_JVM_OPTS says.
        "direct_jar": [
            pre.toolchain.java,
            *TOOLCHAIN_JVM_OPTS,
            "-jar",
            release_jar,
            "--version",
        ],
        "bin_dawn": [launcher, "--version"],
        "native_compiler": [native, "version"],
    }
    result: dict[str, object] = {}
    for name in STARTUP_TARGETS:
        print(f"startup {name}: warm-up + {options.startup_samples} samples", file=sys.stderr)
        result[name] = time_startup(
            commands[name], cwd=ROOT, env=env, samples=options.startup_samples
        )
    return result


def artifact_record(path: Path) -> dict[str, object]:
    return {"sha256": sha256_file(path), "bytes": path.stat().st_size}


def make_baseline(
    options: Options,
    pre: Preflight,
    release_jar: Path,
    native: Path,
    rounds: list[dict[str, object]],
    workloads: dict[str, object],
    startup: dict[str, object],
) -> dict[str, object]:
    value = {
        "schema": SCHEMA,
        "kind": KIND,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": {"commit": pre.commit, "tree": "clean"},
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "kernel": platform.release(),
            "locale": MEASUREMENT_LOCALE,
            "java_version": pre.toolchain.java_version,
            "java_runtime": pre.toolchain.java_runtime,
        },
        "seed": {"tag": pre.seed_tag, "sha256": pre.seed_sha256},
        "parameters": {
            "weight_samples": options.weight_samples,
            "startup_samples": options.startup_samples,
            "max_rounds": options.max_rounds,
            "proc_interval_ms": PROC_INTERVAL_NS / 1_000_000,
            "noise_threshold": NOISE_THRESHOLD,
            "bootstrap_ratio_tolerance": BOOTSTRAP_TOLERANCE,
        },
        "artifacts": {
            "release_jar": artifact_record(release_jar),
            "native_compiler": artifact_record(native),
        },
        "bootstrap_cpu": {"rounds": rounds, "selected_round": len(rounds)},
        "workloads": workloads,
        "startup": startup,
    }
    return validate_baseline_data(value)


def gibibytes(value: int) -> float:
    return value / (1024**3)


def milliseconds(value: int) -> float:
    return value / 1_000_000


def print_summary(value: Mapping[str, object]) -> None:
    bootstrap = value["bootstrap_cpu"]
    selected = bootstrap["rounds"][bootstrap["selected_round"] - 1]
    summary = selected["summary"]
    print(
        f"bootstrap ratio {float(summary['median_ratio']):.6f} "
        f"(spread {float(summary['spread']) * 100:.2f}%)"
    )
    artifacts = value["artifacts"]
    for name in ("release_jar", "native_compiler"):
        print(
            f"artifact {name}: {artifacts[name]['bytes']} bytes "
            f"sha256 {artifacts[name]['sha256']}"
        )
    for name in WORKLOAD_ROLES:
        workload = value["workloads"][name]["summary"]
        print(
            f"workload {name}: tree RSS "
            f"{gibibytes(workload['median_tree_peak_rss_bytes']):.3f} GiB, "
            f"wall {milliseconds(workload['median_wall_time_ns']):.1f} ms"
        )
        for role in WORKLOAD_ROLES[name]:
            metric = workload["roles"][role]
            heap = metric["max_heap_bytes"]
            heap_text = "n/a" if heap is None else f"{gibibytes(heap):.3f} GiB"
            print(
                f"  {role}: HWM {gibibytes(metric['rss_hwm_bytes']):.3f} GiB, "
                f"VAS {gibibytes(metric['vas_peak_bytes']):.3f} GiB, heap {heap_text}"
            )
    for name in STARTUP_TARGETS:
        print(
            f"startup {name}: "
            f"{milliseconds(value['startup'][name]['median_ns']):.3f} ms median"
        )


def selected_ratio(value: Mapping[str, object]) -> float:
    bootstrap = value["bootstrap_cpu"]
    selected = bootstrap["rounds"][bootstrap["selected_round"] - 1]
    return float(selected["summary"]["median_ratio"])


def measure(options: Options, pre: Preflight) -> dict[str, object]:
    env = measurement_environment(pre.toolchain)
    with tempfile.TemporaryDirectory(prefix="dawn-selfhost-bench-") as raw:
        work = Path(raw)
        phase_started = time.perf_counter()
        rounds, release_jar = measure_bootstrap(work, options, env)
        bootstrap_seconds = time.perf_counter() - phase_started
        print(f"duration bootstrap: {bootstrap_seconds:.2f}s", file=sys.stderr)

        phase_started = time.perf_counter()
        native = build_native_release(work, release_jar, env)
        native_seconds = time.perf_counter() - phase_started
        print(f"duration native release: {native_seconds:.2f}s", file=sys.stderr)

        phase_started = time.perf_counter()
        workloads = measure_workloads(work, options, release_jar, native, pre, env)
        workloads_seconds = time.perf_counter() - phase_started
        print(f"duration workloads: {workloads_seconds:.2f}s", file=sys.stderr)

        phase_started = time.perf_counter()
        startup = measure_startup(work, options, release_jar, native, pre, env)
        startup_seconds = time.perf_counter() - phase_started
        print(f"duration startup: {startup_seconds:.2f}s", file=sys.stderr)

        return make_baseline(
            options, pre, release_jar, native, rounds, workloads, startup
        )


def publish_measurement(
    options: Options,
    expected_commit: str,
    measured: Mapping[str, object],
    baseline: Mapping[str, object] | None,
    *,
    root: Path = ROOT,
    baseline_path: Path = BASELINE,
) -> int:
    verify_final_source_snapshot(expected_commit, root)
    print_summary(measured)
    if options.mode == "record":
        verify_final_source_snapshot(expected_commit, root)
        write_baseline_atomic(baseline_path, measured)
        print(f"wrote {baseline_path}", file=sys.stderr)
    elif options.mode == "check":
        if baseline is None:
            raise AssertionError("check mode reached comparison without baseline")
        current = selected_ratio(measured)
        previous = selected_ratio(baseline)
        limit = previous * (1 + BOOTSTRAP_TOLERANCE)
        delta = (current / previous - 1) * 100
        if current > limit:
            print(
                f"FAIL: bootstrap ratio {current:.6f} is {delta:+.2f}% "
                f"against baseline {previous:.6f} "
                f"(budget +{BOOTSTRAP_TOLERANCE * 100:.0f}%)"
            )
            return 1
        print(
            f"PASS: bootstrap ratio {current:.6f} is {delta:+.2f}% "
            f"against baseline {previous:.6f} "
            f"(budget +{BOOTSTRAP_TOLERANCE * 100:.0f}%)"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--help"]:
        print(USAGE, end="")
        return 0
    try:
        options = parse_cli(args)
        pre, baseline = preflight(options)
        measured = measure(options, pre)
        return publish_measurement(options, pre.commit, measured, baseline)
    except CliError as error:
        print(f"error: {error}", file=sys.stderr)
        print(USAGE, file=sys.stderr, end="")
        return 2
    except Inconclusive as error:
        for index, round_record in enumerate(error.rounds, 1):
            ratios = ", ".join(
                f"{float(sample['ratio']):.6f}" for sample in round_record["samples"]
            )
            spread = float(round_record["summary"]["spread"]) * 100
            print(
                f"inconclusive round {index}: ratios [{ratios}], spread {spread:.2f}%",
                file=sys.stderr,
            )
        print(
            "INCONCLUSIVE: bootstrap spread stayed at or above 15%; "
            "baseline was not written and no PASS/FAIL was reported",
            file=sys.stderr,
        )
        return error.exit_code
    except (BenchError, SchemaError) as error:
        exit_code = error.exit_code if isinstance(error, BenchError) else 2
        print(f"error: {error}", file=sys.stderr)
        return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
