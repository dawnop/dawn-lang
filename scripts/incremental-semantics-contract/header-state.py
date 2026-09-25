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
    # Cx is package-private, HeaderProduct is public: take whichever spelling
    # the declaration has, and still refuse anything but exactly one.
    anchor = next((head + name + " = {\n" for head in ("pub type ", "pub(pkg) type ")
                   if head + name + " = {\n" in source), "pub type " + name + " = {\n")
    if source.count(anchor) != 1:
        raise RuntimeError("Header schema anchor drifted: " + name)
    block = source.split(anchor, 1)[1].split("\n}", 1)[0]
    return set(re.findall(r"^  ([a-z_]+):", block, re.M))


def audit(cx, product):
    stored = fields(product, "HeaderProduct") - {"decl_slots", "diagnostics"}
    unchanged = set(re.findall(r"a\.([a-z_]+) == b\.\1", product))
    written = stored | {"diags", "decl_slots"}
    classified = unchanged | written | {"jsig"}
    if fields(cx, "Cx") != classified or unchanged & written:
        raise RuntimeError(f"Unclassified/stale header context fields: {fields(cx, 'Cx') ^ classified}; overlap: {unchanged & written}")
    for field in stored:
        if product.count(field + ": after." + field) != 1 or product.count(field + ": product." + field) != 1:
            raise RuntimeError("Missing header capture/assembly: " + field)


def main():
    started = time.monotonic()
    path = Path("selfhost/src/check/header_product.dawn")
    original = (ROOT / path).read_text()
    cx = (ROOT / "selfhost/src/check/cx.dawn").read_text()
    audit(cx, original)
    for source, product in [
        (cx.replace("pub(pkg) type Cx = {\n", "pub(pkg) type Cx = {\n  unclassified: Int,\n"), original),
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
        ("slots-advanced", "if not slots_advanced(current.decl_slots, product.decl_slots) { return None }", ""),
        ("slots-not-merged", "slots = map.insert(slots, declaration, count)", "slots = slots"),
        ("diagnostic-prefix", "current.diags ++ product.diagnostics", "product.diagnostics"),
        ("diagnostic-suffix", "current.diags ++ product.diagnostics", "current.diags"),
        ("identity-table", "identities: after.identities", "identities: before.identities"),
        ("identity-install", "identities: product.identities", "identities: current.identities"),
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
