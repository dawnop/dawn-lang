#!/usr/bin/env python3
"""Build and measure the local slab-residency workload matrix.

This intentionally has no metric threshold. A non-zero exit means that the
matrix could not be compared (build/protocol/checksum failure), never that one
allocator's RSS or wall time was worse.
"""

from __future__ import annotations

import argparse
import ctypes
import csv
import datetime as dt
import functools
import hashlib
import os
from pathlib import Path
import platform
import selectors
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import time
from typing import Iterable, Sequence


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORE_CFLAGS = [
    "-std=c11",
    "-O2",
    "-fwrapv",
    "-fexceptions",
    "-fno-strict-aliasing",
    "-pthread",
]
ALL_WORKLOADS = ("lexer", "rbtree", "compiler")
ALL_VARIANTS = ("eager", "candidate", "glibc", "mimalloc")


class BenchError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def display_command(command: Sequence[str]) -> str:
    return shlex.join(str(part) for part in command)


def checked(
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    text: bool = True,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [str(part) for part in command],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        stdout = result.stdout if text else result.stdout.decode("utf-8", "replace")
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise BenchError(
            f"command exited {result.returncode}: {display_command(command)}\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )
    return result


def first_line(
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    environment: dict[str, str] | None = None,
) -> str:
    output = checked(command, cwd=cwd, environment=environment).stdout.strip()
    return output.splitlines()[0] if output else ""


def parse_selection(raw: str, allowed: Sequence[str], what: str) -> list[str]:
    selected = [part.strip() for part in raw.split(",") if part.strip()]
    if not selected:
        raise BenchError(f"no {what} selected")
    unknown = [part for part in selected if part not in allowed]
    if unknown:
        raise BenchError(f"unknown {what}: {', '.join(unknown)}")
    if len(set(selected)) != len(selected):
        raise BenchError(f"duplicate {what} in {raw!r}")
    return selected


def md5_file(path: Path) -> str:
    # This is a byte-identity label, not an authenticity claim.
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def git_bytes(ref: str, path: str) -> bytes:
    return checked(["git", "show", f"{ref}:{path}"], text=False).stdout


def snapshot_runtime_from_ref(ref: str, destination: Path) -> None:
    destination.mkdir(parents=True)
    for name in ("dawn_rt.c", "dawn_rt.h"):
        (destination / name).write_bytes(git_bytes(ref, f"runtime/c/{name}"))


def validate_runtime_dir(source: Path, label: str) -> Path:
    source = source.resolve()
    for name in ("dawn_rt.c", "dawn_rt.h"):
        path = source / name
        if not path.is_file():
            raise BenchError(f"{label} is missing {path}")
    return source


def snapshot_runtime_from_dir(source: Path, destination: Path, label: str) -> None:
    source = validate_runtime_dir(source, label)
    destination.mkdir(parents=True)
    for name in ("dawn_rt.c", "dawn_rt.h"):
        shutil.copy2(source / name, destination / name)


def archive_corpus(ref: str, destination: Path, build_dir: Path) -> None:
    archive = build_dir / "corpus.tar"
    checked(
        [
            "git",
            "archive",
            "--format=tar",
            f"--output={archive}",
            ref,
            "selfhost",
            "std",
            "packages",
            "compiler-plan",
        ]
    )
    destination.mkdir(parents=True)
    root = destination.resolve()
    with tarfile.open(archive, "r") as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if os.path.commonpath((root, target)) != str(root):
                raise BenchError(f"refusing unsafe corpus member {member.name!r}")
        bundle.extractall(destination)
    archive.unlink()


def validate_corpus_dir(source: Path, destination: Path | None = None) -> Path:
    source = source.resolve()
    required = ("selfhost", "std", "packages", "compiler-plan")
    for name in required:
        path = source / name
        if not path.is_dir():
            raise BenchError(f"corpus directory is missing {path}")
        if destination is not None:
            destination_root = destination.resolve()
            if destination_root == path or path in destination_root.parents:
                raise BenchError(
                    f"result corpus {destination_root} must not be inside source tree {path}"
                )
    for relative in (
        "selfhost/dawn.toml",
        "selfhost/src/front/lexer.dawn",
        "selfhost/src/nmain.dawn",
    ):
        path = source / relative
        if not path.is_file():
            raise BenchError(f"corpus directory is missing {path}")
    return source


def snapshot_corpus_from_dir(source: Path, destination: Path) -> None:
    source = validate_corpus_dir(source, destination)
    required = ("selfhost", "std", "packages", "compiler-plan")
    destination.mkdir(parents=True)
    for name in required:
        # Dereference links so the result is a self-contained byte snapshot.
        shutil.copytree(source / name, destination / name, symlinks=False)


def snapshot_workloads(workloads: Sequence[str], corpus: Path) -> None:
    """Put the measured entrypoints beside the fixed corpus they import."""
    destination = corpus / "scripts/slab-bench/workloads"
    destination.mkdir(parents=True)
    for workload in workloads:
        shutil.copytree(HERE / "workloads" / workload, destination / workload)


def write_corpus_manifest(root: Path, destination: Path) -> tuple[int, int, str]:
    """Record copied byte identities; MD5 is only a reproducibility label."""
    aggregate = hashlib.md5(usedforsecurity=False)
    count = 0
    total_bytes = 0
    with destination.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow(["kind", "relative_path", "bytes", "md5"])
        entries = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
        for path in entries:
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                kind = "symlink"
                payload = os.readlink(path).encode("utf-8")
                digest = hashlib.md5(payload, usedforsecurity=False).hexdigest()
                size = len(payload)
            elif path.is_file():
                kind = "file"
                digest = md5_file(path)
                size = path.stat().st_size
            else:
                continue
            writer.writerow([kind, relative, size, digest])
            aggregate.update(kind.encode("ascii"))
            aggregate.update(b"\0")
            aggregate.update(relative.encode("utf-8"))
            aggregate.update(b"\0")
            aggregate.update(str(size).encode("ascii"))
            aggregate.update(b"\0")
            aggregate.update(digest.encode("ascii"))
            aggregate.update(b"\n")
            count += 1
            total_bytes += size
    return count, total_bytes, aggregate.hexdigest()


def cpu_model() -> str:
    try:
        with Path("/proc/cpuinfo").open(encoding="utf-8") as source:
            for line in source:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def libc_description() -> str:
    libc = " ".join(part for part in platform.libc_ver() if part).strip()
    ldd = shutil.which("ldd")
    if ldd:
        try:
            line = first_line([ldd, "--version"])
            if line:
                return line
        except BenchError:
            pass
    return libc or "unknown"


def mimalloc_flags(
    explicit: str | None,
    environment: dict[str, str],
) -> tuple[list[str], str]:
    if explicit is not None:
        flags = shlex.split(explicit)
        if not flags:
            raise BenchError("--mimalloc-link must not be empty")
        return flags, "explicit"
    pkg_config = shutil.which("pkg-config")
    if pkg_config:
        result = subprocess.run(
            [pkg_config, "--cflags", "--libs", "mimalloc"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            env=environment,
        )
        if result.returncode == 0 and result.stdout.strip():
            return shlex.split(result.stdout), "pkg-config"
    return ["-lmimalloc"], "fallback"


def mimalloc_version(environment: dict[str, str]) -> str:
    pkg_config = shutil.which("pkg-config")
    if pkg_config:
        result = subprocess.run(
            [pkg_config, "--modversion", "mimalloc"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            env=environment,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    dpkg_query = shutil.which("dpkg-query")
    if dpkg_query:
        for package in ("libmimalloc-dev", "libmimalloc2.0"):
            result = subprocess.run(
                [dpkg_query, "-W", "-f=${Version}", package],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                env=environment,
            )
            if result.returncode == 0 and result.stdout.strip():
                return f"{package} {result.stdout.strip()}"
    return "unknown"


def benchmark_environment() -> tuple[dict[str, str], list[str]]:
    """Keep ambient allocator/debug knobs from silently changing a variant."""
    exact = {
        "ASAN_OPTIONS",
        "GLIBC_TUNABLES",
        "LD_AUDIT",
        "LD_BIND_NOW",
        "LD_DEBUG",
        "LD_PRELOAD",
        "LD_PROFILE",
        "LSAN_OPTIONS",
        "UBSAN_OPTIONS",
    }
    prefixes = ("DAWN_", "MALLOC_", "MIMALLOC_")
    clean: dict[str, str] = {}
    removed: list[str] = []
    for key, value in os.environ.items():
        if key in exact or key.startswith(prefixes):
            removed.append(key)
        else:
            clean[key] = value
    clean["LANG"] = "C"
    clean["LC_ALL"] = "C"
    return clean, sorted(removed)


def write_environment(path: Path, entries: Iterable[tuple[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow(["key", "value"])
        for key, value in entries:
            writer.writerow([key, value if value != "" else "not-applicable"])


def append_environment(path: Path, entries: Iterable[tuple[str, object]]) -> None:
    with path.open("a", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        for key, value in entries:
            writer.writerow([key, value if value != "" else "not-applicable"])


def emit_workloads(
    dawn: Path,
    workloads: Sequence[str],
    corpus: Path,
    build_dir: Path,
    environment: dict[str, str],
) -> dict[str, Path]:
    emitted: dict[str, Path] = {}
    for workload in workloads:
        target = corpus / "scripts/slab-bench/workloads" / workload
        output = build_dir / "emitted" / f"{workload}.c"
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            dawn,
            "__emitc",
            "--std",
            corpus / "std",
            target,
            "-o",
            output,
        ]
        print(f"emit  {workload}: {display_command(command)}", flush=True)
        checked(command, environment=environment)
        if not output.is_file() or output.stat().st_size == 0:
            raise BenchError(f"emitter did not create {output}")
        emitted[workload] = output
    return emitted


def link_matrix(
    *,
    cc: Sequence[str],
    workloads: Sequence[str],
    variants: Sequence[str],
    emitted: dict[str, Path],
    runtimes: dict[str, Path],
    mimalloc_link: Sequence[str],
    build_dir: Path,
    builds_tsv: Path,
    environment: dict[str, str],
) -> dict[tuple[str, str], Path]:
    fields = [
        "workload",
        "variant",
        "runtime_source",
        "runtime_c_md5",
        "runtime_h_md5",
        "emitted_c_md5",
        "program_header_source",
        "program_header_md5",
        "program_object_md5",
        "defines",
        "link_args",
        "program_compile_command",
        "runtime_compile_command",
        "link_command",
        "program_compile_ms",
        "runtime_compile_ms",
        "link_ms",
        "executable",
        "executable_bytes",
        "executable_md5",
    ]
    binaries: dict[tuple[str, str], Path] = {}
    object_dir = build_dir / "obj"
    object_dir.mkdir(parents=True, exist_ok=True)

    # An emitted translation unit includes dawn_rt.h. Compile it once for each
    # distinct selected header, so an old eager ABI is never mixed with a
    # candidate program object. Byte-identical headers still share an object.
    runtime_key_for_variant = {
        variant: "eager" if variant == "eager" else "candidate"
        for variant in variants
    }
    selected_runtime_keys = list(dict.fromkeys(runtime_key_for_variant.values()))
    runtime_digests = {
        runtime_key: (
            md5_file(runtimes[runtime_key] / "dawn_rt.c"),
            md5_file(runtimes[runtime_key] / "dawn_rt.h"),
        )
        for runtime_key in selected_runtime_keys
    }
    emitted_digests = {workload: md5_file(emitted[workload]) for workload in workloads}
    header_sources: dict[str, str] = {}
    for runtime_key in selected_runtime_keys:
        _runtime_c_md5, header_md5 = runtime_digests[runtime_key]
        header_sources.setdefault(header_md5, runtime_key)

    program_objects: dict[
        tuple[str, str], tuple[Path, list[str], float, str, str]
    ] = {}
    for workload in workloads:
        for header_md5, header_source in header_sources.items():
            object_path = object_dir / f"{workload}-program-{header_md5[:12]}.o"
            command = [
                *cc,
                *CORE_CFLAGS,
                "-I",
                str(runtimes[header_source]),
                "-c",
                str(emitted[workload]),
                "-o",
                str(object_path),
            ]
            print(f"compile program {workload} ({header_source} header)", flush=True)
            started = time.monotonic_ns()
            checked(command, environment=environment)
            elapsed = (time.monotonic_ns() - started) / 1_000_000
            program_objects[(workload, header_md5)] = (
                object_path,
                command,
                elapsed,
                header_source,
                md5_file(object_path),
            )

    runtime_shapes = {
        "eager": ("eager", []),
        "candidate": ("candidate", []),
        "noslab": ("candidate", ["-DDAWN_NO_SLAB"]),
    }
    shape_for_variant = {
        "eager": "eager",
        "candidate": "candidate",
        "glibc": "noslab",
        "mimalloc": "noslab",
    }
    selected_shapes = list(dict.fromkeys(shape_for_variant[variant] for variant in variants))
    runtime_objects: dict[str, tuple[Path, list[str], float]] = {}
    for runtime_shape in selected_shapes:
        runtime_key, defines = runtime_shapes[runtime_shape]
        runtime = runtimes[runtime_key]
        object_path = object_dir / f"runtime-{runtime_shape}.o"
        command = [
            *cc,
            *CORE_CFLAGS,
            *defines,
            "-I",
            str(runtime),
            "-c",
            str(runtime / "dawn_rt.c"),
            "-o",
            str(object_path),
        ]
        print(f"compile runtime {runtime_shape}", flush=True)
        started = time.monotonic_ns()
        checked(command, environment=environment)
        elapsed = (time.monotonic_ns() - started) / 1_000_000
        runtime_objects[runtime_shape] = (object_path, command, elapsed)

    with builds_tsv.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for workload in workloads:
            for variant in variants:
                runtime_key = runtime_key_for_variant[variant]
                runtime = runtimes[runtime_key]
                defines = ["-DDAWN_NO_SLAB"] if variant in ("glibc", "mimalloc") else []
                link_args = list(mimalloc_link) if variant == "mimalloc" else []
                runtime_shape = shape_for_variant[variant]
                header_md5 = runtime_digests[runtime_key][1]
                (
                    program_object,
                    program_command,
                    program_ms,
                    program_header_source,
                    program_object_md5,
                ) = program_objects[(workload, header_md5)]
                runtime_object, runtime_command, runtime_ms = runtime_objects[runtime_shape]
                executable = build_dir / "bin" / f"{workload}-{variant}"
                executable.parent.mkdir(parents=True, exist_ok=True)
                command = [
                    *cc,
                    "-pthread",
                    "-o",
                    str(executable),
                    str(program_object),
                    str(runtime_object),
                    *link_args,
                    "-lm",
                ]
                print(f"link  {workload}/{variant}", flush=True)
                started = time.monotonic_ns()
                try:
                    checked(command, environment=environment)
                except BenchError as error:
                    if variant == "mimalloc":
                        raise BenchError(
                            f"mimalloc link failed; install its development package, pass "
                            f"--mimalloc-link, or omit that variant\n{error}"
                        ) from error
                    raise
                link_ms = (time.monotonic_ns() - started) / 1_000_000
                if not executable.is_file() or not os.access(executable, os.X_OK):
                    raise BenchError(f"linker did not create executable {executable}")
                binaries[(workload, variant)] = executable
                writer.writerow(
                    {
                        "workload": workload,
                        "variant": variant,
                        "runtime_source": runtime_key,
                        "runtime_c_md5": runtime_digests[runtime_key][0],
                        "runtime_h_md5": runtime_digests[runtime_key][1],
                        "emitted_c_md5": emitted_digests[workload],
                        "program_header_source": program_header_source,
                        "program_header_md5": header_md5,
                        "program_object_md5": program_object_md5,
                        "defines": " ".join(defines),
                        "link_args": " ".join(link_args),
                        "program_compile_command": display_command(program_command),
                        "runtime_compile_command": display_command(runtime_command),
                        "link_command": display_command(command),
                        "program_compile_ms": f"{program_ms:.3f}",
                        "runtime_compile_ms": f"{runtime_ms:.3f}",
                        "link_ms": f"{link_ms:.3f}",
                        "executable": executable,
                        "executable_bytes": executable.stat().st_size,
                        "executable_md5": md5_file(executable),
                    }
                )
                output.flush()
    return binaries


def proc_memory(pid: int) -> tuple[int, int]:
    values: dict[str, int] = {}
    try:
        with Path(f"/proc/{pid}/status").open(encoding="ascii") as status:
            for line in status:
                if line.startswith("VmRSS:") or line.startswith("VmHWM:"):
                    fields = line.split()
                    if len(fields) < 2:
                        raise BenchError(f"malformed /proc/{pid}/status line: {line.rstrip()}")
                    values[fields[0].rstrip(":")] = int(fields[1])
    except FileNotFoundError as error:
        raise BenchError(f"process {pid} exited before its ready barrier was sampled") from error
    if "VmRSS" not in values or "VmHWM" not in values:
        raise BenchError(f"/proc/{pid}/status has no VmRSS/VmHWM")
    return values["VmRSS"], values["VmHWM"]


def die_with_parent(expected_parent: int) -> None:
    """Do not leave a stdin_ready loop behind if the runner is killed."""
    libc = ctypes.CDLL(None, use_errno=True)
    # Linux prctl(PR_SET_PDEATHSIG, SIGKILL). This runs before exec, so none of
    # the Python address space or allocations enter the measured process.
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        os._exit(127)
    if os.getppid() != expected_parent:
        os.kill(os.getpid(), signal.SIGKILL)


def wait_for_ready(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    stderr_path: Path,
    environment: dict[str, str],
) -> dict[str, object]:
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    started_utc = utc_now()
    started = time.monotonic_ns()
    proc: subprocess.Popen | None = None
    checksum_line = b""
    ready_line = b""
    trailing = b""
    try:
        with stderr_path.open("wb") as stderr:
            proc = subprocess.Popen(
                [str(part) for part in command],
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                bufsize=0,
                env=environment,
                preexec_fn=functools.partial(die_with_parent, os.getpid()),
            )
            if proc.stdout is None or proc.stdin is None:
                raise BenchError("failed to open benchmark pipes")
            selector = selectors.DefaultSelector()
            selector.register(proc.stdout, selectors.EVENT_READ)
            buffer = bytearray()
            deadline = time.monotonic() + timeout
            try:
                while buffer.count(b"\n") < 2:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise BenchError(f"timed out before ready: {display_command(command)}")
                    events = selector.select(min(remaining, 0.25))
                    if events:
                        chunk = os.read(proc.stdout.fileno(), 65536)
                        if chunk:
                            buffer.extend(chunk)
                        elif proc.poll() is not None:
                            break
                    elif proc.poll() is not None:
                        chunk = os.read(proc.stdout.fileno(), 65536)
                        if chunk:
                            buffer.extend(chunk)
                        else:
                            break
            finally:
                selector.close()
            if buffer.count(b"\n") < 2:
                raise BenchError(
                    f"process exited before ready (exit {proc.poll()}): {display_command(command)}"
                )
            checksum_line, ready_line, trailing = bytes(buffer).split(b"\n", 2)
            to_ready_ns = time.monotonic_ns() - started
            try:
                decoded_checksum = checksum_line.decode("utf-8")
                decoded_ready = ready_line.decode("utf-8")
            except UnicodeDecodeError as error:
                raise BenchError(
                    f"barrier lines are not UTF-8: {checksum_line!r}, {ready_line!r}"
                ) from error
            parts = decoded_checksum.split("\t")
            if len(parts) != 2 or parts[0] != "checksum" or not parts[1]:
                raise BenchError(f"bad checksum protocol line: {decoded_checksum!r}")
            if decoded_ready != "ready":
                raise BenchError(f"bad ready protocol line: {decoded_ready!r}")
            quiet_rss, hwm = proc_memory(proc.pid)
            proc.stdin.write(b"x")
            proc.stdin.flush()
            proc.stdin.close()
            try:
                exit_code = proc.wait(timeout=10)
            except subprocess.TimeoutExpired as error:
                raise BenchError("process did not exit after the ready barrier was released") from error
            trailing += proc.stdout.read()
            if exit_code != 0:
                raise BenchError(f"process exited {exit_code} after ready: {display_command(command)}")
            if trailing.strip():
                raise BenchError(f"unexpected output after ready: {trailing!r}")
            return {
                "started_utc": started_utc,
                "pid": proc.pid,
                "quiet_vmrss_kib": quiet_rss,
                "vmhwm_kib": hwm,
                "to_ready_ns": to_ready_ns,
                "to_ready_ms": f"{to_ready_ns / 1_000_000:.3f}",
                "checksum": parts[1],
                "exit_code": exit_code,
            }
    except BaseException as error:
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            proc.wait()
        detail = ""
        try:
            detail = stderr_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        if isinstance(error, BenchError):
            raise BenchError(f"{error}\nstderr:\n{detail}") from error
        raise


def workload_command(
    workload: str,
    executable: Path,
    *,
    corpus: Path,
    lexer_reps: int,
    rbtree_reps: int,
    compiler_reps: int,
) -> list[str]:
    if workload == "lexer":
        return [
            str(executable),
            str(corpus / "selfhost/src/front/lexer.dawn"),
            str(lexer_reps),
        ]
    if workload == "rbtree":
        return [str(executable), str(rbtree_reps)]
    if workload == "compiler":
        return [
            str(executable),
            str(corpus / "std"),
            str(corpus / "selfhost/src/nmain.dawn"),
            str(compiler_reps),
        ]
    raise AssertionError(workload)


def rotate(items: Sequence[str], amount: int) -> list[str]:
    offset = amount % len(items)
    return [*items[offset:], *items[:offset]]


def measure_matrix(
    *,
    workloads: Sequence[str],
    variants: Sequence[str],
    binaries: dict[tuple[str, str], Path],
    corpus: Path,
    logs: Path,
    samples_tsv: Path,
    warmups: int,
    samples: int,
    timeout: float,
    lexer_reps: int,
    rbtree_reps: int,
    compiler_reps: int,
    environment: dict[str, str],
) -> list[dict[str, object]]:
    fields = [
        "phase",
        "workload",
        "variant",
        "sample",
        "started_utc",
        "pid",
        "quiet_vmrss_kib",
        "vmhwm_kib",
        "to_ready_ns",
        "to_ready_ms",
        "checksum",
        "exit_code",
        "stderr_file",
    ]
    rows: list[dict[str, object]] = []
    expected: dict[str, str] = {}
    with samples_tsv.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for workload in workloads:
            phases = (("warmup", warmups), ("sample", samples))
            rotation = 0
            for phase, count in phases:
                for number in range(1, count + 1):
                    for variant in rotate(variants, rotation):
                        log_name = f"{workload}-{phase}-{number:02d}-{variant}.stderr"
                        stderr_path = logs / log_name
                        command = workload_command(
                            workload,
                            binaries[(workload, variant)],
                            corpus=corpus,
                            lexer_reps=lexer_reps,
                            rbtree_reps=rbtree_reps,
                            compiler_reps=compiler_reps,
                        )
                        print(
                            f"run   {workload}/{variant} {phase} {number}/{count}",
                            flush=True,
                        )
                        measured = wait_for_ready(
                            command,
                            cwd=corpus,
                            timeout=timeout,
                            stderr_path=stderr_path,
                            environment=environment,
                        )
                        checksum = str(measured["checksum"])
                        if workload not in expected:
                            expected[workload] = checksum
                        elif checksum != expected[workload]:
                            raise BenchError(
                                f"{workload}/{variant} checksum {checksum}, expected "
                                f"{expected[workload]}"
                            )
                        row = {
                            "phase": phase,
                            "workload": workload,
                            "variant": variant,
                            "sample": number,
                            **measured,
                            "stderr_file": f"logs/{log_name}",
                        }
                        writer.writerow(row)
                        output.flush()
                        rows.append(row)
                    rotation += 1
    return rows


def print_summary(
    rows: Sequence[dict[str, object]],
    workloads: Sequence[str],
    variants: Sequence[str],
) -> None:
    print("\nmedians (samples only; informational, never a gate)")
    print("workload\tvariant\tquiet_vmrss_kib\tvmhwm_kib\tto_ready_ms")
    for workload in workloads:
        for variant in variants:
            group = [
                row
                for row in rows
                if row["phase"] == "sample"
                and row["workload"] == workload
                and row["variant"] == variant
            ]
            rss = statistics.median(int(row["quiet_vmrss_kib"]) for row in group)
            hwm = statistics.median(int(row["vmhwm_kib"]) for row in group)
            wall = statistics.median(float(row["to_ready_ms"]) for row in group)
            print(f"{workload}\t{variant}\t{rss:g}\t{hwm:g}\t{wall:.3f}")


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure Dawn allocator variants at a post-workload ready barrier.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--workloads", default=",".join(ALL_WORKLOADS))
    parser.add_argument("--variants", default=",".join(ALL_VARIANTS))
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--lexer-reps", type=int, default=100)
    parser.add_argument("--rbtree-reps", type=int, default=24)
    parser.add_argument("--compiler-reps", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=900.0, help="seconds to ready")
    eager_input = parser.add_mutually_exclusive_group()
    eager_input.add_argument(
        "--eager-ref",
        default=argparse.SUPPRESS,
        help="Git ref whose runtime/c is the eager/current baseline (default: HEAD)",
    )
    eager_input.add_argument(
        "--eager-runtime",
        type=Path,
        default=argparse.SUPPRESS,
        help="non-Git baseline directory containing dawn_rt.c and dawn_rt.h",
    )
    corpus_input = parser.add_mutually_exclusive_group()
    corpus_input.add_argument(
        "--corpus-ref",
        default=argparse.SUPPRESS,
        help="Git ref for fixed lexer/compiler input (defaults to the eager Git ref)",
    )
    corpus_input.add_argument(
        "--corpus-dir",
        type=Path,
        default=argparse.SUPPRESS,
        help="non-Git source root containing selfhost/std/packages/compiler-plan",
    )
    parser.add_argument(
        "--candidate-runtime",
        type=Path,
        default=ROOT / "runtime/c",
        help="directory containing candidate dawn_rt.c and dawn_rt.h",
    )
    parser.add_argument("--dawn", type=Path, default=ROOT / "bin/dawn")
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    parser.add_argument(
        "--mimalloc-link",
        help="shell-split C/link flags; otherwise pkg-config, then -lmimalloc",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="new result directory (defaults under scripts/slab-bench/out)",
    )
    return parser


def select_input_sources(
    args: argparse.Namespace,
    *,
    eager_required: bool,
) -> tuple[tuple[str, str], tuple[str, str]]:
    eager_runtime = getattr(args, "eager_runtime", None)
    eager_ref = getattr(args, "eager_ref", None)
    corpus_dir = getattr(args, "corpus_dir", None)
    corpus_ref = getattr(args, "corpus_ref", None)
    if eager_runtime is not None:
        eager = ("directory", str(eager_runtime.resolve()))
    elif eager_ref is not None:
        eager = ("git-ref", eager_ref)
    elif eager_required:
        eager = ("git-ref", "HEAD")
    else:
        eager = ("not-selected", "")

    if corpus_dir is not None:
        corpus = ("directory", str(corpus_dir.resolve()))
    elif corpus_ref is not None:
        corpus = ("git-ref", corpus_ref)
    elif eager[0] == "git-ref":
        corpus = eager
    elif eager[0] == "not-selected":
        corpus = ("git-ref", "HEAD")
    else:
        raise BenchError(
            "--eager-runtime requires an explicit --corpus-dir or --corpus-ref"
        )
    return eager, corpus


def main(argv: Sequence[str] | None = None) -> int:
    args = argument_parser().parse_args(argv)
    for name in ("eager_ref", "eager_runtime", "corpus_ref", "corpus_dir"):
        if not hasattr(args, name):
            setattr(args, name, None)
    if not sys.platform.startswith("linux") or not Path("/proc/self/status").is_file():
        raise BenchError("slab-bench is Linux-only and requires /proc/<pid>/status")
    for name in ("samples", "lexer_reps", "rbtree_reps", "compiler_reps"):
        if getattr(args, name) <= 0:
            raise BenchError(f"--{name.replace('_', '-')} must be positive")
    if args.warmups < 0:
        raise BenchError("--warmups must not be negative")
    if args.timeout <= 0:
        raise BenchError("--timeout must be positive")

    workloads = parse_selection(args.workloads, ALL_WORKLOADS, "workload")
    variants = parse_selection(args.variants, ALL_VARIANTS, "variant")
    eager_source, corpus_source = select_input_sources(
        args,
        eager_required="eager" in variants,
    )
    eager_source_kind, eager_source_value = eager_source
    corpus_source_kind, corpus_source_value = corpus_source
    needs_git = "git-ref" in (eager_source_kind, corpus_source_kind)
    if needs_git and not (ROOT / ".git").exists():
        raise BenchError(
            "Git-ref input requires a Git checkout; pass --eager-runtime and "
            "--corpus-dir for a source snapshot without .git"
        )
    if needs_git:
        current_commit = first_line(["git", "rev-parse", "HEAD"])
        working_tree_dirty = str(
            first_line(["git", "status", "--porcelain=v1"]) != ""
        ).lower()
    else:
        current_commit = "not-applicable"
        working_tree_dirty = "not-applicable"
    eager_commit = (
        first_line(["git", "rev-parse", eager_source_value])
        if eager_source_kind == "git-ref"
        else "not-applicable"
    )
    corpus_commit = (
        first_line(["git", "rev-parse", corpus_source_value])
        if corpus_source_kind == "git-ref"
        else "not-applicable"
    )

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    result_dir = (args.out or (HERE / "out" / f"run-{stamp}")).resolve()
    if result_dir.exists() and any(result_dir.iterdir()):
        raise BenchError(f"result directory is not empty: {result_dir}")
    selected_runtime_keys = {
        "eager" if variant == "eager" else "candidate" for variant in variants
    }
    if eager_source_kind == "directory" and "eager" in selected_runtime_keys:
        validate_runtime_dir(Path(eager_source_value), "eager runtime directory")
    if "candidate" in selected_runtime_keys:
        validate_runtime_dir(args.candidate_runtime, "candidate runtime directory")
    corpus = result_dir / "corpus"
    if corpus_source_kind == "directory":
        validate_corpus_dir(Path(corpus_source_value), corpus)

    result_dir.mkdir(parents=True, exist_ok=True)
    build_dir = result_dir / "build"
    logs = result_dir / "logs"
    build_dir.mkdir()
    logs.mkdir()

    eager_runtime = build_dir / "runtime-eager"
    candidate_runtime = build_dir / "runtime-candidate"
    runtimes: dict[str, Path] = {}
    if "eager" in selected_runtime_keys:
        if eager_source_kind == "git-ref":
            print(
                f"snapshot eager runtime: {eager_source_value} ({eager_commit[:12]})",
                flush=True,
            )
            snapshot_runtime_from_ref(eager_commit, eager_runtime)
        else:
            print(f"snapshot eager runtime: {eager_source_value}", flush=True)
            snapshot_runtime_from_dir(
                Path(eager_source_value),
                eager_runtime,
                "eager runtime directory",
            )
        runtimes["eager"] = eager_runtime
    if "candidate" in selected_runtime_keys:
        print(f"snapshot candidate runtime: {args.candidate_runtime}", flush=True)
        snapshot_runtime_from_dir(
            args.candidate_runtime,
            candidate_runtime,
            "candidate runtime directory",
        )
        runtimes["candidate"] = candidate_runtime
    if corpus_source_kind == "git-ref":
        print(
            f"archive corpus: {corpus_source_value} ({corpus_commit[:12]})",
            flush=True,
        )
        archive_corpus(corpus_commit, corpus, build_dir)
    else:
        print(f"snapshot corpus: {corpus_source_value}", flush=True)
        snapshot_corpus_from_dir(Path(corpus_source_value), corpus)
    snapshot_workloads(workloads, corpus)
    corpus_files, corpus_bytes, corpus_md5 = write_corpus_manifest(
        corpus,
        result_dir / "corpus-files.tsv",
    )
    runtime_snapshot_md5 = {
        runtime_key: (
            md5_file(runtime / "dawn_rt.c"),
            md5_file(runtime / "dawn_rt.h"),
        )
        for runtime_key, runtime in runtimes.items()
    }

    if (
        "eager" in runtimes
        and "candidate" in runtimes
        and runtime_snapshot_md5["eager"][0]
        == runtime_snapshot_md5["candidate"][0]
    ):
        print(
            "warning: eager and candidate dawn_rt.c are byte-identical; "
            "select a distinct eager baseline when needed",
            file=sys.stderr,
            flush=True,
        )

    dawn = args.dawn.resolve()
    if not dawn.is_file():
        raise BenchError(f"Dawn compiler not found: {dawn}")
    cc = shlex.split(args.cc)
    if not cc:
        raise BenchError("--cc must not be empty")
    if shutil.which(cc[0]) is None:
        raise BenchError(f"C compiler not found: {cc[0]}")
    process_environment, removed_environment = benchmark_environment()
    if "mimalloc" in variants:
        mi_flags, mi_source = mimalloc_flags(args.mimalloc_link, process_environment)
        mi_version = mimalloc_version(process_environment)
    else:
        mi_flags, mi_source, mi_version = [], "not-selected", "not-selected"

    compiler_version = first_line([dawn, "--version"], environment=process_environment)
    cc_version = first_line([*cc, "--version"], environment=process_environment)
    eager_runtime_ids = runtime_snapshot_md5.get(
        "eager",
        ("not-selected", "not-selected"),
    )
    candidate_runtime_ids = runtime_snapshot_md5.get(
        "candidate",
        ("not-selected", "not-selected"),
    )
    environment_path = result_dir / "environment.tsv"
    write_environment(
        environment_path,
        [
            ("schema", 2),
            ("started_utc", utc_now()),
            ("repo", ROOT),
            ("head", current_commit),
            ("working_tree_dirty", working_tree_dirty),
            ("git_inputs_used", str(needs_git).lower()),
            ("eager_source_kind", eager_source_kind),
            ("eager_source", eager_source_value or "not-selected"),
            (
                "eager_source_argument",
                str(args.eager_runtime)
                if args.eager_runtime is not None
                else (
                    args.eager_ref
                    or ("HEAD" if eager_source_kind == "git-ref" else "not-selected")
                ),
            ),
            (
                "eager_ref",
                eager_source_value if eager_source_kind == "git-ref" else "not-applicable",
            ),
            ("eager_commit", eager_commit),
            ("eager_runtime_c_md5", eager_runtime_ids[0]),
            ("eager_runtime_h_md5", eager_runtime_ids[1]),
            ("corpus_source_kind", corpus_source_kind),
            ("corpus_source", corpus_source_value),
            (
                "corpus_source_argument",
                str(args.corpus_dir)
                if args.corpus_dir is not None
                else (args.corpus_ref or f"default:{corpus_source_value}"),
            ),
            (
                "corpus_ref",
                corpus_source_value if corpus_source_kind == "git-ref" else "not-applicable",
            ),
            ("corpus_commit", corpus_commit),
            ("corpus_files", corpus_files),
            ("corpus_bytes", corpus_bytes),
            ("corpus_tree_md5", corpus_md5),
            ("corpus_manifest", "corpus-files.tsv"),
            ("candidate_runtime_argument", args.candidate_runtime),
            ("candidate_runtime", args.candidate_runtime.resolve()),
            ("candidate_runtime_c_md5", candidate_runtime_ids[0]),
            ("candidate_runtime_h_md5", candidate_runtime_ids[1]),
            ("dawn", dawn),
            ("dawn_version", compiler_version),
            ("cc", display_command(cc)),
            ("cc_version", cc_version),
            ("core_cflags", " ".join(CORE_CFLAGS)),
            ("mimalloc_flags", " ".join(mi_flags)),
            ("mimalloc_flags_source", mi_source),
            ("mimalloc_version", mi_version),
            ("sanitized_environment_keys", ",".join(removed_environment)),
            ("kernel", platform.release()),
            ("platform", platform.platform()),
            ("libc", libc_description()),
            ("cpu_model", cpu_model()),
            ("cpu_count", os.cpu_count() or "unknown"),
            ("page_size", os.sysconf("SC_PAGE_SIZE")),
            ("loadavg_start", " ".join(f"{n:.2f}" for n in os.getloadavg())),
            ("workloads", ",".join(workloads)),
            ("variants", ",".join(variants)),
            ("warmups", args.warmups),
            ("samples", args.samples),
            ("lexer_reps", args.lexer_reps),
            ("rbtree_reps", args.rbtree_reps),
            ("compiler_reps", args.compiler_reps),
            ("timeout_seconds", args.timeout),
            ("lexer_corpus_bytes", (corpus / "selfhost/src/front/lexer.dawn").stat().st_size),
            ("lexer_corpus_md5", md5_file(corpus / "selfhost/src/front/lexer.dawn")),
            ("runner_md5", md5_file(Path(__file__).resolve())),
            *(
                (
                    f"workload_{workload}_md5",
                    md5_file(HERE / "workloads" / workload / "src/main.dawn"),
                )
                for workload in workloads
            ),
        ],
    )

    emitted = emit_workloads(dawn, workloads, corpus, build_dir, process_environment)
    binaries = link_matrix(
        cc=cc,
        workloads=workloads,
        variants=variants,
        emitted=emitted,
        runtimes=runtimes,
        mimalloc_link=mi_flags,
        build_dir=build_dir,
        builds_tsv=result_dir / "builds.tsv",
        environment=process_environment,
    )
    rows = measure_matrix(
        workloads=workloads,
        variants=variants,
        binaries=binaries,
        corpus=corpus,
        logs=logs,
        samples_tsv=result_dir / "samples.tsv",
        warmups=args.warmups,
        samples=args.samples,
        timeout=args.timeout,
        lexer_reps=args.lexer_reps,
        rbtree_reps=args.rbtree_reps,
        compiler_reps=args.compiler_reps,
        environment=process_environment,
    )
    append_environment(
        environment_path,
        [
            ("finished_utc", utc_now()),
            ("loadavg_end", " ".join(f"{n:.2f}" for n in os.getloadavg())),
        ],
    )
    print_summary(rows, workloads, variants)
    print(f"\nraw results: {result_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BenchError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
