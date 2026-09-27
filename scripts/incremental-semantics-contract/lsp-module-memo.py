#!/usr/bin/env python3
"""Prove that the LSP's answers come from the real producers.

The workspace cache mutants show that the analysis owner is the thing the
server commits and discards, and the parse mutants that the parses a load
reuses are the previous load's and only for unchanged text; the resolver
mutant shows that a query's
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

CACHE = ("lsp/server", "workspace commits its module memo with its Program and drops it on conflict")
RESOLVER = ("lsp/server", "a handler state cell answers at every spelling of it")
PARSES = ("driver/analyze", "a reusing load parses only the files whose text changed")

SERVER = "selfhost/src/lsp/server.dawn"
CHECKER = "selfhost/src/check/checker.dawn"
ANALYZE = "selfhost/src/driver/analyze.dawn"


def owner_line(verdict, owner):
    module, name = owner
    return r"^" + verdict + r"\s+" + re.escape(module) + " :: " + re.escape(name)


def main():
    start = time.monotonic()
    paths = (SERVER, CHECKER, ANALYZE)
    originals = {path: (ROOT / path).read_text() for path in paths}
    variants = [
        ("drop-session", CACHE, SERVER, "        cache: update.session,", "        cache: ws0.cache,"),
        ("bypass-cache", CACHE, SERVER, "incremental.analyze(ws0.cache, loaded)",
         "incremental.analyze(incremental.evict(ws0.cache), loaded)"),
        ("keep-conflict-cache", CACHE, SERVER, "        cache: incremental.evict(ws0.cache),",
         "        cache: ws0.cache,"),
        # A load that is handed nothing to reuse still answers correctly, so
        # only the counts can see it; a load that reuses a parse whose text
        # changed answers with the old syntax.
        ("drop-parses", CACHE, SERVER, "        parses: retained_parses(st, reusing.parses),",
         "        parses: ws0.parses,"),
        ("stale-parse", PARSES, ANALYZE, "    Some(p) -> if p.text == text { (p, true) }",
         "    Some(p) -> if true { (p, true) }"),
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
    with tempfile.TemporaryDirectory(prefix="dawn-lsp-module-memo-") as temp:
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
                if status or not all(re.search(owner_line("PASS", each), output, re.M)
                                     for each in (CACHE, RESOLVER, PARSES)):
                    raise RuntimeError(f"positive failed\n{output}")
            elif not status or not re.search(
                    owner_line("FAIL", owner) + r"\n\s+assertion failed:", output, re.M):
                raise RuntimeError(f"{name} missed the owning assertion\n{output}")
            (root / path).write_text(originals[path])
            print(f"OK: lsp module memo, parses and resolver {name}", flush=True)
    print(f"OK: {len(variants)} compiling LSP session, parse and resolver mutants; elapsed={time.monotonic()-start:.2f}s")


if __name__ == "__main__":
    main()
