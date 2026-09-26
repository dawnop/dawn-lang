#!/usr/bin/env python3
"""Which typed function a hover reads, asserted over a live `dawn lsp` session.

The language server walks the parse tree and the checker's typed tree in
parallel, so everything it says about a function body -- a parameter's type,
where a local read was declared -- depends first on picking that function's
typed tree. It used to pick it by scanning every typed function for one whose
body spanned the same (lo, hi) as the syntax under the cursor. Since
docs/symbol-id-design.md §5 (S4) each typed function carries the declaration
path it was checked under (`TFun.decl`, the `identity.path_text` spelling the
diagnostics' owner uses) and the server looks it up by the path it spells from
the syntax it holds.

The selfhost-lsp-diff.sh transcript cannot pin this: it compares against the
previous release, which pairs by span and answers the same on every program
where spans are unique. So the cases here are the ones a key can get wrong
and a span cannot, and the one a span answers differently:

  keyed      two impls of one trait with a method of the same name, one of
             them overriding the trait's default body; an inferred function,
             an annotated one and a test named like the inferred one. A key
             spelled without its kind or impl head hands one of them
             another's tree.
  moved      two adjacent functions whose bodies are the same text, before
             and after `textDocument/formatting` moves them. This is the
             shipped (legacy) analysis, which checks the second revision
             afresh; the replayed-body half of the same question is the
             inline test "a replayed body's definition points at the
             candidate revision's position" in selfhost/src/lsp/server.dawn,
             which queries a revision whose bodies were replayed.
  repeated   a function declared twice. The key names the first instance
             (docs/symbol-id-design.md §4, the same rule as the header
             table), so the second instance's parameters read the first's
             types. A span pairing gives each instance its own tree; this
             case is where a revert to it shows.

Usage:  scripts/lsp-decl-pairing.py [dawn-launcher]     (default ./bin/dawn)
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAWN = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "bin", "dawn")

KEYED = """trait Label[T] {
  fn label(x: T) -> String
  fn twice(x: T) -> String = {
    let copy = x
    label(copy) ++ label(copy)
  }
}

type Box = { v: Int }

type Crate = { w: Float }

impl Label[Box] {
  fn label(b: Box) -> String = "box"
}

impl Label[Crate] {
  fn label(c: Crate) -> String = "crate"
  fn twice(c: Crate) -> String = "crates"
}

fn inferred(k: Float) = 1

fn annotated(flag: Bool) -> Int = 2

const LIMIT: Int = {
  let base = 40
  base + 2
}

test "inferred" {
  let probe = inferred(1.5)
  assert probe == 1
}
"""

MOVED = """fn   left( a : Int )  ->  Int =  a
fn   right( a : String )  ->  String =  a
"""

REPEATED = """fn twin(n: Int) -> Int = n
fn twin(s: String) -> Int = 2
"""

failures = []


def ok(name):
    print("PASS  %s" % name)


def bad(name, detail):
    print("FAIL: %s\n      %s" % (name, detail), file=sys.stderr)
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


def position(text, needle, delta=0, occurrence=1):
    i = -1
    for _ in range(occurrence):
        i = text.index(needle, i + 1)
    i += delta
    line = text.count("\n", 0, i)
    return {"line": line, "character": i - (text.rfind("\n", 0, i) + 1)}


def offset(text, pos):
    lines = text.split("\n")
    return sum(len(l) + 1 for l in lines[:pos["line"]]) + pos["character"]


def apply_edits(text, edits):
    spans = sorted(((offset(text, e["range"]["start"]), offset(text, e["range"]["end"]), e["newText"])
                    for e in edits), reverse=True)
    for lo, hi, new in spans:
        text = text[:lo] + new + text[hi:]
    return text


class Session:
    def __init__(self):
        self.p = subprocess.Popen([DAWN, "lsp"], cwd=ROOT, stdin=subprocess.PIPE,
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
            self.p.wait(timeout=20)
        except Exception:
            self.p.kill()


def hover(s, uri, text, needle, delta=0, occurrence=1):
    r = s.request("textDocument/hover", {"textDocument": {"uri": uri},
                                         "position": position(text, needle, delta, occurrence)})
    if not r:
        return None
    c = r.get("contents")
    value = c.get("value") if isinstance(c, dict) else c
    return value.replace("```dawn", "").replace("```", "").strip()


def definition(s, uri, text, needle, delta=0, occurrence=1):
    r = s.request("textDocument/definition", {"textDocument": {"uri": uri},
                                              "position": position(text, needle, delta, occurrence)})
    if not r:
        return None
    loc = r[0] if isinstance(r, list) else r
    start = loc["range"]["start"]
    return (start["line"], start["character"])


def expect(name, got, want):
    if got == want:
        ok("%s: %s" % (name, got))
    else:
        bad(name, "want %r, got %r" % (want, got))


def open_doc(s, uri, text, version=1):
    s.notify("textDocument/didOpen", {"textDocument": {
        "uri": uri, "languageId": "dawn", "version": version, "text": text}})


def keyed(s, uri):
    open_doc(s, uri, KEYED)
    t = KEYED
    expect("impl method parameter", hover(s, uri, t, "b: Box"), "b: Box")
    expect("second impl's namesake method parameter", hover(s, uri, t, "c: Crate) -> String = \"crate"), "c: Crate")
    expect("impl override of a trait default, parameter", hover(s, uri, t, "c: Crate) -> String = \"crates"), "c: Crate")
    expect("trait default body read", hover(s, uri, t, "copy) ++"), "let copy: T")
    expect("inferred function parameter", hover(s, uri, t, "k: Float"), "k: Float")
    expect("annotated function parameter", hover(s, uri, t, "flag: Bool"), "flag: Bool")
    expect("constant initializer local", hover(s, uri, t, "base + 2"), "let base: Int")
    expect("test body local", hover(s, uri, t, "probe == 1"), "let probe: Int")
    expect("test body local definition", definition(s, uri, t, "probe == 1"),
           (position(t, "let probe")["line"], position(t, "let probe")["character"]))


def moved(s, uri):
    open_doc(s, uri, MOVED)
    t = MOVED
    expect("left body read, first revision", hover(s, uri, t, "=  a\nfn", 3), "let a: Int")
    expect("right body read, first revision", hover(s, uri, t, "=  a\n", 3, 2), "let a: String")
    edits = s.request("textDocument/formatting", {"textDocument": {"uri": uri},
                                                  "options": {"tabSize": 2, "insertSpaces": True}})
    formatted = apply_edits(t, edits or [])
    if formatted == t:
        bad("formatting moves the bodies", "the server returned no edit")
        return
    s.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 2},
                                        "contentChanges": [{"text": formatted}]})
    t = formatted
    expect("left body read, formatted", hover(s, uri, t, "= a\n", 2), "let a: Int")
    expect("right body read, formatted", hover(s, uri, t, "= a\n", 2, 2), "let a: String")
    expect("left body read definition, formatted", definition(s, uri, t, "= a\n", 2),
           (position(t, "left(a")["line"], position(t, "left(a", 5)["character"]))
    expect("right body read definition, formatted", definition(s, uri, t, "= a\n", 2, 2),
           (position(t, "right(a")["line"], position(t, "right(a", 6)["character"]))


def repeated(s, uri):
    open_doc(s, uri, REPEATED)
    t = REPEATED
    expect("first instance parameter", hover(s, uri, t, "n: Int"), "n: Int")
    # the key names the first instance, so the second's parameter is read
    # against the first's typed tree
    expect("second instance reads the first instance's tree", hover(s, uri, t, "s: String"), "s: Int")


def main():
    work = os.path.join(ROOT, "build", "lsp-decl-pairing")
    s = Session()
    try:
        keyed(s, "file://" + os.path.join(work, "keyed.dawn"))
        moved(s, "file://" + os.path.join(work, "moved.dawn"))
        repeated(s, "file://" + os.path.join(work, "repeated.dawn"))
    finally:
        s.close()
    if failures:
        print("\nlsp-decl-pairing: %d assertion(s) failed" % len(failures), file=sys.stderr)
        return 1
    print("\nlsp-decl-pairing: OK")
    return 0


sys.exit(main())
