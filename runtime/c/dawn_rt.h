/* The native runtime: scalars, strings, collections, io, and the reference
 * counting that frees them (docs/perceus-design.md -- Phase 4 complete,
 * strings and Bytes counted since 2026-07-29). LeakSanitizer runs over the
 * corpus with detection on: a leak here is a real hole in the counting.
 *
 * Compile generated code with -fwrapv (Dawn's Int wraps like the JVM's long)
 * and -fno-strict-aliasing. Both are load-bearing, not tuning. */
#ifndef DAWN_RT_H
#define DAWN_RT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Unit is a value, not an absence: keeping it uniform means Unit-returning
 * functions need no special case anywhere in the emitter. */
typedef unsigned char dawn_unit;
#define DAWN_UNIT ((dawn_unit)0)

/* ---- the reference-count header (docs/perceus-design.md) ----------------
 *
 * Every heap object starts with one, at offset 0, so `dawn_drop` can ask an
 * erased `void*` what it is holding. That question is unavoidable rather than
 * a convenience: `box_call` allocates a box for a scalar and plain-casts a
 * reference, so a slot's `void*` may be a box, an adt or a closure, and
 * nothing in the static type of an erased position says which.
 *
 * Counts are non-atomic, and plain RC is complete because a cycle cannot be
 * constructed. Immutability used to be the whole of that argument. The cells
 * at the bottom of this file weaken it: a cell's slot can be overwritten, and
 * a cell reachable from its own slot would be a cycle nothing here can free.
 * The conclusion still holds, on a narrower footing -- a cell is a
 * compiler-private primitive. It has no Dawn spelling, it appears in no
 * user-visible type, and the checker keeps it inside the handler installation
 * that made it (docs/handler-state-design.md). So no value a program can
 * build ever holds a cell, and a slot only ever holds a value. Single-threaded
 * programs are what buys the non-atomic half. */
typedef struct {
  int32_t rc;
  int32_t kind;
} dawn_hdr;

enum {
  DAWN_K_ADT = 1,
  DAWN_K_CLO,
  DAWN_K_ARRAY,
  DAWN_K_ARRAY_BUF,
  DAWN_K_BOX,
  DAWN_K_BYTES,
  DAWN_K_STR,
  /* One activation of a control handler (see "one-shot resumption" in
   * dawn_rt.c). It is in the ledger because the continuation a control arm
   * receives is an ordinary Dawn function value that captures it, so the
   * activation dies when the last continuation over it does -- and the frames
   * it is holding suspended die with it. Native only: nothing on wasm32-wasi
   * ever allocates one. */
  DAWN_K_CTL
};

/* Never freed, and dup/drop return immediately on it. Static dictionaries are
 * out of RC by construction (the pass skips them -- CFun.dicts is its own
 * field), so nothing wears this yet; it is here because interned constants
 * will, and because one comparison is cheaper than a rule about who may be
 * passed to drop. */
#define DAWN_IMMORTAL INT32_MAX

/* A field or capture mask: bit i is set when slot i holds a heap pointer that
 * `drop` must recurse into. `wide` is used when the slot count exceeds 64,
 * pointing at a static array the emitter writes next to the allocation. */
typedef union {
  uint64_t narrow;
  const uint64_t *wide;
} dawn_mask;

/* A counted UTF-8 string: header, byte length, and the bytes. Heap strings
 * are one block -- `p` points at the trailing `data`. A literal is a static
 * the emitter (or `dawn_str_lit`) writes with an immortal header and `p`
 * aimed at the C string literal, so literals cost no copy and no count
 * traffic. Not NUL-terminated: `len` is authoritative and embedded NULs
 * survive.
 *
 * This was a two-word value (`{p, len}`, buffer leaked by contract) until the
 * strings-join-the-ledger change: by count strings are 0.1% of allocations
 * (perceus-design.md 1), but the compiler concatenates by the hundred
 * megabyte, and the leak was what kept LeakSanitizer off the corpus. Slices
 * copy now -- `cursor_slice` hands out token-sized strings, and a shared
 * buffer would need a second word of owner to find the header from a
 * mid-buffer pointer. */
typedef struct {
  dawn_hdr h;
  int64_t len; /* bytes, not code points */
  const char *p; /* heap: the bytes right after this struct; literal: .rodata */
} dawn_str;

/* A borrowed literal with automatic storage: fine to read, print or panic
 * with inside the enclosing block, NOT fine to store or hand to anything
 * that keeps it. Emitted code never uses this -- the emitter writes named
 * statics for `CStr` -- but the runtime's own messages do. */
#define dawn_str_lit(s, n) \
  (&(dawn_str){{DAWN_IMMORTAL, DAWN_K_STR}, (int64_t)(n), (s)})

/* The same thing with the length taken from the literal instead of written
 * next to it. A `dawn_str` is not NUL-terminated and `len` is authoritative,
 * so a length one short does not fail: it silently truncates the message, and
 * the only reader is a human looking at a panic. Seven of the runtime's
 * twenty-six messages were off by one that way -- among them "Array index out
 * of bounds" printing as "Array index out of bound" -- which is the whole
 * argument for not letting a human count bytes. Only for string literals:
 * `sizeof` on a `const char *` is the pointer's size. */
#define DAWN_LIT(s) dawn_str_lit((s), sizeof(s) - 1)

extern dawn_str dawn_str_empty_obj;
#define dawn_str_empty (&dawn_str_empty_obj)

/* A fresh heap string of `len` bytes, rc 1, `p` aimed at the bytes right
 * after the struct; the caller fills them via `dawn_str_data`. The one
 * constructor every string-producing primitive below funnels through. */
dawn_str *dawn_str_new(int64_t len);
dawn_str *dawn_str_copy(const char *p, int64_t n);
#define dawn_str_data(s) ((char *)((s) + 1))

/* One erased slot. Dawn boxes at type-variable positions and keeps concrete
 * positions native (llvm-backend-research.md 5.3); this union is what a
 * boxed slot looks like, and what an ADT field is stored in. One word since
 * strings became references -- the inline `dawn_str` was what held it at
 * two. Uniform for now -- tagged pointers for small ints are a later
 * optimisation. */
typedef union dawn_slot {
  int64_t i;
  double f;
  bool b;
  dawn_unit u;
  void *p;
} dawn_slot;

/* Dawn's `Bytes`: a byte array behind a pointer. Text is `dawn_str`; this is
 * what `bytes_utf8` produces and `std/bytes` walks. Separate because the two
 * are separate Dawn types, and conflating them here would let one be passed
 * where the other belongs without the C compiler saying so. `p` is owned and
 * freed with the struct: every constructor allocates it fresh. */
typedef struct {
  dawn_hdr h;
  const unsigned char *p;
  int64_t len;
} dawn_bytes;

/* Every ADT value, tuple included. `tag` is the constructor index, which is
 * exactly what CIsCtor tests -- the JVM backend uses class identity instead,
 * and that difference is confined to the two emitters. */
typedef struct {
  dawn_hdr h;
  int32_t tag;
  int32_t nfields;
  dawn_mask ptrmask;
  dawn_slot fields[];
} dawn_adt;

dawn_adt *dawn_adt_new(int32_t tag, int32_t nfields, uint64_t mask);
dawn_adt *dawn_adt_new_wide(int32_t tag, int32_t nfields, const uint64_t *mask);

/* ---- the field-less constructors, shared ----
 *
 * A constructor with no fields has nothing in it: `tag`, an `nfields` of 0
 * and an all-clear mask, and the C representation records no type, so two
 * such values with the same tag are byte for byte the same object. They are
 * not rare -- an allocation census of nmain compiling itself put 27.0% of all
 * ADT allocations at nfields 0 (`None`, `Nil`, every enum constant), and a
 * red-black tree benchmark at 52.4%. Each one was a 24-byte malloc plus a
 * full count-and-free life.
 *
 * So there is one static object per tag instead, immortal like a string
 * literal: constructing is taking an address, dup and drop return on the
 * immortal guard they already had, and nothing is ever freed.
 *
 * Why this is not observable. `==` on an ADT is structural, never identity,
 * so sharing cannot be seen from Dawn. Sharing *across types* -- `Nil` and a
 * `None` that happen to land on the same tag -- cannot be seen either: the
 * two are never comparable, and the bytes were already identical. The one
 * property that does move is `dawn_is_unique`, which now answers false where
 * it used to answer true -- and its only two callers are `array_with` and
 * `array_steal` asking about a `dawn_array` and its buffer, neither of which
 * a field-less ADT can be. So the answer that moved is one nobody asks.
 *
 * The table is bounded because the alternative is a per-tag symbol from the
 * emitter, and the bound buys nothing to be careful about: a tag outside it
 * falls back to a fresh allocation, which is exactly what every tag did
 * before. 256 is comfortably past the widest constructor list in the tree
 * (TokKind, 79). */
#define DAWN_ADT0_TAGS 256

/* The same layout as `dawn_adt` minus the flexible array member, which C
 * forbids as an array element. `dawn_adt0` casts across, and the static
 * assertions in dawn_rt.c hold the two shapes together. */
typedef struct {
  dawn_hdr h;
  int32_t tag;
  int32_t nfields;
  dawn_mask ptrmask;
} dawn_adt0_cell;

extern dawn_adt0_cell dawn_adt0_table[DAWN_ADT0_TAGS];

/* Counted for the same reason `array_with` counts its two paths: the win is
 * an absence, and an absence needs a number. Printed on the DAWN_RC_STATS
 * line. */
extern uint64_t dawn_adt0_hits;
extern uint64_t dawn_adt0_missed;

/* Every field-less construction the emitter writes. Inline and with the tag
 * a literal at every call site, so the bound test folds away and what is
 * left is the address of a static. */
static inline dawn_adt *dawn_adt0(int32_t tag) {
  if (tag >= 0 && tag < DAWN_ADT0_TAGS) {
    dawn_adt0_hits++;
    return (dawn_adt *)&dawn_adt0_table[tag];
  }
  dawn_adt0_missed++;
  return dawn_adt_new(tag, 0, 0);
}

/* The prelude ADTs the runtime itself has to build: `parse_float` and
 * `io_getenv` return an Option, `catch_fault` a Result. A constructor's tag is
 * its index in the declaration order, and these four numbers are the one place
 * that order is written down outside the compiler -- emitc's test "the C
 * runtime's constructor tags are the prelude's" is the joint that keeps them
 * honest. A field at a type-variable position is boxed, here as on the JVM,
 * so each of these takes a slot pointer. */
#define DAWN_TAG_SOME 0
#define DAWN_TAG_NONE 1
#define DAWN_TAG_OK 0
#define DAWN_TAG_ERR 1

/* `ForeignError`, the third prelude type, is a record: one constructor, so
 * one tag, and three fields in declaration order (kind, message, cause). The
 * `_e` barriers build it, so the order is written down here for the same
 * reason the four tags above are. */
#define DAWN_TAG_FOREIGN_ERROR 0

dawn_adt *dawn_some(void *boxed);
dawn_adt *dawn_none(void);

/* `Array[T]` -- the one collection primitive a backend owes the language
 * (native-backend-plan D1). std's List, Map and Set are all built on it, so
 * nothing collection-shaped compiles natively until this does.
 *
 * The contract has two halves (scripts/array-contract/README.md):
 *
 *   1. VALUE SEMANTICS. Every operation returns a new array and none is
 *      observably destructive. Two pushes onto the same version must each see
 *      their own element.
 *   2. `array_push` EXTENDS IN PLACE WHEN IT IS ALONE. Deliberately not
 *      observable from Dawn -- if it were, the semantics would not be pure --
 *      so it is measured with a clock instead: accumulation is O(n) with it
 *      and O(n^2) without, which at the contract's sizes is 10ms against a
 *      minute.
 *
 * A `dawn_array` is a length plus a shared buffer, and the buffer carries the
 * high-water mark of how many slots have ever been handed out. A push may
 * write slot `len` in place exactly when `len == buf->high`: that slot has
 * never belonged to any version, so no one can be reading it. Otherwise it
 * copies. This is the same rule the JVM backend enforces with a CAS on the
 * frontier slot; single-threaded C needs no atomic to state it.
 *
 * `array_with` copies unless it is alone: slot `i < len` has already been
 * handed to this version and maybe to others, and no watermark can say who
 * still reads it -- but the reference counts can (perceus-design.md 6). With
 * the array *and* its buffer both at `rc == 1` and the caller's reference
 * consumed, no one is left who could observe the write, and the copy becomes
 * an in-place store. Under `--rc=leak` counts only ever grow, so the test is
 * skipped and a leak-mode run doubles as the all-copies baseline. */
/* Elements are erased, so an Array holds boxed slots by pointer -- the same
 * shape the JVM backend gets from an Object[]. `array_get` therefore hands
 * back what `CUnbox` expects to dereference, and `array_push` takes what
 * `CBox` just produced. */
typedef struct {
  dawn_hdr h;
  void **data;
  int32_t cap;
  int32_t high; /* slots ever handed out; only push may raise it */
} dawn_array_buf;

/* Counted separately from its buffer, because that is exactly the structure
 * sharing a persistent vector is made of: several versions, one buffer. The
 * buffer's count is how many versions point at it. */
typedef struct {
  dawn_hdr h;
  dawn_array_buf *buf;
  int32_t len;
} dawn_array;

dawn_array *dawn_array_new(void);
int64_t dawn_array_len(const dawn_array *a);
void *dawn_array_get(const dawn_array *a, int64_t i);
dawn_array *dawn_array_push(dawn_array *a, void *x);
/* Consumes `a` and `x`: push for accumulation loops, where the superseded
 * header and the element reference are the loop's to give up. */
dawn_array *dawn_array_push_own(dawn_array *a, void *x);
/* Consumes `a` and `x` -- see the calling convention note below. */
dawn_array *dawn_array_with(dawn_array *a, int64_t i, void *x);
/* Borrows `a`, answers an owned reference to slot `i`. Alone (array and
 * buffer both unique) the slot's own reference is transferred out and the
 * slot left NULL, so the caller MUST overwrite slot `i` -- or drop the whole
 * array -- before anything reads it again; shared, it is get+dup and the
 * slot keeps its reference. For the rebuild shape `steal slot i, recurse,
 * write slot i back`, where a plain get would pin an extra count on the
 * child for the whole recursion and foreclose in-place reuse below it. */
void *dawn_array_steal(dawn_array *a, int64_t i);
/* In-place stores against copies (and transfers against dups), for the
 * reuse analysis's gate. Counted unconditionally (two increments against an
 * allocation and a loop); DAWN_RC_STATS=1 prints all four on exit. */
extern uint64_t dawn_array_with_inplace;
extern uint64_t dawn_array_with_copied;
extern uint64_t dawn_array_steal_taken;
extern uint64_t dawn_array_steal_dup;

/* The one bit-twiddle std/hamt needs that C does not portably spell. */
int64_t dawn_popcount(int64_t n);

/* A closure: a code pointer plus the captured environment. The JVM backend
 * gets this shape for free from invokedynamic and LambdaMetafactory; here it
 * is written out, which llvm-backend-research.md 3 called the biggest single
 * piece of native codegen. `fn` always points at the generated adapter, so
 * every call site is one indirect call regardless of capture count. */
typedef struct {
  dawn_hdr h;
  void *fn;
  int32_t ncap;
  int32_t _pad;
  dawn_mask capmask;
  dawn_slot caps[];
} dawn_clo;

dawn_clo *dawn_clo_new(void *fn, int32_t ncap, uint64_t mask);
dawn_clo *dawn_clo_new_wide(void *fn, int32_t ncap, const uint64_t *mask);

/* A trait dictionary: a flat table of function pointers in the trait's
 * declaration order. Dawn is dictionary-passing rather than monomorphising,
 * so this is the whole of generic dispatch -- llvm-backend-research.md 3
 * called it the cleanest part of native codegen, and it is. The JVM backend
 * uses an interface plus a singleton for the same thing.
 *
 * DAWN_DICT_MAX only bounds the static initialiser's shape; a dictionary is
 * never indexed beyond the slot count its trait declares. */
#define DAWN_DICT_MAX 16
typedef struct dawn_dict {
  int32_t nslots;
  void *slots[DAWN_DICT_MAX];
  /* A dictionary whose subject still mentions a type parameter is a function
   * of its arguments' dictionaries -- `Eq[Option[T]]` is not one relation but
   * a family, and which one is decided by the caller's `Eq[T]`. Those
   * arguments live here, and a slot body reads them back out of the
   * dictionary it is already handed. Zero for every dictionary the compiler
   * can build once, which is still nearly all of them. */
  int32_t nargs;
  struct dawn_dict *args[DAWN_DICT_MAX];
} dawn_dict;

/* Copy a static dictionary's slots and bind its arguments. Variadic in the
 * arguments so a call site emits one expression. */
dawn_dict *dawn_dict_new(const dawn_dict *tmpl, int32_t nargs, ...);

/* boxing: a type-variable slot holds a pointer to one of these. The header
 * has to sit at offset 0 like every other heap object's -- a header behind
 * the pointer would leave adts and boxes with theirs in different places, and
 * a uniform drop cannot have that. So `unbox_expr` reads `->val`, and the old
 * cast straight to `dawn_slot*` is gone. */
typedef struct {
  dawn_hdr h;
  dawn_slot val;
} dawn_box;

dawn_box *dawn_box_int(int64_t v);
dawn_box *dawn_box_float(double v);
dawn_box *dawn_box_bool(bool v);
dawn_box *dawn_box_unit(dawn_unit v);
/* No box for strings: a string IS a reference now, and an erased slot holds
 * the `dawn_str*` the way it holds any other pointer. */

/* The one boxed Unit. Unit has a single value, so a box around it carries no
 * information and every one of them may be the same object -- the JVM has
 * spelled it that way all along (`push_unit` loads a singleton and `box_ty`
 * adds nothing to it), and this is the native twin.
 *
 * Immortal, so dup and drop are no-ops on it and nothing ever frees it; boxes
 * are written once at construction and read-only afterwards, so sharing one
 * is unobservable. `dawn_box_unit` returns it too, for the boundaries that
 * reach a box through a call (an adapter boxing a Unit-returning body).
 *
 * It exists for the erased evidence slot. Every call through a function value
 * passes one, an unanswered slot is filled with a boxed unit, and a fresh box
 * there is a malloc and a free on the hot path -- measurably so, since a call
 * through a function value is what every higher-order std function does per
 * element. */
extern dawn_box dawn_unit_box_obj;
#define dawn_unit_box (&dawn_unit_box_obj)

/* Owning reads: the value comes out and the box is released. For the erased
 * call boundary only (dynamic call results and adapter parameters), where the
 * box is a wire format the RC pass never sees. A slot read the pass CAN see
 * (`CUnbox` of a field it borrowed) must not use these. */
int64_t dawn_unbox_int(void *b);
double dawn_unbox_float(void *b);
bool dawn_unbox_bool(void *b);
dawn_unit dawn_unbox_unit(void *b);

/* ---- reference counting -------------------------------------------------
 *
 * `dawn_drop` walks with an explicit stack rather than C recursion: a
 * persistent vector or a HAMT is deep, and dropping a hundred-thousand-node
 * structure would otherwise overflow. That is not a tuning choice; the
 * symptom without it is a segfault that only appears on large inputs. */
extern bool dawn_rc_leak; /* --rc=leak: drop becomes a no-op (plan 6 R3) */

void *dawn_dup(void *p);
void dawn_drop(void *p);
bool dawn_is_unique(const void *p);

/* ---- the small-object allocator -----------------------------------------
 *
 * Blocks come from size-class slabs the runtime carves out of one reserved
 * address range, not from malloc; the shape and the reasons are in dawn_rt.c
 * under the same heading. Two things about it leave the translation unit.
 *
 * The first is `dawn_free`. The runtime's own `free` calls are redirected by
 * a macro inside dawn_rt.c, which reaches nothing else, so a block the
 * runtime made and another translation unit releases has to be released
 * through this. There is one such caller (scripts/rc-contract/rc_test.c),
 * and a grep guard in scripts/rc-contract/run.sh keeps the count at one.
 *
 * The second is `DAWN_SLAB_ACTIVE`, because three builds do not get the slab
 * and one of them has to be able to say so:
 *
 *   * AddressSanitizer and LeakSanitizer. LSan finds leaks by walking
 *     malloc's own book of live blocks; objects carved out of our own
 *     mapping are not in that book, so every leak assertion in spike-native
 *     and rc-contract would pass without being able to fail. Measured, not
 *     supposed: a binary run with DAWN_RC_LEAK=1, which leaks every object
 *     on purpose, reports 5185 leaked bytes and exits 1 on a plain build and
 *     prints nothing and exits 0 on a slab build. Use-after-free detection
 *     goes the same way, a freed block staying addressable on a free list.
 *     Keeping malloc under the sanitizers keeps both, at the price that the
 *     sanitized builds no longer cover the allocator; the allocator's own
 *     assertions and mutants live in scripts/rc-contract instead.
 *   * wasm32-wasi, which has no sys/mman.h, no madvise and no MAP_NORESERVE.
 *   * -DDAWN_NO_SLAB, which is how the allocator is measured against its own
 *     absence, and the escape hatch for a platform where MADV_DONTNEED does
 *     not actually return pages (macOS wants MADV_FREE).
 *
 * That price is paid back with -DDAWN_SLAB_FORCE, which takes the slab into
 * a sanitized build on purpose. It buys the other half: dawn_rt.c poisons
 * every free block by hand, so a use-after-free on a slab block is reported
 * the way malloc's is, offset zero included, and so is a double free. What
 * it cannot buy is leak detection, which is structural rather than a missing
 * call -- LSan has no way to be told about an object it did not allocate
 * (dawn_rt.c, "manual poisoning"). So the forced build is a leg of its own,
 * run with detect_leaks=0 by scripts/rc-contract/run.sh, and the three
 * bypassed sanitizer runs that carry the leak assertions are left exactly as
 * they were.
 *
 * The nesting below is not a style choice: GCC rejects the flat spelling
 * `defined(__has_feature) && __has_feature(address_sanitizer)` with "missing
 * binary operator before token", because it evaluates both sides.
 */
void dawn_free(void *p);

#if defined(__SANITIZE_ADDRESS__)
#define DAWN_ASAN 1
#elif defined(__has_feature)
#if __has_feature(address_sanitizer)
#define DAWN_ASAN 1
#endif
#endif
#ifndef DAWN_ASAN
#define DAWN_ASAN 0
#endif

#if defined(DAWN_NO_SLAB) || defined(__wasi__)
#define DAWN_SLAB_ACTIVE 0
#elif DAWN_ASAN && !defined(DAWN_SLAB_FORCE)
#define DAWN_SLAB_ACTIVE 0
#else
#define DAWN_SLAB_ACTIVE 1
#endif

/* The shape, out here because the bound is a claim about the program rather
 * than about the allocator's insides: at most DAWN_SLAB_KEEP empty slabs are
 * held per size class, over DAWN_SLAB_CLASSES classes, at 64KiB each, so no
 * more than 32MiB ever sits idle whatever the program does. Requests over
 * DAWN_SLAB_MAX are malloc's. scripts/rc-contract reads these. */
#define DAWN_SLAB_GRAIN 16u /* size-class step, and the block alignment */
#define DAWN_SLAB_MAX 2048u /* a bigger request goes to malloc */
#define DAWN_SLAB_CLASSES (DAWN_SLAB_MAX / DAWN_SLAB_GRAIN + 1u)
#define DAWN_SLAB_KEEP 4u

/* Read-only observation ports, for the contract test. Both answer as if the
 * allocator were absent when it is: `dawn_slab_owns` is false of everything
 * and the counters stay zero, so a caller that cannot tell the builds apart
 * reads a bypassed build as one that never allocated rather than as one that
 * passed. `live` counts slabs holding pages, `cached` the empty ones held
 * for reuse, `retired` the slabs whose pages went back to the kernel. */
bool dawn_slab_owns(const void *p);
void dawn_slab_stats(uint64_t *live, uint64_t *cached, uint64_t *retired);
#ifdef DAWN_RC_CONTRACT
/* Test-only logical observation. mincore cannot distinguish a 32KiB tranche
 * from an eager 64KiB layout on a host whose page is itself 64KiB. */
size_t dawn_slab_materialized_bytes(const void *p);
#endif

/* ---- unwind cleanup (#193 ARC-05) ---------------------------------------
 *
 * A raise travels by forced unwind (dawn_rt.c, "landing at a handler"), and
 * this is the emitter's half of that contract. A function's owned slots live
 * in one `void *` array -- `dawn_own[0]` holds the count, the slots follow,
 * NULL-initialized -- and the array carries the one cleanup the unwinder
 * runs when a raise discards the frame. One cleanup variable per function,
 * not one per slot, and that is a measured decision, not a style: a cleanup
 * attribute on every owned local made every call site a distinct EH region
 * dragging its own chain of landing pads, and the -O2 back end (sched2,
 * postreload) went superlinear in them -- the selfhost driver's compile went
 * 16s -> 354s. One cleanup spanning the whole frame collapses that to one
 * region shared by every call.
 *
 * The discipline that makes the ordinary path correct is unchanged: every
 * release the RC pass placed -- a drop or a transfer -- clears its slot, so
 * the cleanup finds NULL everywhere on a normal exit and nothing is ever
 * released twice. `dawn_take` is the transfer: it hands the reference out
 * and clears the slot in the same expression, which is what keeps a slot
 * from being cleaned while its value already belongs to a callee that is
 * unwinding. Slots are `void *` and every read casts to the slot's C type;
 * all object pointers share a representation here, and every consumer
 * compiles with -fno-strict-aliasing (the backend's standing flags).
 *
 * On wasm32-wasi there is no unwinder to run the cleanup attribute when a
 * raise discards frames, so the frames announce themselves instead: every
 * own array is also registered on a shadow stack the runtime keeps
 * (dawn_rt.c, "landing at a handler on wasm32-wasi"), a raise walks that
 * stack and runs the drops itself, and the cleanup attribute -- which still
 * fires on every ordinary scope exit -- unregisters the frame on the way
 * out. DAWN_OWN_FRAME is the one spelling the emitter writes for both
 * arrangements; on native it expands to exactly the declaration it always
 * emitted. */
#ifdef __wasi__
void dawn_wasi_own_push(void *frame);
void dawn_wasi_own_pop(void *frame);
#endif

static inline void dawn_own_drop(void *frame) {
  void **s = (void **)frame;
  int64_t n = (int64_t)(intptr_t)s[0];
  for (int64_t i = 1; i <= n; i++) {
    if (s[i] != NULL) dawn_drop(s[i]);
  }
#ifdef __wasi__
  dawn_wasi_own_pop(frame);
#endif
}

static inline void *dawn_take(void **slot) {
  void *v = *slot;
  *slot = NULL;
  return v;
}

#define DAWN_CLEANUP(f) __attribute__((cleanup(f)))

#ifdef __wasi__
#define DAWN_OWN_FRAME(n) \
  DAWN_CLEANUP(dawn_own_drop) void *dawn_own[(n) + 1] = { (void *)(intptr_t)(n) }; \
  dawn_wasi_own_push(dawn_own)
#else
#define DAWN_OWN_FRAME(n) \
  DAWN_CLEANUP(dawn_own_drop) void *dawn_own[(n) + 1] = { (void *)(intptr_t)(n) }
#endif

/* Take a freshly built object graph out of the ledger for good: every node
 * reachable from `p` gets an immortal header, so dup and drop return
 * immediately on all of them and `dawn_is_unique` is false everywhere in it.
 *
 * The one caller is a comptime constant. The JVM backend puts a folded
 * structured value in a `static final` field that `<clinit>` builds once; C
 * has no <clinit>, so the emitter writes a builder function with a static
 * pointer instead, and this is what makes the result behave like that field:
 * built once, shared by every reference, never released.
 *
 * The *whole graph*, not just the root. `dawn_array_with` is the one place
 * that asks `dawn_is_unique` and then writes in place, and a root-only mark
 * would leave every node under the root at rc 1 -- so whether a constant can
 * be overwritten through its own buffer would rest on every call site duping
 * first, rather than on anything true of the object. Marking the graph makes
 * "a constant is not unique" a fact instead of a convention.
 *
 * Today the convention also holds: measured 2026-08-04, the only route from
 * Dawn to `dawn_array_with` is `std/pvec.push_tail`, the RC pass dups the
 * array before the call, and a constant appended to therefore copies under
 * both markings. So this is a hedge, and the check that can tell the two
 * apart is scripts/rc-contract/rc_test.c's `test_immortal_graph`, which calls
 * `dawn_array_with` itself -- no corpus program sees the difference.
 *
 * Acyclic by construction (a folded value is a tree of literals), and an
 * already-immortal node stops the walk -- string literals are static and
 * carry no children. */
void dawn_immortal(void *p);

/* THE CALLING CONVENTION FOR EVERY PRIMITIVE BELOW: arguments are BORROWED,
 * and anything a primitive keeps it dups for itself. So `array_push` counts
 * both the element it stores and the buffer it goes on sharing, and the
 * caller still owes a drop on the array it passed in and on the element.
 *
 * Written down because the alternative -- consuming arguments -- reads the
 * same at every call site and differs only in who leaks. The array contract
 * found this the hard way: sharing a buffer between versions without counting
 * it means the first version dropped frees a buffer the others still hold.
 *
 * THE EXCEPTIONS CONSUME AND SAY SO: `dawn_array_with` consumes its array
 * and its element (perceus-design.md 6, mirrored by `types.intr_owned_args`)
 * -- a borrowed array keeps the caller's count on it and `rc == 1` could
 * never mean "no one can observe a write". `dawn_array_push_own` consumes for
 * accumulation loops, and the `dawn_unbox_*` family consumes the box it
 * reads. The compiler's rc pass emits the transfer or the dup at each call
 * site -- hand-written C (the contract harnesses) must dup anything it wants
 * to keep before calling a consumer. */

void dawn_rt_init(int argc, char **argv);

/* ---- the program's stack ------------------------------------------------
 *
 * `dawn_rt_main` is what the emitted `main` calls, and it is the *only* thing
 * it calls: it initialises the runtime, runs `entry` on a thread whose stack
 * is DAWN_STACK_BYTES rather than whatever the OS handed the main thread, and
 * returns the process status.
 *
 * The size is the JVM backend's `-Xss512m` (bin/dawn, and `spawn_java` in
 * main.dawn), deliberately the same number for the same reason: general tail
 * calls are not implemented and a big stack is the substitute
 * (docs/native-backend-plan.md 1). It is address space, not memory -- the
 * pages are touched only as the stack actually grows.
 *
 * Until this existed native ran on the OS default 8MB and deep input died
 * with SIGSEGV and not one word of output -- the guard page, at a depth the
 * JVM backend clears by a factor of 64. Nine such crashes are on the record
 * for one afternoon's synthetic inputs (docs/audit/ceval-trampoline-verdict.md
 * 5). The runtime is where it belongs rather than the emitted main, because
 * `nmain`/`cdriver` are emitted programs too: one definition, and the
 * compiler's own native build gets the same stack a user program does.
 *
 * The thread is the mechanism, not a concurrency model. `main` does nothing
 * but join, so exactly one thread ever runs Dawn code and the non-atomic
 * reference counts and the single handler chain stay correct.
 *
 * Requires -pthread (glibc merged it into libc in 2.34, but the flag is the
 * portable spelling and also sets _REENTRANT).
 *
 * There is deliberately no SIGSEGV handler printing "stack overflow" next to
 * this, which would be the other half of parity with StackOverflowError. It
 * was prototyped and measured on 2026-07-31, and the price is wrong for one
 * line of text: `sigaltstack`/`SA_ONSTACK` are not visible under this file's
 * `_POSIX_C_SOURCE 200809L`, so the whole translation unit's symbol
 * visibility would have to move to `_XOPEN_SOURCE 700`; `SIGSTKSZ` stopped
 * being a compile-time constant in glibc 2.34, so the alternate stack has to
 * be a made-up size; and -- measured -- installing the handler *silences*
 * AddressSanitizer's own stack-overflow report, which is strictly better than
 * the one line, so it would need a `__SANITIZE_ADDRESS__` opt-out and the
 * sanitized build would stop being the shipped one. Detection is also only a
 * heuristic (is the faulting address near the stack?), and a wild pointer
 * mislabelled "stack overflow" is worse than no message. The stack itself
 * moved the threshold by 64x, which was the part worth having. */
#define DAWN_STACK_BYTES ((size_t)512 << 20)

int dawn_rt_main(int argc, char **argv, void (*entry)(void));

/* ---- the runtime-intrinsic contract ------------------------------------
 *
 * Everything from here to `dawn_panic` implements a primitive the intrinsic
 * table says a runtime module owns, and each is named `dawn_` plus the
 * intrinsic's own name. That is not a convention the emitter can be talked
 * out of: it emits the call from the table, so a primitive whose C function
 * is missing or misspelled fails to link, and one that is added here needs no
 * emitter change at all (docs/runtime-intrinsics-design.md 4). */

/* io */
dawn_unit dawn_io_print(dawn_str *s);
dawn_unit dawn_io_println(dawn_str *s);
dawn_unit dawn_io_eprint(dawn_str *s);
dawn_unit dawn_io_eprintln(dawn_str *s);
dawn_adt *dawn_io_read_line(void); /* Option[String]; None at EOF */
/* One type-erased root per process / wasm instance. std/reactor stores only
 * its one private concrete Root type here; application state is captured by
 * that Root's fixed-signature closure. `get` returns an owned reference;
 * `set` borrows its argument and takes its own reference before releasing the
 * old root. */
bool dawn_reactor_state_has(void);
void *dawn_reactor_state_get(void);
dawn_unit dawn_reactor_state_set(void *state);
bool dawn_io_is_dir(dawn_str *path); /* false for absent or invalid paths */
bool dawn_io_exists(dawn_str *path); /* false for absent or invalid paths */
dawn_unit dawn_io_mkdirs(dawn_str *path); /* panics on failure */
dawn_unit dawn_io_exit(int64_t code);    /* returns a Unit it never delivers */
dawn_str *dawn_io_read_file(dawn_str *path);      /* panics on failure */
dawn_unit dawn_io_write_file(dawn_str *path, dawn_str *content);
dawn_array *dawn_io_list_names(dawn_str *path);  /* boxed dawn_str elements */
dawn_str *dawn_io_cwd(void);
dawn_adt *dawn_io_getenv(dawn_str *name); /* Option[String]; None for invalid names */
dawn_bytes *dawn_io_read_bytes(dawn_str *path);
dawn_unit dawn_io_write_bytes(dawn_str *path, const dawn_bytes *content);
bool dawn_io_delete(dawn_str *path); /* false only for ENOENT; other failures fault */
dawn_unit dawn_io_rename(dawn_str *src, dawn_str *dst); /* rename(2): atomic or panic */
dawn_str *dawn_io_temp_dir(dawn_str *parent, dawn_str *prefix); /* "" parent = $TMPDIR */
dawn_str *dawn_io_temp_file(dawn_str *parent, dawn_str *prefix); /* mkstemp: created, mode 0600 */
dawn_unit dawn_io_copy_permissions(dawn_str *src, dawn_str *dst); /* lstat + chmod, no follow */
bool dawn_io_is_symlink(dawn_str *path); /* false for absent or invalid paths */
dawn_bytes *dawn_io_read_stdin(int64_t n); /* short only at end of input */
/* At least one byte readable now; end of input is not readiness. Both stdin
 * readers above go straight to read(2) so this can ask the kernel and be
 * believed -- see the note above dawn_io_read_line. */
bool dawn_io_stdin_ready(int64_t timeout_ms);
/* argv holds boxed dawn_str and is CONSUMED (an emitter crossing temp, like
 * `from_code_points`); an empty path inherits this process's stream */
int64_t dawn_io_run(dawn_array *argv, dawn_str *out_path, dawn_str *err_path);
dawn_array *dawn_args(void);

/* The GPU runtime module behind std/gpu's `with_gpu_real`: the CUDA driver
 * through a dlopen'd libcuda.so.1 (see the section in dawn_rt.c). Every one
 * answers Result[_, ForeignError] itself and never faults; a driver refusal
 * has kind "cuda." ++ its CUresult name, a missing driver "gpu.no_driver",
 * and on wasm every one is "gpu.unsupported_backend". Arguments are borrowed
 * like every other intrinsic's; the Result and what it holds are the
 * caller's. Buffers are raw device pointers, a module is the CUmodule
 * handle load_module answered, `data` holds boxed doubles and `args` boxed
 * device pointers. */
dawn_adt *dawn_gpu_load_module_host(const dawn_bytes *cubin);   /* Result[Int, _] */
dawn_adt *dawn_gpu_alloc_host(int64_t nbytes);                   /* Result[Int, _] */
dawn_adt *dawn_gpu_upload_host(int64_t devptr, const dawn_array *data);
dawn_adt *dawn_gpu_download_host(int64_t devptr, int64_t len);   /* Result[Array[Float], _] */
dawn_adt *dawn_gpu_launch_host(int64_t module, dawn_str *kernel, int64_t grid,
                               const dawn_array *args);
dawn_adt *dawn_gpu_free_host(int64_t devptr);
dawn_adt *dawn_gpu_sync_host(void);
dawn_unit dawn_gpu_close_host(void); /* releases the context and the library; idempotent */

/* `f` returns an erased slot, so one cast serves whatever `T` is -- the same
 * reason the JVM hands these an `Fn0` whose `apply` returns `Object`.
 *
 * The JVM catches an exception; native has no exceptions, so these catch a
 * raise, which is the one failure mechanism there is.
 *
 * The `Err` payload is a `ForeignError`
 * (docs/audit/error-model-design.md A). What this backend puts in each field
 * is the native half of a contract the language says is backend-specific by
 * design:
 *
 *   kind     the runtime's own name for the failure class, which here is the
 *            failure kind itself -- "panic" or "fault", the split
 *            `dawn_raise` already routes by. Not an errno symbol and not a
 *            signal name: `dawn_fault` is handed a message and nothing else,
 *            and a signal is not caught at all. Both would be a wider change
 *            at every raise site, and `kind` is documented as the backend's
 *            own name precisely so it can get more specific later without
 *            breaking a promise.
 *   message  what was raised.
 *   cause    always None. Nothing here chains one failure onto another.
 *
 * `kind` is a backend's own name, so a program that *prints* one prints
 * different text on the two backends; everything that branches on Ok/Err, or
 * reads `message`, agrees.
 *
 * `ev` is the evidence pack `f` is applied with, and it is the second
 * parameter rather than a NULL for the reason `dawn_bracket` takes one: the
 * barriers bind an effect parameter over the protected closure
 * (`catch_fault[T, !e]`), so their ABI row is worth one evidence slot and the
 * call site fills it. It is borrowed like every other intrinsic argument, so
 * the closure call takes a reference of its own. */
dawn_adt *dawn_catch_fault(dawn_clo *f, void *ev);
dawn_adt *dawn_catch_panic(dawn_clo *f, void *ev);

/* The third of the family, and the one that stops nothing. `use` runs on the
 * already-acquired `resource` under a handler that takes both kinds; whichever
 * way `use` leaves, `release` runs exactly once, and a failure carries on to
 * whatever was going to stop it with its kind and message untouched. So
 * `catch_fault` still refuses a panic that crossed a bracket -- the saved kind
 * is re-raised, not re-derived.
 *
 * The parameter order is the intrinsic's declared order: resource, release,
 * use. The resource is a value and not an acquire thunk because Dawn has no
 * asynchronous failures -- nothing runs between the caller evaluating it and
 * the handler below going up. Everything crosses erased, `use`'s answer
 * included, for the same reason the two above take an `Fn0` whose apply
 * returns Object.
 *
 * A taken unwind path leaks what the discarded C frames held, exactly as a
 * taken barrier does; see the note above and scripts/spike-native's
 * `.leaks-on-catch` markers.
 *
 * `ev` is the fourth parameter because `bracket` is effect-polymorphic:
 * `release` and `use` share one row, so the primitive's own row is worth one
 * evidence slot at the call site (types.nev) and this is that slot. The two
 * barriers above take none -- their thunks are declared `fn() -> T !io`, and
 * `!io` is an answer rather than a question. `ev` is borrowed like every other
 * intrinsic argument; each closure call takes a reference of its own. */
void *dawn_bracket(void *resource, dawn_clo *release, dawn_clo *use, void *ev);

/* ---- one-shot resumption (docs/oneshot-design.md 11.10) ----------------
 *
 * The two primitives the C emitter writes for a `with handle` with a control
 * arm. Everything crossing here is erased (`types.erased_ctl_ty`), so these
 * signatures do not vary with the operation: lowering boxes the payloads.
 *
 * `dawn_ctl_enter(hid, rest, evs)` is the block's tail. `hid` is the
 * installation's identity, `rest` a `fn() -> A` function value (one evidence
 * slot), `evs` the pack it is applied with. The answer is the block's, owned.
 *
 * `dawn_ctl_yield(hid, arm, env, nargs, args)` is what the wrapper closure in
 * the evidence record calls when the operation is raised. `arm` is the
 * author's arm, `env` the pack the *installation* built for it, and `args`
 * the operation's arguments, borrowed. It answers the value the continuation
 * was resumed with, owned; it does not return at all if the continuation is
 * dropped.
 *
 * `dawn_discard(k, ev)` abandons the computation `k` would have resumed,
 * running every bracket release inside it innermost-first
 * (docs/oneshot-design.md 11.12). It is the one of the three that is language
 * surface: `discard` is a builtin the io runtime module owns, so the name here
 * carries no `ctl` prefix. It consumes the one-shot ticket, so
 * resume-after-discard and discard-twice are the same panic family as
 * resume-twice. `ev` is the evidence slot its signature buys by binding `!e`
 * over the continuation (`discard[T, U, !e]`, the same reason `dawn_bracket`
 * takes one); it is never read, because a continuation carries the pack its
 * remainder was installed with, so the parameter exists to make the call
 * site's arity and the shim's agree.
 *
 * All three borrow like every other primitive here. */
void *dawn_ctl_enter(int64_t hid, void *rest, void *evs);
void *dawn_ctl_yield(int64_t hid, void *arm, void *env, int64_t nargs, void **args);
dawn_unit dawn_discard(void *k, void *ev);

/* Simple (1:1) Unicode case mapping: a code point in `lo..hi` maps to itself
 * plus `delta`, and one in no range maps to itself.
 *
 * Defined by the *generated program*, not by this runtime, because the table
 * belongs to the compiler (selfhost/src/embed/unicode_case.dawn) and the JVM backend
 * receives the same rows in dawn/rt/Strings. It lived here as a generated
 * header until 2026-07-28, which made it one mapping only while the JDK that
 * generated it was the JDK the JVM backend happened to be running -- Unicode
 * 15 and 16 differ by 18 code points, and nothing said so. `dawn __emitc`
 * always emits these symbols, so the runtime always links -- but a table
 * nothing reachable reads is emitted with a count of zero (reach.dawn), and
 * a zero count is a claim, not a set: no real table is empty, so the readers
 * (dawn_cp_in, dawn_case) panic on n == 0 rather than answer from rows that
 * are not there. */
typedef struct {
  int32_t lo;
  int32_t hi;
  int32_t delta;
} dawn_case_range;

extern const dawn_case_range dawn_upper_ranges[];
extern const int64_t dawn_upper_ranges_n;
extern const dawn_case_range dawn_lower_ranges[];
extern const int64_t dawn_lower_ranges_n;

/* Unicode classification, as the ranges each predicate holds at. Defined by
 * the generated program for the same reason as the case table above. */
typedef struct {
  int32_t lo;
  int32_t hi;
} dawn_cp_range;

extern const dawn_cp_range dawn_letter_ranges[];
extern const int64_t dawn_letter_ranges_n;
extern const dawn_cp_range dawn_digit_ranges[];
extern const int64_t dawn_digit_ranges_n;
extern const dawn_cp_range dawn_upper_class_ranges[];
extern const int64_t dawn_upper_class_ranges_n;
extern const dawn_cp_range dawn_lower_class_ranges[];
extern const int64_t dawn_lower_class_ranges_n;
extern const dawn_cp_range dawn_space_ranges[];
extern const int64_t dawn_space_ranges_n;

/* strings */
dawn_str *dawn_str_concat(dawn_str *a, dawn_str *b);
bool dawn_str_eq(dawn_str *a, dawn_str *b);
dawn_str *dawn_str_lower(dawn_str *s);
dawn_str *dawn_str_upper(dawn_str *s);
/* the one parse primitive left: fmt.atod's decimal-to-binary conversion on a
 * pre-validated, pre-trimmed string (std/fmt owns the accepted language) */
dawn_adt *dawn_parse_float(dawn_str *s);                  /* Option[Float] */
dawn_array *dawn_code_points(dawn_str *s);                /* boxed Int elements */
/* These two CONSUME their array: it is the emitter's list-to-Array crossing
 * temp (`to_host`), which no Core node owns, so the reader frees it. */
dawn_str *dawn_from_code_points(dawn_array *cps);
dawn_str *dawn_join(dawn_array *parts, dawn_str *sep);

/* Cursors. A position is a byte offset into the UTF-8 here and a UTF-16 index
 * on the JVM, and neither is observable: `Cursor` is opaque outside
 * std/cursor, so nothing can print one or do arithmetic on one. What is
 * observable -- the order, and what `slice` returns -- agrees.
 *
 * `cursor_slice` panics on a range that is out of bounds or lands inside a
 * character. The JVM's returns a sentinel and its emitter raises the panic;
 * that split is why this one is not in the intrinsic table. */
int64_t dawn_cursor_start(dawn_str *s);
int64_t dawn_cursor_end(dawn_str *s);
bool dawn_cursor_done(dawn_str *s, int64_t c);
int64_t dawn_cursor_char(dawn_str *s, int64_t c); /* -1 at the end */
int64_t dawn_cursor_next(dawn_str *s, int64_t c);
int64_t dawn_cursor_prev(dawn_str *s, int64_t c);
dawn_str *dawn_cursor_slice(dawn_str *s, int64_t from, int64_t to);

/* bytes. `concat` and `eq` are not intrinsics -- they are what `++` and `==`
 * at Bytes compile to, the way dawn_str_concat and dawn_str_eq are for text. */
dawn_bytes *dawn_bytes_concat(const dawn_bytes *a, const dawn_bytes *b);
bool dawn_bytes_eq(const dawn_bytes *a, const dawn_bytes *b);
dawn_bytes *dawn_bytes_utf8(dawn_str *s);
int64_t dawn_bytes_len(const dawn_bytes *b);
int64_t dawn_bytes_at(const dawn_bytes *b, int64_t i); /* 0..255, -1 out of range */
dawn_bytes *dawn_bytes_slice(const dawn_bytes *b, int64_t from, int64_t to);
/* The one way to make bytes that did not come from text. Elements are boxed
 * (the array is erased) and truncated to a byte. */
dawn_bytes *dawn_bytes_from_array(const dawn_array *a);
/* The two decodings the language promises, one function each rather than one
 * taking a charset name: the function name is the domain, both charsets read
 * every byte string, and so neither answers an Option. Malformed UTF-8 is
 * replaced rather than refused, as `new String(bytes, charset)` does. */
dawn_str *dawn_bytes_decode_utf8(const dawn_bytes *b);
dawn_str *dawn_bytes_decode_latin1(const dawn_bytes *b);
dawn_str *dawn_str_of_int(int64_t v);
dawn_str *dawn_str_of_bool(bool v);
/* `<N bytes>` -- the language renders a Bytes as its length, not its content.
 * The third member of the str_of_* family (Float renders in std/fmt). */
dawn_str *dawn_str_of_bytes(const dawn_bytes *b);
/* A String as it appears *inside* a rendered value: source-literal escaping
 * between double quotes. What the trait method `show` does at a String, so
 * that punctuation and content stay distinguishable. */
dawn_str *dawn_str_quote(dawn_str *s);

/* Unicode classification of one code point (the char_is_* intrinsics), out of
 * the tables above. Exact against the JVM backend everywhere, because both
 * read the same rows.
 *
 * These classified ASCII and panicked above U+007F until 2026-07-28, on the
 * grounds that a wrong answer would differ from the JVM silently while a panic
 * would not. That was the right call while the JVM's answer came from the
 * running JDK -- there was nothing to copy that would stay copied. */
bool dawn_char_is_letter(int64_t c);
bool dawn_char_is_digit(int64_t c);
bool dawn_char_is_alnum(int64_t c);
bool dawn_char_is_upper(int64_t c);
bool dawn_char_is_lower(int64_t c);
bool dawn_char_is_space(int64_t c);

/* The prelude Hash and Ord over one scalar: what a `[T: Hash]` or `[T: Ord]`
 * bound instantiated at that scalar ends up calling.
 *
 * Both are observable -- a program can print `hash(x)` or `cmp(a, b)` -- so
 * these are not free choices: spec 3.5 defines the hash leaves, and `cmp`
 * contracts code point order and only the sign (-1/0/1). Where an answer is
 * surprising, the surprise is documented at the definition rather than
 * smoothed over here. */
int64_t dawn_hash_int(int64_t v);
int64_t dawn_hash_bool(bool v);
int64_t dawn_hash_str(dawn_str *s);
int64_t dawn_hash_bytes(const dawn_bytes *b);
int64_t dawn_cmp_int(int64_t a, int64_t b);
int64_t dawn_cmp_str(dawn_str *a, dawn_str *b);

/* arithmetic whose C behaviour would be undefined where the JVM's is not.
 * The shifts are the third member of this family and are emitted inline --
 * masking the count to six bits is an expression, so it needs no call. */
int64_t dawn_idiv(int64_t a, int64_t b);
int64_t dawn_imod(int64_t a, int64_t b);
int64_t dawn_int_of_float(double v); /* Float -> Int, saturating like D2L */

/* One lookup in an evidence pack: the `ev_get` intrinsic, whose contract is
 * written at `types.ev_pack_adt` in the compiler.
 *
 * A call rather than emitted C because the walk has to ask what it is
 * standing on, and that question is this file's to answer: the JVM gets it
 * from `INSTANCEOF`, and here it is the `kind` byte every heap object carries
 * in its header. Core cannot spell either -- `CIsCtor` reads a tag off
 * whatever it is handed, which is undefined when that is a box or a null.
 *
 * Safe on all three things that end a walk: NULL, the immortal boxed Unit
 * that spells the empty pack, and any other erased value that is not a pack
 * node. The result is *borrowed* from inside the pack, like an ADT field
 * read; the emitter dups it, because a Core expression hands back an owned
 * value and `rc.dawn` does not wrap intrinsics. Falling off the end panics:
 * a missing key is a broken compiler invariant, not an answer. */
#define DAWN_TAG_EV_PACK 0 /* one constructor, so index 0 -- emitc pins it */
#define DAWN_EV_PACK_FIELDS 3 /* key, ev, outer */
#define DAWN_EV_PACK_MASK 6 /* fields 1 and 2 are pointers, the key is not */
void *dawn_ev_get(void *pack, int64_t key);

/* The other half of the pack contract: two packs joined, `front`'s entries
 * first (`types.ev_pack_adt`). One slot can be handed two rows -- `!e := !e1
 * !e2` -- and consing is only enough when there is one, so `front`'s chain is
 * walked and rebuilt onto `back`. `front`'s terminator is dropped rather than
 * copied, so the chain stays flat and `ev_get` is unchanged by any of it.
 *
 * A call for the same reason `ev_get` is: it has to recognise a node, and
 * that is this file's knowledge. It allocates, which `ev_get` does not, so
 * the counting rule is worth stating twice -- both arguments are borrowed and
 * the RESULT IS OWNED. The emitter does not dup it. */
void *dawn_ev_append(void *front, void *back);

/* ---- handler-local cells (docs/handler-state-design.md) -----------------
 *
 * One mutable slot, made where a handler is installed and read and written by
 * the shells the compiler wraps around that handler's arms. The four
 * `cell_*` intrinsics are the only things that reach it; no Dawn name spells
 * them and no user-visible type mentions a cell, which is what the note on
 * cycles at the top of this file leans on.
 *
 * The representation is a `dawn_adt` with one boxed field, not a kind of its
 * own, and the whole reason is that `dawn_dup` and `dawn_drop` then need no
 * new arm: their `DAWN_K_ADT` case walks `nfields` against `ptrmask`, and the
 * two constants below are exactly what that case reads. A new kind would have
 * been a second place to keep the release walk correct.
 *
 * Ownership is stated per function at the definitions in dawn_rt.c. In brief:
 * `new` and `set` take the value OWNED, `get` hands back a BORROWED reference
 * the emitter dups, `take` transfers the slot's own reference out and leaves
 * the slot empty. */
#define DAWN_TAG_CELL 0 /* one constructor, so index 0 -- emitc pins it */
#define DAWN_CELL_FIELDS 1
#define DAWN_CELL_MASK 1 /* the one field holds a reference */
void *dawn_cell_new(void *x);
void *dawn_cell_get(void *c);
void dawn_cell_set(void *c, void *x);
/* Empties the slot, so the caller MUST store into it -- or drop the cell --
 * before anything reads it again. `dawn_array_steal` carries the same
 * obligation for the same reason: a plain get would pin a second count on the
 * value for as long as the slot holds it, and that forecloses the in-place
 * reuse a collecting handler is written to get. */
void *dawn_cell_take(void *c);

/* Control. The two failure kinds, and the difference is which barrier stops
 * one: `catch_fault` takes a fault (the outside world said no) and lets a panic
 * past, `catch_panic` takes both. The JVM gets the same split from `Error` vs
 * `Exception`; here it is a flag on the handler. Everything in this file
 * raises a fault only where an io primitive failed -- a bad index or a bad
 * argument is the language's own failure and panics. */
void dawn_panic(dawn_str *msg);
void dawn_fault(dawn_str *msg);

#endif /* DAWN_RT_H */
