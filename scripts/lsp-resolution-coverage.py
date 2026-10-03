#!/usr/bin/env python3
"""Which written names `textDocument/definition` resolves, asserted name by name.

The language server answers hover and definition from one walk that pairs the
parse tree with the checker's typed tree (selfhost/src/lsp/lspq.dawn). A name
the walk has no arm for answers with nothing, or with the type of whatever
expression encloses it, and no gate noticed: selfhost-lsp-diff.sh compares
against the previous release, which had the same holes. References and rename
are built on the same walk (docs/lsp-references-design.md), so a hole there
is a reference rename would miss and a program it would break. T0 of that
design closed the holes this script names; it holds them closed.

Two programs, one per session: a single file (effects, a handler, records, a
trait bound, an alias, named arguments, `var`) and a two-module project (a
whole-module alias, a renamed selective import, qualified types, effects,
constants, constructors and function values). For every probed name the
definition must be one location, at the declaration the test names. For the
names that already answered before T0 the hover must also be byte-identical
to what it was, since T0 only adds answers.

Usage:
  scripts/lsp-resolution-coverage.py [--server CMD...]   positive run (default ./bin/dawn lsp)
  scripts/lsp-resolution-coverage.py --mutants           positive run, then compile each
                                                         mutant from a private selfhost copy
                                                         and require its owning case red

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

SINGLE = """use std/str

effect Env {
  fn lookup(name: String) -> Int
}

type Expr =
  | Num(v: Int)
  | Var(name: String)
  | Add(l: Expr, r: Expr)

type Point = { x: Int, y: Int, label: String }

alias Name = String

trait Shown[T] {
  fn show_it(x: T) -> String
}

impl Shown[Int] {
  fn show_it(x: Int) -> String = "int"
}

const LIMIT: Int = 1024

fn eval(e: Expr) -> Int !Env =
  match e {
    Num(v) -> v
    Var(name) -> lookup(name)
    Add(l, r) -> eval(l) + eval(r)
  }

fn apply_env(f: fn(Int) -> Int !Env, x: Int) -> Int !Env = f(x)

fn labelled[T: Shown](x: T, fallback: Name) -> String = show_it(x) ++ fallback

fn shift(p: Point, dx: Int, dy: Int = 0) -> Point = Point { ..p, x: p.x + dx, y: p.y + dy }

fn px(p: Point) -> Int =
  match p {
    Point { x: first, y, label } -> first + y + str.len(label)
  }

fn norm(p: Point) -> Int = {
  var acc = 0
  acc = acc + p.x * p.x + p.y * p.y
  if acc > LIMIT { LIMIT } else { acc }
}

fn run() -> Int = {
  let e = Add(Var("x"), Num(v: 3))
  with handle Env { lookup(n) => str.len(n) }
  fn local_eval() -> Int !Env = lookup("z")
  let first = eval(e) + local_eval() + apply_env(k => k + lookup("w"), 1)
  let p = shift(Point { x: first, y: 2, label: "p" }, 3, dy: 5)
  norm(p) + px(p) + str.len(labelled(7, "n"))
}

pub fn main() -> Unit !io = {
  println("${run()}")
}
"""

HELPER = """## Doubles.
pub fn double(x: Int) -> Int = x * 2

pub type Shape = Circle(r: Int) | Square(side: Int)

pub const LIMIT: Int = 7

pub effect Ask {
  fn ask() -> Int
}
"""

MAIN = """use std/io
use helper
use helper.{double as twice, Shape, Circle}

fn apply(f: fn(Int) -> Int, x: Int) -> Int = f(x)

fn area(s: Shape) -> Int =
  match s {
    Circle(r) -> r * r
    helper.Square(side) -> side * side
  }

fn area2(s: helper.Shape) -> Int = area(s)

fn asked() -> Int !helper.Ask = helper.ask()

pub fn main() -> Unit !io = {
  let a = helper.double(3)
  let b = apply(helper.double, 4)
  let c = 5 |> helper.double
  let d = 6 |> twice
  let e = 7.twice()
  let g = area2(Circle(2)) + area(helper.Square(3)) + helper.LIMIT
  with handle helper.Ask { ask() => 1 }
  io.println(show(a + b + c + d + e + g + asked()))
}
"""

# (label, needle, delta, file, declaration needle, declaration delta). The
# probed position is `needle` + delta in the document; the definition must be
# one location at `declaration needle` + delta in `file` ("" = the document
# itself, "<module>" = line 0 column 0 of `declaration needle`'s file).
SINGLE_DEFS = [
    ("op call", "lookup(name)", 0, "", "fn lookup", 3),
    ("effect row", "!Env =", 1, "", "effect Env", 7),
    ("effect row in a fn type", "Int !Env, x", 5, "", "effect Env", 7),
    ("local fn effect row", "Int !Env = lookup", 5, "", "effect Env", 7),
    ("with handle effect", "handle Env", 7, "", "effect Env", 7),
    ("handler arm op", "{ lookup(n) =>", 2, "", "fn lookup", 3),
    ("written type in a param", "e: Expr", 3, "", "type Expr", 5),
    ("written type in a field", "l: Expr", 3, "", "type Expr", 5),
    ("written type, return", "-> Point =", 3, "", "type Point", 5),
    ("written alias", "fallback: Name", 10, "", "alias Name", 6),
    ("type parameter use", "x: T,", 3, "", "[T: Shown]", 1),
    ("type parameter declaration", "[T: Shown]", 1, "", "[T: Shown]", 1),
    ("trait bound", "[T: Shown]", 4, "", "trait Shown", 6),
    ("trait parameter use", "x: T) -> String\n}", 3, "", "Shown[T]", 6),
    ("builtin type names no declaration", "fn show_it(x: Int)", 14, "", "", None),
    ("record literal field", "{ x: first, y: 2", 2, "", "{ x: Int", 2),
    ("record pattern field", "{ x: first, y, label }", 2, "", "{ x: Int", 2),
    ("constructor named argument", "Num(v: 3)", 4, "", "Num(v: Int)", 4),
    ("named argument", "dy: 5", 0, "", "dy: Int = 0", 0),
    ("var declaration", "var acc", 4, "", "var acc", 0),
    ("let declaration", "let first", 4, "", "let first", 0),
    ("module alias segment", "str.len(n)", 0, "std/str.dawn", "<module>", 0),
]

PROJECT_DEFS = [
    ("qualified function value", "helper.double, 4", 7, "helper.dawn", "fn double", 3),
    ("piped qualified function value", "|> helper.double", 10, "helper.dawn", "fn double", 3),
    ("renamed import UFCS", "7.twice", 2, "helper.dawn", "fn double", 3),
    ("alias segment of a call", "helper.double(3)", 1, "helper.dawn", "<module>", 0),
    ("alias segment of a value", "helper.double, 4", 1, "helper.dawn", "<module>", 0),
    ("alias segment of a constant", "helper.LIMIT", 1, "helper.dawn", "<module>", 0),
    ("alias segment of a pattern", "helper.Square(side)", 1, "helper.dawn", "<module>", 0),
    ("alias segment of a type", "s: helper.Shape", 4, "helper.dawn", "<module>", 0),
    ("alias segment of a row", "!helper.Ask =", 2, "helper.dawn", "<module>", 0),
    ("imported type in a signature", "s: Shape", 3, "helper.dawn", "type Shape", 5),
    ("qualified type", "s: helper.Shape", 11, "helper.dawn", "type Shape", 5),
    ("qualified effect in a row", "!helper.Ask =", 8, "helper.dawn", "effect Ask", 7),
    ("qualified op call", "helper.ask()", 7, "helper.dawn", "fn ask", 3),
    ("qualified with handle", "handle helper.Ask", 14, "helper.dawn", "effect Ask", 7),
    ("imported effect's arm op", "{ ask() =>", 2, "helper.dawn", "fn ask", 3),
]

# Names that answered before T0, with the hover they gave: T0 only adds
# answers, so these stay byte for byte (the first ```dawn fence).
SINGLE_HOVERS = [
    ("effect declaration", "effect Env", 7, "effect Env"),
    ("op declaration", "fn lookup", 3, "fn lookup(name: String) -> Int !Env"),
    ("constructor call", "Var(\"x\")", 0, "Var(name: String): Expr"),
    ("field access", "p.x + dx", 2, "x: Int"),
    ("punned record pattern field", "y, label }", 0, "y: Int"),
    ("var use", "acc > LIMIT", 0, "var acc: Int"),
    ("const use", "> LIMIT", 2, "const LIMIT: Int = 1024  (0x400)"),
    ("qualified std call", "str.len(n)", 4, "fn len(s: String) -> Int"),
    ("default parameter", "dy: Int = 0", 0, "dy: Int"),
    ("handler arm parameter", "lookup(n) =>", 7, "n: String"),
]

PROJECT_HOVERS = [
    ("qualified call", "helper.double(3)", 7, "fn double(x: Int) -> Int"),
    ("renamed import", "as twice", 3, "fn double(x: Int) -> Int"),
    ("piped renamed import", "|> twice", 3, "fn double(x: Int) -> Int"),
    ("qualified constant", "helper.LIMIT", 7, "const LIMIT: Int = 7"),
    ("qualified constructor", "helper.Square(3)", 7, "Square(side: Int): Shape"),
]

# What the new answers say, for the cases whose text is not obvious from the
# declaration alone.
SINGLE_NEW_HOVERS = [
    ("op call hover", "lookup(name)", 0, "fn lookup(name: String) -> Int !Env"),
    ("written type hover", "e: Expr", 3, "type Expr = Num | Var | Add"),
    ("type parameter hover", "x: T,", 3, "type parameter T"),
    ("effect row hover", "!Env =", 1, "effect Env"),
    ("named argument hover", "dy: 5", 0, "dy: Int"),
    ("var declaration hover", "var acc", 4, "var acc: Int"),
]

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
    return {"line": text.count("\n", 0, i), "character": i - (text.rfind("\n", 0, i) + 1)}


class Session:
    def __init__(self, cmd, cwd, env):
        self.p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.next_id = 0
        self.request("initialize", {"processId": None, "rootUri": None, "capabilities": {}})
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


def check_doc(s, uri, text, defs, hovers, files):
    s.notify("textDocument/didOpen", {"textDocument": {
        "uri": uri, "languageId": "dawn", "version": 1, "text": text}})
    td = {"uri": uri}
    for label, needle, delta, file, decl, ddelta in defs:
        got = s.request("textDocument/definition", {"textDocument": td, "position": position(text, needle, delta)})
        locs = got if isinstance(got, list) else ([got] if got else [])
        if ddelta is None:
            # a builtin names no declaration: the answer is that there is none
            if locs:
                bad(label, "want no definition, got %r" % locs)
            else:
                ok(label)
            continue
        if len(locs) != 1:
            bad(label, "want one definition, got %r" % locs)
            continue
        where = locs[0]["uri"]
        start = locs[0]["range"]["start"]
        got_at = (start["line"], start["character"])
        if file == "":
            want_uri, src = uri, text
        else:
            want_uri, src = None, files.get(file)
        if want_uri is not None and where != want_uri:
            bad(label, "want %s, got %s" % (want_uri, where))
            continue
        if want_uri is None and not where.endswith("/" + file):
            bad(label, "want a location in %s, got %s" % (file, where))
            continue
        if decl == "<module>":
            want_at = (0, 0)
        else:
            p = position(src, decl, ddelta)
            want_at = (p["line"], p["character"])
        if got_at != want_at:
            bad(label, "want %r, got %r in %s" % (want_at, got_at, where))
        else:
            ok("%s -> %s:%d:%d" % (label, file or "doc", want_at[0], want_at[1]))
    for label, needle, delta, want in hovers:
        got = s.request("textDocument/hover", {"textDocument": td, "position": position(text, needle, delta)})
        code = hover_code(got) if got else None
        if code != want:
            bad(label, "want hover %r, got %r" % (want, code))
        else:
            ok("%s: %s" % (label, want))


def contract(server, env):
    work = tempfile.mkdtemp(prefix="lsp-resolution-coverage.")
    try:
        one = os.path.join(work, "one")
        os.makedirs(one)
        s = Session(server, one, env)
        try:
            std_str = os.path.join(ROOT, "std", "str.dawn")
            check_doc(s, "file://" + os.path.join(one, "one.dawn"), SINGLE,
                      SINGLE_DEFS, SINGLE_HOVERS + SINGLE_NEW_HOVERS, {"std/str.dawn": std_str})
        finally:
            s.close()
        src = os.path.join(work, "proj", "src")
        os.makedirs(src)
        with open(os.path.join(src, "helper.dawn"), "w") as f:
            f.write(HELPER)
        main = os.path.join(src, "main.dawn")
        with open(main, "w") as f:
            f.write(MAIN)
        s = Session(server, src, env)
        try:
            check_doc(s, "file://" + main, MAIN, PROJECT_DEFS, PROJECT_HOVERS, {"helper.dawn": HELPER})
        finally:
            s.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- mutants ---------------------------------------------------------------
#
# Each removes one piece of the walk this contract exists for, and must turn
# its owning case red. The anchors are in lsp-resolution-coverage/mutate.py,
# where the preflight proves them before any build; this is (mutant, owner).

MUTATE = os.path.join(ROOT, "scripts", "lsp-resolution-coverage", "mutate.py")

MUTANTS = [
    ('drop-qualified-fn-value', 'qualified function value'),
    ('drop-written-types', 'written type in a param'),
    ('drop-arm-names', 'handler arm op'),
    ('drop-alias-segment', 'alias segment of a call'),
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
    if args[:1] == ["--mutants"]:
        mutants = True
    elif args[:1] == ["--server"]:
        server = args[1:]
    contract(server, env)
    if failures:
        print("\nlsp-resolution-coverage: %d assertion(s) failed" % len(failures), file=sys.stderr)
        return 1
    print("\nlsp-resolution-coverage: positive OK")
    if not mutants:
        return 0
    work = tempfile.mkdtemp(prefix="lsp-resolution-mutants.")
    try:
        for name, owner in MUTANTS:
            cmd = build_mutant(dawn, work, name)
            print("PASS  %s mutant compiles" % name)
            del failures[:]
            contract(cmd, env)
            if owner not in failures:
                print("lsp-resolution-coverage: %s mutant left '%s' green (red: %r)"
                      % (name, owner, failures), file=sys.stderr)
                return 1
            print("PASS  %s mutant turns '%s' red" % (name, owner))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\nlsp-resolution-coverage: OK")
    return 0


sys.exit(main())
