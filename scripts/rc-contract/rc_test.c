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

#include "dawn_rt.h"

#include <stdio.h>
#include <stdlib.h>

/* The Unicode tables are `extern` in the runtime and emitted by the compiler
 * alongside the program (emitc's `emit_case_table`). Nothing here touches
 * case or classification, so empty ones are enough to link. */
const dawn_case_range dawn_upper_ranges[] = {{0, 0, 0}};
const int64_t dawn_upper_ranges_n = 0;
const dawn_case_range dawn_lower_ranges[] = {{0, 0, 0}};
const int64_t dawn_lower_ranges_n = 0;
const dawn_cp_range dawn_letter_ranges[] = {{0, 0}};
const int64_t dawn_letter_ranges_n = 0;
const dawn_cp_range dawn_digit_ranges[] = {{0, 0}};
const int64_t dawn_digit_ranges_n = 0;
const dawn_cp_range dawn_upper_class_ranges[] = {{0, 0}};
const int64_t dawn_upper_class_ranges_n = 0;
const dawn_cp_range dawn_lower_class_ranges[] = {{0, 0}};
const int64_t dawn_lower_class_ranges_n = 0;
const dawn_cp_range dawn_space_ranges[] = {{0, 0}};
const int64_t dawn_space_ranges_n = 0;

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
  dawn_box *child = dawn_box_int(7);
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
    dawn_box *elem = dawn_box_int(i);
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
    dawn_box *e = dawn_box_int(i);
    dawn_array *n = dawn_array_push(xs, e);
    dawn_drop(e);
    dawn_drop(xs);
    xs = n;
  }
  uint64_t inplace0 = dawn_array_with_inplace;
  uint64_t copied0 = dawn_array_with_copied;

  /* shared: the caller keeps xs, so it dups both arguments in */
  dawn_box *replacement = dawn_box_int(99);
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

static void test_immortal(void) {
  dawn_adt *a = dawn_adt_new(0, 0, 0);
  a->h.rc = DAWN_IMMORTAL;
  dawn_dup(a);
  check(a->h.rc == DAWN_IMMORTAL, "dup does not move an immortal count");
  dawn_drop(a);
  check(a->h.rc == DAWN_IMMORTAL, "drop does not move it either");
  free(a); /* by hand: drop would never have */
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
    dawn_box *e = dawn_box_int(i);
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
  dawn_box *replacement = dawn_box_int(99);
  dawn_array *ys = dawn_array_with(xs, 3, replacement);
  check(dawn_array_with_copied == copied0 + 1, "a rebuild copies an immortal array");
  check(dawn_array_with_inplace == inplace0, "it does not write one in place");
  check(((dawn_box *)dawn_array_get(xs, 3))->val.i == 3, "the constant is unchanged");
  check(((dawn_box *)dawn_array_get(ys, 3))->val.i == 99, "the copy has the new value");
  dawn_drop(ys);
}

/* --rc=leak. Nothing is freed, so this runs last and the harness turns the
 * leak check off for it -- the leaks are the point. */
static void test_leak_mode(void) {
  dawn_rc_leak = true;
  dawn_adt *a = dawn_adt_new(0, 1, MASK1);
  a->fields[0].p = dawn_box_int(1);
  dawn_drop(a);
  check(a->h.rc == 1, "leak mode leaves the count alone");
  check(dawn_is_unique(a), "and the value is still live");
  dawn_rc_leak = false;
}

int main(int argc, char **argv) {
  dawn_rt_init(argc, argv);
  int leak_mode = argc > 1 && argv[1][0] == 'l';

  if (leak_mode) {
    test_leak_mode();
  } else {
    test_counts();
    test_sharing();
    test_mask_skips_scalars();
    test_array();
    test_array_with();
    test_deep_chain();
    test_immortal();
    test_immortal_graph();
  }

  if (failures > 0) {
    fprintf(stderr, "%d check(s) failed\n", failures);
    return 1;
  }
  printf("ok\n");
  return 0;
}
