#!/usr/bin/env python3
"""Test SQLite through real Dawn code, package manifests and the public ABI.

Native and backend legs fit their existing CI jobs. Sanitized SQLite is built
once per compiler/target/source/options key, reused by both RC configurations
and all mutants; cold caches run the same assertions. Every mutant must build
successfully before a named assertion or sanitizer cause can kill it.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

from fixtures import LOCK, digest, prepare, prepare_engine

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "scripts/sqlite-contract"
PACKAGE = ROOT / "packages/sqlite"
DAWN = ROOT / "bin/dawn"
CC = shutil.which(os.environ.get("CC", "clang-20")) or shutil.which("cc")
SAN = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-sanitize-recover=undefined", "-g"]


def run(args, *, env=None, good=True, cwd=None):
    r = subprocess.run(list(map(str, args)), cwd=cwd or ROOT, env=env, capture_output=True, text=True)
    if good and r.returncode:
        raise AssertionError(f"command failed ({r.returncode}): {args}\n{r.stdout}{r.stderr}")
    return r


def ok(message):
    print("OK  " + message, flush=True)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def engine(work, cache, sanitized, key="sqlite"):
    flags = ["-std=c11", "-O1", "-fPIC", "-shared", "-DSQLITE_ENABLE_FTS5", * (SAN if sanitized else [])]
    identity = {"source": LOCK[key]["source_sha256"], "compiler": str(Path(CC).resolve()),
                "version": run([CC, "--version"]).stdout, "target": run([CC, "-dumpmachine"]).stdout,
                "flags": flags}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    target = cache / "engine" / key
    target.mkdir(parents=True, exist_ok=True)
    library = target / "libsqlite3.so.0"
    with (target / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        info = target / "artifact.json"
        if library.exists() and info.exists() and json.loads(info.read_text()).get("sha256") == digest(library):
            ok("engine cache hit: " + ("san" if sanitized else "plain"))
        else:
            start = time.monotonic()
            partial = target / "engine.tmp.so"
            run([CC, *flags, work / "sqlite3.c", "-lm", "-o", partial])
            partial.replace(library)
            info.write_text(json.dumps({"identity": identity, "sha256": digest(library)}, sort_keys=True))
            ok(f"engine cold compile: {'san' if sanitized else 'plain'} {time.monotonic() - start:.2f}s")
    return library


def wrapper(work):
    path = work / "cc-wrapper"
    write(path, '''#!/usr/bin/env python3
# The driver still chooses every input and option; add instrumentation to all TUs.
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["F3_CC_LOG"], "a") as f:
    f.write(json.dumps(args) + "\\n")
flags = []
if os.environ.get("F3_SAN"):
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-sanitize-recover=undefined", "-g"]
if "-c" not in args and os.environ.get("F3_LOADER_OBJECT"):
    flags += [os.environ["F3_LOADER_OBJECT"], "-Wl,--wrap=dlopen,--wrap=dlsym"]
sys.exit(subprocess.call([os.environ["F3_REAL_CC"], *flags, *args]))
''')
    path.chmod(0o755)
    return path


def native_package(work, name, simple, probe, mode="all"):
    tree = work / name
    shutil.copytree(PACKAGE, tree / "packages/sqlite")
    pkg = tree / "packages/sqlite"
    native = (HERE / "native.dawn").read_text()
    if mode in ("fts", "commit"):
        native = native[:native.index("pub fn main()")]
        native += '''pub fn main() -> Unit !io = {
  let result: Result[Unit, ForeignError] = with_db(":memory:", db => {
    FOCUSED_CALL
    Ok(())
  })
  demand(result)
  println("sqlite native: OK")
}
'''.replace("FOCUSED_CALL", "exercise_fts(db, simple_path(), probe_path())" if mode == "fts" else "exercise_commit_failure(db)")
    source = pkg / "src/sqlite.dawn"
    source.write_text(source.read_text() + "\n" + native + "\n" + (HERE / "fts.dawn").read_text() +
                      '\nfn simple_path() -> String = ' + json.dumps(str(simple)) +
                      '\nfn probe_path() -> String = ' + json.dumps(str(probe)) +
                      '\nfn test_path() -> String = ' + json.dumps(str(tree / "fixture.db")) + "\n")
    return tree, pkg


def build(driver, pkg, binary, env, inline=False, sanitized=False):
    current = dict(env, DAWN_NO_INLINE_RC="" if inline else "1", F3_SAN="1" if sanitized else "")
    Path(env["F3_CC_LOG"]).write_text("")
    run([driver, "build", pkg / "src/sqlite.dawn", "-o", binary], env=current)
    rows = [json.loads(line) for line in Path(env["F3_CC_LOG"]).read_text().splitlines()]
    stubs = [row for row in rows if "-c" in row and any(a.endswith("sqlite_stub.c") for a in row)]
    assert len(stubs) == 1, rows
    assert ("-DDAWN_RT_INLINE_RC" in stubs[0]) == inline, stubs
    return current


def execute(binary, env, loader, library=None, mode=None, good=True):
    current = dict(env)
    if library:
        current["F3_SQLITE_LIBRARY"] = str(library)
    if mode:
        current["F3_LOADER_MODE"] = mode
    return run([binary], env=current, good=good, cwd=binary.parent)


def native(driver, work, cache, env):
    simple = prepare(cache / "downloads", work)
    probe = work / "sql_gate.so"
    loader = work / "loader.o"
    run([CC, "-shared", "-fPIC", "-I", work, HERE / "sql_gate.c", "-o", probe])
    run([CC, "-c", HERE / "loader.c", "-o", loader])
    env = dict(env, F3_LOADER_OBJECT=str(loader))
    plain = engine(work, cache, False)
    san = engine(work, cache, True)
    baseline_source = work / "baseline-source"
    prepare_engine(cache / "downloads", baseline_source, "baseline")
    baseline = engine(baseline_source, cache, False, "baseline")
    # The two loader failures are standalone executions of the actual open entry.
    tree = work / "loader-failures"
    shutil.copytree(PACKAGE, tree)
    source = tree / "src/sqlite.dawn"
    source.write_text(source.read_text() + '''
pub fn main() -> Unit !io = match sq_open(":memory:", false) {
  Err(e) -> println(e.kind)
  Ok(db) -> { let _ = sq_close(db)
    panic("loader unexpectedly accepted") }
}
''')
    binary = work / "loader-check"
    current = build(driver, tree, binary, env)
    for mode, expected in [("no-library", "sqlite.no_library"), ("no-symbol", "sqlite.no_symbol")]:
        r = execute(binary, current, loader, mode=mode)
        assert r.stdout == expected + "\n" and r.stderr == "", (mode, r.stdout, r.stderr)
        ok("loader failure Result: " + expected)
    failures = {
        "static": r"AddressSanitizer: heap-use-after-free",
        "column-delayed": r"AddressSanitizer: heap-use-after-free",
        "leak-finalize": r"LeakSanitizer: detected memory leaks",
        "double-finalize": r"AddressSanitizer: (heap-use-after-free|attempting double-free)|sqlite3.c:[0-9]+:[0-9]+: runtime error:",
        "stale-token": "panic: token-not-reused",
        "parent": "panic: parent-handle: accepted",
        "row-state": "panic: column-before-row: sqlite.no_memory",
        "bind-range": "panic: wide-bind: sqlite.error",
        "column-range": "panic: negative-column: accepted",
        "utf8": "panic: utf8: accepted",
        "text-nul": "panic: value-5",
        "int-width": "panic: value-0",
        "null": "panic: value-6",
        "empty-label": "panic: sqlite.statement_state",
        "path-nul": "panic: nul-path: accepted",
        "sql-nul": "panic: nul-sql: accepted",
        "entry-nul": "panic: nul-entry: sqlite.extension",
        "empty-path": "panic: sqlite.embedded_nul",
        "autocommit": "panic: error-data-rollback",
        "panic-rollback": "panic: panic-rollback",
        "commit-rollback": "panic: commit-error-rollback",
        "nested-rollback": "panic: nested: accepted",
        "sql-load": "sql load_extension was enabled during C loading",
        "no-simple": "no such tokenizer: simple",
        "swallow-extension": "panic: empty-entry: accepted",
    }
    for name, expected in failures.items():
        mode = "fts" if name == "no-simple" else "commit" if name == "commit-rollback" else "all"
        tree, pkg = native_package(work, "mutant-" + name, simple, probe, mode)
        run([sys.executable, HERE / "mutate.py", name, tree])
        # A mutant compiler or C syntax failure is never evidence of detection.
        binary = tree / "program"
        current = build(driver, pkg, binary, env, sanitized=True)
        r = execute(binary, current, loader, san, good=False)
        log_dir = Path(os.environ.get("SQLITE_CONTRACT_LOG_DIR", work))
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / (name + ".log")).write_text(r.stdout + r.stderr)
        assert r.returncode and re.search(expected, r.stdout + r.stderr), (name, expected, r.returncode, r.stdout, r.stderr)
        ok("negative control " + name + ": exit " + str(r.returncode) + ", " + expected)
    cleanup_pkg = work / "cleanup-panic"
    shutil.copytree(PACKAGE, cleanup_pkg)
    source = cleanup_pkg / "src/sqlite.dawn"
    source.write_text(source.read_text() + "\n" + (HERE / "cleanup_panic.dawn").read_text())
    binary = work / "cleanup-panic-program"
    current = build(driver, cleanup_pkg, binary, env, sanitized=True)
    r = execute(binary, current, loader, san)
    assert r.stdout == "cleanup panic preserved\n", (r.stdout, r.stderr)
    assert r.stderr.startswith("sqlite cleanup: sqlite.invalid_handle: ") and r.stderr.count("\n") == 1, r.stderr
    ok("panic cleanup failure is reported while the original panic survives")
    # Only after proving each detector can turn red do we accept the originals.
    for label, library, sanitized, inline in [("plain", None, False, False), ("baseline", baseline, False, False), ("inline", plain, False, True),
                                                ("san", san, True, False), ("san-inline", san, True, True)]:
        tree, pkg = native_package(work, "positive-" + label, simple, probe)
        binary = tree / "program"
        current = build(driver, pkg, binary, env, inline=inline, sanitized=sanitized)
        r = execute(binary, current, loader, library)
        assert r.stdout == "sqlite native: OK\n" and r.stderr == "", (r.stdout, r.stderr)
        ok("native " + label + ": values, handles, cleanup, transactions, WAL/BUSY and real simple FTS")


def fallback_package(work, name):
    tree = work / name
    pkg = tree / "packages/sqlite"
    shutil.copytree(PACKAGE, pkg)
    source = pkg / "src/sqlite.dawn"
    text = source.read_text()
    entries = re.findall(r'fn (sq_[a-z_]+)\(([^\n]*)\) -> Result\[([^\n]+), ForeignError\] !io =\s*extern c "(sqlite_[a-z_]+)" else', text)
    c_symbols = set(re.findall(r'DAWN_EXTERN\((sqlite_[a-z_]+)\)', (pkg / "src/sqlite_stub.c").read_text()))
    assert entries and {row[3] for row in entries} == c_symbols, "every extern and C entry must be covered"
    calls = []
    for fn, params, ret, symbol in entries:
        args = []
        for param in params.split(", "):
            typ = param.split(": ", 1)[1]
            args.append({"Int": "123", "Float": "1.5", "Bool": "false", "String": '"value"', "Option[String]": "None"}[typ])
        calls.append('  refuse(' + fn + '(' + ", ".join(args) + '), "' + symbol + '")')
    extra = '''
fn refuse[T](result: Result[T, ForeignError], label: String) -> Unit = match result {
  Err(e) -> if e.kind != "sqlite.unsupported_backend" { panic(label ++ ": " ++ e.kind) }
  Ok(_) -> panic(label ++ ": unsupported entry returned Ok")
}
fn empty_result() -> Result[Unit, ForeignError] = Ok(())
pub fn main() -> Unit !io = {
'''+ "\n".join(calls) + '''
  refuse(query(123, "select 1", [], [ColInt]), "public-query")
  refuse(execute(123, "select 1", []), "public-execute")
  refuse(execute_changes(123, "insert into t values(1)", []), "public-changes")
  refuse(last_id(123), "public-last-id")
  refuse(busy_timeout(123, 1), "public-timeout")
  refuse(in_transaction(123), "public-state")
  refuse(with_tx(123, Immediate, () => empty_result()), "public-transaction")
  refuse(with_db(":memory:", _db => empty_result()), "public-connection")
  refuse(load_extension(123, "missing", None), "public-load")
  println("sqlite unsupported: ''' + str(len(entries)) + ''' entries OK")
}
'''
    source.write_text(text + extra)
    return tree, pkg, "sqlite unsupported: " + str(len(entries)) + " entries OK\n"


def backends(driver, work, env):
    for mutant in ["jvm-success", "wasi-success"]:
        tree, pkg, expected = fallback_package(work, mutant)
        run([sys.executable, HERE / "mutate.py", mutant, tree])
        if mutant == "jvm-success":
            jar = tree / "fallback.jar"
            run([DAWN, "build", pkg / "src/sqlite.dawn", "-o", jar], env=env)
            r = run(["java", "-XX:-UsePerfData", "-jar", jar], env=env, good=False)
            cause = "sqlite_busy_timeout: unsupported entry returned Ok"
        else:
            wasm = tree / "fallback.wasm"
            run([driver, "build", "--target", "wasm", pkg / "src/sqlite.dawn", "-o", wasm], env=env)
            r = run(["node", "--no-warnings", ROOT / "scripts/wasm-contract/runwasi.mjs", wasm], env=env, good=False)
            cause = "sqlite_open: unsupported entry returned Ok"
        assert r.returncode and cause in r.stdout + r.stderr, (mutant, r.stdout, r.stderr)
        ok("negative control " + mutant + ": " + cause)
    tree, pkg, expected = fallback_package(work, "unsupported")
    Path(env["F3_CC_LOG"]).write_text("")
    r = run([DAWN, "run", pkg / "src/sqlite.dawn"], env=env)
    assert r.stdout == expected and r.stderr == "", (r.stdout, r.stderr)
    assert Path(env["F3_CC_LOG"]).read_text() == "", "JVM must not invoke cc"
    ok("JVM: every extern and public operation returns stable unsupported without cc")
    wasm = tree / "program.wasm"
    run([driver, "build", "--target", "wasm", pkg / "src/sqlite.dawn", "-o", wasm], env=env)
    r = run(["node", "--no-warnings", ROOT / "scripts/wasm-contract/runwasi.mjs", wasm], env=env)
    assert r.stdout == expected and r.stderr == "", (r.stdout, r.stderr)
    ok("WASI: compile the real stub and execute every unsupported entry")
    url_consumer(driver, work, env)


def url_consumer(driver, work, env):
    archive_tree = work / "archive-tree"
    shutil.copytree(PACKAGE, archive_tree / "packages/sqlite")
    hash = run([DAWN, "__pkghash", archive_tree], env=env).stdout.strip()
    archive = work / "package.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(archive_tree, arcname="archive")
    app = work / "consumer"
    source = '''# Consume the safe API as a downstream application would.
use sqlite/sqlite
pub fn main() -> Unit !io = {
  let result: Result[sqlite.Rows, ForeignError] = sqlite.with_db(":memory:", db =>
    sqlite.query(db, "select 42 as answer", [], [sqlite.ColInt]))
  match result {
    Ok(rows) -> match rows.rows[0][0] {
      sqlite.Integer(42) -> println("sqlite consumer: OK")
      _ -> panic("consumer value")
    }
    Err(e) -> panic(e.kind)
  }
}
'''
    write(app / "src/main.dawn", source)
    for kind, dep in [("path", '[deps]\nsqlite = ' + json.dumps(str(PACKAGE)) + "\n"),
                      ("url", '[deps.sqlite]\nurl = ' + json.dumps(archive.as_uri()) + '\nversion = "0.1.0"\nhash = ' + json.dumps(hash) + '\nsubdir = "packages/sqlite"\n')]:
        write(app / "dawn.toml", 'schema = 1\nname = "consumer"\nversion = "1.0.0"\n' + dep)
        binary = work / (kind + "-consumer")
        run([driver, "build", app, "-o", binary], env=env)
        r = run([binary], env=env)
        assert r.stdout == "sqlite consumer: OK\n" and r.stderr == "", (kind, r.stdout, r.stderr)
        ok("native " + kind + "/subdir consumer: real query through public package API")


def main():
    start = time.monotonic()
    run([DAWN, "--version"])
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "dawn/sqlite-contract"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sqlite-contract.", dir=os.environ.get("TMPDIR")) as directory:
        work = Path(directory)
        driver = os.environ.get("DAWNC_BIN")
        if not driver:
            jar = work / "nmain.jar"
            run([DAWN, "build", ROOT / "selfhost/src/nmain.dawn", "-o", jar])
            driver = work / "dawnc"
            write(driver, '#!/bin/sh\nexec java -XX:-UsePerfData -Djava.io.tmpdir="$TMPDIR" -Xss512m -Xmx2g -jar "' + str(jar) + '" "$@"\n')
            driver.chmod(0o755)
        env = dict(os.environ, CC=str(wrapper(work)), F3_REAL_CC=CC, F3_CC_LOG=str(work / "cc.jsonl"),
                   DAWN_PKG_CACHE=str(work / "pkg-cache"), ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                   UBSAN_OPTIONS="halt_on_error=1")
        if "--backends" not in sys.argv:
            native(driver, work, cache, env)
        if "--native" not in sys.argv:
            backends(driver, work, env)
    print(f"sqlite contract: OK ({time.monotonic() - start:.2f}s)", flush=True)


if __name__ == "__main__":
    main()
