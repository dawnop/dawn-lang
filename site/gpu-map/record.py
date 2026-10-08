#!/usr/bin/env python3
"""Which call of flash_attn wrote which line of its Tile IR, and where that call is in the source.

    python3 site/gpu-map/record.py            # check flash_attn.map against a fresh recording
    python3 site/gpu-map/record.py --record   # rewrite flash_attn.map

The cuTile page (site/src/gen/gpu.dawn) shows one kernel, scripts/tile-golden's
`flash_attn`, with every call in its source beside the Tile IR lines that call
wrote. Two programs know half each, and neither half is guessed:

  - packages/tileir knows which call issued which operation, because it ran
    them: `prog.trace_calls` keeps the tree of the kernel's calls (a call
    inside a `d_range` or a `d_scan` closure is that region call's child) and
    `render.line_map` carries it to lines of the text. That needs the kernel
    to RUN, so it is a Dawn harness over a copy of kernels.dawn.
  - Dawn's own parser knows where each call is: `dawn parse` gives every call
    node its code point span and the span of its callee's name.

The two are paired strictly, level by level of the tree: under each parent,
the names of the kernel's calls in the order they ran must be EXACTLY the
names the parser finds in evaluation order (arguments left to right, each
call after its arguments, a closure handed to a call being that call's
children). Anything else stops here with both lists printed: a helper with
an effect, a call under host control flow, a closure bound before the call
that runs it, a call of a closure. Which names are calls at all is read off
packages/tileir/src/dev.dawn (its `called("<name>"` marks); every other call,
`permute(..)` or `neg_inf()`, records nothing and is looked through.

The generator is a pure function of files on disk (site/build.sh says why:
scripts/site-dist-diff.sh runs it on two backends and compares), so the pairing
is RECORDED into flash_attn.map beside this file, and site/build.sh runs this
script without `--record` on every build: a kernels.dawn or a tileir that moved
under the recording is a red build, never a stale page.

flash_attn.map:

    kernel flash_attn
    fn 2380-2406                    the function's lines in kernels.dawn
    ops 38                          operations recorded, make_token included
    head 1-4                        lines no call wrote: module, entry, make_token
    call 0 -1 block_id 2381:12-2381:23 2381:12-2381:20 4-5
    ...
    tail 92-95                      return and the two closing braces

A call line is its row, its parent's row (-1 at the top of the body), its
name, its span and its name's span in kernels.dawn (line:column, both from 1,
columns in code points, the end exclusive), then the lines of Tile IR it wrote
itself, its children's left out (half-open, from 1). A region call has its
header, its terminator and its closing brace.
"""

from pathlib import Path
import contextlib
import io
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
KERNELS = ROOT / "scripts" / "tile-golden" / "kernels.dawn"
GOLDEN = ROOT / "scripts" / "tile-golden"
DEV = ROOT / "packages" / "tileir" / "src" / "dev.dawn"
NAME = "flash_attn"
OUT = Path(__file__).resolve().parent / f"{NAME}.map"

CUT_AT = "# Trace `name` twice and answer the record, or panic if the two runs differ.\n"

# (old, new, how many times old must occur)
EDITS = [
    ("use tileir/prog.{TileProg, ",
     "use tileir/prog.{TileProg, trace_calls, op_count, erase, ", 1),
    ("use tileir/render.{render}\n",
     "use tileir/render.{render, line_map}\n", 1),
    ("use tileir/bytecode.{encode, bytecode_version}\n", "", 1),
    ("use std/io.{with_fs_real, write_bytes}\n", "", 1),
]

MAIN = '''
fn spans(rs: List[(Int, Int)]) -> String =
  list.fold(rs, "", (acc, r) => {
    let (a, b) = r
    acc ++ " ${a}-${b}"
  })

pub fn main() -> Unit !io = {
  let (p, calls) = %TRACE%
  if p != trace("%NAME%") { panic("%NAME%: the call marks changed the program") } else { () }
  match line_map(p, calls) {
    Ok(m) -> {
      if m.text != render(p) { panic("%NAME%: the line map's text is not render's") } else { () }
      println("ops ${op_count(p.ops)}")
      println("head${spans(m.head)}")
      for k in range(0, len(calls)) {
        let c = calls[k]
        println("call ${k} ${c.parent} ${c.name}${spans(m.calls[k].lines)}")
      }
      let (ta, tb) = m.tail
      println("tail ${ta}-${tb}")
    }
    Err(e) -> panic("%NAME%: ${e}")
  }
}
'''


def fail(msg: str) -> None:
    print(f"site/gpu-map/record.py: {msg}", file=sys.stderr)
    sys.exit(1)


# ---- the run: tileir's tree of calls and the lines each wrote ----

def harness_source(src: str) -> str:
    for old, new, times in EDITS:
        if src.count(old) != times:
            fail(f"kernels.dawn has {src.count(old)} of {old.strip()!r}, expected {times}")
        src = src.replace(old, new)
    if src.count(CUT_AT) != 1:
        fail(f"kernels.dawn has {src.count(CUT_AT)} of {CUT_AT.strip()!r}, expected 1")
    src = src[:src.index(CUT_AT)]
    # the kernel's dispatch arm, traced with the side table instead: its
    # `traceN` call becomes `trace_calls` over the same markers, erased
    arm = re.search(r'^  "' + NAME + r'" -> \{\n((?:    .*\n)+)  \}\n', src, re.M)
    if not arm:
        fail(f"kernels.dawn's dispatch has no arm for {NAME}")
    body = " ".join(l.strip() for l in arm.group(1).splitlines())
    m = re.fullmatch(r'let \(p, _e\) = trace([1-5])\((.*)\) p', body)
    if not m:
        fail(f"the {NAME} arm is not one traceN call answered as `p`: {body}")
    args = split_args(m.group(2))
    count = int(m.group(1))
    if len(args) != count + 2 or args[0] != f'"{NAME}"' or args[-1] != NAME:
        fail(f"the {NAME} arm does not trace {NAME} itself with {count} markers: {body}")
    markers = args[1:-1]
    formats = [re.match(r'(?:In|Out|Shared|Scalar)\(([A-Z0-9]+)', k).group(1) for k in markers]
    params = ", ".join(f"param({d}, {k})" for k, d in enumerate(formats))
    erased = ", ".join(f"erase({k})" for k in markers)
    traced = f'trace_calls("{NAME}", [], () => {NAME}({params}), markers: [{erased}])'
    return src + MAIN.replace("%TRACE%", traced).replace("%NAME%", NAME)


def split_args(s: str) -> list:
    """A call's argument text cut at its top-level commas."""
    out, depth, cur = [], 0, ""
    for c in s:
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
    out.append(cur.strip())
    return out


def run_harness(src: str) -> str:
    with tempfile.TemporaryDirectory(prefix="gpu-map.") as work:
        proj = Path(work)
        (proj / "src").mkdir()
        (proj / "src" / "main.dawn").write_text(harness_source(src), encoding="utf-8")
        (proj / "dawn.toml").write_text(
            "schema = 1\nname = \"gpu_map\"\n\n[deps]\n"
            f"tileir = \"{ROOT / 'packages' / 'tileir'}\"\n"
            f"tileref = \"{ROOT / 'packages' / 'tileref'}\"\n",
            encoding="utf-8")
        r = subprocess.run([str(ROOT / "bin" / "dawn"), "run", str(proj)],
                           capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        fail("the harness did not run:\n" + (r.stderr or r.stdout)[-2000:])
    return r.stdout


# ---- the parse: where each call is ----

class Node:
    def __init__(self, depth, text, lo, hi):
        self.depth, self.text, self.lo, self.hi = depth, text, lo, hi
        self.kids = []

    @property
    def kind(self):
        return self.text.split(" ", 1)[0]


def parse_tree(dump: str, name: str) -> Node:
    """The `Fn <name>` subtree of a `dawn parse` dump."""
    root, stack, inside = None, [], False
    for raw in dump.splitlines():
        body = raw.lstrip(" ")
        depth = (len(raw) - len(body)) // 2
        if depth == 1:
            inside = body.startswith(f"Fn {name} ")
        if not inside:
            continue
        m = re.search(r" @(\d+)\.\.(\d+)$", body)
        node = Node(depth, body, int(m.group(1)) if m else None, int(m.group(2)) if m else None)
        while stack and stack[-1].depth >= depth:
            stack.pop()
        if stack:
            stack[-1].kids.append(node)
        else:
            root = node
        stack.append(node)
    if root is None:
        fail(f"`dawn parse` has no `Fn {name}` in kernels.dawn")
    return root


class Env:
    """What the walk knows about names. `decls` are the `var`s declared so far
    (name, Let node) in order, `cells` the ones the staged `for` being walked
    carries (each mention is a recorded `get`, each assignment a `set`),
    `tiles` the names bound to something tile-valued (so that an operator over
    them is a recorded call and an operator over host numbers is not)."""

    def __init__(self):
        self.decls, self.cells, self.tiles = [], set(), set()


OPERATORS = {"ADD": {"add", "addi", "idx_add"}, "SUB": {"sub", "subi", "idx_sub"},
             "MUL": {"mul", "muli", "idx_mul"}, "DIV": {"div", "divi", "idx_div"},
             "REM": {"idx_rem"}}
SRC = ""


def node_name(n: Node) -> str:
    return n.text.split(" ")[1]


def tile_valued(n: Node, dev: set, env: Env) -> bool:
    """Whether an expression's value is a tile (or an index): it calls a
    recorded function, mentions a cell, or mentions a name bound to one. The
    pairing below proves the guess: a host operation taken for a tile
    operation, or the reverse, makes the two lists of calls differ."""
    if n.kind == "Apply" and n.kids and n.kids[0].kind == "Var" and node_name(n.kids[0]) in dev:
        return True
    if n.kind == "MethodCall" and node_name(n) in dev:
        return True
    if n.kind == "Var" and (node_name(n) in env.tiles or node_name(n) in env.cells):
        return True
    return any(tile_valued(k, dev, env) for k in n.kids)


def assigned_in(n: Node) -> list:
    out = []
    if n.kind == "Assign":
        out.append(node_name(n))
    for k in n.kids:
        out += assigned_in(k)
    return out


def static_calls(n: Node, dev: set, env: "Env" = None) -> list:
    """The calls of `dev` under `n` in evaluation order, each a dict with its
    span, its name's span and its children (the calls in a closure it takes).
    A call's `names` are the recorded names it may have and `text` what its
    name span holds in the source (an operator, a `var`'s name, a callee)."""
    env = env or Env()
    kind = n.kind
    if kind == "Lambda":
        fail(f"a closure at {n.lo}..{n.hi} is not an argument of a call that runs it")
    if kind == "Let":
        name = node_name(n)
        inner = [k for k in n.kids if k.kind not in ("TNamed", "TApp", "TFn", "PBind")]
        calls = []
        for k in inner:
            calls += static_calls(k, dev, env)
        if inner and tile_valued(inner[-1], dev, env):
            env.tiles.add(name)
        if "mut=true" in n.text:
            env.decls.append((name, n))
            env.tiles.add(name)
        return calls
    if kind == "Assign":
        name = node_name(n)
        calls = []
        for k in n.kids:
            calls += static_calls(k, dev, env)
        if name in env.cells:
            m = re.search(r"name@(\d+)\.\.(\d+)", n.text)
            calls.append({"names": {"set"}, "span": (n.lo, n.hi), "name_span": (int(m.group(1)), int(m.group(2))),
                          "text": name, "kids": []})
        return calls
    if kind == "Var" and node_name(n) in env.cells:
        return [{"names": {"get"}, "span": (n.lo, n.hi), "name_span": (n.lo, n.hi), "text": node_name(n), "kids": []}]
    if kind == "Binary":
        op = n.text.split(" ")[1]
        m = re.search(r"op@(\d+)\.\.(\d+)", n.text)
        calls = static_calls(n.kids[0], dev, env) + static_calls(n.kids[1], dev, env)
        if op in OPERATORS and tile_valued(n, dev, env):
            calls.append({"names": OPERATORS[op], "span": (n.lo, n.hi), "name_span": (int(m.group(1)), int(m.group(2))),
                          "text": SRC[int(m.group(1)):int(m.group(2))], "kids": []})
        return calls
    if kind == "Unary" and n.text.split(" ")[1] == "NEG" and tile_valued(n, dev, env):
        calls = static_calls(n.kids[0], dev, env)
        calls.append({"names": {"neg", "negi"}, "span": (n.lo, n.hi), "name_span": (n.lo, n.lo + 1), "text": "-", "kids": []})
        return calls
    if kind == "For" and len(n.kids) == 3 and n.kids[1].kind == "Apply" and n.kids[1].kids \
            and n.kids[1].kids[0].kind == "Var" and node_name(n.kids[1].kids[0]) in dev:
        # A staged `for` over a region call (`for j in d_range(..) { .. }`): the
        # region is the call, its span is the whole statement, and the body's
        # calls are its children, as the closure's were before `for` was staged.
        # Before it, one `carry` for each `var` the body assigns, in declaration
        # order; after it, one `get` for each, which hands the host variable
        # what the loop left in the cell.
        head = n.kids[1].kids[0]
        before = []
        for a in n.kids[1].kids[1:]:
            before += static_calls(a, dev, env)
        written = set(assigned_in(n.kids[2]))
        carried = [(name, let) for name, let in env.decls if name in written]
        opened = []
        for name, let in carried:
            at = let.lo + SRC[let.lo:let.hi].index(name, 3)
            opened.append({"names": {"carry"}, "span": (let.lo, let.hi), "name_span": (at, at + len(name)),
                           "text": name, "kids": []})
        inside = Env()
        inside.decls, inside.tiles, inside.cells = env.decls, set(env.tiles), set(name for name, _ in carried)
        kids = static_calls(n.kids[2], dev, inside)
        closed = [{"names": {"get"}, "span": (n.lo, n.hi), "name_span": (n.lo, n.lo + 3), "text": "for", "kids": []}
                  for _ in carried]
        return before + opened + [{"names": {node_name(head)}, "span": (n.lo, n.hi), "name_span": (head.lo, head.hi),
                                   "text": node_name(head), "kids": kids}] + closed
    if kind in ("If", "Match", "For", "While") and any_call(n, dev):
        fail(f"a call under host control flow at {n.lo}..{n.hi}")
    if kind in ("Apply", "MethodCall"):
        if kind == "Apply":
            head, args = n.kids[0], n.kids[1:]
            callee = head.text.split(" ")[1] if head.kind == "Var" else None
            name_span = (head.lo, head.hi)
        else:
            head, args = None, n.kids
            callee = n.text.split(" ")[1]
            m = re.search(r"name@(\d+)\.\.(\d+)", n.text)
            name_span = (int(m.group(1)), int(m.group(2)))
        before, closures = [], []
        for a in args:
            inner = a.kids[0] if a.kind == "Arg" and a.kids else a
            if inner.kind == "Lambda":
                if callee not in dev:
                    fail(f"a closure at {inner.lo}..{inner.hi} is handed to `{callee}`, which is not a call the recording sees")
                for k in inner.kids:
                    if k.kind != "LParam":
                        closures += static_calls(k, dev, env)
            else:
                before += static_calls(a, dev, env)
                if inner.kind in ("Float", "Int") and callee in dev and callee != "lit":
                    # A bare number handed to a call of the recording may be
                    # made a tile constant by the compiler before the call
                    # runs (`mma(a, b, 0.0)`), and that is a recorded `lit`
                    # row with no call of its own in the source. It may also
                    # stay a host number (`full(.., 0.0)`), so the entry is
                    # optional: `pair` takes it when the run has the `lit`
                    # row here and leaves it when it does not.
                    before.append({"names": {"lit"}, "optional": True, "span": (inner.lo, inner.hi),
                                   "name_span": (inner.lo, inner.hi), "text": SRC[inner.lo:inner.hi], "kids": []})
        if head is not None and head.kind != "Var":
            before = static_calls(head, dev, env) + before
        if callee in dev:
            return before + [{"names": {callee}, "span": (n.lo, n.hi), "name_span": name_span, "text": callee,
                              "kids": closures}]
        if closures:
            fail(f"`{callee}` takes a closure the recording does not see into")
        return before
    out = []
    for k in n.kids:
        out += static_calls(k, dev, env)
    return out


def any_call(n: Node, dev: set) -> bool:
    if n.kind == "Apply" and n.kids and n.kids[0].kind == "Var" and n.kids[0].text.split(" ")[1] in dev:
        return True
    if n.kind == "MethodCall" and n.text.split(" ")[1] in dev:
        return True
    return any(any_call(k, dev) for k in n.kids)


# ---- the pairing ----

def pair(static: list, rows: list) -> list:
    """Each row of the run with the static call it is, level by level."""
    kids = {}
    for r in rows:
        kids.setdefault(r["parent"], []).append(r)
    paired = {}

    def walk(sl, parent):
        ran = kids.get(parent, [])
        taken, j = [], 0
        for s in sl:
            if j < len(ran) and ran[j]["name"] in s["names"]:
                taken.append((s, ran[j]))
                j += 1
            elif not s.get("optional"):
                taken = None
                break
        if taken is None or j != len(ran):
            under = "the top of the body" if parent < 0 else f"row {parent} (`{rows[parent]['name']}`)"
            fail(f"under {under} the source calls {[sorted(s['names']) for s in sl]} "
                 f"and the recording ran {[r['name'] for r in ran]}")
        for s, r in taken:
            paired[r["id"]] = s
            walk(s["kids"], r["id"])

    walk(static, -1)
    if len(paired) != len(rows):
        fail(f"{len(rows) - len(paired)} recorded call(s) sit under no call of the source")
    return [paired[r["id"]] for r in rows]


def selftest() -> None:
    """The pairing's rules on made-up rows, so that a change to them is caught
    without a kernel: a bare number is a `lit` row where the run has one and
    nothing where it has none, and anything else still stops."""
    def call(name, **kw):
        return {"names": {name}, "span": (0, 0), "name_span": (0, 0), "text": name, "kids": [], **kw}
    lit = call("lit", optional=True)
    row = lambda i, name: {"id": i, "parent": -1, "name": name, "lines": []}
    ok = pair([call("load"), lit, call("mma")], [row(0, "load"), row(1, "lit"), row(2, "mma")])
    assert len(ok) == 3 and ok[1] is lit
    assert pair([lit, call("full")], [row(0, "full")])[0]["names"] == {"full"}
    for static, rows in (([call("load"), call("mma")], [row(0, "load"), row(1, "lit"), row(2, "mma")]),
                         ([lit, call("mma")], [row(0, "lit"), row(1, "lit"), row(2, "mma")]),
                         ([lit, call("mma")], [row(0, "mma"), row(1, "lit")])):
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                pair(static, rows)
        except SystemExit:
            continue
        raise AssertionError("a pairing that should stop did not")


def place(src: str):
    starts = [0] + [m.end() for m in re.finditer("\n", src)]

    def at(off):
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= off:
                lo = mid
            else:
                hi = mid - 1
        return f"{lo + 1}:{off - starts[lo] + 1}"
    return at


def record() -> str:
    src = KERNELS.read_text(encoding="utf-8")
    dev = set(re.findall(r'called\("([a-z_0-9]+)"', DEV.read_text(encoding="utf-8")))
    ran = run_harness(src)
    p = subprocess.run([str(ROOT / "bin" / "dawn"), "parse", str(KERNELS)],
                       capture_output=True, text=True, cwd=ROOT)
    if p.returncode != 0:
        fail("`dawn parse` failed:\n" + (p.stderr or p.stdout)[-2000:])
    fn = parse_tree(p.stdout, NAME)
    body = [k for k in fn.kids if k.kind == "Block"]
    if len(body) != 1:
        fail(f"{NAME} is not a function with a block body")
    global SRC
    SRC = src
    static = static_calls(body[0], dev)
    rows, head, tail, ops = [], None, None, None
    for line in ran.splitlines():
        w = line.split(" ")
        if w[0] == "call":
            rows.append({"id": int(w[1]), "parent": int(w[2]), "name": w[3], "lines": w[4:]})
        elif w[0] == "head":
            head = " ".join(w[1:])
        elif w[0] == "tail":
            tail = w[1]
        elif w[0] == "ops":
            ops = w[1]
    if head is None or tail is None or ops is None:
        fail("the harness printed no head, tail or ops line:\n" + ran[-1000:])
    paired = pair(static, rows)
    at = place(src)
    for s in paired:
        if src[s["name_span"][0]:s["name_span"][1]] != s["text"]:
            fail(f"the parser's name span for `{sorted(s['names'])}` holds {src[s['name_span'][0]:s['name_span'][1]]!r}, not {s['text']!r}")
    golden = (GOLDEN / f"{NAME}.mlir").read_text(encoding="utf-8")
    if int(tail.split("-")[1]) - 1 != golden.count("\n"):
        fail(f"the map ends at line {int(tail.split('-')[1]) - 1}, {NAME}.mlir has {golden.count(chr(10))} lines")
    first = src[:fn.lo].count("\n") + 1
    last = src[:fn.hi].count("\n") + 1
    out = [f"kernel {NAME}", f"fn {first}-{last}", f"ops {ops}", f"head {head}"]
    for r, s in zip(rows, paired):
        (a, b), (na, nb) = s["span"], s["name_span"]
        out.append(" ".join(["call", str(r["id"]), str(r["parent"]), r["name"],
                             f"{at(a)}-{at(b)}", f"{at(na)}-{at(nb)}"] + r["lines"]))
    out.append(f"tail {tail}")
    return "\n".join(out) + "\n"


def main() -> None:
    write = sys.argv[1:] == ["--record"]
    if sys.argv[1:] not in ([], ["--record"]):
        fail("usage: record.py [--record]")
    selftest()
    fresh = record()
    calls = fresh.count("\ncall ")
    if write:
        OUT.write_text(fresh, encoding="utf-8")
        print(f"recorded {calls} calls of {NAME} into {OUT.relative_to(ROOT)}")
        return
    if not OUT.exists() or OUT.read_text(encoding="utf-8") != fresh:
        fail(f"{OUT.relative_to(ROOT)} is not what packages/tileir and the parser say today; "
             "run `python3 site/gpu-map/record.py --record` and commit the result")
    print(f"OK: {OUT.relative_to(ROOT)} matches a fresh recording of {calls} calls")


if __name__ == "__main__":
    main()
