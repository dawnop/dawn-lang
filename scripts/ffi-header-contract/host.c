/* The caller's side of the stub in stub.c: what emitted code does around a
 * call to an extern, written against dawn_rt.h. That makes the checks below a
 * second, independent reading of the layout dawn_ffi.h builds (tags, field
 * counts, slot masks, the boxing of an Int), so a constructor that disagrees
 * with the runtime is red here and not first in a package's program.
 *
 * Counting is part of the contract being held. Every argument is borrowed, so
 * this file drops only what it made, and every answer is owned, so it drops
 * each one exactly once. LeakSanitizer (run.sh builds this under it) is what
 * turns a constructor that forgets to copy, or a mask that hides a field from
 * the drop, into a failure.
 *
 * Usage:  host            every case, `<name> PASS|FAIL` per line
 *         host --panic    the stub's one panic (exits 1, message on stderr)
 *         host --panic-ok the same call with a legal argument (exits 0) */

#include "../rc-contract/unicode_stubs.h"

#include <stdio.h>
#include <string.h>

/* What emitted code declares for each extern: the stub's `dawn_x_` symbols,
 * typed with the runtime's own types. */
dawn_adt *dawn_x_t_cstr_len(dawn_str *s);
bool dawn_x_t_is_cstr(dawn_str *s);
int64_t dawn_x_t_str_len(dawn_str *s);
dawn_adt *dawn_x_t_bytes_rev(dawn_bytes *b);
dawn_adt *dawn_x_t_greet(dawn_str *who);
dawn_adt *dawn_x_t_not(bool b);
dawn_adt *dawn_x_t_half(double x);
dawn_adt *dawn_x_t_unit(void);
dawn_adt *dawn_x_t_int(int64_t v);
dawn_adt *dawn_x_t_find(int64_t i);
dawn_adt *dawn_x_t_bump(dawn_adt *r);
int64_t dawn_x_t_or_zero(dawn_adt *o);
int64_t dawn_x_t_checked(int64_t i);

static int failed;

#define CHECK(c)                                          \
  do {                                                    \
    if (!(c)) {                                           \
      fprintf(stderr, "  check failed (line %d): %s\n", __LINE__, #c); \
      failed = 1;                                         \
    }                                                     \
  } while (0)

static bool str_is(const dawn_str *s, const char *want, int64_t n) {
  return s->len == n && memcmp(s->p, want, (size_t)n) == 0;
}

/* The shape of Ok(x): tag, one field, that field masked as a reference. */
static void check_ok(const dawn_adt *r) {
  CHECK(r->tag == DAWN_TAG_OK);
  CHECK(r->nfields == 1);
  CHECK(r->ptrmask.narrow == DAWN_MASK_ONE_BOXED);
}

/* The shape of Err(ForeignError{kind, message, None}) with its two texts. */
static void check_err(const dawn_adt *r, const char *kind, const char *message) {
  CHECK(r->tag == DAWN_TAG_ERR);
  CHECK(r->nfields == 1);
  CHECK(r->ptrmask.narrow == DAWN_MASK_ONE_BOXED);
  const dawn_adt *e = (const dawn_adt *)r->fields[0].p;
  CHECK(e->tag == DAWN_TAG_FOREIGN_ERROR);
  CHECK(e->nfields == 3);
  CHECK(e->ptrmask.narrow == DAWN_MASK_THREE_BOXED);
  CHECK(str_is((const dawn_str *)e->fields[0].p, kind, (int64_t)strlen(kind)));
  CHECK(str_is((const dawn_str *)e->fields[1].p, message, (int64_t)strlen(message)));
  CHECK(((const dawn_adt *)e->fields[2].p)->tag == DAWN_TAG_NONE);
}

static void case_cstr_ok(void) {
  dawn_adt *r = dawn_x_t_cstr_len(DAWN_LIT("hello"));
  check_ok(r);
  CHECK(dawn_peek_int(r->fields[0].p) == 5);
  dawn_drop(r);
  /* the empty string is a C string of length 0, not an error */
  r = dawn_x_t_cstr_len(dawn_str_empty);
  check_ok(r);
  CHECK(dawn_peek_int(r->fields[0].p) == 0);
  dawn_drop(r);
  CHECK(dawn_x_t_is_cstr(DAWN_LIT("x")));
}

/* An embedded NUL is an error, whatever follows it, and the length the header
 * reports still counts it. Truncating would answer Ok(1) here. */
static void case_cstr_embedded_nul(void) {
  dawn_str *s = dawn_str_copy("a\0b", 3);
  dawn_adt *r = dawn_x_t_cstr_len(s);
  check_err(r, "t.embedded_nul", "string has an embedded NUL");
  dawn_drop(r);
  CHECK(!dawn_x_t_is_cstr(s));
  CHECK(dawn_x_t_str_len(s) == 3);
  dawn_drop(s);
  /* a NUL in the last position is just as embedded */
  s = dawn_str_copy("ab\0", 3);
  CHECK(!dawn_x_t_is_cstr(s));
  dawn_drop(s);
  /* and a leading one */
  CHECK(!dawn_x_t_is_cstr(DAWN_LIT("\0ab")));
}

/* The promise dawn_ffi_cstr leans on: p[len] is a NUL, for a string from every
 * kind of producer the runtime has. */
static void case_str_nul_terminated(void) {
  dawn_str *a = dawn_str_copy("abc", 3);
  dawn_str *b = dawn_str_copy("de", 2);
  dawn_str *c = dawn_str_concat(a, b);
  dawn_str *d = dawn_cursor_slice(c, 1, 4);
  CHECK(a->p[a->len] == '\0');
  CHECK(c->len == 5 && c->p[c->len] == '\0');
  CHECK(str_is(d, "bcd", 3) && d->p[d->len] == '\0');
  CHECK(dawn_str_empty->p[0] == '\0');
  dawn_str *e = dawn_str_new(0);
  CHECK(e->p[0] == '\0');
  dawn_drop(a);
  dawn_drop(b);
  dawn_drop(c);
  dawn_drop(d);
  dawn_drop(e);
}

static void case_bytes(void) {
  /* four bytes including a NUL in the middle: a copy by length, not by NUL */
  dawn_bytes *b = dawn_bytes_utf8(DAWN_LIT("\x01\x02\x00\x03"));
  dawn_adt *r = dawn_x_t_bytes_rev(b);
  check_ok(r);
  const dawn_bytes *out = (const dawn_bytes *)r->fields[0].p;
  CHECK(out->len == 4);
  CHECK(memcmp(out->p, "\x03\x00\x02\x01", 4) == 0);
  CHECK(out != b);
  dawn_drop(r);
  dawn_drop(b);
  b = dawn_bytes_utf8(dawn_str_empty);
  r = dawn_x_t_bytes_rev(b);
  check_ok(r);
  CHECK(((const dawn_bytes *)r->fields[0].p)->len == 0);
  dawn_drop(r);
  dawn_drop(b);
}

static void case_string(void) {
  dawn_adt *r = dawn_x_t_greet(DAWN_LIT("world"));
  check_ok(r);
  CHECK(str_is((const dawn_str *)r->fields[0].p, "hello, world", 12));
  dawn_drop(r);
}

static void case_scalars(void) {
  dawn_adt *r = dawn_x_t_not(true);
  check_ok(r);
  CHECK(!dawn_peek_bool(r->fields[0].p));
  dawn_drop(r);
  r = dawn_x_t_half(5.0);
  check_ok(r);
  CHECK(((const dawn_box *)r->fields[0].p)->val.f == 2.5);
  dawn_drop(r);
  r = dawn_x_t_unit();
  check_ok(r);
  CHECK(((const dawn_box *)r->fields[0].p)->val.u == DAWN_UNIT);
  dawn_drop(r);
}

/* An immediate, the largest and smallest ones, and a value only a heap box can
 * hold: `dawn_ffi_box_int` must agree with `dawn_peek_int` on all of them. */
static void case_int_boxes(void) {
  int64_t vs[] = {0, -1, 42, DAWN_IMM_MAX, DAWN_IMM_MIN, DAWN_IMM_MAX + 1, DAWN_IMM_MIN - 1,
                  INT64_MAX, INT64_MIN};
  for (size_t i = 0; i < sizeof vs / sizeof vs[0]; i++) {
    dawn_adt *r = dawn_x_t_int(vs[i]);
    check_ok(r);
    CHECK(dawn_peek_int(r->fields[0].p) == vs[i]);
    dawn_drop(r);
  }
}

static void case_option(void) {
  dawn_adt *o = dawn_x_t_find(21);
  CHECK(o->tag == DAWN_TAG_SOME);
  CHECK(o->nfields == 1);
  CHECK(o->ptrmask.narrow == DAWN_MASK_ONE_BOXED);
  CHECK(dawn_peek_int(o->fields[0].p) == 42);
  CHECK(dawn_x_t_or_zero(o) == 42);
  dawn_drop(o);
  o = dawn_x_t_find(-1);
  CHECK(o->tag == DAWN_TAG_NONE);
  CHECK(dawn_x_t_or_zero(o) == 0);
  dawn_drop(o);
}

/* The Result readers: a stub reads the Ok it is given, and an Err's kind and
 * message, and answers a fresh value without touching the argument's count. */
static void case_result_readers(void) {
  dawn_adt *in = dawn_x_t_int(9);
  dawn_adt *r = dawn_x_t_bump(in);
  check_ok(r);
  CHECK(dawn_peek_int(r->fields[0].p) == 10);
  dawn_drop(r);
  dawn_drop(in);
}

static void case_err_roundtrip(void) {
  dawn_str *bad = dawn_str_copy("a\0b", 3);
  dawn_adt *in = dawn_x_t_cstr_len(bad);
  dawn_adt *r = dawn_x_t_bump(in);
  check_err(r, "t.embedded_nul", "string has an embedded NUL");
  dawn_drop(r);
  dawn_drop(in);
  dawn_drop(bad);
}

typedef struct {
  const char *name;
  void (*fn)(void);
} test_case;

static const test_case cases[] = {
    {"cstr_ok", case_cstr_ok},
    {"cstr_embedded_nul", case_cstr_embedded_nul},
    {"str_nul_terminated", case_str_nul_terminated},
    {"bytes", case_bytes},
    {"string", case_string},
    {"scalars", case_scalars},
    {"int_boxes", case_int_boxes},
    {"option", case_option},
    {"result_readers", case_result_readers},
    {"err_roundtrip", case_err_roundtrip},
};

int main(int argc, char **argv) {
  if (argc == 2 && strcmp(argv[1], "--panic") == 0) {
    dawn_x_t_checked(-1);
    return 0; /* not reached: the panic exits 1 */
  }
  if (argc == 2 && strcmp(argv[1], "--panic-ok") == 0) {
    return dawn_x_t_checked(3) == 3 ? 0 : 2;
  }
  int bad = 0;
  for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
    failed = 0;
    cases[i].fn();
    printf("%s %s\n", cases[i].name, failed ? "FAIL" : "PASS");
    bad |= failed;
  }
  fflush(stdout);
  return bad;
}
