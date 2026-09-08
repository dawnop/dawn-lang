#!/usr/bin/env python3
"""Require Java import/namespace answers and consumer contexts to be retained.

Only successfully compiled mutations that reach owning assertions count; a
refusing host oracle panic is not accepted as a semantic negative control.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    variants = [
        ("cx", "enabled-answer", "semantic_reads.JavaEnabled(cx.jsig.on)", "semantic_reads.JavaEnabled(not cx.jsig.on)"),
        ("cx", "find-key", "semantic_reads.JavaFindClass(name, answer)", 'semantic_reads.JavaFindClass("wrong", answer)'),
        ("cx", "find-answer", "semantic_reads.JavaFindClass(name, answer)", "semantic_reads.JavaFindClass(name, None)"),
        ("cx", "names-answer", "semantic_reads.JavaClassNames(names)", "semantic_reads.JavaClassNames([])"),
        ("passes", "gate-consumer", "cx1 = enabled_cx", "cx1 = cx1"),
        ("passes", "find-consumer", "cx1 = found_cx", "cx1 = cx1"),
        ("passes", "import-name-consumer", "cx1 = name_cx\n        if previous", "cx1 = cx1\n        if previous"),
        ("passes", "type-collision-consumer", "cx1 = name_cx\n    if java_name", "cx1 = cx1\n    if java_name"),
        ("checker", "static-consumer", "cx1 = name_cx\n        match java_target", "cx1 = cx1\n        match java_target"),
        ("checker", "field-consumer", "field_cx = name_cx", "field_cx = field_cx"),
        ("checker", "message-consumer", "\n          cx = name_cx\n", "\n          cx = cx\n"),
        ("checker", "refusal-consumer", "cerr_h(message_cx, message,", "cerr_h(cx, message,"),
        ("checker", "enumeration-consumer", "cx1 = names_cx", "cx1 = cx1"),
        ("checker", "value-consumer", "(java_cx, java_name != None)", "(next, java_name != None)"),
        ("semantic_reads", "enabled-projection", "JavaEnabled(enabled) -> JavaEnabled(enabled)", "JavaEnabled(enabled) -> JavaEnabled(false)"),
        ("semantic_reads", "find-key-projection", "JavaFindClass(name, answer) -> JavaFindClass(name, answer)", 'JavaFindClass(name, answer) -> JavaFindClass("wrong", answer)'),
        ("semantic_reads", "find-answer-projection", "JavaFindClass(name, answer) -> JavaFindClass(name, answer)", "JavaFindClass(name, answer) -> JavaFindClass(name, None)"),
        ("semantic_reads", "names-projection", "JavaClassNames(names) -> JavaClassNames(names)", "JavaClassNames(names) -> JavaClassNames([])"),
        ("semantic_reads", "names-order", "JavaClassNames(names) -> JavaClassNames(names)", "JavaClassNames(names) -> JavaClassNames(list.reverse(names))"),
        ("body_product", "capture", "semantic_reads.capture(before.function_reads, after.function_reads)?", "before.function_reads"),
    ]
    for kind in ("effect", "trait"):
        anchor = '    if occupied {\n      cx1 = cerr_h(cx1, "' + kind + ' `'
        variants.append(("passes", kind + "-collision-consumer", anchor,
                         '    cx1 = Cx { ..cx1, function_reads: cx.function_reads }\n' + anchor))
    sources = {m: (ROOT / "selfhost/src/check" / (m + ".dawn")).read_text()
               for m in ("cx", "passes", "checker", "semantic_reads", "body_product")}
    subjects = [(m, "positive", s) for m, s in sources.items()]
    subjects += [(m, n, edit(sources[m], a, b)) for m, n, a, b in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-java-namespace-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        for module, name, source in subjects:
            target = root / "selfhost/src/check" / (module + ".dawn")
            target.write_text(source)
            owner = root / "selfhost/src/check" / ("checker.dawn" if module in ("cx", "passes") else module + ".dawn")
            status, output = run("test", owner)
            target.write_text(sources[module])
            if name == "positive":
                if status:
                    raise RuntimeError("Positive " + module + " failed\n" + output)
            elif not status or not re.search(r"^FAIL\s+(?:check/\w+ :: )?(?:java (?:import|namespace) reads|java reads|semantic reads preserve plain Java metadata|body product)[^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: Java namespace " + module + " " + name, flush=True)
    print(f"OK: Java namespace reads and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
