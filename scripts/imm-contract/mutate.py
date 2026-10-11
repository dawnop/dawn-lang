#!/usr/bin/env python3
"""Apply one production mutation to a copy of runtime/c.

Same arrangement as scripts/rc-contract/mutate.py: the copy is what gets
compiled, the working tree is never touched, and every anchor must match
exactly once or the mutation refuses to apply.

Each mutation removes ONE question from the tagged-immediate scheme
(docs/native-immediates-design.md, section 4): a point that reads a header or
a box and has to ask "is this word an immediate?" first. The mutant is the
same point without the question. None of them computes a wrong answer on a
program that never holds an immediate; each one dereferences `(void *)3` on a
program that does, which is why the harness accepts a signal or a sanitizer
report as the red.
"""

from pathlib import Path
import sys


MUTATIONS = {
    # P1: dup writes through the tag.
    "dup-ignores-imm": (
        "dawn_rt.c",
        """void *dawn_dup(void *p) {
  if (p == NULL || dawn_is_imm(p)) {""",
        """void *dawn_dup(void *p) {
  if (p == NULL) {""",
    ),
    # P2: the same, in the inline copy (built with -DDAWN_RT_INLINE_RC).
    "inline-dup-ignores-imm": (
        "dawn_rt.h",
        """static inline void *dawn_dup(void *p) {
  if (p != NULL && !dawn_is_imm(p)) {""",
        """static inline void *dawn_dup(void *p) {
  if (p != NULL) {""",
    ),
    # P3: the out-of-line drop (the whole of it in a plain build, the cold
    # half `dawn_drop_slow` in an inline one) reads the header of a tag.
    "drop-ignores-imm": (
        "dawn_rt.c",
        """  if (dawn_rc_leak || p == NULL || dawn_is_imm(p)) {
    return;
  }
  /* Fast path""",
        """  if (dawn_rc_leak || p == NULL) {
    return;
  }
  /* Fast path""",
    ),
    # P4: the inline drop front.
    "inline-drop-ignores-imm": (
        "dawn_rt.h",
        """  if (p == NULL || dawn_is_imm(p) || dawn_rc_leak) {""",
        """  if (p == NULL || dawn_rc_leak) {""",
    ),
    # P5: an immediate child is queued on the drop work list, and read as a
    # header when it is popped. The immortal walk shares the push.
    "ws-push-ignores-imm": (
        "dawn_rt.c",
        """static void dawn_ws_push(dawn_ws *s, void *p) {
  if (p == NULL || dawn_is_imm(p)) {""",
        """static void dawn_ws_push(dawn_ws *s, void *p) {
  if (p == NULL) {""",
    ),
    # P6
    "is-unique-ignores-imm": (
        "dawn_rt.c",
        """  return p != NULL && !dawn_is_imm(p) && ((const dawn_hdr *)p)->rc == 1;""",
        """  return p != NULL && ((const dawn_hdr *)p)->rc == 1;""",
    ),
    # P7
    "ev-node-ignores-imm": (
        "dawn_rt.c",
        """  if (p == NULL || dawn_is_imm(p) || ((const dawn_hdr *)p)->kind != DAWN_K_ADT) {""",
        """  if (p == NULL || ((const dawn_hdr *)p)->kind != DAWN_K_ADT) {""",
    ),
    # P8
    "discard-ignores-imm": (
        "dawn_rt.c",
        """  if (kv == NULL || dawn_is_imm(kv) || ((dawn_hdr *)kv)->kind != DAWN_K_CLO ||""",
        """  if (kv == NULL || ((dawn_hdr *)kv)->kind != DAWN_K_CLO ||""",
    ),
    # P9: the borrowing read of an Int goes straight to the box.
    "peek-int-reads-the-box": (
        "dawn_rt.h",
        """static inline int64_t dawn_peek_int(const void *b) {
  if (dawn_is_imm(b)) {
    return (int64_t)((intptr_t)b >> 1);
  }
  return ((const dawn_box *)b)->val.i;
}""",
        """static inline int64_t dawn_peek_int(const void *b) {
  return ((const dawn_box *)b)->val.i;
}""",
    ),
    # P9, the owning twin.
    "unbox-int-reads-the-box": (
        "dawn_rt.h",
        """static inline int64_t dawn_unbox_int(void *b) {
  if (dawn_is_imm(b)) {
    return (int64_t)((intptr_t)b >> 1);
  }
  return dawn_unbox_int_heap(b);
}""",
        """static inline int64_t dawn_unbox_int(void *b) {
  return dawn_unbox_int_heap(b);
}""",
    ),
    # P10: a Bool is read as if a heap box had been made for it.
    "peek-bool-reads-the-box": (
        "dawn_rt.h",
        """static inline bool dawn_peek_bool(const void *b) { return ((uintptr_t)b >> 1) & 1u; }""",
        """static inline bool dawn_peek_bool(const void *b) { return ((const dawn_box *)b)->val.b; }""",
    ),
    # P11a: every Int is tagged, so one outside the range loses its top bit.
    "box-int-always-tags": (
        "dawn_rt.h",
        """  if ((uint64_t)v - (uint64_t)DAWN_IMM_MIN < (UINT64_C(1) << DAWN_IMM_BITS)) {""",
        """  if (1) {""",
    ),
    # P11b: the range admits one value too many at the top.
    "box-int-range-off-by-one": (
        "dawn_rt.h",
        """  if ((uint64_t)v - (uint64_t)DAWN_IMM_MIN < (UINT64_C(1) << DAWN_IMM_BITS)) {""",
        """  if ((uint64_t)v - (uint64_t)DAWN_IMM_MIN <= (UINT64_C(1) << DAWN_IMM_BITS)) {""",
    ),
    # P12
    "from-code-points-reads-the-box": (
        "dawn_rt.c",
        """    int64_t cp = dawn_peek_int(dawn_array_get(cps, i));""",
        """    int64_t cp = ((dawn_box *)dawn_array_get(cps, i))->val.i;""",
    ),
    # P13
    "bytes-pack-reads-the-box": (
        "dawn_rt.c",
        """(uint64_t)dawn_peek_int(slots[i]),           \\""",
        """(uint64_t)((dawn_box *)slots[i])->val.i,   \\""",
    ),
    # P14
    "gpu-launch-reads-the-box": (
        "dawn_rt.c",
        """ptrs[i] = (dawn_cu_deviceptr)dawn_peek_int(dawn_array_get(args, i)); /* borrowed */""",
        """ptrs[i] = (dawn_cu_deviceptr)((dawn_box *)dawn_array_get(args, i))->val.i; /* borrowed */""",
    ),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <runtime-dir>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    name, old, new = MUTATIONS[mutation]
    path = root / name
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{mutation}: mutation anchor drifted ({count} matches)")
    path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
