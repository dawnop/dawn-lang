#!/usr/bin/env python3
"""Reject broken provenance joins through compiling owning negative controls.

Use a private compiler source copy so the join changes without changing the
test assertions or any concurrently used worktree.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    original = (ROOT / "selfhost/src/check/allocation.dawn").read_text()
    variants = [
        ("constant-type", "if relocate.ty(header_ids, old_ty) != Some(next_ty) { return None }", ""),
        ("binding-conflict", "if id != e.id", "if false"),
        ("owner-conflict", "if binding != e.binding", "if false"),
        ("target-identity", "map.get(b.bindings, binding)", "map.get(a.bindings, binding)"),
        ("negative-slot", "HeaderSlot(index) -> if index < 0", "HeaderSlot(index) -> if false"),
        ("trait-domain", "TraitId -> { traits = map.insert(traits, id, target) }", "TraitId -> { types = map.insert(types, id, target) }"),
        ("body-evidence", "map.get(moved_evidence, start + offset).unwrap_or(target + offset)", "target + offset"),
        ("body-ghost", "while offset < count {", "while offset < count - 1 {"),
        ("body-endpoint", "next_id: target + count", "next_id: target + count - 1"),
        ("body-carry", "old_allocations: old_allocations, next_allocations: next_allocations",
         "old_allocations: old_headers, next_allocations: next_headers"),
        ("module-combine", "  table(entries)\n}\n\n## Rebind", "  table([])\n}\n\n## Rebind"),
        ("world-owner", "if declaration.scope.world != from", "if false"),
        ("world-evidence", "if effect_key.scope.world != from", "if false"),
        ("world-nested", "LabelEvidence(DeclKey { ..effect_key, scope: ModuleKey { ..effect_key.scope, world: world } })", "LabelEvidence(effect_key)"),
        ("source-wildcard", 'None -> scope.source == ""', "None -> true"),
        ("compiler-nominals", "entries = entries ++ [entry(key, NominalId, 0, adt.id)] ++ binders(key, adt.tparams, adt.bound_eparams)?",
         "entries = entries ++ binders(key, adt.tparams, adt.bound_eparams)?"),
        ("compiler-erasure", 'entries = entries ++ [entry(compiler_key(world, TypeDecl, "erased_runtime"), TypeParameter, 0, id)]',
         "entries = entries"),
    ]
    with tempfile.TemporaryDirectory(prefix="dawn-allocation-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        target = root / "selfhost/src/check/allocation.dawn"
        for name, source in [("positive", original)] + [(n, edit(original, a, b)) for n, a, b in variants]:
            target.write_text(source)
            status, output = run("test", target)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive allocation subject failed\n" + output)
            elif not status or not re.search(r"^FAIL\s+check/allocation :: allocation [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: allocation " + name, flush=True)
    print(f"OK: allocation and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
