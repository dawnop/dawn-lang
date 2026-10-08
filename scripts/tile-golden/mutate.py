#!/usr/bin/env python3
"""Apply one tile-golden mutant's edit to a copy of the repository tree.

    scripts/tile-golden/mutate.py <mutant> <tree-root>

The anchors used to be run.sh arguments: each mutant block handed its old and
new text to `mutant_project`, which passed them to a `patch_pkg` heredoc that
refused a non-unique match. That was correct but self-once: a rewrite of
packages/tileir was noticed only when the tile-golden shard holding that
mutant next ran, and the shards run only on pushes that touch the tile paths
(#254, after #249 found the same gap in delete-contract). Declared here, in
the registry shape mutation-anchor-preflight.py discovers, the same anchors
have two consumers: run.sh applies one mutant per forked package, and the
preflight proves every one exactly-once before any build.

What each mutant claims, and how it has to go red, stays in run.sh beside
its assertions; the keys here are the names run.sh's `mutants` list and
matrix.txt use, in the same order. A mutant is an ordered tuple of edits,
each applied to the text the previous one left, with paths relative to the
tree root: run.sh forks packages/tileir to `<tree>/packages/tileir`, and
copies kernels.dawn to `<tree>/scripts/tile-golden/` for the mutant that edits
a kernel.

Changing this file changes the tile input digest (scripts/tile-gpu-diff/
inputs.py hashes everything under scripts/tile-golden), so it needs a new
layer-2 ledger line like any other tile-path change.
"""

from pathlib import Path
import sys

RENDER = "packages/tileir/src/render.dawn"
DEV = "packages/tileir/src/dev.dawn"
BYTECODE = "packages/tileir/src/bytecode.dawn"
PROG = "packages/tileir/src/prog.dawn"
LOWER = "packages/tileir/src/lower.dawn"
KERNELS = "scripts/tile-golden/kernels.dawn"

MUTATIONS = {
    "drop-store-token": ((
        RENDER,
        ' token=${name(tok_in)}${hints_attr(hints)} : ${ty(ptr_ty)}, ${ty(val_ty)}${opt_ty(mask, mask_ty)} -> token',
        '${hints_attr(hints)} : ${ty(ptr_ty)}, ${ty(val_ty)}${opt_ty(mask, mask_ty)} -> token',
    ),),
    "load-dtype-f64": ((
        DEV,
        't_load(position(p), param_dtype(p), i, shape, strides_or_row_major(shape, strides),',
        't_load(position(p), "f64", i, shape, strides_or_row_major(shape, strides),',
    ),),
    "make-token-as-iota": ((
        BYTECODE,
        'const OP_MAKE_TOKEN: Int = 0x44',
        'const OP_MAKE_TOKEN: Int = 0x3A',
    ),),
    "store-token-unwritten": ((
        BYTECODE,
        'emit_ref(emit_opt_ref(emit_ref(emit_ref(w1, ptrs), value), mask), tok_in)',
        'emit_opt_ref(emit_ref(emit_ref(w1, ptrs), value), mask)',
    ),),
    "f64-tag-as-i64": ((
        BYTECODE,
        '  "f64" -> 9',
        '  "f64" -> 4',
    ),),
    "loop-token-not-carried": ((
        PROG,
        ('        tok = last(results)\n'),
        ('        ()\n'),
    ),),
    "region-stack-pop": ((
        PROG,
        'let (outer, inner) = (saved, ops)',
        'let (outer, inner) = (ops, saved)',
    ),),
    "for-results-not-rolled-back": ((
        BYTECODE,
        'fn roll_back(before: W, after: W) -> W = W { ..after, index: before.index, nvals: before.nvals }',
        'fn roll_back(before: W, after: W) -> W = after',
    ),),
    "addf-no-rounding": ((
        RENDER,
        '  "addf" | "subf" | "mulf" | "divf" | "addf_ftz" | "mulf_ftz" -> " rounding<nearest_even>"',
        '  "addf" | "subf" | "mulf" | "divf" | "addf_ftz" | "mulf_ftz" -> ""',
    ),),
    "bf16-tag-as-i16": ((
        BYTECODE,
        '  "bf16" -> 6',
        '  "bf16" -> 2',
    ),),
    "load-pad-flag-as-token": ((
        BYTECODE,
        'const LOAD_FLAG_PAD: Int = 8',
        'const LOAD_FLAG_PAD: Int = 16',
    ),),
    "ftoi-rounds-instead-of-truncates": ((
        BYTECODE,
        '  "ftoi" -> [SIGNED, ROUND_INT_TO_ZERO]',
        '  "ftoi" -> [SIGNED, ROUND_NEAREST_EVEN]',
    ),),
    "scan-result-drops-the-dim": ((
        BYTECODE,
        ('    let w1 = emit(emit(w0, OP_SCAN), len(tys))\n'
         '    let w2 = list.fold(tys, w1, (w, t) => {'),
        ('    let w1 = emit(emit(w0, OP_SCAN), len(tys))\n'
         '    let w2 = list.fold(list.map(tys, rank0_of), w1, (w, t) => {'),
    ),),
    "atomic-rmw-claims-weak-ordering": ((
        BYTECODE,
        '  _ -> (mode, ORDER_RELAXED, SCOPE_DEVICE)',
        '  _ -> (mode, ORDER_WEAK, SCOPE_DEVICE)',
    ),),
    "atomic-cas-writes-an-rmw-mode": ((
        BYTECODE,
        ('    let w3 = emit(emit(emit(emit(w2, tok), flags), ORDER_RELAXED), SCOPE_DEVICE)\n'
         '    emit_ref(emit_opt_ref(emit_ref(emit_ref(emit_ref(w3, ptrs), cmp), val), mask), tok_in)'),
        ('    let w3 = emit(emit(emit(emit(emit(w2, tok), flags), ORDER_RELAXED), SCOPE_DEVICE), rmw_mode_value("add"))\n'
         '    emit_ref(emit_opt_ref(emit_ref(emit_ref(emit_ref(w3, ptrs), cmp), val), mask), tok_in)'),
    ),),
    "trig-extra-flags": ((
        BYTECODE,
        '    "sin", "cos", "tan", "sinh", "cosh", "atan2", "remf"]))',
        '    "cos", "tan", "sinh", "cosh", "atan2", "remf"]))',
    ),),
    "join-tokens-operand-count-wrong": ((
        BYTECODE,
        'let w1 = emit(emit_op_counted(w0, OP_JOIN_TOKENS, Token), len(toks))',
        'let w1 = emit(emit_op_counted(w0, OP_JOIN_TOKENS, Token), len(toks) + 1)',
    ),),
    "cat-dim-swapped": ((
        BYTECODE,
        'emit_ref(emit_ref(emit(emit_op(w0, OP_CAT, to), dim), lhs), rhs)',
        'emit_ref(emit_ref(emit(emit_op(w0, OP_CAT, to), 1 - dim), lhs), rhs)',
    ),),
    "int-to-ptr-as-ptr-to-int": ((
        BYTECODE,
        'IntToPtrTile(_dst, src, _from, to) -> emit_ref(emit_op(w0, OP_INT_TO_PTR, to), src)',
        'IntToPtrTile(_dst, src, _from, to) -> emit_ref(emit_op(w0, OP_PTR_TO_INT, to), src)',
    ),),
    "ptr-to-int-as-int-to-ptr": ((
        BYTECODE,
        'PtrToIntTile(_dst, src, _from, to) -> emit_ref(emit_op(w0, OP_PTR_TO_INT, to), src)',
        'PtrToIntTile(_dst, src, _from, to) -> emit_ref(emit_op(w0, OP_INT_TO_PTR, to), src)',
    ),),
    "ptr-to-ptr-as-bitcast": ((
        BYTECODE,
        'PtrToPtrTile(_dst, src, _from, to) -> emit_ref(emit_op(w0, OP_PTR_TO_PTR, to), src)',
        'PtrToPtrTile(_dst, src, _from, to) -> emit_ref(emit_op(w0, OP_BITCAST, to), src)',
    ),),
    "i16-tag-as-bf16": ((
        BYTECODE,
        ('  "i16" -> 2\n'),
        ('  "i16" -> 6\n'),
    ),),
    "i64-payload-four-bytes": ((
        BYTECODE,
        '  "i64" -> bytes.freeze(put_le(bytes.buf(), value, 8))',
        '  "i64" -> bytes.freeze(put_le(bytes.buf(), value, 4))',
    ),),
    "e4m3-tag-as-i8": ((
        BYTECODE,
        ('  "f8E4M3FN" -> 10\n'),
        ('  "f8E4M3FN" -> 1\n'),
    ),),
    "e8m0-rounding-as-nearest-even": ((
        BYTECODE,
        '  if to == "f8E8M0FNU" { ROUND_ZERO } else { ROUND_NEAREST_EVEN }',
        '  ROUND_NEAREST_EVEN',
    ),),
    "e8m0-tag-as-f8e5m2": ((
        BYTECODE,
        ('  "f8E8M0FNU" -> 18\n'),
        ('  "f8E8M0FNU" -> 11\n'),
    ),),
    "loop-carried-not-rolled-back": ((
        BYTECODE,
        '    roll_back(w_block, w_body)',
        '    w_body',
    ),),
    "break-values-missing": ((
        BYTECODE,
        '  BreakVals(values, _tys) -> list.fold(values, emit(emit(emit(w0, OP_BREAK), 0), len(values)), emit_ref)',
        '  BreakVals(_values, _tys) -> emit(emit(emit(w0, OP_BREAK), 0), 0)',
    ),),
    "overflow-attr-not-written": ((
        BYTECODE,
        ('  "addi_nsw" -> [OVERFLOW_NSW]\n'
         '  "subi_nuw" -> [OVERFLOW_NUW]\n'
         '  "muli_nw" -> [OVERFLOW_NW]'),
        ('  "addi_nsw" -> []\n'
         '  "subi_nuw" -> []\n'
         '  "muli_nw" -> []'),
    ),),
    "atomic-memory-attrs-swapped": ((
        BYTECODE,
        ('  "add_acquire_tl_blk" -> ("add", ORDER_ACQUIRE, SCOPE_TL_BLK)\n'
         '  "add_release_sys" -> ("add", ORDER_RELEASE, SCOPE_SYS)\n'
         '  "add_acq_rel_device" -> ("add", ORDER_ACQ_REL, SCOPE_DEVICE)'),
        ('  "add_acquire_tl_blk" -> ("add", SCOPE_TL_BLK, ORDER_ACQUIRE)\n'
         '  "add_release_sys" -> ("add", SCOPE_SYS, ORDER_RELEASE)\n'
         '  "add_acq_rel_device" -> ("add", SCOPE_DEVICE, ORDER_ACQ_REL)'),
    ),),
    "rmw-addf-as-add": ((
        BYTECODE,
        '  "addf" -> 4',
        '  "addf" -> 3',
    ),),
    "assert-message-tagged": ((
        BYTECODE,
        '    emit_ref(emit(emit(w1, OP_ASSERT), si), cond)',
        '    emit_ref(emit(emit(emit(w1, OP_ASSERT), 5), si), cond)',
    ),),
    "print-tko-token-unwritten": ((
        BYTECODE,
        '    emit_ref(list.fold(args, emit(emit(w2, si), len(args)), emit_ref), tok_in)',
        '    list.fold(args, emit(emit(w2, si), len(args)), emit_ref)',
    ),),
    "assume-divby-tag-as-same-elements": ((
        BYTECODE,
        'const ATTR_DIV_BY: Int = 8',
        'const ATTR_DIV_BY: Int = 9',
    ),),
    "assume-same-elements-payload-four-bytes": ((
        BYTECODE,
        '  W { ..w, body: list.fold(xs, put_varint(w.body, len(xs)), (b, x) => put_le(b, x, 8)) }',
        '  W { ..w, body: list.fold(xs, put_varint(w.body, len(xs)), (b, x) => put_le(b, x, 4)) }',
    ),),
    "assume-bounded-bounds-swapped": ((
        BYTECODE,
        '    emit_opt_signed(emit_opt_signed(w1, lb), ub)',
        '    emit_opt_signed(emit_opt_signed(w1, ub), lb)',
    ),),
    "global-record-alignment-dropped": ((
        BYTECODE,
        '    let b4 = put_varint(put_varint(put_varint(put_varint(b, si), ti), ci), g.align)',
        '    let b4 = put_varint(put_varint(put_varint(b, si), ti), ci)',
    ),),
    "global-visibility-omitted-at-13-3": ((
        BYTECODE,
        '      put_varint(put_varint(b4, if g.is_private { VIS_PRIVATE } else { VIS_PUBLIC }), if g.constant { 1 } else { 0 })',
        '      b4',
    ),),
    "get-global-symbol-not-written": ((
        BYTECODE,
        ('    let (w2, si) = str_of(w1, sym)\n'
         '    emit(w2, si)'),
        ('    let (w2, _si) = str_of(w1, sym)\n'
         '    w2'),
    ),),
    "visibility-private-written-as-public": ((
        BYTECODE,
        'put_varint(put_varint(b4, if g.is_private { VIS_PRIVATE } else { VIS_PUBLIC }), if g.constant { 1 } else { 0 })',
        'put_varint(put_varint(b4, VIS_PUBLIC), if g.constant { 1 } else { 0 })',
    ),),
    "constant-flag-as-mutable": ((
        BYTECODE,
        'put_varint(put_varint(b4, if g.is_private { VIS_PRIVATE } else { VIS_PUBLIC }), if g.constant { 1 } else { 0 })',
        'put_varint(put_varint(b4, if g.is_private { VIS_PRIVATE } else { VIS_PUBLIC }), 0)',
    ),),
    "hint-dictionary-count-wrong": ((
        BYTECODE,
        'ATTR_DICTIONARY), len(under))',
        'ATTR_DICTIONARY), len(under) + 1)',
    ),),
    "hint-tag-as-dictionary": ((
        BYTECODE,
        'const ATTR_OPTIMIZATION_HINTS: Int = 11',
        'const ATTR_OPTIMIZATION_HINTS: Int = 10',
    ),),
    "hint-flag-bit-misplaced": ((
        BYTECODE,
        'const LOAD_FLAG_HINTS: Int = 2',
        'const LOAD_FLAG_HINTS: Int = 1',
    ),),
    "hint-entry-flag-dropped": ((
        BYTECODE,
        'const FLAG_HAS_HINTS: Int = 0x04',
        'const FLAG_HAS_HINTS: Int = 0x00',
    ),),
    "exp-rounding-unwritten": ((
        BYTECODE,
        ('  } else if op == "exp" && exp_has_rounding() {\n'
         '    Some(ROUND_FULL)'),
        ('  } else if op == "exp" && false {\n'
         '    Some(ROUND_FULL)'),
    ),),
    "mmaf-flags-unwritten": ((
        BYTECODE,
        '    let w2 = if mmaf_has_flags() { emit(w1, MMAF_FLAG_FAST_ACC_UNSET) } else { w1 }',
        '    let w2 = w1',
    ),),
    "header-minor-still-2": ((
        BYTECODE,
        'bytes.put(bytes.put(magic(), BYTECODE_MAJOR), BYTECODE_MINOR)',
        'bytes.put(bytes.put(magic(), BYTECODE_MAJOR), 2)',
    ),),
    "alloca-flags-unwritten": ((
        BYTECODE,
        '    let w1 = emit(emit_op(w0, OP_ALLOCA, t), if shared { ALLOCA_FLAG_GLOBAL } else { 0 })',
        '    let w1 = emit_op(w0, OP_ALLOCA, t)',
    ),),
    "alloca-alignment-as-num-elem": ((
        BYTECODE,
        '    emit(emit(w1, num_elem), align)',
        '    emit(emit(w1, num_elem), num_elem)',
    ),),
    "mmaf-scaled-scale-operand-missing": ((
        BYTECODE,
        '    emit_ref(emit_ref(emit_ref(emit_ref(emit_ref(w1, lhs), rhs), acc), lhs_scale), rhs_scale)',
        '    emit_ref(emit_ref(emit_ref(emit_ref(w1, lhs), rhs), acc), lhs_scale)',
    ),),
    "mmaf-scaled-writes-a-flags-word": ((
        BYTECODE,
        '    let w1 = emit_op(w0, OP_MMAF_SCALED, t)',
        '    let w1 = emit(emit_op(w0, OP_MMAF_SCALED, t), 0)',
    ),),
    "i4-tag-as-i8": ((
        BYTECODE,
        '  "i4" -> 22',
        '  "i4" -> 1',
    ),),
    "e2m1-tag-as-i4": ((
        BYTECODE,
        '  "f4E2M1FN" -> 19',
        '  "f4E2M1FN" -> 22',
    ),),
    "unpack-as-pack": ((
        BYTECODE,
        'const OP_UNPACK: Int = 0x70',
        'const OP_UNPACK: Int = 0x6F',
    ),),
    "pack-result-shape-unhalved": ((
        PROG,
        '  [bits / dtype_bits(to)]',
        '  [lanes_of(shape)]',
    ),),
    "tensor-view-tag-as-ptr": ((
        BYTECODE,
        'bytes.put(bytes.buf(), TAG_TENSOR_VIEW)), ei)',
        'bytes.put(bytes.buf(), TAG_PTR)), ei)',
    ),),
    "partition-view-padding-inline-flag-at-13-3": ((
        BYTECODE,
        'fn partition_view_has_bitfield() -> Bool = at_least(13, 3)',
        'fn partition_view_has_bitfield() -> Bool = false',
    ),),
    "padding-nan-on-integer-elements": ((
        BYTECODE,
        '  PadZero -> Some(PAD_ZERO)',
        '  PadZero -> Some(PAD_NAN)',
    ),),
    "dynamic-dim-written-static": ((
        BYTECODE,
        'if d == DYN_DIM { bytes.put(put_le(b, 0, 7), 0x80) } else { put_le(b, d, 8) }',
        'if d == DYN_DIM { put_le(b, 4096, 8) } else { put_le(b, d, 8) }',
    ),),
    "tensor-shape-as-index-space-shape": ((
        BYTECODE,
        'emit_shape_query(w0, OP_GET_TENSOR_SHAPE, len(dsts), res_ty, src)',
        'emit_shape_query(w0, OP_GET_INDEX_SPACE_SHAPE, len(dsts), res_ty, src)',
    ),),
    "index-space-shape-as-tensor-shape": ((
        BYTECODE,
        'emit_shape_query(w0, OP_GET_INDEX_SPACE_SHAPE, len(dsts), res_ty, src)',
        'emit_shape_query(w0, OP_GET_TENSOR_SHAPE, len(dsts), res_ty, src)',
    ),),
    "make-strided-view-as-partition-view": ((
        BYTECODE,
        'emit_ref(emit_op(w0, OP_MAKE_STRIDED_VIEW, t), src)',
        'emit_ref(emit_op(w0, OP_MAKE_PARTITION_VIEW, t), src)',
    ),),
    "make-gather-view-as-strided-view": ((
        BYTECODE,
        'emit_ref(emit_op(w0, OP_MAKE_GATHER_SCATTER_VIEW, t), src)',
        'emit_ref(emit_op(w0, OP_MAKE_STRIDED_VIEW, t), src)',
    ),),
    "gather-sparse-dim-and-tensor-view-swapped": ((
        BYTECODE,
        'let b2 = put_varint(put_varint(b1, tvi), sparse_dim)',
        'let b2 = put_varint(put_varint(b1, sparse_dim), tvi)',
    ),),
    "atomic-red-scope-and-mode-swapped": ((
        BYTECODE,
        'emit(emit(emit(w2, ORDER_RELAXED), scope_value(scope)), red_mode_value(mode))',
        'emit(emit(emit(w2, ORDER_RELAXED), red_mode_value(mode)), scope_value(scope))',
    ),),
    "atomic-red-value-and-token-swapped": ((
        BYTECODE,
        'emit_ref(emit_ref(list.fold(indices, w4, emit_ref), value), tok_in)',
        'emit_ref(emit_ref(list.fold(indices, w4, emit_ref), tok_in), value)',
    ),),
    "ptr-flags-unwritten": ((
        BYTECODE,
        'fn ptr_param_bits(b: bytes.Buf) -> bytes.Buf = if ptr_has_flags() { put_varint(b, 0) } else { b }',
        'fn ptr_param_bits(b: bytes.Buf) -> bytes.Buf = b',
    ),),
    "ftoi-flags-unwritten": ((
        BYTECODE,
        'fn ftoi_flags(op: String, w: W) -> W = if (op == "ftoi" || op == "ftoi_sat") && ftoi_has_flags() { emit(w, ftoi_flag_word(op)) } else { w }',
        'fn ftoi_flags(op: String, w: W) -> W = w',
    ),),
    "view-inbounds-unwritten": ((
        BYTECODE,
        '  if view_has_inbounds() { list.fold(range(0, n), emit(w, n), (v, _k) => emit_byte(v, 0)) } else { w }',
        '  w',
    ),),
    "header-minor-still-3": ((
        BYTECODE,
        'bytes.put(bytes.put(magic(), BYTECODE_MAJOR), BYTECODE_MINOR)',
        'bytes.put(bytes.put(magic(), BYTECODE_MAJOR), 3)',
    ),),
    "fpowi-exponent-as-float": ((
        BYTECODE,
        'emit_ref(emit_ref(emit_op(w0, OP_FPOWI, t), base), exp)',
        'emit_ref(emit_ref(emit_op(w0, OP_FPOWI, t), base), base)',
    ),),
    "fpowi-as-fpowf": ((
        BYTECODE,
        'emit_ref(emit_ref(emit_op(w0, OP_FPOWI, t), base), exp)',
        'emit_ref(emit_ref(emit_op(w0, OP_FPOWF, t), base), exp)',
    ),),
    "insert-source-and-destination-swapped": ((
        BYTECODE,
        'list.fold(indices, emit_ref(emit_ref(w1, src), dest), emit_ref)',
        'list.fold(indices, emit_ref(emit_ref(w1, dest), src), emit_ref)',
    ),),
    "insert-index-dropped": ((
        BYTECODE,
        ('    let w1 = emit(emit_op_counted(w0, OP_INSERT, to), 2 + len(indices))\n'
         '    list.fold(indices, emit_ref(emit_ref(w1, src), dest), emit_ref)'),
        ('    let w1 = emit(emit_op_counted(w0, OP_INSERT, to), 1 + len(indices))\n'
         '    list.fold(list.drop(indices, 1), emit_ref(emit_ref(w1, src), dest), emit_ref)'),
    ),),
    "loop-return-as-break": ((
        BYTECODE,
        '  Ret -> emit(emit(emit(w0, OP_RETURN), 0), 0)',
        '  Ret -> emit(emit(emit(w0, OP_BREAK), 0), 0)',
    ),),
    "ftof-zero-as-nearest-away": ((
        BYTECODE,
        '  "ftof_zero" -> ROUND_ZERO',
        '  "ftof_zero" -> ROUND_NEAREST_AWAY',
    ),),
    "scalar-param-as-ptr": (
        (
            BYTECODE,
            'use lower.{kparam_ty, Kernel,',
            'use lower.{param_ty, Kernel,',
        ),
        (
            BYTECODE,
            'use prog.{TileProg, ByPtr, ',
            'use prog.{TileProg, ByPtr, ByValue, ',
        ),
        (
            BYTECODE,
            '    let (w1, pi) = ty(w, kparam_ty(kp))',
            '    let (w1, pi) = ty(w, param_ty(match kp {\n      ByPtr(d) -> d\n      ByValue(d) -> d\n    }))',
        ),
    ),
    "scalar-dtype-as-i32": (
        (
            BYTECODE,
            'use prog.{TileProg, ByPtr, ',
            'use prog.{TileProg, ByPtr, ByValue, ',
        ),
        (
            BYTECODE,
            '    let (w1, pi) = ty(w, kparam_ty(kp))',
            '    let (w1, pi) = ty(w, kparam_ty(match kp {\n      ByPtr(d) -> ByPtr(d)\n      ByValue(_d) -> ByValue("i32")\n    }))',
        ),
    ),
    "scalar-arg-index-shifted": ((
        LOWER,
        '    bind(l0, dst, Arg(param), num_tile([], dtype))',
        '    bind(l0, dst, Arg(param + 1), num_tile([], dtype))',
    ),),
    "out-along-twice-accepted": ((
        PROG,
        '} else if list.any(range(0, len(along)), j => list.any(range(0, j), i => along[i] == along[j])) {',
        '} else if false {',
    ),),
    # The one mutant that edits a KERNEL and not packages/tileir: flash_attn's
    # softmax scale read from its parameter goes back to the host constant it
    # was before tileir 0.12.0 (docs/tileir-k4-design.md 5, knife 5).
    "scale-baked-again": ((
        KERNELS,
        'let s: Tile[Float] = mma(tq, load_at(k, [j]).transpose(), 0.0) * scalar(scale)\n',
        'let s: Tile[Float] = mma(tq, load_at(k, [j]).transpose(), 0.0) * f_const(F64, ATT_INV_SQRT_D)\n',
    ),),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutant> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    for rel, old, new in MUTATIONS[mutation]:
        path = root / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{mutation}: mutation anchor in {rel} is not unique "
                             f"({count} matches)")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
