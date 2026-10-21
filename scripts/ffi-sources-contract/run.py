#!/usr/bin/env python3
"""Keep package C inputs, header isolation and backend selection observable.

Fixtures are generated in a private tree; F1's independent transcript remains
our value/ownership oracle. Every refusal and the collection mutant precede
the corresponding positive builds, and compiler failures must name a cause.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "scripts/ffi-sources-contract"
F1 = ROOT / "scripts/ffi-extern-contract"
DAWN = ROOT / "bin/dawn"
REAL_CC = shutil.which(os.environ.get("CC", "cc"))
REAL_WCC = shutil.which(os.environ.get("DAWN_WASM_CC", "clang-20"))
EXPECTED = (F1 / "expected.txt").read_text()


def run(args, *, env=None, good=True):
    r = subprocess.run(list(map(str, args)), cwd=ROOT, env=env, capture_output=True, text=True)
    if good and r.returncode:
        raise AssertionError(f"command failed ({r.returncode}): {args}\n{r.stdout}{r.stderr}")
    return r


def ok(message):
    print("OK  " + message, flush=True)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def manifest(name, sources=(), deps=""):
    return f'schema = 1\nname = "{name}"\nversion = "1.0.0"\n' + deps + (
        "\n[native]\nsources = " + json.dumps(list(sources)) + "\n" if sources else "")


def fixtures(work):
    leaf, mid, app = (work / n for n in ["leaf", "mid", "app"])
    write(leaf / "dawn.toml", manifest("leaf", ["src/stub.c", "src/a/stub.c", "src/b/stub.c"]))
    dawn = (F1 / "roundtrip.dawn").read_text().replace("pub fn main()", "pub fn exercise()")
    dawn += '\npub fn marker() -> Int = 0\n' + '''fn a() -> Int !io = extern c "f2_a" else 11
fn b() -> Int !io = extern c "f2_b" else 22
test "package native inputs" {
  assert add(1) == 12
  assert a() == 11
  assert b() == 22
}
'''
    write(leaf / "src/api.dawn", dawn)
    stub = (F1 / "stub.c").read_text().replace('#include "dawn_ffi.h"', '#include "dawn_ffi.h"\n#include "nested/api.h"')
    write(leaf / "src/stub.c", stub.replace("x + 11", "x + F2_ADD"))
    write(leaf / "src/nested/api.h", '/* Preserve nested includes and search this package first. */\n#include "sqlite3.h"\n')
    write(leaf / "src/sqlite3.h", "/* A host sqlite3.h cannot supply this fixture value. */\n#define F2_ADD 11\n")
    write(leaf / "src/local.h", "/* The package root is a per-TU include directory. */\n#define F2_VALUE 11\n")
    write(leaf / "src/b/local.h", "/* This basename must not overwrite the package root. */\n#define F2_VALUE 22\n")
    for sub in ["a", "b"]:
        write(leaf / f"src/{sub}/stub.c", f'#include "dawn_ffi.h"\n#include "local.h"\nint64_t DAWN_EXTERN(f2_{sub})(void) {{ return F2_VALUE; }}\n')
    write(leaf / "src/unlisted.c", "#error an unlisted C input must not be compiled\n")
    write(mid / "dawn.toml", manifest("mid", ["src/stub.c"], '\n[deps]\nleaf = "../leaf"\n'))
    write(mid / "src/api.dawn", '''# Keep the C package transitive, alongside a second path to its leaf.
use leaf/api
fn number() -> Int !io = extern c "f2_mid" else 9
pub fn exercise() -> Unit !io = { if number() != 9 { panic("mid header") }
  api.exercise()
}
''')
    write(mid / "src/stub.c", '#include "dawn_ffi.h"\n#include "local.h"\nint64_t DAWN_EXTERN(f2_mid)(void) { return F2_VALUE; }\n')
    write(mid / "src/local.h", "/* Another package owns a different local.h. */\n#define F2_VALUE 9\n")
    write(work / "unused/dawn.toml", manifest("unused", ["src/poison.c"]))
    write(work / "unused/src/poison.c", "#error unused dependency compiled\n")
    write(work / "unused/src/api.dawn", "pub fn unused() -> Int = 0\n")
    write(app / "dawn.toml", manifest("app", ["src/stub.c"], '\n[deps]\nmid = "../mid"\nleaf = "../leaf"\nunused = "../unused"\n'))
    write(app / "src/main.dawn", '''# The direct and transitive leaf imports must share one C compilation.
use mid/api
use leaf/api as leaf
fn number() -> Int !io = extern c "f2_root" else 7
pub fn main() -> Unit !io = { if number() != 7 { panic("root header") }
  if leaf.marker() != 0 { panic("leaf import") }
  api.exercise()
}
test "root and dependencies" { assert number() == 7 }
''')
    write(app / "src/stub.c", '#include "dawn_ffi.h"\n#include "local.h"\n#ifdef __wasi__\nint64_t DAWN_EXTERN(f2_root)(void) { return F2_VALUE; }\n#else\nint64_t DAWN_EXTERN(f2_root)(void) { return F2_VALUE; }\n#endif\n')
    write(app / "src/local.h", "/* Root headers cannot overwrite dependency headers. */\n#define F2_VALUE 7\n")
    return app, mid, leaf


def compiler_wrapper(work):
    wrapper = work / "cc-wrapper"
    write(wrapper, '''#!/usr/bin/env python3
# Record actual compiler argv and optionally remove the staged public header.
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
wasm = any(a.startswith("--target=wasm") for a in args)
with open(os.environ["F2_CC_LOG"], "a") as stream:
    stream.write(json.dumps(args) + "\\n")
if os.environ.get("F2_BREAK_HEADER") and "-c" in args and any("/native/" in a and a.endswith(".c") for a in args):
    (pathlib.Path(args[args.index("-I") + 1]) / "dawn_ffi.h").unlink(missing_ok=True)
flags = []
if os.environ.get("F2_SAN") and not wasm:
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-sanitize-recover=undefined", "-g"]
sys.exit(subprocess.call([os.environ["F2_REAL_WCC" if wasm else "F2_REAL_CC"], *flags, *args]))
''')
    wrapper.chmod(0o755)
    return wrapper


def entries(env):
    path = Path(env["F2_CC_LOG"])
    return [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []


def reset_log(env):
    Path(env["F2_CC_LOG"]).write_text("")


def reject(driver, app, env, label, message, *, before_cc=True):
    reset_log(env)
    r = run([driver, "build", app, "-o", app.parent / "rejected"], env=env, good=False)
    assert r.returncode and message in r.stdout + r.stderr, (label, r.returncode, r.stdout, r.stderr)
    if before_cc:
        assert entries(env) == [], (label, entries(env))
    ok("control: " + label + " rejected for " + message)


def controls(driver, app, mid, leaf, work, env):
    m = app / "dawn.toml"
    original = m.read_text()
    for label, old, new, message in [
        ("missing-file", "src/stub.c", "src/missing.c", "native source does not exist"),
        ("parent-segment", "src/stub.c", "src/../stub.c", "invalid native source"),
        ("absolute-source", "src/stub.c", "/src/stub.c", "invalid native source"),
        ("duplicate-source", '["src/stub.c"]', '["src/stub.c", "src/stub.c"]', "duplicate native source"),
        ("unknown-key", "sources =", "libs =", "unknown key `libs` in `[native]`"),
    ]:
        m.write_text(original.replace(old, new))
        reject(driver, app, env, label, message)
        m.write_text(original)
    stub = app / "src/stub.c"
    body = stub.read_text()
    stub.write_text(body + "int64_t DAWN_EXTERN(f2_mid)(void) { return 9; }\n")
    reject(driver, app, env, "two-package-symbol", "duplicate native symbol `f2_mid`")
    stub.write_text(body.replace("int64_t DAWN_EXTERN(f2_root)", "bool DAWN_EXTERN(f2_root)"))
    reject(driver, app, env, "C-signature", "inconsistent native signature for `f2_root`")
    stub.write_text("/* This source defines no stub. */\n")
    reject(driver, app, env, "missing-stub", "extern `f2_root` needs the package")
    stub.write_text(body)
    main = app / "src/main.dawn"
    main_body = main.read_text()
    main.write_text(main_body + '\nfn conflicting(x: Float) -> Float !io = extern c "f2_root" else x\n')
    reject(driver, app, env, "Dawn-signature", "inconsistent native signature for `f2_root`")
    main.write_text(main_body)
    standalone = work / "standalone.dawn"
    standalone.write_text('# A single file has no manifest.\nfn f() -> Int !io = extern c "f2_absent" else 0\npub fn main() -> Unit !io = println(show(f()))\n')
    reject(driver, standalone, env, "no-manifest", "extern `f2_absent` needs the package")
    for path in [app / "src/stub.c", app / "src/local.h"]:
        text = path.read_text()
        outside = work / "outside"
        outside.write_text(text)
        path.unlink()
        path.symlink_to(outside)
        reject(driver, app, env, "symlink-" + path.suffix, "symbolic link in package tree")
        path.unlink()
        path.write_text(text)
    nested = leaf / "src/nested"
    nested.rename(leaf / "saved-nested")
    nested.symlink_to(leaf / "saved-nested", target_is_directory=True)
    reject(driver, app, env, "symlink-directory", "symbolic link in package tree")
    nested.unlink()
    (leaf / "saved-nested").rename(nested)
    (mid / "src").rename(mid / "saved-src")
    (mid / "src").symlink_to(mid / "saved-src", target_is_directory=True)
    reject(driver, app, env, "symlink-src-root", "symbolic link in native package tree")
    (mid / "src").unlink()
    (mid / "saved-src").rename(mid / "src")
    reject(driver, app, dict(env, F2_BREAK_HEADER="1"), "missing-staged-ffi-header", "dawn_ffi.h", before_cc=False)


def collection_mutant(app, work, env):
    tree = work / "omit-transitive"
    shutil.copytree(ROOT / "selfhost", tree / "selfhost")
    for dep in ["compiler-plan", "packages"]:
        (tree / dep).symlink_to(ROOT / dep, target_is_directory=True)
    run([sys.executable, HERE / "mutate.py", "omit-transitive", tree])
    jar = tree / "mutant.jar"
    run([DAWN, "build", tree / "selfhost/src/nmain.dawn", "-o", jar])
    reset_log(env)
    r = run(["java", "-Xss512m", "-Xmx2g", "-jar", jar, "build", app, "-o", work / "mutant"], env=env, good=False)
    assert r.returncode and "extern `f1_add` needs the package" in r.stdout + r.stderr, r.stdout + r.stderr
    assert entries(env) == []
    ok("mutant: omitting the transitive leaf collection fails its real build before cc")


def transcript(result):
    assert result.stdout == EXPECTED, (result.stdout, EXPECTED, result.stderr)
    assert result.stderr == "", result.stderr


def compiled_sources(env, *, inline, wasm=False):
    rows = entries(env)
    stubs = [r for r in rows if "-c" in r and any("/native/" in a and a.endswith(".c") for a in r)]
    assert len(stubs) == 5, stubs
    paths = [next(a for a in r if a.endswith(".c")) for r in stubs]
    assert len(paths) == len(set(paths)), paths
    assert [Path(p).relative_to(Path(p).parents[2]).as_posix() for p in paths if "/a/" in p or "/b/" in p] == ["src/a/stub.c", "src/b/stub.c"]
    for row in stubs:
        for flag in ["-std=c11", "-fwrapv", "-fno-strict-aliasing", "-O2"]:
            assert flag in row, row
        assert ("-DDAWN_RT_INLINE_RC" in row) == inline, row
        assert any(a.startswith("--target=wasm") for a in row) == wasm, row
        if wasm:
            assert "-fwasm-exceptions" in row, row
    assert not any("unlisted.c" in a or "poison.c" in a for r in rows for a in r)
    return [p.split("/src/", 1)[1] for p in paths]


def positives(driver, app, leaf, work, env):
    reference_order = None
    for label, extra, inline in [("plain", {"DAWN_NO_INLINE_RC": "1"}, False),
                                  ("inline", {"DAWN_NO_INLINE_RC": ""}, True),
                                  ("san", {"DAWN_NO_INLINE_RC": "1", "F2_SAN": "1"}, False),
                                  ("san-inline", {"DAWN_NO_INLINE_RC": "", "F2_SAN": "1"}, True)]:
        current = dict(env, **extra)
        reset_log(env)
        binary = work / label
        run([driver, "build", app, "-o", binary], env=current)
        order = compiled_sources(env, inline=inline)
        if reference_order is None:
            reference_order = order
        assert order == reference_order
        transcript(run([binary], env=current))
        ok("native " + label + ": F1 transcript, isolated headers, stable diamond collection")
    reset_log(env)
    transcript(run([driver, "run", app], env=env))
    compiled_sources(env, inline=True)
    ok("run uses the same package C source plan")
    for target in [app, leaf]:
        reset_log(env)
        r = run([driver, "test", target], env=dict(env, F2_SAN="1"))
        assert "test(s) passed" in r.stdout and "FAIL" not in r.stdout, r.stdout + r.stderr
        assert any("/native/" in a for row in entries(env) for a in row)
    ok("package and dependency tests compile their stubs under ASan/UBSan/LSan")
    reset_log(env)
    emitted = work / "manual.c"
    r = run([driver, "emitc", app, "-o", emitted], env=env)
    assert r.stdout == "" and "DAWN_EXTERN(f1_add)" in emitted.read_text()
    for path in [app / "src/stub.c", leaf / "src/stub.c", leaf / "src/a/stub.c", leaf / "src/b/stub.c"]:
        assert "note: native source: " + str(path) in r.stderr, r.stderr
    assert "headers: " + str(leaf / "src") in r.stderr
    assert entries(env) == []
    ok("manual emitc reports package sources and include directories without invoking cc")
    reset_log(env)
    wasm = work / "path.wasm"
    run([driver, "build", "--target", "wasm", app, "-o", wasm], env=env)
    compiled_sources(env, inline=False, wasm=True)
    transcript(run(["node", "--no-warnings", ROOT / "scripts/wasm-contract/runwasi.mjs", wasm], env=env))
    ok("wasm compiles every actual package stub and runs the F1 transcript")
    reset_log(env)
    transcript(run([DAWN, "run", app], env=env))
    for target in [app, leaf]:
        r = run([DAWN, "test", target], env=env)
        assert "test(s) passed" in r.stdout, r.stdout + r.stderr
    assert entries(env) == []
    c_inputs = [path for path in leaf.rglob("*.c")]
    for path in c_inputs:
        path.rename(path.with_suffix(".hidden"))
    transcript(run([DAWN, "run", app], env=env))
    for path in c_inputs:
        path.with_suffix(".hidden").rename(path)
    native_only = leaf / "src/api.dawn"
    original = native_only.read_text()
    native_only.write_text(original.replace('extern c "f1_add" else fallback_int(x)', 'extern c "f1_add"'))
    r = run([DAWN, "run", app], env=env, good=False)
    assert r.returncode and "has no fallback body and the JVM backend has no C" in r.stdout + r.stderr
    native_only.write_text(original)
    assert entries(env) == []
    ok("JVM uses transitive package fallbacks, refuses absent fallbacks and never invokes cc")


def url_contract(driver, app, leaf, work, env):
    archive_tree = work / "archive"
    shutil.copytree(leaf, archive_tree / "packages/leaf")
    hash = run([DAWN, "__pkghash", archive_tree], env=env).stdout.strip()
    assert hash.startswith("d1:") and len(hash) == 67, hash
    archive = work / "sources.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(archive_tree, arcname="bundle")
    url_app = work / "urlapp"
    shutil.copytree(app, url_app)
    write(url_app / "dawn.toml", manifest("urlapp", ["src/stub.c"], f'''\n[deps.leaf]
url = "{archive.as_uri()}"
version = "1.0.0"
hash = "{hash}"
subdir = "packages/leaf"
'''))
    write(url_app / "src/main.dawn", '''# The identical leaf is consumed through url plus subdir.
use leaf/api
fn number() -> Int !io = extern c "f2_root" else 7
pub fn main() -> Unit !io = { if number() != 7 { panic("root header") }
  api.exercise()
}
''')
    # A one-byte C or header change must invalidate the declared d1 lock.
    cached = Path(env["DAWN_PKG_CACHE"]) / ("d1-" + hash[3:])
    run([driver, "check", url_app], env=env)
    assert (cached / "packages/leaf/src/stub.c").is_file(), list(cached.rglob("*"))
    for rel in ["stub.c", "nested/api.h"]:
        path = cached / "packages/leaf/src" / rel
        original = path.read_bytes()
        path.write_bytes(original[:-1] + b" ")
        reset_log(env)
        r = run([driver, "build", url_app, "-o", work / "rejected-url"], env=env, good=False)
        assert entries(env) == []
        assert r.returncode and ("hash mismatch" in r.stdout + r.stderr or "does not match its own name" in r.stdout + r.stderr), r.stdout + r.stderr
        path.write_bytes(original)
        ok("control: one byte in url " + rel + " fails the d1 lock")
    before = run([driver, "version", "-m", url_app], env=env).stdout
    for rel in ["stub.c", "nested/api.h"]:
        path = archive_tree / "packages/leaf/src" / rel
        original = path.read_bytes()
        path.write_bytes(original[:-1] + b" ")
        changed_hash = run([DAWN, "__pkghash", archive_tree], env=env).stdout.strip()
        assert changed_hash != hash
        # Build information's s1/b1 check uses a path package so the changed
        # content can be read after the url lock has correctly refused it.
        local_manifest = manifest("urlapp", ["src/stub.c"], f'\n[deps]\nleaf = "{archive_tree / "packages/leaf"}"\n')
        url_manifest = (url_app / "dawn.toml").read_text()
        (url_app / "dawn.toml").write_text(local_manifest)
        changed = run([driver, "version", "-m", url_app], env=env).stdout
        path.write_bytes(original)
        unchanged = run([driver, "version", "-m", url_app], env=env).stdout
        assert changed != unchanged and "s1:" in changed and "b1:" in changed, (before, changed, unchanged)
        (url_app / "dawn.toml").write_text(url_manifest)
        ok("one byte in " + rel + " changes d1, source s1 and build b1")
    for wasm in [False, True]:
        out = work / ("url.wasm" if wasm else "url-native")
        run([driver, "build", *(["--target", "wasm"] if wasm else []), url_app, "-o", out], env=env)
        command = ["node", "--no-warnings", ROOT / "scripts/wasm-contract/runwasi.mjs", out] if wasm else [out]
        transcript(run(command, env=env))
    reset_log(env)
    transcript(run([DAWN, "run", url_app], env=env))
    assert entries(env) == []
    ok("url plus subdir: same package builds and runs on native, wasm and JVM")


def main():
    start = time.monotonic()
    run([DAWN, "--version"])
    assert REAL_CC and REAL_WCC, "native and WASI C compilers are required"
    with tempfile.TemporaryDirectory(prefix="ffi-sources.", dir=os.environ.get("TMPDIR")) as directory:
        work = Path(directory)
        driver = os.environ.get("DAWNC_BIN")
        if not driver:
            driver = work / "dawnc"
            run([DAWN, "__emitc", ROOT / "selfhost/src/nmain.dawn", "--split", work / "units"])
            run([ROOT / "scripts/cc-units.sh", "-o", driver, work / "units"])
        app, mid, leaf = fixtures(work)
        wrapper = compiler_wrapper(work)
        stage = work / "stage"
        stage.mkdir()
        env = dict(os.environ, CC=str(wrapper), DAWN_WASM_CC=str(wrapper), F2_CC_LOG=str(work / "cc.jsonl"),
                   F2_REAL_CC=REAL_CC, F2_REAL_WCC=REAL_WCC, DAWN_PKG_CACHE=str(work / "cache"),
                   TMPDIR=str(stage), ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
        controls(driver, app, mid, leaf, work, env)
        if "--no-mutant" not in sys.argv:
            collection_mutant(app, work, env)
        positives(driver, app, leaf, work, env)
        url_contract(driver, app, leaf, work, env)
    print(f"ffi sources contract: OK ({time.monotonic() - start:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
