/* See dawn_rt.h. Phase -1 scope only. */
#include "dawn_rt.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int dawn_argc;
static char **dawn_argv;

void dawn_rt_init(int argc, char **argv) {
  dawn_argc = argc;
  dawn_argv = argv;
  /* stdout is compared byte for byte against the JVM backend by the
   * differential harness, so it must not be reordered by buffering
   * when stdout is a pipe and stderr is not. */
  setvbuf(stdout, NULL, _IOFBF, 1 << 16);
}

static void *dawn_alloc(size_t n) {
  void *p = malloc(n);
  if (p == NULL) {
    fputs("dawn: out of memory\n", stderr);
    exit(1);
  }
  return p;
}

dawn_adt *dawn_adt_new(int32_t tag, int32_t nfields) {
  dawn_adt *a =
      (dawn_adt *)dawn_alloc(sizeof(dawn_adt) + (size_t)nfields * sizeof(dawn_slot));
  a->tag = tag;
  a->nfields = nfields;
  return a;
}

dawn_clo *dawn_clo_new(void *fn, int32_t ncap) {
  dawn_clo *c =
      (dawn_clo *)dawn_alloc(sizeof(dawn_clo) + (size_t)ncap * sizeof(dawn_slot));
  c->fn = fn;
  c->ncap = ncap;
  return c;
}

dawn_dict *dawn_dict_new(const dawn_dict *tmpl, int32_t nargs, ...) {
  dawn_dict *d = (dawn_dict *)dawn_alloc(sizeof(dawn_dict));
  *d = *tmpl;
  d->nargs = nargs;
  va_list ap;
  va_start(ap, nargs);
  for (int32_t i = 0; i < nargs; i++) {
    d->args[i] = va_arg(ap, dawn_dict *);
  }
  va_end(ap);
  return d;
}

static dawn_slot *dawn_box(void) {
  return (dawn_slot *)dawn_alloc(sizeof(dawn_slot));
}

dawn_slot *dawn_box_int(int64_t v) {
  dawn_slot *s = dawn_box();
  s->i = v;
  return s;
}

dawn_slot *dawn_box_float(double v) {
  dawn_slot *s = dawn_box();
  s->f = v;
  return s;
}

dawn_slot *dawn_box_bool(bool v) {
  dawn_slot *s = dawn_box();
  s->b = v;
  return s;
}

dawn_slot *dawn_box_unit(dawn_unit v) {
  dawn_slot *s = dawn_box();
  s->u = v;
  return s;
}

dawn_slot *dawn_box_str(dawn_str v) {
  dawn_slot *s = dawn_box();
  s->s = v;
  return s;
}

dawn_unit dawn_print(dawn_str s) {
  if (s.len > 0) {
    fwrite(s.p, 1, (size_t)s.len, stdout);
  }
  return DAWN_UNIT;
}

dawn_unit dawn_println(dawn_str s) {
  dawn_print(s);
  fputc('\n', stdout);
  return DAWN_UNIT;
}

dawn_str dawn_str_concat(dawn_str a, dawn_str b) {
  if (a.len == 0) return b;
  if (b.len == 0) return a;
  char *buf = (char *)dawn_alloc((size_t)(a.len + b.len));
  memcpy(buf, a.p, (size_t)a.len);
  memcpy(buf + a.len, b.p, (size_t)b.len);
  return (dawn_str){buf, a.len + b.len};
}

bool dawn_str_eq(dawn_str a, dawn_str b) {
  if (a.len != b.len) return false;
  if (a.len == 0) return true;
  return memcmp(a.p, b.p, (size_t)a.len) == 0;
}

int64_t dawn_str_len(dawn_str s) {
  /* Code points, not bytes: the JVM backend's str_len counts code points,
   * and that is the observable contract (llvm-backend-research.md 4.3).
   * Continuation bytes are 10xxxxxx; everything else starts a code point. */
  int64_t n = 0;
  for (int64_t i = 0; i < s.len; i++) {
    if (((unsigned char)s.p[i] & 0xC0) != 0x80) n++;
  }
  return n;
}

static dawn_str dawn_str_copy(const char *buf, size_t n) {
  char *out = (char *)dawn_alloc(n);
  memcpy(out, buf, n);
  return (dawn_str){out, (int64_t)n};
}

dawn_str dawn_str_of_int(int64_t v) {
  char buf[32];
  int n = snprintf(buf, sizeof buf, "%lld", (long long)v);
  return dawn_str_copy(buf, (size_t)n);
}

dawn_str dawn_str_of_float(double v) {
  /* Approximates Java's Double.toString well enough for the spike but is
   * NOT byte-identical to it (Java emits the shortest round-tripping form).
   * Floats are therefore excluded from the differential corpus until the
   * real emitter lands a proper dtoa. */
  char buf[64];
  int n = snprintf(buf, sizeof buf, "%.17g", v);
  bool plain = true;
  for (int i = 0; i < n; i++) {
    if (buf[i] == '.' || buf[i] == 'e' || buf[i] == 'E' ||
        buf[i] == 'n' || buf[i] == 'i') {
      plain = false;
      break;
    }
  }
  if (plain && n + 2 < (int)sizeof buf) {
    buf[n++] = '.';
    buf[n++] = '0';
  }
  return dawn_str_copy(buf, (size_t)n);
}

dawn_str dawn_str_of_bool(bool v) {
  return v ? dawn_str_lit("true", 4) : dawn_str_lit("false", 5);
}

dawn_str dawn_str_quote(dawn_str s) {
  /* Worst case every byte doubles, plus the two quotes. Bytes above 0x7f are
   * copied through: the escapes are the five the JVM backend applies, and a
   * multi-byte code point has no continuation byte in that set. */
  char *buf = (char *)dawn_alloc((size_t)(2 * s.len + 2));
  int64_t n = 0;
  buf[n++] = '"';
  for (int64_t i = 0; i < s.len; i++) {
    char c = s.p[i];
    switch (c) {
      case '\\': buf[n++] = '\\'; buf[n++] = '\\'; break;
      case '"': buf[n++] = '\\'; buf[n++] = '"'; break;
      case '\n': buf[n++] = '\\'; buf[n++] = 'n'; break;
      case '\t': buf[n++] = '\\'; buf[n++] = 't'; break;
      case '\r': buf[n++] = '\\'; buf[n++] = 'r'; break;
      default: buf[n++] = c; break;
    }
  }
  buf[n++] = '"';
  return (dawn_str){buf, n};
}

/* ---- hashing and ordering ------------------------------------------------
 *
 * Java defines String.hashCode and String.compareTo over UTF-16 code units.
 * Dawn stores UTF-8, so native has to walk a string the way the JVM sees it
 * rather than the way it holds it. Everything in the BMP -- CJK included --
 * is one unit either way; only astral code points split into a surrogate
 * pair, and that is the only case where the two walks differ. */

/* Next UTF-16 code unit, or -1 at the end. `*i` is the byte cursor and
 * `*pending` carries the low surrogate a previous step left behind. */
static int32_t dawn_utf16_next(dawn_str s, int64_t *i, int32_t *pending) {
  if (*pending >= 0) {
    int32_t u = *pending;
    *pending = -1;
    return u;
  }
  if (*i >= s.len) return -1;
  unsigned char c = (unsigned char)s.p[*i];
  uint32_t cp;
  int64_t n;
  if (c < 0x80) {
    cp = c;
    n = 1;
  } else if ((c & 0xE0) == 0xC0) {
    cp = c & 0x1Fu;
    n = 2;
  } else if ((c & 0xF0) == 0xE0) {
    cp = c & 0x0Fu;
    n = 3;
  } else {
    cp = c & 0x07u;
    n = 4;
  }
  /* a truncated sequence cannot come from a Dawn string; the clamp is only
   * so a malformed one reads no further than the buffer */
  if (*i + n > s.len) n = s.len - *i;
  for (int64_t k = 1; k < n; k++) {
    cp = (cp << 6) | ((unsigned char)s.p[*i + k] & 0x3Fu);
  }
  *i += n;
  if (cp >= 0x10000u) {
    cp -= 0x10000u;
    *pending = (int32_t)(0xDC00u + (cp & 0x3FFu));
    return (int32_t)(0xD800u + (cp >> 10));
  }
  return (int32_t)cp;
}

/* Length in UTF-16 code units: what Java's String.length() reports, and what
 * compareTo falls back on when one string is a prefix of the other. */
static int64_t dawn_utf16_len(dawn_str s) {
  int64_t n = 0;
  for (int64_t i = 0; i < s.len; i++) {
    unsigned char c = (unsigned char)s.p[i];
    if ((c & 0xC0) == 0x80) continue;
    n += (c >= 0xF0) ? 2 : 1;
  }
  return n;
}

/* Java's Double.doubleToLongBits: every NaN collapses to one bit pattern, so
 * that hashing and the total order both treat NaN as a single value. */
static int64_t dawn_double_bits(double v) {
  uint64_t bits;
  if (v != v) {
    bits = UINT64_C(0x7ff8000000000000);
  } else {
    memcpy(&bits, &v, sizeof bits);
  }
  return (int64_t)bits;
}

int64_t dawn_hash_int(int64_t v) {
  return (int32_t)((uint32_t)((uint64_t)v ^ ((uint64_t)v >> 32)));
}

int64_t dawn_hash_float(double v) {
  uint64_t bits = (uint64_t)dawn_double_bits(v);
  /* -0.0 and 0.0 have different bits and therefore different hashes, while
   * `-0.0 == 0.0` is true. That is the JVM's answer too, and it is why the
   * spec says Hash[Float] should not exist (docs/spec 2.2). Reproduced here
   * rather than repaired: the two backends have to give one answer, and
   * removing the impl is a language change, not a runtime one. */
  return (int32_t)((uint32_t)(bits ^ (bits >> 32)));
}

int64_t dawn_hash_bool(bool v) { return v ? 1231 : 1237; }

int64_t dawn_hash_str(dawn_str s) {
  int32_t h = 0;
  int64_t i = 0;
  int32_t pending = -1;
  for (;;) {
    int32_t u = dawn_utf16_next(s, &i, &pending);
    if (u < 0) break;
    h = (int32_t)((uint32_t)h * 31u + (uint32_t)u);
  }
  return h;
}

int64_t dawn_cmp_int(int64_t a, int64_t b) { return a < b ? -1 : (a > b ? 1 : 0); }

int64_t dawn_cmp_float(double a, double b) {
  /* Double.compare's total order, not IEEE: NaN sorts above everything and
   * -0.0 below 0.0. Dawn's `<` is the IEEE comparison and deliberately
   * disagrees with this on exactly those values (spec 4.3). */
  if (a < b) return -1;
  if (a > b) return 1;
  int64_t ba = dawn_double_bits(a);
  int64_t bb = dawn_double_bits(b);
  return ba == bb ? 0 : (ba < bb ? -1 : 1);
}

int64_t dawn_cmp_str(dawn_str a, dawn_str b) {
  int64_t ia = 0;
  int64_t ib = 0;
  int32_t pa = -1;
  int32_t pb = -1;
  for (;;) {
    int32_t ua = dawn_utf16_next(a, &ia, &pa);
    int32_t ub = dawn_utf16_next(b, &ib, &pb);
    /* the magnitude matters, not just the sign: String.compareTo hands back
     * the difference of the first differing unit, and a program can print it */
    if (ua < 0 || ub < 0) return dawn_utf16_len(a) - dawn_utf16_len(b);
    if (ua != ub) return ua - ub;
  }
}

int64_t dawn_idiv(int64_t a, int64_t b) {
  if (b == 0) {
    dawn_panic(dawn_str_lit("/ by zero", 9));
  }
  /* INT64_MIN / -1 overflows and is UB in C; the JVM defines it as
   * wrapping back to INT64_MIN. */
  if (a == INT64_MIN && b == -1) return INT64_MIN;
  return a / b;
}

int64_t dawn_imod(int64_t a, int64_t b) {
  if (b == 0) {
    dawn_panic(dawn_str_lit("/ by zero", 9));
  }
  if (a == INT64_MIN && b == -1) return 0;
  return a % b;
}

void dawn_panic(dawn_str msg) {
  /* Phase 3 replaces this with setjmp/longjmp so catch_panic can intercept.
   * Until then an uncaught panic is the only kind there is. */
  fflush(stdout);
  fputs("panic: ", stderr);
  if (msg.len > 0) fwrite(msg.p, 1, (size_t)msg.len, stderr);
  fputc('\n', stderr);
  exit(1);
}

/* ---- code-point classification (char_is_*) ---------------------------- */

/* Above U+007F the answer needs the Unicode tables; see dawn_rt.h. */
static void dawn_char_ascii_only(int64_t c) {
  if (c < 0 || c > 0x7F) {
    dawn_panic(dawn_str_lit(
      "char classification above U+007F is not implemented on this backend", 67));
  }
}

bool dawn_char_is_letter(int64_t c) {
  dawn_char_ascii_only(c);
  return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z');
}

bool dawn_char_is_digit(int64_t c) {
  dawn_char_ascii_only(c);
  return c >= '0' && c <= '9';
}

bool dawn_char_is_alnum(int64_t c) {
  return dawn_char_is_letter(c) || dawn_char_is_digit(c);
}

bool dawn_char_is_upper(int64_t c) {
  dawn_char_ascii_only(c);
  return c >= 'A' && c <= 'Z';
}

bool dawn_char_is_lower(int64_t c) {
  dawn_char_ascii_only(c);
  return c >= 'a' && c <= 'z';
}

/* Java's set for this range: HT VT LF FF CR, the four file/group/record/unit
 * separators, and space. */
bool dawn_char_is_space(int64_t c) {
  dawn_char_ascii_only(c);
  return (c >= 0x09 && c <= 0x0D) || (c >= 0x1C && c <= 0x1F) || c == 0x20;
}
