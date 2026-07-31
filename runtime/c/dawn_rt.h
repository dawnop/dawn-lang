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
 * Counts are non-atomic. Dawn is strict, immutable and has no mutable
 * aliasing, so a cycle cannot be constructed and plain RC is complete --
 * that, and single-threaded programs, is what buys both simplifications. */
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
  DAWN_K_STR
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

/* The prelude ADTs the runtime itself has to build: `parse_int` and
 * `bytes_decode` return an Option, `catch_fault` a Result. A constructor's tag is
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
/* In-place stores against copies, for the reuse analysis's gate. Counted
 * unconditionally (two increments against an allocation and a loop);
 * DAWN_RC_STATS=1 prints both on exit. */
extern uint64_t dawn_array_with_inplace;
extern uint64_t dawn_array_with_copied;

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
bool dawn_io_is_dir(dawn_str *path);
bool dawn_io_exists(dawn_str *path);
dawn_unit dawn_io_mkdirs(dawn_str *path); /* panics on failure */
dawn_unit dawn_io_exit(int64_t code);    /* returns a Unit it never delivers */
dawn_str *dawn_io_read_file(dawn_str *path);      /* panics on failure */
dawn_unit dawn_io_write_file(dawn_str *path, dawn_str *content);
dawn_array *dawn_io_list_names(dawn_str *path);  /* boxed dawn_str elements */
dawn_str *dawn_io_cwd(void);
dawn_adt *dawn_io_getenv(dawn_str *name); /* Option[String] */
dawn_bytes *dawn_io_read_bytes(dawn_str *path);
dawn_unit dawn_io_write_bytes(dawn_str *path, const dawn_bytes *content);
bool dawn_io_delete(dawn_str *path); /* false when there was nothing to delete */
dawn_unit dawn_io_rename(dawn_str *src, dawn_str *dst); /* rename(2): atomic or panic */
dawn_str *dawn_io_temp_dir(dawn_str *parent, dawn_str *prefix); /* "" parent = $TMPDIR */
bool dawn_io_is_symlink(dawn_str *path);
dawn_bytes *dawn_io_read_stdin(int64_t n); /* short only at end of input */
/* argv holds boxed dawn_str and is CONSUMED (an emitter crossing temp, like
 * `from_code_points`); an empty path inherits this process's stream */
int64_t dawn_io_run(dawn_array *argv, dawn_str *out_path, dawn_str *err_path);
dawn_array *dawn_args(void);

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
 * reads `message`, agrees. */
dawn_adt *dawn_catch_fault(dawn_clo *f);
dawn_adt *dawn_catch_panic(dawn_clo *f);

/* Simple (1:1) Unicode case mapping: a code point in `lo..hi` maps to itself
 * plus `delta`, and one in no range maps to itself.
 *
 * Defined by the *generated program*, not by this runtime, because the table
 * belongs to the compiler (selfhost/src/case_table.dawn) and the JVM backend
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
/* code-point indices, -1 when absent: the wrappers in std/str turn the
 * sentinel into None, and the index is observable, so it is not the byte
 * offset the search actually ran on. */
dawn_adt *dawn_parse_int(dawn_str *s);                    /* Option[Int] */
dawn_adt *dawn_parse_float(dawn_str *s);                  /* Option[Float] */
dawn_adt *dawn_parse_int_radix(dawn_str *s, int64_t radix);
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
/* Option[String]; None only for a charset this runtime cannot decode, which
 * is what the JVM's UnsupportedEncodingException arm means. Malformed input
 * is replaced rather than refused, as `new String(bytes, charset)` does. */
dawn_adt *dawn_bytes_decode(const dawn_bytes *b, dawn_str *charset);
dawn_str *dawn_str_of_int(int64_t v);
dawn_str *dawn_str_of_float(double v);
dawn_str *dawn_str_of_bool(bool v);
/* `<N bytes>` -- the language renders a Bytes as its length, not its content.
 * The fourth member of the str_of_* family, one per show scalar. */
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
 * these are not free choices. Each reproduces the JVM backend's answer bit
 * for bit; where that answer is surprising, the surprise is documented at the
 * definition rather than smoothed over here. */
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

/* Control. The two failure kinds, and the difference is which barrier stops
 * one: `catch_fault` takes a fault (the outside world said no) and lets a panic
 * past, `catch_panic` takes both. The JVM gets the same split from `Error` vs
 * `Exception`; here it is a flag on the handler. Everything in this file
 * raises a fault only where an io primitive failed -- a bad index or a bad
 * argument is the language's own failure and panics. */
void dawn_panic(dawn_str *msg);
void dawn_fault(dawn_str *msg);

#endif /* DAWN_RT_H */
