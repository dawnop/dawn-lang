#!/usr/bin/env python3
"""Prove Java class answers survive observation, consumers and projection.

Only compiled mutants reaching the Java owning assertions count. Host query
counts are not dependency answers, and these tests do not authorize caching
across a changed classpath or a closed metadata oracle.
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
        ("cx", "name-key", "semantic_reads.JavaClassName(name, answer)", 'semantic_reads.JavaClassName("wrong", answer)'),
        ("cx", "name-answer", "semantic_reads.JavaClassName(name, answer)", "semantic_reads.JavaClassName(name, None)"),
        ("cx", "info-key", "semantic_reads.JavaClassInfo(fqcn, answer)", 'semantic_reads.JavaClassInfo("wrong", answer)'),
        ("cx", "info-answer", "semantic_reads.JavaClassInfo(fqcn, answer)", 'semantic_reads.JavaClassInfo(fqcn, JClass { ..answer, display: "wrong" })'),
        ("cx", "name-consumer", "cx = java_cx", "cx = cx"),
        ("cx", "type-consumer", "record_span_at(info_cx, lo, hi, no_trefs())", "record_span_at(cx, lo, hi, no_trefs())"),
        ("checker", "return-consumer", "(info_cx, opt_ty(TyJava(rc, info.display)))", "(cx, opt_ty(TyJava(rc, info.display)))"),
        ("checker", "static-consumer", "check_java_call(info_cx, info, None, true", "check_java_call(cx1, info, None, true"),
        ("checker", "instance-consumer", "check_java_call(info_cx, info, Some(tx), false", "check_java_call(cx1, info, Some(tx), false"),
        # Drop class metadata at the renderer handoff, retaining the new
        # rendering fact so the original Java-metadata owner remains decisive.
        ("checker", "sam-diagnostic-consumer", 'type_display_read(info_cx, TyFn(sps, sret, EIo))', 'type_display_read(cx1, TyFn(sps, sret, EIo))'),
        ("checker", "list-diagnostic-consumer", 'type_display_read(info_cx, t)', 'type_display_read(cx1, t)'),
        ("semantic_reads", "project-name-key", "JavaClassName(name, answer) -> JavaClassName(name, answer)", 'JavaClassName(name, answer) -> JavaClassName("wrong", answer)'),
        ("semantic_reads", "project-name-answer", "JavaClassName(name, answer) -> JavaClassName(name, answer)", "JavaClassName(name, answer) -> JavaClassName(name, None)"),
        ("semantic_reads", "project-info-key", "JavaClassInfo(fqcn, answer) -> JavaClassInfo(fqcn, answer)", "JavaClassInfo(fqcn, answer) -> JavaClassInfo(answer.fqcn, answer)"),
        ("body_product", "capture-reads", "semantic_reads.capture(before.function_reads, after.function_reads)?", "before.function_reads"),
    ]
    for field in ("fqcn", "simple", "display", "is_interface", "is_primitive", "is_array"):
        value = '"wrong"' if field in ("fqcn", "simple", "display") else "not answer." + field
        variants.append(("semantic_reads", "project-info-" + field,
                         "JavaClassInfo(fqcn, answer) -> JavaClassInfo(fqcn, answer)",
                         "JavaClassInfo(fqcn, answer) -> JavaClassInfo(fqcn, JClass { ..answer, " + field + ": " + value + " })"))
    sources = {name: (ROOT / "selfhost/src/check" / (name + ".dawn")).read_text()
               for name in ("cx", "checker", "semantic_reads", "body_product")}
    subjects = [(module, "positive", source) for module, source in sources.items()]
    subjects += [(module, name, edit(sources[module], old, new)) for module, name, old, new in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-java-reads-") as temp:
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
                prefix = ("java reads" if module in ("cx", "checker") else
                          "semantic reads preserve plain Java metadata" if module == "semantic_reads" else "body product")
                if not status or not re.search(r"^FAIL\s+(?:check/\w+ :: )?" + prefix + r"[^\n]*\n\s+assertion failed:", output, re.M):
                    raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: Java reads " + module + " " + name, flush=True)
    print(f"OK: Java reads and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
