#!/usr/bin/env python3
"""The two reference tables of packages/tileir are held to the source they describe.

    scripts/tileir-docs/check.py              # check both tables
    scripts/tileir-docs/check.py --self-test  # negative controls

packages/tileir/OPERATIONS.md says, for every public function of `tileir/dev`
and `tileir/prog`, which `cuda_tile` operation it records. packages/tileir/
ERRORS.md says which of four layers an error comes from, what it looks like
and how to fix it, and lists every `gpu.*` error kind. A table like that is
read once and then trusted, and a trusted table that nothing reads rots: the
same shape as the builtin mirror (selfhost/builtins.dawn, whose gate holds it
to the checker's table in both directions) and the three coverage ledgers
beside this directory. So both are checked here, and the rule for each is
"a row too few is red, and a row too many is red".

## OPERATIONS.md

  * Surface. The functions are the `pub fn` of dev.dawn and prog.dawn, plus
    the seven bitwise and shift prelude trait methods implemented on Tile. Each
    has exactly one row, and each row names a function that is there. A new
    public function does not compile past this gate until it has said what it
    records (a function that records nothing says `-`).
  * Vocabulary. Every operation a row names is one of the opcodes of
    scripts/tileir-features/features.txt (the frozen dialect table), so a
    misspelled mnemonic is red.
  * Reach. Every opcode that ledger calls `implemented` or `structural` is
    named by some row, so an operation the backend writes but no function is
    documented to record is red. The other direction, which operation a given
    function really records, is the goldens' to say (scripts/tile-golden), not
    a text file's; the rows were written against `render.line_map`'s
    attribution over those goldens.

## ERRORS.md

  * Kinds. The table of `gpu.*` error kinds holds exactly the kinds std/gpu.dawn
    builds before its tests start (`refuse("gpu.x", ..)` and the
    `Err(("gpu.x", ..))` of the launch plan), plus the two the runtime builds
    (`gpu.no_driver` in runtime/c/dawn_rt.c, `gpu.unsupported_backend` in
    runtime/c/dawn_rt.c and the JVM runtime classes), each of which must still
    be spelled in its source file.
  * Fragments. The type-check, recording and emitting layers have no codes,
    only messages, so their rows are keyed by a fragment of the message that
    is a literal in the source (the checker's for the first, packages/tileir's
    for the other two). A fragment the source no longer contains is red,
    which is how a reworded message finds the row that quotes it.
  * Layers. The four layers are named, each is present, and every row says
    which one it belongs to.

## README.md

  * The first example. README.md shows a whole program, from `trace3` to an
    assertion on the fake device's answer, and says it is
    examples/projects/gpu_fake/src/first.dawn. CI compiles that file and runs
    its tests, but not the README, so the README's functions are compared with
    the file's, text for text (the `##` comments above them aside). Edit one and
    not the other and this is red, which is what keeps the example in the README
    a program that runs.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PKG = ROOT / "packages" / "tileir"
OPERATIONS = PKG / "OPERATIONS.md"
ERRORS = PKG / "ERRORS.md"
README = PKG / "README.md"
FIRST = ROOT / "examples" / "projects" / "gpu_fake" / "src" / "first.dawn"
DEV = PKG / "src" / "dev.dawn"
PROG = PKG / "src" / "prog.dawn"
SRC = PKG / "src"
GPU = ROOT / "std" / "gpu.dawn"
FEATURES = ROOT / "scripts" / "tileir-features" / "features.txt"
RUNTIME_C = ROOT / "runtime" / "c" / "dawn_rt.c"
RUNTIME_JVM = ROOT / "selfhost" / "src" / "jvm" / "rtclasses.dawn"
CHECKER = ROOT / "selfhost" / "src" / "check" / "checker.dawn"

# The kinds the runtime builds, and the files that must still spell them.
RUNTIME_KINDS = {
    "gpu.no_driver": [RUNTIME_C],
    "gpu.unsupported_backend": [RUNTIME_C, RUNTIME_JVM],
}
LAYERS = ("type check", "record", "emit", "device")
# The items of the example file the README shows verbatim: "fn <name>" or
# 'test "<name>"'. The README's first example is that program, and it stays so
# because this gate compares the text.
SHOWN = ("fn vadd", "fn record", "fn run", "fn xs", "fn ys", "fn expected",
         'test "the kernel launched through its entry on the fake device adds the vectors"')


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def table_rows(text):
    """Every `| ... |` row that starts with a backticked cell, as its cells."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        out.append((n, cells))
    return out


def ticked(cell):
    return re.findall(r"`([^`]+)`", cell)


# ---- OPERATIONS.md ----

def pub_fns(text):
    return re.findall(r"^pub fn ([a-z][a-z0-9_]*)", text, re.M)


def feature_names(text):
    """The opcode names of features.txt and the ones its rows call implemented
    or structural."""
    names, owed = set(), set()
    for line in text.splitlines():
        if line.startswith("#") or "|" not in line:
            continue
        f = [c.strip() for c in line.split("|")]
        if len(f) < 4:
            continue
        names.add(f[0])
        if f[3] in ("implemented", "structural"):
            owed.add(f[0])
    return names, owed


def check_operations(table_text, dev_text, prog_text, features_text):
    problems = []
    dev, prog = pub_fns(dev_text), pub_fns(prog_text)
    # Operator methods are public through their prelude traits, rather than
    # through top-level function exports. Each still owes one operation row.
    operators = re.findall(
        r"impl[^\n]*\b(?:BitAnd|BitOr|BitXor|BitNot|Shl|Shr|Ushr)\[Tile\[\w+\]\]\s*\{\s*"
        r"(?:type \w+ = Tile\[\w+\]\s*)?effect \w+ = !Dev\s*fn ((?:bit_)?\w+)\(", dev_text)
    surface = set(dev) | set(prog) | set(operators)
    both = sorted(set(dev) & set(prog))
    if both:
        problems.append(f"{', '.join(both)} is public in both dev.dawn and prog.dawn, so a row cannot say which")
    names, owed = feature_names(features_text)
    if not names:
        problems.append("scripts/tileir-features/features.txt has no opcode rows")
    rows = table_rows(table_text)
    if not rows:
        problems.append("OPERATIONS.md has no table rows")
    seen = {}
    named = set()
    for n, cells in rows:
        if len(cells) != 3:
            problems.append(f"OPERATIONS.md:{n}: a row has {len(cells)} cells, expected Function, Operation, Also")
            continue
        fn_cell, op_cell, also_cell = cells
        fns = ticked(fn_cell)
        if len(fns) != 1 or fn_cell != f"`{fns[0]}`":
            problems.append(f"OPERATIONS.md:{n}: the first cell is one backticked function name, got {fn_cell!r}")
            continue
        fn = fns[0]
        if fn in seen:
            problems.append(f"OPERATIONS.md:{n}: `{fn}` already has a row on line {seen[fn]}")
        seen[fn] = n
        if fn not in surface:
            problems.append(f"OPERATIONS.md:{n}: `{fn}` is not a public function of dev.dawn or prog.dawn")
        for label, cell in (("Operation", op_cell), ("Also", also_cell)):
            if cell == "-":
                continue
            if not cell:
                problems.append(f"OPERATIONS.md:{n}: `{fn}` has an empty {label} cell; write `-` for none")
                continue
            ops = ticked(cell)
            rebuilt = ", ".join(f"`{o}`" for o in ops)
            if rebuilt != cell:
                problems.append(f"OPERATIONS.md:{n}: `{fn}`'s {label} cell is not a list of backticked operations or `-`: {cell!r}")
            for o in ops:
                named.add(o)
                if o not in names:
                    problems.append(f"OPERATIONS.md:{n}: `{fn}` names `{o}`, which is not an opcode of features.txt")
    for fn in sorted(surface - set(seen)):
        problems.append(f"`{fn}` is a public function and OPERATIONS.md has no row for it")
    for o in sorted(owed - named):
        problems.append(f"the backend writes `{o}` and no row of OPERATIONS.md names it")
    return problems


# ---- ERRORS.md ----

def production(text):
    """std/gpu.dawn up to its first test block."""
    m = re.search(r"^test ", text, re.M)
    return text[:m.start()] if m else text


def gpu_kinds(text):
    body = production(text)
    kinds = set(re.findall(r'refuse\("(gpu\.[a-z_]+)"', body))
    kinds |= set(re.findall(r'Err\(\("(gpu\.[a-z_]+)"', body))
    return kinds


def check_errors(table_text, gpu_text, src_texts, runtime_texts, checker_text):
    """`src_texts` is the concatenated source of packages/tileir/src,
    `checker_text` the type checker's, and `runtime_texts` maps each runtime
    file to its text."""
    problems = []
    want = gpu_kinds(gpu_text)
    if not want:
        problems.append("std/gpu.dawn builds no gpu.* error kind: the pattern this gate reads is stale")
    for kind, files in RUNTIME_KINDS.items():
        for f in files:
            if kind not in runtime_texts.get(f, ""):
                problems.append(f"{kind} is no longer spelled in {f.relative_to(ROOT)}")
        want.add(kind)
    rows = table_rows(table_text)
    kinds_seen = {}
    layers_seen = set()
    for n, cells in rows:
        first = ticked(cells[0]) if cells else []
        if len(cells) < 2 or len(first) != 1:
            problems.append(f"ERRORS.md:{n}: a row starts with one backticked key")
            continue
        key = first[0]
        layer = cells[1].strip()
        if layer not in LAYERS:
            problems.append(f"ERRORS.md:{n}: `{key}` names the layer {layer!r}, expected one of {', '.join(LAYERS)}")
            continue
        layers_seen.add(layer)
        if re.fullmatch(r"gpu\.[a-z_]+", key) or key.startswith("cuda."):
            if layer != "device":
                problems.append(f"ERRORS.md:{n}: `{key}` is an error kind of the device layer, not {layer!r}")
            if key in kinds_seen:
                problems.append(f"ERRORS.md:{n}: `{key}` already has a row on line {kinds_seen[key]}")
            kinds_seen[key] = n
            continue
        # a message fragment: a literal of packages/tileir/src
        if layer in ("record", "emit"):
            if key not in src_texts:
                problems.append(f"ERRORS.md:{n}: the fragment `{key}` is not in packages/tileir/src, so the message was reworded or removed")
        elif layer == "type check":
            if key not in checker_text:
                problems.append(f"ERRORS.md:{n}: the fragment `{key}` is not in selfhost/src/check/checker.dawn, so the message was reworded or removed")
    for kind in sorted(want - set(kinds_seen)):
        problems.append(f"{kind} is an error kind and ERRORS.md has no row for it")
    for kind in sorted(set(kinds_seen) - want):
        if kind.startswith("cuda."):
            continue
        problems.append(f"ERRORS.md:{kinds_seen[kind]}: `{kind}` is not an error kind std/gpu.dawn or the runtime builds")
    for layer in LAYERS:
        if layer not in layers_seen:
            problems.append(f"ERRORS.md has no row for the {layer!r} layer")
    return problems


def item_text(text, header):
    """The lines of the top-level item whose first line starts with `header`: the
    line itself, then every line that is indented or a closing brace."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(header + "(") or line.startswith(header + " ") or line.startswith(header + "["):
            out = [line]
            for nxt in lines[i + 1:]:
                if nxt.startswith(" ") or nxt == "}":
                    out.append(nxt)
                else:
                    break
            return "\n".join(out)
    return None


def check_readme(readme_text, first_text):
    problems = []
    if "examples/projects/gpu_fake/src/first.dawn" not in readme_text:
        problems.append("README.md does not say the example it shows is examples/projects/gpu_fake/src/first.dawn")
    for header in SHOWN:
        body = item_text(first_text, header)
        if body is None:
            problems.append(f"first.dawn has no `{header}`; this gate expects it, update SHOWN with the README")
        elif body not in readme_text:
            problems.append(f"README.md does not show `{header}` the way first.dawn writes it")
    return problems


def sources():
    src = "\n".join(read(p) for p in sorted(SRC.glob("*.dawn")))
    runtime = {RUNTIME_C: read(RUNTIME_C), RUNTIME_JVM: read(RUNTIME_JVM)}
    return src, runtime


# ---- self-test ----

def self_test():
    ops, errs = read(OPERATIONS), read(ERRORS)
    readme, first = read(README), read(FIRST)
    dev, prog, feats, gpu = read(DEV), read(PROG), read(FEATURES), read(GPU)
    src, runtime = sources()
    checker = read(CHECKER)

    def drop(text, key):
        out = [l for l in text.splitlines() if not l.startswith(f"| `{key}` |")]
        assert len(out) == len(text.splitlines()) - 1, key
        return "\n".join(out) + "\n"

    first_gpu = re.search(r"^\| `(gpu\.[a-z_]+)` \|", errs, re.M).group(1)
    first_frag = next(c[0] for _n, c in table_rows(errs) if c[1] in ("record", "emit"))
    first_frag = ticked(first_frag)[0]
    first_tc = ticked(next(c[0] for _n, c in table_rows(errs) if c[1] == "type check"))[0]
    cases = [
        ("the real tables are clean (the positive control)", "ops", ops, None),
        ("a public function with no row", "ops", drop(ops, "add"), "`add` is a public function and OPERATIONS.md has no row"),
        ("an operator method with no row", "ops", drop(ops, "bit_and"), "`bit_and` is a public function and OPERATIONS.md has no row"),
        ("a shift method with no row", "ops", drop(ops, "shl"), "`shl` is a public function and OPERATIONS.md has no row"),
        ("a row for a function that is not there", "ops", ops + "| `no_such_fn` | `addf` | - |\n",
         "`no_such_fn` is not a public function"),
        ("a misspelled operation", "ops", ops.replace("| `add` | `addf` |", "| `add` | `addff` |", 1),
         "`addff`, which is not an opcode"),
        ("an operation that no row names", "ops", ops.replace("`print_tko`", "`assert`"),
         "no row of OPERATIONS.md names it"),
        ("a duplicated row", "ops", ops + "| `add` | `addf` | - |\n", "`add` already has a row"),
        ("an empty operation cell", "ops", ops.replace("| `add` | `addf` |", "| `add` |  |", 1), "empty Operation cell"),
        ("the real errors table is clean (the positive control)", "err", errs, None),
        ("an error kind with no row", "err", drop(errs, first_gpu), f"{first_gpu} is an error kind and ERRORS.md has no row"),
        ("a row for a kind nothing builds", "err", errs + "| `gpu.no_such_kind` | device | x | y |\n",
         "`gpu.no_such_kind` is not an error kind"),
        ("a kind filed under the wrong layer", "err",
         errs.replace(f"| `{first_gpu}` | device |", f"| `{first_gpu}` | record |", 1), "is an error kind of the device layer"),
        ("a quoted type-check fragment the checker no longer has", "err",
         errs.replace(f"`{first_tc}`", "`this message was reworded`", 1), "selfhost/src/check/checker.dawn"),
        ("a quoted fragment the source no longer has", "err",
         errs.replace(f"`{first_frag}`", "`this message was reworded`", 1), "was reworded or removed"),
        ("the real README example is clean (the positive control)", "readme", readme, None),
        ("a README function that parted from the example", "readme", readme.replace("  sync()?\n", "  sync()?\n  sync()?\n", 1),
         "does not show `fn run`"),
        ("a README with no example", "readme", readme.replace("fn xs() -> List[Float]", "fn ws() -> List[Float]", 1),
         "does not show `fn xs`"),
        ("a layer with no row", "err", "\n".join(l for l in errs.splitlines() if "| emit |" not in l) + "\n",
         "no row for the 'emit' layer"),
    ]
    bad = 0
    for name, which, text, want in cases:
        if which == "ops":
            problems = check_operations(text, dev, prog, feats)
        elif which == "readme":
            problems = check_readme(text, first)
        else:
            problems = check_errors(text, gpu, src, runtime, checker)
        if want is None:
            ok = not problems
        else:
            ok = any(want in p for p in problems)
        print(("PASS  " if ok else "FAIL  ") + name)
        if not ok:
            bad += 1
            for p in problems[:5]:
                print("      " + p)
            if want:
                print(f"      wanted a problem containing: {want}")
    # the pattern of gpu_kinds is itself read: one of the kinds it finds is not
    # a test fixture
    if "gpu.test" in gpu_kinds(gpu):
        print("FAIL  a test fixture kind leaked into the production kinds")
        bad += 1
    return 1 if bad else 0


# The summary line says `tileir-docs` and not `tileir docs` on purpose: site/src/
# gen/gpu.dawn reads scripts/tileir-features/check.py's output for the lines that
# start `PASS  tileir <name>:` and counts each as a coverage ledger.
def main(argv):
    if argv[1:] == ["--self-test"]:
        return self_test()
    if argv[1:]:
        print(__doc__, file=sys.stderr)
        return 2
    src, runtime = sources()
    problems = [f"operations: {p}" for p in check_operations(
        read(OPERATIONS), read(DEV), read(PROG), read(FEATURES))]
    problems += [f"errors: {p}" for p in check_errors(read(ERRORS), read(GPU), src, runtime, read(CHECKER))]
    problems += [f"readme: {p}" for p in check_readme(read(README), read(FIRST))]
    for p in problems:
        print("FAIL: " + p)
    if problems:
        return 1
    n_fn = len(table_rows(read(OPERATIONS)))
    n_err = len(table_rows(read(ERRORS)))
    print(f"PASS  tileir-docs: {n_fn} function row(s) in OPERATIONS.md, {n_err} error row(s) in ERRORS.md, "
          f"{len(SHOWN)} item(s) of the README's example")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
