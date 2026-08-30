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
  dawn_box *first = dawn_box_int(11);
  dawn_box *held = (dawn_box *)dawn_dup(first);
  void *c = dawn_cell_new(first);
  check(held->h.rc == 2, "cell_new keeps the reference it was handed");
  check(dawn_cell_get(c) == first, "and the slot holds it");

  dawn_cell_set(c, dawn_box_int(22));
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
  dawn_box *v = dawn_box_int(33);
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
  dawn_cell_set(c, dawn_box_int(44));
  check(((dawn_box *)dawn_cell_get(c))->val.i == 44, "the write-back restores the slot");

  dawn_drop(taken);
  dawn_drop(c);
}

/* `cell_get` hands back a borrowed reference out of the slot, exactly like an
 * ADT field read: no count moves and the slot keeps what it had. Read twice,
 * because a get that transferred would leave the second read looking at an
 * emptied slot rather than at the value. */
static void test_cell_get_does_not_transfer(void) {
  dawn_box *v = dawn_box_int(55);
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
 * ## The allowance the poisoned leg gets, and why it is not a loosened bound
 *
 * AddressSanitizer keeps one shadow byte per eight bytes of address space,
 * and the hand poisoning (dawn_rt.c, "manual poisoning") writes that shadow
 * for every slab the allocator carves. madvise hands the slab's own pages
 * back; the shadow pages stay, because the sanitizer owns that mapping and
 * has no interface for returning part of it -- writing to it directly, or
 * madvising it, would be reaching into the runtime's internal layout.
 *
 * The arithmetic is not close, it is exact. The case allocates 64MiB in
 * 32-byte blocks: 2097152 objects, 1024 slabs of 64KiB, and 64MiB / 8 =
 * *8192 KiB* of shadow. The old allowance was 8 * 1024 = 8192 KiB. So on a
 * poisoned build the shadow alone accounted for the entire budget, and what
 * was left for everything else was however much of that shadow happened to
 * be resident already when `base` was read -- which is to say, however many
 * slabs the fourteen cases ahead of this one had carved.
 *
 * Measured, not reasoned. Running the whole roster here: after - base =
 * 7844 KiB against 8192, bit-identical over three runs, a margin of 348 KiB
 * (87 pages, 4%) supplied entirely by the ~44 slabs the earlier cases had
 * already touched. Running this case *alone*, so that nothing is pre-
 * resident, on the same machine and the same binary: after - base = 8924
 * KiB, which fails the old bound. That is the CI failure reproduced locally
 * and it settles what it was: not a flake, and not the runner being slow or
 * small, but a knife edge whose green side depended on how much of the
 * measurement had been paid for before the measurement started.
 *
 * So the poisoned build is allowed, on top of the unchanged 8192 KiB, the
 * shadow of exactly the address range it makes the allocator carve. That is
 * a quantity the build provably cannot return, derived rather than tuned.
 * The worst figure measured above, the 8924 KiB that fails the old bound,
 * now sits 46% under the new one. The assertion keeps its teeth: a runtime
 * that stops retiring leaves ~65MiB of slab pages *plus* that same shadow,
 * four and a half times the widened limit. Verified by mutant rather than by
 * argument -- slab-never-retires still reddens this case on a poisoned
 * build, and slab-swallows-oversize still leaves it green there, which is
 * the red set matrix.txt records for both off the plain leg.
 *
 * The plain build's limit does not move by one byte. Every mutant's red set
 * is read off the plain leg, so that is where this bound is load bearing,
 * and an allowance granted only under DAWN_ASAN cannot reach it. */
static void test_slab_returns_pages(void) {
  size_t node = sizeof(dawn_adt) + sizeof(dawn_slot);
  long count = (long)((64 * 1024 * 1024) / node);

  /* The address range the loop below makes the allocator carve, rounded up
   * to whole slabs because a slab is poisoned whole, and the shadow of it at
   * the sanitizer's fixed 1:8 scale. Zero without the sanitizer, and the
   * only build that both defines DAWN_ASAN and reaches this line is the
   * -DDAWN_SLAB_FORCE leg: the bypassed sanitized builds skip the case. */
  long shadow_kib = 0;
#if DAWN_ASAN
  size_t block = ((node + DAWN_SLAB_GRAIN - 1) / DAWN_SLAB_GRAIN) * DAWN_SLAB_GRAIN;
  size_t carved = ((size_t)count * block + 65535u) / 65536u * 65536u;
  shadow_kib = (long)(carved / 8 / 1024);
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
  long after = rss_kib();

  check(peak - base > 48 * 1024, "64MiB of live objects is resident");
  check(after - base < 8 * 1024 + shadow_kib,
        "and releasing them gives the pages back");
}

/* The bound the header states, read off the counters rather than off the
 * source: slabs really are retired (a run that never called madvise has a
 * bound nothing is holding it to), and the empty ones being kept for reuse
 * are within DAWN_SLAB_KEEP per class. Runs after the case above, which is
 * what makes the retirement count non-trivial. */
static void test_slab_bound_is_honoured(void) {
  uint64_t live = 0;
  uint64_t cached = 0;
  uint64_t retired = 0;
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
  int slab; /* asks a question only a build with the slab allocator can answer */
} rc_case;

static const rc_case rc_cases[] = {
    {"slab_materializes_on_demand", test_slab_materializes_on_demand, 1},
    {"counts", test_counts, 0},
    {"sharing", test_sharing, 0},
    {"mask_skips_scalars", test_mask_skips_scalars, 0},
    {"array", test_array, 0},
    {"array_with", test_array_with, 0},
    {"array_steal", test_array_steal, 0},
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
    {"slab_bound_is_honoured", test_slab_bound_is_honoured, 1},
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
