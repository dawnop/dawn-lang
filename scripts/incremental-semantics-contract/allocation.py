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
        ("constant-type", "if old_ty != next_ty { return false }", ""),
        ("binding-conflict", "if id != e.id", "if false"),
        ("owner-conflict", "if binding != e.binding", "if false"),
        ("target-identity", "Some(target) -> if target != id { return false }",
         "Some(target) -> if false { return false }"),
        ("effect-domain", "if held == id && binding.domain == domain", "if held == id"),
        ("compiler-trait-binders", "entries = entries ++ binders(key, [tr.tvar], [])?", "entries = entries"),
        ("negative-slot", "HeaderSlot(index) -> if index < 0", "HeaderSlot(index) -> if false"),
        # A body's entry evidence pack is one run of the declaration's own
        # slots, in ABI order. It was an interval inside one counter, and the
        # control that owned its extent went with the interval; what is left
        # to get wrong is the run itself and the header it is admitted under.
        ("entry-pack-not-a-run", "if id != evidence[0] + index { return false }", "if false { return false }"),
        ("reserved-signature", "if old_sig != next_sig { return false }", "if false { return false }"),
        ("module-combine", "  table(entries)\n}\n\n## Rebind", "  table([])\n}\n\n## Rebind"),
        ("world-owner", "if declaration.scope.world != from", "if false"),
        ("source-wildcard", 'None -> scope.source == ""', "None -> true"),
        ("compiler-erasure", 'entries = entries ++ [entry(compiler_key(world, TypeDecl, "erased_runtime"), TypeParameter, 0, id)]',
         "entries = entries"),
    ]
    # The nominal and trait halves of this ledger are gone: those two domains
    # derive their integers from the declaration, so a consumer needs no
    # mapping and two declarations cannot quarrel over one number. What
    # inherited the ledger's job on those domains is `cx.mint` -- the intern
    # table and its collision refusal -- so those verdicts are held here too.
    cx_original = (ROOT / "selfhost/src/check/cx.dawn").read_text()
    cx_variants = [
        ("intern-collision-ignored", "Some(other) -> if other != decl {", "Some(other) -> if false {"),
        ("intern-not-recorded", "(Cx { ..cx, identities: map.insert(cx.identities, id, decl) }, id)", "(cx, id)"),
        ("mint-takes-a-slot", "(Cx { ..cx, identities: map.insert(cx.identities, id, decl) }, id)",
         "(Cx { ..cx, decl_slots: map.insert(cx.decl_slots, cx.owner_decl, slot_of(cx) + 1),\n    identities: map.insert(cx.identities, id, decl) }, id)"),
        # The slot seam. A declaration that does not open one numbers its
        # bindings in whatever declaration the previous pass left open; one
        # that reissues slot zero puts its body's locals on its signature's
        # binders; and a pool shared by the program puts two modules' unowned
        # bindings on one key.
        ("enter-keeps-the-previous-declaration", "Cx { ..interned_cx, owner_decl: id }", "interned_cx"),
        ("slots-restart-at-zero", "pub(pkg) fn fresh(cx: Cx) -> (Cx, Int) = {\n  let slot = slot_of(cx)",
         "pub(pkg) fn fresh(cx: Cx) -> (Cx, Int) = {\n  let slot = 0"),
        ("pool-is-one-for-the-program", 'pub(pkg) fn module_pool(cx: Cx) -> Int = free_pool(cx.owner_class.unwrap_or(""))',
         'pub(pkg) fn module_pool(cx: Cx) -> Int = free_pool("")'),
        ("mint-reads-the-source-path",
         'interned(cx, minted(cx.owner_class.unwrap_or(""), kind, name), lo, hi)',
         'interned(cx, minted(cx.owner_class.unwrap_or("") ++ cx.src_path.unwrap_or(""), kind, name), lo, hi)'),
        ("mint-ignores-the-kind",
         'interned(cx, minted(cx.owner_class.unwrap_or(""), kind, name), lo, hi)',
         'interned(cx, minted(cx.owner_class.unwrap_or(""), identity.TypeDecl, name), lo, hi)'),
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
        target.write_text(original)
        cx_target = root / "selfhost/src/check/cx.dawn"
        for name, source in [("positive", cx_original)] + [(n, edit(cx_original, a, b)) for n, a, b in cx_variants]:
            cx_target.write_text(source)
            status, output = run("test", cx_target)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive mint subject failed\n" + output)
            elif not status or not re.search(
                    r"^FAIL\s+check/cx :: (a minted id|two declarations|identifiers are numbered|the free pool) [^\n]*\n\s+assertion failed:",
                    output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: derived identity " + name, flush=True)
    print(f"OK: allocation and {len(variants) + len(cx_variants)} compiling mutants, "
          f"{time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
