#!/usr/bin/env python3
"""Guard production provenance producers, not only table transformations.

Private source copies must reach the exact transition owning assertion. A
build failure, linker failure or unrelated test cannot stand in for the guard.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    driver_path = "selfhost/src/driver/analyze.dawn"
    std_path = "selfhost/src/driver/stdlib.dawn"
    originals = {path: (ROOT / path).read_text() for path in (driver_path, std_path)}
    variants = [
        ("drop-local-origin", driver_path, "local_provenance = allocation.table(entries ++ methods)", "local_provenance = None"),
        ("lose-provider-carry", driver_path, "map.insert(origin.modules, mf.mod_path, local_provenance)", "map.from([(mf.mod_path, local_provenance)])"),
        ("admit-header-errors", driver_path, "if len(headers.cx.diags) == 0 {", "if true {"),
        ("drop-std-origin", std_path, "header_origin = allocation.table(entries ++ methods)", "header_origin = None"),
        ("skip-std-world", driver_path, 'allocation.in_world(table, "std", world)', "Some(table)"),
        ("drop-compiler-origin", driver_path, "intrinsics: allocation.compiler_headers(world)", "intrinsics: None"),
    ]
    with tempfile.TemporaryDirectory(prefix="dawn-provenance-carry-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        subjects = [("positive", driver_path, originals[driver_path])] + [
            (name, path, edit(originals[path], old, new)) for name, path, old, new in variants]
        for name, path, source in subjects:
            (root / path).write_text(source)
            status, output = run("test", root / driver_path)
            failure = re.search(r"^FAIL\s+driver/analyze :: module provenance carry keeps exporting owners across header reorder[^\n]*\n\s+assertion failed:", output, re.M)
            if (status if name == "positive" else not status or not failure):
                raise RuntimeError(name + " did not satisfy its owning contract\n" + output)
            (root / path).write_text(originals[path])
            print("OK: provenance carry " + name, flush=True)
    print(f"OK: provenance producers and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
