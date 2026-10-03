#!/usr/bin/env python3
"""Which kind `textDocument/semanticTokens` gives each name, asserted token by token.

The language server classifies every name its definition walk resolves
(selfhost/src/lsp/lsptok.dawn, docs/lsp-references-design.md §T1): a type, a
record, a constructor, a trait, an effect and its operations, a constant, a
parameter, a mutable local, a module alias. selfhost-lsp-diff.sh compares
against the previous release, which answered neither request, so it can say
that the reply changed and never whether it is right. This script says it.

Two programs, one per session, the ones scripts/lsp-resolution-coverage.py
probes (a single file, and a two-module project) plus a line whose string
holds characters outside the BMP ahead of names, so a column counted in code
points or bytes instead of UTF-16 units decodes to the wrong text. For each:
the full reply decoded to (text, type, modifiers) must equal the expected
sequence, and a range inside one declaration must answer exactly the tokens
starting in it. The legend must be the one initialize declared, and a document
the server has no analysis for must answer with no tokens.

Usage:
  scripts/lsp-semantic-tokens.py [--server CMD...]   positive run (default ./bin/dawn lsp)
  scripts/lsp-semantic-tokens.py --dump              print the decoded tokens and exit
  scripts/lsp-semantic-tokens.py --mutants           positive run, then compile each mutant
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

fn labelled[T: Shown](x: T, fallback: Name) -> String = show_it(x) ++ fallback

fn shift(p: Point, dx: Int, dy: Int = 0) -> Point = Point { ..p, x: p.x + dx, y: p.y + dy }

fn norm(p: Point) -> Int = {
  var acc = 0
  acc = acc + p.x * p.x + p.y * p.y
  if acc > LIMIT { LIMIT } else { acc }
}

fn run() -> Int = {
  let e = Add(Var("x"), Num(v: 3))
  with handle Env { lookup(n) => str.len(n) }
  fn local_eval() -> Int !Env = lookup("z")
  let first = eval(e) + local_eval() + [1].map(k => k + 1).len()
  let wide = "\U0001F388\U0001F388" ++ str.repeat(SEP, 2)
  let p = shift(Point { x: first, y: 2, label: wide }, 3, dy: 5)
  norm(p) + str.len(labelled(7, "n"))
}

const SEP: String = "n"

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
  let g = area2(Circle(2)) + area(helper.Square(3)) + helper.LIMIT
  with handle helper.Ask { ask() => 1 }
  io.println(show(a + b + c + d + g + asked()))
}
"""

# The expected tokens, (text, type, modifiers) in document order; modifiers
# joined with "+". Filled from --dump and read name by name against
# docs/lsp-references-design.md §T1's table.
SINGLE_TOKENS = [
    ('std', 'namespace', 'defaultLibrary'),
    ('str', 'namespace', 'defaultLibrary'),
    ('Env', 'interface', 'declaration'),
    ('lookup', 'method', 'declaration'),
    ('Expr', 'enum', 'declaration'),
    ('Num', 'enumMember', 'declaration'),
    ('v', 'property', 'declaration'),
    ('Var', 'enumMember', 'declaration'),
    ('name', 'property', 'declaration'),
    ('Add', 'enumMember', 'declaration'),
    ('l', 'property', 'declaration'),
    ('Expr', 'enum', ''),
    ('r', 'property', 'declaration'),
    ('Expr', 'enum', ''),
    ('Point', 'struct', 'declaration'),
    ('x', 'property', 'declaration'),
    ('y', 'property', 'declaration'),
    ('label', 'property', 'declaration'),
    ('Name', 'type', 'declaration'),
    ('Shown', 'interface', 'declaration'),
    ('T', 'typeParameter', 'declaration'),
    ('show_it', 'method', 'declaration'),
    ('T', 'typeParameter', ''),
    ('Shown', 'interface', ''),
    ('show_it', 'method', 'declaration'),
    ('x', 'parameter', 'declaration'),
    ('LIMIT', 'variable', 'declaration+readonly'),
    ('eval', 'function', 'declaration'),
    ('e', 'parameter', 'declaration'),
    ('Expr', 'enum', ''),
    ('Env', 'interface', ''),
    ('e', 'parameter', ''),
    ('Num', 'enumMember', ''),
    ('v', 'variable', 'declaration'),
    ('v', 'variable', ''),
    ('Var', 'enumMember', ''),
    ('name', 'variable', 'declaration'),
    ('lookup', 'method', ''),
    ('Add', 'enumMember', ''),
    ('l', 'variable', 'declaration'),
    ('r', 'variable', 'declaration'),
    ('eval', 'function', ''),
    ('l', 'variable', ''),
    ('eval', 'function', ''),
    ('r', 'variable', ''),
    ('labelled', 'function', 'declaration'),
    ('T', 'typeParameter', 'declaration'),
    ('Shown', 'interface', ''),
    ('x', 'parameter', 'declaration'),
    ('T', 'typeParameter', ''),
    ('fallback', 'parameter', 'declaration'),
    ('Name', 'type', ''),
    ('show_it', 'method', ''),
    ('x', 'parameter', ''),
    ('fallback', 'parameter', ''),
    ('shift', 'function', 'declaration'),
    ('p', 'parameter', 'declaration'),
    ('Point', 'struct', ''),
    ('dx', 'parameter', 'declaration'),
    ('dy', 'parameter', 'declaration'),
    ('Point', 'struct', ''),
    ('Point', 'struct', ''),
    ('p', 'parameter', ''),
    ('x', 'property', ''),
    ('p', 'parameter', ''),
    ('x', 'property', ''),
    ('dx', 'parameter', ''),
    ('y', 'property', ''),
    ('p', 'parameter', ''),
    ('y', 'property', ''),
    ('dy', 'parameter', ''),
    ('norm', 'function', 'declaration'),
    ('p', 'parameter', 'declaration'),
    ('Point', 'struct', ''),
    ('acc', 'variable', 'declaration+mutable'),
    ('acc', 'variable', 'mutable'),
    ('acc', 'variable', 'mutable'),
    ('p', 'parameter', ''),
    ('x', 'property', ''),
    ('p', 'parameter', ''),
    ('x', 'property', ''),
    ('p', 'parameter', ''),
    ('y', 'property', ''),
    ('p', 'parameter', ''),
    ('y', 'property', ''),
    ('acc', 'variable', 'mutable'),
    ('LIMIT', 'variable', 'readonly'),
    ('LIMIT', 'variable', 'readonly'),
    ('acc', 'variable', 'mutable'),
    ('run', 'function', 'declaration'),
    ('e', 'variable', 'declaration'),
    ('Add', 'enumMember', ''),
    ('Var', 'enumMember', ''),
    ('Num', 'enumMember', ''),
    ('v', 'property', ''),
    ('Env', 'interface', ''),
    ('lookup', 'method', ''),
    ('n', 'parameter', 'declaration'),
    ('str', 'namespace', 'defaultLibrary'),
    ('len', 'function', 'defaultLibrary'),
    ('n', 'parameter', ''),
    ('local_eval', 'function', 'declaration'),
    ('Env', 'interface', ''),
    ('lookup', 'method', ''),
    ('first', 'variable', 'declaration'),
    ('eval', 'function', ''),
    ('e', 'variable', ''),
    ('local_eval', 'function', ''),
    ('map', 'function', 'defaultLibrary'),
    ('k', 'parameter', 'declaration'),
    ('k', 'parameter', ''),
    ('wide', 'variable', 'declaration'),
    ('str', 'namespace', 'defaultLibrary'),
    ('repeat', 'function', 'defaultLibrary'),
    ('SEP', 'variable', 'readonly'),
    ('p', 'variable', 'declaration'),
    ('shift', 'function', ''),
    ('Point', 'struct', ''),
    ('x', 'property', ''),
    ('first', 'variable', ''),
    ('y', 'property', ''),
    ('label', 'property', ''),
    ('wide', 'variable', ''),
    ('dy', 'parameter', ''),
    ('norm', 'function', ''),
    ('p', 'variable', ''),
    ('str', 'namespace', 'defaultLibrary'),
    ('len', 'function', 'defaultLibrary'),
    ('labelled', 'function', ''),
    ('SEP', 'variable', 'declaration+readonly'),
    ('main', 'function', 'declaration'),
    ('println', 'function', 'defaultLibrary'),
    ('run', 'function', ''),
]
PROJECT_TOKENS = [
    ('std', 'namespace', 'defaultLibrary'),
    ('io', 'namespace', 'defaultLibrary'),
    ('helper', 'namespace', ''),
    ('helper', 'namespace', ''),
    ('double', 'function', ''),
    ('twice', 'function', ''),
    ('Shape', 'enum', ''),
    ('Circle', 'enumMember', ''),
    ('apply', 'function', 'declaration'),
    ('f', 'parameter', 'declaration'),
    ('x', 'parameter', 'declaration'),
    ('f', 'parameter', ''),
    ('x', 'parameter', ''),
    ('area', 'function', 'declaration'),
    ('s', 'parameter', 'declaration'),
    ('Shape', 'enum', ''),
    ('s', 'parameter', ''),
    ('Circle', 'enumMember', ''),
    ('r', 'variable', 'declaration'),
    ('r', 'variable', ''),
    ('r', 'variable', ''),
    ('helper', 'namespace', ''),
    ('Square', 'enumMember', ''),
    ('side', 'variable', 'declaration'),
    ('side', 'variable', ''),
    ('side', 'variable', ''),
    ('area2', 'function', 'declaration'),
    ('s', 'parameter', 'declaration'),
    ('helper', 'namespace', ''),
    ('Shape', 'enum', ''),
    ('area', 'function', ''),
    ('s', 'parameter', ''),
    ('asked', 'function', 'declaration'),
    ('helper', 'namespace', ''),
    ('Ask', 'interface', ''),
    ('helper', 'namespace', ''),
    ('ask', 'method', ''),
    ('main', 'function', 'declaration'),
    ('a', 'variable', 'declaration'),
    ('helper', 'namespace', ''),
    ('double', 'function', ''),
    ('b', 'variable', 'declaration'),
    ('apply', 'function', ''),
    ('helper', 'namespace', ''),
    ('double', 'function', ''),
    ('c', 'variable', 'declaration'),
    ('helper', 'namespace', ''),
    ('double', 'function', ''),
    ('d', 'variable', 'declaration'),
    ('twice', 'function', ''),
    ('g', 'variable', 'declaration'),
    ('area2', 'function', ''),
    ('Circle', 'enumMember', ''),
    ('area', 'function', ''),
    ('helper', 'namespace', ''),
    ('Square', 'enumMember', ''),
    ('helper', 'namespace', ''),
    ('LIMIT', 'variable', 'readonly'),
    ('helper', 'namespace', ''),
    ('Ask', 'interface', ''),
    ('ask', 'method', ''),
    ('io', 'namespace', 'defaultLibrary'),
    ('println', 'function', 'defaultLibrary'),
    ('a', 'variable', ''),
    ('b', 'variable', ''),
    ('c', 'variable', ''),
    ('d', 'variable', ''),
    ('g', 'variable', ''),
    ('asked', 'function', ''),
]

# A range inside one declaration: (label, start needle, end needle, expected
# texts). The range runs from the start of the first needle to the start of
# the second; only tokens starting inside it answer.
SINGLE_RANGES = [
    ("range inside norm", "  acc = acc + p.x", "  if acc > LIMIT", [
        ('acc', 'variable', 'mutable'),
        ('acc', 'variable', 'mutable'),
        ('p', 'parameter', ''),
        ('x', 'property', ''),
        ('p', 'parameter', ''),
        ('x', 'property', ''),
        ('p', 'parameter', ''),
        ('y', 'property', ''),
        ('p', 'parameter', ''),
        ('y', 'property', ''),
    ]),
    ("range after a wide string", "str.repeat(SEP", "\n  let p = shift", [
        ('str', 'namespace', 'defaultLibrary'),
        ('repeat', 'function', 'defaultLibrary'),
        ('SEP', 'variable', 'readonly'),
    ]),
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


def utf16_position(text, index):
    """LSP position of code-point index `index`: line, UTF-16 column."""
    line = text.count("\n", 0, index)
    start = text.rfind("\n", 0, index) + 1
    return {"line": line, "character": len(text[start:index].encode("utf-16-le")) // 2}


class Session:
    def __init__(self, cmd, cwd, env):
        self.p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.next_id = 0
        init = self.request("initialize", {"processId": None, "rootUri": None, "capabilities": {}})
        self.provider = (init or {}).get("capabilities", {}).get("semanticTokensProvider")
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


def decode(text, data, legend):
    """The reply's integers as (text, type, modifiers), columns read as UTF-16."""
    types, mods = legend["tokenTypes"], legend["tokenModifiers"]
    lines = text.split("\n")
    out = []
    line = col = 0
    for i in range(0, len(data), 5):
        dl, dc, length, ty, bits = data[i:i + 5]
        line += dl
        col = col + dc if dl == 0 else dc
        units = lines[line].encode("utf-16-le") if line < len(lines) else b""
        name = units[2 * col:2 * (col + length)].decode("utf-16-le", errors="replace")
        names = [m for b, m in enumerate(mods) if bits & (1 << b)]
        out.append((name, types[ty] if ty < len(types) else "?%d" % ty, "+".join(names)))
    return out


def tokens(s, uri, text, rng=None):
    td = {"uri": uri}
    if rng is None:
        got = s.request("textDocument/semanticTokens/full", {"textDocument": td})
    else:
        got = s.request("textDocument/semanticTokens/range", {"textDocument": td, "range": rng})
    return decode(text, (got or {}).get("data", []), s.provider["legend"])


def compare(label, want, got):
    if want == got:
        ok("%s (%d tokens)" % (label, len(got)))
        return
    first = next((i for i in range(min(len(want), len(got))) if want[i] != got[i]), min(len(want), len(got)))
    bad(label, "first difference at token %d: want %r, got %r (%d vs %d tokens)"
        % (first, want[first] if first < len(want) else None,
           got[first] if first < len(got) else None, len(want), len(got)))


def check_doc(s, uri, text, label, want, ranges, dump):
    s.notify("textDocument/didOpen", {"textDocument": {
        "uri": uri, "languageId": "dawn", "version": 1, "text": text}})
    got = tokens(s, uri, text)
    if dump:
        print("%s = [" % label)
        for t in got:
            print("    %r," % (t,))
        print("]")
        return
    compare(label, want, got)
    for rlabel, start, end, rwant in ranges:
        lo, hi = text.index(start), text.index(end)
        rng = {"start": utf16_position(text, lo), "end": utf16_position(text, hi)}
        compare(rlabel, rwant, tokens(s, uri, text, rng))


def contract(server, env, dump=False):
    work = tempfile.mkdtemp(prefix="lsp-semantic-tokens.")
    try:
        one = os.path.join(work, "one")
        os.makedirs(one)
        s = Session(server, one, env)
        try:
            legend = (s.provider or {}).get("legend")
            if not dump:
                if not s.provider or not s.provider.get("full") or not s.provider.get("range") or "delta" in s.provider:
                    bad("provider", "want full and range without delta, got %r" % s.provider)
                elif not legend or "enumMember" not in legend.get("tokenTypes", []):
                    bad("provider", "legend %r" % legend)
                else:
                    ok("provider: full + range, %d types, %d modifiers"
                       % (len(legend["tokenTypes"]), len(legend["tokenModifiers"])))
                # a document the server holds no analysis for: no tokens, no error
                missing = s.request("textDocument/semanticTokens/full",
                                    {"textDocument": {"uri": "file://" + os.path.join(one, "nowhere.dawn")}})
                if missing != {"data": []}:
                    bad("no analysis", "want {'data': []}, got %r" % (missing,))
                else:
                    ok("no analysis: empty data")
            check_doc(s, "file://" + os.path.join(one, "one.dawn"), SINGLE, "SINGLE_TOKENS",
                      SINGLE_TOKENS, SINGLE_RANGES, dump)
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
            check_doc(s, "file://" + main, MAIN, "PROJECT_TOKENS", PROJECT_TOKENS, [], dump)
        finally:
            s.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- mutants ---------------------------------------------------------------
#
# Each breaks one decision this contract exists for and must turn its owning
# case red. The anchors are in lsp-semantic-tokens/mutate.py, where the
# preflight proves them before any build; this is (mutant, owner).

MUTATE = os.path.join(ROOT, "scripts", "lsp-semantic-tokens", "mutate.py")

MUTANTS = [
    ('const-as-type', 'SINGLE_TOKENS'),
    ('drop-mutable', 'SINGLE_TOKENS'),
    ('range-unclipped', 'range inside norm'),
    ('columns-in-bytes', 'SINGLE_TOKENS'),
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
        print("\nlsp-semantic-tokens: %d assertion(s) failed" % len(failures), file=sys.stderr)
        return 1
    print("\nlsp-semantic-tokens: positive OK")
    if not mutants:
        return 0
    work = tempfile.mkdtemp(prefix="lsp-semantic-tokens-mutants.")
    try:
        for name, owner in MUTANTS:
            cmd = build_mutant(dawn, work, name)
            print("PASS  %s mutant compiles" % name)
            del failures[:]
            contract(cmd, env)
            if owner not in failures:
                print("lsp-semantic-tokens: %s mutant left '%s' green (red: %r)"
                      % (name, owner, failures), file=sys.stderr)
                return 1
            print("PASS  %s mutant turns '%s' red" % (name, owner))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\nlsp-semantic-tokens: OK")
    return 0


sys.exit(main())
