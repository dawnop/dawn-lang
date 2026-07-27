/* See dawn_rt.h. Phase -1 scope only. */

/* stat/opendir/readdir are POSIX, and -std=c11 hides them without this. */
#define _POSIX_C_SOURCE 200809L

#include "dawn_rt.h"

#include <dirent.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

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

dawn_adt *dawn_some(void *boxed) {
  dawn_adt *a = dawn_adt_new(DAWN_TAG_SOME, 1);
  a->fields[0].p = boxed;
  return a;
}

dawn_adt *dawn_none(void) { return dawn_adt_new(DAWN_TAG_NONE, 0); }

static dawn_adt *dawn_ok(void *boxed) {
  dawn_adt *a = dawn_adt_new(DAWN_TAG_OK, 1);
  a->fields[0].p = boxed;
  return a;
}

static dawn_adt *dawn_err(void *boxed) {
  dawn_adt *a = dawn_adt_new(DAWN_TAG_ERR, 1);
  a->fields[0].p = boxed;
  return a;
}

dawn_unit dawn_io_print(dawn_str s) {
  if (s.len > 0) {
    fwrite(s.p, 1, (size_t)s.len, stdout);
  }
  return DAWN_UNIT;
}

dawn_unit dawn_io_println(dawn_str s) {
  dawn_io_print(s);
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

/* ---- panics, and the two intrinsics that catch one ----------------------
 *
 * `java_try` and `catch_panic` are one mechanism on the JVM (a try/catch over
 * Exception and over Throwable) and one mechanism here, but not the same one:
 * native has no exceptions, so what these catch is a panic. A handler is a
 * frame on this stack; `dawn_panic` jumps to the innermost one, or reports and
 * exits when there is none, which is what every panic did before this. */
typedef struct dawn_handler {
  jmp_buf jb;
  struct dawn_handler *prev;
} dawn_handler;

static dawn_handler *dawn_handlers;
static dawn_str dawn_panic_msg;

void dawn_panic(dawn_str msg) {
  if (dawn_handlers != NULL) {
    dawn_panic_msg = msg;
    longjmp(dawn_handlers->jb, 1);
  }
  fflush(stdout);
  fputs("panic: ", stderr);
  if (msg.len > 0) fwrite(msg.p, 1, (size_t)msg.len, stderr);
  fputc('\n', stderr);
  exit(1);
}

/* The closure returns an erased slot whatever `T` is, so one cast covers
 * every instantiation -- see the header. */
static dawn_adt *dawn_run_caught(dawn_clo *f) {
  dawn_handler h;
  h.prev = dawn_handlers;
  dawn_handlers = &h;
  if (setjmp(h.jb) != 0) {
    dawn_handlers = h.prev;
    return dawn_err(dawn_box_str(dawn_panic_msg));
  }
  void *v = ((void *(*)(dawn_clo *))f->fn)(f);
  dawn_handlers = h.prev;
  return dawn_ok(v);
}

dawn_adt *dawn_java_try(dawn_clo *f) { return dawn_run_caught(f); }

dawn_adt *dawn_catch_panic(dawn_clo *f) { return dawn_run_caught(f); }

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

/* Whitespace is the one classification whose full answer is small enough to
 * write down, so this one does not stop at U+007F: below it, Java's set is HT
 * VT LF FF CR, the four file/group/record/unit separators, and space; above
 * it, the separators that are not non-breaking. U+00A0, U+2007 and U+202F are
 * separators and are *not* whitespace, which is the part that surprises. */
static bool dawn_is_space_cp(int64_t c) {
  if (c <= 0x7F) {
    return (c >= 0x09 && c <= 0x0D) || (c >= 0x1C && c <= 0x1F) || c == 0x20;
  }
  return c == 0x1680 || (c >= 0x2000 && c <= 0x2006) ||
         (c >= 0x2008 && c <= 0x200A) || c == 0x2028 || c == 0x2029 ||
         c == 0x205F || c == 0x3000;
}

bool dawn_char_is_space(int64_t c) { return dawn_is_space_cp(c); }

/* ---- Array: the backend's one collection primitive ---- */

#define DAWN_ARRAY_MIN_CAP 8

static dawn_array_buf *dawn_array_buf_new(int32_t cap) {
  dawn_array_buf *b = (dawn_array_buf *)dawn_alloc(sizeof(dawn_array_buf));
  if (cap < DAWN_ARRAY_MIN_CAP) {
    cap = DAWN_ARRAY_MIN_CAP;
  }
  b->data = (void **)dawn_alloc((size_t)cap * sizeof(void *));
  b->cap = cap;
  b->high = 0;
  return b;
}

static dawn_array *dawn_array_of(dawn_array_buf *b, int32_t len) {
  dawn_array *a = (dawn_array *)dawn_alloc(sizeof(dawn_array));
  a->buf = b;
  a->len = len;
  return a;
}

dawn_array *dawn_array_new(void) {
  return dawn_array_of(dawn_array_buf_new(DAWN_ARRAY_MIN_CAP), 0);
}

int64_t dawn_array_len(const dawn_array *a) { return (int64_t)a->len; }

/* Bounds are the caller's business on the JVM too -- std/pvec and std/hamt
 * index within a length they just read. A check here is cheap next to what a
 * wild read costs, and native has no verifier to catch it. */
void *dawn_array_get(const dawn_array *a, int64_t i) {
  if (i < 0 || i >= (int64_t)a->len) {
    dawn_panic(dawn_str_lit("Array index out of bounds", 24));
  }
  return a->buf->data[i];
}

/* The frontier slot has never belonged to any version, so writing it in place
 * cannot be observed. Anything else copies. */
dawn_array *dawn_array_push(dawn_array *a, void *x) {
  dawn_array_buf *b = a->buf;
  if (a->len == b->high && a->len < b->cap) {
    b->data[a->len] = x;
    b->high = a->len + 1;
    return dawn_array_of(b, a->len + 1);
  }
  int32_t cap = a->len + 1;
  if (cap < b->cap) {
    cap = b->cap;
  }
  if (cap < a->len * 2) {
    cap = a->len * 2;
  }
  dawn_array_buf *nb = dawn_array_buf_new(cap);
  for (int32_t k = 0; k < a->len; k++) {
    nb->data[k] = a->buf->data[k];
  }
  nb->data[a->len] = x;
  nb->high = a->len + 1;
  return dawn_array_of(nb, a->len + 1);
}

/* Always copies -- see the header: slot `i < len` is already handed out and
 * no watermark can say who still reads it. */
dawn_array *dawn_array_with(const dawn_array *a, int64_t i, void *x) {
  if (i < 0 || i >= (int64_t)a->len) {
    dawn_panic(dawn_str_lit("Array index out of bounds", 24));
  }
  dawn_array_buf *nb = dawn_array_buf_new(a->len);
  for (int32_t k = 0; k < a->len; k++) {
    nb->data[k] = a->buf->data[k];
  }
  nb->data[i] = x;
  nb->high = a->len;
  return dawn_array_of(nb, a->len);
}

/* std/hamt counts set bits of a 32-way bitmap. Dawn's Int is signed 64-bit,
 * so this counts all 64 and lets the caller mask. */
int64_t dawn_popcount(int64_t n) {
  uint64_t v = (uint64_t)n;
  int64_t c = 0;
  while (v != 0) {
    v &= v - 1;
    c++;
  }
  return c;
}

/* ---- UTF-8 --------------------------------------------------------------
 *
 * `dawn_utf16_next` above walks a string as the JVM sees it, because hashing
 * and ordering are defined that way. These walk it as it is stored, which is
 * what positions and code points need. */

static int64_t dawn_utf8_seq(unsigned char c) {
  if (c < 0x80) return 1;
  if ((c & 0xE0) == 0xC0) return 2;
  if ((c & 0xF0) == 0xE0) return 3;
  return 4;
}

/* A byte offset lands between characters, rather than inside one. */
static bool dawn_utf8_boundary(dawn_str s, int64_t i) {
  return i == s.len || ((unsigned char)s.p[i] & 0xC0) != 0x80;
}

/* The code point starting at `i`; `*n` receives its length in bytes. */
static uint32_t dawn_utf8_at(dawn_str s, int64_t i, int64_t *n) {
  unsigned char c = (unsigned char)s.p[i];
  int64_t k = dawn_utf8_seq(c);
  if (i + k > s.len) k = s.len - i;
  uint32_t cp;
  if (k == 1) {
    cp = c;
  } else if (k == 2) {
    cp = c & 0x1Fu;
  } else if (k == 3) {
    cp = c & 0x0Fu;
  } else {
    cp = c & 0x07u;
  }
  for (int64_t j = 1; j < k; j++) {
    cp = (cp << 6) | ((unsigned char)s.p[i + j] & 0x3Fu);
  }
  *n = k;
  return cp;
}

/* Writes at most four bytes; returns how many. */
static int64_t dawn_utf8_put(char *out, uint32_t cp) {
  if (cp < 0x80u) {
    out[0] = (char)cp;
    return 1;
  }
  if (cp < 0x800u) {
    out[0] = (char)(0xC0u | (cp >> 6));
    out[1] = (char)(0x80u | (cp & 0x3Fu));
    return 2;
  }
  if (cp < 0x10000u) {
    out[0] = (char)(0xE0u | (cp >> 12));
    out[1] = (char)(0x80u | ((cp >> 6) & 0x3Fu));
    out[2] = (char)(0x80u | (cp & 0x3Fu));
    return 3;
  }
  out[0] = (char)(0xF0u | (cp >> 18));
  out[1] = (char)(0x80u | ((cp >> 12) & 0x3Fu));
  out[2] = (char)(0x80u | ((cp >> 6) & 0x3Fu));
  out[3] = (char)(0x80u | (cp & 0x3Fu));
  return 4;
}

/* Code points in the first `upto` bytes -- how a byte offset becomes the
 * index `str_index_of` reports. */
static int64_t dawn_cp_count(dawn_str s, int64_t upto) {
  int64_t n = 0;
  for (int64_t i = 0; i < upto; i++) {
    if (((unsigned char)s.p[i] & 0xC0) != 0x80) n++;
  }
  return n;
}

/* First byte offset at or after `from` where `sub` occurs, or -1. An empty
 * needle matches at `from`, as String.indexOf does. */
static int64_t dawn_find(dawn_str s, dawn_str sub, int64_t from) {
  if (from < 0) from = 0;
  if (sub.len == 0) return from <= s.len ? from : -1;
  for (int64_t i = from; i + sub.len <= s.len; i++) {
    if (memcmp(s.p + i, sub.p, (size_t)sub.len) == 0) return i;
  }
  return -1;
}

/* ---- cursors ---- */

int64_t dawn_cursor_start(dawn_str s) {
  (void)s;
  return 0;
}

int64_t dawn_cursor_end(dawn_str s) { return s.len; }

bool dawn_cursor_done(dawn_str s, int64_t c) { return c >= s.len; }

int64_t dawn_cursor_char(dawn_str s, int64_t c) {
  if (c < 0 || c >= s.len) return -1;
  int64_t n;
  return (int64_t)dawn_utf8_at(s, c, &n);
}

int64_t dawn_cursor_next(dawn_str s, int64_t c) {
  if (c < 0) return 0;
  if (c >= s.len) return s.len;
  int64_t k = dawn_utf8_seq((unsigned char)s.p[c]);
  return c + k > s.len ? s.len : c + k;
}

int64_t dawn_cursor_prev(dawn_str s, int64_t c) {
  if (c <= 0) return 0;
  if (c > s.len) c = s.len;
  int64_t i = c - 1;
  while (i > 0 && ((unsigned char)s.p[i] & 0xC0) == 0x80) i--;
  return i;
}

int64_t dawn_cursor_skip(dawn_str s, int64_t c, dawn_str sub) {
  int64_t n = c + sub.len;
  return n > s.len ? s.len : n;
}

dawn_str dawn_cursor_slice(dawn_str s, int64_t from, int64_t to) {
  if (from < 0 || to > s.len || from > to ||
      !dawn_utf8_boundary(s, from) || !dawn_utf8_boundary(s, to)) {
    dawn_panic(dawn_str_lit("cursor_slice: invalid cursor range", 34));
  }
  return (dawn_str){s.p + from, to - from};
}

dawn_adt *dawn_index_of_from(dawn_str s, dawn_str sub, int64_t from) {
  if (from > s.len) return dawn_none();
  int64_t i = dawn_find(s, sub, from);
  return i < 0 ? dawn_none() : dawn_some(dawn_box_int(i));
}

/* ---- the str_* primitives ---- */

dawn_str dawn_str_trim(dawn_str s) {
  int64_t a = 0;
  while (a < s.len) {
    int64_t n;
    if (!dawn_is_space_cp((int64_t)dawn_utf8_at(s, a, &n))) break;
    a += n;
  }
  int64_t b = s.len;
  while (b > a) {
    int64_t prev = dawn_cursor_prev(s, b);
    int64_t n;
    if (!dawn_is_space_cp((int64_t)dawn_utf8_at(s, prev, &n))) break;
    b = prev;
  }
  return (dawn_str){s.p + a, b - a};
}

/* ASCII case only. A cased letter above U+007F -- Greek, Cyrillic, accented
 * Latin -- is left alone where the JVM would fold it, so these two are the
 * one place a program can see the backends differ without a panic saying so.
 * Full folding needs the Unicode tables this runtime does not carry yet, and
 * refusing every non-ASCII string instead would break `str.lower` on text
 * that has no case at all, which is most of it. */
static dawn_str dawn_ascii_case(dawn_str s, bool up) {
  char *buf = (char *)dawn_alloc((size_t)s.len);
  for (int64_t i = 0; i < s.len; i++) {
    char c = s.p[i];
    if (up && c >= 'a' && c <= 'z') {
      c = (char)(c - 32);
    } else if (!up && c >= 'A' && c <= 'Z') {
      c = (char)(c + 32);
    }
    buf[i] = c;
  }
  return (dawn_str){buf, s.len};
}

dawn_str dawn_str_lower(dawn_str s) { return dawn_ascii_case(s, false); }

dawn_str dawn_str_upper(dawn_str s) { return dawn_ascii_case(s, true); }

bool dawn_str_contains(dawn_str s, dawn_str sub) {
  return dawn_find(s, sub, 0) >= 0;
}

bool dawn_str_starts_with(dawn_str s, dawn_str prefix) {
  return prefix.len <= s.len && memcmp(s.p, prefix.p, (size_t)prefix.len) == 0;
}

bool dawn_str_ends_with(dawn_str s, dawn_str suffix) {
  return suffix.len <= s.len &&
         memcmp(s.p + (s.len - suffix.len), suffix.p, (size_t)suffix.len) == 0;
}

int64_t dawn_str_index_of(dawn_str s, dawn_str sub) {
  int64_t i = dawn_find(s, sub, 0);
  return i < 0 ? -1 : dawn_cp_count(s, i);
}

int64_t dawn_str_last_index_of(dawn_str s, dawn_str sub) {
  /* String.lastIndexOf("") is the length, not 0 */
  if (sub.len == 0) return dawn_str_len(s);
  for (int64_t i = s.len - sub.len; i >= 0; i--) {
    if (memcmp(s.p + i, sub.p, (size_t)sub.len) == 0) return dawn_cp_count(s, i);
  }
  return -1;
}

/* ---- parsing ----
 *
 * Long.parseLong and Double.parseDouble strip first and reject anything left
 * over, and overflow is a refusal rather than a wrap. */

static int64_t dawn_digit_val(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'z') return c - 'a' + 10;
  if (c >= 'A' && c <= 'Z') return c - 'A' + 10;
  return -1;
}

static dawn_adt *dawn_parse_radix(dawn_str s, int64_t radix) {
  if (radix < 2 || radix > 36) return dawn_none();
  dawn_str t = dawn_str_trim(s);
  int64_t i = 0;
  bool neg = false;
  if (i < t.len && (t.p[i] == '+' || t.p[i] == '-')) {
    neg = t.p[i] == '-';
    i++;
  }
  if (i >= t.len) return dawn_none();
  /* accumulated as the magnitude, so that LONG_MIN parses */
  uint64_t limit = neg ? (uint64_t)INT64_MAX + 1u : (uint64_t)INT64_MAX;
  uint64_t acc = 0;
  for (; i < t.len; i++) {
    int64_t d = dawn_digit_val(t.p[i]);
    if (d < 0 || d >= radix) return dawn_none();
    if (acc > (limit - (uint64_t)d) / (uint64_t)radix) return dawn_none();
    acc = acc * (uint64_t)radix + (uint64_t)d;
  }
  /* negated as unsigned: LONG_MIN's magnitude has no int64_t to be negated in */
  int64_t v = neg ? (int64_t)(0u - acc) : (int64_t)acc;
  return dawn_some(dawn_box_int(v));
}

dawn_adt *dawn_parse_int(dawn_str s) { return dawn_parse_radix(s, 10); }

dawn_adt *dawn_parse_int_radix(dawn_str s, int64_t radix) {
  return dawn_parse_radix(s, radix);
}

dawn_adt *dawn_parse_float(dawn_str s) {
  /* strtod's grammar is close to Double.parseDouble's but not equal to it:
   * Java also accepts a trailing f/F/d/D and spells the infinities
   * "Infinity", while strtod also takes hex floats. Floats are already out of
   * the differential corpus over dawn_str_of_float; this is the same gap. */
  dawn_str t = dawn_str_trim(s);
  if (t.len == 0) return dawn_none();
  char *buf = (char *)dawn_alloc((size_t)t.len + 1);
  memcpy(buf, t.p, (size_t)t.len);
  buf[t.len] = '\0';
  char *end = NULL;
  double v = strtod(buf, &end);
  bool whole = end != NULL && *end == '\0';
  free(buf);
  return whole ? dawn_some(dawn_box_float(v)) : dawn_none();
}

/* ---- code points, and the list primitives that cross through Array ---- */

dawn_array *dawn_code_points(dawn_str s) {
  dawn_array *a = dawn_array_new();
  int64_t i = 0;
  while (i < s.len) {
    int64_t n;
    uint32_t cp = dawn_utf8_at(s, i, &n);
    a = dawn_array_push(a, dawn_box_int((int64_t)cp));
    i += n;
  }
  return a;
}

dawn_str dawn_from_code_points(dawn_array *cps) {
  int64_t n = dawn_array_len(cps);
  char *buf = (char *)dawn_alloc((size_t)(4 * n) + 1);
  int64_t at = 0;
  for (int64_t i = 0; i < n; i++) {
    int64_t cp = ((dawn_slot *)dawn_array_get(cps, i))->i;
    if (cp < 0 || cp > 0x10FFFF) {
      dawn_panic(dawn_str_lit("from_code_points: not a valid code point", 39));
    }
    at += dawn_utf8_put(buf + at, (uint32_t)cp);
  }
  return (dawn_str){buf, at};
}

dawn_str dawn_join(dawn_array *parts, dawn_str sep) {
  int64_t n = dawn_array_len(parts);
  if (n == 0) return dawn_str_empty;
  int64_t total = sep.len * (n - 1);
  for (int64_t i = 0; i < n; i++) {
    total += ((dawn_slot *)dawn_array_get(parts, i))->s.len;
  }
  char *buf = (char *)dawn_alloc((size_t)total + 1);
  int64_t at = 0;
  for (int64_t i = 0; i < n; i++) {
    if (i > 0 && sep.len > 0) {
      memcpy(buf + at, sep.p, (size_t)sep.len);
      at += sep.len;
    }
    dawn_str part = ((dawn_slot *)dawn_array_get(parts, i))->s;
    if (part.len > 0) {
      memcpy(buf + at, part.p, (size_t)part.len);
      at += part.len;
    }
  }
  return (dawn_str){buf, at};
}

/* ---- bytes ---- */

static dawn_bytes *dawn_bytes_of(const unsigned char *p, int64_t len) {
  dawn_bytes *b = (dawn_bytes *)dawn_alloc(sizeof(dawn_bytes));
  b->p = p;
  b->len = len;
  return b;
}

dawn_bytes *dawn_bytes_concat(const dawn_bytes *a, const dawn_bytes *b) {
  unsigned char *buf = (unsigned char *)dawn_alloc((size_t)(a->len + b->len) + 1);
  if (a->len > 0) memcpy(buf, a->p, (size_t)a->len);
  if (b->len > 0) memcpy(buf + a->len, b->p, (size_t)b->len);
  return dawn_bytes_of(buf, a->len + b->len);
}

bool dawn_bytes_eq(const dawn_bytes *a, const dawn_bytes *b) {
  if (a->len != b->len) return false;
  if (a->len == 0) return true;
  return memcmp(a->p, b->p, (size_t)a->len) == 0;
}

dawn_bytes *dawn_bytes_utf8(dawn_str s) {
  unsigned char *buf = (unsigned char *)dawn_alloc((size_t)s.len + 1);
  if (s.len > 0) memcpy(buf, s.p, (size_t)s.len);
  return dawn_bytes_of(buf, s.len);
}

int64_t dawn_bytes_len(const dawn_bytes *b) { return b->len; }

int64_t dawn_bytes_at(const dawn_bytes *b, int64_t i) {
  if (i < 0 || i >= b->len) return -1;
  return (int64_t)b->p[i];
}

dawn_bytes *dawn_bytes_slice(const dawn_bytes *b, int64_t from, int64_t to) {
  /* both ends clamped into range first, as the JVM backend's bytes_clamp does */
  if (from < 0) from = 0;
  if (from > b->len) from = b->len;
  if (to < 0) to = 0;
  if (to > b->len) to = b->len;
  if (from > to) {
    dawn_panic(dawn_str_lit("bytes_slice: start greater than end", 35));
  }
  unsigned char *buf = (unsigned char *)dawn_alloc((size_t)(to - from) + 1);
  if (to > from) memcpy(buf, b->p + from, (size_t)(to - from));
  return dawn_bytes_of(buf, to - from);
}

/* Charset names compare the way Java's do: case-insensitively. */
static bool dawn_charset_is(dawn_str cs, const char *name) {
  size_t n = strlen(name);
  if ((size_t)cs.len != n) return false;
  for (size_t i = 0; i < n; i++) {
    char a = cs.p[i];
    char b = name[i];
    if (a >= 'A' && a <= 'Z') a = (char)(a + 32);
    if (b >= 'A' && b <= 'Z') b = (char)(b + 32);
    if (a != b) return false;
  }
  return true;
}

dawn_adt *dawn_bytes_decode(const dawn_bytes *b, dawn_str charset) {
  if (dawn_charset_is(charset, "UTF-8") || dawn_charset_is(charset, "UTF8")) {
    /* Malformed input is replaced, not refused -- what `new String(bytes,
     * charset)` does. A byte that starts no valid sequence becomes U+FFFD. */
    char *buf = (char *)dawn_alloc((size_t)(3 * b->len) + 1);
    int64_t at = 0;
    int64_t i = 0;
    dawn_str src = {(const char *)b->p, b->len};
    while (i < b->len) {
      int64_t n;
      uint32_t cp = dawn_utf8_at(src, i, &n);
      bool ok = true;
      for (int64_t j = 1; j < n; j++) {
        if ((b->p[i + j] & 0xC0) != 0x80) ok = false;
      }
      if (!ok || i + dawn_utf8_seq(b->p[i]) > b->len) {
        at += dawn_utf8_put(buf + at, 0xFFFDu);
        i++;
      } else {
        at += dawn_utf8_put(buf + at, cp);
        i += n;
      }
    }
    return dawn_some(dawn_box_str((dawn_str){buf, at}));
  }
  if (dawn_charset_is(charset, "ISO-8859-1") || dawn_charset_is(charset, "latin1")) {
    char *buf = (char *)dawn_alloc((size_t)(2 * b->len) + 1);
    int64_t at = 0;
    for (int64_t i = 0; i < b->len; i++) {
      at += dawn_utf8_put(buf + at, b->p[i]);
    }
    return dawn_some(dawn_box_str((dawn_str){buf, at}));
  }
  return dawn_none();
}

/* ---- io ---- */

dawn_adt *dawn_io_read_line(void) {
  size_t cap = 128;
  size_t n = 0;
  char *buf = (char *)dawn_alloc(cap);
  int c = fgetc(stdin);
  if (c == EOF) {
    free(buf);
    return dawn_none();
  }
  while (c != EOF && c != '\n') {
    if (n == cap) {
      char *bigger = (char *)dawn_alloc(cap * 2);
      memcpy(bigger, buf, n);
      free(buf);
      buf = bigger;
      cap *= 2;
    }
    buf[n++] = (char)c;
    c = fgetc(stdin);
  }
  /* BufferedReader.readLine keeps neither terminator */
  if (n > 0 && buf[n - 1] == '\r') n--;
  return dawn_some(dawn_box_str((dawn_str){buf, (int64_t)n}));
}

/* A Dawn string is not NUL-terminated; every path handed to the C library
 * has to be copied to get the terminator. */
static char *dawn_cpath(dawn_str s) {
  char *p = (char *)dawn_alloc((size_t)s.len + 1);
  if (s.len > 0) memcpy(p, s.p, (size_t)s.len);
  p[s.len] = '\0';
  return p;
}

bool dawn_io_is_dir(dawn_str path) {
  char *p = dawn_cpath(path);
  struct stat st;
  bool yes = stat(p, &st) == 0 && S_ISDIR(st.st_mode);
  free(p);
  return yes;
}

dawn_str dawn_io_read_file(dawn_str path) {
  char *p = dawn_cpath(path);
  FILE *f = fopen(p, "rb");
  free(p);
  if (f == NULL) {
    dawn_panic(dawn_str_lit("io_read_file: cannot open file", 30));
  }
  size_t cap = 4096;
  size_t n = 0;
  char *buf = (char *)dawn_alloc(cap);
  for (;;) {
    if (n == cap) {
      char *bigger = (char *)dawn_alloc(cap * 2);
      memcpy(bigger, buf, n);
      free(buf);
      buf = bigger;
      cap *= 2;
    }
    size_t got = fread(buf + n, 1, cap - n, f);
    n += got;
    if (got == 0) break;
  }
  bool bad = ferror(f) != 0;
  fclose(f);
  if (bad) {
    dawn_panic(dawn_str_lit("io_read_file: read failed", 25));
  }
  return (dawn_str){buf, (int64_t)n};
}

dawn_unit dawn_io_write_file(dawn_str path, dawn_str content) {
  char *p = dawn_cpath(path);
  FILE *f = fopen(p, "wb");
  free(p);
  if (f == NULL) {
    dawn_panic(dawn_str_lit("io_write_file: cannot open file", 31));
  }
  bool bad = content.len > 0 &&
             fwrite(content.p, 1, (size_t)content.len, f) != (size_t)content.len;
  if (fclose(f) != 0) bad = true;
  if (bad) {
    dawn_panic(dawn_str_lit("io_write_file: write failed", 27));
  }
  return DAWN_UNIT;
}

dawn_array *dawn_io_list_names(dawn_str path) {
  char *p = dawn_cpath(path);
  DIR *d = opendir(p);
  free(p);
  if (d == NULL) {
    dawn_panic(dawn_str_lit("io_list_names: cannot open directory", 36));
  }
  dawn_array *a = dawn_array_new();
  struct dirent *e = readdir(d);
  while (e != NULL) {
    if (strcmp(e->d_name, ".") != 0 && strcmp(e->d_name, "..") != 0) {
      size_t n = strlen(e->d_name);
      a = dawn_array_push(a, dawn_box_str(dawn_str_copy(e->d_name, n)));
    }
    e = readdir(d);
  }
  closedir(d);
  return a;
}

dawn_array *dawn_args(void) {
  /* argv[0] is the program, which `args` does not include -- the JVM backend
   * gets the same list from main's parameter. */
  dawn_array *a = dawn_array_new();
  for (int i = 1; i < dawn_argc; i++) {
    a = dawn_array_push(a, dawn_box_str(dawn_str_copy(dawn_argv[i], strlen(dawn_argv[i]))));
  }
  return a;
}
