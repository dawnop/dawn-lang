#!/usr/bin/env python3
"""Require effect observations to retain real rows, scope and allocation.

Compiling mutants must reach an owning assertion, not fail at compilation or
linkage. The checker exercises precedence and repeated reads after a scope write;
leaf and body owners independently constrain effect-domain projection.
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
        ("cx", "declared-answer", "semantic_reads.DeclaredEffect(name, answer)", "semantic_reads.DeclaredEffect(name, None)"),
        ("cx", "declared-name", "semantic_reads.DeclaredEffect(name, answer)", 'semantic_reads.DeclaredEffect("wrong", answer)'),
        ("cx", "declared-label", "Some(label_eff(cx, id))", "Some(ELabeled(EPure, [(id, name)]))"),
        ("cx", "declared-id", "Some(label_eff(cx, id))", "Some(ELabeled(EPure, [(id + 1, effect_of(cx, id).name)]))"),
        ("cx", "declared-consumer", "cx1 = declared_cx", "cx1 = cx1"),
        ("cx", "variable-answer", "semantic_reads.ScopedEffectVariable(name, answer)", "semantic_reads.ScopedEffectVariable(name, None)"),
        ("cx", "variable-name", "semantic_reads.ScopedEffectVariable(name, answer)", 'semantic_reads.ScopedEffectVariable("wrong", answer)'),
        ("cx", "variable-consumer", "cx1 = variable_cx", "cx1 = cx1"),
        ("cx", "scope-write", "cx1 = Cx { ..cx2, current_eff_vars: map.insert(cx2.current_eff_vars, a, v) }", "cx1 = cx2"),
        ("semantic_reads", "declared-domain", "DeclaredEffect(name, moved_effect)", "DeclaredEffect(name, answer)"),
        ("semantic_reads", "variable-domain", "ScopedEffectVariable(name, moved_variable)", "ScopedEffectVariable(name, answer)"),
        ("semantic_reads", "declared-projected-name", "DeclaredEffect(name, moved_effect)", 'DeclaredEffect("wrong", moved_effect)'),
        ("semantic_reads", "variable-projected-name", "ScopedEffectVariable(name, moved_variable)", 'ScopedEffectVariable("wrong", moved_variable)'),
        ("body_product", "effect-callback", "e => relocate.effect_row(v.ids, e), source_value,", "e => Some(e), source_value,"),
    ]
    sources = {name: (ROOT / "selfhost/src/check" / (name + ".dawn")).read_text()
               for name in ("cx", "semantic_reads", "body_product")}
    subjects = [(module, "positive", source) for module, source in sources.items()]
    subjects += [(module, name, edit(sources[module], old, new)) for module, name, old, new in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-effect-reads-") as temp:
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
            elif not status or not re.search(r"^FAIL\s+(?:check/\w+ :: )?(?:effect reads|semantic reads|body product) [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: effect reads " + module + " " + name, flush=True)
    print(f"OK: effect reads and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
