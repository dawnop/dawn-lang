#!/usr/bin/env python3
"""The "remove unused import" code action, driven through a real server.

An unused import is a compile error (spec §10.2, docs/unused-imports-design.md),
and Go can make the same rule an error only because gopls/goimports take the
friction away. `dawn fmt` works on tokens and cannot know what a module uses,
so the language server is where removal lives. This script is its contract:
it opens a buffer with three unused imports of the three shapes the edit has
to handle, takes the diagnostics the server itself published, asks for code
actions with them, applies every edit it gets back, and requires the result
to be exactly the file with those imports gone -- and to check clean.

The oracle is the expected text, written out below, not a transcript: a
transcript of the previous release would be a difference to declare
(scripts/selfhost-lsp-diff.sh), never an assertion that the edit is right.

Usage:  scripts/lsp-unused-import-action.py [server command...]   (default ./bin/dawn lsp)
"""
import json
import os
import select
import subprocess
import sys
import time

DOC_REL = "scripts/zz_unused_import_probe.dawn"

TIMEOUT_S = 600

BEFORE = """use std/str
use std/map
use std/list.{find, reverse, unique as uniq}

pub fn shout(xs: List[Int]) -> String = str.to_upper(to_string(reverse(xs)))
"""

# `map`: a whole-module import, the whole line goes. `find`: the first name of
# three, it goes with the comma after it. `unique as uniq`: the last entry, renamed, goes whole
# with the comma before it. `reverse` and `str` are used and stay.
AFTER = """use std/str
use std/list.{reverse}

pub fn shout(xs: List[Int]) -> String = str.to_upper(to_string(reverse(xs)))
"""


class Server:
    def __init__(self, cmd, cwd):
        self.proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.buf = b""
        self.next_id = 0

    def send(self, msg):
        body = json.dumps(msg).encode()
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
        self.proc.stdin.flush()

    def request(self, method, params):
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        return self.next_id

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def frame(self, deadline):
        while True:
            j = self.buf.find(b"\r\n\r\n")
            if j >= 0:
                clen = None
                for line in self.buf[:j].decode("utf-8", "replace").split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        clen = int(line.split(":", 1)[1].strip())
                if clen is not None and len(self.buf) >= j + 4 + clen:
                    out = json.loads(self.buf[j + 4:j + 4 + clen].decode())
                    self.buf = self.buf[j + 4 + clen:]
                    return out
            left = deadline - time.time()
            if left <= 0:
                raise SystemExit("lsp-unused-import-action: timed out waiting for the server")
            ready, _, _ = select.select([self.proc.stdout], [], [], left)
            if ready:
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if not chunk:
                    raise SystemExit("lsp-unused-import-action: the server closed its output")
                self.buf += chunk

    def until(self, pred):
        deadline = time.time() + TIMEOUT_S
        while True:
            f = self.frame(deadline)
            if pred(f):
                return f

    def close(self):
        self.request("shutdown", None)
        self.notify("exit", {})
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.wait(timeout=60)


def diagnostics_for(server, uri):
    f = server.until(lambda f: f.get("method") == "textDocument/publishDiagnostics"
                     and f["params"]["uri"] == uri)
    return f["params"]["diagnostics"]


def offset(text, pos):
    """LSP position -> index into `text`. The probe is ASCII, so a UTF-16
    column is a character column."""
    lines = text.split("\n")
    return sum(len(l) + 1 for l in lines[:pos["line"]]) + pos["character"]


def apply(text, edits):
    spans = sorted(((offset(text, e["range"]["start"]), offset(text, e["range"]["end"]),
                     e["newText"]) for e in edits), reverse=True)
    for i, (lo, hi, new) in enumerate(spans):
        if i > 0 and hi > spans[i - 1][0]:
            raise SystemExit("lsp-unused-import-action: two edits overlap")
        text = text[:lo] + new + text[hi:]
    return text


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    cmd = sys.argv[1:] or ["./bin/dawn", "lsp"]
    uri = "file://" + os.path.join(root, DOC_REL)
    print("lsp-unused-import-action: server = %s" % " ".join(cmd))
    failures = []

    def expect(why, ok, detail=""):
        print("  %s  %s" % ("ok  " if ok else "FAIL", why))
        if not ok:
            failures.append(why)
            if detail:
                print("        " + detail.replace("\n", "\n        "))

    s = Server(cmd, root)
    init = s.request("initialize", {"processId": None, "rootUri": None, "capabilities": {}})
    caps = s.until(lambda f: f.get("id") == init)["result"]["capabilities"]
    expect("initialize advertises codeActionProvider", caps.get("codeActionProvider") is True,
           "capabilities: %s" % json.dumps(caps))
    s.notify("initialized", {})
    s.notify("textDocument/didOpen", {"textDocument": {
        "uri": uri, "languageId": "dawn", "version": 1, "text": BEFORE}})
    diags = diagnostics_for(s, uri)
    names = sorted(d["message"].split("\n", 1)[0] for d in diags)
    want = ["unused import: find", "unused import: map", "unused import: unique"]
    expect("the server publishes exactly the three unused imports", names == want,
           "want %s\ngot  %s" % (want, names))

    edits, titles = [], []
    for d in diags:
        rid = s.request("textDocument/codeAction", {
            "textDocument": {"uri": uri}, "range": d["range"],
            "context": {"diagnostics": [d]}})
        actions = s.until(lambda f: f.get("id") == rid)["result"]
        expect("one quickfix for `%s`" % d["message"].split("\n", 1)[0],
               isinstance(actions, list) and len(actions) == 1
               and actions[0].get("kind") == "quickfix"
               and actions[0].get("diagnostics") == [d],
               json.dumps(actions))
        for a in actions or []:
            titles.append(a.get("title"))
            edits += a["edit"]["changes"][uri]
    expect("titles name the import",
           sorted(titles) == ["Remove unused import `find`", "Remove unused import `map`",
                              "Remove unused import `unique`"], json.dumps(titles))

    # a range with no diagnostic behind it is offered nothing
    rid = s.request("textDocument/codeAction", {
        "textDocument": {"uri": uri},
        "range": {"start": {"line": 4, "character": 0}, "end": {"line": 4, "character": 3}},
        "context": {"diagnostics": []}})
    expect("no diagnostic, no action", s.until(lambda f: f.get("id") == rid)["result"] == [])

    after = apply(BEFORE, edits)
    expect("the edits remove exactly the unused imports", after == AFTER,
           "want:\n%s\ngot:\n%s" % (AFTER, after))

    s.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 2},
                                        "contentChanges": [{"text": after}]})
    left = diagnostics_for(s, uri)
    expect("the edited buffer checks clean", left == [], json.dumps(left))
    s.close()

    if failures:
        print("FAIL: lsp unused-import code action (%d of the checks above)" % len(failures))
        sys.exit(1)
    print("OK: lsp unused-import code action")


main()
