#!/usr/bin/env python3
"""Which call of a program wrote which lines of its Tile IR, C and JVM listing.

    python3 site/explorer/record.py              # write site/build/explorer/
    python3 site/explorer/record.py --out DIR    # write DIR (site-dist-diff's snapshot)
    python3 site/explorer/record.py --self-test  # each way of getting it wrong is red

The explorer page (site/src/gen/explorer.dawn, docs/explorer-page-design.md)
puts a program's Dawn source beside the output it compiles to, and a click on
a call lights the lines that call wrote. Three side tables know the answer,
one per backend, and each is its compiler's to say, never guessed here:

  - Tile IR: packages/tileir's recording of the kernel's calls, already
    checked into site/gpu-map/flash_attn.map (site/gpu-map/record.py keeps it
    honest).
  - C: `dawn __emitc --map`, which says for each call of the Dawn source the
    lines of the C text it wrote and the columns on the last of them.
  - JVM: `dawn __emit --map`, which says the pc range of each call's bytecode;
    the listing is `javap -c -p -s` of the class, whose lines carry the pcs.

This script turns the three into one format, `.xmap` (docs/explorer-page-design.md
section 4), restricted to the function the page shows, in the page's own
coordinates (the lines of the text it prints). The generator reads only that.
It writes into site/build/explorer/, which is generated and not tracked: the
C and the bytecode are the compiler's function, so a checked-in copy would go
stale at the next change to the compiler, and a page showing the C of last
week's compiler is worse than a build that fails. site/build.sh runs this on
every build; scripts/site-dist-diff.sh runs it into its snapshot.

Every gap is a failure, not a hole in the page: a call of the table that a
side table has no row for, a row with no place, a range outside the function,
a pc range with no instruction, a method javap does not list, a name that is
not at its span. All of them stop here and say which.
"""

from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "c-map"))
from dawnmap import load  # noqa: E402

DAWN = os.environ.get("DAWN_BIN", str(ROOT / "bin" / "dawn"))
OUT = ROOT / "site" / "build" / "explorer"
KERNELS = ROOT / "scripts" / "tile-golden" / "kernels.dawn"
TILE_MAP = ROOT / "site" / "gpu-map" / "flash_attn.map"
GOLDEN = ROOT / "scripts" / "tile-golden" / "flash_attn.mlir"

# One entry per program on the page, in the order the page shows them.
#   name    the page's section and the files' stem
#   source  the Dawn file shown, relative to the repository root
#   fn      the function the page shows (None: the whole file)
#   kernel  True: kernels.dawn's project (its tileir and tileref deps, module
#           `main`) with a Tile IR recording; False: a single file whose
#           module is its stem
PROGRAMS = [
    {"name": "flash_attn", "source": "scripts/tile-golden/kernels.dawn", "fn": "flash_attn", "kernel": True},
    {"name": "attend", "source": "site/explorer/attend.dawn", "fn": None, "kernel": False},
]


def fail(msg):
    print(f"site/explorer/record.py: {msg}", file=sys.stderr)
    sys.exit(1)


# ---- positions ----

class Source:
    """A source file's text, with code point offsets <-> line:col (from 1)."""

    def __init__(self, text):
        self.text = text
        self.starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def at(self, off):
        lo, hi = 0, len(self.starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.starts[mid] <= off:
                lo = mid
            else:
                hi = mid - 1
        return (lo + 1, off - self.starts[lo] + 1)

    def off(self, line, col):
        return self.starts[line - 1] + col - 1

    def lines(self):
        return self.text.split("\n")


def pos(p):
    return f"{p[0]}:{p[1]}"


def ident_at(src, off):
    m = re.compile(r"[A-Za-z_][A-Za-z0-9_]*").match(src.text, off)
    return m.group(0) if m else None


# ---- running the compilers ----

def run(cmd, cwd=ROOT):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        fail(f"`{' '.join(str(c) for c in cmd)}` failed:\n" + (r.stderr + r.stdout)[-3000:])
    return r


def javap_binary():
    if os.environ.get("JAVAP"):
        return os.environ["JAVAP"]
    # the JDK bin/dawn runs on, found the way it finds it: an unmarked javap on
    # PATH may be another release, and its listing another format
    home = os.environ.get("JAVA_HOME", "")
    if not home:
        for pat in ("graalvm-*/Contents/Home", "graalvm-*"):
            hits = sorted((Path.home() / "tools").glob(pat))
            if hits:
                home = str(hits[0])
                break
    if home and (Path(home) / "bin" / "javap").exists():
        return str(Path(home) / "bin" / "javap")
    return "javap"


def target_of(prog, work):
    """The path `dawn __emitc/__emit` is given, and the module the page's code is in."""
    src = ROOT / prog["source"]
    if prog["kernel"]:
        proj = work / "project"
        (proj / "src").mkdir(parents=True)
        shutil.copy(src, proj / "src" / "main.dawn")
        (proj / "dawn.toml").write_text(
            "schema = 1\nname = \"xp_kernels\"\n\n[deps]\n"
            f"tileir = \"{ROOT / 'packages' / 'tileir'}\"\n"
            f"tileref = \"{ROOT / 'packages' / 'tileref'}\"\n", encoding="utf-8")
        return proj, "main"
    one = work / src.name
    shutil.copy(src, one)
    return one, src.stem


def compile_both(prog, work):
    target, module = target_of(prog, work)
    run([DAWN, "__emitc", str(target), "-o", str(work / "out.c"), "--map", str(work / "c.dawnmap")])
    run([DAWN, "__emit", str(target), "-o", str(work / "classes"), "--map", str(work / "jvm.dawnmap")])
    listing = run([javap_binary(), "-c", "-p", "-s", str(work / "classes" / f"{module}.class")]).stdout
    return {
        "module": module,
        "ctext": (work / "out.c").read_text(encoding="utf-8").split("\n"),
        "cmap": load(str(work / "c.dawnmap")),
        "jmap": load(str(work / "jvm.dawnmap")),
        "javap": listing,
    }


# ---- javap ----

INSN = re.compile(r"^\s+(\d+): (\w+)")


def parse_javap(text):
    """{(name, desc): {"lines": [...], "pcs": {pc: index into lines}}}.

    A block is a member's header, its `descriptor:` line and its `Code:`
    listing, up to the blank line that ends it (the class's closing brace
    is dropped). Overloads are told apart by descriptor, which is also what
    the JVM map's `symbol` carries."""
    keyed = {}
    block = []
    for raw in text.split("\n") + [""]:
        line = raw.rstrip()
        if line == "":
            if block:
                name = header_name(block[0])
                desc = next((l.split("descriptor: ", 1)[1] for l in block if "descriptor: " in l), None)
                if name is not None and desc is not None:
                    keyed[(name, desc)] = block_of(block)
            block = []
        elif line == "}":
            continue
        elif line.startswith("  ") and not line.startswith("   ") and not block:
            block = [line]
        elif block:
            block.append(line)
    return keyed


def header_name(line):
    m = re.match(r"^\s+(?:[\w.$\[\]<>, ]+ )?([\w$<>]+)\(.*\);", line)
    if m:
        return m.group(1)
    return "<clinit>" if line.strip() == "static {};" else None


def block_of(lines):
    pcs, in_table = {}, False
    for i, l in enumerate(lines):
        if in_table:
            if l.strip() == "}":
                in_table = False
            continue
        m = INSN.match(l)
        if m:
            pcs[int(m.group(1))] = i
            if m.group(2) in ("tableswitch", "lookupswitch"):
                in_table = True
    return {"lines": lines, "pcs": pcs}


# ---- the call table ----

def origin_of(name):
    return f"Nf{len(name)}:{name}"


def table_from_tile(src, first, last):
    """The calls of flash_attn.map as the table, in file coordinates."""
    rows = []
    for l in TILE_MAP.read_text(encoding="utf-8").splitlines():
        w = l.split(" ")
        # `carry`, `get` and `set` are what a `var` is to the Tile IR (its loop
        # arguments, its reads, its assignments). A host map has no call for any
        # of them, they wrote no Tile IR line of their own, and a click on one
        # would light nothing, so the page does not list them.
        if w[0] == "call" and w[3] not in ("carry", "get", "set"):
            a, b = w[4].split("-")
            na, nb = w[5].split("-")
            p = lambda s: tuple(int(x) for x in s.split(":"))
            rows.append({"id": int(w[1]), "parent": int(w[2]), "name": w[3],
                         "lo": src.off(*p(a)), "hi": src.off(*p(b)),
                         "nlo": src.off(*p(na)), "nhi": src.off(*p(nb)), "lines": w[6:]})
    return tree(sorted(rows, key=lambda r: (r["lo"], -r["hi"])))


def tree(rows):
    """Rows in source order, numbered from 0, each with its innermost
    enclosing call by span as its parent. The page nests by span: the Tile IR
    recording's own parent is the region a call ran in, which is not what a
    reader means by a call inside a call (`mul(mma(..), ..)`), and in C and
    bytecode it is the span that says whose code sits inside whose."""
    for i, r in enumerate(rows):
        r["id"] = i
    for r in rows:
        holders = [p for p in rows if p is not r and p["lo"] <= r["lo"] and r["hi"] <= p["hi"]
                   and (p["lo"], p["hi"]) != (r["lo"], r["hi"])]
        r["parent"] = min(holders, key=lambda p: p["hi"] - p["lo"])["id"] if holders else -1
    return rows


def table_from_maps(src, module, first, last, c, j):
    """The calls of the function in both host maps, in source order, with the
    tree read off their spans (the innermost other call that holds one)."""
    seen = {}
    for m in (c, j):
        keys = set()
        for r in m["calls"]:
            if r["module"] != module or r["lo"] is None:
                continue
            line = src.at(r["lo"])[0]
            if not (first <= line <= last):
                continue
            keys.add((r["lo"], r["hi"], r["nlo"]))
        seen[m["backend"]] = keys
    both = seen["c"] & seen["jvm"]
    for backend, keys in seen.items():
        for k in sorted(keys - both):
            fail(f"the call at {pos(src.at(k[0]))} has a row in the {backend} map and not in the other")
    ks = sorted(both, key=lambda k: (k[0], -k[1]))
    rows = []
    for lo, hi, nlo in ks:
        name = ident_at(src, nlo)
        if name is None:
            fail(f"the call at {pos(src.at(lo))} has its name at {pos(src.at(nlo))}, which is no identifier")
        rows.append({"id": 0, "parent": -1, "name": name, "lo": lo, "hi": hi, "nlo": nlo,
                     "nhi": nlo + len(name), "lines": []})
    return tree(rows)


def spelled(name, text):
    """Whether the source text at a call's name span is how that call is spelled:
    the callee's own name, an operator for the arithmetic calls (`a + b` is
    `add`, `addi`, `idx_add`...), or, for the three calls a `var` makes (`carry`
    where a loop opens it, `get` where it is read, `set` where it is assigned),
    the variable's name or the loop's `for`. The same rule as gen/gpumap.dawn."""
    if text == name:
        return True
    if name in ("carry", "get", "set"):
        return text != ""
    for stem, op in (("add", "+"), ("idx_add", "+"), ("sub", "-"), ("idx_sub", "-"), ("mul", "*"),
                     ("idx_mul", "*"), ("div", "/"), ("idx_div", "/"), ("idx_rem", "%"), ("neg", "-")):
        if name.startswith(stem):
            return text == op
    return False


def check_table(src, table, first, last):
    by_id = {c["id"]: c for c in table}
    for c in table:
        l0, _ = src.at(c["lo"])
        l1, _ = src.at(c["hi"])
        if not (first <= l0 and l1 <= last):
            fail(f"call {c['id']} (`{c['name']}`) is outside the function")
        if not spelled(c["name"], src.text[c["nlo"]:c["nhi"]]):
            fail(f"call {c['id']} (`{c['name']}`): the text at {pos(src.at(c['nlo']))} is "
                 f"{src.text[c['nlo']:c['nhi']]!r}")
        if not (c["lo"] <= c["nlo"] and c["nhi"] <= c["hi"]):
            fail(f"call {c['id']} (`{c['name']}`): its name is outside its span")
        if c["parent"] >= 0:
            p = by_id.get(c["parent"])
            if p is None or not (p["lo"] <= c["lo"] and c["hi"] <= p["hi"]):
                fail(f"call {c['id']} (`{c['name']}`) is not inside its parent's span")


def children_of(table):
    kids = {c["id"]: [] for c in table}
    for c in table:
        if c["parent"] >= 0:
            kids[c["parent"]].append(c["id"])
    return kids


# ---- the C pane ----

def ranges(lines):
    """Sorted line numbers as half-open runs."""
    out = []
    for n in sorted(set(lines)):
        if out and out[-1][1] == n:
            out[-1][1] = n + 1
        else:
            out.append([n, n + 1])
    return [tuple(r) for r in out]


def c_pane(prog, ctext, cmap, module, table, src):
    fn = prog["fn"]
    want = [f for f in cmap["fns"] if f["module"] == module and (fn is None or f["origin"] == origin_of(fn))]
    if not want:
        fail(f"{prog['name']}: the C map has no function of `{fn}`")
    want.sort(key=lambda f: f["first"])
    text, base = [], {}
    for f in want:
        if text:
            text.append("")
        base[(f["first"], f["last"])] = len(text) + 1
        text += [l.rstrip() for l in ctext[f["first"] - 1:f["last"]]]

    def place(line):
        for (a, b), s in base.items():
            if a <= line <= b:
                return s + line - a
        return None

    rows = {}
    for r in cmap["calls"]:
        if r["module"] == module and r["lo"] is not None:
            rows.setdefault((r["lo"], r["hi"]), []).append(r)
    full, marks, lastline = {}, {}, {}
    for c in table:
        rs = rows.get((c["lo"], c["hi"]), [])
        if not rs:
            fail(f"{prog['name']}: call {c['id']} (`{c['name']}`) at {pos(src.at(c['lo']))} has no row in the C map")
        full[c["id"]], marks[c["id"]], lastline[c["id"]] = set(), [], set()
        for r in rs:
            if r["first"] is None or r["line"] is None:
                fail(f"{prog['name']}: call {c['id']} (`{c['name']}`) did not land in the C text")
            a, b = place(r["first"]), place(r["line"])
            if a is None or b is None or b < a:
                fail(f"{prog['name']}: call {c['id']} (`{c['name']}`): C lines {r['first']}-{r['line']} are "
                     f"outside the function's")
            full[c["id"]] |= set(range(a, b + 1))
            lastline[c["id"]].add(b)
            if r["clo"] is not None:
                if not (0 <= r["clo"] < r["chi"] <= len(text[b - 1])):
                    fail(f"{prog['name']}: call {c['id']} (`{c['name']}`): columns {r['clo']}-{r['chi']} "
                         f"are outside C line {b}")
                marks[c["id"]].append((b, r["clo"], r["chi"]))
    kids = children_of(table)
    outs = {}
    for c in table:
        under = set()
        for k in kids[c["id"]]:
            under |= full[k]
        outs[c["id"]] = {"lines": ranges((full[c["id"]] - under) | lastline[c["id"]]), "marks": marks[c["id"]],
                         "key": None}
    return text, outs


# ---- the JVM pane ----

def jvm_pane(prog, listing, jmap, module, table, src):
    fn = prog["fn"]
    want = [f for f in jmap["fns"] if f["module"] == module and (fn is None or f["origin"] == origin_of(fn))]
    if not want:
        fail(f"{prog['name']}: the JVM map has no method of `{fn}`")
    # the page reads a listing in source order: a function, then what was
    # lifted out of it
    want.sort(key=lambda f: (f["symbol"].split(":")[0].rsplit(".", 1)[1].startswith("lambda$"), f["k"]))
    methods = parse_javap(listing)
    text, where = [], {}
    for f in want:
        head, _, desc = f["symbol"].partition(":")
        name = head.rsplit(".", 1)[1]
        m = methods.get((name, desc))
        if m is None:
            fail(f"{prog['name']}: javap lists no method {name}{desc} (the JVM map's {f['symbol']})")
        if text:
            text.append("")
        for pc, i in m["pcs"].items():
            where[(f["k"], pc)] = len(text) + i + 1
        f["_len"] = f["len"]
        f["_pcs"] = sorted(m["pcs"])
        text += m["lines"]
    rows = {}
    for r in jmap["calls"]:
        if r["module"] == module and r["lo"] is not None:
            rows.setdefault((r["lo"], r["hi"]), []).append(r)
    by_k = {f["k"]: f for f in want}
    taken, ipcs = {}, {}
    for c in table:
        rs = rows.get((c["lo"], c["hi"]), [])
        if not rs:
            fail(f"{prog['name']}: call {c['id']} (`{c['name']}`) at {pos(src.at(c['lo']))} has no row in the JVM map")
        taken[c["id"]], ipcs[c["id"]] = {}, []
        for r in rs:
            if r["k"] not in by_k:
                fail(f"{prog['name']}: call {c['id']} (`{c['name']}`) is in method {r['k']}, which is not one of the page's")
            if r["pclo"] is None or r["pchi"] is None:
                fail(f"{prog['name']}: call {c['id']} (`{c['name']}`) did not land in the bytecode")
            f = by_k[r["k"]]
            if not (0 <= r["pclo"] < r["pchi"] <= f["_len"]):
                fail(f"{prog['name']}: call {c['id']} (`{c['name']}`): pcs {r['pclo']}-{r['pchi']} are outside "
                     f"its method's code ({f['_len']} bytes)")
            pcs = [p for p in f["_pcs"] if r["pclo"] <= p < r["pchi"]]
            if not pcs:
                fail(f"{prog['name']}: call {c['id']} (`{c['name']}`): no instruction in pcs {r['pclo']}-{r['pchi']}")
            taken[c["id"]].setdefault(r["k"], set()).update(pcs)
            if r["ipc"] is not None:
                if r["ipc"] not in f["_pcs"]:
                    fail(f"{prog['name']}: call {c['id']} (`{c['name']}`): ipc {r['ipc']} is no instruction")
                ipcs[c["id"]].append(where[(r["k"], r["ipc"])])
    kids = children_of(table)
    outs = {}
    for c in table:
        mine = set()
        for k, pcs in taken[c["id"]].items():
            under = set()
            for kid in kids[c["id"]]:
                under |= taken[kid].get(k, set())
            mine |= {where[(k, p)] for p in pcs - under}
        mine |= set(ipcs[c["id"]])
        outs[c["id"]] = {"lines": ranges(mine), "marks": [], "key": sorted(set(ipcs[c["id"]]))}
    return text, outs


# ---- the Tile IR pane ----

def tile_pane(table):
    text = GOLDEN.read_text(encoding="utf-8").rstrip("\n").split("\n")
    outs = {}
    for c in table:
        rs = []
        for w in c["lines"]:
            a, b = (int(x) for x in w.split("-"))
            if not (1 <= a < b <= len(text) + 1):
                fail(f"flash_attn: call {c['id']} (`{c['name']}`): Tile IR lines {a}-{b} are outside the golden")
            rs.append((a, b))
        outs[c["id"]] = {"lines": rs, "marks": [], "key": []}
    return text, outs


# ---- writing ----

def span_text(src, lo, hi):
    return f"{pos(src.at(lo))}-{pos(src.at(hi))}"


def out_row(kind, cid, o):
    rs = " ".join(f"{a}-{b}" for a, b in o["lines"]) or "-"
    extra = "".join(f" @{l}:{a}-{b}" for l, a, b in o["marks"]) + "".join(f" !{l}" for l in (o["key"] or []))
    return f"out {kind} {cid} {rs}{extra}"


def write(prog, built, outdir):
    src = built["src"]
    table, first, last = built["table"], built["first"], built["last"]
    rows = ["xmap 1", f"program {prog['name']}", f"source {prog['source']} {first} {last}"]
    for c in table:
        rows.append(f"call {c['id']} {c['parent']} {c['name']} {span_text(src, c['lo'], c['hi'])} "
                    f"{span_text(src, c['nlo'], c['nhi'])}")
    for kind, (text, outs), total in built["panes"]:
        fname = f"{prog['name']}.{kind}.txt"
        (outdir / fname).write_text("\n".join(text) + "\n", encoding="utf-8")
        rows.append(f"pane {kind} {fname} {total}")
        for c in table:
            rows.append(out_row(kind, c["id"], outs[c["id"]]))
    (outdir / f"{prog['name']}.xmap").write_text("\n".join(rows) + "\n", encoding="utf-8")


def build(prog, compiled=None):
    """The page's data for one program, or a failure."""
    src = Source((ROOT / prog["source"]).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="explorer.") as w:
        c = compiled or compile_both(prog, Path(w))
    module = c["module"]
    panes = []
    if prog["kernel"]:
        rec = TILE_MAP.read_text(encoding="utf-8").splitlines()
        fnrow = next(l for l in rec if l.startswith("fn "))
        first, last = (int(x) for x in fnrow.split(" ")[1].split("-"))
        table = table_from_tile(src, first, last)
    else:
        first, last = 1, len(src.lines()) - (1 if src.text.endswith("\n") else 0)
        table = table_from_maps(src, module, first, last, c["cmap"], c["jmap"])
    if not table:
        fail(f"{prog['name']}: no calls to show")
    check_table(src, table, first, last)
    if prog["kernel"]:
        tile = tile_pane(table)
        panes.append(("tile", tile, len(tile[0])))
    lines_of = lambda t: len(t.rstrip("\n").split("\n"))
    panes.append(("c", c_pane(prog, c["ctext"], c["cmap"], module, table, src), len("\n".join(c["ctext"]).rstrip("\n").split("\n"))))
    panes.append(("jvm", jvm_pane(prog, c["javap"], c["jmap"], module, table, src), lines_of(c["javap"])))
    skipped = host_only_calls(src, module, first, last, c, table)
    return {"src": src, "table": table, "first": first, "last": last, "panes": panes, "skipped": skipped}


def host_only_calls(src, module, first, last, c, table):
    """How many calls of the function the host maps have that the table does not."""
    keys = {(t["lo"], t["hi"]) for t in table}
    seen = set()
    for r in c["cmap"]["calls"]:
        if r["module"] == module and r["lo"] is not None and first <= src.at(r["lo"])[0] <= last \
                and (r["lo"], r["hi"]) not in keys:
            seen.add((r["lo"], r["hi"]))
    return len(seen)


def main_write(out):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    names = []
    for prog in PROGRAMS:
        b = build(prog)
        write(prog, b, out)
        names.append(prog["name"])
        print(f"explorer: {prog['name']}: {len(b['table'])} calls, "
              + ", ".join(f"{k} {len(t)} lines" for k, (t, _), _n in b["panes"])
              + (f"; {b['skipped']} host-only call(s) not shown" if b["skipped"] else ""))
    (out / "programs.txt").write_text("\n".join(names) + "\n", encoding="utf-8")


# ---- the negative controls ----

def self_test():
    prog = next(p for p in PROGRAMS if not p["kernel"])
    with tempfile.TemporaryDirectory(prefix="explorer-self.") as w:
        good = compile_both(prog, Path(w))
    build(prog, good)  # the positive control: unmutated, it passes

    def clone():
        import copy
        return copy.deepcopy(good)

    def first_call(m, mod):
        return next(r for r in m["calls"] if r["module"] == mod and r["lo"] is not None)

    def both_rows(c, mod, **fields):
        key = first_call(c["cmap"], mod)
        k = (key["lo"], key["hi"])
        for m in (c["cmap"], c["jmap"]):
            for r in m["calls"]:
                if r["module"] == mod and (r["lo"], r["hi"]) == k:
                    r.update(fields)

    cases = []

    def case(label, words, mutate):
        c = clone()
        mutate(c)
        cases.append((label, words, c))

    mod = good["module"]
    case("a call the C map has no row for", "and not in the other",
         lambda c: first_call(c["cmap"], mod).update(lo=-5, hi=-4))
    case("a call the JVM map has no row for", "and not in the other",
         lambda c: first_call(c["jmap"], mod).update(lo=-5, hi=-4))
    case("a pc range past its method", "are outside its method's code",
         lambda c: first_call(c["jmap"], mod).update(pchi=100000))
    case("a pc range between two instructions", "no instruction in pcs",
         lambda c: first_call(c["jmap"], mod).update(pclo=99999, pchi=100000) or c["jmap"]["fns"][0].update(len=100001))
    case("a call that did not land in the C text", "did not land in the C text",
         lambda c: first_call(c["cmap"], mod).update(first=None))
    case("C lines outside the function", "outside the function's",
         lambda c: first_call(c["cmap"], mod).update(first=1, line=1))
    case("a column past the end of its line", "are outside C line",
         lambda c: first_call(c["cmap"], mod).update(clo=0, chi=100000))
    case("a method javap does not list", "javap lists no method",
         lambda c: c.update(javap=c["javap"].replace(" dot(", " dotx(")))
    case("a name that is not at its span", "which is no identifier",
         lambda c: both_rows(c, mod, nlo=0))
    red = []
    for label, words, c in cases:
        err = capture_failure(prog, c)
        if err is None:
            red.append(f"{label}: the build did not fail")
        elif words not in err:
            red.append(f"{label}: failed with {err.strip()!r}, wanted {words!r}")
    if red:
        fail("self-test:\n  " + "\n  ".join(red))
    print(f"OK: {len(cases)} defects, each red in its own words, and the unmutated build is green")


def capture_failure(prog, compiled):
    import io
    import contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            build(prog, compiled)
    except SystemExit:
        return buf.getvalue()
    return None


def main():
    args = sys.argv[1:]
    if args == ["--self-test"]:
        self_test()
    elif args == []:
        main_write(OUT)
    elif len(args) == 2 and args[0] == "--out":
        main_write(Path(args[1]))
    else:
        fail("usage: record.py [--out DIR | --self-test]")


if __name__ == "__main__":
    main()
