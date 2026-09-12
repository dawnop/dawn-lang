#!/usr/bin/env python3
"""Classify every header boundary field and require compiling owning failures.

The separate Java oracle checks complete real header contexts. This audit
also refuses future Cx fields that otherwise fall through record spreads.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def fields(source, name):
    anchor = "pub type " + name + " = {\n"
    if source.count(anchor) != 1:
        raise RuntimeError("Header schema anchor drifted: " + name)
    block = source.split(anchor, 1)[1].split("\n}", 1)[0]
    return set(re.findall(r"^  ([a-z_]+):", block, re.M))


def audit(cx, product):
    stored = fields(product, "HeaderProduct") - {"allocation_start", "allocation_count", "diagnostics"}
    unchanged = set(re.findall(r"a\.([a-z_]+) == b\.\1", product))
    written = stored | {"diags", "next_id"}
    classified = unchanged | written | {"jsig"}
    if fields(cx, "Cx") != classified or unchanged & written:
        raise RuntimeError(f"Unclassified/stale header context fields: {fields(cx, 'Cx') ^ classified}; overlap: {unchanged & written}")
    for field in stored:
        if product.count(field + ": after." + field) != 1 or product.count(field + ": product." + field) != 1:
            raise RuntimeError("Missing header capture/assembly: " + field)


def audit_projection(product, visitor):
    moved = set("allocation_start diagnostics adts traits fns adts_by_name aliases alias_resolved ctors_by_name traits_by_name local_impls observable_impls impl_table module_fn_sigs consts effects effect_infos current_eff_vars current_tparams current_tparam_bounds module_exports ty_spans".split())
    retained = set("allocation_count fn_origin alias_resolving local_traits module_aliases imported_names const_order all_const_names java_classes record_ty_spans".split())
    if fields(product, "HeaderProduct") != moved | retained or moved & retained:
        raise RuntimeError("Unclassified header projection field")
    block = visitor.split("Some(HeaderProduct { ..p,", 1)[1].split(" })", 1)[0]
    assignments = set(re.findall(r"\b([a-z_]+):", block))
    if assignments != moved:
        raise RuntimeError("Missing or unexpected header projection assignment")


def main():
    started = time.monotonic()
    path = Path("selfhost/src/check/header_product.dawn")
    original = (ROOT / path).read_text()
    cx = (ROOT / "selfhost/src/check/cx.dawn").read_text()
    audit(cx, original)
    visitor = (ROOT / "selfhost/src/check/relocate_header.dawn").read_text()
    audit_projection(original, visitor)
    for product, source in [
        (original.replace("pub type HeaderProduct = {\n", "pub type HeaderProduct = {\n  unclassified: Int,\n"), visitor),
        (original, edit(visitor, "    impl_table: impls,\n", "")),
    ]:
        try:
            audit_projection(product, source)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Header projection audit accepted its negative control")
    print("OK: header projection field audit and two negative controls", flush=True)
    for source, product in [
        (cx.replace("pub type Cx = {\n", "pub type Cx = {\n  unclassified: Int,\n"), original),
        (cx, edit(original, "consts: after.consts", "consts: before.consts")),
        (cx, edit(original, "consts: product.consts", "consts: current.consts")),
    ]:
        try:
            audit(source, product)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Header field audit accepted its negative control")
    print("OK: header context field audit and three negative controls", flush=True)
    variants = [
        ("environment", "not environment_unchanged(before, after)", "false"),
        ("body-journal", "a.body_writes == b.body_writes", "true"),
        ("allocation-start", "current.next_id != product.allocation_start", "false"),
        ("allocation-count", " || product.allocation_count < 0 { return None }\n  let limit = current.next_id + product.allocation_count\n  if limit < current.next_id { return None }",
         " { return None }\n  let limit = current.next_id + product.allocation_count"),
        ("diagnostic-prefix", "current.diags ++ product.diagnostics", "product.diagnostics"),
        ("diagnostic-suffix", "current.diags ++ product.diagnostics", "current.diags"),
        ("constant-table", "consts: product.consts", "consts: current.consts"),
        ("type-scope", "current_tparams: product.current_tparams", "current_tparams: current.current_tparams"),
        ("span-reset", "ty_spans: product.ty_spans", "ty_spans: current.ty_spans"),
        ("record-reset", "record_ty_spans: product.record_ty_spans", "record_ty_spans: current.record_ty_spans"),
    ]
    with tempfile.TemporaryDirectory(prefix="dawn-header-state-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        target = root / path
        for name, source in [("positive", original)] + [(n, edit(original, a, b)) for n, a, b in variants]:
            target.write_text(source)
            status, output = run("test", target)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive header state failed\n" + output)
            elif not status or not re.search(r"^FAIL\s+check/header_product :: header product [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: header state " + name, flush=True)
    print(f"OK: header state and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
