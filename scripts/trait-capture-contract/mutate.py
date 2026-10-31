#!/usr/bin/env python3
"""Own the compiling mutations for trait Capture contracts, before erasure."""
from pathlib import Path
import sys

CHECKER = "selfhost/src/check/checker.dawn"
PASSES = "selfhost/src/check/passes.dawn"
CONTRACT = "selfhost/src/check/trait_contract.dawn"
MUTATIONS = {
    "erase-trait-binders": (("selfhost/src/front/parser.dawn",
        "kw.lo, close.hi, name.lo, name.hi, scope)))",
        "kw.lo, close.hi, name.lo, name.hi, no_scope_syntax())))"),),
    "erase-bound-arguments": (("selfhost/src/check/scope_infer.dawn",
        "constraints = map(scoped.constraints, bs => map(bs, b => capture.trait_subst(b, sm, captures))),",
        "constraints = map(scoped.constraints, bs => map(bs, b => capture.closed_trait(b.id))),"),),
    "erase-projection-upper": ((CONTRACT,
        "if member == name { return capture.subst(upper, map.empty(), substitutions(tr, app)) }",
        "if member == name { return [] }"),),
    "erase-forwarded-application": ((CHECKER,
        "match map.get(cx.frame.dict_syms, capture.dictionary_key(vid, application)) {",
        "match map.get(cx.frame.dict_syms, capture.dictionary_key(vid, capture.closed_trait(trait_id))) {"),),
    "erase-default-environment": ((CHECKER,
        "CaptureFunction { ..contract, bound = Some(captured) }",
        "CaptureFunction { ..contract, bound = Some([]) }"),),
    "ignore-subject-support": ((PASSES,
        "if not capture.subset_in(trait_contract.support(cx.adts, params, subject), allowed, params.captures) {",
        "if false && not capture.subset_in(trait_contract.support(cx.adts, params, subject), allowed, params.captures) {"),),
    "ignore-item-upper": ((PASSES,
        "if not capture.subset_in(actual, upper, cx1.current_capture_params.captures) {",
        "if false && not capture.subset_in(actual, upper, cx1.current_capture_params.captures) {"),),
    "widen-invariant-arguments": ((CONTRACT,
        "ok = ok && capture.trait_equal(expected, app)",
        "ok = ok && capture.subset(capture.trait_support(expected), capture.trait_support(app))"),),
    "erase-associated-scope": ((PASSES,
        "} else { row = scoped }",
        "} else { row = EPure }"),),
    "ignore-subwitness-support": ((PASSES,
        "if not capture.subset_in(capture.trait_support(bound), allowed, params.captures) {",
        "if false && not capture.subset_in(capture.trait_support(bound), allowed, params.captures) {"),),
}


def apply(name, root):
    for relative, old, new in MUTATIONS[name]:
        path = Path(root) / relative
        source = path.read_text()
        if source.count(old) != 1:
            raise SystemExit(f"{name}: anchor in {relative} matches {source.count(old)}, expected 1")
        path.write_text(source.replace(old, new))


if __name__ == "__main__":
    apply(sys.argv[1], Path(sys.argv[2]))
