#!/usr/bin/env python3
"""The call table the compiler writes for tileir's `Dev`, held to its record.

    run.py                     # 256 golden kernels, compared with rows.expected
    run.py --samples           # the two Playground samples, rows-samples.expected
    run.py --only vadd,sum     # a subset
    run.py --update            # rewrite the expected file from this tree
    run.py --baseline DIR      # compare with the tree at DIR instead (see below)
    run.py --native DAWNC      # run on a native driver too and require the same tables
    run.py --cases [--native]  # only the transcript cases and the refusals
    run.py --keep DIR          # keep the work tree (default: a temp dir)

`Dev` declares `calls(..)`, so the compiler brackets every public function
that has the effect and every closure such a function is handed. The harness
compiles tileir with its recording handler (prog.dawn) patched to leave the
table of calls the kernel made on the program it returns (`producer`), runs it
over scripts/tile-golden/kernels.dawn, and prints one row per call: name, call
site, parent row, operation range, globals range. `rows.expected` is that
print, the record the table is held to.

`--baseline DIR` is the proof the record was right to begin with: DIR is a tree
from before the hand-written marks were deleted (`called(..)`,
`called_bare(..)`, `user_body(..)`), and its table is the oracle. The two are
compared field by field, with two explained differences and nothing else: the
declared-name map (declared-names.txt: a function reports the name it is
declared with, the hand marks sometimes said something else), and the calls a
hand-marked author helper made inside itself (`fa_exp`, `fa_divide` wrote a
body mark; a compiler-written call has no closure parameter to put one on, so
what they call is theirs and not rows of its own).

What the comparison does not claim: it covers the kernels `trace(name)`
records (the programs the 256 goldens pin), and for a kernel that records more
than one program it sees the one `trace` returns.
"""
import argparse
import os

# JVM C emitter and independent native oracle; keep this consumer independent of the default chain.
os.environ["DAWN_SEED_CHAIN"] = "jar"
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# Author helpers whose hand-written marks put the calls in their bodies among
# the kernel's rows (see the module doc). Only `--baseline` folds them.
HELPERS = ("fa_exp", "fa_divide")

ROWS_FN = '''
fn call_site_text(c: Call) -> String =
  match c.at {
    Some(a) -> "${loc.path(a)}:${loc.line(a)}:${loc.col(a)}"
    None -> "-"
  }

fn rows_text(calls: List[Call]) -> String = {
  let rows = list.map(calls, c => "${c.name}|${call_site_text(c)}|${c.parent}|${c.ops_from}|${c.ops_to}|${c.globals_from}|${c.globals_to}")
  let rows_joined = list.fold(rows, "", (acc, r) => acc ++ r ++ "\\n")
  "CALLROWS\\n" ++ rows_joined ++ "END"
}
'''

# the one edit of prog.dawn, required to occur exactly once
PROG_EDIT = (
    "producer = None, debug = None }, calls, geometry)\n}\n",
    "producer = Some(rows_text(calls)), debug = None }, calls, geometry)\n}\n" + ROWS_FN,
)

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


class Tree:
    """A checkout the harness records: tileir, tileref, tileinterp and the
    kernels live at the same relative places in every one."""

    def __init__(self, root):
        self.root = Path(root)
        self.golden = self.root / "scripts" / "tile-golden"
        self.tileir = self.root / "packages" / "tileir"
        self.tileref = self.root / "packages" / "tileref"
        self.tileinterp = self.root / "packages" / "tileinterp"
        self.samples = [self.root / "site" / "play-ui" / "samples" / "flash_attn.dawn",
                        self.root / "playground" / "test" / "tile_vadd.dawn"]


def kernel_names(tree, only):
    names = sorted(p.stem for p in tree.golden.glob("*.mlir"))
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


def kernels_main(tree, names):
    k = (tree.golden / "kernels.dawn").read_text(encoding="utf-8")
    k = sub_once(k, "pub fn main() -> Unit !io = match args() {", "fn main_orig() -> Unit !io = match args() {", "kernels main")
    lit = "[" + ", ".join('"%s"' % n for n in names) + "]"
    return k + MAIN_NEW.replace("%NAMES%", lit)


def match_close(src, open_at):
    """The index of the parenthesis closing the one at open_at, skipping
    string literals and comments."""
    depth, k, n = 0, open_at, len(src)
    while k < n:
        c = src[k]
        if c == "#":
            k = src.find("\n", k)
            if k < 0:
                break
        elif c == '"':
            k += 1
            while k < n and src[k] != '"':
                k += 2 if src[k] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return k
        k += 1
    fail("unbalanced parenthesis")


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
    stmt = src[m.start():match_close(src, src.index("(", m.start() + len("  let (prog, _e) = trace") - 1)) + 1]
    return src + "\npub fn main() -> Unit !io = {\n" + prefix + stmt + "\n  println(\"@@kernel " + path.stem + "\")\n" \
        "  println(match prog.producer {\n    Some(s) -> s\n    None -> \"NOROWS\"\n  })\n}\n"


def build_variant(work, variant, main_src, tree, prog_patch=True, dev_source=None):
    root = work / variant
    if root.exists():
        shutil.rmtree(root)
    pkg = root / "tileir"
    shutil.copytree(tree.tileir, pkg, ignore=shutil.ignore_patterns(".dawn", "target"))
    shutil.copytree(tree.tileinterp, root / "tileinterp", ignore=shutil.ignore_patterns(".dawn", "target"))
    if prog_patch:
        prog = pkg / "src" / "prog.dawn"
        prog.write_text(sub_once(prog.read_text(encoding="utf-8"), PROG_EDIT[0], PROG_EDIT[1], "prog.dawn edit"), encoding="utf-8")
    if dev_source is not None:
        (pkg / "src" / "dev.dawn").write_text(dev_source, encoding="utf-8")
    proj = root / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "main.dawn").write_text(main_src, encoding="utf-8")
    (proj / "dawn.toml").write_text(
        'schema = 1\nname = "call_records_contract"\n\n[deps]\ntileir = "%s"\ntileref = "%s"\ntileinterp = "%s"\n' % (
            pkg, tree.tileref, root / "tileinterp"), encoding="utf-8")
    return proj


def run_project(proj, label, native=None, tree=None):
    """Run a recording project with the tree's own toolchain: a pre-deletion
    baseline needs the compiler of its day (its `staged_for` has no `at`)."""
    env = dict(os.environ)
    home = tree.root if tree else ROOT
    exe = [native, "run"] if native else [str(home / "bin" / "dawn"), "run"]
    r = subprocess.run(exe + [str(proj)], capture_output=True, text=True, cwd=home, env=env)
    if r.returncode != 0:
        fail("%s did not run:\n%s" % (label, (r.stderr or r.stdout)[-3000:]))
    return r.stdout


SITE = re.compile(r"^(?:.*/)?src/main\.dawn")


def parse(out):
    """kernel -> {"rows": [tuple], "untraced": text}; call sites lose the
    throwaway project path so two runs in different directories agree."""
    kernels, cur = {}, None
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
        rows_txt = text.split("CALLROWS\n", 1)[1]
        rows_txt = re.split(r"(?:^|\n)END\s*$", rows_txt)[0]
        rows = []
        for r in rows_txt.split("\n"):
            if r:
                f = r.split("|")
                f[1] = SITE.sub("main.dawn", f[1])
                rows.append(tuple(f))
        res[k] = {"rows": rows}
    return res


def table_text(res):
    out = []
    for k in sorted(res):
        out.append("@@kernel " + k)
        if "untraced" in res[k]:
            out.append("UNTRACED " + res[k]["untraced"])
        else:
            out.extend("|".join(r) for r in res[k]["rows"])
    return "\n".join(out) + "\n"


def parse_expected(text):
    res, cur = {}, None
    for line in text.splitlines():
        if line.startswith("@@kernel "):
            cur = line[len("@@kernel "):]
            res[cur] = {"rows": []}
        elif line.startswith("UNTRACED "):
            res[cur] = {"untraced": line[len("UNTRACED "):]}
        elif line:
            res[cur]["rows"].append(tuple(line.split("|")))
    return res


def fold_helpers(rows):
    """Drop the rows made inside an author helper's row (the descendants of a
    `fa_exp`/`fa_divide` row) and renumber the parents."""
    drop = set()
    for i, r in enumerate(rows):
        p = int(r[2])
        if p >= 0 and (rows[p][0] in HELPERS or p in drop):
            drop.add(i)
    keep = [i for i in range(len(rows)) if i not in drop]
    new = {old: n for n, old in enumerate(keep)}
    out = []
    for i in keep:
        r = list(rows[i])
        p = int(r[2])
        r[2] = str(new[p]) if p >= 0 else "-1"
        out.append(tuple(r))
    return out


def line_map(old, new):
    """Old line number -> new line number, over the lines the two sources share
    (the baseline's call sites are in a source that has since lost lines)."""
    import difflib
    a, b = old.split("\n"), new.split("\n")
    out = {}
    for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            out[blk.a + k + 1] = blk.b + k + 1
    return out


def remap_sites(res, lines):
    """The baseline's call sites on the lines of the source being compared."""
    for v in res.values():
        if "rows" not in v:
            continue
        rows = []
        for r in v["rows"]:
            m = re.fullmatch(r"(main\.dawn):(\d+):(\d+)", r[1])
            if m and int(m.group(2)) in lines:
                r = (r[0], "%s:%d:%s" % (m.group(1), lines[int(m.group(2))], m.group(3))) + r[2:]
            rows.append(r)
        v["rows"] = rows
    return res


def compare(want, got, rename=None, fold=False):
    """Return (problems, name pairs seen as (want -> got))."""
    rename = rename or {}
    problems, pairs = [], {}
    for k in sorted(want):
        w, g = want[k], got.get(k)
        if g is None:
            problems.append((k, "missing from the run"))
            continue
        if "untraced" in w or "untraced" in g:
            if w.get("untraced") != g.get("untraced"):
                problems.append((k, "refusal differs: %r vs %r" % (w.get("untraced"), g.get("untraced"))))
            continue
        wr = fold_helpers(w["rows"]) if fold else w["rows"]
        gr = g["rows"]
        if len(wr) != len(gr):
            problems.append((k, "row count %d vs %d" % (len(wr), len(gr))))
            continue
        for i, (x, y) in enumerate(zip(wr, gr)):
            if x[0] != y[0]:
                pairs[(x[0], y[0])] = pairs.get((x[0], y[0]), 0) + 1
            if x[0] != y[0] and rename.get(x[0]) != y[0]:
                problems.append((k, "row %d name %s vs %s" % (i, x[0], y[0])))
            for f, name in zip(range(1, 7), ("at", "parent", "ops_from", "ops_to", "globals_from", "globals_to")):
                if x[f] != y[f]:
                    problems.append((k, "row %d %s %s vs %s" % (i, name, x[f], y[f])))
    for k in sorted(set(got) - set(want)):
        problems.append((k, "not in the record"))
    return problems, pairs


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
    ap.add_argument("--native", help="a native driver (dawnc): run the tree on it too and require the same tables")
    ap.add_argument("--no-cases", action="store_true", help="skip the transcript cases and refusals")
    ap.add_argument("--native-build", action="store_true", help="build this tree's native driver first and use it as --native")
    ap.add_argument("--cases", action="store_true", help="run the transcript cases and the refusals only")
    ap.add_argument("--only")
    ap.add_argument("--keep")
    ap.add_argument("--update", action="store_true", help="rewrite the expected file from this tree")
    ap.add_argument("--baseline", help="a pre-deletion tree whose hand-written marks are the oracle")
    ap.add_argument("--dev", help="use this dev.dawn instead of the tree's (negative controls)")
    ap.add_argument("--kernel-edit", nargs=2, metavar=("OLD", "NEW"), help="replace one occurrence of OLD by NEW in the kernels' source (negative controls)")
    ap.add_argument("--dump", help="write the parsed table here as text")
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
    tree = Tree(ROOT)
    names = kernel_names(tree, args.only)
    if args.samples:
        programs = [(p.stem, sample_main(p)) for p in tree.samples]
    else:
        programs = [("kernels", kernels_main(tree, names))]
        if args.kernel_edit:
            programs = [(programs[0][0], sub_once(programs[0][1], args.kernel_edit[0], args.kernel_edit[1], "--kernel-edit"))]
    dev = Path(args.dev).read_text(encoding="utf-8") if args.dev else None
    got_out, native_problems = "", []
    for label, main_src in programs:
        proj = build_variant(work, "run-" + label, main_src, tree, dev_source=dev)
        out = run_project(proj, label)
        got_out += out
        if args.native:
            nat = parse(run_project(proj, label + " (native)", native=args.native))
            jvm = parse(out)
            for k, v in nat.items():
                if jvm.get(k) != v:
                    native_problems.append((k, "native and JVM record different tables"))
    got = parse(got_out)
    (work / "run.out").write_text(table_text(got))
    if args.dump:
        Path(args.dump).write_text(table_text(got))
    expected = HERE / ("rows-samples.expected" if args.samples else "rows.expected")
    if args.update:
        if args.only:
            fail("--update records every kernel; drop --only")
        expected.write_text(table_text(got))
        print("wrote %s: %d kernels" % (expected.name, len(got)))
        return 0
    pairs = {}
    if args.baseline:
        base = Tree(args.baseline)
        if args.samples:
            bprograms = [(p.stem, sample_main(p)) for p in base.samples]
        else:
            bprograms = [("kernels", kernels_main(base, kernel_names(base, args.only)))]
        base_out = ""
        for label, main_src in bprograms:
            base_out += run_project(build_variant(work, "base-" + label, main_src, base), "baseline " + label, tree=base)
        (work / "base.out").write_text(base_out)
        # a source's own lines are the same lines in both trees except where
        # the hand marks were deleted; the sites follow the lines
        base_res = parse(base_out)
        for (label, old_src), (_, new_src) in zip(bprograms, programs):
            lines = line_map(old_src, new_src)
            remap_sites({k: v for k, v in base_res.items() if label == "kernels" or k == label}, lines)
        rename = {}
        for line in (HERE / "declared-names.txt").read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                a, b = line.split()
                rename[a] = b
        problems, pairs = compare(base_res, got, rename, fold=True)
    else:
        want = parse_expected(expected.read_text())
        if args.only:
            want = {k: v for k, v in want.items() if k in got}
        problems, _ = compare(want, got)
    traced = sum(1 for v in got.values() if "rows" in v)
    rows = sum(len(v["rows"]) for v in got.values() if "rows" in v)
    print("kernels %d, traced %d, call rows %d" % (len(got), traced, rows))
    for k, msg in problems[:200]:
        print("DIFF %s: %s" % (k, msg))
    if args.baseline:
        print("name pairs (hand-written -> declared), count:")
        for (a, b), c in sorted(pairs.items()):
            print("  %s -> %s  x%d" % (a, b, c))
    problems += native_problems
    if args.native:
        print("native run compared with the JVM run: %d kernels, %d disagree" % (len(got), len(native_problems)))
    cases = [] if (args.samples or args.no_cases) else run_cases(None) + (run_cases(args.native) if args.native else [])
    for k, m in cases:
        print("DIFF %s: %s" % (k, m))
    problems += cases
    print("%d problems" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
