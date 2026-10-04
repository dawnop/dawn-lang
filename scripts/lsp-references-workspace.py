#!/usr/bin/env python3
"""Which names `textDocument/references` returns across a project, asserted name by name.

A project document's references come from every module of the project, not
only the open ones (selfhost/src/lsp/server.dawn `workspace_references`,
docs/lsp-references-design.md §R2): the requesting document answers from its
own walk, every other module from an index the server keeps beside each
module's analysis step. scripts/lsp-references.py holds the single-document
answer (§R1); this script holds what crosses files.

Two projects, one session each. In both, a function declared in one module is
named from another in every way a name crosses a module: the import list, a
qualified call, a qualified function value, a pipe into a qualified function,
and a call through the import. The same set must come back from each of
those positions and from the declaration itself, as `file line:column text`
(line from 1, column in UTF-16 units). The three-module project adds a module
no open document imports, whose uses must be in the set too. Then the
declaring module is edited above the declaration, and the set must follow it
to its new line, in the module no open document imports as well: the index
holds positions in other files, and an edit there moves them. The tree also
holds a module with a type error that nothing imports: the references program
checks it, and no diagnostic may name it, because diagnostics come from the
open documents' import closure, which the rest of the tree must stay off.

Usage:
  scripts/lsp-references-workspace.py [--server CMD...]   positive run (default ./bin/dawn lsp)
  scripts/lsp-references-workspace.py --dump              print every case's reply and exit
  scripts/lsp-references-workspace.py --mutants           positive run, then compile each mutant
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

# ---- the two-module project: main imports helper --------------------------

TWO = {
    "helper.dawn": """## Doubles a number.
pub fn double(n: Int) -> Int = n * 2

pub fn quad(n: Int) -> Int = double(double(n))
""",
    "main.dawn": """use helper
use helper.{double}

fn apply(f: fn(Int) -> Int, x: Int) -> Int = f(x)

pub fn main() -> Unit !io = {
  let a = helper.double(1)
  let b = apply(helper.double, 2)
  let c = 3 |> helper.double
  let d = double(4)
  println("${a + b + c + d}")
}
""",
}

TWO_ALL = [
    "helper.dawn 2:7 double", "helper.dawn 4:29 double", "helper.dawn 4:36 double",
    "main.dawn 2:12 double", "main.dawn 7:17 double", "main.dawn 8:23 double",
    "main.dawn 9:22 double", "main.dawn 10:10 double",
]

# ---- the three-module project: main and lone import base; nothing imports lone

THREE = {
    "base.dawn": """pub fn pad(n: Int) -> Int = n + 0

## Scales a number.
pub fn scale(n: Int) -> Int = n * 3
""",
    "main.dawn": """use base
use base.{scale}

fn apply(f: fn(Int) -> Int, x: Int) -> Int = f(x)

pub fn main() -> Unit !io = {
  let a = base.scale(1)
  let b = apply(base.scale, 2)
  let c = 3 |> base.scale
  let d = scale(4)
  println("${a + b + c + d}")
}
""",
    "lone.dawn": """use base
use base.{scale}

pub fn lone(n: Int) -> Int = base.scale(n) + (n |> scale)
""",
    # imported by nothing, and wrong: the references program checks it, the
    # diagnostics come from what the open documents import and never name it
    "broken.dawn": """pub fn broken() -> Int = "not an int"
""",
}

THREE_ALL = [
    "base.dawn 4:7 scale",
    "lone.dawn 2:10 scale", "lone.dawn 4:34 scale", "lone.dawn 4:51 scale",
    "main.dawn 2:10 scale", "main.dawn 7:15 scale", "main.dawn 8:21 scale",
    "main.dawn 9:20 scale", "main.dawn 10:10 scale",
]

# `pad`'s body split over two lines: nothing base exports changes, so lone's
# analysis step is reused, and `scale` moves down one line under it
BASE_EDITED = THREE["base.dawn"].replace("n + 0\n", "n +\n  0\n")
THREE_EDITED = ["base.dawn 5:7 scale"] + THREE_ALL[1:]

# (label, file, needle, delta) of each position the set is asked from in main
FROM_MAIN = {
    "two": [
        ("import list", "{double}", 1),
        ("qualified call", "helper.double(1)", 7),
        ("qualified function value", "helper.double, 2", 7),
        ("pipe into a qualified function", "|> helper.double", 10),
        ("call through the import", "double(4)", 0),
    ],
    "three": [
        ("import list", "{scale}", 1),
        ("qualified call", "base.scale(1)", 5),
        ("qualified function value", "base.scale, 2", 5),
        ("pipe into a qualified function", "|> base.scale", 8),
        ("call through the import", "scale(4)", 0),
    ],
}

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
        self.published = set()
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
            if msg.get("method") == "textDocument/publishDiagnostics" and msg["params"].get("diagnostics"):
                self.published.add(msg["params"]["uri"])
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


class Project:
    """A project on disk and the texts the server should be reading."""

    def __init__(self, work, name, files):
        self.root = os.path.join(work, name)
        self.src = os.path.join(self.root, "src")
        os.makedirs(self.src)
        with open(os.path.join(self.root, "dawn.toml"), "w") as f:
            f.write('schema = 1\nname = "%s"\n' % name)
        self.texts = dict(files)
        for base, text in files.items():
            with open(os.path.join(self.src, base), "w") as f:
                f.write(text)

    def uri(self, base):
        return "file://" + os.path.join(self.src, base)

    def shown(self, item):
        """`file line:column text` of a Location."""
        uri = item.get("uri", "")
        prefix = "file://" + self.src + "/"
        if not uri.startswith(prefix):
            return "elsewhere:" + uri
        base = uri[len(prefix):]
        a, b = item["range"]["start"], item["range"]["end"]
        units = self.texts[base].split("\n")[a["line"]].encode("utf-16-le")
        name = units[2 * a["character"]:2 * b["character"]].decode("utf-16-le", errors="replace")
        if b["line"] != a["line"]:
            name += "..."
        return "%s %d:%d %s" % (base, a["line"] + 1, a["character"], name)


def compare(label, want, got):
    if want == got:
        ok("%s (%d)" % (label, len(got)))
    else:
        bad(label, "want %r\n      got  %r" % (want, got))


def references(s, proj, base, needle, delta, with_decl=True):
    text = proj.texts[base]
    got = s.request("textDocument/references", {
        "textDocument": {"uri": proj.uri(base)}, "position": position(text, needle, delta),
        "context": {"includeDeclaration": with_decl}})
    return sorted(proj.shown(x) for x in (got or []))


def open_doc(s, proj, base):
    s.notify("textDocument/didOpen", {"textDocument": {
        "uri": proj.uri(base), "languageId": "dawn", "version": 1, "text": proj.texts[base]}})


def ask(s, proj, label, base, needle, delta, want, dump, with_decl=True):
    got = references(s, proj, base, needle, delta, with_decl)
    if dump:
        print("%s: %r" % (label, got))
    else:
        compare(label, sorted(want), got)


def two_module(server, env, work, dump):
    proj = Project(work, "refs_two", TWO)
    s = Session(server, proj.root, env)
    try:
        # main alone is open; helper is read from disk as main's import
        open_doc(s, proj, "main.dawn")
        for label, needle, delta in FROM_MAIN["two"]:
            ask(s, proj, "two modules, from main's %s" % label, "main.dawn", needle, delta, TWO_ALL, dump)
        ask(s, proj, "two modules, includeDeclaration false", "main.dawn", "{double}", 1,
            [x for x in TWO_ALL if x != "helper.dawn 2:7 double"], dump, with_decl=False)
        open_doc(s, proj, "helper.dawn")
        ask(s, proj, "two modules, from the declaration", "helper.dawn", "fn double", 3, TWO_ALL, dump)
        ask(s, proj, "two modules, from a use in the declaring module", "helper.dawn", "double(n))", 0,
            TWO_ALL, dump)
    finally:
        s.close()


def three_module(server, env, work, dump):
    proj = Project(work, "refs_three", THREE)
    s = Session(server, proj.root, env)
    try:
        # main alone is open; lone is imported by nothing open
        open_doc(s, proj, "main.dawn")
        for label, needle, delta in FROM_MAIN["three"]:
            ask(s, proj, "three modules, from main's %s" % label, "main.dawn", needle, delta,
                THREE_ALL, dump)
        open_doc(s, proj, "base.dawn")
        ask(s, proj, "three modules, from the declaration", "base.dawn", "fn scale", 3, THREE_ALL, dump)
        # an edit of the declaring module above the declaration
        proj.texts["base.dawn"] = BASE_EDITED
        s.notify("textDocument/didChange", {
            "textDocument": {"uri": proj.uri("base.dawn"), "version": 2},
            "contentChanges": [{"text": BASE_EDITED}]})
        ask(s, proj, "three modules, after an edit above the declaration, from main",
            "main.dawn", "|> base.scale", 8, THREE_EDITED, dump)
        ask(s, proj, "three modules, after an edit above the declaration, from the declaration",
            "base.dawn", "fn scale", 3, THREE_EDITED, dump)
        # a round trip after the last publish, then: was the module nothing
        # open imports ever given diagnostics?
        s.request("textDocument/documentSymbol", {"textDocument": {"uri": proj.uri("main.dawn")}})
        got = sorted(u.rsplit("/", 1)[-1] for u in s.published if u.startswith("file://" + proj.src))
        if dump:
            print("diagnostics published for: %r" % got)
        else:
            compare("three modules, diagnostics come from the open documents' imports alone", [], got)
    finally:
        s.close()


def contract(server, env, dump=False):
    work = tempfile.mkdtemp(prefix="lsp-references-workspace.")
    try:
        two_module(server, env, work, dump)
        three_module(server, env, work, dump)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- mutants ---------------------------------------------------------------
#
# Each breaks one decision this contract exists for and must turn its owning
# case red. The anchors are in lsp-references-workspace/mutate.py, where the
# preflight proves them before any build; this is (mutant, owner).

MUTATE = os.path.join(ROOT, "scripts", "lsp-references-workspace", "mutate.py")

MUTANTS = [
    ('open-documents-only', 'two modules, from main\'s qualified call'),
    ('import-list-unresolved', 'three modules, from main\'s import list'),
    ('index-outlives-its-step', 'three modules, after an edit above the declaration, from main'),
    ('diagnostics-load-whole-tree', 'three modules, diagnostics come from the open documents\' imports alone'),
    ('sites-not-moved', 'three modules, after an edit above the declaration, from the declaration'),
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
        print("\nlsp-references-workspace: %d assertion(s) failed" % len(failures), file=sys.stderr)
        return 1
    print("\nlsp-references-workspace: positive OK")
    if not mutants:
        return 0
    work = tempfile.mkdtemp(prefix="lsp-references-workspace-mutants.")
    try:
        for name, owner in MUTANTS:
            cmd = build_mutant(dawn, work, name)
            print("PASS  %s mutant compiles" % name)
            del failures[:]
            contract(cmd, env)
            if owner not in failures:
                print("lsp-references-workspace: %s mutant left '%s' green (red: %r)"
                      % (name, owner, failures), file=sys.stderr)
                return 1
            print("PASS  %s mutant turns '%s' red" % (name, owner))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\nlsp-references-workspace: OK")
    return 0


sys.exit(main())
