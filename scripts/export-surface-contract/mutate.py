#!/usr/bin/env python3
"""Apply one SEM-07 mutation to a copy of the compiler tree.

Each mutation removes or inverts exactly one rule of the public surface
validator, and the harness then asserts that exactly one contract goes red.
A mutant must still compile and run: "the mutant did not build" proves nothing
about the rule (docs/public-surface-design.md §十二).

Every anchor is matched exactly once. A rewrite of the pass moves all of them,
and that must be a hard failure rather than a mutation that silently does
nothing -- a no-op mutant is a gate that has stopped looking.
"""
from pathlib import Path
import sys

PASSES = "selfhost/src/check/passes.dawn"
CHECKER = "selfhost/src/check/checker.dawn"
TYPES = "selfhost/src/check/types.dawn"


def replace_once(text: str, old: str, new: str, name: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"{name}: mutation anchor drifted ({n} matches)")
    return text.replace(old, new)


# mutation -> (file, old, new)
MUTATIONS = {
    # 1 -- an opaque type's representation is not part of its surface
    "recurse-opaque-representation": (
        PASSES,
        "    TyOpaque(id, name, owner, args, _) -> {\n"
        "      let a = opaque_audience(cx, id, name, owner)\n"
        "      var out = no_leaks()\n",
        "    TyOpaque(id, name, owner, args, rep) -> {\n"
        "      let a = opaque_audience(cx, id, name, owner)\n"
        "      var out = surface_ty_leaks(cx, root, rep, sp, path ++ \" representation\")\n",
    ),
    # 2 -- but its explicit arguments are
    "skip-opaque-args": (
        PASSES,
        "      var i = 0\n"
        "      for arg in args {\n"
        "        out = out ++ surface_ty_leaks(cx, root, arg, ty_span_kid(sp, i),\n"
        "          path ++ \" opaque `\" ++ name ++ \"` type argument #\" ++ to_string(i + 1))\n",
        "      var i = 0\n"
        "      for arg in list.take(args, 0) {\n"
        "        out = out ++ surface_ty_leaks(cx, root, arg, ty_span_kid(sp, i),\n"
        "          path ++ \" opaque `\" ++ name ++ \"` type argument #\" ++ to_string(i + 1))\n",
    ),
    # 3 -- generic opaque arguments are identity, not existentials (knife 1).
    # `assignable` is the door a return type goes through, so this is where
    # "two opaque types with the same representation are one type" has to be
    # said for the mutant to be the existential reading rather than a typo.
    "opaque-args-existential": (
        CHECKER,
        "    TyOpaque(_, _, ow, _, tgt) ->\n"
        "      if sees_through(cx, ow) { assignable(cx, tgt, target) } else { false }\n",
        "    TyOpaque(_, _, ow, _, tgt) ->\n"
        "      match target {\n"
        "        TyOpaque(_, _, _, _, ttgt) -> tgt == ttgt\n"
        "        _ -> if sees_through(cx, ow) { assignable(cx, tgt, target) } else { false }\n"
        "      }\n",
    ),
    # 4 -- a nominal type's written arguments are surface
    "skip-adt-args": (
        PASSES,
        "      var i = 0\n"
        "      for a in args {\n"
        "        out = out ++ surface_ty_leaks(cx, root, a, ty_span_kid(sp, i),\n"
        "          path ++ \" type argument #\" ++ to_string(i + 1))\n",
        "      var i = 0\n"
        "      for a in list.take(args, 0) {\n"
        "        out = out ++ surface_ty_leaks(cx, root, a, ty_span_kid(sp, i),\n"
        "          path ++ \" type argument #\" ++ to_string(i + 1))\n",
    ),
    # 5 -- but its fields are not: they belong to the ADT's own root
    "recurse-adt-fields": (
        PASSES,
        "      let info = adt_of(cx.adts, id)\n"
        "      var out = no_leaks()\n"
        "      if not audience_covers(info.audience, root) {\n",
        "      let info = adt_of(cx.adts, id)\n"
        "      var out = no_leaks()\n"
        "      for ctor in info.ctors {\n"
        "        for fld in ctor.fields {\n"
        "          out = out ++ surface_ty_leaks(cx, root, fld.ty, sp, path ++ \" field\")\n"
        "        }\n"
        "      }\n"
        "      if not audience_covers(info.audience, root) {\n",
    ),
    # 6 -- a transparent alias publishes its target
    "skip-alias-target": (
        PASSES,
        "      if d.is_opaque {\n        cx\n      } else {\n",
        "      if true {\n        cx\n      } else {\n",
    ),
    # 8 -- a projection's trait must be nameable
    "skip-assoc-trait": (
        PASSES,
        "      let ta = trait_audience(tr)\n"
        "      var out = no_leaks()\n"
        "      if not audience_covers(ta, root) {\n",
        "      let ta = trait_audience(tr)\n"
        "      var out = no_leaks()\n"
        "      if false {\n",
    ),
    # 10 -- a public effect on a public API is legal
    "reject-all-effects": (
        PASSES,
        "    if not audience_covers(a, root) { out = out ++ [leak_at(\"effect\", name, a, path,"
        " sp)] }\n",
        "    if true { out = out ++ [leak_at(\"effect\", name, a, path, sp)] }\n",
    ),
    # 11 -- a private effect on one is not
    "pass-all-effects": (
        PASSES,
        "    if not audience_covers(a, root) { out = out ++ [leak_at(\"effect\", name, a, path,"
        " sp)] }\n",
        "    if false { out = out ++ [leak_at(\"effect\", name, a, path, sp)] }\n",
    ),
    # 12 -- an observable impl's bounds are surface
    "skip-impl-constraints": (
        PASSES,
        "  var leaks = surface_constraints_leaks(cx, root, imp.constraints, tps, path, head)\n",
        "  var leaks = no_leaks()\n",
    ),
    # 13 -- so are its associated bindings
    "skip-impl-assoc": (
        PASSES,
        "  for b in imp.assoc_bindings {\n",
        "  for b in list.take(imp.assoc_bindings, 0) {\n",
    ),
    # 14 -- an impl whose head is private is not observable at all
    "impl-always-observable": (
        PASSES,
        "fn impl_is_observable(cx: Cx, root: Audience, tr: TraitI, imp: ImplI, head: TySpan)"
        " -> Bool =\n"
        "  audience_covers(trait_audience(tr), root) &&\n"
        "  len(surface_ty_leaks(cx, root, imp.subject, head, \"impl subject\")) == 0\n",
        "fn impl_is_observable(cx: Cx, root: Audience, tr: TraitI, imp: ImplI, head: TySpan)"
        " -> Bool = true\n",
    ),
    # 16 -- the surface is validated before any body
    "surface-after-bodies": (
        CHECKER,
        "  cx1 = pass_export_surface(cx1, m)\n"
        "  let no_spans: Map[(Int, Int), TySpan] = map.empty()\n"
        "  cx1 = Cx { ..cx1, record_ty_spans: false, ty_spans: no_spans }\n",
        "  cx1 = Cx { ..cx1, record_ty_spans: false }\n",
    ),
    # 17 -- the exporter validates its own surface, the importer does not
    "check-imports-not-exports": (
        PASSES,
        "  let root = module_root_audience(cx)\n  var cx1 = cx\n  for d in m.decls {\n",
        "  let root = module_root_audience(cx)\n"
        "  var cx1 = cx\n"
        "  for entry in map.entries(cx.fns) {\n"
        "    let (fname, fsig) = entry\n"
        "    match map.get(cx.fn_origin, fname) {\n"
        "      Some(OImport(_)) -> {\n"
        "        cx1 = surface_report(cx1, \"imported function `\" ++ fname ++ \"`\",\n"
        "          surface_sig_leaks(cx1, root, fsig, no_tparam_decls(), no_params_m(),\n"
        "            no_tref_m(), \"function `\" ++ fname ++ \"`\", plain_span(0, 1)))\n"
        "      }\n"
        "      _ -> ()\n"
        "    }\n"
        "  }\n"
        "  for d in no_decls_m() {\n",
    ),
    # 18..21, 23..26 -- one per recursive branch (design §十二)
    "skip-list-element": (
        PASSES,
        "    TyList(e) -> surface_ty_leaks(cx, root, e, ty_span_kid(sp, 0), path ++"
        " \" list element\")\n",
        "    TyList(e) -> no_leaks()\n",
    ),
    "skip-map-key": (
        PASSES,
        "      surface_ty_leaks(cx, root, k, ty_span_kid(sp, 0), path ++ \" map key\") ++\n",
        "      no_leaks() ++\n",
    ),
    "skip-map-value": (
        PASSES,
        "      surface_ty_leaks(cx, root, v, ty_span_kid(sp, 1), path ++ \" map value\")\n",
        "      no_leaks()\n",
    ),
    "skip-set-element": (
        PASSES,
        "    TySet(e) -> surface_ty_leaks(cx, root, e, ty_span_kid(sp, 0), path ++"
        " \" set element\")\n",
        "    TySet(e) -> no_leaks()\n",
    ),
    "skip-array-element": (
        PASSES,
        "      out ++ surface_ty_leaks(cx, root, e, ty_span_kid(sp, 0), path ++"
        " \" array element\")\n",
        "      out\n",
    ),
    "skip-tuple-element": (
        PASSES,
        "      var i = 0\n"
        "      for e in elems {\n"
        "        out = out ++ surface_ty_leaks(cx, root, e, ty_span_kid(sp, i),\n"
        "          path ++ \" tuple element #\" ++ to_string(i + 1))\n",
        "      var i = 0\n"
        "      for e in list.take(elems, 0) {\n"
        "        out = out ++ surface_ty_leaks(cx, root, e, ty_span_kid(sp, i),\n"
        "          path ++ \" tuple element #\" ++ to_string(i + 1))\n",
    ),
    "skip-fn-param": (
        PASSES,
        "      var i = 0\n"
        "      for p in params {\n"
        "        out = out ++ surface_ty_leaks(cx, root, p, ty_span_kid(sp, i),\n"
        "          path ++ \" function parameter #\" ++ to_string(i + 1))\n",
        "      var i = 0\n"
        "      for p in list.take(params, 0) {\n"
        "        out = out ++ surface_ty_leaks(cx, root, p, ty_span_kid(sp, i),\n"
        "          path ++ \" function parameter #\" ++ to_string(i + 1))\n",
    ),
    "skip-fn-return": (
        PASSES,
        "      out = out ++ surface_ty_leaks(cx, root, ret, ty_span_kid(sp, len(params)),\n"
        "        path ++ \" function return type\")\n",
        "      out = out ++ no_leaks()\n",
    ),
    # 22 -- `Array` is standard-library-internal, not world-facing
    "array-is-world": (
        TYPES,
        "        BtStdOnly -> AStdOnly\n",
        "        BtStdOnly -> AWorld\n",
    ),
    # the three-audience model itself: collapse StdOnly into World everywhere
    "stdonly-collapses-to-world": (
        TYPES,
        "pub fn declared_audience(owner: String) -> Audience =\n"
        "  if list.contains(internal_std_modules(), owner) { AStdOnly } else { AWorld }\n",
        "pub fn declared_audience(owner: String) -> Audience =\n"
        "  if false { AStdOnly } else { AWorld }\n",
    ),
}

# helpers a mutation needs but the unmutated pass does not
EXTRA_HELPERS = {
    "check-imports-not-exports": (
        PASSES,
        "\nfn no_params_m() -> List[Param] = []\n"
        "fn no_tref_m() -> Option[TypeRef] = None\n"
        "fn no_decls_m() -> List[Decl] = []\n",
    ),
}


# A second anchored edit, for the mutations that move code rather than remove
# it. `surface-after-bodies` has to put the call back at the end: a mutant that
# merely deleted the pass would prove nothing about *when* it runs.
EXTRA_EDITS = {
    "surface-after-bodies": (
        CHECKER,
        "  fns_out = fns_out ++ synth ++ impl_tfuns ++ default_tfuns\n",
        "  fns_out = fns_out ++ synth ++ impl_tfuns ++ default_tfuns\n"
        "  cx1 = pass_export_surface(cx1, m)\n",
    ),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    for table in (MUTATIONS, EXTRA_EDITS):
        if mutation in table:
            rel, old, new = table[mutation]
            path = root / rel
            path.write_text(replace_once(path.read_text(), old, new, mutation))
    if mutation in EXTRA_HELPERS:
        hrel, helpers = EXTRA_HELPERS[mutation]
        hpath = root / hrel
        hpath.write_text(hpath.read_text() + helpers)


if __name__ == "__main__":
    main()
