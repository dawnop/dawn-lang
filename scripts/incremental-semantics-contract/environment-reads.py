#!/usr/bin/env python3
"""Constrain named-type environment observation without changing precedence.

The real checker owns reserved names, scope shadowing and std-only visibility.
Projection owners additionally retain builtin metadata and its leaf type domain.
Only a successfully compiled mutant reaching an owning assertion is accepted.
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
        ("cx", "builtin-answer", "semantic_reads.BuiltinTypeAnswer(name, answer)", "semantic_reads.BuiltinTypeAnswer(name, None)"),
        ("cx", "builtin-name", "semantic_reads.BuiltinTypeAnswer(name, answer)", 'semantic_reads.BuiltinTypeAnswer("wrong", answer)'),
        ("cx", "mode-answer", "semantic_reads.StdModuleMode(cx.is_std_module)", "semantic_reads.StdModuleMode(not cx.is_std_module)"),
        ("cx", "reserved-consumer", "cx = reserved_cx", "cx = cx"),
        ("cx", "ordinary-consumer", "cx = builtin_cx", "cx = cx"),
        ("cx", "parameter-consumer", "cx = parameter_cx", "cx = cx"),
        ("cx", "return-mode-consumer", "cx = mode_cx\n        if builtin_type_visible_at_return", "cx = cx\n        if builtin_type_visible_at_return"),
        ("cx", "ordinary-mode-consumer", "cx = mode_cx\n      if builtin_type_visible", "cx = cx\n      if builtin_type_visible"),
        ("semantic_reads", "builtin-leaf-domain", "BtLeaf(ty) -> BtLeaf(type_value(ty)?)", "BtLeaf(ty) -> BtLeaf(ty)"),
        ("semantic_reads", "builtin-projection", "BuiltinTypeAnswer(name, moved_builtin)", "BuiltinTypeAnswer(name, answer)"),
        ("semantic_reads", "builtin-display", "Some(BuiltinTypeI { ..info, build: build })", 'Some(BuiltinTypeI { ..info, name: "wrong", build: build })'),
        ("semantic_reads", "builtin-parameters", "Some(BuiltinTypeI { ..info, build: build })", "Some(BuiltinTypeI { ..info, params: [], build: build })"),
        ("semantic_reads", "builtin-access", "Some(BuiltinTypeI { ..info, build: build })", "Some(BuiltinTypeI { ..info, access: BtPublic, build: build })"),
        ("semantic_reads", "builtin-build", "Some(BuiltinTypeI { ..info, build: build })", "Some(BuiltinTypeI { ..info, build: BtList })"),
        ("semantic_reads", "projected-mode", "StdModuleMode(is_std) -> StdModuleMode(is_std)", "StdModuleMode(is_std) -> StdModuleMode(false)"),
        ("body_product", "type-callback", "t => relocate.ty(v.ids, t), id => relocate.nominal(v.ids, id)", "t => Some(t), id => relocate.nominal(v.ids, id)"),
    ]
    sources = {name: (ROOT / "selfhost/src/check" / (name + ".dawn")).read_text()
               for name in ("cx", "semantic_reads", "body_product")}
    subjects = [(module, "positive", source) for module, source in sources.items()]
    subjects += [(module, name, edit(sources[module], old, new)) for module, name, old, new in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-environment-reads-") as temp:
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
            elif not status or not re.search(r"^FAIL\s+(?:check/\w+ :: )?(?:environment reads|semantic reads|body product) [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: environment reads " + module + " " + name, flush=True)
    print(f"OK: environment reads and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
