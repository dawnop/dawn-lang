#!/usr/bin/env python3
"""Prove that the workspace commits and discards the actual replay owner.

The owning test uses in-memory Fs/Env and can also run in the native suite.
Protocol-only comparisons would accept a server that silently always checks.
"""
from pathlib import Path
import re
import shutil
import tempfile
import time

from cold import ROOT, edit, run

OWNER = "workspace commits prefix cache with its Program and drops it on conflict"


def main():
    start = time.monotonic()
    original = (ROOT / "selfhost/src/lsp/server.dawn").read_text()
    variants = [
        ("drop-session", "        cache: update.session,", "        cache: ws0.cache,"),
        ("bypass-cache", "incremental.analyze(ws0.cache, loaded)",
         "incremental.analyze(incremental.evict(ws0.cache), loaded)"),
        ("keep-conflict-cache", "        cache: incremental.evict(ws0.cache),",
         "        cache: ws0.cache,"),
    ]
    subjects = [("positive", original)] + [(name, edit(original, old, new)) for name, old, new in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-lsp-prefix-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        target = root / "selfhost"
        for name, source in subjects:
            (target / "src/lsp/server.dawn").write_text(source)
            status, output = run("check", target)
            if status:
                raise RuntimeError(f"{name} did not compile\n{output}")
            status, output = run("test", target)
            if name == "positive":
                if status or not re.search(r"^PASS\s+lsp/server :: " + re.escape(OWNER), output, re.M):
                    raise RuntimeError(f"positive failed\n{output}")
            elif not status or not re.search(
                    r"^FAIL\s+lsp/server :: " + re.escape(OWNER) + r"\n\s+assertion failed:", output, re.M):
                raise RuntimeError(f"{name} missed the owning assertion\n{output}")
            print(f"OK: workspace prefix {name}", flush=True)
    print(f"OK: 3 compiling workspace cache mutants; elapsed={time.monotonic()-start:.2f}s")


if __name__ == "__main__":
    main()
