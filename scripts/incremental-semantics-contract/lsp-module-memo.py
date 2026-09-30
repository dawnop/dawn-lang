#!/usr/bin/env python3
"""Prove that the LSP's answers come from the real producers.

The workspace cache mutants show that the analysis owner is the thing the
server commits and discards, and the parse mutants that the parses a load
reuses (and the line starts that ride on them) are the previous load's and
only for unchanged text; the resolver
mutant shows that a query's
positions are the ones the scheduler resolved against the declaration a body
was checked in. The owning tests use in-memory Fs/Env and can also run in the
native suite. Protocol-only comparisons would accept a server that silently
always checks.
"""
from pathlib import Path
import re
import runpy
import shutil
import tempfile
import time

from cold import HERE, ROOT, apply, owned, run

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
    # The mutants are the lsp-module-memo group of mutate.py, where the
    # preflight proves their anchors before any build; this is what each
    # one's failure must be owned by.
    owners = {"drop-session": CACHE, "bypass-cache": CACHE, "keep-conflict-cache": CACHE,
              "drop-parses": CACHE, "stale-parse": PARSES, "stale-line-starts": PARSES,
              "resolver-drops-the-declaration": RESOLVER}
    group = owned(runpy.run_path(str(HERE / "mutate.py"))["MUTATIONS"], "lsp-module-memo")
    if list(group) != list(owners):
        raise RuntimeError(f"mutate.py's lsp-module-memo group is {list(group)}, not {list(owners)}")
    variants = [(name, owners[name], edits[0][0], edits) for name, edits in group.items()]
    subjects = [("positive", CACHE, SERVER, originals[SERVER])] + [
        (name, owner, path, apply(originals[path], edits, path)) for name, owner, path, edits in variants]
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
