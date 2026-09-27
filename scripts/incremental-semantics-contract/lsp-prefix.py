#!/usr/bin/env python3
"""Prove that the LSP's answers come from the real producers.

The workspace cache mutants show that the prefix owner is the thing the
server commits and discards; the resolver mutant shows that a query's
positions are the ones the scheduler resolved against the declaration a body
was checked in. The owning tests use in-memory Fs/Env and can also run in the
native suite. Protocol-only comparisons would accept a server that silently
always checks.
"""
from pathlib import Path
import re
import shutil
import tempfile
import time

from cold import ROOT, edit, run

CACHE = "workspace commits prefix cache with its Program and drops it on conflict"
RESOLVER = "a handler state cell answers at every spelling of it"

SERVER = "selfhost/src/lsp/server.dawn"
CHECKER = "selfhost/src/check/checker.dawn"


def main():
    start = time.monotonic()
    paths = (SERVER, CHECKER)
    originals = {path: (ROOT / path).read_text() for path in paths}
    variants = [
        ("drop-session", CACHE, SERVER, "        cache: update.session,", "        cache: ws0.cache,"),
        ("bypass-cache", CACHE, SERVER, "incremental.analyze(ws0.cache, loaded)",
         "incremental.analyze(incremental.evict(ws0.cache), loaded)"),
        ("keep-conflict-cache", CACHE, SERVER, "        cache: incremental.evict(ws0.cache),",
         "        cache: ws0.cache,"),
        # A body is checked with offsets relative to its own declaration, and
        # `tast_positions.symbols` is what adds the declaration's start back
        # on the way out. Its owner here is the LSP reader of those positions;
        # `a typed span cuts the source the declaration actually holds` in
        # check/checker is the same resolver's checker-side reader. Until
        # 2026-09-27 the owner was a replayed body's definition, which went
        # with the replay engine.
        ("resolver-drops-the-declaration", RESOLVER, CHECKER,
         "syms: tast_positions.symbols(entered.resolver, after.syms, "
         "mint_cursor(entered.cx), mint_cursor(after))",
         "syms: tast_positions.symbols(tast_positions.unowned(after.src_path, after.line_starts), "
         "after.syms, mint_cursor(entered.cx), mint_cursor(after))"),
    ]
    subjects = [("positive", CACHE, SERVER, originals[SERVER])] + [
        (name, owner, path, edit(originals[path], old, new)) for name, owner, path, old, new in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-lsp-prefix-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        target = root / "selfhost"
        for name, owner, path, source in subjects:
            (root / path).write_text(source)
            status, output = run("check", target)
            if status:
                raise RuntimeError(f"{name} did not compile\n{output}")
            status, output = run("test", target)
            if name == "positive":
                if status or not re.search(r"^PASS\s+lsp/server :: " + re.escape(CACHE), output, re.M) \
                        or not re.search(r"^PASS\s+lsp/server :: " + re.escape(RESOLVER), output, re.M):
                    raise RuntimeError(f"positive failed\n{output}")
            elif not status or not re.search(
                    r"^FAIL\s+lsp/server :: " + re.escape(owner) + r"\n\s+assertion failed:", output, re.M):
                raise RuntimeError(f"{name} missed the owning assertion\n{output}")
            (root / path).write_text(originals[path])
            print(f"OK: lsp prefix and resolver {name}", flush=True)
    print(f"OK: {len(variants)} compiling LSP prefix and resolver mutants; elapsed={time.monotonic()-start:.2f}s")


if __name__ == "__main__":
    main()
