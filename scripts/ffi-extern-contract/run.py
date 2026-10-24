#!/usr/bin/env python3
"""Hold extern syntax, checking, backend selection and borrowing end to end.

F1 intentionally has no manifest C-source support. Compile the generated C
and our public-header-only stub together, then compare all three targets to
an independent transcript. Mutants must fail for their owning assertion or
ASan use-after-free; an unrelated build or runtime failure never counts.
"""
import importlib.util
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "scripts/ffi-extern-contract"
DAWN = str(ROOT / "bin/dawn")
CC = os.environ.get("CC", "cc")
WCC = os.environ.get("DAWN_WASM_CC", "clang-20")
FLAGS = ["-std=c11", "-O1", "-g", "-fwrapv", "-fexceptions", "-fno-strict-aliasing", "-ffp-contract=off", "-pthread",
         "-Wno-parentheses-equality", "-I", str(ROOT / "runtime/c")]
SAN = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-sanitize-recover=undefined"]
ENV = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")


def run(args, *, good=True, env=None):
    r = subprocess.run(list(map(str, args)), cwd=ROOT, capture_output=True, text=True, env=env)
    if good and r.returncode:
        raise AssertionError(f"command failed ({r.returncode}): {args}\n{r.stdout}{r.stderr}")
    return r


def ok(label):
    print("OK  " + label, flush=True)


def red(work, name, source, message, command="check"):
    p = work / (name.replace("-", "_") + ".dawn")
    p.write_text("# Each refusal names the boundary it is meant to exercise.\n" + source)
    r = run([DAWN, command, p], good=False)
    assert r.returncode and message in r.stdout + r.stderr, (name, r.returncode, r.stdout, r.stderr)
    ok("control: " + name + " rejected for " + message)


def compile_c(source, out, flags):
    run([CC, *FLAGS, *flags, source, HERE / "stub.c", ROOT / "runtime/c/dawn_rt.c", "-lm", "-o", out])


def transcript(r):
    assert r.stdout == (HERE / "expected.txt").read_text(), r.stdout
    assert r.stderr == "", r.stderr


def lsp_contract(work):
    # Reuse framing/session helpers, not the assertions of the older corpus.
    spec = importlib.util.spec_from_file_location("semantic_contract", ROOT / "scripts/lsp-semantic-tokens.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    source = 'fn f(x: Int) -> Int !io = extern c "f" else x + 1\npub fn main() -> Unit !io = println(show(f(2)))\n'
    path = work / "editor.dawn"
    path.write_text(source)
    s = helper.Session([DAWN, "lsp"], str(work), os.environ.copy())
    try:
        uri = path.as_uri()
        s.notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": "dawn", "version": 1, "text": source}})
        pos = helper.utf16_position(source, source.index("f(2)"))
        hover = s.request("textDocument/hover", {"textDocument": {"uri": uri}, "position": pos})
        assert 'extern c "f"' in str(hover) and "fallback on the JVM backend" in str(hover), hover
        tokens = s.request("textDocument/semanticTokens/full", {"textDocument": {"uri": uri}})
        decoded = helper.decode(source, tokens["data"], s.provider["legend"])
        fallback_col = source.index("else x") + len("else ")
        assert any(token[0][0:2] == ("x", "parameter") and token[1] == (0, fallback_col, 1) for token in decoded), decoded
        bad = source.replace('extern c "f" else x + 1', 'extern c "f" else')
        s.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 2}, "contentChanges": [{"text": bad}]})
        reply = s.request_msg("textDocument/hover", {"textDocument": {"uri": uri}, "position": pos})
        assert "result" in reply, reply
        assert "result" in s.request_msg("textDocument/semanticTokens/full", {"textDocument": {"uri": uri}})
    finally:
        s.close()
    ok("LSP hover, fallback semantic names and malformed fallback remain responsive")


def mutants(work):
    owners = {
        "pub-open": "C extern visibility is a compiler boundary",
        "io-open": "C extern effects are explicit io and boundary types are closed",
        "symbol-open": "C extern symbols cannot enter the compiler namespace",
    }
    for name in [*owners, "borrow-drop"]:
        tree = work / name
        shutil.copytree(ROOT / "selfhost", tree / "selfhost")
        for dep in ["compiler-plan", "packages"]:
            (tree / dep).symlink_to(ROOT / dep, target_is_directory=True)
        run([sys.executable, HERE / "mutate.py", name, tree])
        if name in owners:
            r = run([DAWN, "test", tree / "selfhost/src/check/checker.dawn"], good=False)
            assert r.returncode and ("FAIL  check/checker :: " + owners[name]) in r.stdout, r.stdout + r.stderr
            ok("mutant: " + name + " turns its owning checker test red")
        else:
            jar = tree / "compiler.jar"
            run([DAWN, "build", tree / "selfhost", "-o", jar])
            source = tree / "broken.c"
            run(["java", "-XX:-UsePerfData", "-Xss512m", "-Xmx2g", "-jar", jar, "__emitc", HERE / "roundtrip.dawn", "-o", source])
            binary = tree / "broken"
            compile_c(source, binary, SAN)
            r = run([binary], good=False, env=ENV)
            assert r.returncode and "AddressSanitizer: heap-use-after-free" in r.stderr, r.stdout + r.stderr
            ok("mutant: dropping an extern's borrowed String turns ASan red (heap-use-after-free)")


def main():
    start = time.monotonic()
    run([DAWN, "--version"])
    with tempfile.TemporaryDirectory(prefix="ffi-extern.", dir=os.environ.get("TMPDIR")) as directory:
        work = Path(directory)
        # Refusals come first, each paired with an accepted case below.
        cases = [
            ("pub", 'pub fn f(x: Int) -> Int !io = extern c "f" else x\n', "an extern function cannot be `pub`"),
            ("implicit-pure", 'fn f() -> Int = extern c "f" else 1\n', "must declare exactly `!io`"),
            ("explicit-pure", 'fn f() -> Int !() = extern c "f" else 1\n', "must declare exactly `!io`"),
            ("named-effect", 'effect E { fn get() -> Int }\nfn f() -> Int !E = extern c "f" else 1\n', "must declare exactly `!io`"),
            ("effect-variable", 'fn f[!e]() -> Int !e = extern c "f" else 1\n', "must declare exactly `!io`"),
            ("symbol", 'fn f() -> Int !io = extern c "x__y" else 1\n', "invalid C extern symbol"),
            ("list", 'fn f(x: List[Int]) -> Int !io = extern c "f" else 1\n', "cannot cross a C extern"),
            ("unit-param", 'fn f(x: Unit) -> Int !io = extern c "f" else 1\n', "cannot cross a C extern"),
            ("result-error", 'fn f() -> Result[Int, String] !io = extern c "f" else Ok(1)\n', "cannot cross a C extern"),
            ("generic", 'fn f[T](x: T) -> Int !io = extern c "f" else 1\n', "cannot cross a C extern"),
            ("owned", 'fn f(owned x: String) -> Int !io = extern c "f" else 1\n', "expected `:`"),
            ("local", 'fn f() -> Int !io = { extern c "f" else 1 }\n', "whole body of a top-level function"),
            ("nested", 'fn f() -> Int !io = { fn g() -> Int !io = extern c "g" else 1\ng() }\n', "whole body of a top-level function"),
            ("impl", 'trait T[A] { fn f(a: A) -> Int !io }\nimpl T[Int] { fn f(a: Int) -> Int !io = extern c "f" else a }\n', "whole body of a top-level function"),
            ("trait", 'trait T[A] { fn f(a: A) -> Int !io = extern c "f" else 1 }\n', "whole body of a top-level function"),
            ("java", 'use java "java.lang.Math"\nfn f(x: Int) -> Int !io = extern c "f" else Math.abs(x)\n', "fallback must be portable Dawn"),
            ("fallback-type", 'fn f() -> Int !io = extern c "f" else "bad"\n', "extern fallback has type String"),
        ]
        for case in cases:
            red(work, *case)
        red(work, "jvm-no-fallback", 'fn f() -> Int !io = extern c "f"\npub fn main() -> Unit = ()\n',
            "extern function `f` has no fallback body and the JVM backend has no C", "run")
        # A legal short symbol must still be unable to bind libc itself.
        libc = work / "libc.dawn"
        libc.write_text('# Prefix isolation is checked by a real link, not a string search.\nfn f(x: Int) -> Int !io = extern c "system" else x\npub fn main() -> Unit !io = println(show(f(0)))\n')
        source = work / "libc.c"
        run([DAWN, "__emitc", libc, "-o", source])
        r = run([CC, *FLAGS, source, ROOT / "runtime/c/dawn_rt.c", "-lm", "-o", work / "libc"], good=False)
        assert r.returncode and "dawn_x_system" in r.stderr, r.stderr
        ok("control: a raw libc symbol cannot link through the dawn_x_ namespace")
        source = work / "roundtrip.c"
        run([DAWN, "__emitc", HERE / "roundtrip.dawn", "-o", source])
        generated = source.read_text()
        assert "fallback_int" not in generated, "native retained a fallback-only function"
        for name in ["add", "text", "blob", "result", "option", "float", "bool", "unit"]:
            assert sum(line.startswith("extern ") and " DAWN_EXTERN(f1_" + name + ")(" in line for line in generated.splitlines()) == 1
        assert "extern dawn_bytes* DAWN_EXTERN(f1_blob)(dawn_bytes*);" in generated
        # Omit exactly the caller's release of the String lent to f1_text.
        # Null the owned slot as usual so frame cleanup cannot hide the leak.
        head, body = generated.split("dawn_unit dawn_roundtrip__main(void) {", 1)
        call = re.search(r"dawn_roundtrip__text\(\(\(dawn_str\*\)dawn_own\[(\d+)\]\)\)", body)
        assert call, "the borrowed String call has no owned root"
        slot = "dawn_own[" + call.group(1) + "]"
        release = "dawn_drop(" + slot + "); " + slot + " = NULL;"
        main_body, rest = body.split("\n}\n", 1)
        assert main_body.count(release) == 1
        leaky = work / "leaky.c"
        leaky.write_text(head + "dawn_unit dawn_roundtrip__main(void) {" +
                         main_body.replace(release, slot + " = NULL;") + "\n}\n" + rest)
        compile_c(leaky, work / "leaky", SAN)
        leak = run([work / "leaky"], good=False, env=ENV)
        assert leak.returncode and "LeakSanitizer: detected memory leaks" in leak.stderr, leak.stdout + leak.stderr
        ok("control: omitting one post-borrow release turns ASan/LSan red (leak)")
        for label, flags in [("plain", []), ("inline", ["-O2", "-DDAWN_RT_INLINE_RC"]), ("san", SAN)]:
            binary = work / label
            compile_c(source, binary, flags)
            transcript(run([binary], env=ENV))
            ok("native " + label + ": independent transcript; borrowed inputs survive; owned results released")
        transcript(run([DAWN, "run", HERE / "roundtrip.dawn"]))
        ok("JVM fallback: independent transcript without a linked C stub")
        dumpdir = work / "core"
        run([DAWN, "__lower", "--dump", dumpdir, HERE / "roundtrip.dawn"])
        dumped = "\n".join(p.read_text() for p in dumpdir.rglob("*") if p.is_file())
        assert "extern c f1_text" in dumped, dumped[-1000:]
        ok("Core dump retains CExtern")
        probe = run([WCC, "--target=wasm32-wasip1", "-print-file-name=crt1.o"], good=False)
        triple = "wasm32-wasip1" if probe.returncode == 0 and probe.stdout.strip() != "crt1.o" and Path(probe.stdout.strip()).is_file() else "wasm32-wasi"
        for suffix, lang in [("eh.cc", ["-x", "c++", "-std=c++14", "-fno-rtti", "-fwasm-exceptions"]), ("tag.c", ["-std=c11"])]:
            run([WCC, "--target=" + triple, "-O1", *lang, "-c", ROOT / ("runtime/c/dawn_rt_wasi_" + suffix), "-o", work / (suffix + ".o")])
        wasm = work / "roundtrip.wasm"
        run([WCC, "--target=" + triple, "-std=c11", "-O1", "-fwrapv", "-fwasm-exceptions", "-fno-strict-aliasing", "-ffp-contract=off",
             "-Wno-parentheses-equality", "-I", ROOT / "runtime/c", source, HERE / "stub.c", ROOT / "runtime/c/dawn_rt.c",
             work / "eh.cc.o", work / "tag.c.o", "-lm", "-o", wasm])
        r = run(["node", "--no-warnings", ROOT / "scripts/wasm-contract/runwasi.mjs", wasm])
        transcript(r)
        ok("wasm: same C stub and independent transcript")
        lsp_contract(work)
        if "--no-mutants" not in sys.argv:
            mutants(work)
    print(f"ffi extern contract: OK ({time.monotonic() - start:.1f}s)", flush=True)

if __name__ == "__main__":
    main()
