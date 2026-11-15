#!/usr/bin/env python3
"""Hand-written call marks against the compiler-written ones, field by field.

    run.py                     # 256 golden kernels, both variants, compare
    run.py --only vadd,sum     # a subset
    run.py --mutants           # also run the negative controls
    run.py --keep DIR          # keep the work tree (default: a temp dir)

Two variants of packages/tileir are compiled against the same kernel corpus
(scripts/tile-golden/kernels.dawn):

  hand  the tree as it is: `called(..)`, `called_bare(..)` and `user_body(..)`
        write every call mark and body mark;
  auto  dev.dawn derived by derive_fixture.py: no wrapper, `Dev` declares
        `calls(..)`, and the compiler writes the marks.

Each variant's recording handler (prog.dawn) is patched, identically, to leave
the table of calls the kernel made on the program it returns (`producer`), plus
the log of call and body marks it saw. The harness prints that for every
kernel; this script compares the two prints. The tables are compared in full:
name (through the declared-name map, listed at the end), call site, parent row,
operation range, globals range, and the kernel-body or library-body class of
every body mark.

What the comparison does not claim: it covers the kernels `trace(name)` records
(the programs the 256 goldens pin), and for a kernel that records more than one
program it sees the one `trace` returns.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import derive_fixture  # noqa: E402

GOLDEN = ROOT / "scripts" / "tile-golden"
TILEIR = ROOT / "packages" / "tileir"
TILEREF = ROOT / "packages" / "tileref"

ROWS_FN = '''
fn call_site_text(c: Call) -> String =
  match c.at {
    Some(a) -> "${loc.path(a)}:${loc.line(a)}:${loc.col(a)}"
    None -> "-"
  }

fn rows_text(calls: List[Call], log: List[String]) -> String = {
  let rows = list.map(calls, c => "${c.name}|${call_site_text(c)}|${c.parent}|${c.ops_from}|${c.ops_to}|${c.globals_from}|${c.globals_to}")
  let rows_joined = list.fold(rows, "", (acc, r) => acc ++ r ++ "\\n")
  let log_joined = list.fold(log, "", (acc, r) => acc ++ r ++ "\\n")
  "CALLROWS\\n" ++ rows_joined ++ "EVENTS\\n" ++ log_joined ++ "END"
}
'''

# (old, new) edits of prog.dawn, each required to occur exactly once
PROG_EDITS = [
    ("      var results: List[ResultState] = []\n      t_call_enter(called_name, site) => {\n",
     "      var results: List[ResultState] = []\n      var ev_log: List[String] = []\n"
     "      t_call_enter(called_name, site) => {\n        ev_log = ev_log ++ [\"E ${called_name}\"]\n"),
    ("      t_call_exit() => {\n        if len(marks) == 0 { refuse(name, \"a call mark closes nothing\") } else { () }\n",
     "      t_call_exit() => {\n        ev_log = ev_log ++ [\"X\"]\n        if len(marks) == 0 { refuse(name, \"a call mark closes nothing\") } else { () }\n"),
    ("      t_body_enter() => {\n        marks = marks ++ [if in_row(marks) { KernelBody } else { InnerBody }]\n",
     "      t_body_enter() => {\n        ev_log = ev_log ++ [if in_row(marks) { \"BK\" } else { \"BI\" }]\n"
     "        marks = marks ++ [if in_row(marks) { KernelBody } else { InnerBody }]\n"),
    ("      t_body_exit() => {\n        if len(marks) == 0 { refuse(name, \"a body mark closes nothing\") } else { () }\n",
     "      t_body_exit() => {\n        ev_log = ev_log ++ [\"BX\"]\n        if len(marks) == 0 { refuse(name, \"a body mark closes nothing\") } else { () }\n"),
    ("  let (globals, ops, calls, geometry) = {\n    with handle Dev {\n",
     "  let (globals, ops, calls, geometry, ev_log) = {\n    with handle Dev {\n"),
    ("    (globals, ops, calls, geometry)\n  }\n  (TileProg { name = entry.kernel, params = params, globals = globals, ops = [MakeToken(0)] ++ ops, hints = hints, producer = None, debug = None }, calls, geometry)\n}\n",
     "    (globals, ops, calls, geometry, ev_log)\n  }\n  (TileProg { name = entry.kernel, params = params, globals = globals, ops = [MakeToken(0)] ++ ops, hints = hints, producer = Some(rows_text(calls, ev_log)), debug = None }, calls, geometry)\n}\n" + ROWS_FN),
]

MAIN_NEW = '''
pub fn main() -> Unit !io = {
  for name in %NAMES% {
    match catch_panic(() => trace(name)) {
      Ok(p) -> {
        println("@@kernel ${name}")
        println(match p.producer {
          Some(s) -> s
          None -> "NOROWS"
        })
      }
      Err(e) -> println("@@kernel ${name}\\nUNTRACED ${e.message}")
    }
  }
}
'''


def fail(msg):
    print("call-records-contract: " + msg, file=sys.stderr)
    sys.exit(1)


def sub_once(text, old, new, what):
    if text.count(old) != 1:
        fail("%s: expected exactly one occurrence, found %d" % (what, text.count(old)))
    return text.replace(old, new, 1)


def kernel_names(only):
    names = sorted(p.stem for p in GOLDEN.glob("*.mlir"))
    if only:
        want = only.split(",")
        names = [n for n in names if n in want]
    return names


def build_native(work):
    """This tree's native driver, built the way the other native contracts build
    it (`__emitc --split`, then scripts/cc-units.sh): an explicit --native path
    is for a driver already at hand."""
    units, exe = work / "native-units", work / "dawnc"
    for cmd in ([str(ROOT / "bin" / "dawn"), "__emitc", str(ROOT / "selfhost/src/nmain.dawn"), "--split", str(units)],
                [str(ROOT / "scripts" / "cc-units.sh"), "-o", str(exe), str(units)]):
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            fail("building the native driver failed:\n" + (r.stderr or r.stdout)[-2000:])
    return str(exe)


# The tests the derived package fails, and why: each names `d_range` (the hand
# mark's display name for a staged `for`) or the creation site of its range,
# which a compiler-written `staged_for` record reports as its own name and no
# site. Everything else the package asserts about its calls (names, parents,
# ranges, refusal messages that name the call stack) holds unchanged.
DERIVED_TEST_FAILURES = [
    "prog :: a refusal names the operator as the kernel wrote it and the regions it is in, after the reason",
    "prog :: M5: a refusal at a `for` points at the line of its d_range, and a refusal inside it says which for",
    "prog :: PR-1 (n9): a place that wants a rank-0 tile refuses a wider one while the kernel records",
    "render :: what a loop's body calls are the d_range's children, and the d_range keeps its header, its continue and its brace",
    "render :: regions inside regions nest the rows: each call's parent is the region whose closure it is in",
    "render :: the map agrees with sentinels: every line is the call that ran between the two sentinels around it",
]


def derived_package_tests(work, auto_src):
    """Run the derived package's own test blocks; they must fail exactly where
    DERIVED_TEST_FAILURES says and nowhere else."""
    pkg = work / "derived-package" / "tileir"
    if pkg.parent.exists():
        shutil.rmtree(pkg.parent)
    shutil.copytree(TILEIR, pkg, ignore=shutil.ignore_patterns(".dawn", "target"))
    (pkg / "src" / "dev.dawn").write_text(auto_src, encoding="utf-8")
    r = subprocess.run([str(ROOT / "bin" / "dawn"), "test", str(pkg)], capture_output=True, text=True, cwd=ROOT)
    failed = sorted(l[len("FAIL  "):] for l in r.stdout.splitlines() if l.startswith("FAIL  "))
    problems = []
    if failed != sorted(DERIVED_TEST_FAILURES):
        problems.append(("derived package tests", "failing set differs: extra %s, missing %s" % (
            sorted(set(failed) - set(DERIVED_TEST_FAILURES)), sorted(set(DERIVED_TEST_FAILURES) - set(failed)))))
    total = re.search(r"(\d+) of (\d+) test\(s\) failed", r.stdout)
    print("derived package tests: %s" % (total.group(0) if total else "all passed"))
    return problems


def kernels_main(names):
    k = (GOLDEN / "kernels.dawn").read_text(encoding="utf-8")
    k = sub_once(k, "pub fn main() -> Unit !io = match args() {", "fn main_orig() -> Unit !io = match args() {", "kernels main")
    lit = "[" + ", ".join('"%s"' % n for n in names) + "]"
    return k + MAIN_NEW.replace("%NAMES%", lit)


SAMPLES = [ROOT / "site" / "play-ui" / "samples" / "flash_attn.dawn", ROOT / "playground" / "test" / "tile_vadd.dawn"]


def sample_main(path):
    """A Playground sample whose main now prints the call table of the program
    it traces instead of running it: everything before the `traceN(..)` call
    in main is kept (the cells it names), everything after is dropped."""
    src = path.read_text(encoding="utf-8")
    src = sub_once(src, "pub fn main() -> Unit !io = {", "pub fn main_orig() -> Unit !io = {", "%s main" % path.name)
    m = re.search(r"(?m)^  let \(prog, _\w+\) = trace\d\(", src)
    if not m:
        fail("%s: no `let (prog, _) = traceN(` in main" % path.name)
    body_start = src.index("pub fn main_orig() -> Unit !io = {") + len("pub fn main_orig() -> Unit !io = {\n")
    prefix = src[body_start:m.start()]
    code = derive_fixture.code_mask(src)
    open_at = src.index("(", m.start() + len("  let (prog, _e) = trace") - 1)
    depth, k = 0, open_at
    while True:
        if code[k]:
            if src[k] == "(":
                depth += 1
            elif src[k] == ")":
                depth -= 1
                if depth == 0:
                    break
        k += 1
    stmt = src[m.start():k + 1]
    return src + "\npub fn main() -> Unit !io = {\n" + prefix + stmt + "\n  println(\"@@kernel " + path.stem + "\")\n" \
        "  println(match prog.producer {\n    Some(s) -> s\n    None -> \"NOROWS\"\n  })\n}\n"


def build_variant(work, variant, main_src, dev_source=None):
    root = work / variant
    if root.exists():
        shutil.rmtree(root)
    pkg = root / "tileir"
    shutil.copytree(TILEIR, pkg, ignore=shutil.ignore_patterns(".dawn", "target"))
    shutil.copytree(ROOT / "packages" / "tileinterp", root / "tileinterp", ignore=shutil.ignore_patterns(".dawn", "target"))
    prog = pkg / "src" / "prog.dawn"
    text = prog.read_text(encoding="utf-8")
    for i, (old, new) in enumerate(PROG_EDITS):
        text = sub_once(text, old, new, "prog.dawn edit %d" % i)
    prog.write_text(text, encoding="utf-8")
    if dev_source is not None:
        (pkg / "src" / "dev.dawn").write_text(dev_source, encoding="utf-8")
    proj = root / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "main.dawn").write_text(main_src, encoding="utf-8")
    (proj / "dawn.toml").write_text(
        'schema = 1\nname = "call_records_contract"\n\n[deps]\ntileir = "%s"\ntileref = "%s"\ntileinterp = "%s"\n' % (
            pkg, TILEREF, root / "tileinterp"), encoding="utf-8")
    return proj


def run_project(proj, label, native=None):
    env = dict(os.environ)
    exe = [native, "run"] if native else [str(ROOT / "bin" / "dawn"), "run"]
    r = subprocess.run(exe + [str(proj)], capture_output=True, text=True, cwd=ROOT, env=env)
    if r.returncode != 0:
        fail("%s did not run:\n%s" % (label, (r.stderr or r.stdout)[-3000:]))
    return r.stdout


def parse(out):
    kernels = {}
    cur = None
    for line in out.splitlines():
        if line.startswith("@@kernel "):
            cur = line[len("@@kernel "):]
            kernels[cur] = []
        elif cur is not None:
            kernels[cur].append(line)
    res = {}
    for k, lines in kernels.items():
        text = "\n".join(lines)
        if "CALLROWS" not in text:
            res[k] = {"untraced": text.strip()}
            continue
        rows_part = text.split("CALLROWS\n", 1)[1]
        rows_txt, ev_txt = re.split(r"(?:^|\n)EVENTS\n", rows_part, maxsplit=1)
        ev_txt = re.split(r"(?:^|\n)END\s*$", ev_txt)[0]
        rows = [tuple(r.split("|")) for r in rows_txt.split("\n") if r]
        events = ev_txt.split("\n") if ev_txt else []
        res[k] = {"rows": rows, "events": events}
    return res


def body_classes(events):
    """Each body mark's class with the row depth that classified it."""
    return [e for e in events if e in ("BK", "BI")]


def compare(hand, auto, rename):
    """Return (problems, names seen as (hand -> auto))."""
    problems = []
    pairs = {}
    at_known = []
    for k in sorted(hand):
        h, a = hand[k], auto.get(k)
        if a is None:
            problems.append((k, "missing from the compiler-written run"))
            continue
        if "untraced" in h or "untraced" in a:
            if h.get("untraced") != a.get("untraced"):
                problems.append((k, "refusal differs: %r vs %r" % (h.get("untraced"), a.get("untraced"))))
            continue
        hr, ar = h["rows"], a["rows"]
        if len(hr) != len(ar):
            problems.append((k, "row count %d vs %d" % (len(hr), len(ar))))
            continue
        for i, (x, y) in enumerate(zip(hr, ar)):
            if x[0] != y[0]:
                pairs.setdefault((x[0], y[0]), 0)
                pairs[(x[0], y[0])] += 1
            if x[0] != y[0] and rename.get(x[0]) != y[0]:
                problems.append((k, "row %d name %s vs %s" % (i, x[0], y[0])))
            for f, name in zip(range(1, 7), ("at", "parent", "ops_from", "ops_to", "globals_from", "globals_to")):
                if x[f] != y[f]:
                    # the one field whose source is not the function's own
                    # `caller()` parameter: a staged `for` reports the range's
                    # creation site, which no parameter of staged_for holds
                    if name == "at" and (x[0], y[0]) == ("d_range", "staged_for") and y[f] == "-":
                        at_known.append((k, i, x[f]))
                        continue
                    problems.append((k, "row %d %s %s vs %s" % (i, name, x[f], y[f])))
        if body_classes(h["events"]) != body_classes(a["events"]):
            problems.append((k, "body classes differ: %s vs %s" % (body_classes(h["events"])[:12], body_classes(a["events"])[:12])))
    return problems, pairs, at_known


CASES = HERE / "cases"
REJECT = HERE / "reject"


def run_cases(native=None):
    """The transcript cases and the refusals; on the JVM, and again natively
    when a native driver is given. Returns the problem list."""
    problems = []
    exe = [native, "run"] if native else [str(ROOT / "bin" / "dawn"), "run"]
    r = subprocess.run(exe + [str(CASES / "records.dawn")], capture_output=True, text=True, cwd=ROOT)
    want = (CASES / "records.expected").read_text()
    if r.returncode != 0:
        problems.append(("cases/records.dawn", "did not run: " + (r.stderr or r.stdout)[-600:]))
    elif r.stdout != want:
        got, exp = r.stdout.splitlines(), want.splitlines()
        first = next((i for i, (a, b) in enumerate(zip(got, exp)) if a != b), min(len(got), len(exp)))
        problems.append(("cases/records.dawn", "transcript differs at line %d: got %r, want %r" % (
            first + 1, got[first] if first < len(got) else None, exp[first] if first < len(exp) else None)))
    for f in sorted(REJECT.glob("*.dawn")):
        expect = f.read_text().splitlines()[0].split("# expect: ", 1)[1]
        r = subprocess.run([str(ROOT / "bin" / "dawn"), "check", str(f)], capture_output=True, text=True, cwd=ROOT)
        if r.returncode == 0 or expect not in (r.stdout + r.stderr):
            problems.append(("reject/" + f.name, "expected a refusal containing %r, got exit %d: %s" % (
                expect, r.returncode, (r.stdout + r.stderr)[:300])))
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", action="store_true", help="the Playground vadd and flash_attn samples instead of the golden kernels")
    ap.add_argument("--native", help="a native driver (dawnc): run the compiler-written variant on it too and require the same tables")
    ap.add_argument("--no-cases", action="store_true", help="skip the transcript cases and refusals")
    ap.add_argument("--native-build", action="store_true", help="build this tree's native driver first and use it as --native")
    ap.add_argument("--cases", action="store_true", help="run the transcript cases and the refusals only")
    ap.add_argument("--only")
    ap.add_argument("--keep")
    ap.add_argument("--rename", help="file of 'hand auto' lines: the declared-name map")
    ap.add_argument("--auto-dev", help="use this derived dev.dawn instead of deriving one")
    ap.add_argument("--auto-only", action="store_true", help="skip the hand run (reuse --hand-out)")
    ap.add_argument("--hand-out")
    ap.add_argument("--dump", help="write both parsed runs here as text")
    args = ap.parse_args()
    work = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="call-records."))
    work.mkdir(parents=True, exist_ok=True)
    if args.native_build:
        args.native = build_native(work)
    if args.cases:
        probs = run_cases(None)
        if args.native:
            probs += run_cases(args.native)
        for k, m in probs:
            print("DIFF %s: %s" % (k, m))
        print("%d problems" % len(probs))
        return 1 if probs else 0
    names = kernel_names(args.only)
    rename = {}
    if True:
        for line in (Path(args.rename) if args.rename else HERE / "declared-names.txt").read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                a, b = line.split()
                rename[a] = b
    dev = (TILEIR / "src" / "dev.dawn").read_text(encoding="utf-8")
    if args.auto_dev:
        auto_src = Path(args.auto_dev).read_text(encoding="utf-8")
    else:
        auto_src, n = derive_fixture.derive(dev)
        print("derived %d wrapper sites away" % n)
    if args.samples:
        programs = [(p.stem, sample_main(p)) for p in SAMPLES]
    else:
        programs = [("kernels", kernels_main(names))]
    hand_out, auto_out, native_outs, native_problems = "", "", "", []
    for label, main_src in programs:
        if args.auto_only and args.hand_out:
            hand_out = Path(args.hand_out).read_text()
        else:
            hand_out += run_project(build_variant(work, "hand-" + label, main_src), "hand variant " + label)
        auto_proj = build_variant(work, "auto-" + label, main_src, auto_src)
        auto_out += run_project(auto_proj, "compiler-written variant " + label)
        if args.native:
            native_out = run_project(auto_proj, "compiler-written variant (native) " + label, native=args.native)
            native_outs += native_out
            jvm_one = parse(auto_out)
            nat_one = parse(native_out)
            for k, v in nat_one.items():
                if jvm_one.get(k) != v:
                    native_problems.append((k, "native and JVM record different tables"))
    (work / "hand.out").write_text(hand_out)
    (work / "auto.out").write_text(auto_out)
    hand, auto = parse(hand_out), parse(auto_out)
    problems, pairs, at_known = compare(hand, auto, rename)
    traced = sum(1 for v in hand.values() if "rows" in v)
    rows = sum(len(v["rows"]) for v in hand.values() if "rows" in v)
    print("kernels %d, traced %d, call rows compared %d" % (len(hand), traced, rows))
    for k, msg in problems[:200]:
        print("DIFF %s: %s" % (k, msg))
    print("name pairs (hand -> declared), count:")
    for (a, b), c in sorted(pairs.items()):
        print("  %s -> %s  x%d" % (a, b, c))
    print("known at differences (staged_for reports no site, hand d_range reports the range's): %d rows" % len(at_known))
    problems += native_problems
    if args.native:
        print("native run compared with the JVM run: %d kernels, %d disagree" % (len(parse(native_outs)), len(native_problems)))
    problems += [] if (args.samples or args.only) else derived_package_tests(work, auto_src)
    cases = [] if (args.samples or args.no_cases) else run_cases(None) + (run_cases(args.native) if args.native else [])
    for k, m in cases:
        print("DIFF %s: %s" % (k, m))
    problems += cases
    print("%d problems" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
