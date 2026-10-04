#!/usr/bin/env python3
"""Which names `textDocument/references` and `documentHighlight` return, asserted name by name.

The language server answers both from one list: every name in the document
that resolves to the declaration the cursor's name resolves to
(selfhost/src/lsp/lspref.dawn, docs/lsp-references-design.md §R1). The key is
the declaration, not the spelling, so each case below that a text search
would get right is paired with one it would get wrong: a `let` shadowing the
parameter of its name, a parameter named like a top-level function.
selfhost-lsp-diff.sh compares against the previous release, which answers
neither request, so it can say that the reply changed and never whether it
is right. This script says it.

One program, one session. Each case is a cursor and the exact set of
occurrences, as `line:column text` (line from 1, column in UTF-16 units from
0, the text the range covers): a local, a parameter, a named argument, a
record pun from both sides (the field and the local it binds or reads), a
trait method (its impl's method counts), an operation (its handler arm
counts), a constructor, a field, and a name passed to a call whose arguments
the checker rearranged (a default left out, named arguments out of order),
which the walk used to leave unresolved. A reference request with
`includeDeclaration: false` must leave the declaration out; documentHighlight
must mark a declaration and an assignment target as writes (3) and every
other occurrence as a read (2). Definition and hover at a call of a
parameter must name the parameter, not the top-level function of its name.

Usage:
  scripts/lsp-references.py [--server CMD...]   positive run (default ./bin/dawn lsp)
  scripts/lsp-references.py --dump              print every case's reply and exit
  scripts/lsp-references.py --mutants           positive run, then compile each mutant
                                                from a private selfhost copy and require
                                                its owning case red

A mutant is accepted as red only when its owning assertion is among the
failures; a build failure is not a negative control and fails the run.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

from lsp_hover import hover_code

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROGRAM = """use std/str

effect Env {
  fn lookup(name: String) -> Int
}

type Expr =
  | Num(v: Int)
  | Add(l: Expr, r: Expr)

type Point = { x: Int, y: Int }

trait Area[T] {
  fn area(s: T) -> Int
}

impl Area[Point] {
  fn area(s: Point) -> Int = s.x * s.y
}

fn eval(e: Expr) -> Int =
  match e {
    Num(v) -> v
    Add(l, r) -> eval(l) + eval(r)
  }

fn twice(n: Int) -> Int = n + n

fn shift(p: Point, dx: Int, dy: Int = 0) -> Point = Point { x: p.x + dx, y: p.y + dy }

fn origin(x: Int) -> Point = {
  let y = x + 1
  Point { x, y }
}

fn first(p: Point) -> Int =
  match p {
    Point { x, y: _ } -> x
  }

fn apply(twice: fn(Int) -> Int, n: Int) -> Int = twice(n) + twice(n + 1)

fn shadow(n: Int) -> Int = {
  let n = n + 1
  n * 2
}

fn asked() -> Int !Env = lookup("a") + lookup("b")

fn run() -> Int = {
  with handle Env { lookup(k) => str.len(k) }
  let total = asked() + eval(Add(Num(1), Num(v: 2)))
  var acc = 0
  acc = acc + total
  acc = acc + area(shift(origin(1), 2, dy: 3)) + first(origin(acc))
  acc + twice(acc) + apply(twice, acc) + shadow(acc)
}

pub fn main() -> Unit !io = {
  println("${run()}")
}

fn moved(q: Point) -> Point = shift(q, 1)

fn moved2(q: Point) -> Point = q.shift(dy: 2, dx: q.y)
"""

# (label, needle, delta, includeDeclaration, expected occurrences). The cursor
# is `needle` + delta in the program.
REFERENCES = [
    ("local: a var, its assignments and reads", "var acc", 4, True, [
        "53:6 acc", "54:2 acc", "54:8 acc", "55:2 acc", "55:8 acc", "55:62 acc",
        "56:2 acc", "56:14 acc", "56:34 acc", "56:48 acc"]),
    ("local: a let read by a record pun", "let y = x", 4, True, ["32:6 y", "33:13 y"]),
    ("parameter: declaration, use, named argument", "dy: Int = 0", 0, True,
     ["29:28 dy", "29:82 dy", "55:39 dy", "65:39 dy"]),
    ("parameter: passed to a call that leaves a default out", "moved(q", 6, True,
     ["63:9 q", "63:36 q"]),
    ("parameter: a method call with its named arguments out of order", "moved2(q", 7, True,
     ["65:10 q", "65:31 q", "65:50 q"]),
    ("named argument: a method call's, out of order", "dx: q.y", 0, True,
     ["29:19 dx", "29:69 dx", "65:46 dx"]),
    ("named argument: the parameter it names", "dy: 3", 0, True,
     ["29:28 dy", "29:82 dy", "55:39 dy", "65:39 dy"]),
    ("pun, field side: puns in a construction and a pattern", "x: Int, y", 0, True,
     ["11:15 x", "18:31 x", "29:60 x", "29:65 x", "33:10 x", "38:12 x"]),
    ("pun, local side: the parameter a construction pun reads", "origin(x: Int", 7, True,
     ["31:10 x", "32:10 x", "33:10 x"]),
    ("pun, local side: the binder a pattern pun declares", "Point { x, y: _ }", 8, True,
     ["38:12 x", "38:25 x"]),
    ("trait method: declaration, impl method, call", "fn area(s: T", 3, True,
     ["14:5 area", "18:5 area", "55:14 area"]),
    ("operation: declaration, calls, handler arm", "lookup(k)", 0, True,
     ["4:5 lookup", "48:25 lookup", "48:39 lookup", "51:20 lookup"]),
    ("constructor: declaration, pattern, constructions", "Num(v: Int)", 0, True,
     ["8:4 Num", "23:4 Num", "52:33 Num", "52:41 Num"]),
    ("field: declaration and the named constructor argument", "Num(v: 2)", 4, True,
     ["8:8 v", "52:45 v"]),
    # the negatives: one spelling, two declarations
    ("shadowed: the let, not the parameter it shadows", "let n = n", 4, True,
     ["44:6 n", "45:2 n"]),
    ("shadowed: the parameter, not the let shadowing it", "let n = n", 8, True,
     ["43:10 n", "44:10 n"]),
    ("namesake: the parameter called like a function", "twice(n) + ", 0, True,
     ["41:9 twice", "41:49 twice", "41:60 twice"]),
    ("namesake: the function, not the parameter", "fn twice", 3, True,
     ["27:3 twice", "56:8 twice", "56:27 twice"]),
    ("includeDeclaration false: the declaration left out", "fn twice", 3, False,
     ["56:8 twice", "56:27 twice"]),
    ("no declaration: a builtin type", "-> Unit", 3, True, []),
]

# (label, needle, delta, expected occurrences with their kind)
HIGHLIGHTS = [
    ("highlight: declaration and assignments write, reads read", "acc = acc + total", 0, [
        "53:6 acc/3", "54:2 acc/3", "54:8 acc/2", "55:2 acc/3", "55:8 acc/2", "55:62 acc/2",
        "56:2 acc/2", "56:14 acc/2", "56:34 acc/2", "56:48 acc/2"]),
    ("highlight: a field, its puns read", "x: Int, y", 0, [
        "11:15 x/3", "18:31 x/2", "29:60 x/2", "29:65 x/2", "33:10 x/2", "38:12 x/2"]),
]

# Definition and hover at a call of a parameter that shares its name with a
# top-level function: the parameter (docs/lsp-references-design.md §T1.6).
LOCAL_CALL = ("local call: definition and hover name the parameter", "twice(n) + ", 0,
              "41:9 twice", "let twice: fn(Int) -> Int")

failures = []


def ok(name):
    print("PASS  %s" % name)


def bad(name, detail):
    print("FAIL: %s\n      %s" % (name, detail))
    failures.append(name)


def frame(obj):
    body = json.dumps(obj).encode()
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def read_msg(f):
    n = None
    while True:
        line = f.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        k, _, v = line.decode().partition(":")
        if k.strip().lower() == "content-length":
            n = int(v.strip())
    if n is None:
        return None
    return json.loads(f.read(n))


def position(text, needle, delta):
    i = text.index(needle) + delta
    line = text.count("\n", 0, i)
    start = text.rfind("\n", 0, i) + 1
    return {"line": line, "character": len(text[start:i].encode("utf-16-le")) // 2}


class Session:
    def __init__(self, cmd, cwd, env):
        self.p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.next_id = 0
        init = self.request("initialize", {"processId": None, "rootUri": None, "capabilities": {}})
        self.capabilities = (init or {}).get("capabilities", {})
        self.notify("initialized", {})

    def send(self, obj):
        self.p.stdin.write(frame(obj))
        self.p.stdin.flush()

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method, params):
        self.next_id += 1
        mine = self.next_id
        self.send({"jsonrpc": "2.0", "id": mine, "method": method, "params": params})
        while True:
            msg = read_msg(self.p.stdout)
            if msg is None:
                raise RuntimeError("server closed while waiting for %s" % method)
            if msg.get("id") == mine and "method" not in msg:
                return msg.get("result")

    def close(self):
        try:
            self.request("shutdown", None)
            self.notify("exit", None)
            self.p.stdin.close()
            self.p.wait(timeout=30)
        except Exception:
            self.p.kill()


def shown(text, uri, item, kind=False):
    """`line:column text` of a Location or DocumentHighlight, `/kind` appended."""
    if "uri" in item and item["uri"] != uri:
        return "elsewhere:" + item["uri"]
    a, b = item["range"]["start"], item["range"]["end"]
    units = text.split("\n")[a["line"]].encode("utf-16-le")
    name = units[2 * a["character"]:2 * b["character"]].decode("utf-16-le", errors="replace")
    if b["line"] != a["line"]:
        name += "..."
    out = "%d:%d %s" % (a["line"] + 1, a["character"], name)
    if kind:
        out += "/%s" % item.get("kind")
    return out


def compare(label, want, got):
    if want == got:
        ok("%s (%d)" % (label, len(got)))
    else:
        bad(label, "want %r\n      got  %r" % (want, got))


def contract(server, env, dump=False):
    work = tempfile.mkdtemp(prefix="lsp-references.")
    try:
        s = Session(server, work, env)
        try:
            if not dump:
                caps = s.capabilities
                if caps.get("referencesProvider") is not True or caps.get("documentHighlightProvider") is not True:
                    bad("capabilities", "want referencesProvider and documentHighlightProvider, got %r"
                        % {k: caps.get(k) for k in ("referencesProvider", "documentHighlightProvider")})
                else:
                    ok("capabilities: references and documentHighlight")
            uri = "file://" + os.path.join(work, "refs.dawn")
            td = {"uri": uri}
            s.notify("textDocument/didOpen", {"textDocument": {
                "uri": uri, "languageId": "dawn", "version": 1, "text": PROGRAM}})
            for label, needle, delta, with_decl, want in REFERENCES:
                got = s.request("textDocument/references", {
                    "textDocument": td, "position": position(PROGRAM, needle, delta),
                    "context": {"includeDeclaration": with_decl}})
                got = [shown(PROGRAM, uri, x) for x in (got or [])]
                if dump:
                    print("%s: %r" % (label, got))
                else:
                    compare(label, want, got)
            for label, needle, delta, want in HIGHLIGHTS:
                got = s.request("textDocument/documentHighlight", {
                    "textDocument": td, "position": position(PROGRAM, needle, delta)})
                got = [shown(PROGRAM, uri, x, kind=True) for x in (got or [])]
                if dump:
                    print("%s: %r" % (label, got))
                else:
                    compare(label, want, got)
            label, needle, delta, want_def, want_hover = LOCAL_CALL
            at = {"textDocument": td, "position": position(PROGRAM, needle, delta)}
            defs = [shown(PROGRAM, uri, x) for x in (s.request("textDocument/definition", at) or [])]
            hover = hover_code(s.request("textDocument/hover", at))
            if dump:
                print("%s: %r %r" % (label, defs, hover))
            else:
                compare(label, [want_def, want_hover], [defs[0] if len(defs) == 1 else defs, hover])
            # a document the server holds no analysis for: no occurrences
            missing = {"uri": "file://" + os.path.join(work, "nowhere.dawn")}
            pos0 = {"line": 0, "character": 0}
            got = (s.request("textDocument/references", {"textDocument": missing, "position": pos0,
                                                          "context": {"includeDeclaration": True}}),
                   s.request("textDocument/documentHighlight", {"textDocument": missing, "position": pos0}))
            if not dump:
                compare("no analysis: empty replies", ([], []), got)
        finally:
            s.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- mutants ---------------------------------------------------------------
#
# Each breaks one decision this contract exists for and must turn its owning
# case red. The anchors are in lsp-references/mutate.py, where the preflight
# proves them before any build; this is (mutant, owner).

MUTATE = os.path.join(ROOT, "scripts", "lsp-references", "mutate.py")

MUTANTS = [
    ('match-by-name', 'shadowed: the let, not the parameter it shadows'),
    ('drop-declaration', 'trait method: declaration, impl method, call'),
    ('pun-one-way', 'pun, field side: puns in a construction and a pattern'),
    ('local-call-by-name', 'local call: definition and hover name the parameter'),
]


def build_mutant(dawn, work, name):
    d = os.path.join(work, name)
    os.makedirs(d)
    shutil.copytree(os.path.join(ROOT, "selfhost"), os.path.join(d, "selfhost"))
    os.symlink(os.path.join(ROOT, "packages"), os.path.join(d, "packages"))
    os.symlink(os.path.join(ROOT, "compiler-plan"), os.path.join(d, "compiler-plan"))
    subprocess.run([sys.executable, MUTATE, name, d], check=True)
    jar = os.path.join(d, "compiler.jar")
    r = subprocess.run([dawn, "build", os.path.join(d, "selfhost"), "-o", jar],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit("%s: mutant did not compile" % name)
    return ["java", "-Xss512m", "-Xmx2g", "-jar", jar, "lsp"]


def main():
    args = sys.argv[1:]
    dawn = os.path.join(ROOT, "bin", "dawn")
    env = dict(os.environ)
    env.setdefault("DAWN_STD", os.path.join(ROOT, "std"))
    server = [dawn, "lsp"]
    mutants = False
    if args[:1] == ["--dump"]:
        contract(server, env, dump=True)
        return 0
    if args[:1] == ["--mutants"]:
        mutants = True
    elif args[:1] == ["--server"]:
        server = args[1:]
    contract(server, env)
    if failures:
        print("\nlsp-references: %d assertion(s) failed" % len(failures), file=sys.stderr)
        return 1
    print("\nlsp-references: positive OK")
    if not mutants:
        return 0
    work = tempfile.mkdtemp(prefix="lsp-references-mutants.")
    try:
        for name, owner in MUTANTS:
            cmd = build_mutant(dawn, work, name)
            print("PASS  %s mutant compiles" % name)
            del failures[:]
            contract(cmd, env)
            if owner not in failures:
                print("lsp-references: %s mutant left '%s' green (red: %r)"
                      % (name, owner, failures), file=sys.stderr)
                return 1
            print("PASS  %s mutant turns '%s' red" % (name, owner))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\nlsp-references: OK")
    return 0


sys.exit(main())
