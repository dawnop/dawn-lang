#!/usr/bin/env python3
"""Keep associated-member observations tied to real scope and trait decisions.

The checker owns missing/ambiguous/deduplicated answers on both axes. Projection
must relocate subject and trait references separately; compilation errors cannot
stand in for an assertion that a dependency or its consumer was preserved.
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
        ("cx", "subject-answer", "semantic_reads.ScopedTypeParameter(name, answer)", "semantic_reads.ScopedTypeParameter(name, None)"),
        ("cx", "subject-consumer", "(observe_type_read(cx, semantic_reads.ScopedTypeParameter(name, answer)), answer)", "(cx, answer)"),
        ("cx", "bounds-answer", "semantic_reads.ParameterBounds(subject, answer)", "semantic_reads.ParameterBounds(subject, None)"),
        ("cx", "bounds-consumer", "(observe_type_read(cx, semantic_reads.ParameterBounds(subject, answer)), answer)", "(cx, answer)"),
        ("cx", "members-answer", "semantic_reads.TraitAssociatedMembers(id, kind, names)", "semantic_reads.TraitAssociatedMembers(id, kind, [])"),
        ("cx", "members-axis", "semantic_reads.TraitAssociatedMembers(id, kind, names)", "semantic_reads.TraitAssociatedMembers(id, semantic_reads.AssociatedType, names)"),
        ("cx", "type-members-consumer", "trait_associated_members_read(cx, tid, semantic_reads.AssociatedType)\n        cx = members_cx", "trait_associated_members_read(cx, tid, semantic_reads.AssociatedType)\n        cx = cx"),
        ("cx", "effect-members-consumer", "trait_associated_members_read(cx, tid, semantic_reads.AssociatedEffect)\n        cx = members_cx", "trait_associated_members_read(cx, tid, semantic_reads.AssociatedEffect)\n        cx = cx"),
        ("semantic_reads", "subject-domain", "let moved_parameter = match answer { None -> None, Some(ty) -> Some(type_value(ty)?) }", "let moved_parameter = answer"),
        ("semantic_reads", "bound-subject-domain", "ParameterBounds(type_value(subject)?, moved_bounds)", "ParameterBounds(subject, moved_bounds)"),
        ("semantic_reads", "bounds-domain", "ids = ids ++ [trait_value(id)?]", "ids = ids ++ [id]"),
        ("semantic_reads", "members-domain", "TraitAssociatedMembers(trait_value(id)?, kind, names)", "TraitAssociatedMembers(id, kind, names)"),
        ("semantic_reads", "trait-not-nominal", "TraitAssociatedMembers(trait_value(id)?, kind, names)", "TraitAssociatedMembers(nominal(id)?, kind, names)"),
        ("semantic_reads", "projected-axis", "TraitAssociatedMembers(trait_value(id)?, kind, names)", "TraitAssociatedMembers(trait_value(id)?, AssociatedType, names)"),
        ("body_product", "trait-callback", "id => relocate.trait_id(v.ids, id), id => relocate.type_var(v.ids, id)", "id => Some(id), id => relocate.type_var(v.ids, id)"),
    ]
    sources = {name: (ROOT / "selfhost/src/check" / (name + ".dawn")).read_text()
               for name in ("cx", "semantic_reads", "body_product")}
    subjects = [(module, "positive", source) for module, source in sources.items()]
    subjects += [(module, name, edit(sources[module], old, new)) for module, name, old, new in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-associated-reads-") as temp:
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
            elif not status or not re.search(r"^FAIL\s+(?:check/\w+ :: )?(?:associated reads|semantic reads|body product) [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: associated reads " + module + " " + name, flush=True)
    print(f"OK: associated reads and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
