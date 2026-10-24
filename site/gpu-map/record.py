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
  - Dawn's own parser knows where each call is: `dawnc parse` gives every call
    node its code point span and the span of its callee's name.

The two are paired strictly, level by level of the tree: under each parent,
the names of the kernel's calls in the order they ran must be EXACTLY the
names the parser finds in evaluation order (arguments left to right, each
call after its arguments, a closure handed to a call being that call's
children). Anything else stops here with both lists printed: a helper with
an effect, a call under unknown host control flow, a closure bound before the call
that runs it, a call of a closure. Which names are calls at all is read off
packages/tileir/src/dev.dawn (its `called("<name>"` marks); every other call,
`permute(..)` or `neg_inf()`, records nothing and is looked through.
Only literal Bool fields of the BF16 policy captured by fa_kernel select a
source arm; every other host condition keeps the global refusal.

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
import copy
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
KERNELS = ROOT / "scripts" / "tile-golden" / "kernels.dawn"
GOLDEN = ROOT / "scripts" / "tile-golden"
DEV = ROOT / "packages" / "tileir" / "src" / "dev.dawn"
BODY = "flash_attn"
NAME = "flash_attn_bf16_demo"
OUT = Path(__file__).resolve().parent / f"{BODY}.map"

PROBE_SRC = "pub fn probe() -> Int = 1\n"

CUT_AT = "# Trace `name` twice and answer the record, or panic if the two runs differ.\n"

# (old, new, how many times old must occur)
EDITS = [
    ("use tileir/bytecode.{encode, bytecode_version}\n", "\n", 1),
    ("use std/io.{with_fs_real, write_bytes}\n", "\n", 1),
    # the `--asm-args` mode of main (scripts/tile-gpu-diff) needs it; the cut
    # below removes that main
    ("use tileir/asm.{tileiras_args}\n", "\n", 1),
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
      println("@@ir")
      print(m.text)
      println("@@end")
      println("ops ${op_count(p.ops)}")
      println("head${spans(m.head)}")
      for k in range(0, len(calls)) {
        let c = calls[k]
        let at = match c.at { Some(a) -> {
            if loc.path(a) != "src/main.dawn" { panic("a recorded call is outside the displayed source") }
            "${loc.line(a)}:${loc.col(a)}"
          }
          None -> "-" }
        println("call ${k} ${c.parent} ${c.name} ${at}${spans(m.calls[k].lines)}")
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


# ---- the compiler: dawnc, no JVM ----

_DAWNC = None


def dawnc() -> str:
    """The native driver this script runs the harness and the parser with.

    One resolution for every site script (site/dawnc.sh): DAWNC_BIN if set,
    otherwise the binary built from this tree and cached under site/build/.
    Either way the binary is probed once, because a wrong one (the JVM
    launcher, a stale file, something that is not a compiler at all) must stop
    the build here with a name on it, not surface as a parse tree that is
    quietly empty or shaped differently.
    """
    global _DAWNC
    if _DAWNC is not None:
        return _DAWNC
    exe = os.environ.get("DAWNC_BIN", "")
    if exe:
        where = "DAWNC_BIN"
    else:
        where = "site/dawnc.sh"
        r = subprocess.run(["bash", "-c", ". site/dawnc.sh && site_dawnc"],
                           capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0 or not r.stdout.strip():
            fail("could not get a dawnc from site/dawnc.sh:\n" + (r.stderr or r.stdout)[-2000:])
        exe = r.stdout.strip().splitlines()[-1]
    path = Path(exe)
    if not path.is_absolute():
        path = ROOT / path
    if not (path.is_file() and os.access(path, os.X_OK)):
        fail(f"{where} names {exe}, which is not an executable file")
    with tempfile.TemporaryDirectory(prefix="gpu-map-probe.") as work:
        probe = Path(work) / "probe.dawn"
        probe.write_text(PROBE_SRC, encoding="utf-8")
        try:
            r = subprocess.run([str(path), "parse", str(probe)],
                               capture_output=True, text=True, cwd=ROOT, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            fail(f"{where} names {exe}, which does not run as `dawnc parse`: {e}")
        want = f"== {probe} ==\nModule"
        if r.returncode != 0 or not r.stdout.startswith(want) or "\n  Fn probe" not in r.stdout:
            fail(f"{where} names {exe}, which is not a dawnc whose `parse` prints the AST "
                 f"dump (exit {r.returncode}); got:\n" + (r.stdout or r.stderr)[:400])
    _DAWNC = str(path)
    return _DAWNC


# ---- the run: tileir's tree of calls and the lines each wrote ----

RENDER_IMPORT = re.compile(r"^use tileir/render\.\{([^}]*)\}\n", re.M)
PROG_IMPORT = re.compile(r"^use tileir/prog\.\{([^}]*)\}\n", re.M)


def harness_source(src: str) -> str:
    # The render import grows when kernels.dawn starts using another name from
    # the module (text_debug, knife T14b), so it is matched as a list and
    # `line_map` appended, not as one spelling. Absent or repeated still fails.
    found = RENDER_IMPORT.findall(src)
    if len(found) != 1:
        fail(f"kernels.dawn has {len(found)} 'use tileir/render.{{...}}' lines, expected 1")
    src = RENDER_IMPORT.sub(lambda m: "use tileir/render.{" + m.group(1) + ", line_map}\n", src, count=1)
    # Token guards also import TileOp. Extend the list without depending on
    # which existing name comes first; absent or repeated still fails.
    found = PROG_IMPORT.findall(src)
    if len(found) != 1:
        fail(f"kernels.dawn has {len(found)} 'use tileir/prog.{{...}}' lines, expected 1")
    # The TileOp checks below CUT_AT are removed from this harness too.
    members = [name.strip() for name in found[0].split(",") if name.strip() != "TileOp"]
    members += [name for name in ["trace_calls", "op_count", "erase"] if name not in members]
    src = PROG_IMPORT.sub(lambda m: "use tileir/prog.{" + ", ".join(members) + "}" + "\n" * m.group(0).count("\n"), src, count=1)
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
    if arm:
        lines = arm.group(1)
    elif f'  "{NAME}" -> {NAME}()\n' in src:
        # A separate recording assembler keeps the large dispatch below the
        # JVM method limit. Read that actual zero-argument entry, not a plan.
        entry = re.search(r'^fn ' + NAME + r'\(\) -> TileProg = \{\n(.*?)^\}\n', src, re.M | re.S)
        if not entry:
            fail(f"missing recording assembler for {NAME}")
        lines = entry.group(1)
    else:
        fail(f"kernels.dawn's dispatch has no arm for {NAME}")
    body = " ".join(l.strip() for l in lines.splitlines())
    m = re.fullmatch(r'let \(p, _e\) = trace([1-5])\((.*)\) p', body)
    if not m:
        fail(f"the {NAME} arm is not one traceN call answered as `p`: {body}")
    args = split_args(m.group(2))
    count = int(m.group(1))
    if len(args) != count + 2 or args[0] != f'"{NAME}"' or args[-1] != 'fa_kernel(BF16, fa_bf16_math())':
        fail(f"the {NAME} arm does not trace {NAME} itself with {count} markers: {body}")
    markers = args[1:-1]
    formats = [re.match(r'(?:In|Out|Shared|Scalar)\(([A-Z0-9]+)', k).group(1) for k in markers]
    if count != 5 or formats != ["BF16", "BF16", "BF16", "F32", "F32"]:
        fail("reader instance must use BF16 inputs and F32 output/scale")
    params = ", ".join(f"param({d}, {k})" for k, d in enumerate(formats))
    erased = ", ".join(f"erase({k})" for k in markers)
    traced = f'trace_calls("{NAME}", [], () => ({args[-1]})({params}), markers = [{erased}])'
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


HARNESS_DIR = ROOT / "site" / "gpu-map" / "harness"


def run_harness(src: str) -> str:
    # The harness is a project of its own (site/gpu-map/harness: dawn.toml is
    # committed, src/main.dawn is written here from kernels.dawn and ignored by
    # git). It is listed in site/native-progs.txt, so site_prog builds it once
    # with dawnc and the site's one CI cache keeps it; `dawnc run` would emit C
    # and run cc on every build (about 40 s). Its key reads kernels.dawn
    # through harness/inputs.txt, since main.dawn does not exist when CI
    # computes the cache key.
    (HARNESS_DIR / "src").mkdir(parents=True, exist_ok=True)
    main = HARNESS_DIR / "src" / "main.dawn"
    # Keep the original function text and line count: runtime Loc values
    # independently verify parser spans. Remove the generated source after
    # use so it is not a second formatting input to the site.
    text = harness_source(src)
    if not main.exists() or main.read_text(encoding="utf-8") != text:
        main.write_text(text, encoding="utf-8")
    r = subprocess.run(["bash", "-c", ". site/dawnc.sh && site_prog gpu_map_harness"],
                       capture_output=True, text=True, cwd=ROOT,
                       env={**os.environ, "DAWNC_BIN": dawnc()})
    if r.returncode != 0 or not r.stdout.strip():
        fail("the harness did not build:\n" + (r.stderr or r.stdout)[-2000:])
    exe = ROOT / r.stdout.strip().splitlines()[-1]
    r = subprocess.run([str(exe)], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        fail("the harness did not run:\n" + (r.stderr or r.stdout)[-2000:])
    main.unlink()
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
    """The `Fn <name>` subtree of a `dawnc parse` dump."""
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
        fail(f"`dawnc parse` has no `Fn {name}` in kernels.dawn")
    return root


class Env:
    """What the walk knows about names. `decls` are the `var`s declared so far
    (name, Let node) in order, `cells` the ones the staged `for` being walked
    carries (each mention is a recorded `get`, each assignment a `set`),
    `tiles` the names bound to something tile-valued (so that an operator over
    them is a recorded call and an operator over host numbers is not)."""

    def __init__(self, policy=None):
        self.policy = policy or {}
        self.decls, self.cells, self.tiles = [], set(), set()


OPERATORS = {"ADD": {"add", "addi", "idx_add"}, "SUB": {"sub", "subi", "idx_sub"},
             "MUL": {"mul", "muli", "idx_mul"}, "DIV": {"div", "divi", "idx_div"},
             "REM": {"idx_rem"}}
SRC = ""


def node_name(n: Node) -> str:
    return n.text.split(" ")[1]


HELPERS = {}


def tile_valued(n: Node, dev: set, env: Env) -> bool:
    """Whether an expression's value is a tile (or an index): it calls a
    recorded function, mentions a cell, or mentions a name bound to one. The
    pairing below proves the guess: a host operation taken for a tile
    operation, or the reverse, makes the two lists of calls differ."""
    if n.kind == "Apply" and n.kids and n.kids[0].kind == "Var" and node_name(n.kids[0]) == "tile_shape":
        return False
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
        inside = Env(env.policy)
        inside.decls, inside.tiles, inside.cells = env.decls, set(env.tiles), set(name for name, _ in carried)
        kids = static_calls(n.kids[2], dev, inside)
        closed = [{"names": {"get"}, "span": (n.lo, n.hi), "name_span": (n.lo, n.lo + 3), "text": "for", "kids": []}
                  for _ in carried]
        return before + opened + [{"names": {node_name(head)}, "span": (n.lo, n.hi), "name_span": (head.lo, head.hi),
                                   "text": node_name(head), "site": n.kids[1].lo, "kids": kids}] + closed
    if kind == "If" and len(n.kids) == 3 and n.kids[0].kind == "FieldAccess":
        cond = n.kids[0]
        if len(cond.kids) == 1 and cond.kids[0].kind == "Var" and node_name(cond.kids[0]) == "math" and node_name(cond) in env.policy:
            return static_calls(n.kids[1 if env.policy[node_name(cond)] else 2], dev, env)
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
        if callee in HELPERS:
            inside = Env(env.policy)
            inside.tiles = {"x", "y"}
            closures = static_calls(HELPERS[callee], dev, inside)
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


def fixed_factory(dump):
    validate_factory(parse_tree(dump, "fa_kernel"))


def validate_factory(factory):
    params = [node_name(k) for k in factory.kids if k.kind == "Param"]
    lambdas = [k for k in factory.kids if k.kind == "Lambda"]
    if params != ["dt", "math"] or len(lambdas) != 1:
        fail("fa_kernel does not capture exactly dt and math")
    lam = lambdas[0]
    forwarded = [node_name(k) for k in lam.kids if k.kind == "LParam"]
    calls = [k for k in lam.kids if k.kind != "LParam"]
    if forwarded != ["q", "k", "v", "o", "scale"] or len(calls) != 1:
        fail("fa_kernel does not return the five parameter closure")
    call = calls[0]
    if call.kind != "Apply" or any(k.kind != "Var" for k in call.kids) or [node_name(k) for k in call.kids] != ["flash_attn"] + forwarded + params:
        fail("fa_kernel does not forward its parameters unchanged")


def fixed_policy(dump):
    """Read the literal Bool fields of the exact BF16 capture used by the harness.

    This is one fixed strategy constructor, not an interpreter. Changes to
    its shape or an unknown condition fail closed. The runtime locations
    independently distinguish identical call names in the two source arms.
    """
    fn = parse_tree(dump, "fa_bf16_math")
    bodies = [k for k in fn.kids if k.kind == "Record"]
    if len(bodies) != 1 or node_name(bodies[0]) != "FaNumerics" or "spread=false" not in bodies[0].text:
        fail("fa_bf16_math is not a literal FaNumerics constructor")
    fields = {}
    for field in bodies[0].kids:
        name = node_name(field).removeprefix("name=")
        if len(field.kids) == 1 and field.kids[0].kind == "Bool":
            if name in fields:
                fail(f"duplicate numeric policy field {name}")
            fields[name] = node_name(field.kids[0]) == "true"
    if set(fields) != {"base2", "exp_ftz", "approx_div", "div_ftz"}:
        fail("fa_bf16_math does not provide exactly the fixed Bool policy fields")
    return fields


def validate_pairs(src, rows, paired):
    at = place(src)
    for r, s in zip(rows, paired):
        site = at(s.get("site", s["span"][0]))
        if r["at"] != "-" and r["at"] != site:
            fail(f"source span for row {r['id']} `{r['name']}` starts at {site}, recording says {r['at']}")
        if src[s["name_span"][0]:s["name_span"][1]] != s["text"]:
            fail(f"the parser's name span for `{sorted(s['names'])}` holds the wrong text")


def expect_refused(label, action):
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            action()
        except SystemExit:
            return
    raise AssertionError(f"{label} stayed green")


def strategy_controls(src, body, dev, policy, static, rows, paired):
    """Faults over this real recording, including two same-named exp sites."""
    queries = [r for r in rows if r["name"] == "tile_shape"]
    if len(queries) != 1 or queries[0]["lines"]:
        fail("tile_shape must retain exactly one zero IR source call")
    casts = [r for r in rows if r["name"] == "to"]
    if len(casts) != 1 or not casts[0]["lines"]:
        fail("the BF16 probability cast must own real IR")
    wrong = dict(policy, base2=not policy["base2"])
    expect_refused("wrong strategy arm", lambda: pair(static_calls(body, dev, Env(wrong)), rows))
    exp_rows = [i for i, row in enumerate(rows) if row["name"] == "fa_exp"]
    if len(exp_rows) != 2:
        fail("the BF16 instance did not record both base-2 exponentials")
    moved = copy.deepcopy(paired)
    moved[exp_rows[0]] = copy.deepcopy(paired[exp_rows[1]])
    expect_refused("same-name wrong source span", lambda: validate_pairs(src, rows, moved))
    missing = copy.deepcopy(static)
    def drop_call(calls, name):
        return [dict(c, kids=drop_call(c["kids"], name)) for c in calls if name not in c["names"]]
    for name in ["fa_exp", "tile_shape"]:
        expect_refused("missing " + name, lambda: pair(drop_call(static, name), rows))
    unknown = copy.deepcopy(body)
    def spoil(n):
        if n.kind == "FieldAccess" and node_name(n) == "base2":
            n.kids[0].text = "Var unknown_capture"
        for k in n.kids:
            spoil(k)
    unknown = copy.deepcopy(HELPERS["fa_exp"])
    spoil(unknown)
    expect_refused("unknown host condition", lambda: static_calls(unknown, dev, Env(policy)))



def record() -> str:
    src = KERNELS.read_text(encoding="utf-8")
    dev = set(re.findall(r'called\("([a-z_0-9]+)"', DEV.read_text(encoding="utf-8")))
    ran = run_harness(src)
    p = subprocess.run([dawnc(), "parse", str(KERNELS)],
                       capture_output=True, text=True, cwd=ROOT)
    if p.returncode != 0:
        fail("`dawnc parse` failed:\n" + (p.stderr or p.stdout)[-2000:])
    fixed_factory(p.stdout)
    altered = copy.deepcopy(parse_tree(p.stdout, "fa_kernel"))
    lam = next(k for k in altered.kids if k.kind == "Lambda")
    call = next(k for k in lam.kids if k.kind != "LParam")
    call.kids[1], call.kids[2] = call.kids[2], call.kids[1]
    expect_refused("wrong factory forwarding", lambda: validate_factory(altered))
    global HELPERS
    HELPERS = {}
    for name in ["fa_exp", "fa_divide"]:
        helper = parse_tree(p.stdout, name)
        bodies = [k for k in helper.kids if k.kind == "Block"]
        if len(bodies) != 1:
            fail(f"{name} has no unique block body")
        HELPERS[name] = bodies[0]
    dev |= set(HELPERS)
    fn = parse_tree(p.stdout, BODY)
    body = [k for k in fn.kids if k.kind == "Block"]
    if len(body) != 1:
        fail(f"{NAME} is not a function with a block body")
    global SRC
    SRC = src
    static = static_calls(body[0], dev, Env(fixed_policy(p.stdout)))
    rows, head, tail, ops = [], None, None, None
    for line in ran.splitlines():
        w = line.split(" ")
        if w[0] == "call":
            rows.append({"id": int(w[1]), "parent": int(w[2]), "name": w[3], "at": w[4], "lines": w[5:]})
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
    validate_pairs(src, rows, paired)
    strategy_controls(src, body[0], dev, fixed_policy(p.stdout), static, rows, paired)
    print("PASS fresh recording controls: wrong arm, same-name span, missing helper, missing tile_shape, wrong factory forwarding, unknown host branch", file=sys.stderr)
    golden = (GOLDEN / f"{NAME}.mlir").read_text(encoding="utf-8")
    cast_lines = [golden.splitlines()[i - 1] for span in next(r for r in rows if r["name"] == "to")["lines"]
                  for i in range(*map(int, span.split("-")))]
    if len(cast_lines) != 1 or not re.search(r"ftof .*rounding<nearest_even>.*f32.*bf16|ftof .*f32.*bf16.*rounding<nearest_even>", cast_lines[0]):
        fail("reader probability cast must be nearest-even F32 to BF16: " + repr(cast_lines))
    if ran.split("@@ir\n", 1)[1].split("@@end\n", 1)[0] != golden:
        fail("the selected factory recording differs from the full golden text")
    if int(tail.split("-")[1]) - 1 != golden.count("\n"):
        fail(f"the map ends at line {int(tail.split('-')[1]) - 1}, {NAME}.mlir has {golden.count(chr(10))} lines")
    definitions = [fn, parse_tree(p.stdout, "fa_kernel")] + [parse_tree(p.stdout, name) for name in HELPERS]
    first = src[:min(f.lo for f in definitions)].count("\n") + 1
    last = src[:max(f.hi for f in definitions)].count("\n") + 1
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
