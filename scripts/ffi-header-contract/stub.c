/* A C stub written the way a package writes one: against dawn_ffi.h and
 * nothing else (docs/ffi-extern-design.md). It exists so the header is held to
 * "self-sufficient" by a translation unit that cannot cheat: this file includes
 * no other Dawn header, and dawn_ffi.h poisons the runtime names beyond its own
 * surface, so a function here that needed one would not compile.
 *
 * Each function is one thing a stub does with the surface: read a borrowed
 * argument of each boundary type, build each kind of answer, read a Result it
 * was handed, and refuse. host.c calls them the way emitted code will (borrowed
 * arguments, then drops the answer) and checks the values with the runtime's
 * own header, which is a second reading of the same layout. */
#include "dawn_ffi.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* The ABI this stub was written for. A -D override is how run.sh shows that a
 * header with another number stops the build. */
#ifndef DAWN_FFI_WANT
#define DAWN_FFI_WANT 1
#endif
DAWN_FFI_REQUIRE(DAWN_FFI_WANT);

/* String in, Result[Int] out; the C string path, with its refusal. */
dawn_adt *DAWN_EXTERN(t_cstr_len)(dawn_str *s) {
  const char *c = dawn_ffi_cstr(s);
  if (c == NULL) {
    return dawn_ffi_err("t.embedded_nul", "string has an embedded NUL");
  }
  return dawn_ffi_ok(dawn_ffi_box_int((int64_t)strlen(c)));
}

/* The same question answered as a plain Bool: true when the string has no NUL. */
bool DAWN_EXTERN(t_is_cstr)(dawn_str *s) { return dawn_ffi_cstr(s) != NULL; }

/* The length the header reports, which counts embedded NULs. */
int64_t DAWN_EXTERN(t_str_len)(dawn_str *s) { return dawn_ffi_str_len(s); }

/* Bytes in, Bytes out: reversed, so an off-by-one or a NUL cut shows. */
dawn_adt *DAWN_EXTERN(t_bytes_rev)(dawn_bytes *b) {
  int64_t n = dawn_ffi_bytes_len(b);
  const unsigned char *p = dawn_ffi_bytes_data(b);
  unsigned char buf[64];
  if (n > (int64_t)sizeof buf) {
    return dawn_ffi_err("t.too_long", "more than 64 bytes");
  }
  for (int64_t i = 0; i < n; i++) {
    buf[i] = p[n - 1 - i];
  }
  return dawn_ffi_ok(dawn_ffi_bytes_copy(buf, n));
}

/* String in, String out. */
dawn_adt *DAWN_EXTERN(t_greet)(dawn_str *who) {
  char buf[128];
  int n = snprintf(buf, sizeof buf, "hello, %.*s", (int)dawn_ffi_str_len(who),
                   dawn_ffi_str_data(who));
  return dawn_ffi_ok(dawn_ffi_str_copy(buf, n));
}

/* Bool, Float and Unit payloads. */
dawn_adt *DAWN_EXTERN(t_not)(bool b) { return dawn_ffi_ok(dawn_ffi_box_bool(!b)); }
dawn_adt *DAWN_EXTERN(t_half)(double x) { return dawn_ffi_ok(dawn_ffi_box_float(x / 2)); }
dawn_adt *DAWN_EXTERN(t_unit)(void) { return dawn_ffi_ok(dawn_ffi_box_unit()); }

/* An Int through a box: handed back as given, so an immediate and a heap box
 * (a value outside the immediate range) both go through. */
dawn_adt *DAWN_EXTERN(t_int)(int64_t v) { return dawn_ffi_ok(dawn_ffi_box_int(v)); }

/* Option[Int]. */
dawn_adt *DAWN_EXTERN(t_find)(int64_t i) {
  if (i < 0) {
    return dawn_ffi_none();
  }
  return dawn_ffi_some(dawn_ffi_box_int(i * 2));
}

/* A Result in, a Result out: Ok(n) becomes Ok(n + 1), an Err comes back as a
 * new Err with the same kind and message (borrowed from the argument and
 * copied by the constructor). Reads every accessor. */
dawn_adt *DAWN_EXTERN(t_bump)(dawn_adt *r) {
  if (dawn_ffi_is_ok(r)) {
    return dawn_ffi_ok(dawn_ffi_box_int(dawn_ffi_peek_int(dawn_ffi_payload(r)) + 1));
  }
  const char *kind = dawn_ffi_cstr(dawn_ffi_err_kind(r));
  const char *message = dawn_ffi_cstr(dawn_ffi_err_message(r));
  if (kind == NULL || message == NULL) {
    return dawn_ffi_err("t.embedded_nul", "error text has an embedded NUL");
  }
  return dawn_ffi_err(kind, message);
}

/* Option in, Int out. */
int64_t DAWN_EXTERN(t_or_zero)(dawn_adt *o) {
  return dawn_ffi_is_some(o) ? dawn_ffi_peek_int(dawn_ffi_payload(o)) : 0;
}

/* The one panic: the caller broke the documented contract (index >= 0). */
int64_t DAWN_EXTERN(t_checked)(int64_t i) {
  if (i < 0) {
    dawn_ffi_panic("t.checked: index below zero");
  }
  return i;
}
