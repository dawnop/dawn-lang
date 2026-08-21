#!/usr/bin/env python3
"""Where `dawn lsp` finds std, asserted from cwds that are not the checkout.

The language server used to resolve std against the process cwd: `run_lsp` was
called with the bare literal "std". An editor spawns the server with whatever
directory it happened to be in, and when that missed, `load_std` fell back to
the embedded copy -- so a source file of the very checkout being edited was no
longer recognised as std, and the editor showed hundreds of phantom "undefined
function" diagnostics on files `dawn check` calls clean.

The unit rule (flag, then the toolchain's std, then the cwd-relative literal)
is pinned by an inline test on `lsp_std_dir` in selfhost/src/lsp/server.dawn.
This gate covers the two halves that test cannot reach:

  wiring    the CLI dispatch actually passes the parsed `--std` into `run_lsp`.
            Reverting that in either driver leaves every inline test green.
  launcher  bin/dawn exports DAWN_STD, resolved from its own location rather
            than from the caller's, and only when that directory exists.

A single run from the repo root would prove none of it -- that is the
configuration that passed before the fix -- so every server here is started
somewhere else, and the run from the repo root is present only as the control.

Also the #314 negative controls, because the risk of finding std more eagerly
is handing std identity to a file that is not std.

Usage:  scripts/lsp-std-resolution.py [dawn-launcher]     (default ./bin/dawn)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAWN = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "bin", "dawn")

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


def diagnostics(server_cwd, doc_path, args=(), env_overrides=None):
    """didOpen doc_path against a server started in server_cwd; return its diagnostics."""
    text = open(doc_path).read()
    uri = "file://" + os.path.abspath(doc_path)
    env = dict(os.environ)
    # the launcher's own DAWN_STD is what is under test, so never inherit one
    env.pop("DAWN_STD", None)
    if env_overrides:
        env.update(env_overrides)

    p = subprocess.Popen([DAWN, "lsp"] + list(args), cwd=server_cwd, env=env,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    try:
        w = p.stdin
        w.write(frame({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"processId": None, "rootUri": None, "capabilities": {}}}))
        w.flush()
        read_msg(p.stdout)
        w.write(frame({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
        w.write(frame({"jsonrpc": "2.0", "method": "textDocument/didOpen",
                       "params": {"textDocument": {"uri": uri, "languageId": "dawn",
                                                   "version": 1, "text": text}}}))
        w.flush()
        while True:
            msg = read_msg(p.stdout)
            if msg is None:
                return None
            if (msg.get("method") == "textDocument/publishDiagnostics"
                    and msg["params"].get("uri") == uri):
                return msg["params"].get("diagnostics", [])
    finally:
        try:
            p.stdin.close()
        except Exception:
            pass
        try:
            p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()


def messages(diags):
    return "; ".join(d["message"].split("\n")[0] for d in (diags or [])[:3])


def main():
    std_file = os.path.join(ROOT, "std", "cursor.dawn")
    if not os.path.exists(std_file):
        print("skip: no std/ checkout to resolve against", file=sys.stderr)
        return 0

    work = tempfile.mkdtemp(prefix="dawn-lsp-std-resolution.")
    try:
        # Two directories that are not the checkout and contain no std/ of their
        # own. The second is a parent of the checkout, which is where a real
        # editor was observed to put it.
        elsewhere = os.path.join(work, "elsewhere")
        os.makedirs(elsewhere)
        above = os.path.dirname(ROOT)

        for cwd in (elsewhere, above, work):
            d = diagnostics(cwd, std_file)
            if d is None:
                bad("std file from cwd %s" % cwd, "no publishDiagnostics")
            elif d:
                bad("a std file is std from cwd %s" % cwd,
                    "%d diagnostic(s): %s" % (len(d), messages(d)))
            else:
                ok("a std file is std when the server runs from %s" % cwd)

        # The control: the configuration that passed before the fix must still
        # pass, or this gate is measuring the wrong thing.
        d = diagnostics(ROOT, std_file)
        if d:
            bad("std file from the repo root",
                "%d diagnostic(s): %s" % (len(d), messages(d)))
        else:
            ok("a std file is std when the server runs from the checkout")

        # The escape hatch reaches run_lsp. Pointing --std at a directory that
        # is not a std makes load_std fall back to the embedded copy, and the
        # checkout's own std/cursor.dawn stops being recognised -- which is only
        # observable if the flag was parsed and passed through at all.
        d = diagnostics(elsewhere, std_file, args=["--std", os.path.join(work, "no-std-here")])
        if not d:
            bad("--std reaches the server",
                "an explicit --std at a non-std directory changed nothing")
        else:
            ok("--std overrides the toolchain default (%d diagnostic(s))" % len(d))

        # An explicit DAWN_STD is honoured over the launcher's default, same way.
        d = diagnostics(elsewhere, std_file,
                        env_overrides={"DAWN_STD": os.path.join(work, "no-std-here")})
        if not d:
            bad("DAWN_STD is honoured", "an explicit DAWN_STD changed nothing")
        else:
            ok("an inherited DAWN_STD wins over the launcher default")

        # ---- #314 negative controls: eager is not the same as indiscriminate --
        user = os.path.join(work, "user.dawn")
        with open(user, "w") as f:
            f.write("pub fn probe(s: String) -> Int = cursor_start(s)\n")
        d = diagnostics(elsewhere, user)
        if not d or "cursor_start" not in messages(d):
            bad("user code may not call a std-only name",
                "expected an undefined-function diagnostic, got: %s" % messages(d))
        else:
            ok("user code calling cursor_start is still refused")

        impostor_dir = os.path.join(work, "proj", "src", "std")
        os.makedirs(impostor_dir)
        impostor = os.path.join(impostor_dir, "cursor.dawn")
        shutil.copyfile(std_file, impostor)
        d = diagnostics(elsewhere, impostor)
        if not d:
            bad("a project file named src/std/cursor.dawn is not std",
                "it was accepted as the bundled std/cursor")
        else:
            ok("a project file at src/std/cursor.dawn is still rejected")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if failures:
        print("\nlsp-std-resolution: %d assertion(s) failed" % len(failures), file=sys.stderr)
        return 1
    print("\nlsp-std-resolution: OK")
    return 0


sys.exit(main())
