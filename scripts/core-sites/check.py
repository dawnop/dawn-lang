#!/usr/bin/env python3
"""Every call site lowering puts in Core is a call the parser sees, and the other way round.

    python3 scripts/core-sites/check.py                    # every case below
    python3 scripts/core-sites/check.py corpus flash_attn  # some of them

Core call nodes carry a site (docs/source-span-map-design.md): where the call
was written, as offsets from its declaration, plus where the callee's name
starts. No output of the compiler reads it yet, so nothing else in the tree
would notice a site that points at the wrong call, at the wrong declaration,
or at nothing. This is the reader that notices. It compiles a program with
`dawn __lower --sites`, which lists every site in file coordinates after the
whole Core pipeline (rc included) has run, runs `dawn parse` on the same
file, and holds the two to three rules:

  sound      every site's [lo, hi) is exactly one parser call node's span, and
             its nlo is that node's callee name start: the `name@` of a
             method call, the `field@` of an applied field, otherwise the
             start of an application's callee expression;
  injective  no two sites name the same call node;
  complete   every parser call node in the checked functions has a site,
             except the kinds listed in EXCUSED, each for a stated reason.

Which nodes are calls is the parser's answer, not a scan of the text:
`Apply` (its callee is its first child, which is also how a pipe `x |> f`
parses) and `MethodCall` (its callee is the `name@` span). The parse half is
the same reading site/gpu-map/record.py does for the GPU page.

The cases are the call-shape corpus beside this file and three kernels of
scripts/tile-golden/kernels.dawn (flash_attn, softmax, vadd), compiled the way
record.py compiles them: as the main module of a throwaway project with
tileir and tileref as dependencies.

run.py beside this file is what shows each rule has teeth: it restores a
defect in a copy of the compiler and requires this script to go red on it.
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
HERE = ROOT / "scripts" / "core-sites"
# a launcher, or a compiler jar (run.py's mutants), run the way bin/dawn runs one
DAWN_BIN = os.environ.get("DAWN_BIN", str(ROOT / "bin" / "dawn"))
DAWN = ["java", "-Xss512m", "-Xmx2g", "-jar", DAWN_BIN] if DAWN_BIN.endswith(".jar") else [DAWN_BIN]
KERNELS = ROOT / "scripts" / "tile-golden" / "kernels.dawn"


# (source, module listing, functions to check or None for all)
CASES = {
    "corpus": (HERE / "corpus.dawn", None),
    "flash_attn": (KERNELS, ["flash_attn"]),
    "softmax": (KERNELS, ["softmax"]),
    "vadd": (KERNELS, ["vadd"]),
}

# Call nodes that lower to no call, so carry no site. Each is decided from the
# parse alone, and each says why.
#   ctor      a constructor application builds a value; Core has no call
#             there (CCtor), and the design leaves constructors unsited
#   self      a self call in tail position is a loop after lowering (spec
#             12.4); one that is not in tail position keeps its site, which
#             the sound rule still checks
#   rewritten builtins lowering turns into something that is not a call of
#             that name: `to_string` is a rendering chosen by type, `Some`-like
#             helpers are not here because they are constructors
EXCUSED_BUILTINS = {"to_string", "char_unchecked"}


def fail(msg: str) -> None:
    print(f"scripts/core-sites/check.py: {msg}", file=sys.stderr)
    sys.exit(1)


class Node:
    def __init__(self, depth, text, lo, hi):
        self.depth, self.text, self.lo, self.hi = depth, text, lo, hi
        self.kids = []
        self.parent = None

    @property
    def kind(self):
        return self.text.split(" ", 1)[0]


def parse_forest(dump: str) -> list:
    """The top-level declarations of a `dawn parse` dump, as trees."""
    tops, stack = [], []
    for raw in dump.splitlines():
        body = raw.lstrip(" ")
        if not body:
            continue
        depth = (len(raw) - len(body)) // 2
        m = re.search(r" @(\d+)\.\.(\d+)$", body)
        node = Node(depth, body, int(m.group(1)) if m else None, int(m.group(2)) if m else None)
        while stack and stack[-1].depth >= depth:
            stack.pop()
        if stack:
            node.parent = stack[-1]
            stack[-1].kids.append(node)
        elif depth == 1:
            tops.append(node)
        if depth >= 1:
            stack.append(node)
    return tops


def fn_name(top: Node) -> str:
    return top.text.split(" ")[1]


def calls_under(n: Node, out: list) -> list:
    if n.kind in ("Apply", "MethodCall"):
        out.append(n)
    for k in n.kids:
        calls_under(k, out)
    return out


def callee(n: Node):
    """(name, name start) of a call node."""
    if n.kind == "MethodCall":
        m = re.search(r"name@(\d+)\.\.(\d+)", n.text)
        return n.text.split(" ")[1], int(m.group(1))
    head = n.kids[0]
    name = head.text.split(" ")[1] if head.kind in ("Var", "Ctor") else None
    if head.kind == "FieldAccess":
        # `(r.f)(x)`: the callee is the field, named where the field is
        m = re.search(r"field@(\d+)\.\.(\d+)", head.text)
        return head.text.split(" ")[1], int(m.group(1))
    return name, head.lo


def excuse(n: Node, fn: str):
    name, _ = callee(n)
    if n.kind == "Apply" and n.kids[0].kind == "Ctor":
        return "ctor"
    if name is not None and name[:1].isupper():
        return "ctor"
    if name == fn:
        return "self"
    if name in EXCUSED_BUILTINS:
        return "rewritten"
    return None


def lower_sites(target: Path, module: str) -> list:
    with tempfile.TemporaryDirectory(prefix="core-sites.") as work:
        out = Path(work) / "sites"
        out.mkdir()
        r = subprocess.run(DAWN + ["__lower", "--sites", str(out), str(target)],
                           capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0 or "GAP " in r.stdout:
            fail(f"`dawn __lower --sites {target}` failed:\n" + (r.stderr + r.stdout)[-3000:])
        listing = out / f"{module}.sites"
        if not listing.exists():
            fail(f"`dawn __lower` wrote no {listing.name}: {sorted(p.name for p in out.iterdir())}")
        rows = []
        for line in listing.read_text(encoding="utf-8").splitlines():
            owner, fname, origin, what, at = line.split("\t")
            if "?" in at:
                fail(f"a site in {fname} (origin `{origin}`) has no declaration base to place it")
            lo, hi, nlo = (int(x) for x in at.split(" "))
            rows.append({"fn": fname, "origin": origin, "what": what, "lo": lo, "hi": hi, "nlo": nlo})
        return rows


def kernels_project(work: Path) -> Path:
    proj = work / "kernels"
    (proj / "src").mkdir(parents=True)
    shutil.copy(KERNELS, proj / "src" / "main.dawn")
    (proj / "dawn.toml").write_text(
        "schema = 1\nname = \"core_sites\"\n\n[deps]\n"
        f"tileir = \"{ROOT / 'packages' / 'tileir'}\"\n"
        f"tileref = \"{ROOT / 'packages' / 'tileref'}\"\n", encoding="utf-8")
    return proj


def check(name: str, source: Path, fns, rows: list, tops: list) -> list:
    """The three rules on one case; the problems found."""
    chosen = [t for t in tops if t.kind == "Fn" and (fns is None or fn_name(t) in fns)]
    if fns is not None and sorted(fn_name(t) for t in chosen) != sorted(fns):
        return [f"{name}: the parse has no Fn {sorted(set(fns) - {fn_name(t) for t in chosen})}"]
    problems = []
    by_span = {}
    for t in chosen:
        for c in calls_under(t, []):
            by_span.setdefault((c.lo, c.hi), []).append((t, c))
    spans = [(t.lo, t.hi) for t in chosen]
    inside = [r for r in rows if any(a <= r["lo"] and r["hi"] <= b for a, b in spans)]
    if fns is None and len(inside) != len(rows):
        stray = [r for r in rows if r not in inside]
        problems.append(f"{name}: {len(stray)} site(s) fall in no function of the file, first {stray[0]}")
    claimed = {}
    for r in inside:
        hits = by_span.get((r["lo"], r["hi"]), [])
        if not hits:
            problems.append(f"{name}: site {r['lo']}..{r['hi']} ({r['what']} in {r['fn']}) is no call the parser sees")
            continue
        # two parser nodes with one span (a call wrapped in nothing but
        # itself) cannot happen for calls; take the innermost if it ever does
        t, c = hits[-1]
        _, nlo = callee(c)
        if r["nlo"] != nlo:
            problems.append(f"{name}: site {r['lo']}..{r['hi']} ({r['what']}) has its name at {r['nlo']}, "
                            f"expected {nlo}")
        key = (c.lo, c.hi)
        if key in claimed:
            problems.append(f"{name}: call {c.text} has two sites: {claimed[key]['what']} and {r['what']}")
        claimed[key] = r
    excused = {}
    for t in chosen:
        for c in calls_under(t, []):
            if (c.lo, c.hi) in claimed:
                continue
            why = excuse(c, fn_name(t))
            if why is None:
                problems.append(f"{name}: call {c.text} in {fn_name(t)} has no site")
            else:
                excused[why] = excused.get(why, 0) + 1
    calls = sum(len(calls_under(t, [])) for t in chosen)
    summary = ", ".join(f"{k} {v}" for k, v in sorted(excused.items())) or "none"
    print(f"{name}: {len(claimed)} of {calls} call(s) sited, excused: {summary}")
    return problems


def main() -> None:
    names = sys.argv[1:] or list(CASES)
    unknown = [n for n in names if n not in CASES]
    if unknown:
        fail(f"no case {unknown}; the cases are {list(CASES)}")
    problems = []
    with tempfile.TemporaryDirectory(prefix="core-sites.") as work:
        work = Path(work)
        lowered, parsed = {}, {}
        for name in names:
            source, fns = CASES[name]
            if source not in lowered:
                if source == KERNELS:
                    lowered[source] = lower_sites(kernels_project(work), "main")
                else:
                    lowered[source] = lower_sites(source, source.stem)
                p = subprocess.run(DAWN + ["parse", str(source)], capture_output=True, text=True, cwd=ROOT)
                if p.returncode != 0:
                    fail(f"`dawn parse {source}` failed:\n" + (p.stderr or p.stdout)[-2000:])
                parsed[source] = parse_forest(p.stdout)
            problems += check(name, source, fns, lowered[source], parsed[source])
    if problems:
        for p in problems[:60]:
            print("FAIL: " + p)
        if len(problems) > 60:
            print(f"... and {len(problems) - 60} more")
        sys.exit(1)
    print(f"OK: every site pairs with one parser call and every call is sited or excused ({len(names)} case(s))")


if __name__ == "__main__":
    main()
