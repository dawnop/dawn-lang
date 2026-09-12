#!/usr/bin/env python3
"""Exercise captured checker writes without accepting compilation failures.

Mutants change the production extractor/assembler, not its owning assertions.
The real-body oracle separately compares every Cx field in Java.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def audit_fields(cx_source, product_source):
    start = "pub type Cx = {\n"
    if cx_source.count(start) != 1:
        raise RuntimeError("Cx declaration anchor drifted")
    block = cx_source.split(start, 1)[1].split("\n}", 1)[0]
    fields = set(re.findall(r"^  ([a-z_]+):", block, re.M))
    unchanged = set(re.findall(r"a\.([a-z_]+) == b\.\1", product_source))
    unchanged |= set(re.findall(r"environment_map_same\(a\.([a-z_]+), b\.\1, tracked\)", product_source))
    written = {"diags", "next_id", "fns", "alias_resolved", "frame", "syms",
               "current_eff_vars", "current_tparams", "current_tparam_bounds",
               "in_test", "const_cutoff", "loop_jumps", "take_cell", "function_reads", "body_writes"}
    # jsig is the one owner-held capability; it is intentionally not Eq data.
    classified = unchanged | written | {"jsig"}
    if fields != classified or unchanged & written:
        raise RuntimeError(f"Unclassified/stale Cx fields: {fields ^ classified}; overlap: {unchanged & written}")


def main():
    started = time.monotonic()
    original = (ROOT / "selfhost/src/check/body_product.dawn").read_text()
    cx_source = (ROOT / "selfhost/src/check/cx.dawn").read_text()
    audit_fields(cx_source, original)
    try:
        audit_fields(cx_source.replace("pub type Cx = {\n", "pub type Cx = {\n  unclassified: Int,\n"), original)
    except RuntimeError:
        print("OK: state product field audit rejects an unclassified Cx field", flush=True)
    else:
        raise RuntimeError("Cx field audit accepted its negative control")
    variants = [
        ("function-read-capture", "semantic_reads.capture(before.function_reads, after.function_reads)?", "Some([])"),
        ("function-read-write", "semantic_reads.append(current.function_reads, product.function_reads)?", "current.function_reads"),
        ("function-read-domain", "semantic_reads.project_with_inference(p.function_reads, s => relocate.signature(v.ids, s),\n      t => relocate.ty(v.ids, t), id => relocate.nominal(v.ids, id), e => relocate.effect_row(v.ids, e), source_value,\n      id => relocate.trait_id(v.ids, id), id => relocate.type_var(v.ids, id), id => relocate.local_id(v.ids, id),\n      id => relocate.effect_var(v.ids, id))?", "p.function_reads"),
        ("constant-tree", "tree => relocate_tree.constant(v, tree)", "tree => Some(tree)"),
        ("symbol-order", "sort_by(moved_symbols, (a, b) => cmp(a.key, b.key))", "moved_symbols"),
        ("signature-write", "fns: apply_changes(current.fns, product.signatures)", "fns: current.fns"),
        ("alias-write", "alias_resolved: apply_changes(current.alias_resolved, product.aliases)", "alias_resolved: current.alias_resolved"),
        ("bound-write", "current_tparam_bounds: apply_changes(current.current_tparam_bounds, product.bounds)", "current_tparam_bounds: current.current_tparam_bounds"),
        ("frame-reset", "frame: product.frame", "frame: current.frame"),
        ("diagnostic-write", "diags: current.diags ++ product.diagnostics", "diags: current.diags"),
        ("environment-write", "not environment_unchanged(before, after, tracked)", "false"),
        ("environment-value", "Some(other) -> value == other", "Some(other) -> true"),
        ("environment-key", "Some(other) -> value == other, None -> false", "Some(other) -> value == other, None -> true"),
        ("environment-size", "map.len(a) == map.len(b) && map.fold", "map.fold"),
        ("allocation-start", "current.next_id != product.allocation_start", "false"),
        ("unobserved-allocation", "while id < old_limit", "while false"),
        ("diagnostic-span", "Diag { ..d, lo: map.get(v.positions, d.lo)?, hi: map.get(v.ends, d.hi)? }", "d"),
        ("bound-domain", "out = out ++ [relocate.trait_id(v.ids, tr)?]", "out = out ++ [tr]"),
        ("used-effect-domain", "used = used ++ [relocate.effect_row(v.ids, e)?]", "used = used ++ [e]"),
        ("handler-cell", "Some(cell) -> Some(relocate.local_id(v.ids, cell)?)", "Some(cell) -> Some(cell)"),
        ("frame-signature", "Some(s) -> Some(relocate.signature(v.ids, s)?)", "Some(s) -> Some(s)"),
        ("sealed-signature", "projected_changes(p.signatures, name => Some(name), s => relocate.signature(v.ids, s))?", "p.signatures"),
    ]
    with tempfile.TemporaryDirectory(prefix="dawn-state-product-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        target = root / "selfhost/src/check/body_product.dawn"
        for name, source in [("positive", original)] + [(n, edit(original, a, b)) for n, a, b in variants]:
            target.write_text(source)
            status, output = run("test", target)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive state product failed\n" + output)
            elif not status or not re.search(r"^FAIL\s+check/body_product :: body product [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: state product " + name, flush=True)
    print(f"OK: state product and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
