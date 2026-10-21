/* The public header of the C extern surface (docs/ffi-extern-design.md).
 *
 * Why this file exists. A package that binds C (`fn f(..) = extern c "sym"`)
 * ships a C stub, and the stub has to build Dawn values: a `Result`, a
 * `String`, a `Bytes`. dawn_rt.h is the runtime's own header (allocator,
 * handlers, continuations, the slot mask of every constructor) and any line of
 * it may change with the next RC or immediates work. A stub written against it
 * would freeze all of that into every package. This header is the small part
 * a stub may rely on, behind an ABI number, and everything else is poisoned
 * below so that reaching past it is a compile error rather than a habit.
 *
 * What a stub gets: read the borrowed arguments (Int and Bool and Float are
 * plain C scalars, String and Bytes through the readers here), build the
 * answer (`ok`, `err`, `some`, `none`, a fresh string or bytes), and in one
 * case only refuse to continue (`dawn_ffi_panic`). That is the whole surface.
 *
 * What a stub does not get, on purpose:
 *   - dup and drop. Arguments are BORROWED for the duration of the call, so a
 *     stub that only reads them has no counting to do, and the constructors
 *     here COPY what they are given, so it holds nothing it must release. A
 *     stub keeps no Dawn value past the call; if it needs the bytes later it
 *     copies them into C memory.
 *   - `dawn_fault`. A fault is a forced unwind that runs the cleanups of the
 *     emitted frames and skips the stub's own, so every C resource the stub
 *     holds at that point leaks, and a third-party library's state is left
 *     half-updated. A failure of the outside world is a `Result`, built with
 *     `dawn_ffi_err`.
 *   - the layout of anything. `dawn_adt`, the slot masks and the tags are the
 *     runtime's; the accessors below are the only way a stub reads them.
 *
 * Values that cross: Int (`int64_t`), Float (`double`), Bool (`bool`), Unit
 * (`dawn_unit`), String (`dawn_str *`), Bytes (`dawn_bytes *`), and
 * `Option`/`Result` (`dawn_adt *`) as the return type. Not Array (the first
 * thing the next ABI number adds, when a consumer needs one), not user types,
 * closures or collections.
 *
 * Header only, and it includes dawn_rt.h, so it adds no file to the staging
 * directory beyond itself: a native build already has the runtime header next
 * to the generated C. The accessors are `static inline` over the runtime's
 * exported functions; if one ever needs a runtime function of its own it moves
 * out of line and no stub notices.
 *
 * Counting convention, once more because it is the contract: an ARGUMENT is
 * borrowed (do not drop it, do not store it); a RETURN VALUE is owned (a fresh
 * count, which every constructor below hands back). The `Result` accessors
 * return borrowed pointers into the result they read. */
#ifndef DAWN_FFI_H
#define DAWN_FFI_H

#include "dawn_rt.h"

#include <string.h>

/* The ABI number. It goes up when a name here changes meaning or goes away;
 * adding a name does not move it. A stub says which one it was written for
 * with `DAWN_FFI_REQUIRE(1);` after the include, and a mismatch stops the
 * build there with a sentence instead of surfacing as a wrong answer. */
#define DAWN_FFI_ABI 1

#define DAWN_FFI_REQUIRE(n)                                                  \
  _Static_assert((n) == DAWN_FFI_ABI,                                        \
                 "this C stub was written for a different dawn_ffi.h ABI; " \
                 "see docs/ffi-extern-design.md")

/* The linker name of an extern's stub. The compiler spells a call to
 * `extern c "sq_open"` as `dawn_x_sq_open`, and the stub defines it with
 * `DAWN_EXTERN(sq_open)`. libc has no `dawn_x_*`, so an extern cannot bind
 * `system` or `dlopen`: only a symbol the package's own stub wrote can be
 * reached. The prefix and the expansion are one definition here so the
 * emitter and the stubs cannot disagree about it. */
#define DAWN_EXTERN(sym) dawn_x_##sym

/* ---- reading arguments ---------------------------------------------------
 *
 * Int, Float and Bool arrive as C scalars and need nothing. */

static inline int64_t dawn_ffi_str_len(const dawn_str *s) { return s->len; }

/* The bytes of a string, `dawn_ffi_str_len` of them, NOT necessarily a C
 * string: a Dawn string may hold NUL. */
static inline const char *dawn_ffi_str_data(const dawn_str *s) { return s->p; }

/* The string as a C string, for libraries that take `const char *`; NULL when
 * the string has an embedded NUL, never a truncation. Truncating would make
 * `open("a\0b")` open "a", which is a different file than the program named,
 * and the stub's caller cannot see it happen. The stub answers NULL with
 * `dawn_ffi_err`, in its own error kind. This leans on the runtime's promise
 * that `p[len]` is a NUL (see `dawn_str` in dawn_rt.h). Borrowed: valid for the
 * call and no longer. */
static inline const char *dawn_ffi_cstr(const dawn_str *s) {
  if (s->len > 0 && memchr(s->p, 0, (size_t)s->len) != NULL) {
    return NULL;
  }
  return s->p;
}

static inline int64_t dawn_ffi_bytes_len(const dawn_bytes *b) { return b->len; }
static inline const unsigned char *dawn_ffi_bytes_data(const dawn_bytes *b) { return b->p; }

/* ---- building results ----------------------------------------------------
 *
 * Every constructor returns an owned value and copies its C inputs. `box_*`
 * make the erased payload `ok` and `some` take; they are for the payload of
 * `Result[Int, _]` and friends, where the type variable erases the Int. A
 * payload that is already a pointer (a string, bytes) goes in as it is. */

static inline void *dawn_ffi_box_int(int64_t v) { return dawn_box_int(v); }
static inline void *dawn_ffi_box_bool(bool v) { return dawn_box_bool(v); }
static inline void *dawn_ffi_box_float(double v) { return dawn_box_float(v); }
static inline void *dawn_ffi_box_unit(void) { return dawn_box_unit(DAWN_UNIT); }

static inline dawn_str *dawn_ffi_str_copy(const char *p, int64_t n) { return dawn_str_copy(p, n); }
static inline dawn_str *dawn_ffi_str_from_cstr(const char *c) {
  return dawn_str_copy(c, (int64_t)strlen(c));
}

/* Fresh bytes holding a copy of `n` bytes at `p`. The runtime has one
 * constructor that copies a byte run and it takes text; lending it a borrowed
 * string over the same bytes is the same copy, and keeps this header from
 * asking the runtime for a name. */
static inline dawn_bytes *dawn_ffi_bytes_copy(const void *p, int64_t n) {
  return dawn_bytes_utf8(dawn_str_lit((const char *)p, n));
}

/* `Ok(payload)`. Takes the payload's reference, so `ok(box_int(3))`,
 * `ok(str_from_cstr(s))` and `ok(box_unit())` leave nothing to release. */
static inline dawn_adt *dawn_ffi_ok(void *payload) {
  dawn_adt *a = dawn_adt_new(DAWN_TAG_OK, 1, DAWN_MASK_ONE_BOXED);
  a->fields[0].p = payload;
  return a;
}

/* `Err(ForeignError { kind, message, cause: None })`, both strings copied.
 * `kind` is `"<package>.<code>"`, as `gpu.no_driver` and `cuda.*` are, so a
 * handler can tell whose failure it holds. */
static inline dawn_adt *dawn_ffi_err(const char *kind, const char *message) {
  dawn_adt *e = dawn_adt_new(DAWN_TAG_FOREIGN_ERROR, 3, DAWN_MASK_THREE_BOXED);
  e->fields[0].p = dawn_str_copy(kind, (int64_t)strlen(kind));
  e->fields[1].p = dawn_str_copy(message, (int64_t)strlen(message));
  e->fields[2].p = dawn_none();
  dawn_adt *a = dawn_adt_new(DAWN_TAG_ERR, 1, DAWN_MASK_ONE_BOXED);
  a->fields[0].p = e;
  return a;
}

/* `Some(payload)` (takes the reference, as `ok` does) and `None`. */
static inline dawn_adt *dawn_ffi_some(void *payload) { return dawn_some(payload); }
static inline dawn_adt *dawn_ffi_none(void) { return dawn_none(); }

/* ---- reading results -----------------------------------------------------
 *
 * For a stub that calls another stub, and for a test that holds a stub to what
 * it answered. Everything returned is borrowed from the value read. */

static inline bool dawn_ffi_is_ok(const dawn_adt *r) { return r->tag == DAWN_TAG_OK; }
static inline bool dawn_ffi_is_some(const dawn_adt *o) { return o->tag == DAWN_TAG_SOME; }

/* The erased payload of an `Ok` or a `Some`; read it back with the matching
 * `peek` below, or as the `dawn_str *`/`dawn_bytes *` it is. */
static inline void *dawn_ffi_payload(const dawn_adt *a) { return a->fields[0].p; }

/* The `ForeignError` of an `Err`: its kind and message as strings. */
static inline const dawn_str *dawn_ffi_err_kind(const dawn_adt *r) {
  return (const dawn_str *)((const dawn_adt *)r->fields[0].p)->fields[0].p;
}
static inline const dawn_str *dawn_ffi_err_message(const dawn_adt *r) {
  return (const dawn_str *)((const dawn_adt *)r->fields[0].p)->fields[1].p;
}

static inline int64_t dawn_ffi_peek_int(const void *payload) { return dawn_peek_int(payload); }
static inline bool dawn_ffi_peek_bool(const void *payload) { return dawn_peek_bool(payload); }
static inline double dawn_ffi_peek_float(const void *payload) {
  return ((const dawn_box *)payload)->val.f;
}

/* ---- refusing to continue ------------------------------------------------
 *
 * The one use: the CALLER broke the contract the stub documents (an index out
 * of the range it was told, a handle it never issued), the same judgement the
 * runtime makes when it panics on a bad array index. It is not for a failure
 * of the outside world (a missing file, a locked database, an absent library):
 * those are `dawn_ffi_err`, which the program can handle. A panic unwinds
 * through the stub's frame without running anything of the stub's, so call it
 * before the stub holds a C resource, never after. The message is copied. */
static inline _Noreturn void dawn_ffi_panic(const char *message) {
  dawn_panic(dawn_str_lit(message, strlen(message)));
  __builtin_unreachable();
}

/* ---- the fence -----------------------------------------------------------
 *
 * Everything above is the surface. From here on, the runtime names a stub
 * could reach through dawn_rt.h are poisoned, so a stub that wants one has to
 * come back and ask for it here (and the design doc says what it will answer).
 * The list is the counting, the fault, the raw constructors and the boxing
 * representation. A translation unit that includes dawn_rt.h and not this
 * header, the emitted code and the runtime itself, is not touched. */
#pragma GCC poison dawn_fault dawn_panic dawn_dup dawn_drop dawn_drop_slow
#pragma GCC poison dawn_adt_new dawn_adt_new_wide dawn_str_new dawn_str_copy
#pragma GCC poison dawn_some dawn_none dawn_box_int dawn_box_bool dawn_box_float dawn_box_unit
#pragma GCC poison dawn_peek_int dawn_peek_bool dawn_bytes_utf8

#endif /* DAWN_FFI_H */
