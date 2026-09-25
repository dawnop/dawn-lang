#!/usr/bin/env python3
"""Measure production body checking, recording, admission, replay and renewal.

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
--smoke bypasses statistical sampling only for correctness checks; its output
is explicitly marked and must not be used as performance evidence.
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

from cold import install_probe

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SUBJECT = HERE / "bench-replay.dawn.txt"
# The class generator and cold-equality check, shared with edit-matrix.py.
WORKLOADS = HERE / "replay-workloads.dawn.txt"
JVM_FLAGS = ["-Xss64m", "-Xmx2g", "-XX:+UseSerialGC"]
# Retained-heap rounds. Each one keeps another snapshot alive, so a handful is
# enough and a long run would only measure the list holding them.
MEMORY_ROUNDS = 5

# (1) literal-only scalar, (2) primitive parameters with locals and arithmetic,
# (3) calls to annotated non-generic functions, (4) generic functions with trait
# bounds (dictionary passing), (5) inference-heavy bodies with lambdas,
# (6a) impl methods, (6b) trait defaults, (7) bodies reaching Java via `use java`.
CLASSES = ["scalar", "arith", "calls", "generic", "inferred", "method", "default", "java",
           "primitive_inferred"]
# Keep the lambda-heavy inferred workload; primitive inference is a distinct
# class, not a replacement that would make existing acceptance goals easier.
MODES = ("cold", "parse", "record", "admit", "replay", "renew", "memory", "timer")
BODY_MODES = {"cold", "record", "admit", "replay", "renew"}
METRICS = {mode: {mode} for mode in BODY_MODES | {"timer"}}
METRICS.update(parse={"parse", "index", "compare", "snapshot_of"},
               memory={"retained_index", "retained_snapshot"})


def parse_rows(text):
    meta, rows = {}, []
    for line in text.splitlines():
        values = line.split("\t")
        if values[0] == "meta" and len(values) == 3:
            if values[1] in meta:
                raise RuntimeError("duplicate metadata: " + values[1])
            meta[values[1]] = values[2]
        elif values[0] == "round" and len(values) == 4:
            rows.append((int(values[1]), values[2], int(values[3])))
        elif line.strip():
            raise RuntimeError("invalid benchmark row: " + line)
    return meta, rows


def summarize(meta, rows, mode, kind, size, rounds, warmup):
    for key, expected in {"mode": mode, "class": kind, "n": str(size), "rounds": str(rounds)}.items():
        if meta.get(key) != expected:
            raise RuntimeError(f"metadata {key}: {meta.get(key)!r} != {expected!r}")
    if {metric for _, metric, _ in rows} != METRICS[mode]:
        raise RuntimeError("unexpected or missing benchmark metrics")
    bodies = None
    if mode in BODY_MODES:
        bodies = int(meta["bodies"])
        expected = size + (2 if kind == "calls" else 1 if kind in {"generic", "primitive_inferred"} else 0)
        if bodies != expected:
            raise RuntimeError(f"body census {bodies} != fixture census {expected}")
    unit = "bytes" if mode == "memory" else "ns"
    metrics = {}
    for metric in sorted(METRICS[mode]):
        series = [(index, value) for index, label, value in rows if label == metric]
        if sorted(index for index, _ in series) != list(range(rounds)):
            raise RuntimeError(f"{metric}: duplicate, missing, or out-of-range round")
        if unit == "ns" and any(value < 0 for _, value in series):
            raise RuntimeError("negative operation duration")
        measured = [value for index, value in series if index >= warmup]
        if not measured:
            raise RuntimeError("no measured rounds")
        median = statistics.median(measured)
        entry = {"unit": unit, "median": median,
                 "stdev": statistics.stdev(measured) if len(measured) > 1 else 0.0}
        if bodies is not None:
            entry["us_per_body"] = median / 1000.0 / bodies
        metrics[metric] = entry
    return {"mode": mode, "class": kind, "n": size, "meta": meta,
            "bodies": bodies, "metrics": metrics}


def self_test():
    meta = {"mode": "replay", "class": "calls", "n": "2", "rounds": "2", "bodies": "4"}
    rows = [(0, "replay", 4000), (1, "replay", 8000)]
    result = summarize(meta, rows, "replay", "calls", 2, 2, 0)
    assert result["metrics"]["replay"]["us_per_body"] == 1.5
    memory_meta = {"mode": "memory", "class": "calls", "n": "2", "rounds": "2"}
    memory_rows = [(i, metric, value) for metric in METRICS["memory"]
                   for i, value in enumerate((-32, 64))]
    result = summarize(memory_meta, memory_rows, "memory", "calls", 2, 2, 0)
    assert result["bodies"] is None
    assert all(v["unit"] == "bytes" and "us_per_body" not in v for v in result["metrics"].values())
    for broken in [rows[:1], rows + rows[:1], [(2, "replay", 3)] + rows[1:],
                   [(0, "wrong", 3)] + rows[1:]]:
        try:
            summarize(meta, broken, "replay", "calls", 2, 2, 0)
        except RuntimeError:
            pass
        else:
            raise AssertionError("accepted malformed rounds")
    for changed in [dict(meta, bodies="2"), dict(meta, mode="cold")]:
        try:
            summarize(changed, rows, "replay", "calls", 2, 2, 0)
        except RuntimeError:
            pass
        else:
            raise AssertionError("accepted incorrect fixture metadata")
    try:
        parse_rows("meta\tmode\treplay\nmeta\tmode\tcold\n")
    except RuntimeError:
        pass
    else:
        raise AssertionError("accepted duplicate metadata")
    print("OK: benchmark units, body denominators, and strict round validation")


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
    parser.add_argument("--java-home", type=Path)
    parser.add_argument("--output", type=Path,
                        help="new directory; existing results are never overwritten")
    parser.add_argument("--sizes", default="100,1000")
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=12,
                        help="dropped rounds; these subjects need about ten to reach steady JIT state")
    parser.add_argument("--only", default="",
                        help="comma-separated subset of " + ",".join(MODES))
    parser.add_argument("--classes", default=",".join(CLASSES))
    parser.add_argument("--smoke", action="store_true",
                        help="3 rounds, no warmup; correctness only, not performance evidence")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.java_home is None or args.output is None:
        parser.error("--java-home and --output are required")
    if args.smoke:
        args.rounds, args.warmup = 3, 0
    if args.warmup < 0 or (not args.smoke and args.rounds - args.warmup < 8):
        raise SystemExit("at least 8 measured rounds are required")
    java = args.java_home.resolve() / "bin/java"
    compiler = Path(os.environ.get("DAWN_BIN", str(ROOT / "bin/dawn"))).resolve()
    if not java.exists():
        raise SystemExit("no java under " + str(args.java_home))
    sizes = [int(value) for value in args.sizes.split(",")]
    if not sizes or any(size < 1 for size in sizes):
        parser.error("--sizes must contain positive integers")
    requested = args.only.split(",") if args.only else list(MODES)
    classes = args.classes.split(",")
    if set(requested) - set(MODES) or len(requested) != len(set(requested)):
        parser.error("unknown or duplicate --only mode")
    if set(classes) - set(CLASSES) or len(classes) != len(set(classes)):
        parser.error("unknown or duplicate --classes entry")
    modes = [m for m in MODES if m in requested]
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
            for kind in classes:
                targets.append(("memory", kind, max(sizes)))
            continue
        for kind in classes:
            for size in sizes:
                targets.append((mode, kind, size))

    metadata = {
        "schema": 2, "smoke_only": args.smoke,
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "java": subprocess.run([str(java), "-version"], text=True, capture_output=True,
                               check=True).stderr.strip(),
        "jvm_flags": JVM_FLAGS,
        "compiler_launcher": str(compiler),
        "rounds": args.rounds, "warmup_rounds": args.warmup,
        "memory_rounds": MEMORY_ROUNDS,
        "measured_rounds": args.rounds - args.warmup,
        "load_before": load_average(),
        "sources": {},
        "limitations": [
            "wall clock on a shared machine; medians only, no speedup claim",
            "peak RSS is the whole process, not retained cache memory",
            "body timers exclude parsing, headers, and cold-equivalence validation",
            "outside-timer validation still influences allocation and JIT state",
            "retained snapshot/index deltas are not marginal semantic-cache memory",
            "renew alternates prebuilt revisions and carries the previous admission",
            "schema 2 uses explicit ns/bytes units and removes the private split",
        ],
    }
    for path in [SUBJECT, WORKLOADS, Path(__file__)]:
        metadata["sources"][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for directory in ("selfhost/src", "std"):
        digest = hashlib.sha256()
        for path in sorted((ROOT / directory).rglob("*.dawn")):
            digest.update(path.read_bytes())
        metadata["sources"][directory] = digest.hexdigest()

    with tempfile.TemporaryDirectory(prefix="dawn-bench-replay-") as temp:
        # The subject is a module of the compiler package (contract/reference),
        # so it is written into a private copy; the checkout is never written to.
        tree = Path(temp) / "tree"
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, tree / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (tree / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        fixture = install_probe(tree, {"reference": SUBJECT.read_text(), "workloads": WORKLOADS.read_text()})
        jar = output / "bench-replay.jar"
        with (output / "build.log").open("w") as log:
            subprocess.run([str(compiler), "build", str(fixture), "-o", str(jar)],
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
            warmup = 0 if mode == "memory" else args.warmup
            summary = summarize(meta, rows, mode, kind, size, rounds, warmup)
            summary.update(raw=name + ".tsv", peak_rss_kb=peak_rss_kb(rss),
                           smoke_only=args.smoke)
            summaries.append(summary)
            print(f"{name}: " + "  ".join(
                f"{metric}={value['median']:.1f}{value['unit']}"
                for metric, value in summary["metrics"].items()), flush=True)

    metadata["load_after"] = load_average()
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (output / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    with (output / "summary.tsv").open("w") as table:
        table.write("smoke_only\tmode\tclass\tn\tbodies\tmetric\tunit\tmedian\tstdev\tus_per_body\tpeak_rss_kb\n")
        for s in summaries:
            for metric, value in s["metrics"].items():
                table.write(f"{s['smoke_only']}\t{s['mode']}\t{s['class']}\t{s['n']}\t{s['bodies'] or ''}\t{metric}\t"
                            f"{value['unit']}\t{value['median']:.4f}\t{value['stdev']:.4f}\t"
                            f"{value.get('us_per_body', '')}\t{s['peak_rss_kb']}\n")

    print("wrote " + str(output / "summary.tsv"))


if __name__ == "__main__":
    main()
