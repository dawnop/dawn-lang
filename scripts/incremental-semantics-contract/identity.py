#!/usr/bin/env python3
"""Require declaration identity admission to survive compiling negative controls.

The private subject keeps its parser and declaration index together; only
production identity admission changes, never the owning test assertions.
The mutants are the identity group of mutate.py, where the preflight proves
their anchors before any build; each section below takes the ones that edit
its files, in registry order.
"""
import re
import runpy
import shutil
import tempfile
import time
from pathlib import Path

from cold import HERE, ROOT, apply, owned, run


def main():
    started = time.monotonic()
    original = (ROOT / "selfhost/src/check/identity.dawn").read_text()
    group = owned(runpy.run_path(str(HERE / "mutate.py"))["MUTATIONS"], "identity")

    def section(*paths):
        return [(name, edits) for name, edits in group.items() if edits[0][0] in paths]

    variants = section("selfhost/src/check/identity.dawn")
    with tempfile.TemporaryDirectory(prefix="dawn-declaration-identity-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        target = root / "selfhost/src/check/identity.dawn"
        for name, source in [("positive", original)] + [
                (n, apply(original, e, "selfhost/src/check/identity.dawn")) for n, e in variants]:
            target.write_text(source)
            status, output = run("test", target)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive identity subject failed\n" + output)
            elif not status or not re.search(r"^FAIL\s+check/identity :: identity [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: declaration identity " + name, flush=True)
        target.write_text(original)
        # The other end of the same numbering. A packed key means nothing
        # below the checker, so lowering renumbers every one of them into one
        # run of small integers per module, in the order `ir/coredump` names
        # them. Both consumers are outside Core's own meaning -- `emitc`
        # prints a local as `v<id>`, the JVM emitter looks its type up in one
        # module-wide table -- and neither can tell a wrong order from a right
        # one, so the order is held here.
        #
        # A lifted body refers to its captures by the ids the enclosing
        # function gave them, so a pass that stops visiting them does not
        # crash: it numbers them at their first appearance in the body, which
        # is why these are assertions about an order rather than a missing key.
        lower_target = root / "selfhost/src/ir/lower.dawn"
        lower_original = lower_target.read_text()
        lower_variants = section("selfhost/src/ir/lower.dawn")
        for name, source in ([("positive", lower_original)] +
                             [(n, apply(lower_original, e, "selfhost/src/ir/lower.dawn")) for n, e in lower_variants]):
            lower_target.write_text(source)
            status, output = run("test", lower_target)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive densify subject failed\n" + output)
            elif not status or not re.search(
                    r"^FAIL\s+ir/lower :: lowering numbers [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: dense numbering " + name, flush=True)
        lower_target.write_text(lower_original)
        # The minting end of the same identities: `cx.mint` interns a derived
        # id and refuses a collision, and `enter_decl` opens the declaration
        # whose slots its bindings take. These controls lived in allocation.py
        # beside the provenance ledger until that ledger went with the replay
        # engine (2026-09-27); the code they hold is on every cold check.
        cx_target = root / "selfhost/src/check/cx.dawn"
        cx_original = cx_target.read_text()
        cx_variants = section("selfhost/src/check/cx.dawn")
        for name, source in [("positive", cx_original)] + [
                (n, apply(cx_original, e, "selfhost/src/check/cx.dawn")) for n, e in cx_variants]:
            cx_target.write_text(source)
            status, output = run("test", cx_target)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive mint subject failed\n" + output)
            elif not status or not re.search(
                    r"^FAIL\s+check/cx :: (a minted id|two declarations|identifiers are numbered|the free pool) "
                    r"[^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: derived identity " + name, flush=True)
        cx_target.write_text(cx_original)
        # The carry between modules. The intern table travels on it for the
        # reason the carry exists: a digest collision between two modules is
        # as fatal as one inside a module, and only a program-wide table can
        # see it. These controls lived in provenance.py until the provenance
        # half of the carry went with the replay engine (2026-09-27).
        carry = "module identity carry keeps exporting owners across header reorder"
        effects = "a consumer names a provider's effect without minting the provider's identity"
        spans = "the program a render reads from carries this revision's declaration spans"
        driver_path = "selfhost/src/driver/analyze.dawn"
        std_path = "selfhost/src/driver/stdlib.dawn"
        passes_path = "selfhost/src/check/passes.dawn"
        carry_originals = {path: (root / path).read_text() for path in (driver_path, std_path, passes_path)}
        owners = {"drop-identity-carry": carry, "drop-std-identity-carry": carry,
                  "drop-std-identity-step": carry, "drop-render-view": spans, "mint-imported-effect": effects}
        carry_variants = [(name, owners[name], edits[0][0], edits)
                          for name, edits in section(driver_path, std_path, passes_path)]
        if [name for name, *_ in carry_variants] != list(owners):
            raise RuntimeError(f"mutate.py's identity carry mutants are not {list(owners)}")
        carry_subjects = [("positive", carry, driver_path, carry_originals[driver_path])] + [
            (name, owner, path, apply(carry_originals[path], edits, path))
            for name, owner, path, edits in carry_variants]
        for name, owner, path, source in carry_subjects:
            (root / path).write_text(source)
            status, output = run("test", root / driver_path)
            (root / path).write_text(carry_originals[path])
            failure = re.search(r"^FAIL\s+driver/analyze :: " + re.escape(owner) +
                                r"[^\n]*\n\s+assertion failed:", output, re.M)
            if (status if name == "positive" else not status or not failure):
                raise RuntimeError(name + " did not satisfy its owning contract\n" + output)
            print("OK: identity carry " + name, flush=True)
    total = len(variants) + len(lower_variants) + len(cx_variants) + len(carry_variants)
    if total != len(group):
        raise RuntimeError(f"{len(group) - total} of mutate.py's identity mutants edit no file this harness tests")
    print(f"OK: declaration identity and {total} compiling mutants, "
          f"{time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
