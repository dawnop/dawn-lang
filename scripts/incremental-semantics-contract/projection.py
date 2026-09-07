#!/usr/bin/env python3
"""Exercise source and evidence provenance guards in private compiler copies.

Compiling mutants must fail the exact owning inline assertion; linker errors,
timeouts and unrelated test failures are not evidence for these guards.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def owning(output, module, title):
    return bool(re.search(r"^FAIL\s+" + re.escape(module + " :: " + title)
                          + r"[^\n]*\n\s+assertion failed:", output, re.M))


def main():
    started = time.monotonic()
    jobs = [
        ("source_projection", "source projection ", [
            ("same-boundary-table", "ends: ends, old_text:", "ends: starts, old_text:"),
            ("changed-token", "a.kind != b.kind || str.slice(old_text, a.lo, a.hi) != str.slice(new_text, b.lo, b.hi)", "false"),
            ("stale-assertion", "Some(Some(str.slice(p.new_text, nlo, nhi)))", "Some(Some(text))"),
            ("unchecked-assertion-origin", "str.slice(p.old_text, start, hi) != text", "false"),
        ]),
        ("checker", "evidence reads preserve distinct origins behind the same runtime key", [
            ("lost-crossed-origin", "if crossed {\n        (cx1, Some(XEvRead(key, origin, lo, hi, ty)))",
             "if crossed {\n        (cx1, Some(XEvRead(key, VariableSlot(0), lo, hi, ty)))"),
            ("lost-missing-origin", "if len(cx1.frame.lambda_stack) > 0 {\n        (cx1, Some(XEvRead(key, origin, lo, hi, ty)))",
             "if len(cx1.frame.lambda_stack) > 0 {\n        (cx1, Some(XEvRead(key, VariableSlot(0), lo, hi, ty)))"),
        ]),
    ]
    assert owning("FAIL  check/source_projection :: source projection control\n assertion failed: expected\n",
                  "check/source_projection", "source projection ")
    assert not owning("FAIL  check/source_projection :: source projection control\n NoSuchMethodError\n",
                      "check/source_projection", "source projection ")
    with tempfile.TemporaryDirectory(prefix="dawn-projection-contract-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        for module, title, mutations in jobs:
            target = root / "selfhost/src/check" / (module + ".dawn")
            original = target.read_text()
            subjects = [("positive", original)] + [(name, edit(original, old, new)) for name, old, new in mutations]
            for name, source in subjects:
                target.write_text(source)
                status, output = run("test", target)
                if name == "positive":
                    if status:
                        raise RuntimeError("Positive projection subject failed\n" + output)
                elif not status or not owning(output, "check/" + module, title):
                    raise RuntimeError(name + " did not reach its owning assertion\n" + output)
                print("OK: projection " + module + " " + name, flush=True)
            target.write_text(original)
    print(f"OK: source/evidence projection and six compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
