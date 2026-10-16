/* Contract test for the reference-count half of the C runtime
 * (docs/perceus-design.md).
 *
 * This is C rather than Dawn on purpose: until the Core pass lands (knife 2)
 * nothing emitted calls dup or drop, so there is no Dawn program that can
 * reach them. The ABI still has to be right before anything is built on it.
 *
 * The oracle is the sanitizer, not printed output. A drop that fails to
 * recurse shows up as a leak; a drop that recurses twice, or frees something
 * still shared, shows up as a double free or a use-after-free. Both are
 * exactly the class of bug this file exists to catch, and neither is visible
 * from inside the program. */

/* mincore and sysconf, for the allocator's first-touch assertion. */
#define _DEFAULT_SOURCE 1
#define _POSIX_C_SOURCE 200809L

#include "dawn_rt.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if DAWN_SLAB_ACTIVE
#include <sys/mman.h>
#endif
#include <sys/wait.h>
#include <unistd.h>

#include "unicode_stubs.h"

static int failures;

static void check(int ok, const char *what) {
  if (!ok) {
    fprintf(stderr, "FAIL %s\n", what);
    failures++;
  }
}

/* one boxed field */
#define MASK1 UINT64_C(1)

static void test_counts(void) {
  dawn_adt *a = dawn_adt_new(0, 0, 0);
  check(dawn_is_unique(a), "a fresh value is unique");
  dawn_dup(a);
  check(!dawn_is_unique(a), "dup makes it shared");
  dawn_drop(a);
  check(dawn_is_unique(a), "drop makes it unique again");
  dawn_drop(a); /* freed here */
}

/* A child held by two parents is freed once, with the second parent, and not
 * before -- the case a naive drop gets wrong in whichever direction it errs. */
static void test_sharing(void) {
  dawn_box *child = dawn_box_int_heap(7);
  dawn_adt *p1 = dawn_adt_new(0, 1, MASK1);
  p1->fields[0].p = child;
  dawn_adt *p2 = dawn_adt_new(0, 1, MASK1);
  p2->fields[0].p = dawn_dup(child);

  dawn_drop(p1);
  check(dawn_is_unique(child), "the survivor holds the last reference");
  check(child->val.i == 7, "and the child is still readable");
  dawn_drop(p2);
}

/* A scalar field must not be walked: the mask bit is clear, so whatever bit
 * pattern the slot holds is never treated as a pointer. */
static void test_mask_skips_scalars(void) {
  dawn_adt *a = dawn_adt_new(0, 2, 0); /* no pointer fields */
  a->fields[0].i = 0x4142434445464748;
  a->fields[1].f = 3.5;
  dawn_drop(a);
}

/* Arguments are borrowed and the callee counts what it keeps (see the header),
 * so an accumulation owes a drop on the version it replaced and on the element
 * it handed over. Writing it out is the point: this is the shape every
 * emitted accumulation will have once knife 2 inserts the same drops. */
static void test_array(void) {
  dawn_array *xs = dawn_array_new();
  for (int i = 0; i < 1000; i++) {
    dawn_box *elem = dawn_box_int_heap(i);
    dawn_array *next = dawn_array_push(xs, elem);
    dawn_drop(elem);
    dawn_drop(xs);
    xs = next;
  }
  check(dawn_array_len(xs) == 1000, "the accumulation kept every element");
  check(((dawn_box *)dawn_array_get(xs, 999))->val.i == 999, "and the last one reads back");
  dawn_drop(xs);
}

/* `array_with` consumes what it is given (the one owned-argument primitive),
 * and answers uniqueness with reuse: shared, it copies and the version it
 * came from stays intact; alone, it writes the slot in place and hands the
 * same array back. Both halves are asserted, counters included. */
static void test_array_with(void) {
  dawn_array *xs = dawn_array_new();
  for (int i = 0; i < 8; i++) {
    dawn_box *e = dawn_box_int_heap(i);
    dawn_array *n = dawn_array_push(xs, e);
    dawn_drop(e);
    dawn_drop(xs);
    xs = n;
  }
  uint64_t inplace0 = dawn_array_with_inplace;
  uint64_t copied0 = dawn_array_with_copied;

  /* shared: the caller keeps xs, so it dups both arguments in */
  dawn_box *replacement = dawn_box_int_heap(99);
  dawn_array *ys = dawn_array_with(dawn_dup(xs), 3, dawn_dup(replacement));
  check(dawn_array_with_copied == copied0 + 1, "a shared array is copied");
  check(((dawn_box *)dawn_array_get(xs, 3))->val.i == 3, "the base is unchanged");
  check(((dawn_box *)dawn_array_get(ys, 3))->val.i == 99, "the copy has the new value");
  dawn_drop(ys);

  /* alone: xs's reference is handed over, and the same array comes back */
  dawn_array *zs = dawn_array_with(xs, 3, replacement);
  check(dawn_array_with_inplace == inplace0 + 1, "a unique array is written in place");
  check(zs == xs, "and it is the same array");
  check(((dawn_box *)dawn_array_get(zs, 3))->val.i == 99, "with the new value in the slot");
  dawn_drop(zs);
}

/* `array_with` consumes both arguments, and that has to hold on the panic
 * path too: an out-of-bounds index raises, `catch_panic` resumes, and the
 * references handed in are not in any frame that will release them. The
 * subject and the element are owned by the test, each lent to the call as a
 * dup, so after the catch the only count left on either must be the test's
 * own. A path that raised without dropping leaves both at 2 (and, in the
 * sanitized run, a leaked array, buffer and element per call). */
static dawn_array *with_oob_subject;
static dawn_box *with_oob_elem;

static void *with_out_of_bounds(dawn_clo *f) {
  (void)f;
  return dawn_array_with(dawn_dup(with_oob_subject), 99, dawn_dup(with_oob_elem));
}

static void test_array_with_oob_releases_arguments(void) {
  dawn_array *xs = dawn_array_new();
  for (int i = 0; i < 4; i++) {
    dawn_box *e = dawn_box_int_heap(i);
    dawn_array *n = dawn_array_push(xs, e);
    dawn_drop(e);
    dawn_drop(xs);
    xs = n;
  }
  with_oob_subject = xs;
  with_oob_elem = dawn_box_int_heap(7);
  dawn_clo *c = dawn_clo_new((void *)with_out_of_bounds, 0, 0);
  for (int k = 0; k < 3; k++) {
    dawn_adt *r = dawn_catch_panic(c, NULL);
    check(r->tag == DAWN_TAG_ERR, "an out-of-bounds with raises a panic");
    dawn_drop(r);
  }
  check(xs->h.rc == 1, "the array handed to a panicking with is released");
  check(with_oob_elem->h.rc == 1, "and so is the element");
  check(((dawn_box *)dawn_array_get(xs, 3))->val.i == 3, "the subject is intact");
  dawn_drop(c);
  dawn_drop(with_oob_elem);
  dawn_drop(xs);
  with_oob_subject = NULL;
  with_oob_elem = NULL;
}

/* `array_steal` borrows the array and answers an owned slot reference. Alone
 * it transfers the slot's own reference out -- slot NULL, the child's count
 * untouched -- and shared it dups, leaving the slot's reference in place so
 * every other version still reads it. Both halves are asserted, counters
 * included, plus the caller's obligation shape: the emptied slot is written
 * back through `array_with` before anything reads it. */
static void test_array_steal(void) {
  dawn_array *xs = dawn_array_new();
  for (int i = 0; i < 8; i++) {
    dawn_box *e = dawn_box_int_heap(i);
    dawn_array *n = dawn_array_push(xs, e);
    dawn_drop(e);
    dawn_drop(xs);
    xs = n;
  }
  uint64_t taken0 = dawn_array_steal_taken;
  uint64_t dup0 = dawn_array_steal_dup;

  /* shared: a second holder pins the array, so the slot keeps its reference
   * and the answer is a fresh one */
  dawn_array *held = (dawn_array *)dawn_dup(xs);
  dawn_box *shared = (dawn_box *)dawn_array_steal(xs, 3);
  check(dawn_array_steal_dup == dup0 + 1, "a shared array answers a dup");
  check(dawn_array_steal_taken == taken0, "and transfers nothing");
  check(xs->buf->data[3] != NULL, "the slot keeps its reference");
  check(shared->val.i == 3, "the dup reads the slot's value");
  check(((dawn_box *)dawn_array_get(held, 3))->val.i == 3,
        "and the other version still reads it");
  dawn_drop(shared);
  dawn_drop(held);

  /* alone: the slot's own reference transfers out. The child's count does
   * not move -- the reference changed hands, it was not re-taken. */
  dawn_box *peek = (dawn_box *)dawn_array_get(xs, 3); /* borrowed */
  int32_t child_rc = peek->h.rc;
  dawn_box *taken = (dawn_box *)dawn_array_steal(xs, 3);
  check(dawn_array_steal_taken == taken0 + 1, "a unique array transfers the slot");
  check(xs->buf->data[3] == NULL, "and empties it");
  check(taken == peek, "the same reference changed hands");
  check(taken->h.rc == child_rc, "at the same count");

  /* the caller's obligation: overwrite the emptied slot before any read */
  dawn_array *ys = dawn_array_with(xs, 3, taken);
  check(((dawn_box *)dawn_array_get(ys, 3))->val.i == 3, "the write-back restores the slot");
  dawn_drop(ys);
}

/* `n` boxed ints `base .. base+n-1`, built the way an accumulation does. */
static dawn_array *ints(int base, int n) {
  dawn_array *xs = dawn_array_new();
  for (int i = 0; i < n; i++) {
    dawn_box *e = dawn_box_int_heap(base + i);
    dawn_array *next = dawn_array_push(xs, e);
    dawn_drop(e);
    dawn_drop(xs);
    xs = next;
  }
  return xs;
}

static int array_reads(const dawn_array *a, int base, int n) {
  if (dawn_array_len(a) != n) {
    return 0;
  }
  for (int i = 0; i < n; i++) {
    if (((dawn_box *)dawn_array_get(a, i))->val.i != base + i) {
      return 0;
    }
  }
  return 1;
}

/* `array_extend` borrows both arrays and dups every element it copies, once
 * for the buffer that now holds it -- the one reference-count site the
 * primitive adds. The element's count is the oracle: a missing dup leaves the
 * count where it was, and the drops below then free an element a live version
 * still reads, which AddressSanitizer reports as a use-after-free and the
 * sanitized leg catches even if this file's own checks were to pass. Both
 * halves of the push rule are asserted: alone (the buffer's high-water mark
 * is `a`'s end and there is room) the elements land in `a`'s own buffer, and
 * a second extend of the same base finds the mark moved and copies. */
static void test_array_extend(void) {
  dawn_array *xs = ints(0, 3);
  dawn_array *ys = ints(10, 3);
  int32_t rc_y0 = ((dawn_box *)dawn_array_get(ys, 0))->h.rc;
  int32_t rc_x0 = ((dawn_box *)dawn_array_get(xs, 0))->h.rc;

  dawn_array *zs = dawn_array_extend(xs, ys);
  check(dawn_array_len(zs) == 6, "extend answers the combined length");
  check(zs->buf == xs->buf, "a lone array grows into its own buffer");
  check(((dawn_box *)dawn_array_get(zs, 2))->val.i == 2 &&
            ((dawn_box *)dawn_array_get(zs, 3))->val.i == 10 &&
            ((dawn_box *)dawn_array_get(zs, 5))->val.i == 12,
        "extend keeps a's elements then b's, in order");
  check(array_reads(xs, 0, 3), "the base version is unchanged");
  int dupped = ((dawn_box *)dawn_array_get(ys, 0))->h.rc == rc_y0 + 1;
  check(dupped, "every element copied from b is dup'd for the new holder");
  if (!dupped) {
    /* the drops below would free elements a live version still reads. A
     * failed check leaks instead, so a mutant of this count is read off the
     * assertion rather than off a crash. */
    return;
  }
  check(((dawn_box *)dawn_array_get(xs, 0))->h.rc == rc_x0,
        "an element already in the buffer is not dup'd again in place");

  /* the mark has moved past xs, so a second extend of xs copies */
  dawn_array *ws = dawn_array_extend(xs, ys);
  check(ws->buf != xs->buf, "a second extend of the same base copies");
  check(((dawn_box *)dawn_array_get(ws, 0))->h.rc == rc_x0 + 1,
        "a copied element is dup'd for the copy");
  check(((dawn_box *)dawn_array_get(ws, 5))->val.i == 12 &&
            array_reads(xs, 0, 3) && dawn_array_len(zs) == 6,
        "and neither tail shows the other's");

  /* an array extended by itself reads only below its own end */
  dawn_array *dd = dawn_array_extend(ws, ws);
  check(dawn_array_len(dd) == 12 && ((dawn_box *)dawn_array_get(dd, 6))->val.i == 0 &&
            ((dawn_box *)dawn_array_get(dd, 11))->val.i == 12,
        "extending an array by itself doubles it");

  /* empty operands */
  dawn_array *none = dawn_array_new();
  dawn_array *same = dawn_array_extend(xs, none);
  check(array_reads(same, 0, 3), "extend by empty is the same elements");
  dawn_array *only = dawn_array_extend(none, ys);
  check(array_reads(only, 10, 3), "extend of empty is b's elements");

  dawn_drop(only);
  dawn_drop(same);
  dawn_drop(none);
  dawn_drop(dd);
  dawn_drop(ws);
  dawn_drop(zs);
  dawn_drop(ys);
  dawn_drop(xs);
}

static dawn_array *slice_subject;
static int64_t slice_from;
static int64_t slice_to;

static void *slice_out_of_range(dawn_clo *f) {
  (void)f;
  return dawn_array_slice(slice_subject, slice_from, slice_to);
}

/* `array_slice` borrows the array and answers an owned copy of `[from, to)`,
 * each element dup'd. The half-open right end is the claim most worth a
 * mutant: one element too many or too few, and the length check goes red.
 * A range outside `[0, len]`, or with `from > to`, is a panic worded as the
 * JVM words it -- never a clamp. */
static void test_array_slice(void) {
  dawn_array *xs = ints(0, 6);
  int32_t rc_x2 = ((dawn_box *)dawn_array_get(xs, 2))->h.rc;

  dawn_array *mid = dawn_array_slice(xs, 2, 5);
  check(array_reads(mid, 2, 3), "slice [2, 5) is elements 2, 3, 4");
  check(((dawn_box *)dawn_array_get(xs, 2))->h.rc == rc_x2 + 1,
        "every element of the copy is dup'd");
  check(array_reads(xs, 0, 6), "the source is unchanged");

  dawn_array *all = dawn_array_slice(xs, 0, 6);
  check(array_reads(all, 0, 6), "the full range is a copy of everything");
  dawn_array *edge = dawn_array_slice(xs, 6, 6);
  dawn_array *none = dawn_array_slice(xs, 0, 0);
  check(dawn_array_len(edge) == 0 && dawn_array_len(none) == 0, "empty ranges are empty");

  /* pushing onto a slice must not write into the source's buffer */
  dawn_box *extra = dawn_box_int_heap(99);
  dawn_array *grown = dawn_array_push(mid, extra);
  dawn_drop(extra);
  check(array_reads(xs, 0, 6) && array_reads(mid, 2, 3) && dawn_array_len(grown) == 4,
        "a slice is its own array");

  static const char *const want[] = {
      "array slice [-1, 2) out of bounds for length 6",
      "array slice [0, 7) out of bounds for length 6",
      "array slice [4, 3) out of bounds for length 6",
      "array slice [7, 8) out of bounds for length 6",
  };
  static const int64_t bad[][2] = {{-1, 2}, {0, 7}, {4, 3}, {7, 8}};
  slice_subject = xs;
  for (int k = 0; k < 4; k++) {
    slice_from = bad[k][0];
    slice_to = bad[k][1];
    dawn_clo *c = dawn_clo_new((void *)slice_out_of_range, 0, 0);
    dawn_adt *r = dawn_catch_panic(c, NULL);
    check(r->tag == DAWN_TAG_ERR, "a range outside the array raises a panic");
    dawn_adt *err = (dawn_adt *)r->fields[0].p;
    dawn_str *msg = (dawn_str *)err->fields[1].p;
    size_t wl = strlen(want[k]);
    check(msg->len == (int64_t)wl && memcmp(msg->p, want[k], wl) == 0,
          "the slice panic names the range and the length");
    dawn_drop(r);
    dawn_drop(c);
  }
  slice_subject = NULL;

  dawn_drop(grown);
  dawn_drop(none);
  dawn_drop(edge);
  dawn_drop(all);
  dawn_drop(mid);
  dawn_drop(xs);
}

static dawn_i64buf *i64_subject;
static dawn_i64buf *volatile i64_immortal_root;

static void *i64_read_out_of_range(dawn_clo *f) {
  (void)f;
  return (void *)(intptr_t)dawn_i64buf_at(i64_subject, 7);
}

static void *i64_copy_out_of_range(dawn_clo *f) {
  (void)f;
  dawn_i64buf_copy_from(i64_subject, 2, i64_subject, 0, 5);
  return NULL;
}

/* An `I64Buf` is a counted leaf: one block, the elements right after the
 * header, no children. Every primitive borrows it, so a program that calls
 * `at`, `set`, `fill` or `copy_from` in a loop never moves the count -- the
 * claim that keeps those loops free of dup and drop, and so the one worth a
 * mutant: a primitive that takes a reference it does not give back is a leak
 * the sanitized leg reports, and one that gives back a reference it never took
 * is a double free. A panic raised from inside a primitive must leave the
 * count where it was too, because `catch_panic` resumes with the buffer live. */
static void test_i64buf(void) {
  dawn_i64buf *b = dawn_i64buf_new(6);
  check(b->h.rc == 1 && b->len == 6, "a new buffer is owned once and has its length");
  int all_zero = 1;
  for (int64_t i = 0; i < 6; i++) {
    all_zero = all_zero && dawn_i64buf_at(b, i) == 0;
  }
  check(all_zero, "a new buffer is zero-filled");

  dawn_i64buf_set(b, 1, 11);
  dawn_i64buf_set(b, 5, INT64_MIN);
  dawn_i64buf_fill(b, 2, 4, 7);
  check(dawn_i64buf_at(b, 1) == 11 && dawn_i64buf_at(b, 2) == 7 && dawn_i64buf_at(b, 3) == 7 &&
            dawn_i64buf_at(b, 4) == 0 && dawn_i64buf_at(b, 5) == INT64_MIN,
        "set and fill write what at reads");
  dawn_i64buf_copy_from(b, 0, b, 1, 4);
  check(dawn_i64buf_at(b, 0) == 11 && dawn_i64buf_at(b, 1) == 7 && dawn_i64buf_at(b, 3) == 0 &&
            dawn_i64buf_at(b, 5) == INT64_MIN,
        "an overlapping copy within one buffer moves it as a memmove does");
  check(b->h.rc == 1 && dawn_i64buf_len(b) == 6, "no primitive moves the count");

  dawn_i64buf *c = dawn_i64buf_new(3);
  dawn_i64buf_copy_from(c, 0, b, 1, 3);
  check(b->h.rc == 1 && c->h.rc == 1, "a copy between two buffers moves neither count");

  i64_subject = b;
  dawn_clo *r1 = dawn_clo_new((void *)i64_read_out_of_range, 0, 0);
  dawn_adt *e1 = dawn_catch_panic(r1, NULL);
  check(e1->tag == DAWN_TAG_ERR, "a read past the end raises a panic");
  dawn_clo *r2 = dawn_clo_new((void *)i64_copy_out_of_range, 0, 0);
  dawn_adt *e2 = dawn_catch_panic(r2, NULL);
  check(e2->tag == DAWN_TAG_ERR, "a copy past the end raises a panic");
  check(b->h.rc == 1, "a panic from a primitive leaves the count where it was");
  i64_subject = NULL;
  dawn_drop(e2);
  dawn_drop(r2);
  dawn_drop(e1);
  dawn_drop(r1);

  dawn_i64buf *d = dawn_dup(b);
  check(d == b && b->h.rc == 2, "a second holder is a count");
  dawn_drop(d);
  check(b->h.rc == 1, "and giving it up is one back");

  dawn_i64buf_set(c, 0, 5);
  i64_immortal_root = c; /* an immortal block is never freed; a global keeps it reachable */
  dawn_immortal(c);
  check(c->h.rc == DAWN_IMMORTAL && dawn_i64buf_at(c, 0) == 5,
        "a buffer can be made immortal and reads the same");
  dawn_drop(b);
}

/* An `F64Buf` is the same counted leaf over doubles, and its one claim beyond
 * I64Buf's is that no primitive touches the bits: a NaN payload and `-0.0`
 * come out as they went in, through `set`, `fill` and a copy. */
static void test_f64buf(void) {
  dawn_f64buf *b = dawn_f64buf_new(4);
  check(b->h.rc == 1 && dawn_f64buf_len(b) == 4, "a new buffer is owned once and has its length");
  uint64_t zero_bits = 1;
  memcpy(&zero_bits, &b->data[3], sizeof zero_bits);
  check(zero_bits == 0, "a new buffer is zero-filled");

  const uint64_t nan_bits = UINT64_C(0x7FF8000000000001);
  double nan;
  memcpy(&nan, &nan_bits, sizeof nan);
  dawn_f64buf_set(b, 0, nan);
  dawn_f64buf_set(b, 1, -0.0);
  dawn_f64buf_copy_from(b, 2, b, 0, 2);
  uint64_t got0, got1, got2, got3;
  memcpy(&got0, &b->data[0], 8);
  memcpy(&got1, &b->data[1], 8);
  memcpy(&got2, &b->data[2], 8);
  memcpy(&got3, &b->data[3], 8);
  check(got0 == nan_bits && got1 == UINT64_C(0x8000000000000000) && got2 == nan_bits &&
            got3 == UINT64_C(0x8000000000000000),
        "set and a copy keep a NaN payload and the sign of zero");
  dawn_f64buf_fill(b, 0, 4, 2.5);
  check(dawn_f64buf_at(b, 0) == 2.5 && dawn_f64buf_at(b, 3) == 2.5, "fill writes what at reads");
  check(b->h.rc == 1, "no primitive moves the count");
  dawn_f64buf *d = dawn_dup(b);
  check(d == b && b->h.rc == 2, "a second holder is a count");
  dawn_drop(d);
  check(b->h.rc == 1, "and giving it up is one back");
  dawn_drop(b);
}

/* ---- a handler's state cells (docs/handler-state-design.md) --------------
 *
 * The only overwritable slot in the runtime, so the only place a superseded
 * reference can be forgotten. The three cases below are the three sentences
 * of the ownership note at `dawn_cell_new` in dawn_rt.c, one each.
 *
 * Every probe holds a *heap* value. A string literal is DAWN_IMMORTAL and its
 * count never moves, so a leak probe built on one reads the same before and
 * after whatever it was meant to catch. */

/* `cell_set` takes its value owned and releases the one it displaced. The
 * release is read as a count rather than as a free, because a second holder
 * is the only way to look at the old value *after* the set and still be
 * entitled to. Under `cell-set-forgets-the-old-value` the count stays at two
 * and this is the assertion that says so; the leak that mutant also causes is
 * invisible here, since a `counted` mutant is built without the sanitizer. */
static void test_cell_set_releases_the_old_value(void) {
  dawn_box *first = dawn_box_int_heap(11);
  dawn_box *held = (dawn_box *)dawn_dup(first);
  void *c = dawn_cell_new(first);
  check(held->h.rc == 2, "cell_new keeps the reference it was handed");
  check(dawn_cell_get(c) == first, "and the slot holds it");

  dawn_cell_set(c, dawn_box_int_heap(22));
  check(held->h.rc == 1, "cell_set released the value it displaced");
  check(dawn_is_unique(held), "so the second holder now has the last reference");
  check(held->val.i == 11, "and the displaced value is still readable from it");
  check(((dawn_box *)dawn_cell_get(c))->val.i == 22, "the slot holds the new value");

  dawn_drop(held);
  dawn_drop(c);
}

/* `cell_take` transfers the slot's own reference out and leaves the slot
 * empty. The count must not move: the reference changed hands, it was not
 * re-taken, and a take that dup'd instead would forfeit the in-place reuse
 * the primitive exists for. */
static void test_cell_take_empties_and_transfers(void) {
  dawn_box *v = dawn_box_int_heap(33);
  void *c = dawn_cell_new(v);
  dawn_adt *cell = (dawn_adt *)c;
  int32_t rc0 = v->h.rc;

  dawn_box *taken = (dawn_box *)dawn_cell_take(c);
  check(taken == v, "the same reference changed hands");
  check(taken->h.rc == rc0, "at the same count");
  check(dawn_is_unique(taken), "so what came out is uniquely referenced");
  check(cell->fields[0].p == NULL, "and the slot is empty");

  /* the caller's obligation, and the shape the emitter always writes: store
   * into the emptied slot before anything reads it again. The store's own
   * release finds NULL, which `dawn_drop` returns on. */
  dawn_cell_set(c, dawn_box_int_heap(44));
  check(((dawn_box *)dawn_cell_get(c))->val.i == 44, "the write-back restores the slot");

  dawn_drop(taken);
  dawn_drop(c);
}

/* `cell_get` hands back a borrowed reference out of the slot, exactly like an
 * ADT field read: no count moves and the slot keeps what it had. Read twice,
 * because a get that transferred would leave the second read looking at an
 * emptied slot rather than at the value. */
static void test_cell_get_does_not_transfer(void) {
  dawn_box *v = dawn_box_int_heap(55);
  void *c = dawn_cell_new(v);
  int32_t rc0 = v->h.rc;

  dawn_box *seen = (dawn_box *)dawn_cell_get(c);
  check(seen == v, "cell_get answers the slot's own reference");
  check(seen->h.rc == rc0, "and moves no count: the result is borrowed");
  check(((dawn_adt *)c)->fields[0].p == v, "the slot keeps it");
  check(dawn_cell_get(c) == v, "a second read answers the same reference");
  check(v->h.rc == rc0, "still at the same count");

  dawn_drop(c);
}

/* The reason drop walks with an explicit stack. A persistent vector and a
 * HAMT are both deep; at this length C recursion overflows, and run.sh runs
 * this binary under a deliberately small stack so that a regression to
 * recursion is a crash rather than a slow build-up. */
#define CHAIN 200000

static void test_deep_chain(void) {
  dawn_adt *head = NULL;
  for (int i = 0; i < CHAIN; i++) {
    dawn_adt *node = dawn_adt_new(0, 1, MASK1);
    node->fields[0].p = head;
    head = node;
  }
  dawn_drop(head);
}

/* The runtime's own messages, checked whole. `dawn_str` carries an explicit
 * length and is not NUL-terminated, so a literal whose length was written one
 * short does not fail -- it truncates, and the only reader is a human staring
 * at a panic that says "out of bound". Seven of the twenty-six were wrong that
 * way until DAWN_LIT took the counting away from the author; this pins the
 * shortest path from a raise to the bytes a program can read back, so a
 * hand-written length that creeps back in is a failing check and not a typo
 * nobody sees.
 *
 * Reached through `dawn_catch_panic` rather than by reading the literal: the
 * literal is what the fix changed, and a test that read it would pass on the
 * definition it is meant to be checking. */
/* Outside the closure on purpose: a taken unwind path leaks what the
 * discarded C frames held (see `dawn_bracket`'s header), and LeakSanitizer is
 * on for this run. The subject is therefore owned by the caller, which still
 * has a frame after the raise. */
static dawn_array *panic_subject;

static void *panic_out_of_bounds(dawn_clo *f) {
  (void)f;
  return dawn_array_get(panic_subject, 0);
}

static void test_panic_message(void) {
  static const char want[] = "array index 0 out of bounds for length 0";
  panic_subject = dawn_array_new();
  dawn_clo *c = dawn_clo_new((void *)panic_out_of_bounds, 0, 0);
  /* the empty pack: this closure raises nothing that needs evidence, and a
   * barrier's second parameter is the pack its `!e` binder buys */
  dawn_adt *r = dawn_catch_panic(c, NULL);
  check(r->tag == DAWN_TAG_ERR, "an out-of-bounds read raises a panic");
  dawn_adt *err = (dawn_adt *)r->fields[0].p;
  dawn_str *msg = (dawn_str *)err->fields[1].p;
  check(msg->len == (int64_t)sizeof(want) - 1, "the panic message is not truncated");
  check(msg->len == (int64_t)sizeof(want) - 1 &&
            memcmp(msg->p, want, sizeof(want) - 1) == 0,
        "the panic message is the whole literal");
  dawn_drop(r);
  dawn_drop(c);
  dawn_drop(panic_subject);
  panic_subject = NULL;
}

/* A constructor with no fields is one shared immortal object per tag
 * (dawn_rt.h's `dawn_adt0`). Nothing in Dawn can see the sharing -- `==` is
 * structural -- so the property has to be checked here, at the C level, or it
 * is checked nowhere; and the same goes for the other half, that the shared
 * object is out of the ledger and therefore survives every release a program
 * can spell.
 *
 * The mutation this owns is the obvious retreat: hand back a fresh
 * `dawn_adt_new(tag, 0, 0)` instead. That is what the code did before, so
 * every other assertion in this file stays green under it, and only the
 * identity and immortality checks below go red. */
static void test_adt0_singleton(void) {
  dawn_adt *a = dawn_adt0(7);
  dawn_adt *b = dawn_adt0(7);
  check(a == b, "two constructions of one field-less tag are one object");
  check(a->tag == 7, "which reads back its tag");
  check(a->nfields == 0 && a->ptrmask.narrow == 0, "its arity and its empty mask");
  check(a->h.kind == DAWN_K_ADT, "and answers the kind question drop asks");
  check(a->h.rc == DAWN_IMMORTAL, "it is out of the ledger");
  check(!dawn_is_unique(a), "so nothing ever sees it as unique");

  /* dup and drop are the no-ops string literals have had since they joined
   * the ledger -- the same guard, reached by the same comparison */
  dawn_dup(a);
  check(a->h.rc == DAWN_IMMORTAL, "dup does not move its count");
  dawn_drop(a);
  check(a->h.rc == DAWN_IMMORTAL, "drop does not move it either");

  /* The property a fresh allocation loses: it outlives every release. Guarded
   * on immortality because on a counted value this loop is a double free, and
   * the check above has already recorded that it is not immortal -- a mutant
   * should be red, not undefined. */
  if (a->h.rc == DAWN_IMMORTAL) {
    for (int i = 0; i < 100; i++) {
      dawn_dup(a);
      dawn_drop(a);
      dawn_drop(a);
    }
    check(dawn_adt0(7) == a && a->tag == 7 && a->h.rc == DAWN_IMMORTAL,
          "and it survives a hundred releases");
  } else {
    check(0, "and it survives a hundred releases");
  }

  /* sharing is per tag, not global: a tag is the whole content of the value,
   * so two tags may not collapse into one object */
  check(dawn_adt0(8) != a, "a different tag is a different object");
  check(dawn_adt0(8)->tag == 8, "carrying its own tag");

  /* Past the table's bound the answer is an ordinary counted value -- the
   * fallback is exactly the pre-singleton behaviour, and it is the reason the
   * bound needs no care beyond being large enough to be worth having. */
  dawn_adt *far = dawn_adt0(DAWN_ADT0_TAGS);
  check(far->tag == DAWN_ADT0_TAGS && far->nfields == 0,
        "a tag past the table still builds");
  check(dawn_is_unique(far), "as an ordinary counted value");
  dawn_drop(far);
}

/* The runtime builds `None` for `float_of_decimal`, `io_getenv` and every
 * `ForeignError` cause, and it goes through the same shared object emitted
 * code takes: field-less is field-less whoever builds it. */
static void test_none_is_shared(void) {
  dawn_adt *n = dawn_none();
  check(n == dawn_none(), "the runtime's None is the singleton");
  check(n->tag == DAWN_TAG_NONE && n->nfields == 0, "at the prelude's tag");
  check(n->h.rc == DAWN_IMMORTAL, "and out of the ledger");
  dawn_drop(n);
}

static void test_immortal(void) {
  dawn_adt *a = dawn_adt_new(0, 0, 0);
  a->h.rc = DAWN_IMMORTAL;
  dawn_dup(a);
  check(a->h.rc == DAWN_IMMORTAL, "dup does not move an immortal count");
  dawn_drop(a);
  check(a->h.rc == DAWN_IMMORTAL, "drop does not move it either");
  /* By hand, because drop would never have. Through the runtime's own
   * release: the block came from the runtime's allocator, which is not
   * malloc, and libc's free would refuse an address it never handed out. */
  dawn_free(a);
}

/* `dawn_immortal` takes a whole object graph out of the ledger, which is what
 * a comptime constant needs: the emitter builds one once behind a static
 * pointer and never releases it (emitc's `const_builder`).
 *
 * The checks below are what says it marks the graph rather than the root: a
 * child left at rc 1 is a *unique* value, and `dawn_array_with` writes a
 * unique array in place, so the constant would be overwritten through its own
 * buffer.
 *
 * This file is the only place that can say so. Root-only marking was tried
 * against the whole native corpus on 2026-08-04 and every program stayed
 * green, including a 1100-element constant appended to -- the smallest shape
 * that reaches `array_with` from Dawn at all -- because the RC pass dups the
 * array before the call and `dawn_is_unique` then answers no either way. So
 * the property is checked here, against `dawn_array_with` directly, or it is
 * checked nowhere.
 *
 * The graph here is the shape a folded list really has: an array, its buffer,
 * and boxed elements -- three kinds, reached through three different child
 * rules. */

/* What keeps the graph reachable, for the same reason the emitter's builder
 * keeps a constant in a static: an immortal graph is never freed, and
 * LeakSanitizer's question is reachability, not liveness. External linkage on
 * purpose -- a `static` whose only use is a store is a store the optimiser may
 * delete, and at -O1 it did: the subject was then reported as a leak by the
 * very check it exists to satisfy. */
void *dawn_rc_test_immortal_root;

static void test_immortal_graph(void) {
  dawn_array *xs = dawn_array_new();
  for (int i = 0; i < 8; i++) {
    dawn_box *e = dawn_box_int_heap(i);
    dawn_array *n = dawn_array_push(xs, e);
    dawn_drop(e);
    dawn_drop(xs);
    xs = n;
  }
  dawn_adt *holder = dawn_adt_new(0, 1, MASK1);
  holder->fields[0].p = xs;
  dawn_rc_test_immortal_root = holder;

  dawn_immortal(holder);
  check(holder->h.rc == DAWN_IMMORTAL, "the root is immortal");
  check(xs->h.rc == DAWN_IMMORTAL, "so is the array it holds");
  check(xs->buf->h.rc == DAWN_IMMORTAL, "and the array's buffer");
  check(((dawn_box *)dawn_array_get(xs, 3))->h.rc == DAWN_IMMORTAL,
    "and every boxed element");
  check(!dawn_is_unique(xs), "nothing inside is unique any more");
  check(!dawn_is_unique(xs->buf), "the buffer included");

  /* drop the graph as often as anything could: it must survive all of it */
  for (int i = 0; i < 100; i++) {
    dawn_dup(holder);
    dawn_drop(holder);
    dawn_drop(holder);
  }
  check(((dawn_box *)dawn_array_get(xs, 3))->val.i == 3, "and still reads back");

  /* The property root-only marking would lose. `array_with` is handed the
   * constant's own array with no dup in front of it -- which is exactly what
   * the RC pass emits for an immortal operand, and the reason an immortal
   * operand is safe to hand over at all. Marked graph-wide, the array is not
   * unique and `array_with` copies. Marked root-only it is unique, and
   * `array_with` writes the constant's buffer in place: the value of a `const`
   * changes underneath the program, and nothing before this line notices. */
  uint64_t inplace0 = dawn_array_with_inplace;
  uint64_t copied0 = dawn_array_with_copied;
  dawn_box *replacement = dawn_box_int_heap(99);
  dawn_array *ys = dawn_array_with(xs, 3, replacement);
  check(dawn_array_with_copied == copied0 + 1, "a rebuild copies an immortal array");
  check(dawn_array_with_inplace == inplace0, "it does not write one in place");
  check(((dawn_box *)dawn_array_get(xs, 3))->val.i == 3, "the constant is unchanged");
  check(((dawn_box *)dawn_array_get(ys, 3))->val.i == 99, "the copy has the new value");
  dawn_drop(ys);
}

/* ---- argument-carrying dictionaries (dawn_rt.c, dawn_dict_new) ----------
 *
 * Not reference counting, but here for the same reason the allocator is:
 * nothing in Dawn can see it. A dictionary is never freed by design, so
 * building one per call rather than one per (template, arguments) is a leak
 * in every program that does not exit -- and one no answer a program prints
 * depends on, which is how it survived in the tree. scripts/wasm-dom-contract
 * measures the consequence on a reactor; these two ask the runtime directly.
 *
 * A template per case, because a shared one would let the first case seed the
 * table for the second and the two would stop being independent questions.
 * Different slot counts so that stays true: two identical read-only objects
 * are two the compiler is allowed to fold into one address. */

static const dawn_dict dict_tmpl_a = {1, {NULL}, 0, {NULL}};
static const dawn_dict dict_tmpl_b = {2, {NULL}, 0, {NULL}};
static dawn_dict dict_arg_x = {1, {NULL}, 0, {NULL}};
static dawn_dict dict_arg_y = {1, {NULL}, 0, {NULL}};

/* One relation, asked for twice, is one dictionary. */
static void test_dict_is_shared(void) {
  dawn_dict *first = dawn_dict_new(&dict_tmpl_a, 1, &dict_arg_x);
  dawn_dict *again = dawn_dict_new(&dict_tmpl_a, 1, &dict_arg_x);
  check(first == again, "the same relation is the same dictionary");
  check(first->nargs == 1, "and carries its argument count");
  check(first->args[0] == &dict_arg_x, "and its argument");
}

/* A template whose body still mentions a type variable is a *family*, so the
 * arguments are part of the identity and not decoration on it. No program in
 * this tree instantiates one template twice with different arguments -- that
 * was measured, and it is a fact about today's emitter rather than a contract
 * -- so nothing else can go red when the key stops carrying them. This is the
 * only place that shape exists. */
static void test_dict_family_is_keyed(void) {
  dawn_dict *x = dawn_dict_new(&dict_tmpl_b, 1, &dict_arg_x);
  dawn_dict *y = dawn_dict_new(&dict_tmpl_b, 1, &dict_arg_y);
  check(x != y, "one template with two arguments is two dictionaries");
  check(x->args[0] == &dict_arg_x, "each holding the argument it was built for");
  check(y->args[0] == &dict_arg_y, "the other one included");
}

/* ---- the allocator (dawn_rt.h, DAWN_SLAB_ACTIVE) ------------------------
 *
 * Blocks come from the runtime's own size-class slabs, not from malloc.
 * Nothing in Dawn can see that, and neither do the sanitized runs that carry
 * the leak assertions, because those are the builds that bypass it: objects
 * outside malloc's book are objects LeakSanitizer cannot report. So these
 * six assertions and the slab mutants in matrix.txt are the whole oracle
 * for what the allocator does. The retirement assertion -- that the pages
 * go back to the kernel -- is the reason the allocator exists at all.
 *
 * What the allocator does to *memory safety* is a separate leg, because it
 * needs the sanitizer and the slab in the same binary: run.sh builds one
 * with -DDAWN_SLAB_FORCE and asks poison_probe.c about it.
 *
 * On a build without the slab these are skipped, not passed. A vacuous pass
 * reads exactly like a real one, which is the shape this file is here to
 * refuse; the harness only checks that the roster ran, so `SKIP` keeps the
 * bookkeeping honest and the claim absent. */

/* Resident kilobytes, from the second field of /proc/self/statm. Negative
 * where there is no procfs. */
static long rss_kib(void) {
  FILE *f = fopen("/proc/self/statm", "r");
  if (f == NULL) {
    return -1;
  }
  long total = 0;
  long resident = 0;
  int got = fscanf(f, "%ld %ld", &total, &resident);
  fclose(f);
  if (got != 2) {
    return -1;
  }
  return resident * (sysconf(_SC_PAGESIZE) / 1024);
}

/* A string whose whole block is `bytes`, so a case can name a size class
 * instead of guessing at one. */
static dawn_str *block_of(size_t bytes) {
  return dawn_str_new((int64_t)(bytes - sizeof(dawn_str) - 1));
}

/* A logical slab remains 64KiB, but making one current must not make all of
 * those pages resident before the class needs them. This case runs first, so
 * its 2032-byte class has no earlier current slab. mincore observes the
 * mapping directly instead of using a process-wide RSS delta: allocator and
 * libc noise elsewhere in the process cannot turn an eager layout green.
 *
 * The rest of the case is the correctness edge behind the policy. It drains
 * every incremental tranche and checks the exact floor(64KiB / block) count,
 * then empties that non-current slab and makes the allocator take it from the
 * empty list again. That reuse must retain the old full-relayout behaviour:
 * address ordered and complete, not treated as another fresh carve. */
static void test_slab_materializes_on_demand(void) {
  /* Class 127 is deliberately odd, so slab-merges-size-classes does not move
   * this question to a different class. It also does not divide 32KiB: the
   * seventeenth block crosses the first batch boundary and exercises the
   * rounding in dawn_sl_extend. */
  enum { slab_bytes = 65536, block_bytes = 2032 };
  const size_t block = block_bytes;
  const size_t blocks_per_slab = slab_bytes / block;
  dawn_str *first_slab[slab_bytes / block_bytes];
  dawn_str *second_slab[slab_bytes / block_bytes];

  first_slab[0] = block_of(block);
#if DAWN_SLAB_ACTIVE
  /* This literal is deliberately independent of DAWN_SL_BATCH. It keeps the
   * production mutant observable even when one host page is the whole 64KiB
   * logical slab and mincore therefore cannot distinguish the two extents. */
  check(dawn_slab_materialized_bytes(first_slab[0]) == 32768u,
        "one small live set links only its first logical slab batch");
  long page = sysconf(_SC_PAGESIZE);
  int page_shape = page > 0 && slab_bytes % page == 0;
  int aligned = page_shape && (uintptr_t)first_slab[0] % (size_t)page == 0;
  check(page_shape,
        "the logical slab is an exact number of host pages");
  check(aligned, "the first block is host-page aligned");
  if (aligned) {
    size_t pages = slab_bytes / (size_t)page;
    unsigned char resident[slab_bytes];
    memset(resident, 0, pages);
    int got = mincore(first_slab[0], slab_bytes, (void *)resident);
    check(got == 0, "the logical slab's residency can be read");
    if (got == 0) {
      size_t present = 0;
      for (size_t i = 0; i < pages; i++) {
        present += (resident[i] & 1u) != 0;
      }
      /* The 32KiB is the candidate policy being asserted, not a value derived
       * from the runtime. On page sizes below one logical slab this is the
       * physical-RSS half of the observation port assertion above. */
      size_t first_touch = (32768u + (size_t)page - 1) / (size_t)page;
      check(present <= first_touch,
            "one small live set materializes only its first slab batch");
    }
  }
#endif

  for (size_t i = 1; i < blocks_per_slab; i++) {
    first_slab[i] = block_of(block);
    check((uintptr_t)first_slab[i] == (uintptr_t)first_slab[0] + i * block,
          "incremental batches preserve the logical slab's block count");
  }
  second_slab[0] = block_of(block);
  check((uintptr_t)second_slab[0] == (uintptr_t)first_slab[0] + slab_bytes,
        "only a full logical slab advances to the next slot");

  for (size_t i = 0; i < blocks_per_slab; i++) {
    dawn_drop(first_slab[i]);
  }
  for (size_t i = 1; i < blocks_per_slab; i++) {
    second_slab[i] = block_of(block);
    check((uintptr_t)second_slab[i] == (uintptr_t)second_slab[0] + i * block,
          "the replacement current slab also grows in place");
  }

  dawn_str *reuse0 = block_of(block);
  dawn_str *reuse1 = block_of(block);
  dawn_str *reuse2 = block_of(block);
  check(reuse0 == first_slab[0], "an empty logical slab is reused from its start");
  check((uintptr_t)reuse1 == (uintptr_t)reuse0 + block,
        "the empty slab's full relayout stays in address order");
  check((uintptr_t)reuse2 == (uintptr_t)reuse0 + 2 * block,
        "empty-slab reuse retains its complete free list");

  for (size_t i = 0; i < blocks_per_slab; i++) {
    dawn_drop(second_slab[i]);
  }
  dawn_drop(reuse0);
  dawn_drop(reuse1);
  dawn_drop(reuse2);
}

/* Freeing and re-requesting one size gets the same block back. This is the
 * allocator's reason for being on the time axis: without it every one of the
 * self-hosted compiler's 2e8 allocations pays a full malloc. */
static void test_slab_reuses_a_block(void) {
  dawn_str *a = block_of(3 * DAWN_SLAB_GRAIN);
  void *was = a;
  dawn_drop(a);
  dawn_str *b = block_of(3 * DAWN_SLAB_GRAIN);
  check(dawn_slab_owns(b), "a small block comes from the reserve");
  check((void *)b == was, "and a freed one is handed straight back");
  dawn_drop(b);
}

/* Size classes do not leak into each other. A freed block is only ever
 * handed to a request its own class covers, so no caller can be given fewer
 * bytes than it asked for -- the failure a single pool of free blocks makes,
 * and one nothing else in the tree would notice until it corrupted a heap. */
static void test_slab_never_shrinks_a_block(void) {
  dawn_str *small = block_of(2 * DAWN_SLAB_GRAIN);
  void *was = small;
  dawn_drop(small);
  dawn_str *big = block_of(3 * DAWN_SLAB_GRAIN);
  check((void *)big != was, "a bigger request does not get a smaller block");
  dawn_drop(big);
}

/* The property glibc does not have, and the whole point of retiring at the
 * slab rather than bounding a cache of free blocks: a program that allocates
 * 64MiB and releases it is not still holding 64MiB. On a plain malloc build
 * the second check below fails -- small chunks sit under the arena's top
 * chunk and the resident set stays at its high-water mark -- which is why
 * this case is skipped there rather than run and believed.
 *
 * Linux, deliberately: MADV_DONTNEED is what returns the pages, and a
 * platform where it does not (macOS wants MADV_FREE) is one that should be
 * building with -DDAWN_NO_SLAB.
 *
 * ## Why the poisoned leg does not read the resident set
 *
 * AddressSanitizer keeps one shadow byte per eight bytes of address space,
 * and the hand poisoning (dawn_rt.c, "manual poisoning") writes that shadow
 * for every slab the allocator carves. madvise hands the slab's own pages
 * back; the shadow pages stay, because the sanitizer owns that mapping. For
 * this case that is 64MiB / 8 = 8192 KiB, exactly the plain build's whole
 * allowance, so an earlier version widened the bound by the shadow's size.
 * That made the margin depend on how much shadow earlier cases had already
 * made resident, and it failed intermittently on CI (issue 541) with the
 * runtime unchanged. No resident-set bound is both exact and stable there.
 *
 * So the poisoned build asks the allocator instead: the retirement counter
 * (the one test_slab_bound_is_honoured reads) must have advanced by all but
 * a handful of the slabs the loop carved. It is deterministic, and a runtime
 * that stops retiring leaves it at zero. The plain build keeps the resident
 * set check unchanged, and every mutant's red set is read off that leg. */
static void test_slab_returns_pages(void) {
  size_t node = sizeof(dawn_adt) + sizeof(dawn_slot);
  long count = (long)((64 * 1024 * 1024) / node);

  /* The slabs the loop below makes the allocator carve, rounded up to whole
   * slabs because a slab is poisoned whole. Only the -DDAWN_SLAB_FORCE leg
   * both defines DAWN_ASAN and reaches this line: the bypassed sanitized
   * builds skip the case. */
#if DAWN_ASAN
  size_t block = ((node + DAWN_SLAB_GRAIN - 1) / DAWN_SLAB_GRAIN) * DAWN_SLAB_GRAIN;
  size_t carved = ((size_t)count * block + 65535u) / 65536u * 65536u;
  uint64_t slabs = carved / 65536u;
  uint64_t unused_live = 0, unused_cached = 0, retired0 = 0;
  dawn_slab_stats(&unused_live, &unused_cached, &retired0);
#endif

  long base = rss_kib();
  check(base >= 0, "the resident set can be read");
  if (base < 0) {
    return;
  }

  dawn_adt *head = NULL;
  for (long i = 0; i < count; i++) {
    dawn_adt *n = dawn_adt_new(0, 1, MASK1);
    n->fields[0].p = head;
    head = n;
  }
  long peak = rss_kib();
  dawn_drop(head);
  /* The pages are held for reuse until the cache has gone unused for a decay
   * interval; test_slab_retains_a_burst owns that half. What this case owns
   * is that they do go back, so it asks for the sweeps a quiet pair of
   * intervals would have run. */
  dawn_slab_quiesce();
  check(peak - base > 48 * 1024, "64MiB of live objects is resident");
#if DAWN_ASAN
  /* Sanitized: the resident set is not an oracle here (issue 541). The shadow
   * pages the hand poisoning writes stay resident, and how many were already
   * touched depends on the machine, so no RSS bound is both exact and stable.
   * The slab's own retirement count says the same thing without the noise: of
   * the slabs the loop carved (1024), all but the DAWN_SLAB_KEEP the decay
   * keeps for the class, plus the one the allocator still carves from, must
   * have been retired (madvised) by now; measured 1019 of 1024. A drop that
   * releases nothing retires none, far under the line. */
  uint64_t retired1 = 0;
  dawn_slab_stats(&unused_live, &unused_cached, &retired1);
  check(retired1 - retired0 + DAWN_SLAB_KEEP + 1 >= slabs,
        "and releasing them gives the pages back");
#else
  long after = rss_kib();
  check(after - base < 8 * 1024, "and releasing them gives the pages back");
#endif
}

/* The bound the header states, read off the counters rather than off the
 * source: slabs really are retired (a run that never called madvise has a
 * bound nothing is holding it to), and once the decay sweeps have run the
 * empty ones being kept for reuse are within DAWN_SLAB_KEEP per class. Runs
 * after the case above, which is what makes the retirement count
 * non-trivial. */
static void test_slab_bound_is_honoured(void) {
  uint64_t live = 0;
  uint64_t cached = 0;
  uint64_t retired = 0;
  dawn_slab_quiesce();
  dawn_slab_stats(&live, &cached, &retired);
  check(retired > 0, "pages have gone back to the kernel");
  check(cached <= (uint64_t)DAWN_SLAB_KEEP * DAWN_SLAB_CLASSES,
        "and no more empty slabs are held than the bound allows");
  /* The 32MiB idle budget is a spec-level claim, so the 33554432 is written
   * here rather than derived: the check above follows DAWN_SLAB_KEEP wherever
   * it drifts, and a KEEP of 5..7 keeps every mutant's red set intact too, so
   * without this line nothing reds when the budget quietly grows. Class 0 is
   * a dead index (a class is always >= 1), hence CLASSES - 1. */
  check((uint64_t)DAWN_SLAB_KEEP * (DAWN_SLAB_CLASSES - 1) * 65536u <= 33554432u,
        "and the whole idle budget stays within the documented 32MiB");
  check(live > 0, "while the slabs still in use are still there");
}

/* The idle half of the policy: a process that blocks after a burst has the
 * burst's empty slabs returned before the block, not at some later sweep it
 * would never get to run. The block is a real one, read_stdin on a pipe whose
 * writer is a forked child. The child waits long enough for the parent to be
 * parked in read(2), reads the parent's resident set from /proc, and sends
 * that number down the pipe as the bytes the parent is waiting for. So the
 * figure is what the parent held *while* blocked, taken from outside, with no
 * sweep of the parent's own having had a chance to run. */
static void test_slab_returns_before_blocking(void) {
  size_t node = sizeof(dawn_adt) + sizeof(dawn_slot);
  long count = (long)((64 * 1024 * 1024) / node);
#if DAWN_ASAN
  size_t block = ((node + DAWN_SLAB_GRAIN - 1) / DAWN_SLAB_GRAIN) * DAWN_SLAB_GRAIN;
  size_t carved = ((size_t)count * block + 65535u) / 65536u * 65536u;
  uint64_t slabs = carved / 65536u;
  uint64_t unused_live = 0, unused_cached = 0, retired0 = 0;
#endif
  /* Start from a cache of the floor's size, whatever earlier cases left in
   * it, so that the burst below has to fault fresh pages. */
  dawn_slab_before_block();
#if DAWN_ASAN
  dawn_slab_stats(&unused_live, &unused_cached, &retired0);
#endif
  long base = rss_kib();
  dawn_adt *head = NULL;
  for (long i = 0; i < count; i++) {
    dawn_adt *n = dawn_adt_new(0, 1, MASK1);
    n->fields[0].p = head;
    head = n;
  }
  long peak = rss_kib();
  dawn_drop(head);
  check(peak - base > 48 * 1024, "64MiB of live objects is resident");

  int fds[2];
  check(pipe(fds) == 0, "a pipe can be made");
  pid_t parent = getpid();
  pid_t kid = fork();
  if (kid == 0) {
    char path[64];
    char out[32];
    snprintf(path, sizeof path, "/proc/%d/statm", (int)parent);
    usleep(500 * 1000);
    long resident = -1;
    FILE *f = fopen(path, "r");
    if (f != NULL) {
      long total = 0;
      if (fscanf(f, "%ld %ld", &total, &resident) != 2) resident = -1;
      fclose(f);
    }
    int len = snprintf(out, sizeof out, "%ld\n", resident * (sysconf(_SC_PAGESIZE) / 1024));
    if (write(fds[1], out, (size_t)len) < 0) _exit(1);
    _exit(0);
  }
  close(fds[1]);
  dup2(fds[0], 0);
  dawn_bytes *got = dawn_io_read_stdin(1);
  /* One byte asked for; the child's whole line is read by this loop below so
   * the number is complete whatever the pipe's chunking. */
  char line[32] = {0};
  size_t have = 0;
  if (dawn_bytes_len(got) == 1) line[have++] = (char)got->p[0];
  dawn_drop(got);
  while (have < sizeof line - 1) {
    ssize_t k = read(0, line + have, 1);
    if (k <= 0 || line[have] == '\n') break;
    have++;
  }
  waitpid(kid, NULL, 0);
  long blocked = atol(line);
  check(blocked > 0, "the child reported the resident set");
#if DAWN_ASAN
  /* Sanitized: the resident set is not an oracle here (issue 541). The shadow
   * pages the hand poisoning writes stay resident and how many were already
   * touched depends on the machine, so no RSS bound is both exact and stable.
   * The retirement count says the same thing without the noise: the burst's
   * slabs, all but the DAWN_SLAB_KEEP the decay keeps plus the one still
   * carved from, must have been madvised by the time the blocking read
   * returned. A runtime that releases nothing before blocking leaves the
   * count at zero. */
  uint64_t retired1 = 0;
  dawn_slab_stats(&unused_live, &unused_cached, &retired1);
  (void)base;
  check(retired1 - retired0 + DAWN_SLAB_KEEP + 1 >= slabs,
        "and the burst was already back while the parent was blocked");
#else
  check(blocked - base < 8 * 1024,
        "and the burst was already back while the parent was blocked");
#endif
}

/* The other half of the policy: a burst that was just freed is not given back
 * at once. A loop that builds and drops a structure takes its empty slabs
 * straight back, and returning them to the kernel in between is what cost
 * 595,164 page faults in a binary-trees run. Read off the counters: the
 * retirement count must not move while the cache fills, and it must move
 * once the sweeps have run. The 100 is far under what the loop frees (256
 * slabs) and far over the KEEP floor, so neither the page size nor the
 * classes the earlier cases left cached can move it. */
static void test_slab_retains_a_burst(void) {
  uint64_t live = 0;
  uint64_t cached0 = 0;
  uint64_t retired0 = 0;
  dawn_slab_quiesce();
  dawn_slab_stats(&live, &cached0, &retired0);
  size_t node = sizeof(dawn_adt) + sizeof(dawn_slot);
  long count = (long)((16 * 1024 * 1024) / node);
  dawn_adt *head = NULL;
  for (long i = 0; i < count; i++) {
    dawn_adt *n = dawn_adt_new(0, 1, MASK1);
    n->fields[0].p = head;
    head = n;
  }
  dawn_drop(head);
  uint64_t cached1 = 0;
  uint64_t retired1 = 0;
  dawn_slab_stats(&live, &cached1, &retired1);
  check(cached1 > cached0 + 100, "a freed burst stays cached for reuse");
  check(retired1 == retired0, "and none of it has gone back yet");
  dawn_slab_quiesce();
  uint64_t cached2 = 0;
  uint64_t retired2 = 0;
  dawn_slab_stats(&live, &cached2, &retired2);
  check(retired2 > retired1 + 100, "until the cache goes unused for a while");
  check(cached2 <= (uint64_t)DAWN_SLAB_KEEP * DAWN_SLAB_CLASSES,
        "when the surplus goes back in one batch");
}

/* Past the documented cap a request is malloc's, which is what lets one
 * range comparison answer "is this block mine" and why no size class has to
 * cover a large block. The 4096 is written here rather than derived from
 * DAWN_SLAB_MAX on purpose: a mutant that raises the cap must fail this, not
 * move the question it is being asked. */
static void test_oversize_leaves_the_slab(void) {
  dawn_str *small = block_of(2 * DAWN_SLAB_GRAIN);
  check(dawn_slab_owns(small), "a small block is inside the reserve");
  dawn_str *big = dawn_str_new(4096);
  check(!dawn_slab_owns(big), "a 4KiB one is not");
  dawn_str_data(big)[0] = 'x';
  check(dawn_str_data(big)[0] == 'x', "and is writable all the same");
  dawn_drop(big);
  dawn_drop(small);
}

/* ---- reset and reuse of ADT nodes (docs/perceus-reuse-design.md 4.2) -------
 *
 * Every probe holds a heap child (a box) in field 0 and keeps a reference to
 * it, so the child's count is the observation port: it says whether reset
 * released it, and whether dropping the token released it a second time.
 * Field 1 is a scalar. */
/* Drop a token without relying on its mask being clear, which is the one
 * thing only `adt_reset_token_is_a_shell` is allowed to ask: in a poisoned
 * build a mask left set sends the drop into the poison word, and the other
 * cases would die of a fault that belongs to someone else's name. */
static void drop_token(dawn_adt *tok) {
  tok->ptrmask.narrow = 0;
  dawn_drop(tok);
}

static dawn_adt *reset_node(dawn_box *child) {
  dawn_adt *a = dawn_adt_new(0, 2, UINT64_C(1));
  a->fields[0].p = dawn_dup(child);
  a->fields[1].i = 42;
  return a;
}

/* A node somebody else also holds is not ours to write into: reset answers
 * NULL, drops our reference and touches nothing else. */
static void test_adt_reset_shared(void) {
  dawn_box *child = dawn_box_int_heap(1);
  dawn_adt *a = reset_node(child);
  dawn_adt *hold = (dawn_adt *)dawn_dup(a);
  dawn_adt *tok = dawn_adt_reset(a);
  check(tok == NULL, "a shared node gives no token");
  check(hold->h.rc == 1, "the reset still gave up its own reference");
  check(child->h.rc == 2, "and left the children to the other holder");
  check(hold->ptrmask.narrow == UINT64_C(1), "and the mask alone");
  dawn_drop(hold);
  if (tok != NULL) {
    dawn_drop(tok);
  }
  dawn_drop(child);
}

/* Alone, the node is handed back as the token and its children are released:
 * the reference the field held is gone, the one the test kept is not. */
static void test_adt_reset_releases_fields(void) {
  dawn_box *child = dawn_box_int_heap(2);
  dawn_adt *a = reset_node(child);
  check(child->h.rc == 2, "the node holds a reference to its child");
  dawn_adt *tok = dawn_adt_reset(a);
  check(tok == a, "a unique node is its own token");
  check(child->h.rc == 1, "reset released the child");
  drop_token(tok);
  dawn_drop(child);
}

/* The token is a legal, field-less node. Dropping it frees the shell and
 * releases nothing a second time, which is what a panic unwinding the frame
 * that holds it relies on. A second holder of the child makes a double
 * release a count and not a crash. */
static void test_adt_reset_token_is_a_shell(void) {
  dawn_box *child = dawn_box_int_heap(3);
  dawn_box *other = (dawn_box *)dawn_dup(child);
  dawn_adt *a = reset_node(child);
  dawn_adt *tok = dawn_adt_reset(a);
  check(tok != NULL && tok->ptrmask.narrow == 0, "the token carries no pointer fields");
  check(child->h.rc == 2, "the test's two references remain");
  if (tok->ptrmask.narrow != 0) {
    /* already reported; the slots hold poison, so letting the drop walk them
     * would end the run in a fault instead of in a name */
    tok->ptrmask.narrow = 0;
  }
  dawn_drop(tok);
  check(child->h.rc == 2, "dropping the token releases no child");
  dawn_drop(other);
  dawn_drop(child);
}

/* `reuse` turns a token into the next node in place: same block, new tag and
 * mask, one reference. With no token it allocates, and both are counted. */
static void test_adt_reuse_rewrites(void) {
  dawn_box *child = dawn_box_int_heap(4);
  dawn_box *other = (dawn_box *)dawn_dup(child);
  dawn_adt *a = reset_node(child);
  dawn_adt *tok = dawn_adt_reset(a);
  uint64_t taken0 = dawn_adt_reuse_taken;
  uint64_t missed0 = dawn_adt_reuse_missed;
  dawn_adt *b = dawn_adt_reuse(tok, 5, 2, UINT64_C(2));
  check(b == a, "reuse answers the token's own block");
  check(b->tag == 5 && b->nfields == 2, "with the new tag and field count");
  check(b->ptrmask.narrow == UINT64_C(2), "and the new mask");
  check(b->h.rc == 1, "at one reference");
  check(dawn_adt_reuse_taken == taken0 + 1 && dawn_adt_reuse_missed == missed0,
        "and counts the reuse");
  b->fields[0].i = 7;
  b->fields[1].p = dawn_dup(child);
  dawn_drop(b);
  check(child->h.rc == 2, "the new mask decides what the drop releases");
  dawn_adt *c = dawn_adt_reuse(NULL, 3, 2, UINT64_C(0));
  check(c != NULL && c->tag == 3 && c->h.rc == 1, "without a token it allocates");
  check(dawn_adt_reuse_missed == missed0 + 1 && dawn_adt_reuse_taken == taken0 + 1,
        "and counts the miss");
  dawn_drop(c);
  dawn_drop(other);
  dawn_drop(child);
}

/* A field-less constructor is one immortal static (`dawn_adt0`); its count is
 * not 1, and writing a new tag into it would change every `None` in the
 * program. */
static void test_adt_reset_immortal(void) {
  dawn_adt *s = dawn_adt0(9);
  dawn_adt *tok = dawn_adt_reset(s);
  check(tok == NULL, "a shared singleton gives no token");
  check(s->tag == 9 && s->h.rc == DAWN_IMMORTAL, "and stays what it was");
}

/* Under --rc=leak counts only grow, so rc == 1 does not prove the node is
 * alone; reset must take the plain-drop path, which there does nothing. */
static void test_adt_reset_leak_mode(void) {
  dawn_box *child = dawn_box_int_heap(5);
  dawn_adt *a = reset_node(child);
  dawn_rc_leak = true;
  dawn_adt *tok = dawn_adt_reset(a);
  dawn_rc_leak = false;
  check(tok == NULL, "leak mode gives no token");
  check(child->h.rc == 2, "and releases nothing");
  dawn_drop(a);
  dawn_drop(child);
}

/* More than 64 fields keep their mask behind a pointer; those nodes do not
 * take part, and the plain drop releases their children. */
static void test_adt_reset_declines_wide(void) {
  static const uint64_t wide_mask[2] = {UINT64_C(1), UINT64_C(0)};
  dawn_box *child = dawn_box_int_heap(6);
  dawn_adt *a = dawn_adt_new_wide(0, 65, wide_mask);
  for (int i = 0; i < 65; i++) {
    a->fields[i].p = NULL;
  }
  a->fields[0].p = dawn_dup(child);
  dawn_adt *tok = dawn_adt_reset(a);
  check(tok == NULL, "a wide node gives no token");
  check(child->h.rc == 1, "and was dropped whole");
  dawn_drop(child);
}

/* Nothing to reset is not an error: a binding declared and not yet assigned
 * on this path holds NULL, and the drop it replaces would have been a no-op. */
static void test_adt_reset_null(void) {
  check(dawn_adt_reset(NULL) == NULL, "a reset of nothing gives nothing");
}

/* Field stealing (docs/perceus-reuse-design.md 10). The caller read field 0 out
 * of the node without a count; the reset is told so. Field 0's child `a` and
 * field 1's child `b` are each also held twice by the test (`a`, `a2`; `b`,
 * `b2`), so a release that should not happen is a count and not a fault. */
static dawn_adt *steal_node(dawn_box *a, dawn_box *b) {
  dawn_adt *n = dawn_adt_new(0, 3, UINT64_C(3));
  n->fields[0].p = dawn_dup(a);
  n->fields[1].p = dawn_dup(b);
  n->fields[2].i = 42;
  return n;
}

/* Alone: the stolen reference stays with the caller, the other is released.
 * The caller's drop of what it took is the only release of the stolen child. */
static void test_adt_reset_steal_unique(void) {
  dawn_box *a = dawn_box_int_heap(11);
  dawn_box *a2 = (dawn_box *)dawn_dup(a);
  dawn_box *b = dawn_box_int_heap(12);
  dawn_box *b2 = (dawn_box *)dawn_dup(b);
  int f0 = failures;
  dawn_adt *n = steal_node(a, b);
  void *got = n->fields[0].p;
  check(a->h.rc == 3 && b->h.rc == 3, "the node and the test hold both children");
  uint64_t unique0 = dawn_adt_steal_unique;
  dawn_adt *tok = dawn_adt_reset_steal(n, UINT64_C(1));
  check(tok == n, "a unique node is its own token");
  check(a->h.rc == 3, "the stolen child was not released");
  check(dawn_adt_steal_unique == unique0 + 1, "and the steal is counted");
  if (failures != f0) {
    return; /* leak on purpose: the drops below would free what is already gone */
  }
  dawn_drop(got);
  check(a->h.rc == 2, "the caller's drop of what it took is the one release");
  drop_token(tok);
  check(a->h.rc == 2, "dropping the token releases nothing more");
  dawn_drop(a2);
  dawn_drop(a);
  dawn_drop(b2);
  dawn_drop(b);
}

/* The field nobody took is still released by the reset, once: this is what
 * keeps a stolen-from node from leaking the half the new node does not use. */
static void test_adt_reset_steal_releases_the_rest(void) {
  /* the stolen field is an immortal singleton, so a mutant that releases it
   * as well changes no count and frees nothing it should not */
  dawn_box *b = dawn_box_int_heap(16);
  dawn_box *b2 = (dawn_box *)dawn_dup(b);
  dawn_adt *n = dawn_adt_new(0, 3, UINT64_C(3));
  n->fields[0].p = dawn_adt0(2);
  n->fields[1].p = dawn_dup(b);
  n->fields[2].i = 42;
  check(b->h.rc == 3, "the node and the test hold the other child");
  dawn_adt *tok = dawn_adt_reset_steal(n, UINT64_C(1));
  check(tok == n, "a unique node is its own token");
  check(b->h.rc == 2, "the child nobody took was released, once");
  drop_token(tok);
  check(b->h.rc == 2, "and dropping the token releases it no more");
  dawn_drop(b2);
  dawn_drop(b);
}

/* Shared: the node stays alive for its other holder, so what the caller moved
 * out of it is a loan until the reset counts it. */
static void test_adt_reset_steal_shared(void) {
  dawn_box *a = dawn_box_int_heap(13);
  dawn_box *a2 = (dawn_box *)dawn_dup(a);
  dawn_box *b = dawn_box_int_heap(14);
  dawn_box *b2 = (dawn_box *)dawn_dup(b);
  dawn_adt *n = steal_node(a, b);
  dawn_adt *hold = (dawn_adt *)dawn_dup(n);
  int f0 = failures;
  void *got = n->fields[0].p;
  uint64_t shared0 = dawn_adt_steal_shared;
  dawn_adt *tok = dawn_adt_reset_steal(n, UINT64_C(1));
  check(tok == NULL, "a shared node gives no token");
  check(hold->h.rc == 1, "the reset gave up its own reference to the node");
  check(a->h.rc == 4, "the stolen child gained the count the caller skipped");
  check(b->h.rc == 3, "the other child is still the node's");
  check(dawn_adt_steal_shared == shared0 + 1, "and the shared path is counted");
  if (failures != f0) {
    return;
  }
  dawn_drop(got);
  check(a->h.rc == 3, "the caller's drop gives that count back");
  dawn_drop(hold);
  check(a->h.rc == 2 && b->h.rc == 2, "the last holder of the node releases its own");
  dawn_drop(a2);
  dawn_drop(a);
  dawn_drop(b2);
  dawn_drop(b);
}

/* Reset is typed by the compiler and checked here: a value that is not a
 * constructed node (a string reached through an erased position) is dropped,
 * not rewritten. The string is eight bytes long so that, read as a node, its
 * length is a plausible tag and field count of zero, which is what keeps the
 * mutant that skips this test from faulting instead of failing. */
static void test_adt_reset_kind(void) {
  dawn_str *s = dawn_str_copy("abcdefgh", 8);
  dawn_adt *tok = dawn_adt_reset((dawn_adt *)s);
  check(tok == NULL, "a string is no node");
}

/* The compiler pairs a token with a build of the same type, and a type with
 * constructors of several widths can hand a token to the wrong one. The
 * block is the wrong size; it goes back and the build allocates. */
static void test_adt_reuse_mismatch(void) {
  dawn_box *child = dawn_box_int_heap(9);
  dawn_adt *a = reset_node(child);
  dawn_adt *tok = dawn_adt_reset(a);
  tok->ptrmask.narrow = 0; /* the shell case's business; see drop_token */
  uint64_t taken0 = dawn_adt_reuse_taken;
  uint64_t missed0 = dawn_adt_reuse_missed;
  dawn_adt *b = dawn_adt_reuse(tok, 1, 3, UINT64_C(0));
  check(b->nfields == 3 && b->h.rc == 1, "a build of another width is a fresh node of that width");
  check(dawn_adt_reuse_missed == missed0 + 1 && dawn_adt_reuse_taken == taken0,
        "and counts as a miss");
  dawn_drop(b);
  dawn_drop(child);
}

/* Test builds define DAWN_REUSE_POISON (run.sh `warn`): a reset node's slots
 * are then a word no valid value is, so a field read that should have come
 * before the reset cannot go unnoticed. */
static void test_adt_reset_poisons(void) {
  dawn_box *child = dawn_box_int_heap(7);
  dawn_adt *a = reset_node(child);
  dawn_adt *tok = dawn_adt_reset(a);
#ifdef DAWN_REUSE_POISON
  check(tok->fields[0].p == (void *)UINT64_C(0xdeaddeaddeaddead) &&
            tok->fields[1].p == (void *)UINT64_C(0xdeaddeaddeaddead),
        "every slot of a reset node is poisoned");
#else
  check(0, "the contract builds define DAWN_REUSE_POISON");
#endif
  drop_token(tok);
  dawn_drop(child);
}

/* --rc=leak. Nothing is freed, so this runs last and the harness turns the
 * leak check off for it -- the leaks are the point. */
static void test_leak_mode(void) {
  dawn_rc_leak = true;
  dawn_adt *a = dawn_adt_new(0, 1, MASK1);
  a->fields[0].p = dawn_box_int_heap(1);
  dawn_drop(a);
  check(a->h.rc == 1, "leak mode leaves the count alone");
  check(dawn_is_unique(a), "and the value is still live");
  dawn_rc_leak = false;
}

/* The named assertions, in the order they run. Names rather than a bare call
 * list because scripts/rc-contract/matrix.txt records which of them a mutant
 * reddens, and a red set is only a record if its members have names. The
 * lines go to stdout as `<name> PASS|FAIL`, one per case; `run.sh` reads them
 * and the exit status still says whether anything failed. */
typedef struct {
  const char *name;
  void (*fn)(void);
  int slab; /* asks a question only a build with the slab allocator can answer */
} rc_case;

static const rc_case rc_cases[] = {
    {"slab_materializes_on_demand", test_slab_materializes_on_demand, 1},
    {"counts", test_counts, 0},
    {"sharing", test_sharing, 0},
    {"mask_skips_scalars", test_mask_skips_scalars, 0},
    {"array", test_array, 0},
    {"array_with", test_array_with, 0},
    {"array_with_oob_releases_arguments", test_array_with_oob_releases_arguments, 0},
    {"array_steal", test_array_steal, 0},
    {"array_extend", test_array_extend, 0},
    {"array_slice", test_array_slice, 0},
    {"i64buf", test_i64buf, 0},
    {"f64buf", test_f64buf, 0},
    {"adt_reset_shared", test_adt_reset_shared, 0},
    {"adt_reset_releases_fields", test_adt_reset_releases_fields, 0},
    {"adt_reset_token_is_a_shell", test_adt_reset_token_is_a_shell, 0},
    {"adt_reuse_rewrites", test_adt_reuse_rewrites, 0},
    {"adt_reset_immortal", test_adt_reset_immortal, 0},
    {"adt_reset_leak_mode", test_adt_reset_leak_mode, 0},
    {"adt_reset_declines_wide", test_adt_reset_declines_wide, 0},
    {"adt_reset_steal_unique", test_adt_reset_steal_unique, 0},
    {"adt_reset_steal_releases_the_rest", test_adt_reset_steal_releases_the_rest, 0},
    {"adt_reset_steal_shared", test_adt_reset_steal_shared, 0},
    {"adt_reset_null", test_adt_reset_null, 0},
    {"adt_reset_kind", test_adt_reset_kind, 0},
    {"adt_reuse_mismatch", test_adt_reuse_mismatch, 0},
    {"adt_reset_poisons", test_adt_reset_poisons, 0},
    {"cell_set_releases_the_old_value", test_cell_set_releases_the_old_value, 0},
    {"cell_take_empties_and_transfers", test_cell_take_empties_and_transfers, 0},
    {"cell_get_does_not_transfer", test_cell_get_does_not_transfer, 0},
    {"deep_chain", test_deep_chain, 0},
    {"panic_message", test_panic_message, 0},
    {"adt0_singleton", test_adt0_singleton, 0},
    {"none_is_shared", test_none_is_shared, 0},
    {"immortal", test_immortal, 0},
    {"immortal_graph", test_immortal_graph, 0},
    {"dict_is_shared", test_dict_is_shared, 0},
    {"dict_family_is_keyed", test_dict_family_is_keyed, 0},
    {"slab_reuses_a_block", test_slab_reuses_a_block, 1},
    {"slab_never_shrinks_a_block", test_slab_never_shrinks_a_block, 1},
    {"slab_returns_pages", test_slab_returns_pages, 1},
    {"slab_retains_a_burst", test_slab_retains_a_burst, 1},
    {"slab_bound_is_honoured", test_slab_bound_is_honoured, 1},
    {"slab_returns_before_blocking", test_slab_returns_before_blocking, 1},
    {"oversize_leaves_the_slab", test_oversize_leaves_the_slab, 1},
};

int main(int argc, char **argv) {
  dawn_rt_init(argc, argv);
  int leak_mode = argc > 1 && argv[1][0] == 'l';
  const char *only =
      argc == 3 && strcmp(argv[1], "--case") == 0 ? argv[2] : NULL;

  if (leak_mode) {
    failures = 0;
    test_leak_mode();
    printf("leak_mode %s\n", failures > 0 ? "FAIL" : "PASS");
  } else {
    int selected = only == NULL;
    for (size_t i = 0; i < sizeof(rc_cases) / sizeof(rc_cases[0]); i++) {
      if (only != NULL && strcmp(only, rc_cases[i].name) != 0) {
        continue;
      }
      selected = 1;
      if (rc_cases[i].slab && !DAWN_SLAB_ACTIVE) {
        printf("%s SKIP\n", rc_cases[i].name);
        continue;
      }
      int before = failures;
      rc_cases[i].fn();
      printf("%s %s\n", rc_cases[i].name, failures > before ? "FAIL" : "PASS");
    }
    if (!selected) {
      fprintf(stderr, "unknown rc contract case: %s\n", only);
      return 2;
    }
  }

  if (failures > 0) {
    fprintf(stderr, "%d check(s) failed\n", failures);
    return 1;
  }
  printf("ok\n");
  return 0;
}
