#!/usr/bin/env python3
"""Capture reproducible cold-stage samples, not an incremental speedup claim.

Each target is a fresh JVM; paired analyses alternate order within that JVM.
Parse replay is separate from loader timing. Peak RSS includes JVM startup,
stdlib loading and all rounds, so it is not retained semantic-cache memory.
It is read from the kernel's rusage for the reaped child (`os.wait4`), as
bench-replay.py does, not from `/usr/bin/time`, which minimal images do not
ship; `<index>.rss.txt` keeps the one line of `time -v` output it used to hold.
"""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import statistics
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FIELDS = ["kind", "round", "target", "modules", "parsed_decls", "load_ns",
          "parse_replay_ns", "observed_ns", "module_ns", "check_ns", "comptime_ns",
          "cold_ns", "check_runs", "comptime_runs",
          "observed_diags", "cold_diags", "order"]
# Every numeric column: all but the leading kind/round/target and the trailing order.
NUMERIC = FIELDS[3:-1]


def peak_rss_kb(maxrss, system=None):
    """`ru_maxrss` in KiB, the unit `/usr/bin/time -v` reported. Linux already
    counts KiB; macOS counts bytes (getrusage(2) on each), so it is divided."""
    system = sys.platform if system is None else system
    kib = maxrss // 1024 if system == "darwin" else maxrss
    if kib <= 0:
        raise RuntimeError(f"no peak RSS: ru_maxrss={maxrss} on {system}")
    return kib


def run_measured(command, cwd, stdout, stderr, timeout):
    """Run one target and return its peak RSS in KiB.

    `os.wait4` reaps the child and hands back the rusage of that child alone,
    which is what `/usr/bin/time` measured around the same command. A timeout
    kills the child and fails the target, as `subprocess.run` would."""
    process = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr)
    expired = threading.Event()

    def expire():
        expired.set()
        process.kill()

    timer = threading.Timer(timeout, expire)
    timer.start()
    try:
        _, status, usage = os.wait4(process.pid, 0)
    finally:
        timer.cancel()
    code = os.waitstatus_to_exitcode(status)
    # The child is already reaped; tell Popen so it does not wait a second time.
    process.returncode = code
    if expired.is_set():
        raise subprocess.TimeoutExpired(command, timeout)
    if code != 0:
        raise subprocess.CalledProcessError(code, command)
    return peak_rss_kb(usage.ru_maxrss)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-home", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path,
                        help="new directory; existing results are never overwritten")
    parser.add_argument("targets", nargs="+")
    args = parser.parse_args()
    java = args.java_home.resolve() / "bin/java"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    metadata = {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "platform": platform.platform(),
        "java": subprocess.run([str(java), "-version"], text=True, capture_output=True,
                               check=True).stderr,
        "jvm_flags": ["-Xss512m", "-Xmx2g", "-XX:+UseSerialGC"],
        "warmup_rounds": 3, "measured_rounds": 8,
        "targets": args.targets,
        "sources": {},
        "limitations": ["parse replay is not an internal loader interval",
                        "peak RSS is process-wide, not retained cache memory",
                        "no warm incremental path exists in this benchmark yet"],
    }
    for directory in ("selfhost/src", "compiler-plan/src", "std",
                      "scripts/incremental-semantics-contract"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.is_file() and path.suffix in (".dawn", ".toml", ".py", ".txt", ".java"):
                metadata["sources"][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    with (output / "build.log").open("w") as log:
        subprocess.run([str(ROOT / "bin/dawn"), "build", str(HERE), "-o", str(output / "bench.jar"),
                        "--vendor", "org/objectweb/asm", "--vendor", "coursierapi"],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    summaries = []
    for index, target in enumerate(args.targets):
        command = [str(java), *metadata["jvm_flags"], "-jar", str(output / "bench.jar"), target]
        with (output / f"{index}.tsv").open("w") as stdout, (output / f"{index}.stderr").open("w") as stderr:
            peak = run_measured(command, ROOT, stdout, stderr, 600)
        (output / f"{index}.rss.txt").write_text(f"\tMaximum resident set size (kbytes): {peak}\n")
        rows = []
        for line in (output / f"{index}.tsv").read_text().splitlines():
            values = line.split("\t")
            if values[0] == "meta":
                continue
            if len(values) != len(FIELDS) or values[0] != "round":
                raise RuntimeError(f"invalid benchmark row: {line}")
            row = dict(zip(FIELDS, values))
            for field in NUMERIC + ["round"]:
                row[field] = int(row[field])
            if row["target"] != target or row["observed_diags"] or row["cold_diags"]:
                raise RuntimeError(f"invalid analysis: {row}")
            if row["check_runs"] != row["modules"] or row["comptime_runs"] != row["modules"]:
                raise RuntimeError(f"incomplete stage coverage: {row}")
            if row["order"] != ("observed-first" if row["round"] % 2 == 0 else "cold-first"):
                raise RuntimeError(f"analysis order drift: {row}")
            rows.append(row)
        if [row["round"] for row in rows] != list(range(11)):
            raise RuntimeError("expected exactly rounds 0..10")
        measured = rows[3:]
        summaries.append({
            "target": target, "samples": 8,
            "median_ms": {field: statistics.median(row[field] for row in measured) / 1e6
                          for field in FIELDS if field.endswith("_ns")},
            "raw": f"{index}.tsv", "process_peak_rss": f"{index}.rss.txt",
        })
    (output / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
