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
#include <string.h>

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

/* `array_steal` borrows the array and answers an owned slot reference. Alone
 * it transfers the slot's own reference out -- slot NULL, the child's count
 * untouched -- and shared it dups, leaving the slot's reference in place so
 * every other version still reads it. Both halves are asserted, counters
 * included, plus the caller's obligation shape: the emptied slot is written
 * back through `array_with` before anything reads it. */
static void test_array_steal(void) {
  dawn_array *xs = dawn_array_new();
  for (int i = 0; i < 8; i++) {
    dawn_box *e = dawn_box_int(i);
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
  static const char want[] = "Array index out of bounds";
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

/* The runtime builds `None` for `parse_float`, `io_getenv` and every
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

/* The named assertions, in the order they run. Names rather than a bare call
 * list because scripts/rc-contract/matrix.txt records which of them a mutant
 * reddens, and a red set is only a record if its members have names. The
 * lines go to stdout as `<name> PASS|FAIL`, one per case; `run.sh` reads them
 * and the exit status still says whether anything failed. */
typedef struct {
  const char *name;
  void (*fn)(void);
} rc_case;

static const rc_case rc_cases[] = {
    {"counts", test_counts},
    {"sharing", test_sharing},
    {"mask_skips_scalars", test_mask_skips_scalars},
    {"array", test_array},
    {"array_with", test_array_with},
    {"array_steal", test_array_steal},
    {"deep_chain", test_deep_chain},
    {"panic_message", test_panic_message},
    {"adt0_singleton", test_adt0_singleton},
    {"none_is_shared", test_none_is_shared},
    {"immortal", test_immortal},
    {"immortal_graph", test_immortal_graph},
};

int main(int argc, char **argv) {
  dawn_rt_init(argc, argv);
  int leak_mode = argc > 1 && argv[1][0] == 'l';

  if (leak_mode) {
    failures = 0;
    test_leak_mode();
    printf("leak_mode %s\n", failures > 0 ? "FAIL" : "PASS");
  } else {
    for (size_t i = 0; i < sizeof(rc_cases) / sizeof(rc_cases[0]); i++) {
      int before = failures;
      rc_cases[i].fn();
      printf("%s %s\n", rc_cases[i].name, failures > before ? "FAIL" : "PASS");
    }
  }

  if (failures > 0) {
    fprintf(stderr, "%d check(s) failed\n", failures);
    return 1;
  }
  printf("ok\n");
  return 0;
}
