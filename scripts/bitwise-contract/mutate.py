#!/usr/bin/env python3
"""Keep the first two bitwise cuts' compiling negative controls executable.

The closeout runner applies each edit to a private copy. The common anchor
preflight applies this same registry in memory, so a moved implementation
cannot silently retire a control between compiler builds.
"""
from pathlib import Path
import sys

CHECKER = "selfhost/src/check/checker.dawn"
TYPES = "selfhost/src/check/types.dawn"
I8 = "std/int/i8.dawn"
U64 = "std/int/u64.dawn"
C = "selfhost/src/c/emitc.dawn"

MUTATIONS = {
    "int-trait": ((CHECKER, "if t == TyInt || is_errorish(t) {", "if is_errorish(t) {"),),
    "amount-subject": ((CHECKER,
        "if is_shift_trait(tid) {\n    reduce_assoc(cx, TyAssoc(subject, capture.closed_trait(tid), shift_amount_name(tid), []))",
        "if false {\n    reduce_assoc(cx, TyAssoc(subject, capture.closed_trait(tid), shift_amount_name(tid), []))"),),
    "opaque-inherit": ((TYPES,
        "trait_id == EQ_ID || trait_id == HASH_ID || trait_id == ORD_ID",
        "trait_id == EQ_ID || trait_id == HASH_ID || trait_id == ORD_ID || trait_id == BIT_AND_ID"),),
    "effect-forward": ((CHECKER,
        "XCallFn(ms.sig.owner, emitted_fn_name(ms.sig, mn), args, [wr], evs, Some(tid),",
        "XCallFn(ms.sig.owner, emitted_fn_name(ms.sig, mn), args, [wr], (if tid == SHL_ID { [] } else { evs }), Some(tid),"),),
    "narrow-logical": ((I8,
        "impl Ushr[I8] {\n  type UshrAmount = Int\n  fn ushr(a: I8, n: Int) -> I8 = {\n    let x: Int = a\n    let u = x & 0xFF",
        "impl Ushr[I8] {\n  type UshrAmount = Int\n  fn ushr(a: I8, n: Int) -> I8 = {\n    let x: Int = a\n    let u = x"),),
    "negative-count": ((I8, "wrap(u << (n & 7))", "wrap(u << (n % 8))"),),
    "unsigned-right": ((U64,
        "fn shr(a: U64, n: Int) -> U64 = {\n    let x: Int = a\n    x >>> (n & 63)",
        "fn shr(a: U64, n: Int) -> U64 = {\n    let x: Int = a\n    x >> (n & 63)"),),
    "c-truncation": ((C,
        "  } else if op == CDiv && ty == TyInt {",
        '  } else if op == CBand && rv == "INT64_C(255)" {\n    (st2, lv)\n  } else if op == CDiv && ty == TyInt {'),),
}


def main():
    name, root = sys.argv[1], Path(sys.argv[2])
    for rel, old, new in MUTATIONS[name]:
        path = root / rel
        text = path.read_text()
        if text.count(old) != 1:
            raise SystemExit(f"{name}: {rel}: expected exactly one match")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
