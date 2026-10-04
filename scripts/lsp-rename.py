#!/usr/bin/env python3
"""What `textDocument/prepareRename` and `textDocument/rename` answer, asserted case by case.

A rename edits every name the references index of the project resolves to
the declaration at the cursor, its doc links included, and nothing else
(selfhost/src/lsp/server.dawn `handle_rename`, selfhost/src/lsp/lsprename.dawn,
docs/lsp-references-design.md §R3). Before it hands the edit out it analyzes
the edited project and refuses when a module gains an error or when any name
resolves to another declaration than it did. selfhost-lsp-diff.sh compares
against the previous release, which has no rename, so it can say that a reply
changed and never whether it is right. This script says it, one case per
safety condition of the research report's §3.3 that a fixture can hold
(formatting, the fourteenth, is measured on selfhost instead; §R3.6):

  1 case class          an upper-case new name for a function is refused
  2 keyword             `match` is refused
  3 shadowing           a function renamed onto the builtin `len`, which the
                        module calls, is refused; so is one renamed onto a
                        local lambda a call would then capture
  4 module alias        a function renamed onto `str`, a module alias, is refused
  5 selective import    `use geo.{first as head}`: renaming `first` edits the
                        list's `first` and not `head`; renaming `head` edits
                        only `head`; a name already imported is refused
  6 importers           a public function's every importer is edited, through
                        the import list, a qualified call, a pipe and UFCS
  7 std and [deps]      a std function, a builtin and a [deps] package's
                        function are refused at prepareRename
  8 record puns         the field side spells `{ x }` out as `{ col: x }`, the
                        local side as `{ x: v }`, in a construction and a pattern
  9 named arguments     a parameter's `by: 3` at a call follows it
  10 trait methods      the trait's method, the impl's and the call
  11 operations         the declaration, the call and the handler arm
  12 pipes and UFCS     in 6
  13 doc links          [`scale`], [`geo.scale`] and [`Point.x`] follow
  15 self-check         3 and 4 are the compiler's and the resolution check's

plus the refusals of §3.2: a module name, `main`, and a module with errors.

Every accepted rename is then applied to a copy of the project, edit ranges
read whole, start line to end line, and the copy must run and print what the
original printed: an edit that compiles and calls another function (a
default argument's call left behind, now the builtin's) changes the output.
Two more projects hold what one session's fixture cannot:

  default argument  `fn f(n: Int = len([1]))` with a top-level `len`: the call
                    in the default is renamed with the declaration
  files on disk     a module no document holds is edited and another is
                    created on disk mid-session: references follows a
                    watched-file notification, and rename reads the files
                    again even when the client sent none

Usage:
  scripts/lsp-rename.py [--server CMD...]   positive run (default ./bin/dawn lsp)
  scripts/lsp-rename.py --dump              print every case's reply and exit
  scripts/lsp-rename.py --mutants           positive run, then compile each mutant
                                            from a private selfhost copy and require
                                            its owning case red

A mutant is accepted as red only when its owning assertion is among the
failures; a build failure is not a negative control and fails the run.
"""
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GEO = """## Shapes and their sizes; see [`scale`] and [`Point.x`].

## A point.
pub type Point = { x: Int, y: Int }

## Scales a number. Pairs with [`geo.scale`].
pub fn scale(n: Int, by: Int = 2) -> Int = n * by

pub fn shift(p: Point, dx: Int) -> Point = Point { x: p.x + dx, y: p.y }

pub fn origin(x: Int) -> Point = {
  let y = x + 1
  Point { x, y }
}

pub fn first(p: Point) -> Int =
  match p {
    Point { x, y: _ } -> x
  }

pub trait Area[T] {
  fn area(s: T) -> Int
}

impl Area[Point] {
  fn area(s: Point) -> Int = s.x * s.y
}

pub effect Ask {
  fn ask() -> Int
}

pub fn asked() -> Int !Ask = ask() + 1
"""

MAIN = """use std/str
use geo
use geo.{scale, area, asked, Ask, first as head}
use dep/lib.{triple}

fn count_of(xs: List[Int]) -> Int = 0

fn helper(n: Int) -> Int = {
  let twice = (k: Int) => k * 2
  scale(n) + twice(n) + len([n])
}

pub fn main() -> Unit !io = {
  with handle Ask { ask() => 4 }
  let a = scale(1, by: 3)
  let b = geo.scale(2)
  let c = 3 |> scale
  let d = 2.scale()
  let p = geo.origin(a)
  let q = geo.shift(p, 1)
  println("${a + b + c + d + head(p) + area(q) + asked() + triple(1) + str.len("x") + count_of([]) + helper(1)}")
}
"""

# a module with an error, which nothing imports
BROKEN = """pub fn broken() -> Int = "not an int"

pub fn fine(n: Int) -> Int = n
"""

FILES = {"geo.dawn": GEO, "main.dawn": MAIN, "broken.dawn": BROKEN}

# a top-level `len` shadows the builtin, and a default argument calls it: a
# rename that misses the default leaves a call the builtin then answers, and
# the program prints 1 instead of 99 with no error anywhere
DEFAULTS = """fn len(xs: List[Int]) -> Int = 99

fn f(n: Int = len([1])) -> Int = n

const RESULT: Int = f()

pub fn main() -> Unit !io = println("${RESULT}")
"""

DEFAULT_CASES = [
    ("default argument: a call in a default follows its declaration", "main.dawn", "fn len", 3, "count", [
        "main.dawn 1:4 len -> count", "main.dawn 3:15 len -> count"]),
]

DISK_BASE = "pub fn scale(n: Int) -> Int = n * 3\n"
DISK_MAIN = 'use base\n\npub fn main() -> Unit !io = println("${base.scale(1)}")\n'
DISK_LONE = "use base\n\npub fn lone() -> Int = base.scale(2)\n"
DISK_PAD = "# a comment added on disk\n"

DEP_LIB = "pub fn triple(n: Int) -> Int = n * 3\n"

SCALE_TO_GROW = [
    "geo.dawn 1:34 scale -> grow", "geo.dawn 6:38 scale -> grow", "geo.dawn 7:8 scale -> grow",
    "main.dawn 3:10 scale -> grow", "main.dawn 10:3 scale -> grow", "main.dawn 15:11 scale -> grow",
    "main.dawn 16:15 scale -> grow", "main.dawn 17:16 scale -> grow", "main.dawn 18:13 scale -> grow",
]

# (label, file, needle, delta, new name or None for prepareRename, expected).
# Expected is the sorted list of `file line:column old -> new` edits (line and
# column from 1, column in UTF-16 units, `old` the text the range covers), or
# for prepareRename `range line:column-line:column placeholder`, or
# `error: <message>` for a refusal, with the project's directory cut out.
CASES = [
    # a rename the editor asks about first
    ("prepare: a function at a call", "main.dawn", "scale(1, by", 0, None, "range 15:11-15:16 scale"),
    # 6, 12, 13: every importer, through every way a name crosses a module
    ("importers: a public function from a call", "main.dawn", "scale(1, by", 2, "grow", SCALE_TO_GROW),
    ("importers: the same from its declaration", "geo.dawn", "fn scale", 3, "grow", SCALE_TO_GROW),
    # 9
    ("named argument: the parameter follows to its call", "main.dawn", "by: 3", 0, "factor", [
        "geo.dawn 7:22 by -> factor", "geo.dawn 7:48 by -> factor", "main.dawn 15:20 by -> factor"]),
    # 8, 13
    ("record pun, field side: spelled out where it puns", "geo.dawn", "x: Int, y", 0, "col", [
        "geo.dawn 1:54 x -> col", "geo.dawn 4:20 x -> col", "geo.dawn 9:52 x -> col",
        "geo.dawn 9:57 x -> col", "geo.dawn 13:11 x -> col: x", "geo.dawn 18:13 x -> col: x",
        "geo.dawn 26:32 x -> col"]),
    ("record pun, local side: a let a construction puns", "geo.dawn", "let y", 4, "yy", [
        "geo.dawn 12:7 y -> yy", "geo.dawn 13:14 y -> y: yy"]),
    ("record pun, local side: a binder a pattern puns", "geo.dawn", "{ x, y: _ }", 2, "v", [
        "geo.dawn 18:13 x -> x: v", "geo.dawn 18:26 x -> v"]),
    # 10
    ("trait method: the trait's, the impl's and the call", "main.dawn", "area(q)", 0, "size", [
        "geo.dawn 22:6 area -> size", "geo.dawn 26:6 area -> size",
        "main.dawn 3:17 area -> size", "main.dawn 21:40 area -> size"]),
    # 11
    ("operation: the declaration, the call and the handler arm", "geo.dawn", "fn ask", 3, "query", [
        "geo.dawn 30:6 ask -> query", "geo.dawn 33:30 ask -> query", "main.dawn 14:21 ask -> query"]),
    # 5
    ("selective import: the declaration's name, not the `as` name", "geo.dawn", "fn first", 3, "lead", [
        "geo.dawn 16:8 first -> lead", "main.dawn 3:35 first -> lead"]),
    ("selective import: the `as` name, in its module only", "main.dawn", "head(p)", 0, "top", [
        "main.dawn 3:44 head -> top", "main.dawn 21:30 head -> top"]),
    ("selective import: a name the module already imports", "main.dawn", "fn helper", 3, "scale",
     "error: renaming `helper` to `scale` breaks the program: main.dawn:8:4: "
     "function `scale` conflicts with a name imported from `geo`"),
    # 1, 2
    ("case class: a value's new name is lower-case", "main.dawn", "scale(1, by", 0, "Grow",
     "error: `scale` names a value, so its new name must start with a lower-case letter"),
    ("keyword: never a new name", "main.dawn", "scale(1, by", 0, "match", "error: `match` is a keyword"),
    # 3: the builtin `len` would now be this function at its call
    ("shadowing: a builtin the module calls", "main.dawn", "fn count_of", 3, "len",
     "error: renaming `count_of` to `len` would change what the name at main.dawn:10:25 refers to"),
    # 3: the call would now be the local lambda's
    ("shadowing: a local a call would be captured by", "main.dawn", "scale(n)", 0, "twice",
     "error: renaming `scale` to `twice` would change what the name at main.dawn:10:3 refers to"),
    # 4
    ("module alias: one namespace with functions", "main.dawn", "fn helper", 3, "str",
     "error: renaming `helper` to `str` breaks the program: main.dawn:8:4: "
     "`str` shadows the imported module `std/str`"),
    # 7
    ("[deps]: a dependency's function", "main.dawn", "triple(1)", 0, None,
     "error: `triple` is declared outside this project's sources (in std, a builtin or a dependency); "
     "rename only changes the project's own declarations"),
    ("std: a std function", "main.dawn", "str.len", 4, None,
     "error: `len` is declared outside this project's sources (in std, a builtin or a dependency); "
     "rename only changes the project's own declarations"),
    ("builtin: no declaration in the project", "main.dawn", "len([n", 0, None,
     "error: this name is not declared in this project's sources"),
    # §3.2
    ("module: renamed by moving its file", "main.dawn", "geo.origin", 1, None,
     "error: `geo` names a module; a module is renamed by moving its file"),
    ("main: the entry point keeps its name", "main.dawn", "fn main", 3, None,
     "error: `main` is the program's entry point and keeps its name"),
    ("errors: a module with errors is not read", "broken.dawn", "fn fine", 3, None,
     "error: `broken` has errors; rename reads every name, so fix them first"),
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


def offset(text, pos):
    """The code point offset in `text` of an LSP position (UTF-16 column)."""
    lines = text.split("\n")
    if pos["line"] >= len(lines):
        return len(text)
    at = sum(len(l) + 1 for l in lines[:pos["line"]])
    units = lines[pos["line"]].encode("utf-16-le")[:2 * pos["character"]]
    return at + len(units.decode("utf-16-le", errors="replace"))


def run_copy(dawn, proj, texts):
    """Run a copy of `proj` whose sources are `texts`: (exit code, output)."""
    work = tempfile.mkdtemp(prefix="lsp-rename-run.")
    try:
        root = os.path.join(work, os.path.basename(proj.root))
        shutil.copytree(proj.root, root)
        if os.path.isdir(os.path.join(proj.root, "..", "dep")):
            shutil.copytree(os.path.join(proj.root, "..", "dep"), os.path.join(work, "dep"))
        for base, text in texts.items():
            with open(os.path.join(root, "src", base), "w") as f:
                f.write(text)
        r = subprocess.run([dawn, "run", root], capture_output=True, text=True)
        return r.returncode, (r.stdout + r.stderr).replace(root + "/", "")
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
        self.caps = self.request("initialize", {"processId": None, "rootUri": None, "capabilities": {}})
        self.notify("initialized", {})

    def send(self, obj):
        self.p.stdin.write(frame(obj))
        self.p.stdin.flush()

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method, params):
        """The result, or {"error": message} for an error reply."""
        self.next_id += 1
        mine = self.next_id
        self.send({"jsonrpc": "2.0", "id": mine, "method": method, "params": params})
        while True:
            msg = read_msg(self.p.stdout)
            if msg is None:
                raise RuntimeError("server closed while waiting for %s" % method)
            if msg.get("id") == mine and "method" not in msg:
                if "error" in msg:
                    return {"error": msg["error"].get("message", "")}
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
    """The project, its [deps] package beside it, and the texts the server reads."""

    def __init__(self, work, files=FILES, with_dep=True):
        manifest = 'schema = 1\nname = "ren"\n'
        if with_dep:
            dep = os.path.join(work, "dep")
            os.makedirs(os.path.join(dep, "src"))
            with open(os.path.join(dep, "dawn.toml"), "w") as f:
                f.write('schema = 1\nname = "dep"\nversion = "1.0.0"\n')
            with open(os.path.join(dep, "src", "lib.dawn"), "w") as f:
                f.write(DEP_LIB)
            manifest += '\n[deps]\ndep = "../dep"\n'
        self.root = os.path.join(work, "ren")
        self.src = os.path.join(self.root, "src")
        os.makedirs(self.src)
        with open(os.path.join(self.root, "dawn.toml"), "w") as f:
            f.write(manifest)
        self.texts = {}
        for base, text in files.items():
            self.put(base, text)

    def put(self, base, text):
        """Write a source file on disk, and remember it as the text edits read."""
        self.texts[base] = text
        with open(os.path.join(self.src, base), "w") as f:
            f.write(text)

    def uri(self, base):
        return "file://" + os.path.join(self.src, base)

    def base_of(self, uri):
        prefix = "file://" + self.src + "/"
        return uri[len(prefix):] if uri.startswith(prefix) else None

    def covered(self, base, rng):
        """Where an edit starts and the text it replaces, read from its start
        to its end on whichever line that is: an end on a later line covers
        the line break and shows as text that is not the old name."""
        a, b = rng["start"], rng["end"]
        text = self.texts[base]
        return "%d:%d" % (a["line"] + 1, a["character"] + 1), text[offset(text, a):offset(text, b)]

    def applied(self, reply):
        """The project's files with the edits of `reply` applied."""
        out = dict(self.texts)
        for uri, edits in reply["changes"].items():
            base = self.base_of(uri)
            text = out[base]
            spans = sorted(((offset(text, e["range"]["start"]), offset(text, e["range"]["end"]), e["newText"])
                            for e in edits), reverse=True)
            for lo, hi, new in spans:
                text = text[:lo] + new + text[hi:]
            out[base] = text
        return out

    def shown(self, reply):
        if isinstance(reply, dict) and "error" in reply:
            return "error: " + reply["error"].replace(self.src + "/", "")
        if isinstance(reply, dict) and "placeholder" in reply:
            r = reply["range"]
            return "range %d:%d-%d:%d %s" % (
                r["start"]["line"] + 1, r["start"]["character"] + 1,
                r["end"]["line"] + 1, r["end"]["character"] + 1, reply["placeholder"])
        if isinstance(reply, dict) and "changes" in reply:
            out = []
            for uri, edits in reply["changes"].items():
                base = self.base_of(uri)
                if base is None:
                    out.append("elsewhere:" + uri)
                    continue
                for e in edits:
                    at, old = self.covered(base, e["range"])
                    out.append("%s %s %s -> %s" % (base, at, old, e["newText"]))
            return sorted(out)
        return "unexpected reply: %r" % (reply,)


def want_of(want):
    return sorted(want) if isinstance(want, list) else want


# Each accepted rename's run is a compile of its own, so they run side by
# side while the session goes on; `settle` reads them in case order.
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def check_runs(dawn, label, proj, reply, before, pending):
    """An accepted rename, applied to a copy of the project, must run and
    print what the project printed; queued on `pending`."""
    texts = proj.applied(reply)
    pending.append((label, before, POOL.submit(run_copy, dawn, proj, texts)))


def settle(pending):
    for label, before, fut in pending:
        after = fut.result()
        if after == before:
            ok("%s: the renamed project prints the same" % label)
        else:
            bad("%s: the renamed project prints the same" % label,
                "before %r\n      after  %r" % (before, after))
    del pending[:]


def ask(s, proj, base, needle, delta, new):
    params = {"textDocument": {"uri": proj.uri(base)},
              "position": position(proj.texts[base], needle, delta)}
    if new is None:
        return s.request("textDocument/prepareRename", params)
    params["newName"] = new
    return s.request("textDocument/rename", params)


def run_cases(s, proj, cases, dump, dawn, before, pending):
    for label, base, needle, delta, new, want in cases:
        reply = ask(s, proj, base, needle, delta, new)
        got = proj.shown(reply)
        if dump:
            print("%s: %r" % (label, got))
            continue
        if got == want_of(want):
            ok(label)
        else:
            bad(label, "want %r\n      got  %r" % (want, got))
        if before is not None and isinstance(reply, dict) and "changes" in reply:
            check_runs(dawn, label, proj, reply, before, pending)


def open_all(s, proj):
    for base in sorted(proj.texts):
        s.notify("textDocument/didOpen", {"textDocument": {
            "uri": proj.uri(base), "languageId": "dawn", "version": 1, "text": proj.texts[base]}})


def main_project(server, env, dump, dawn, applied):
    work = tempfile.mkdtemp(prefix="lsp-rename.")
    try:
        proj = Project(work)
        pending = []
        before = run_copy(dawn, proj, proj.texts) if applied else None
        s = Session(server, proj.root, env)
        try:
            caps = (s.caps or {}).get("capabilities", {})
            got = caps.get("renameProvider")
            if dump:
                print("renameProvider: %r" % got)
            elif got == {"prepareProvider": True}:
                ok("initialize declares renameProvider with prepareProvider")
            else:
                bad("initialize declares renameProvider with prepareProvider", "got %r" % got)
            open_all(s, proj)
            run_cases(s, proj, CASES, dump, dawn, before, pending)
            if dump:
                return
            # an edit whose range ends on the next line deletes the line break
            # and the next line's start; the comparison has to read the end line
            reply = ask(s, proj, "main.dawn", "scale(1, by", 2, "grow")
            if isinstance(reply, dict) and "changes" in reply:
                for edits in reply["changes"].values():
                    for e in edits:
                        e["range"]["end"]["line"] = e["range"]["start"]["line"] + 1
            label = "an edit range is read to its end line"
            if proj.shown(reply) != want_of(SCALE_TO_GROW):
                ok(label)
            else:
                bad(label, "an edit ending a line further down reads as the name it starts with")
        finally:
            s.close()
            settle(pending)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def defaults_project(server, env, dump, dawn, applied):
    work = tempfile.mkdtemp(prefix="lsp-rename-defaults.")
    try:
        proj = Project(work, {"main.dawn": DEFAULTS}, with_dep=False)
        pending = []
        before = run_copy(dawn, proj, proj.texts) if applied else None
        if before is not None and before != (0, "99\n"):
            bad("default argument: the project prints 99", "got %r" % (before,))
        s = Session(server, proj.root, env)
        try:
            open_all(s, proj)
            run_cases(s, proj, DEFAULT_CASES, dump, dawn, before, pending)
        finally:
            s.close()
            settle(pending)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def watched(proj, base, kind):
    """A didChangeWatchedFiles notification: 1 created, 2 changed, 3 deleted."""
    return {"changes": [{"uri": proj.uri(base), "type": kind}]}


def disk_project(server, env, dump, dawn, applied, notify):
    """Only main.dawn is open. base.dawn gains a line on disk, lone.dawn is
    created beside it, and then `scale` is renamed. With `notify` the client
    reports both; without, it reports neither, and rename alone must notice."""
    how = "notified" if notify else "unreported"
    work = tempfile.mkdtemp(prefix="lsp-rename-disk.")
    try:
        proj = Project(work, {"base.dawn": DISK_BASE, "main.dawn": DISK_MAIN}, with_dep=False)
        pending = []
        s = Session(server, proj.root, env)
        try:
            s.notify("textDocument/didOpen", {"textDocument": {
                "uri": proj.uri("main.dawn"), "languageId": "dawn", "version": 1, "text": DISK_MAIN}})
            at = {"textDocument": {"uri": proj.uri("main.dawn")},
                  "position": position(DISK_MAIN, "scale(1", 0), "context": {"includeDeclaration": True}}
            s.request("textDocument/references", at)
            proj.put("base.dawn", DISK_PAD + DISK_BASE)
            if notify:
                s.notify("workspace/didChangeWatchedFiles", watched(proj, "base.dawn", 2))
                refs = s.request("textDocument/references", at)
                got = sorted("%s %d:%d" % (proj.base_of(r["uri"]), r["range"]["start"]["line"] + 1,
                                           r["range"]["start"]["character"] + 1) for r in refs or [])
                label = "files on disk (notified): references follows a module edited on disk"
                want = ["base.dawn 2:8", "main.dawn 3:45"]
                if dump:
                    print("%s: %r" % (label, got))
                elif got == want:
                    ok(label)
                else:
                    bad(label, "want %r\n      got  %r" % (want, got))
            proj.put("lone.dawn", DISK_LONE)
            if notify:
                s.notify("workspace/didChangeWatchedFiles", watched(proj, "lone.dawn", 1))
            before = run_copy(dawn, proj, proj.texts) if applied else None
            run_cases(s, proj, [
                ("files on disk (%s): rename reads the edited module and the created one" % how,
                 "main.dawn", "scale(1", 0, "grow", [
                     "base.dawn 2:8 scale -> grow", "lone.dawn 3:29 scale -> grow",
                     "main.dawn 3:45 scale -> grow"]),
            ], dump, dawn, before, pending)
        finally:
            s.close()
            settle(pending)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def project_of(label):
    """Which project's session holds the case `label`."""
    if label.startswith("default argument"):
        return "defaults"
    if label.startswith("files on disk"):
        return "disk"
    return "main"


def contract(server, env, dump=False, applied=True, only=None):
    """Every case against `server`, or the cases of project `only`. `applied`
    also runs each accepted rename's result; a mutant run skips that and
    every other project, since its owner is one edit set or refusal."""
    dawn = os.path.join(ROOT, "bin", "dawn")
    if only in (None, "main"):
        main_project(server, env, dump, dawn, applied)
    if only in (None, "defaults"):
        defaults_project(server, env, dump, dawn, applied)
    if only in (None, "disk"):
        disk_project(server, env, dump, dawn, applied, True)
        disk_project(server, env, dump, dawn, applied, False)


# ---- mutants ---------------------------------------------------------------
#
# Each breaks one decision this contract exists for and must turn its owning
# case red. The anchors are in lsp-rename/mutate.py, where the preflight
# proves them before any build; this is (mutant, owner).

MUTATE = os.path.join(ROOT, "scripts", "lsp-rename", "mutate.py")

MUTANTS = [
    ('case-class-unchecked', 'case class: a value\'s new name is lower-case'),
    ('resolutions-unchecked', 'shadowing: a builtin the module calls'),
    ('diagnostics-unchecked', 'module alias: one namespace with functions'),
    ('puns-not-spelled-out', 'record pun, field side: spelled out where it puns'),
    ('as-names-renamed', 'selective import: the declaration\'s name, not the `as` name'),
    ('doc-links-skipped', 'importers: a public function from a call'),
    ('dependencies-renamed', '[deps]: a dependency\'s function'),
    ('defaults-unread', 'default argument: a call in a default follows its declaration'),
    ('disk-unread', 'files on disk (unreported): rename reads the edited module and the created one'),
    ('tree-not-rewalked', 'files on disk (unreported): rename reads the edited module and the created one'),
    ('watch-ignored', 'files on disk (notified): references follows a module edited on disk'),
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
        contract(server, env, dump=True, applied=False)
        return 0
    if args[:1] == ["--mutants"]:
        mutants = True
    elif args[:1] == ["--server"]:
        server = args[1:]
    contract(server, env)
    if failures:
        print("\nlsp-rename: %d assertion(s) failed" % len(failures), file=sys.stderr)
        return 1
    print("\nlsp-rename: positive OK")
    if not mutants:
        return 0
    work = tempfile.mkdtemp(prefix="lsp-rename-mutants.")
    try:
        for name, owner in MUTANTS:
            cmd = build_mutant(dawn, work, name)
            print("PASS  %s mutant compiles" % name)
            del failures[:]
            contract(cmd, env, applied=False, only=project_of(owner))
            if owner not in failures:
                print("lsp-rename: %s mutant left '%s' green (red: %r)"
                      % (name, owner, failures), file=sys.stderr)
                return 1
            print("PASS  %s mutant turns '%s' red" % (name, owner))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\nlsp-rename: OK")
    return 0


sys.exit(main())
