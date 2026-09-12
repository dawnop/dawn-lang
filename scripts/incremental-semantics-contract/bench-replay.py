#!/usr/bin/env python3
"""Measure cold body checking, scheduler recording and scalar replay per body.

Local only: wall-clock numbers are machine-bound, so there is nothing for a
gate to compare. Nothing here changes checker, recorder or executor semantics;
the subject calls the same production entries the scheduler uses.

Each target is a fresh JVM with a fixed GC, and reports raw per-round nanos.
The memory mode is the exception: it reports retained heap bytes per snapshot,
measured across forced collections, and drops no warmup rounds.
The first rounds are warmup and are dropped before the median: on these subjects
the first round runs five to fifteen times slower than steady state, and the
tail only settles after about ten rounds, so the default drops twelve. Peak RSS is the
whole process, including JVM startup and the subject's own source generation,
so it is not a measure of retained semantic-cache memory.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SUBJECT = HERE / "bench-replay.dawn.txt"
JVM_FLAGS = ["-Xss64m", "-Xmx2g", "-XX:+UseSerialGC"]
# Retained-heap rounds. Each one keeps another snapshot alive, so a handful is
# enough and a long run would only measure the list holding them.
MEMORY_ROUNDS = 5

# (1) literal-only scalar, (2) primitive parameters with locals and arithmetic,
# (3) calls to annotated non-generic functions, (4) generic functions with trait
# bounds (dictionary passing), (5) inference-heavy bodies with lambdas,
# (6a) impl methods, (6b) trait defaults, (7) bodies reaching Java via `use java`.
CLASSES = ["scalar", "arith", "calls", "generic", "inferred", "method", "default", "java"]
# Replay admits the closed producer over primitive parameters and immutable
# locals: `scalar` and `arith` are reused whole, and `calls` reuses only its two
# leaf helpers. The remaining classes always miss, which prices what an extended
# executor would pay before it reused anything. The phase-split subject mirrors
# that admission and checks itself against production counts every run, so a
# widened executor makes the split fail rather than silently price a narrower
# rule than the one in production.


def parse_rows(text):
    meta, rows = {}, []
    for line in text.splitlines():
        values = line.split("\t")
        if values[0] == "meta" and len(values) == 3:
            meta[values[1]] = values[2]
        elif values[0] == "round" and len(values) == 4:
            rows.append((int(values[1]), values[2], int(values[3])))
        elif line.strip():
            raise RuntimeError("invalid benchmark row: " + line)
    return meta, rows


def peak_rss_kb(path):
    for line in path.read_text().splitlines():
        if "Maximum resident set size" in line:
            return int(line.rsplit(":", 1)[1].strip())
    raise RuntimeError("no peak RSS in " + str(path))


def load_average():
    return os.getloadavg()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--java-home", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path,
                        help="new directory; existing results are never overwritten")
    parser.add_argument("--sizes", default="100,1000")
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=12,
                        help="dropped rounds; these subjects need about ten to reach steady JIT state")
    parser.add_argument("--only", default="",
                        help="comma-separated subset of cold,parse,record,replay,split,memory,timer")
    args = parser.parse_args()
    if args.rounds - args.warmup < 8:
        raise SystemExit("at least 8 measured rounds are required")
    java = args.java_home.resolve() / "bin/java"
    if not java.exists():
        raise SystemExit("no java under " + str(args.java_home))
    sizes = [int(value) for value in args.sizes.split(",")]
    modes = [m for m in ("cold", "parse", "record", "replay", "split", "memory", "timer")
             if not args.only or m in args.only.split(",")]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    targets = []
    for mode in modes:
        if mode == "timer":
            targets.append(("timer", "scalar", 1000))
            continue
        if mode == "memory":
            # Heap attribution needs few rounds, and every round retains one
            # more snapshot; the largest size answers the question.
            for kind in CLASSES:
                targets.append(("memory", kind, sizes[-1]))
            continue
        for kind in CLASSES:
            for size in sizes:
                targets.append((mode, kind, size))

    metadata = {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "java": subprocess.run([str(java), "-version"], text=True, capture_output=True,
                               check=True).stderr.strip(),
        "jvm_flags": JVM_FLAGS,
        "rounds": args.rounds, "warmup_rounds": args.warmup,
        "measured_rounds": args.rounds - args.warmup,
        "load_before": load_average(),
        "sources": {},
        "limitations": [
            "wall clock on a shared machine; medians only, no speedup claim",
            "peak RSS is the whole process, not retained cache memory",
            "the replay phase split adds nanoTime pairs per body; the timer "
            "target measures that overhead so it can be discounted",
            "the split is a fixture-local re-composition of the production "
            "producers, validated against production replay counts in process",
        ],
    }
    for path in [SUBJECT, Path(__file__)]:
        metadata["sources"][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for directory in ("selfhost/src", "std"):
        digest = hashlib.sha256()
        for path in sorted((ROOT / directory).rglob("*.dawn")):
            digest.update(path.read_bytes())
        metadata["sources"][directory] = digest.hexdigest()

    with tempfile.TemporaryDirectory(prefix="dawn-bench-replay-") as temp:
        fixture = Path(temp) / "bench"
        (fixture / "src").mkdir(parents=True)
        shutil.copyfile(SUBJECT, fixture / "src/reference.dawn")
        (fixture / "dawn.toml").write_text(
            'schema = 1\nname = "bench_replay"\n\n[deps]\n'
            f'compiler = "{ROOT / "selfhost"}"\ncompiler_plan = "{ROOT / "compiler-plan"}"\n')
        jar = output / "bench-replay.jar"
        with (output / "build.log").open("w") as log:
            subprocess.run([str(ROOT / "bin/dawn"), "build", str(fixture), "-o", str(jar)],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True,
                           timeout=1800, env={**os.environ, "JAVA_HOME": str(args.java_home.resolve())})

        summaries = []
        for index, (mode, kind, size) in enumerate(targets):
            name = f"{index:02d}-{mode}-{kind}-{size}"
            rss = output / (name + ".rss.txt")
            rounds = MEMORY_ROUNDS if mode == "memory" else args.rounds
            command = ["/usr/bin/time", "-v", "-o", str(rss), str(java), *JVM_FLAGS,
                       "-jar", str(jar), mode, kind, str(size), str(rounds)]
            with (output / (name + ".tsv")).open("w") as out, \
                 (output / (name + ".stderr")).open("w") as err:
                subprocess.run(command, cwd=ROOT, stdout=out, stderr=err, check=True, timeout=3600)
            meta, rows = parse_rows((output / (name + ".tsv")).read_text())
            metrics = sorted({metric for _, metric, _ in rows})
            summary = {"mode": mode, "class": kind, "n": size, "raw": name + ".tsv",
                       "meta": meta, "peak_rss_kb": peak_rss_kb(rss), "median_ns": {}}
            # The memory mode reports retained bytes, not wall time, and its
            # first round is as valid as its last; it drops no warmup.
            warmup = 0 if mode == "memory" else args.warmup
            for metric in metrics:
                series = [value for round_index, m, value in rows
                          if m == metric and round_index >= warmup]
                if len(series) < rounds - warmup:
                    raise RuntimeError(f"{name}: {metric} has {len(series)} measured rounds")
                summary["median_ns"][metric] = statistics.median(series)
                summary.setdefault("stdev_ns", {})[metric] = (
                    statistics.stdev(series) if len(series) > 1 else 0.0)
            bodies = int(meta.get("bodies", size))
            summary["bodies"] = bodies
            summary["median_us_per_body"] = {
                metric: value / 1000.0 / bodies for metric, value in summary["median_ns"].items()}
            summaries.append(summary)
            unit = (lambda v: f"{v / 1024.0:.1f}KiB") if mode == "memory" else (
                lambda v: f"{v / 1e6:.3f}ms")
            print(f"{name}: " + "  ".join(
                f"{metric}={unit(summary['median_ns'][metric])}" for metric in metrics),
                flush=True)

    metadata["load_after"] = load_average()
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (output / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    with (output / "summary.tsv").open("w") as table:
        table.write("mode\tclass\tn\tbodies\tmetric\tmedian_ms\tstdev_ms\tus_per_body\tpeak_rss_kb\n")
        for s in summaries:
            for metric, value in s["median_ns"].items():
                table.write(f"{s['mode']}\t{s['class']}\t{s['n']}\t{s['bodies']}\t{metric}\t"
                            f"{value / 1e6:.4f}\t{s['stdev_ns'][metric] / 1e6:.4f}\t"
                            f"{s['median_us_per_body'][metric]:.4f}\t{s['peak_rss_kb']}\n")
    print("wrote " + str(output / "summary.tsv"))


if __name__ == "__main__":
    main()
