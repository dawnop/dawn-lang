#!/usr/bin/env python3
"""Every row of the JVM side table points at its call, in the bytecode and in the source.

    python3 scripts/jvm-map/check.py                    # every case below
    python3 scripts/jvm-map/check.py corpus kernels     # some of them
    python3 scripts/jvm-map/check.py --self-test        # the rules on hand-made maps

`dawn __emit --map` writes a `.dawnmap` beside the classes: for each written
call, the method it is in, the pcs its bytecode spans and the pc of the
instruction that makes it (docs/source-span-map-design.md section 13). The
pcs are labels read off a second, labelled emission, kept only where that
emission's class is the plain one byte for byte, so nothing in the tree would
notice a row whose pcs name the wrong instruction, or a class the labels
changed whose rows were kept anyway. This is the reader that notices. Per case
it runs the same compiler three ways -- `__emit -o` alone, `__emit -o --map`,
`__lower --sites` -- reads the classes with JDK `javap -c -p -s` (a different
toolchain from the one that wrote them, and the listing the three-backend page
shows) and with method-size-gate.py's struct reader, and holds them to:

  same       the classes written with `--map` are byte for byte the classes
             written without it (design 13.4: what is written never depends
             on `--map`);
  paired     each row's source site is one row of `__lower --sites` for its
             module, and every site of a function whose declaration has a
             method in the table is a row exactly once; a row with no
             declaration base is red;
  placed     no row is without pcs, except where the labelled emission cannot
             be trusted: `dead`, whose whole class must lose them, and a
             method javap shows a `goto_w` in, which may (a row of it that
             keeps pcs is held to every rule below, so stale pcs are red);
  method     each `fn` row's symbol is one method in the javap listing, and its
             length is the Code attribute's `code_length`;
  bounds     `pclo` and `ipc` start an instruction, `pchi` starts one or ends
             the method, and `pclo <= ipc < pchi`;
  called     the instruction at `ipc` is the call: a direct call's
             `invokestatic` of that owner and name, an impl or default method's
             `invokestatic` of the name the emitter spells for it (spelled here
             independently), a trait method's `invokeinterface` of its name, a
             closure call's `invokeinterface dawn/rt/FnN.apply`, a Java
             member's invoke of that member; an intrinsic has no `ipc` and a
             range that is not empty;
  one-place  no two rows name the same call instruction;
  nested     a call inside another in the source is inside it in the
             bytecode, or wholly before it (an argument with a jump in it is
             evaluated into a local first, `jvm/operand.prepare`).

The cases: the call-shape corpus of scripts/core-sites (it has `use java`,
which the C side table never sees), the tile-golden kernels program compiled
the way scripts/core-sites compiles it, `dead.dawn` beside this file, and the
compiler itself (`selfhost`), the largest program this backend writes.

`dead.dawn` is a measurement, not a fixture: its `f(panic(..), g(x))` puts a
call in unreachable code, where a label splits ASM's basic block and the
labelled class gets one more stack map frame. Its class must come out of the
labelled emission different and every row of it without pcs; if the emitter
one day stops writing unreachable code, this case goes red, and the right
change is to make it assert that the two emissions agree, not to delete it.

`--self-test` runs the bytecode rules on a hand-made listing and map, each
broken one way, and requires each to come out red.

DAWN_BIN overrides the compiler, a launcher or a jar (run.py points it at a
mutant's jar). JAVAP overrides the javap binary.
"""

import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "scripts" / "jvm-map"
sys.path.insert(0, str(ROOT / "scripts" / "c-map"))
from dawnmap import load  # noqa: E402

DAWN_BIN = os.environ.get("DAWN_BIN", str(ROOT / "bin" / "dawn"))
DAWN = (["java", "-Xss512m", "-Xmx6g", "-jar", DAWN_BIN] if DAWN_BIN.endswith(".jar") else [DAWN_BIN])
JAVAP = os.environ.get("JAVAP", "javap")
KERNELS = ROOT / "scripts" / "tile-golden" / "kernels.dawn"
READ_CLASS = runpy.run_path(str(ROOT / "scripts" / "method-size-gate.py"))["read_class"]

CASES = ["corpus", "kernels", "dead", "selfhost"]

INVOKES = {"invokestatic", "invokevirtual", "invokeinterface", "invokespecial"}


def fail(msg):
    print(f"scripts/jvm-map/check.py: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd, cwd=ROOT):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        fail(f"`{' '.join(cmd)}` failed:\n" + (r.stderr + r.stdout)[-3000:])
    return r


def target(name, work):
    if name == "corpus":
        return ROOT / "scripts" / "core-sites" / "corpus.dawn"
    if name == "dead":
        return HERE / "dead.dawn"
    if name == "selfhost":
        return ROOT / "selfhost"
    proj = work / "kernels"
    (proj / "src").mkdir(parents=True)
    shutil.copy(KERNELS, proj / "src" / "main.dawn")
    (proj / "dawn.toml").write_text(
        "schema = 1\nname = \"jvm_map\"\n\n[deps]\n"
        f"tileir = \"{ROOT / 'packages' / 'tileir'}\"\n"
        f"tileref = \"{ROOT / 'packages' / 'tileref'}\"\n", encoding="utf-8")
    return proj


def sites_of(sites_dir):
    """module -> list of {fn, origin, what, lo, hi, nlo}, from `__lower --sites`."""
    out = {}
    # a package module's file sits under its owner's directories
    for p in sorted(Path(sites_dir).rglob("*.sites")):
        for line in p.read_text(encoding="utf-8").splitlines():
            owner, fname, origin, what, at = line.split("\t")
            if "?" in at:
                continue
            lo, hi, nlo = (int(x) for x in at.split(" "))
            out.setdefault(owner, []).append({"fn": fname, "origin": origin, "what": what,
                                              "lo": lo, "hi": hi, "nlo": nlo})
    return out


HEAD = re.compile(r"^(?:[\w.$]+ )*class ([\w.$/]+)")
INSN = re.compile(r"^\s+(\d+): (\w+)\s*(.*)$")
TARGET = re.compile(r"// (?:Method|InterfaceMethod) (.+):\(")


def parse_javap(text):
    """class -> {(name, desc): {pc: (mnemonic, owner, member)}}, from `javap -c -p -s`.

    Owner and member are those of an invoke (javap leaves the owner out when it
    is the class itself), None for any other instruction. Switch tables are
    skipped: their `n: target` lines look like instructions."""
    out = {}
    cls = None
    name = None
    desc = None
    pending = None
    in_table = False
    for line in text.splitlines():
        m = HEAD.match(line)
        if m and not line.startswith(" "):
            cls = m.group(1).replace(".", "/")
            out[cls] = {}
            continue
        s = line.strip()
        if in_table:
            if s == "}":
                in_table = False
            continue
        if line.startswith("  ") and not line.startswith("   ") and s:
            # a member's header: a method (`... name(params);`), a field, or
            # `static {};`. Whatever it is, the instructions before it are over
            name = desc = None
            pending = s[:s.index("(")].split(" ")[-1] if "(" in s else ("<clinit>" if s == "static {};" else None)
            continue
        if s.startswith("descriptor: ") and pending is not None:
            name, desc = pending, s[len("descriptor: "):]
            pending = None
            out[cls][(name, desc)] = {}
            continue
        m = INSN.match(line)
        if m and name is not None and (name, desc) in out[cls]:
            pc, op, rest = int(m.group(1)), m.group(2), m.group(3)
            owner = member = None
            if op in INVOKES:
                t = TARGET.search(rest)
                if t:
                    # an internal class name holds `/` and `$`, never `.`
                    ref = t.group(1)
                    if "." in ref:
                        owner, _, member = ref.rpartition(".")
                    else:
                        owner, member = cls, ref
                    if member.startswith('"') and member.endswith('"'):
                        member = member[1:-1]
            out[cls][(name, desc)][pc] = (op, owner, member)
            if op in ("tableswitch", "lookupswitch"):
                in_table = True
    return out


def split_symbol(symbol):
    """`owner.name:desc` -> (owner, name, desc). Neither an internal class
    name nor a method name holds `.` or `:`, so the first `:` ends the name
    and the last `.` before it ends the owner."""
    head, _, desc = symbol.partition(":")
    owner, _, name = head.rpartition(".")
    return owner, name, desc


def called(c, insn):
    """None when the instruction at `ipc` is the call the row names, else why not."""
    op, owner, member = insn
    kind, _, rest = c["what"].partition(" ")
    if op not in INVOKES:
        return f"is `{op}`, not an invoke"
    if kind == "direct":
        o, _, n = rest.rpartition(".")
        if op != "invokestatic" or owner != o or member != n:
            return f"is `{op} {owner}.{member}`, not `invokestatic {o}.{n}`"
    elif kind == "impl":
        if op != "invokestatic" or not (member.startswith("dawn$impl$") and member.endswith("$" + rest)):
            return f"is `{op} {owner}.{member}`, not an impl method `{rest}`"
    elif kind == "default":
        if op != "invokestatic" or not (member.startswith("dawn$default$") and member.endswith("$" + rest)):
            return f"is `{op} {owner}.{member}`, not a default method `{rest}`"
    elif kind == "method":
        if op != "invokeinterface" or member != rest:
            return f"is `{op} {owner}.{member}`, not `invokeinterface ..{rest}`"
    elif kind == "dynamic":
        if op != "invokeinterface" or member != "apply" or not re.fullmatch(r"dawn/rt/Fn\d+", owner or ""):
            return f"is `{op} {owner}.{member}`, not a function value's `apply`"
    elif kind == "java":
        if member != rest and not (member == "<init>" and rest in ("<init>", "new")):
            return f"is `{op} {owner}.{member}`, not the Java member `{rest}`"
    return None


def check_map(name, m, listing, lengths, sites, lost=frozenset(), may_lose=frozenset()):
    """The rules other than `same`; problems found. Rows of a method in `lost`
    must lack pcs (its class came out of the labelled emission different);
    rows of a method in `may_lose` may (ASM wrote a `goto_w` in it, so a jump
    may have been widened after the labels were read). Every other row must
    have them, and every row that has them is held to every rule."""
    problems = []
    stats = {"rows": 0, "placed": 0, "unplaced": 0, "methods": len(m["fns"])}
    fns = {}
    for f in m["fns"]:
        owner, mname, desc = split_symbol(f["symbol"])
        code = listing.get(owner, {}).get((mname, desc))
        if code is None:
            problems.append(f"{name}: fn {f['symbol']} is no method javap lists")
            continue
        n = lengths.get(owner, {}).get(mname + desc)
        if n != f["len"]:
            problems.append(f"{name}: fn {f['symbol']} says {f['len']} bytes, its Code attribute {n}")
        fns[f["k"]] = (f, code)
    origins = {(f["module"], f["origin"]) for f in m["fns"]}
    by_site = {}
    by_ipc = {}
    placed_by_fn = {}
    for c in m["calls"]:
        stats["rows"] += 1
        where = f"{name}: {c['what']} at {c['module']} {c['lo']}..{c['hi']}"
        if None in (c["lo"], c["hi"], c["nlo"]):
            problems.append(f"{where} has no declaration base")
            continue
        key = (c["module"], c["lo"], c["hi"], c["nlo"])
        if key in by_site:
            problems.append(f"{where} is two rows")
        by_site[key] = c
        if c["k"] not in fns:
            problems.append(f"{where} is in method {c['k']}, which the table does not list")
            continue
        f, code = fns[c["k"]]
        if c["pclo"] is None:
            stats["unplaced"] += 1
            if f["symbol"] not in lost and f["symbol"] not in may_lose:
                problems.append(f"{where} has no place in the bytecode of {f['symbol']}")
            continue
        stats["placed"] += 1
        if f["symbol"] in lost:
            problems.append(f"{where} has pcs in a class the labelled emission changed")
        starts = set(code)
        lo, hi, ipc = c["pclo"], c["pchi"], c["ipc"]
        if lo not in starts or not (hi in starts or hi == f["len"]):
            problems.append(f"{where} spans pcs {lo}..{hi}, which are not instruction boundaries of {f['symbol']}")
            continue
        intrinsic = c["what"].startswith("intrinsic ")
        if intrinsic:
            if ipc is not None:
                problems.append(f"{where} is an intrinsic with a call instruction at {ipc}")
            if not lo < hi:
                problems.append(f"{where} is an intrinsic with no bytecode ({lo}..{hi})")
        else:
            if ipc is None or not (lo <= ipc < hi):
                problems.append(f"{where} has its call instruction at {ipc}, outside {lo}..{hi}")
                continue
            if ipc not in starts:
                problems.append(f"{where} has its call instruction at {ipc}, which starts no instruction")
                continue
            why = called(c, code[ipc])
            if why:
                problems.append(f"{where}: the instruction at {ipc} of {f['symbol']} {why}")
            k = (c["k"], ipc)
            if k in by_ipc:
                problems.append(f"{where} and {by_ipc[k]['what']} at {by_ipc[k]['lo']} name one instruction, "
                                f"{ipc} of {f['symbol']}")
            by_ipc[k] = c
        placed_by_fn.setdefault(c["k"], []).append(c)
    problems += nesting(name, placed_by_fn)
    # paired: every site of a declaration with a method in the table is a row
    for mod, rows in sites.items():
        for s in rows:
            if (mod, s["origin"]) not in origins:
                continue
            if (mod, s["lo"], s["hi"], s["nlo"]) not in by_site:
                problems.append(f"{name}: site {mod} {s['lo']}..{s['hi']} ({s['what']} in {s['fn']}) has no row")
    site_keys = {(mod, s["lo"], s["hi"], s["nlo"]) for mod, rows in sites.items() for s in rows}
    for key, c in by_site.items():
        # `__lower --sites` lists the functions of a module, not its test
        # blocks (a test's declaration path is `Ns..`, check/identity.dawn),
        # nor the lambdas lifted out of them; their rows are held to every
        # rule but this one
        if fns.get(c["k"], ({"origin": ""}, None))[0]["origin"].startswith("Ns"):
            stats["test rows"] = stats.get("test rows", 0) + 1
            continue
        if key not in site_keys:
            problems.append(f"{name}: row {c['what']} at {key} is no site of `__lower --sites`")
    return problems, stats


def nesting(name, placed_by_fn):
    problems = []
    for k, cs in placed_by_fn.items():
        cs = sorted(cs, key=lambda c: (c["lo"], -c["hi"]))
        for i, a in enumerate(cs):
            for b in cs[i + 1:]:
                if b["lo"] >= a["hi"]:
                    break
                if not (a["lo"] <= b["lo"] and b["hi"] <= a["hi"]):
                    continue
                inside = a["pclo"] <= b["pclo"] and b["pchi"] <= a["pchi"]
                before = b["pchi"] <= a["pclo"]
                if not (inside or before):
                    problems.append(f"{name}: {b['what']} at {b['lo']}..{b['hi']} is inside {a['what']} in the "
                                    f"source, but its pcs {b['pclo']}..{b['pchi']} are neither inside "
                                    f"{a['pclo']}..{a['pchi']} nor before them")
    return problems


def class_lengths(out_dir, owners):
    lengths = {}
    for o in owners:
        _, _, methods = READ_CLASS((out_dir / (o + ".class")).read_bytes())
        lengths[o] = {sig.removeprefix("static "): n for sig, n in methods}
    return lengths


def same_tree(a, b):
    fa = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    fb = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    if fa != fb:
        return "the class files written are not the same set"
    for p in fa:
        if (a / p).read_bytes() != (b / p).read_bytes():
            return f"{p} is not the same bytes"
    return None


def check_case(name, work):
    t = target(name, work)
    d = work / ("out-" + name)
    d.mkdir()
    run(DAWN + ["__emit", str(t), "-o", str(d / "plain")])
    run(DAWN + ["__emit", str(t), "-o", str(d / "mapped"), "--map", str(d / "jvm.dawnmap")])
    (d / "sites").mkdir()
    lowered = run(DAWN + ["__lower", "--sites", str(d / "sites"), str(t)])
    if "GAP " in lowered.stdout:
        fail(f"`dawn __lower --sites {t}` has gaps:\n{lowered.stdout[-2000:]}")
    problems = []
    why = same_tree(d / "plain", d / "mapped")
    if why:
        problems.append(f"{name}: the classes written with --map are not those written without it: {why}")
    m = load(d / "jvm.dawnmap")
    if m["backend"] != "jvm":
        fail(f"{name}: the map is for backend {m['backend']!r}")
    owners = sorted({split_symbol(f["symbol"])[0] for f in m["fns"]})
    listing = parse_javap(run([JAVAP, "-c", "-p", "-s"] +
                              [str(d / "mapped" / (o + ".class")) for o in owners]).stdout)
    lengths = class_lengths(d / "mapped", owners)
    # where the labelled emission cannot be trusted: the whole of `dead`, and
    # in every case the methods ASM wrote a `goto_w` in
    lost = {f["symbol"] for f in m["fns"] if name == "dead" and split_symbol(f["symbol"])[0] == "dead"}
    may_lose = set()
    for f in m["fns"]:
        owner, mname, desc = split_symbol(f["symbol"])
        code = listing.get(owner, {}).get((mname, desc), {})
        if any(op == "goto_w" for op, _, _ in code.values()):
            may_lose.add(f["symbol"])
    found, stats = check_map(name, m, listing, lengths, sites_of(d / "sites"), lost, may_lose)
    problems += found
    if name == "dead":
        mine = [c for c in m["calls"] if c["module"] == "dead"]
        placed = sum(1 for c in mine if c["pclo"] is not None)
        if placed or not mine:
            problems.append(f"dead: expected every row of the class `dead` without pcs (the labelled class "
                            f"differs), got {placed} placed of {len(mine)}")
    print(f"{name}: {stats['rows']} row(s), {stats['placed']} placed, {stats['unplaced']} without pcs; "
          f"{stats['methods']} method(s) in {len(owners)} class(es), {len(may_lose)} with a goto_w; "
          f"{stats.get('test rows', 0)} row(s) in test blocks, which `__lower --sites` does not list")
    return problems


def self_test():
    listing_text = """public final class m {
  public static long f(long);
    descriptor: (J)J
    Code:
         0: lload_0
         1: invokestatic  #7                  // Method g:(J)J
         4: invokestatic  #7                  // Method g:(J)J
         7: invokeinterface #9,  2            // InterfaceMethod dawn/rt/Fn1.apply:(Ljava/lang/Object;)Ljava/lang/Object;
        12: tableswitch   { // 0 to 1
                       0: 28
                       1: 30
                 default: 30
            }
        28: lmul
        29: lreturn
        30: lreturn

  static {};
    descriptor: ()V
    Code:
         0: invokestatic  #11                 // Method g:(J)J
         3: return
}
"""
    listing = parse_javap(listing_text)
    # `static {};` ends `f`: its instructions are its own, not more of f's
    assert set(listing["m"][("f", "(J)J")]) == {0, 1, 4, 7, 12, 28, 29, 30}, listing
    assert set(listing["m"][("<clinit>", "()V")]) == {0, 3}, listing
    lengths = {"m": {"f(J)J": 31}}

    def mk(calls, n=31):
        return {"backend": "jvm", "fns": [{"k": 0, "len": n, "module": "m", "origin": "f",
                                           "symbol": "m.f:(J)J"}], "calls": calls}

    def row(what, lo, hi, pclo, pchi, ipc):
        return {"k": 0, "pclo": pclo, "pchi": pchi, "ipc": ipc, "module": "m", "lo": lo, "hi": hi,
                "nlo": lo, "what": what}

    inner = row("direct m.g", 6, 10, 0, 4, 1)
    outer = row("direct m.g", 4, 11, 0, 7, 4)
    sites = {"m": [{"fn": "f", "origin": "f", "what": "direct m.g", "lo": 6, "hi": 10, "nlo": 6},
                   {"fn": "f", "origin": "f", "what": "direct m.g", "lo": 4, "hi": 11, "nlo": 4}]}
    cases = {
        "right": (mk([inner, outer]), None),
        "length": (mk([inner, outer], 30), "its Code attribute"),
        "ipc on another instruction": (mk([dict(inner, ipc=0), outer]), "is `lload_0`"),
        "ipc on the wrong callee": (mk([inner, dict(outer, what="direct m.h")]), "not `invokestatic m.h`"),
        "ipc outside the range": (mk([dict(inner, pchi=1), outer]), "outside"),
        "range off an instruction": (mk([dict(inner, pclo=2), outer]), "not instruction boundaries"),
        "two rows on one instruction": (mk([inner, dict(outer, ipc=1, pclo=0)]), "name one instruction"),
        "nested call after its caller": (mk([dict(inner, pclo=7, pchi=12, ipc=7, what="dynamic"), outer]),
                                         "neither inside"),
        "no pcs": (mk([dict(inner, pclo=None, pchi=None, ipc=None), outer]), "has no place"),
        "a site with no row": (mk([outer]), "has no row"),
        "a closure call": (mk([inner, outer, row("dynamic", 20, 25, 7, 12, 7)]), "is no site"),
        "intrinsic with an instruction": (mk([inner, outer, row("intrinsic x", 30, 31, 28, 29, 28)]),
                                          "an intrinsic with a call instruction"),
    }
    bad = []
    for label, (m, words) in cases.items():
        got, _ = check_map("self-test", m, listing, lengths, sites)
        if words is None and got:
            bad.append(f"{label}: expected no problem, got {got}")
        elif words is not None and not any(words in g for g in got):
            bad.append(f"{label}: expected a problem with `{words}`, got {got}")
        else:
            print(f"OK: self-test {label}")
    # a class the labelled emission changed may lose its pcs, and may not keep them
    lost = mk([dict(inner, pclo=None, pchi=None, ipc=None), dict(outer, pclo=None, pchi=None, ipc=None)])
    got, _ = check_map("self-test", lost, listing, lengths, sites, {"m.f:(J)J"})
    if got:
        bad.append(f"a changed class without pcs: expected no problem, got {got}")
    got, _ = check_map("self-test", lost, listing, lengths, sites, frozenset(), {"m.f:(J)J"})
    if got:
        bad.append(f"a widened method without pcs: expected no problem, got {got}")
    got, _ = check_map("self-test", mk([inner, outer]), listing, lengths, sites, {"m.f:(J)J"})
    if not any("in a class the labelled emission changed" in g for g in got):
        bad.append(f"a changed class keeping its pcs: expected a problem, got {got}")
    assert split_symbol("dawn$pkg$tileir/prog.trace3:(J)J") == ("dawn$pkg$tileir/prog", "trace3", "(J)J")
    assert called({"what": "dynamic"}, ("invokeinterface", "dawn/rt/Fn2", "apply")) is None
    assert called({"what": "impl show"}, ("invokestatic", "m", "dawn$impl$Show$Foo$show")) is None
    assert called({"what": "impl show"}, ("invokestatic", "m", "dawn$impl$Show$Foo$shows")) is not None
    if bad:
        for b_ in bad:
            print("FAIL: " + b_)
        sys.exit(1)
    print(f"OK: {len(cases) + 2} self-test case(s)")


def main():
    args = sys.argv[1:]
    if args == ["--self-test"]:
        return self_test()
    names = args or CASES
    unknown = [n for n in names if n not in CASES]
    if unknown:
        fail(f"no case {unknown}; the cases are {CASES}")
    problems = []
    with tempfile.TemporaryDirectory(prefix="jvm-map.") as work:
        for name in names:
            problems += check_case(name, Path(work))
    if problems:
        for p in problems[:60]:
            print("FAIL: " + p)
        if len(problems) > 60:
            print(f"... and {len(problems) - 60} more")
        sys.exit(1)
    print(f"OK: every row points at its call in the bytecode and in the source ({len(names)} case(s))")


if __name__ == "__main__":
    main()
