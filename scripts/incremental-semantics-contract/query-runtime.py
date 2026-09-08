#!/usr/bin/env python3
"""Require runtime graph invariants to fail in compiling private subjects.

These are graph tests, not checker dependency coverage. The owning failure
must be an assertion, never a compiler, linker or arbitrary process error.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    path = Path("selfhost/src/check/query_runtime.dawn")
    original = (ROOT / path).read_text()
    variants = [
        ("propagation", "Some(if same { next } else { invalidate(next, key) })", "Some(next)"),
        ("transitive", "queue = queue ++ [reader]", "queue = queue"),
        ("equal-cutoff", "Some(old) -> data.same(old.value, value)", "Some(old) -> false"),
        ("replace-edges", "var next = detach(data, key)", "var next = data"),
        ("read-dependency", 'reads = reads ++ [Dependency { key: key, stamp: map.get(next.memos, key).expect("query read stamp").stamp }]', "reads = reads"),
        ("blocked-read", "var blocked = set.insert(top.blocked, key)", "var blocked = top.blocked"),
        ("input-role", "Some(old) -> if not old.input { return None }", "Some(old) -> if false { return None }"),
        ("computed-role", "Some(old) -> if old.input { return None }", "Some(old) -> if false { return None }"),
        ("active-cycle", "if active(data, key) { return None }", "if false { return None }"),
        ("memo-cycle", "let next = invalidate(data, key)", "let next = data"),
        ("changed-read", "set.has(data.dirty, dep.key) || current.stamp != dep.stamp", "set.has(data.dirty, dep.key)"),
        ("abort-order", "data.stack[len(data.stack) - 1].key != key", "false"),
        ("evict-edges", "let next = detach(invalidate(data, key), key)", "let next = invalidate(data, key)"),
        ("same-revision-aba", "None -> data.next_stamp", "None -> data.revision"),
        ("busy-revision", "len(data.stack) != 0 || data.revision + 1 <= data.revision", "data.revision + 1 <= data.revision"),
        ("busy-input", "if len(data.stack) != 0 { return None }\n  match map.get(data.memos, key)", "if false { return None }\n  match map.get(data.memos, key)"),
        ("busy-eviction", "if len(data.stack) != 0 { return None }\n  let next = detach", "if false { return None }\n  let next = detach"),
    ]
    with tempfile.TemporaryDirectory(prefix="dawn-query-runtime-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        target = root / path
        subjects = [("positive", original)] + [(name, edit(original, old, new)) for name, old, new in variants]
        for name, source in subjects:
            target.write_text(source)
            status, output = run("test", target)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive query runtime failed\n" + output)
            elif not status or not re.search(r"^FAIL\s+(?:check/query_runtime :: )?query runtime [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: query runtime " + name, flush=True)
    print(f"OK: query runtime and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
