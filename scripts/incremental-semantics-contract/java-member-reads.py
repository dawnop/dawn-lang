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
    fields = {
        "JavaMethods": ("JMethod", {"name": '"wrong"', "param_cls": "list.reverse(m.param_cls)",
            "ret_cls": '"wrong"', "is_static": "not m.is_static", "is_varargs": "not m.is_varargs",
            "is_abstract": "not m.is_abstract", "desc": '"wrong"', "decl_cls": '"wrong"'}),
        "JavaConstructors": ("JCtor", {"param_cls": "list.reverse(m.param_cls)",
            "is_varargs": "not m.is_varargs", "desc": '"wrong"'}),
        "JavaStaticFields": ("JField", {"name": '"wrong"', "type_cls": '"wrong"', "decl_cls": '"wrong"'}),
    }
    for fact, (record, members) in fields.items():
        observed = f"semantic_reads.{fact}(fqcn, answer)"
        variants += [("cx", fact + "-key", observed, f'semantic_reads.{fact}("wrong", answer)'),
                     ("cx", fact + "-answer", observed, f"semantic_reads.{fact}(fqcn, [])")]
        projected = f"{fact}(fqcn, answer) -> {fact}(fqcn, answer)"
        for label, value in (("key", f'{fact}("wrong", answer)'),
                             ("answer", f"{fact}(fqcn, [])"),
                             ("order", f"{fact}(fqcn, list.reverse(answer))")):
            variants.append(("semantic_reads", fact + "-project-" + label, projected,
                             f"{fact}(fqcn, answer) -> " + value))
        for field, value in members.items():
            variants.append(("semantic_reads", fact + "-field-" + field, projected,
                             f"{fact}(fqcn, answer) -> {fact}(fqcn, list.map(answer, m => {record} {{ ..m, {field}: {value} }}))"))
    variants += [
        ("checker", "constructors-consumer", "cx1 = constructors_cx", "cx1 = cx1"),
        ("checker", "methods-consumer", "cx1 = methods_cx", "cx1 = cx1"),
        ("checker", "fields-consumer", "let (cx, fields) = java_static_fields_read(initial, fq)",
         "let (_, fields) = java_static_fields_read(initial, fq)\n  let cx = initial"),
        ("body_product", "capture", "semantic_reads.capture(before.function_reads, after.function_reads)?", "before.function_reads"),
    ]
    sources = {name: (ROOT / "selfhost/src/check" / (name + ".dawn")).read_text()
               for name in ("cx", "checker", "semantic_reads", "body_product")}
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
                          "semantic reads preserve ordered Java candidates" if module == "semantic_reads" else "body product")
                if not status or not re.search(r"^FAIL\s+(?:check/\w+ :: )?" + prefix + r"[^\n]*\n\s+assertion failed:", output, re.M):
                    raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: Java member reads " + module + " " + name, flush=True)
    print(f"OK: Java member reads and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
