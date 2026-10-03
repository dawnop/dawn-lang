#!/usr/bin/env python3
"""Apply one mutation of the LSP resolution-coverage contract to a copy of the tree.

Each mutation removes one piece of the definition walk in
selfhost/src/lsp/lspq.dawn that scripts/lsp-resolution-coverage.py holds, and
that script requires the mutant to compile and turn its owning case red. The
registry lives here, not in that script, so that
scripts/mutation-anchor-preflight.py proves every anchor matches exactly once
before any compiler is built; an anchor that drifts is a red preflight rather
than a mutant that silently changes nothing.
"""
from pathlib import Path
import sys

LSPQ = "selfhost/src/lsp/lspq.dawn"

# mutation -> (file, anchor, replacement)
MUTATIONS = {
    'drop-qualified-fn-value': (LSPQ, '        Some(XFnValue(owner, fname, _, _, _, _)) -> {\n          q = offer_alias_receiver(qc, q, target)\n          match sig_by_owner(qc, owner, fname, None) {\n            Some(s) -> { q = offer_sig_at(qc, q, flo, fhi, s, site_of_sig(qc, s)) }\n            None -> ()\n          }\n        }\n', ''),
    'drop-written-types': (LSPQ, 'fn offer_type_name(qc: QCx, q: Q, name: String, lo: Int, hi: Int) -> Q = {\n', 'fn offer_type_name(qc: QCx, q: Q, name: String, lo: Int, hi: Int) -> Q = {\n  if true { return q }\n'),
    'drop-arm-names': (LSPQ, 'fn offer_arm_names(qc: QCx, q0: Q, eff_name: String, arms: List[HandlerArm]) -> Q = {\n', 'fn offer_arm_names(qc: QCx, q0: Q, eff_name: String, arms: List[HandlerArm]) -> Q = {\n  if true { return q0 }\n'),
    'drop-alias-segment': (LSPQ, '    Some(path) -> if spelled(qc, lo, hi, mod_alias) {', '    Some(path) -> if false {'),
}


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: mutation anchor occurs {count} times")
    return text.replace(old, new)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    rel, old, new = MUTATIONS[mutation]
    path = root / rel
    path.write_text(replace_once(path.read_text(), old, new, mutation))


if __name__ == "__main__":
    main()
