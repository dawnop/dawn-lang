#!/usr/bin/env python3
"""Prove dependency re-exec inherits the parent JVM's effective max heap."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import ModuleType
from typing import Mapping, Sequence
import zipfile


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BENCH = ROOT / "scripts/selfhost-bench.py"
MATRIX = HERE / "matrix.txt"
MUTATE = HERE / "mutate.py"
ASSERTIONS = (
    "heap.inherits_parent_max",
    "heap.dependency_reexec_observed",
)
MUTATED_ASSERTIONS = {"heap.inherits_parent_max"}
EXPECTED_ROLES = ("compiler", "dependency_reexec")
OVERRIDE_HEAP_BYTES = 384 * 1024 * 1024
FIXTURE_SLEEP_MILLIS = 4_000
FIXTURE_MARKER = "dependency-heap-contract-ok"


class ContractError(RuntimeError):
    pass


class MatrixError(ValueError):
    pass


@dataclass(frozen=True)
class CaseEvidence:
    name: str
    returncode: int
    parent_heap_bytes: int | None
    child_heap_bytes: int | None
    parent_count: int
    child_count: int
    overlap_samples: int
    marker_seen: bool


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ContractError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_checked(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: float = 600,
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
        raise ContractError(
            f"command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout[-4000:]}\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )
    return result


def mutator_keys() -> tuple[str, ...]:
    result = run_checked([sys.executable, MUTATE, "--list"], cwd=ROOT)
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
        if len(owner) != 1 or owner[0] not in MUTATED_ASSERTIONS:
            raise MatrixError(f"owner for {mutation} must name one mutated assertion")
        if red != owner:
            raise MatrixError(f"red for {mutation} must equal its owner")
        if len(control) != 1 or control[0] not in ASSERTIONS:
            raise MatrixError(f"control for {mutation} must name one known assertion")
        if control == owner:
            raise MatrixError(f"control for {mutation} must differ from its owner")
        owners.append(owner[0])
    if len(owners) != len(set(owners)):
        raise MatrixError("counted mutants must have unique owners")
    if set(owners) != MUTATED_ASSERTIONS:
        raise MatrixError("matrix owners must cover every mutated assertion")
    return records


def matrix_selftest(text: str, mutations: tuple[str, ...]) -> None:
    parse_matrix(text, mutations)
    lines = text.splitlines()
    first = next(line for line in lines if line and not line.startswith("#"))
    first_mutation = mutations[0]
    owner_line = next(
        line for line in lines if line.startswith(f"owner\t{first_mutation}\t")
    )
    mutants = {
        "unknown record": text.replace("role\t", "scope\t", 1),
        "duplicate record": text + first + "\n",
        "missing record": "\n".join(lines[:-1]) + "\n",
        "changed owner": text.replace(
            owner_line,
            f"owner\t{first_mutation}\theap.dependency_reexec_observed",
        ),
        "unknown mutation": text.replace(first_mutation, "unknown-mutator", 1),
        "changed role": text.replace("\tcounted", "\tignored", 1),
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


def clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "DAWN_JVM_OPTS",
        "DAWN_SEED",
        "DAWN_SEED_ALLOW_UNVERIFIED",
        "DAWN_SELFHOST_CP",
        "JAVA_TOOL_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "_JAVA_OPTIONS",
        "CLASSPATH",
    ):
        env.pop(name, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def prepare_seed_cache(env: dict[str, str]) -> None:
    seed_cache = Path(env.get("DAWN_SEED_CACHE", ROOT / ".dawn/seeds")).resolve()
    env["DAWN_SEED_CACHE"] = os.fspath(seed_cache)
    script = (
        'ROOT="$1"; export ROOT; . "$ROOT/scripts/seedjar.sh"; '
        "seed_jar >/dev/null; seed_std_dir >/dev/null"
    )
    run_checked(["bash", "-c", script, "dependency-heap-contract", ROOT], cwd=ROOT, env=env)


def copy_tracked_tree(destination: Path) -> None:
    listed = run_checked(["git", "ls-files", "-z"], cwd=ROOT)
    for raw in listed.stdout.split("\0"):
        if not raw:
            continue
        relative = Path(raw)
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, target)


def build_release(source_root: Path, output: Path, env: Mapping[str, str]) -> float:
    started = time.monotonic()
    run_checked(
        [source_root / "scripts/build-release-jar.sh", "-o", output],
        cwd=source_root,
        env=env,
        timeout=900,
    )
    return time.monotonic() - started


def build_mutant(
    bench: ModuleType,
    source_root: Path,
    release_jar: Path,
    output: Path,
    env: Mapping[str, str],
) -> float:
    run_checked(
        [sys.executable, MUTATE, "drop-inherited-max-heap", source_root / "selfhost/src/main.dawn"],
        cwd=ROOT,
    )
    started = time.monotonic()
    run_checked(
        [
            bench.resolve_toolchain().java,
            "-Xss512m",
            "-jar",
            release_jar,
            "build",
            "selfhost",
            "-o",
            output,
            "--std",
            "std",
            "--vendor",
            "org/objectweb/asm",
            "--vendor",
            "coursierapi",
        ],
        cwd=source_root,
        env=env,
        timeout=600,
    )
    return time.monotonic() - started


def write_fixture(work: Path) -> tuple[Path, Path]:
    fixture = work / "fixture.dawn"
    fixture.write_text(
        'use java "java.lang.Thread"\n\n'
        "pub fn main() -> Unit !io = {\n"
        f"  let _ = Thread.sleep({FIXTURE_SLEEP_MILLIS})\n"
        f'  println("{FIXTURE_MARKER}")\n'
        "}\n",
        encoding="utf-8",
    )
    dependency = work / "empty.jar"
    with zipfile.ZipFile(dependency, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n\n")
    return fixture, dependency


def deploy_candidate(work: Path, label: str, jar: Path) -> Path:
    deployment = work / f"deploy-{label}"
    (deployment / "bin").mkdir(parents=True)
    (deployment / "build").mkdir()
    shutil.copy2(ROOT / "bin/dawn", deployment / "bin/dawn")
    shutil.copy2(jar, deployment / "build/dawn-selfhost.jar")
    return deployment / "bin/dawn"


def profile_case(
    bench: ModuleType,
    *,
    name: str,
    launcher: Path,
    fixture: Path,
    dependency: Path,
    source_root: Path,
    jvm_opts: str | None,
) -> CaseEvidence:
    toolchain = bench.resolve_toolchain()
    env = clean_environment()
    env["JAVA_HOME"] = os.fspath(toolchain.java.parent.parent)
    if jvm_opts is not None:
        env["DAWN_JVM_OPTS"] = jvm_opts
    result = bench.profile_command(
        [launcher, "run", "--cp", dependency, fixture],
        cwd=source_root,
        env=env,
        classifier=bench.workload_classifier("compiler"),
        expected_roles=EXPECTED_ROLES,
        java_roles=set(EXPECTED_ROLES),
        jcmd=toolchain.jcmd,
        timeout=30,
    )
    parent = result.roles.get("compiler", {})
    child = result.roles.get("dependency_reexec", {})
    return CaseEvidence(
        name=name,
        returncode=result.returncode,
        parent_heap_bytes=parent.get("max_heap_bytes"),
        child_heap_bytes=child.get("max_heap_bytes"),
        parent_count=int(parent.get("process_count", 0)),
        child_count=int(child.get("process_count", 0)),
        overlap_samples=result.complete_overlap_samples,
        marker_seen=FIXTURE_MARKER in result.stdout,
    )


def evaluate_candidate(
    bench: ModuleType,
    *,
    work: Path,
    label: str,
    jar: Path,
    source_root: Path,
    fixture: Path,
    dependency: Path,
) -> tuple[dict[str, bool], tuple[CaseEvidence, ...]]:
    launcher = deploy_candidate(work, label, jar)
    cases = (
        profile_case(
            bench,
            name="launcher-default",
            launcher=launcher,
            fixture=fixture,
            dependency=dependency,
            source_root=source_root,
            jvm_opts=None,
        ),
        profile_case(
            bench,
            name="launcher-override",
            launcher=launcher,
            fixture=fixture,
            dependency=dependency,
            source_root=source_root,
            jvm_opts="-Xss512m -Xmx384m",
        ),
    )
    observed = all(
        case.returncode == 0
        and case.parent_count == 1
        and case.child_count == 1
        and case.overlap_samples > 0
        and case.marker_seen
        for case in cases
    )
    default, override = cases
    inherited = (
        observed
        and all(
            case.parent_heap_bytes is not None
            and case.child_heap_bytes == case.parent_heap_bytes
            for case in cases
        )
        and override.parent_heap_bytes == OVERRIDE_HEAP_BYTES
        and default.parent_heap_bytes != override.parent_heap_bytes
    )
    assertions = {
        "heap.inherits_parent_max": inherited,
        "heap.dependency_reexec_observed": observed,
    }
    for case in cases:
        print(
            f"CASE  {label}/{case.name}: parent={case.parent_heap_bytes} "
            f"child={case.child_heap_bytes} overlap={case.overlap_samples}"
        )
    for assertion in ASSERTIONS:
        state = "PASS" if assertions[assertion] else "FAIL"
        print(f"{state}  {label}: {assertion}")
    return assertions, cases


def require_green(label: str, assertions: Mapping[str, bool]) -> None:
    red = [name for name in ASSERTIONS if not assertions[name]]
    if red:
        raise ContractError(f"{label} has red assertions: {', '.join(red)}")


def main() -> int:
    mode = "full"
    if sys.argv[1:] == ["--candidate-only"]:
        mode = "candidate-only"
    elif sys.argv[1:] == ["--matrix-selftest"]:
        mode = "matrix-selftest"
    elif sys.argv[1:]:
        print("usage: run.py [--candidate-only | --matrix-selftest]", file=sys.stderr)
        return 2

    mutations = mutator_keys()
    matrix_text = MATRIX.read_text(encoding="utf-8")
    records = parse_matrix(matrix_text, mutations)
    matrix_selftest(matrix_text, mutations)
    if mode == "matrix-selftest":
        print("dependency heap contract matrix: OK")
        return 0

    bench = load_module(BENCH, "dependency_heap_contract_bench")
    build_env = clean_environment()
    prepare_seed_cache(build_env)
    with tempfile.TemporaryDirectory(prefix="dependency-heap-contract.") as raw_work:
        work = Path(raw_work)
        base_root = work / "base-source"
        copy_tracked_tree(base_root)
        release_jar = work / "release.jar"
        release_seconds = build_release(base_root, release_jar, build_env)
        fixture, dependency = write_fixture(work)
        base_assertions, _ = evaluate_candidate(
            bench,
            work=work,
            label="candidate",
            jar=release_jar,
            source_root=base_root,
            fixture=fixture,
            dependency=dependency,
        )
        print(f"TIME  release build: {release_seconds:.2f}s")
        require_green("candidate", base_assertions)
        if mode == "candidate-only":
            print("dependency heap candidate contract: OK")
            return 0

        for mutation in mutations:
            mutant_root = work / f"mutant-source-{mutation}"
            shutil.copytree(base_root, mutant_root, symlinks=True)
            mutant_jar = work / f"{mutation}.jar"
            mutant_seconds = build_mutant(
                bench, mutant_root, release_jar, mutant_jar, build_env
            )
            mutant_assertions, _ = evaluate_candidate(
                bench,
                work=work,
                label=mutation,
                jar=mutant_jar,
                source_root=mutant_root,
                fixture=fixture,
                dependency=dependency,
            )
            owner = records[("owner", mutation)][0]
            control = records[("control", mutation)][0]
            red = {name for name in ASSERTIONS if not mutant_assertions[name]}
            if red != {owner}:
                raise ContractError(
                    f"{mutation} red {sorted(red)!r}, expected only {owner}"
                )
            if not mutant_assertions[control]:
                raise ContractError(f"{mutation} lost control {control}")
            print(f"PASS  {mutation} uniquely reds {owner}; control {control} stays green")
            print(f"TIME  {mutation} build: {mutant_seconds:.2f}s")
    print("dependency heap contract: OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, MatrixError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
