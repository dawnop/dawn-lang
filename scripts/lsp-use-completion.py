#!/usr/bin/env python3
"""What the language server offers on a `use` line, checked against the tree
it claims to be describing.

The directory tree IS the namespace (#175): `use front/lexer` names
selfhost/src/front/lexer.dawn and nothing else decides that. Completion is the
half that makes the tree navigable rather than merely addressable, and its
oracle is therefore not a golden file -- it is the tree. Every expectation
below is computed from the filesystem (directory listings, std/modules.txt,
the `[deps]` table, `pub` declarations), so adding a module keeps this green
and *removing* the feature turns it red. A recorded transcript would have
rotted at the first new module in check/.

Why this cannot be scripts/selfhost-lsp-diff.sh: that gate compares the server
against the previous release, so a feature the previous release does not have
is a difference to be declared, never an assertion to be checked. Nor
lsp-liveness.py, which is about scheduling and reads no payloads at all.

The document is a path under selfhost/src that does not exist on disk. That is
not a trick to avoid writing a file: an unsaved new buffer is exactly when a
user types their first `use`, and the server has to answer from the buffer's
*path* -- the tree around a file that is not in it yet.

Usage:  scripts/lsp-use-completion.py [server command...]   (default ./bin/dawn lsp)
"""
import json
import os
import re
import subprocess
import sys

# The buffer: inside the selfhost tree (so the module root is selfhost/src),
# not on disk (so nothing in the repo has to be created or cleaned up).
DOC_REL = "selfhost/src/zz_use_probe.dawn"

TIMEOUT_S = 600


# ---- the oracles, all read off the tree ------------------------------------

def dawn_dir(path):
    """{label} for one directory as `use <label>` would spell its entries:
    a module drops `.dawn`, a subdirectory keeps a trailing `/`. A directory
    with no modules under it is not a step to anywhere, so it is not offered."""
    out = set()
    for name in os.listdir(path):
        p = os.path.join(path, name)
        if os.path.isdir(p):
            if any(f.endswith(".dawn") for _, _, fs in os.walk(p) for f in fs):
                out.add(name + "/")
        elif name.endswith(".dawn"):
            out.add(name[:-5])
    return out


def dep_aliases(manifest):
    """The `[deps]` keys -- the spelling the *consumer* uses, which is what a
    `use` line in this project may name (the package's own name may differ)."""
    out, in_deps = set(), False
    for line in open(manifest):
        line = line.split("#", 1)[0].strip()
        if line.startswith("["):
            in_deps = line in ("[deps]",)
            continue
        if in_deps and "=" in line:
            out.add(line.split("=", 1)[0].strip())
    return out


def std_modules(path):
    out = set()
    for line in open(path):
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


def pub_names(path):
    """Every name a `use m.{...}` may import from a module, read off its source.

    Constructors of a `pub type` are importable too, but a record's sole
    constructor shares the type's name, so this set is by name and not by
    declaration -- which is also how the server de-duplicates it."""
    out = set()
    for m in re.finditer(r"(?m)^pub (?:opaque )?(?:fn|type|const|trait|effect) (\w+)",
                         open(path).read()):
        out.add(m.group(1))
    return out


# ---- the session -----------------------------------------------------------

def run_session(server, root, cases):
    """One `didOpen`/`didChange` per case, each followed by a completion
    request at the end of the single line. Returns id -> result."""
    uri = "file://" + os.path.join(root, DOC_REL)
    msgs, next_id = [], [1]

    def req(method, params):
        next_id[0] += 1
        msgs.append({"jsonrpc": "2.0", "id": next_id[0], "method": method,
                     "params": params})
        return next_id[0]

    def note(method, params):
        msgs.append({"jsonrpc": "2.0", "method": method, "params": params})

    req("initialize", {"processId": None, "rootUri": None, "capabilities": {}})
    note("initialized", {})
    ids = []
    for i, text in enumerate(cases):
        doc = {"uri": uri, "version": i + 1}
        if i == 0:
            note("textDocument/didOpen", {"textDocument": dict(
                doc, languageId="dawn", text=text + "\n")})
        else:
            note("textDocument/didChange", {"textDocument": doc,
                                            "contentChanges": [{"text": text + "\n"}]})
        # the cursor sits at the end of the line, which is where a person
        # typing it would be
        ids.append(req("textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": 0, "character": len(text)}}))
    req("shutdown", None)
    note("exit", {})

    payload = b""
    for m in msgs:
        body = json.dumps(m).encode()
        payload += b"Content-Length: %d\r\n\r\n%s" % (len(body), body)
    proc = subprocess.run(server, input=payload, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, cwd=root, timeout=TIMEOUT_S)

    data, out, i = proc.stdout, {}, 0
    while True:
        j = data.find(b"\r\n\r\n", i)
        if j < 0:
            break
        clen = None
        for line in data[i:j].decode("utf-8", "replace").split("\r\n"):
            if line.lower().startswith("content-length:"):
                clen = int(line.split(":", 1)[1].strip())
        if clen is None:
            break
        frame = json.loads(data[j + 4:j + 4 + clen].decode())
        if "id" in frame and "result" in frame:
            out[frame["id"]] = frame["result"]
        i = j + 4 + clen
    return dict(zip(cases, [out.get(k) for k in ids]))


def labels(result):
    return sorted(it["label"] for it in result) if isinstance(result, list) else None


def main():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    root = os.path.abspath(root)
    server = sys.argv[1:] or ["./bin/dawn", "lsp"]
    src = os.path.join(root, "selfhost/src")

    # ---- what each line should answer, computed from the tree --------------
    first = dawn_dir(src) | {"std/"} | {a + "/" for a in dep_aliases(
        os.path.join(root, "selfhost/dawn.toml"))} | {"java"}
    check = dawn_dir(os.path.join(src, "check"))
    stds = std_modules(os.path.join(root, "std/modules.txt"))
    lexer = pub_names(os.path.join(src, "front/lexer.dawn"))

    cases = [
        "use ",
        "use check/",
        "use std/",
        "use front/lexer.{",
        "use front/lexer.{view_of, ",
        "use front/lexer ",
        "use front/lexer as ",
        "use java ",
        "fn f() -> Int = 1 + fo",
    ]
    print("lsp-use-completion: server = %s" % " ".join(server))
    got = run_session(server, root, cases)

    checks = []

    def expect(case, why, ok, detail):
        checks.append((case, why, ok, detail))

    # (a) the first segment: every directory and root module of the project,
    #     the std prefix, every [deps] alias, and the `java` keyword. Exact,
    #     not "contains" -- an over-eager walk (following symlinks out of the
    #     tree, offering `std/` twice, leaking a dependency's real name beside
    #     its alias) is a failure this could not otherwise see.
    got_first = labels(got["use "])
    expect("use ", "project dirs + root modules + std/ + [deps] aliases + java",
           got_first == sorted(first), "want %s\n        got  %s" % (sorted(first), got_first))

    # (b) a deep path: one `/` steps into the directory and nothing else.
    got_check = labels(got["use check/"])
    expect("use check/", "exactly the modules under selfhost/src/check",
           got_check == sorted(check), "want %s\n        got  %s" % (sorted(check), got_check))

    # (c) std is bundled, not on disk beside the project: its list comes from
    #     the server's own StdCtx, and modules.txt is what built that.
    got_std = labels(got["use std/"])
    expect("use std/", "exactly the modules in std/modules.txt",
           got_std == sorted(stds), "want %s\n        got  %s" % (sorted(stds), got_std))

    # (d) the names inside `.{ }` for a module the buffer does not import --
    #     which is every module worth completing, since the `use` being typed
    #     is what would have imported it. Nothing has checked that module, so
    #     the server parses it for its `pub` declarations.
    got_items = labels(got["use front/lexer.{"])
    expect("use front/lexer.{", "the pub declarations of front/lexer.dawn",
           got_items == sorted(lexer), "want %s\n        got  %s" % (sorted(lexer), got_items))
    # spelled out rather than derived, because the point is a name that the
    # module keeps to itself: `fn src_of` in front/lexer.dawn, no `pub`
    expect("use front/lexer.{", "a module-private name (`src_of`) is not offered",
           "src_of" not in (got_items or []), "offered `src_of`")

    # (e) a name already in the list is not offered again.
    got_more = labels(got["use front/lexer.{view_of, "])
    expect("use front/lexer.{view_of, ", "already-listed names are dropped",
           got_more == sorted(lexer - {"view_of"}),
           "want %s\n        got  %s" % (sorted(lexer - {"view_of"}), got_more))

    # (f) after a whole path the grammar admits `as <name>`, and after `as`
    #     the name is the user's -- so exactly one item, then none.
    expect("use front/lexer ", "the `as` rename", labels(got["use front/lexer "]) == ["as"],
           "got %s" % labels(got["use front/lexer "]))
    expect("use front/lexer as ", "nothing to suggest for a name the user picks",
           labels(got["use front/lexer as "]) == [],
           "got %s" % labels(got["use front/lexer as "]))

    # (g) `use java` takes a quoted class name. Guessing one is not on offer.
    expect("use java ", "no module paths where a Java class name goes",
           labels(got["use java "]) == [], "got %s" % labels(got["use java "]))

    # (h) the negative that keeps the rest honest: ordinary code still gets
    #     ordinary completion, with no path or directory leaking into it.
    code = labels(got["fn f() -> Int = 1 + fo"]) or []
    expect("fn f() -> Int = 1 + fo", "ordinary code is unchanged (prelude + keywords, no paths)",
           "fold" in code and "if" in code and not any(x.endswith("/") for x in code),
           "got %d items%s" % (len(code),
                               "; paths: %s" % [x for x in code if x.endswith("/")]
                               if any(x.endswith("/") for x in code) else ""))

    bad = 0
    for case, why, ok, detail in checks:
        print("%-4s %-30s %s" % ("PASS" if ok else "FAIL", "[%s|]" % case, why))
        if not ok:
            bad += 1
            print("        " + str(detail))
    if bad:
        print("lsp-use-completion: FAILED (%d of %d)" % (bad, len(checks)))
        return 1
    print("lsp-use-completion: OK (%d assertions over %d lines)" % (len(checks), len(cases)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
