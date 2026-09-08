#!/usr/bin/env python3
"""Guard metadata references and source ownership in compiling private copies.

The separate Java oracle compares complete exports from real headers. These
small owning assertions also cover malformed inputs and uncommon syntax;
neither compilation failures nor linker errors count as a rejected mutant.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


SCHEMAS = {
    "FieldI": ("types", "ty", "name"),
    "CtorI": ("types", "adt fields", "name"),
    "AdtI": ("types", "id tparams ctors bound_eparams", "name is_record eparams derives_show derives_ord owner audience"),
    "MethodSig": ("types", "sig", "has_default"),
    "TraitI": ("types", "id tvar methods eff_defaults", "name is_pub owner src_path assoc eff_assoc injects"),
    "EffectI": ("types", "id", "name owner audience ops ctl"),
    "ImplI": ("types", "trait_id subject tparams constraints lo hi assoc_bindings eff_bindings", "derived owner src_path provided"),
    "Sig": ("types", "param_tys ret eff tparams constraints eparams trait_id op_of", "name param_names param_defaults is_builtin owner inferring"),
    "AliasE": ("cx", "tparams eparams target id nlo nhi", "name is_opaque owner audience"),
    "ModExports": ("cx", "fns types_by_name aliases alias_resolved ctors consts traits_by_name effects effect_infos impls adt_infos trait_infos", "mod_path class_name all_names src_path"),
}


def audit_fields(sources):
    for name, (module, projected, retained) in SCHEMAS.items():
        source = sources[module]
        anchor = "pub type " + name + " = {"
        if source.count(anchor) != 1:
            raise RuntimeError("Metadata schema anchor drifted: " + name)
        body = source.split(anchor, 1)[1].split("}", 1)[0]
        body = re.sub(r"#[^\n]*", "", body)
        fields = set(re.findall(r"\b([a-z_]+)\s*:", body))
        moved, kept = set(projected.split()), set(retained.split())
        if moved & kept or fields != moved | kept:
            raise RuntimeError("Unclassified metadata fields: " + name + ": " + str(fields ^ (moved | kept)))


def main():
    started = time.monotonic()
    path = Path("selfhost/src/check/relocate_header.dawn")
    original = (ROOT / path).read_text()
    sources = {name: (ROOT / "selfhost/src/check" / (name + ".dawn")).read_text() for name in ("types", "cx")}
    audit_fields(sources)
    for name, (module, _, _) in SCHEMAS.items():
        changed = dict(sources)
        anchor = "pub type " + name + " = {"
        changed[module] = changed[module].replace(anchor, anchor + " unclassified: Int,", 1)
        try:
            audit_fields(changed)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Metadata field audit accepted a new field: " + name)
    print("OK: ten metadata schemas and their unclassified-field controls", flush=True)
    variants = [
        ("adt-binder", "tparams: projected_list(a.tparams, t => relocate.ty(v.ids, t))?,\n    bound_eparams:", "tparams: a.tparams,\n    bound_eparams:"),
        ("constructor-field", "Some(FieldI { ..f, ty: relocate.ty(v.ids, f.ty)? })", "Some(f)"),
        ("trait-method", "MethodSig { ..method, sig: relocate.signature(v.ids, method.sig)? }", "method"),
        ("trait-default", "eff_defaults: defaults", "eff_defaults: t.eff_defaults"),
        ("impl-subject", "subject: relocate.ty(v.ids, i.subject)?", "subject: i.subject"),
        ("impl-associated", "assoc_bindings: associated", "assoc_bindings: i.assoc_bindings"),
        ("impl-effect", "eff_bindings: effects", "eff_bindings: i.eff_bindings"),
        ("impl-owner", "lo: v.position(i.owner, i.src_path, i.lo)?, hi: v.end_position(i.owner, i.src_path, i.hi)?",
         'lo: v.position(Some("decl"), i.src_path, i.lo)?, hi: v.end_position(Some("decl"), i.src_path, i.hi)?'),
        ("impl-end", "v.end_position(i.owner, i.src_path, i.hi)?", "i.hi"),
        ("alias-sentinel", "if not a.is_opaque && a.id != -1 { return None }", ""),
        ("alias-target", "Some(t) -> Some(type_source(v, Some(a.owner), t)?)", "Some(t) -> Some(t)"),
        ("alias-effect", "eparams: projected_list(a.eparams, e => relocate.effect_row(v.ids, e))?", "eparams: a.eparams"),
    ]
    with tempfile.TemporaryDirectory(prefix="dawn-header-metadata-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        target = root / path
        subjects = [("positive", original)] + [(name, edit(original, old, new)) for name, old, new in variants]
        for name, source in subjects:
            target.write_text(source)
            status, output = run("test", target)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive header metadata failed\n" + output)
            elif not status or not re.search(r"^FAIL\s+check/relocate_header :: header metadata [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: header metadata " + name, flush=True)
    print(f"OK: header metadata and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
