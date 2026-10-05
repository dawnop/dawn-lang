#!/usr/bin/env python3
"""Every row of the C side table points at its call, in the C and in the source.

    python3 scripts/c-map/check.py                  # every case below
    python3 scripts/c-map/check.py corpus kernels   # some of them
    python3 scripts/c-map/check.py --self-test      # the rules on hand-made maps

`dawn __emitc --map` writes a `.dawnmap` beside the C: for each written call,
the lines its C occupies and the columns of the call expression
(docs/source-span-map-design.md section 12). The emitter finds those columns
by looking for the call's C text in the line that writes it down, so nothing
in the tree would notice a row that names the wrong line, the wrong
occurrence, or the wrong call. This is the reader that notices. Per case it
runs the same compiler four ways -- `__emitc -o` alone, `__emitc -o --map
--split`, `__lower --sites` -- and holds the results to these rules:

  same       the C written with `--map` is byte for byte the C written
             without it (design 12.4: the map never touches the text);
  paired     each row's source site is one row of `__lower --sites` for its
             module (M2's oracle already ties those to the parser's call
             nodes), and every site of a function the C kept is a row exactly
             once; a row with no place, or with no declaration base, is red;
  named      the C a row points at is that call: a direct call's range holds
             its mangled symbol (spelled here independently of the compiler),
             an impl or default method's holds its escaped name, a trait
             method's a dictionary slot, a closure call's `->fn)`, and an
             intrinsic's is not empty; a call written as statements holds the
             symbol on one of its lines;
  one-place  no two rows claim the same range of the same line;
  ordered    two rows of one function on one line that are disjoint in the
             source are in the same order in the C, so a claim that took the
             wrong one of two identical texts cannot pass;
  nested     a call inside another in the source is inside it in the C, when
             both are in one C function;
  units      each row's line, moved into the `--split` file the unit table
             names, is the same text there.

The cases: the call-shape corpus beside this file (all of it), the
tile-golden kernels program compiled the way scripts/core-sites compiles it
(all of it, flash_attn, softmax and vadd included), and the native compiler's
own driver, nmain.dawn, the largest C this backend writes.

`--self-test` runs the rules that are about occurrences on hand-made maps of
one line: two identical calls on one line claimed in the wrong order, both
rows on one occurrence, and an inner call whose text starts its enclosing
call's text placed after it. Each has to come out red. The emitter never
writes two identical call texts on one line today (a row with two running
operands names every one of them), so a real compile cannot show these
rules have teeth; the emitter's own half is its `claim` test block, which
run.py's mutants turn red.

DAWN_BIN overrides the compiler, a launcher or a jar (run.py points it at a
mutant's jar).
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "scripts" / "c-map"
sys.path.insert(0, str(HERE))
from dawnmap import load, unit_line  # noqa: E402

DAWN_BIN = os.environ.get("DAWN_BIN", str(ROOT / "bin" / "dawn"))
DAWN = (["java", "-Xss512m", "-Xmx4g", "-jar", DAWN_BIN] if DAWN_BIN.endswith(".jar") else [DAWN_BIN])
KERNELS = ROOT / "scripts" / "tile-golden" / "kernels.dawn"

CASES = ["corpus", "kernels", "nmain"]

# what the rules looked at, printed per case so that a rule that saw nothing shows
STATS = {"kept sites": 0, "same-line pairs": 0, "identical texts on one line": 0}


def fail(msg):
    print(f"scripts/c-map/check.py: {msg}", file=sys.stderr)
    sys.exit(1)


def esc(part):
    """`emitc.escape_part`, from its table: injective, never ends an escape in `_`."""
    out = []
    for ch in part:
        if ch.isascii() and ch.isalnum():
            out.append(ch)
        elif ch == "_":
            out.append("_1")
        elif ch == "/":
            out.append("_2")
        elif ch == "$":
            out.append("_3")
        else:
            out.append("_0" + format(ord(ch), "06X"))
    return "".join(out)


def mangle(owner, name):
    return "dawn_" + esc(owner) + "__" + esc(name)


def run(cmd):
    r = subprocess.run(DAWN + cmd, capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        fail(f"`dawn {' '.join(cmd)}` failed:\n" + (r.stderr + r.stdout)[-3000:])
    return r


def target(name, work):
    if name == "corpus":
        return HERE / "corpus.dawn"
    if name == "nmain":
        return ROOT / "selfhost" / "src" / "nmain.dawn"
    proj = work / "kernels"
    (proj / "src").mkdir(parents=True)
    shutil.copy(KERNELS, proj / "src" / "main.dawn")
    (proj / "dawn.toml").write_text(
        "schema = 1\nname = \"c_map\"\n\n[deps]\n"
        f"tileir = \"{ROOT / 'packages' / 'tileir'}\"\n"
        f"tileref = \"{ROOT / 'packages' / 'tileref'}\"\n", encoding="utf-8")
    return proj


def sites_of(sites_dir):
    """module -> list of {fn, origin, what, lo, hi, nlo}, from `__lower --sites`."""
    out = {}
    for p in sorted(Path(sites_dir).glob("*.sites")):
        for line in p.read_text(encoding="utf-8").splitlines():
            owner, fname, origin, what, at = line.split("\t")
            if "?" in at:
                continue
            lo, hi, nlo = (int(x) for x in at.split(" "))
            out.setdefault(owner, []).append({"fn": fname, "origin": origin, "what": what,
                                              "lo": lo, "hi": hi, "nlo": nlo})
    return out


def fn_at(fns, line):
    # fns sorted by first line; bodies do not overlap
    lo, hi = 0, len(fns)
    while lo < hi:
        mid = (lo + hi) // 2
        if fns[mid]["first"] <= line:
            lo = mid + 1
        else:
            hi = mid
    if lo and fns[lo - 1]["first"] <= line <= fns[lo - 1]["last"]:
        return lo - 1
    return None


def named(c, text, lines):
    """None when the C a row points at is its call, else why not."""
    what = c["what"]
    kind, _, rest = what.partition(" ")
    if kind == "direct":
        owner, _, name = rest.rpartition(".")
        want = mangle(owner, name) + "("
    elif kind in ("impl", "default"):
        want = "_3" + esc(rest) + "("
    elif kind == "method":
        want = "->slots["
    elif kind == "dynamic":
        want = "->fn)"
    else:
        want = ""
    if c["clo"] is None:
        body = "".join(lines[c["first"] - 1:c["line"]])
    else:
        body = text
    if want and want not in body:
        return f"holds no `{want}`"
    if not want and not body.strip():
        return "is empty"
    return None


def check_map(name, m, lines, sites, split_dir):
    """The rules other than `same`, on one map and the C it describes; problems found."""
    problems = []
    fns = sorted(m["fns"], key=lambda f: f["first"])
    kept = {(f["module"], f["symbol"]) for f in fns}
    by_site = {}
    for c in m["calls"]:
        where = f"{name}: {c['what']} at {c['module']} {c['lo']}..{c['hi']}"
        if None in (c["lo"], c["hi"], c["nlo"]):
            problems.append(f"{where} has no declaration base")
            continue
        if c["line"] is None:
            problems.append(f"{where} has no place in the C")
            continue
        key = (c["module"], c["lo"], c["hi"], c["nlo"])
        if key in by_site:
            problems.append(f"{where} is two rows")
        by_site[key] = c
        if not (c["first"] <= c["line"] <= m["lines"]):
            problems.append(f"{where} has lines {c['first']}..{c['line']} outside the text")
            continue
        text = ""
        if c["clo"] is not None:
            ln = lines[c["line"] - 1]
            if not (0 <= c["clo"] < c["chi"] <= len(ln)):
                problems.append(f"{where} has columns {c['clo']}..{c['chi']} outside its line")
                continue
            text = ln[c["clo"]:c["chi"]]
        why = named(c, text, lines)
        if why:
            problems.append(f"{where}: its C {text[:80]!r} {why}")
        fi = fn_at(fns, c["line"])
        if fi is None or not (fns[fi]["first"] <= c["first"]):
            problems.append(f"{where} is in no one C function")
        c["_fn"] = fi
        c["_text"] = text
        if split_dir is not None:
            u = unit_line(m, c["line"])
            if u is None:
                problems.append(f"{where} is on line {c['line']}, in no unit")
            else:
                f, l = u
                ul = (split_dir / f).read_text(encoding="utf-8").split("\n")
                if l - 1 >= len(ul) or ul[l - 1] != lines[c["line"] - 1]:
                    problems.append(f"{where} is line {l} of {f} by the unit table, and that is another line")
    # paired: every site of a kept function is a row
    for mod, rows in sites.items():
        for s in rows:
            if (mod, mangle(mod, s["fn"])) not in kept:
                continue
            STATS["kept sites"] += 1
            if (mod, s["lo"], s["hi"], s["nlo"]) not in by_site:
                problems.append(f"{name}: site {mod} {s['lo']}..{s['hi']} ({s['what']} in {s['fn']}) has no row")
    site_keys = {(mod, s["lo"], s["hi"], s["nlo"]) for mod, rows in sites.items() for s in rows}
    for key, c in by_site.items():
        if key not in site_keys:
            problems.append(f"{name}: row {c['what']} at {key} is no site of `__lower --sites`")
    problems += occurrence_rules(name, [c for c in by_site.values() if c["clo"] is not None])
    return problems


def occurrence_rules(name, calls):
    """one-place, ordered and nested, over expression rows (each with `_fn`, `_text`)."""
    problems = []
    seen = {}
    by_line = {}
    for c in calls:
        k = (c["line"], c["clo"], c["chi"])
        if k in seen:
            problems.append(f"{name}: {c['what']} at {c['lo']}..{c['hi']} and {seen[k]['what']} at "
                            f"{seen[k]['lo']}..{seen[k]['hi']} claim one occurrence, line {k[0]} {k[1]}..{k[2]}")
        seen[k] = c
        by_line.setdefault(c["line"], []).append(c)
    for line, cs in by_line.items():
        for i, a in enumerate(cs):
            for b in cs[i + 1:]:
                if a["module"] != b["module"] or a.get("_fn") != b.get("_fn"):
                    continue
                STATS["same-line pairs"] += 1
                if a.get("_text") and a.get("_text") == b.get("_text"):
                    STATS["identical texts on one line"] += 1
                src_in = (a["lo"] <= b["lo"] and b["hi"] <= a["hi"]) or (b["lo"] <= a["lo"] and a["hi"] <= b["hi"])
                c_in = (a["clo"] <= b["clo"] and b["chi"] <= a["chi"]) or (b["clo"] <= a["clo"] and a["chi"] <= b["chi"])
                if src_in:
                    outer, inner = (a, b) if a["hi"] - a["lo"] >= b["hi"] - b["lo"] else (b, a)
                    if not (outer["clo"] <= inner["clo"] and inner["chi"] <= outer["chi"]):
                        problems.append(f"{name}: {inner['what']} at {inner['lo']}..{inner['hi']} is inside "
                                        f"{outer['what']} in the source but not in the C (line {line})")
                elif not c_in and (a["lo"] < b["lo"]) != (a["clo"] < b["clo"]):
                    problems.append(f"{name}: {a['what']} at {a['lo']} and {b['what']} at {b['lo']} are in one "
                                    f"order in the source and the other in the C (line {line})")
    return problems


def check_case(name, work):
    t = target(name, work)
    d = work / ("out-" + name)
    d.mkdir()
    run(["__emitc", str(t), "-o", str(d / "plain.c")])
    run(["__emitc", str(t), "-o", str(d / "mapped.c"), "--map", str(d / "c.dawnmap"), "--split", str(d / "units")])
    (d / "sites").mkdir()
    lowered = run(["__lower", "--sites", str(d / "sites"), str(t)])
    if "GAP " in lowered.stdout:
        fail(f"`dawn __lower --sites {t}` has gaps:\n{lowered.stdout[-2000:]}")
    plain = (d / "plain.c").read_bytes()
    mapped = (d / "mapped.c").read_bytes()
    STATS.update({"kept sites": 0, "same-line pairs": 0, "identical texts on one line": 0})
    problems = []
    if plain != mapped:
        problems.append(f"{name}: the C written with --map is not the C written without it")
    m = load(d / "c.dawnmap")
    text = mapped.decode("utf-8")
    lines = text.split("\n")
    if m["lines"] != text.count("\n"):
        problems.append(f"{name}: the map says {m['lines']} lines, the C has {text.count(chr(10))}")
    problems += check_map(name, m, lines, sites_of(d / "sites"), d / "units")
    exprs = sum(1 for c in m["calls"] if c["clo"] is not None)
    stmts = sum(1 for c in m["calls"] if c["clo"] is None and c["line"] is not None)
    print(f"{name}: {len(m['calls'])} row(s), {exprs} expression, {stmts} statement form; "
          f"{len(m['fns'])} function(s), {len(m['units'])} unit(s); "
          + ", ".join(f"{k} {v}" for k, v in STATS.items()))
    return problems


# One line, `  return pair(h(v), h(v));`, and what each claim should be. The
# rows are as check_map leaves them (with `_fn` and `_text`).
SELF_LINE = "  return pair(dawn_m__h(v), dawn_m__h(v));"


def self_row(what, lo, hi, clo, chi):
    return {"what": what, "module": "m", "lo": lo, "hi": hi, "nlo": lo, "first": 1, "line": 1,
            "clo": clo, "chi": chi, "_fn": 0, "_text": SELF_LINE[clo:chi]}


def self_test():
    a, b = SELF_LINE.index("dawn_m__h"), SELF_LINE.rindex("dawn_m__h")
    n = len("dawn_m__h(v)")
    outer = self_row("direct m.pair", 0, 16, 9, len(SELF_LINE) - 1)
    good = [outer, self_row("direct m.h", 5, 9, a, a + n), self_row("direct m.h", 11, 15, b, b + n)]
    cases = {
        "right": (good, None),
        "two identical calls swapped": (
            [outer, self_row("direct m.h", 5, 9, b, b + n), self_row("direct m.h", 11, 15, a, a + n)],
            "the other in the C"),
        "two identical calls on one occurrence": (
            [outer, self_row("direct m.h", 5, 9, a, a + n), self_row("direct m.h", 11, 15, a, a + n)],
            "claim one occurrence"),
    }
    # `f(x)(y)`: the inner call's text starts the enclosing one's; placed after it, it is outside
    line2 = "  return dawn_m__f(v)(w);"
    s = line2.index("dawn_m__f")
    enclosing = {"what": "dynamic", "module": "m", "lo": 0, "hi": 7, "nlo": 0, "first": 2, "line": 2,
                 "clo": s, "chi": len(line2) - 1, "_fn": 0}
    inner_ok = dict(enclosing, what="direct m.f", hi=4, clo=s, chi=s + len("dawn_m__f(v)"))
    inner_bad = dict(inner_ok, clo=len(line2) - 1, chi=len(line2) + 11)
    cases["prefix of its enclosing call"] = ([enclosing, inner_ok], None)
    cases["prefix of its enclosing call, claimed past it"] = ([enclosing, inner_bad], "not in the C")
    bad = []
    for label, (rows, words) in cases.items():
        got = occurrence_rules("self-test", rows)
        if words is None and got:
            bad.append(f"{label}: expected no problem, got {got}")
        elif words is not None and not any(words in g for g in got):
            bad.append(f"{label}: expected a problem with `{words}`, got {got}")
        else:
            print(f"OK: self-test {label}")
    if bad:
        for b_ in bad:
            print("FAIL: " + b_)
        sys.exit(1)
    # the symbol spelling, against two symbols the emitter wrote
    assert mangle("dawn$pkg$tileir/dev", "load_cell") == "dawn_dawn_3pkg_3tileir_2dev__load_1cell"
    assert mangle("std/io", "println") == "dawn_std_2io__println"
    print(f"OK: {len(cases)} self-test case(s)")


def main():
    args = sys.argv[1:]
    if args == ["--self-test"]:
        return self_test()
    names = args or CASES
    unknown = [n for n in names if n not in CASES]
    if unknown:
        fail(f"no case {unknown}; the cases are {CASES}")
    problems = []
    with tempfile.TemporaryDirectory(prefix="c-map.") as work:
        for name in names:
            problems += check_case(name, Path(work))
    if problems:
        for p in problems[:60]:
            print("FAIL: " + p)
        if len(problems) > 60:
            print(f"... and {len(problems) - 60} more")
        sys.exit(1)
    print(f"OK: every row points at its call in the C and in the source ({len(names)} case(s))")


if __name__ == "__main__":
    main()
