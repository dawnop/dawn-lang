#!/usr/bin/env python3
"""Count production replay over a matrix of real edits; no timing claims.

bench-replay's only edit prepends a comment, which every admitted body
survives, so its hit counts cannot say what an ordinary edit costs. This
harness applies ten edits to four workload classes and holds every cell to an
exact count prediction, derived in docs/real-edit-matrix-design.md and spelled
in `oracle` below, plus body-by-body equality with a cold check.

The Dawn side (edit-matrix.dawn.txt) only observes; this side judges, so a
mutated compiler shows up as the cells whose counts or products moved rather
than as one panic. `--controls` runs the compiling mutants against a private
compiler copy and requires each to turn its own cells red, then restores the
source and requires the whole selection green again. `--check-anchors` is the
mutation-anchor preflight: it applies every mutant in memory and builds
nothing. Counts only: the machine is shared, so no timer is started.
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SUBJECT = HERE / "edit-matrix.dawn.txt"
WORKLOADS = HERE / "replay-workloads.dawn.txt"
JVM_FLAGS = ["-Xss64m", "-Xmx2g"]

CLASSES = ("calls", "primitive_inferred", "generic", "inferred")
EDITS = ("identical", "shift", "body_one", "body_one_type_error", "inferred_return",
         "ws_between", "ws_inside", "insert_decl", "delete_decl", "reorder")
# Class shape, read off replay-workloads.dawn.txt: function bodies in the
# support prefix, bodies no producer claims by role (generic's impl method),
# and whether every member is outside the admitted class (the lambda-heavy
# inferred workload, admitted by nothing today).
SUPPORT_FUNCTIONS = {"calls": 2, "primitive_inferred": 1, "generic": 0, "inferred": 0}
ROLE_BODIES = {"calls": 0, "primitive_inferred": 0, "generic": 1, "inferred": 0}
MEMBERS_REFUSED = {"calls": False, "primitive_inferred": False, "generic": False, "inferred": True}
# edit-matrix.dawn.txt appends one inferred function and two inferred callers.
PROBE_BODIES, PROBE_CALLERS = 3, 2

STEPS = ("replay", "renew", "back")
FIELDS = ("body_count", "by_role", "diags", "checked", "reused", "cold_unadmitted",
          "cold_rejected", "visited", "capture_refused", "admitted", "equal")
PREDICTED = ("body_count", "by_role", "checked", "reused", "cold_unadmitted",
             "cold_rejected", "visited", "capture_refused")
COLUMNS = ("class", "edit", "body_count", "checked", "reused", "cold_unadmitted",
           "cold_rejected", "visited", "capture_refused", "hit_rate_all",
           "hit_rate_admissible", "oracle_ok")

# Compiling mutants. Each owns the cells it must turn red; any other cell it
# moves is reported, not required. Anchors must occur exactly once.
MUTATIONS = {
    # same_text alone: `pair` still compares spellings, so only an edit that
    # moves bytes without changing a token (ws_inside) reaches it.
    "same-text-blind": {
        "edits": [("selfhost/src/check/source_projection.dawn",
                   "  if old_hi - old_lo != new_hi - new_lo { return false }",
                   "  if true { return true }")],
        "owns": [(kind, "ws_inside") for kind in CLASSES if not MEMBERS_REFUSED[kind]],
    },
    # The declaration-identity check is pair's spellings plus same_text; a
    # changed body literal gets past it only when both are blind.
    "identity-blind": {
        "edits": [("selfhost/src/check/source_projection.dawn",
                   "  if old_hi - old_lo != new_hi - new_lo { return false }",
                   "  if true { return true }"),
                  ("selfhost/src/check/source_projection.dawn",
                   "x.kinds == y.kinds && x.texts == y.texts", "x.kinds == y.kinds")],
        "owns": [(kind, "body_one") for kind in CLASSES if not MEMBERS_REFUSED[kind]],
    },
    # A caller's recorded function answer is no longer compared with the
    # candidate revision's, so an inferred signature change rejects nobody.
    "inferred-callers-kept": {
        "edits": [("selfhost/src/check/scalar_replay.dawn",
                   "    if not call_header_fact(prepared.callees, cx, read) "
                   "{ return (Prepared { ..prepared, memo: memo }, Rejected) }",
                   "    continue")],
        "owns": [(kind, "inferred_return") for kind in CLASSES],
    },
}


# ---------------------------------------------------------------- oracle

def oracle(kind, edit, n):
    """Exact counts per step; the derivation is in the design document."""
    m = n // 2
    role = ROLE_BODIES[kind]
    refused = MEMBERS_REFUSED[kind]
    base = SUPPORT_FUNCTIONS[kind] + n + role

    def members_cold(count):
        # Members outside the class are cold whatever the edit did.
        return n if refused else count

    def row(bodies, unadmitted, rejected=0, diags=False):
        return {"body_count": bodies, "by_role": role, "diags": diags,
                "checked": unadmitted + rejected, "reused": bodies - unadmitted - rejected,
                "cold_unadmitted": unadmitted, "cold_rejected": rejected}

    clean = row(base, role + members_cold(0))
    one = row(base, role + members_cold(1))
    if edit in ("identical", "shift", "ws_between", "reorder"):
        forward = back = clean
    elif edit in ("body_one", "ws_inside"):
        forward = back = one
    elif edit == "body_one_type_error":
        # relocation refuses once the scheduler context holds a diagnostic,
        # so the edited member and every member scheduled after it go cold.
        forward, back = row(base, role + members_cold(n - m), diags=True), one
    elif edit == "inferred_return":
        forward = back = row(base + PROBE_BODIES, role + members_cold(0) + 1, PROBE_CALLERS)
    elif edit == "insert_decl":
        forward = row(base + 1, role + (n + 1 if refused else 1))
        back = clean
    elif edit == "delete_decl":
        forward = row(base - 1, role + (n - 1 if refused else 0))
        back = one
    else:
        raise ValueError("unknown edit " + edit)
    expected = {}
    for step, counts in (("replay", forward), ("renew", forward), ("back", back)):
        visited = -1 if step == "replay" else counts["body_count"]
        refused_captures = -1 if step == "replay" else 0
        expected[step] = dict(counts, visited=visited, capture_refused=refused_captures)
    return expected


def mismatches(kind, edit, n, observed):
    """Every disagreement between one cell's three observed steps and its oracle."""
    expected = oracle(kind, edit, n)
    problems = []
    if set(observed) != set(STEPS):
        return [f"steps {sorted(observed)} != {sorted(STEPS)}"]
    for step in STEPS:
        got, want = observed[step], expected[step]
        for field in PREDICTED:
            if got[field] != want[field]:
                problems.append(f"{step}.{field} {got[field]} != predicted {want[field]}")
        if (got["diags"] > 0) != want["diags"]:
            problems.append(f"{step}.diags {got['diags']} but predicted "
                            + ("some" if want["diags"] else "none"))
        if got["equal"] != 1:
            problems.append(f"{step} typed bodies differ from the cold check")
    return problems


# ---------------------------------------------------------------- parsing

def parse(text, classes, edits, n):
    cells, meta = {}, {}
    for line in text.splitlines():
        values = line.split("\t")
        if values[0] == "meta" and len(values) == 3:
            if values[1] in meta:
                raise RuntimeError("duplicate metadata " + values[1])
            meta[values[1]] = values[2]
        elif values[0] == "step" and len(values) == 4 + len(FIELDS):
            kind, edit, step = values[1:4]
            if kind not in classes or edit not in edits or step not in STEPS:
                raise RuntimeError("unrequested cell: " + line)
            cell = cells.setdefault((kind, edit), {})
            if step in cell:
                raise RuntimeError("duplicate step: " + line)
            cell[step] = dict(zip(FIELDS, map(int, values[4:])))
        elif line.strip():
            raise RuntimeError("invalid matrix row: " + line)
    if meta.get("n") != str(n) or meta.get("done") != "1":
        raise RuntimeError(f"incomplete run: metadata {meta}")
    if set(cells) != {(k, e) for k in classes for e in edits}:
        raise RuntimeError("missing cells")
    if any(set(steps) != set(STEPS) for steps in cells.values()):
        raise RuntimeError("a cell is missing one of its steps")
    return cells


def rates(counts):
    admissible = counts["body_count"] - counts["by_role"]
    return (counts["reused"] / counts["body_count"],
            counts["reused"] / admissible if admissible else 0.0)


def percentile(values, q):
    """Nearest rank: the smallest value with at least q of the sample at or below it."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def table(cells, classes, edits, n):
    rows, ok = [], True
    for kind in classes:
        for edit in edits:
            observed = cells[(kind, edit)]
            problems = mismatches(kind, edit, n, observed)
            ok = ok and not problems
            for step in ("renew", "back"):
                counts = observed[step]
                own = [p for p in problems if p.startswith(step + ".") or p.startswith(step + " ")
                       or (step == "renew" and p.startswith("replay"))]
                every, admissible = rates(counts)
                rows.append({"step": step, "class": kind, "edit": edit,
                             **{f: counts[f] for f in COLUMNS[2:9]},
                             "hit_rate_all": every, "hit_rate_admissible": admissible,
                             "oracle_ok": not own, "problems": own})
    return rows, ok


def summaries(rows, classes):
    out = {}
    for kind in classes:
        forward = [r for r in rows if r["class"] == kind and r["step"] == "renew"]
        out[kind] = {key: {"p50": percentile([r[key] for r in forward], 0.5),
                           "p95": percentile([r[key] for r in forward], 0.95)}
                     for key in ("hit_rate_all", "hit_rate_admissible")}
    return out


def render(rows, summary, step):
    lines = ["\t".join(COLUMNS)]
    for r in rows:
        if r["step"] == step:
            lines.append("\t".join(f"{r[c]:.4f}" if c.startswith("hit_rate") else str(r[c])
                                   for c in COLUMNS))
    if step == "renew":
        lines.append("#\tclass\tp50_all\tp95_all\tp50_admissible\tp95_admissible")
        for kind, s in summary.items():
            lines.append(f"#\t{kind}\t{s['hit_rate_all']['p50']:.4f}\t{s['hit_rate_all']['p95']:.4f}\t"
                         f"{s['hit_rate_admissible']['p50']:.4f}\t{s['hit_rate_admissible']['p95']:.4f}")
    return "\n".join(lines)


# ---------------------------------------------------------------- building

def mutated(sources, name):
    out = dict(sources)
    for path, before, after in MUTATIONS[name]["edits"]:
        count = out[path].count(before)
        if count != 1:
            raise RuntimeError(f"{name}: mutation anchor matched {count} times in {path}: {before!r}")
        out[path] = out[path].replace(before, after)
    return out


def originals():
    return {path: (ROOT / path).read_text()
            for spec in MUTATIONS.values() for path, _, _ in spec["edits"]}


def check_anchors():
    sources = originals()
    for name in MUTATIONS:
        changed = mutated(sources, name)
        if changed == sources:
            raise RuntimeError(name + ": mutation changed nothing")
    print(f"OK: {len(MUTATIONS)} edit-matrix mutation anchors, "
          f"{sum(len(s['edits']) for s in MUTATIONS.values())} substitutions, no build")


def build(compiler_root, out_dir, log):
    fixture = out_dir / "fixture"
    (fixture / "src").mkdir(parents=True)
    shutil.copyfile(SUBJECT, fixture / "src/reference.dawn")
    # a project's entry module is src/main.dawn (spec §10.5); the fixture's own
    # `main` is an ordinary function now, so a two-line entry forwards to it
    (fixture / "src/main.dawn").write_text("use reference\n\npub fn main() -> Unit !io = reference.main()\n")
    shutil.copyfile(WORKLOADS, fixture / "src/workloads.dawn")
    (fixture / "dawn.toml").write_text(
        'schema = 1\nname = "edit_matrix"\n\n[deps]\n'
        f'compiler = "{compiler_root / "selfhost"}"\ncompiler_plan = "{compiler_root / "compiler-plan"}"\n')
    jar = out_dir / "edit-matrix.jar"
    dawn = os.environ.get("DAWN_BIN", str(ROOT / "bin/dawn"))
    result = subprocess.run([dawn, "build", str(fixture), "-o", str(jar)], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1800)
    log.write_text(result.stdout)
    if result.returncode:
        raise RuntimeError("edit-matrix subject did not compile\n" + result.stdout[-4000:])
    return jar


def java():
    home = os.environ.get("JAVA_HOME")
    return str(Path(home) / "bin/java") if home else "java"


def observe(jar, classes, edits, n):
    result = subprocess.run([java(), *JVM_FLAGS, "-jar", str(jar), ",".join(classes), ",".join(edits),
                             str(n)], cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=3600)
    if result.returncode:
        raise RuntimeError("edit-matrix subject failed\n" + result.stderr[-4000:])
    return parse(result.stdout, classes, edits, n)


def report(cells, classes, edits, n, output=None, label=None):
    rows, ok = table(cells, classes, edits, n)
    summary = summaries(rows, classes)
    heading = f"== {label} ==\n" if label else ""
    print(heading + "forward (before -> after, replay_and_record; replay agrees):\n"
          + render(rows, summary, "renew"))
    print("renewed back (after -> before, from the renewed cache):\n" + render(rows, summary, "back"))
    for r in rows:
        for problem in r["problems"]:
            print(f"MISMATCH {r['class']} {r['edit']}: {problem}")
    if output:
        output.mkdir(parents=True, exist_ok=True)
        name = (label or "matrix").replace(" ", "-")
        (output / f"{name}.json").write_text(json.dumps(
            {"n": n, "rows": rows, "summary": summary,
             "steps": {f"{k}/{e}": v for (k, e), v in cells.items()}}, indent=2) + "\n")
        (output / f"{name}.tsv").write_text(render(rows, summary, "renew") + "\n")
    return rows, ok


def red_cells(rows):
    return sorted({(r["class"], r["edit"]) for r in rows if not r["oracle_ok"]})


def controls(classes, edits, n, output):
    """Mutants first, each red in its own cells; then the restored source, green."""
    started = time.monotonic()
    sources = originals()
    with tempfile.TemporaryDirectory(prefix="dawn-edit-matrix-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        for name in list(MUTATIONS) + ["restored"]:
            t0 = time.monotonic()
            variant = sources if name == "restored" else mutated(sources, name)
            for path, text in variant.items():
                (root / path).write_text(text)
            owned = [] if name == "restored" else MUTATIONS[name]["owns"]
            run_classes = classes
            run_edits = edits if name == "restored" else sorted({e for _, e in owned if e in edits}, key=EDITS.index)
            if not run_edits:
                raise RuntimeError(f"{name}: none of its owned cells is selected")
            jar = build(root, root / f"out-{name}", root / f"build-{name}.log")
            cells = observe(jar, run_classes, run_edits, n)
            rows, ok = report(cells, run_classes, run_edits, n, output, name)
            red = red_cells(rows)
            elapsed = time.monotonic() - t0
            if name == "restored":
                if not ok:
                    raise RuntimeError(f"restored source is not green: {red}")
                print(f"OK: restored source green on {len(rows) // 2} cells ({elapsed:.1f}s)", flush=True)
                continue
            missing = [cell for cell in owned if cell[0] in run_classes and cell[1] in run_edits
                       and cell not in red]
            if missing:
                raise RuntimeError(f"{name} left owned cells green: {missing}")
            print(f"OK: mutant {name} red in owned cells {[c for c in red if c in owned]}; "
                  f"also red: {[c for c in red if c not in owned]} ({elapsed:.1f}s)", flush=True)
    print(f"OK: {len(MUTATIONS)} compiling edit-matrix controls red, restored source green; "
          f"elapsed={time.monotonic() - started:.1f}s")


# ---------------------------------------------------------------- self-test

def synthetic(n, classes, edits, tweak=None):
    lines = [f"meta\tn\t{n}"]
    for kind in classes:
        for edit in edits:
            for step, counts in oracle(kind, edit, n).items():
                values = dict(counts, diags=2 if counts["diags"] else 0, admitted=0, equal=1)
                if tweak:
                    tweak(kind, edit, step, values)
                lines.append("\t".join(["step", kind, edit, step] + [str(int(values[f])) for f in FIELDS]))
    lines.append("meta\tdone\t1")
    return "\n".join(lines) + "\n"


def self_test():
    n = 20
    cells = parse(synthetic(n, CLASSES, EDITS), CLASSES, EDITS, n)
    rows, ok = table(cells, CLASSES, EDITS, n)
    assert ok and len(rows) == 2 * len(CLASSES) * len(EDITS)
    # The n=20 census the production run reported when this oracle was written.
    assert oracle("calls", "body_one_type_error", n)["replay"]["cold_unadmitted"] == 10
    assert oracle("generic", "inferred_return", n)["renew"]["reused"] == 20
    assert oracle("inferred", "inferred_return", n)["back"]["cold_unadmitted"] == 21
    rejected = 0
    for field in PREDICTED + ("equal", "diags"):
        for step in STEPS:
            def tweak(kind, edit, at, values, field=field, step=step):
                if (kind, edit, at) == ("generic", "insert_decl", step):
                    values[field] = values[field] + 1 if field != "diags" else 1
            if field in ("visited", "capture_refused") and step == "replay":
                continue
            bad = parse(synthetic(n, CLASSES, EDITS, tweak), CLASSES, EDITS, n)
            rows, ok = table(bad, CLASSES, EDITS, n)
            if ok or red_cells(rows) != [("generic", "insert_decl")]:
                raise AssertionError(f"oracle accepted a moved {step}.{field}")
            rejected += 1
    for broken in ["", synthetic(n, CLASSES, EDITS).replace("meta\tdone\t1\n", ""),
                   synthetic(n, CLASSES, EDITS) + "step\tcalls\tshift\trenew" + "\t0" * len(FIELDS) + "\n",
                   synthetic(n, CLASSES, EDITS).replace("step\tcalls\tshift\tback", "step\tcalls\tshift\tsideways"),
                   synthetic(n, CLASSES, EDITS).replace(f"meta\tn\t{n}", "meta\tn\t21"),
                   synthetic(n, CLASSES, EDITS) + "garbage\n",
                   "\n".join(l for l in synthetic(n, CLASSES, EDITS).splitlines()
                             if not l.startswith("step\tcalls\treorder\tback")) + "\n"]:
        try:
            parse(broken, CLASSES, EDITS, n)
        except RuntimeError:
            continue
        raise AssertionError("parser accepted a malformed run")
    assert percentile([0.1 * i for i in range(10)], 0.5) == 0.4
    assert percentile([0.1 * i for i in range(10)], 0.95) == 0.9
    for name, spec in MUTATIONS.items():
        assert spec["owns"] and all(k in CLASSES and e in EDITS for k, e in spec["owns"]), name
    check_anchors()
    print(f"OK: edit-matrix oracle, {len(CLASSES) * len(EDITS)} cells, {rejected} moved-count "
          "rejections, 7 malformed runs, nearest-rank percentiles")


# ---------------------------------------------------------------- main

def selection(value, universe, flag):
    chosen = value.split(",") if value else list(universe)
    if not chosen or set(chosen) - set(universe) or len(chosen) != len(set(chosen)):
        raise SystemExit(f"{flag}: unknown or duplicate entry in {value!r}")
    return [x for x in universe if x in chosen]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--classes", default="", help="comma-separated subset of " + ",".join(CLASSES))
    parser.add_argument("--edits", default="", help="comma-separated subset of " + ",".join(EDITS))
    parser.add_argument("--functions", type=int, default=1000)
    parser.add_argument("--output", type=Path, help="directory for JSON/TSV results")
    parser.add_argument("--controls", action="store_true",
                        help="run the compiling mutants, then the restored source")
    parser.add_argument("--check-anchors", action="store_true",
                        help="apply every mutant in memory; builds nothing")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.check_anchors:
        check_anchors()
        return 0
    classes = selection(args.classes, CLASSES, "--classes")
    edits = selection(args.edits, EDITS, "--edits")
    if args.functions < 4:
        parser.error("--functions must be at least 4")
    if args.controls:
        controls(classes, edits, args.functions, args.output)
        return 0
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="dawn-edit-matrix-") as temp:
        jar = build(ROOT, Path(temp), Path(temp) / "build.log")
        cells = observe(jar, classes, edits, args.functions)
    _, ok = report(cells, classes, edits, args.functions, args.output)
    print(("OK" if ok else "FAIL") + f": {len(classes) * len(edits)} cells at n={args.functions}, "
          f"counts only; elapsed={time.monotonic() - started:.1f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
