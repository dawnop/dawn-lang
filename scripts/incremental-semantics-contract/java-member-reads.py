#!/usr/bin/env python3
"""Require actual ordered Java member answers and returned consumer contexts.

The owning tests distinguish metadata loss, query-key loss and candidate-list
reordering. Compilation errors and unrelated runtime failures are not evidence
that a mutation was caught by the semantic contract.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    variants = []
    # Twenty three projection controls were generated here and are gone with
    # the read-log projection they mutated (K7b): for each of the three facts a
    # `-project-key`, `-project-answer` and `-project-order`, plus one
    # `-field-<member>` per record member (`JavaMethods` eight, over `JMethod`;
    # `JavaConstructors` three, over `JCtor`; `JavaStaticFields` three, over
    # `JField`). Each edited a member the projection copied out of a member
    # list. Nothing copies them now: the fact is carried whole, list and all.
    # The recording controls below are what still decides a member fact.
    for fact in ("JavaMethods", "JavaConstructors", "JavaStaticFields"):
        observed = f"semantic_reads.{fact}(fqcn, answer)"
        variants += [("cx", fact + "-key", observed, f'semantic_reads.{fact}("wrong", answer)'),
                     ("cx", fact + "-answer", observed, f"semantic_reads.{fact}(fqcn, [])")]
    variants += [
        ("checker", "constructors-consumer", "cx1 = constructors_cx", "cx1 = cx1"),
        ("checker", "methods-consumer", "cx1 = methods_cx", "cx1 = cx1"),
        ("checker", "fields-consumer", "let (cx, fields) = java_static_fields_read(initial, fq)",
         "let (_, fields) = java_static_fields_read(initial, fq)\n  let cx = initial"),
    ]
    sources = {name: (ROOT / "selfhost/src/check" / (name + ".dawn")).read_text()
               for name in ("cx", "checker", "semantic_reads")}
    subjects = [(module, "positive", source) for module, source in sources.items()]
    subjects += [(module, name, edit(sources[module], old, new)) for module, name, old, new in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-java-member-reads-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        for module, name, source in subjects:
            target = root / "selfhost/src/check" / (module + ".dawn")
            target.write_text(source)
            owner = root / "selfhost/src/check" / ("checker.dawn" if module == "cx" else module + ".dawn")
            status, output = run("test", owner)
            target.write_text(sources[module])
            if name == "positive":
                if status:
                    raise RuntimeError("Positive " + module + " failed\n" + output)
            else:
                prefix = ("java member reads" if module in ("cx", "checker") else
                          "semantic reads preserve ordered Java candidates")
                if not status or not re.search(r"^FAIL\s+(?:check/\w+ :: )?" + prefix + r"[^\n]*\n\s+assertion failed:", output, re.M):
                    raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: Java member reads " + module + " " + name, flush=True)
    print(f"OK: Java member reads and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
