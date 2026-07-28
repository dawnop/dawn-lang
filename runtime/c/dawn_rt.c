/* See dawn_rt.h. Phase -1 scope only. */

/* stat/opendir/readdir are POSIX, and -std=c11 hides them without this. */
#define _POSIX_C_SOURCE 200809L

#include "dawn_rt.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <setjmp.h>
#include <spawn.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

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

/* stdout is block-buffered here (dawn_rt_init) and stderr is not, so the two
 * would interleave in the wrong order if a program used both. Flushing stdout
 * before writing stderr is what System.err's autoflush gets for free. */
dawn_unit dawn_io_eprint(dawn_str s) {
  fflush(stdout);
  if (s.len > 0) {
    fwrite(s.p, 1, (size_t)s.len, stderr);
  }
  return DAWN_UNIT;
}

dawn_unit dawn_io_eprintln(dawn_str s) {
  dawn_io_eprint(s);
  fputc('\n', stderr);
  return DAWN_UNIT;
}

dawn_unit dawn_io_exit(int64_t code) {
  /* exit() flushes stdio, which the block buffering above makes load-bearing */
  exit((int)code);
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

int64_t dawn_hash_bytes(const dawn_bytes *b) {
  /* java.util.Arrays.hashCode(byte[]): seed 1, h = 31*h + element, and the
   * element is a *signed* byte there. The same fold the structural hash of a
   * tuple or a union runs, so the one Dawn spells out and the one the runtime
   * owns are the same shape. */
  int32_t h = 1;
  for (int64_t i = 0; i < b->len; i++) {
    h = (int32_t)((uint32_t)h * 31u + (uint32_t)(int32_t)(int8_t)b->p[i]);
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

/* ---- failures, and the two barriers that stop them ----------------------
 *
 * A failure has a kind, and the kind decides which barrier stops it:
 *
 *   panic   the language's own -- `panic`, `expect`, a bad index, division by
 *           zero. A broken invariant inside the program. Only `catch_panic`.
 *   fault   the outside world said no: an io primitive failed. Both barriers,
 *           and `catch_fault` is *for* this one -- it is how std/io turns a
 *           missing file into a `Result`.
 *
 * The JVM gets the same split from its class hierarchy for free -- `panic`
 * throws an `Error` and `catch_fault` catches `Exception` -- so this is not a
 * native invention, it is native catching up. Both intrinsics were literally
 * this same function until 2026-07-28, which made the io barrier swallow the
 * panics the JVM lets through; scripts/spike-native/catch_kinds.dawn is the
 * corpus that asked.
 *
 * A handler is a frame on this stack. A raise walks to the innermost handler
 * that will take its kind -- skipping io barriers when a panic passes through
 * them -- or reports and exits when there is none. */
typedef struct dawn_handler {
  jmp_buf jb;
  struct dawn_handler *prev;
  bool catches_panic;
} dawn_handler;

static dawn_handler *dawn_handlers;
static dawn_str dawn_failure_msg;

static void dawn_raise(dawn_str msg, bool is_panic) {
  dawn_handler *h = dawn_handlers;
  while (h != NULL && is_panic && !h->catches_panic) h = h->prev;
  if (h != NULL) {
    /* The skipped frames go with it: they sit above `h`, and `h`'s own
     * setjmp branch restores the list to `h->prev`. */
    dawn_failure_msg = msg;
    longjmp(h->jb, 1);
  }
  /* Nothing stopped it, so the program is over either way -- which is why
   * both kinds report under the same word. */
  fflush(stdout);
  fputs("panic: ", stderr);
  if (msg.len > 0) fwrite(msg.p, 1, (size_t)msg.len, stderr);
  fputc('\n', stderr);
  exit(1);
}

void dawn_panic(dawn_str msg) { dawn_raise(msg, true); }

void dawn_fault(dawn_str msg) { dawn_raise(msg, false); }

/* The closure returns an erased slot whatever `T` is, so one cast covers
 * every instantiation -- see the header. */
static dawn_adt *dawn_run_caught(dawn_clo *f, bool catches_panic) {
  dawn_handler h;
  h.prev = dawn_handlers;
  h.catches_panic = catches_panic;
  dawn_handlers = &h;
  if (setjmp(h.jb) != 0) {
    dawn_handlers = h.prev;
    return dawn_err(dawn_box_str(dawn_failure_msg));
  }
  void *v = ((void *(*)(dawn_clo *))f->fn)(f);
  dawn_handlers = h.prev;
  return dawn_ok(v);
}

dawn_adt *dawn_catch_fault(dawn_clo *f) { return dawn_run_caught(f, false); }

dawn_adt *dawn_catch_panic(dawn_clo *f) { return dawn_run_caught(f, true); }

/* ---- code-point classification (char_is_*) ---------------------------- */

/* Membership in a sorted, disjoint set of ranges (dawn_rt.h). Out-of-range and
 * negative inputs fall out as false, which is the answer: the intrinsic takes
 * an Int and nothing says it is a code point. */
static bool dawn_cp_in(int64_t c, const dawn_cp_range *rs, size_t n) {
  size_t lo = 0, hi = n;
  while (lo < hi) {
    size_t mid = lo + (hi - lo) / 2;
    if (c < rs[mid].lo) {
      hi = mid;
    } else if (c > rs[mid].hi) {
      lo = mid + 1;
    } else {
      return true;
    }
  }
  return false;
}

bool dawn_char_is_letter(int64_t c) {
  return dawn_cp_in(c, dawn_letter_ranges, (size_t)dawn_letter_ranges_n);
}

bool dawn_char_is_digit(int64_t c) {
  return dawn_cp_in(c, dawn_digit_ranges, (size_t)dawn_digit_ranges_n);
}

/* Not a table of its own: Java defines isLetterOrDigit this way, so a third
 * set would be a third thing to keep in agreement with the other two. */
bool dawn_char_is_alnum(int64_t c) {
  return dawn_char_is_letter(c) || dawn_char_is_digit(c);
}

bool dawn_char_is_upper(int64_t c) {
  return dawn_cp_in(c, dawn_upper_class_ranges, (size_t)dawn_upper_class_ranges_n);
}

bool dawn_char_is_lower(int64_t c) {
  return dawn_cp_in(c, dawn_lower_class_ranges, (size_t)dawn_lower_class_ranges_n);
}

/* Whitespace is the one set small enough that it used to be written out here
 * by hand, and the hand-written version was right -- but it was a second
 * definition, and being right is a property that has to be maintained rather
 * than one that holds. U+00A0, U+2007 and U+202F are separators and are *not*
 * whitespace, which is the part that surprises; the table says so. */
bool dawn_char_is_space(int64_t c) {
  return dawn_cp_in(c, dawn_space_ranges, (size_t)dawn_space_ranges_n);
}

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

dawn_str dawn_cursor_slice(dawn_str s, int64_t from, int64_t to) {
  if (from < 0 || to > s.len || from > to ||
      !dawn_utf8_boundary(s, from) || !dawn_utf8_boundary(s, to)) {
    dawn_panic(dawn_str_lit("cursor_slice: invalid cursor range", 34));
  }
  return (dawn_str){s.p + from, to - from};
}

/* ---- the str_* primitives ---- */

/* Only `parse_int`'s leading/trailing strip uses this now; the language's
 * `str.trim` is a cursor walk in std/str (native-backend-plan.md 14.12). */
static dawn_str dawn_str_trim(dawn_str s) {
  int64_t a = 0;
  while (a < s.len) {
    int64_t n;
    if (!dawn_char_is_space((int64_t)dawn_utf8_at(s, a, &n))) break;
    a += n;
  }
  int64_t b = s.len;
  while (b > a) {
    int64_t prev = dawn_cursor_prev(s, b);
    int64_t n;
    if (!dawn_char_is_space((int64_t)dawn_utf8_at(s, prev, &n))) break;
    b = prev;
  }
  return (dawn_str){s.p + a, b - a};
}

/* Simple (1:1) Unicode case mapping, out of the table the generated program
 * carries (dawn_rt.h, selfhost/src/case_table.dawn). The JVM backend decodes
 * the same rows into dawn/rt/Strings, so the two backends are two
 * implementations of one mapping rather than two mappings
 * (native-backend-plan.md 14.12). scripts/unicode-contract/run.sh checks the
 * compiled result against the table, and the table against the JDK it was
 * generated from.
 *
 * This folded ASCII only until 2026-07-28, so every cased letter above U+007F
 * came back unchanged where the JVM folded it -- the one place a program could
 * see the backends differ with no panic saying so, and a `const` folded the
 * JVM's answer into a native binary. */
static int32_t dawn_case_cp(int32_t cp, const dawn_case_range *rs, size_t n) {
  size_t lo = 0, hi = n;
  while (lo < hi) {
    size_t mid = lo + (hi - lo) / 2;
    if (cp < rs[mid].lo) {
      hi = mid;
    } else if (cp > rs[mid].hi) {
      lo = mid + 1;
    } else {
      return cp + rs[mid].delta;
    }
  }
  return cp;
}

/* Two passes: a mapped code point can be wider or narrower than the one it
 * replaces (U+0131 is two bytes and maps to one-byte `I`), so the output
 * length is not the input's and is not worth over-allocating four bytes a
 * character for. */
static dawn_str dawn_case(dawn_str s, bool up) {
  const dawn_case_range *rs = up ? dawn_upper_ranges : dawn_lower_ranges;
  size_t rn = (size_t)(up ? dawn_upper_ranges_n : dawn_lower_ranges_n);
  int64_t out = 0;
  for (int64_t i = 0; i < s.len;) {
    int64_t n;
    uint32_t cp = dawn_utf8_at(s, i, &n);
    char scratch[4];
    out += dawn_utf8_put(scratch, (uint32_t)dawn_case_cp((int32_t)cp, rs, rn));
    i += n;
  }
  char *buf = (char *)dawn_alloc((size_t)out + 1);
  int64_t at = 0;
  for (int64_t i = 0; i < s.len;) {
    int64_t n;
    uint32_t cp = dawn_utf8_at(s, i, &n);
    at += dawn_utf8_put(buf + at, (uint32_t)dawn_case_cp((int32_t)cp, rs, rn));
    i += n;
  }
  return (dawn_str){buf, at};
}

dawn_str dawn_str_lower(dawn_str s) { return dawn_case(s, false); }

dawn_str dawn_str_upper(dawn_str s) { return dawn_case(s, true); }

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
  /* `start > end` yields empty, which is what std/bytes.slice documents and
   * what the JVM's bytes_clamp path does. This panicked instead until
   * 2026-07-28 -- under this very comment. */
  if (from > to) to = from;
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

dawn_bytes *dawn_bytes_from_array(const dawn_array *a) {
  int64_t n = dawn_array_len(a);
  unsigned char *buf = (unsigned char *)dawn_alloc((size_t)n + 1);
  for (int64_t i = 0; i < n; i++) {
    dawn_slot *s = (dawn_slot *)dawn_array_get(a, i);
    buf[i] = (unsigned char)(s->i & 0xFF);
  }
  return dawn_bytes_of(buf, n);
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

/* `mkdir -p` over the *parent* of `p`. The JVM side spells this
 * getParentFile().mkdirs() inside io_write_file, and this side did not, so a
 * write into a directory that did not exist yet failed on one backend only.
 * Both write primitives go through it now. */
static void dawn_mkparents(const char *p) {
  size_t n = strlen(p);
  size_t cut = 0;
  for (size_t i = 0; i < n; i++) {
    if (p[i] == '/') cut = i;
  }
  if (cut == 0) return;
  char *dir = (char *)dawn_alloc(cut + 1);
  memcpy(dir, p, cut);
  dir[cut] = '\0';
  for (size_t i = 1; i <= cut; i++) {
    if (i != cut && dir[i] != '/') continue;
    char saved = dir[i];
    dir[i] = '\0';
    mkdir(dir, 0777); /* an existing directory is fine; fopen reports the rest */
    dir[i] = saved;
  }
  free(dir);
}

/* Read all of `f` into a fresh buffer. Shared by read_file and read_bytes,
 * which differ only in what they wrap the result in. */
static unsigned char *dawn_slurp(FILE *f, size_t *out_len, bool *out_bad) {
  size_t cap = 4096;
  size_t n = 0;
  unsigned char *buf = (unsigned char *)dawn_alloc(cap);
  for (;;) {
    if (n == cap) {
      unsigned char *bigger = (unsigned char *)dawn_alloc(cap * 2);
      memcpy(bigger, buf, n);
      free(buf);
      buf = bigger;
      cap *= 2;
    }
    size_t got = fread(buf + n, 1, cap - n, f);
    n += got;
    if (got == 0) break;
  }
  *out_bad = ferror(f) != 0;
  *out_len = n;
  return buf;
}

bool dawn_io_is_dir(dawn_str path) {
  char *p = dawn_cpath(path);
  struct stat st;
  bool yes = stat(p, &st) == 0 && S_ISDIR(st.st_mode);
  free(p);
  return yes;
}

bool dawn_io_exists(dawn_str path) {
  char *p = dawn_cpath(path);
  struct stat st;
  bool yes = stat(p, &st) == 0;
  free(p);
  return yes;
}

/* Every prefix of the path, `mkdir -p` style. An existing directory is not a
 * failure; an existing *file* is, which is what Files.createDirectories does
 * and File.mkdirs does not. */
dawn_unit dawn_io_mkdirs(dawn_str path) {
  char *p = dawn_cpath(path);
  for (int64_t i = 1; i <= path.len; i++) {
    if (i != path.len && p[i] != '/') continue;
    char saved = p[i];
    p[i] = '\0';
    struct stat st;
    if (stat(p, &st) == 0) {
      if (!S_ISDIR(st.st_mode)) {
        free(p);
        dawn_fault(dawn_str_lit("io_mkdirs: path exists and is not a directory", 44));
      }
    } else if (mkdir(p, 0777) != 0) {
      free(p);
      dawn_fault(dawn_str_lit("io_mkdirs: cannot create directory", 34));
    }
    p[i] = saved;
  }
  free(p);
  return DAWN_UNIT;
}

dawn_str dawn_io_read_file(dawn_str path) {
  char *p = dawn_cpath(path);
  FILE *f = fopen(p, "rb");
  free(p);
  if (f == NULL) {
    dawn_fault(dawn_str_lit("io_read_file: cannot open file", 30));
  }
  size_t n = 0;
  bool bad = false;
  unsigned char *buf = dawn_slurp(f, &n, &bad);
  fclose(f);
  if (bad) {
    dawn_fault(dawn_str_lit("io_read_file: read failed", 25));
  }
  return (dawn_str){(const char *)buf, (int64_t)n};
}

dawn_unit dawn_io_write_file(dawn_str path, dawn_str content) {
  char *p = dawn_cpath(path);
  dawn_mkparents(p);
  FILE *f = fopen(p, "wb");
  free(p);
  if (f == NULL) {
    dawn_fault(dawn_str_lit("io_write_file: cannot open file", 31));
  }
  bool bad = content.len > 0 &&
             fwrite(content.p, 1, (size_t)content.len, f) != (size_t)content.len;
  if (fclose(f) != 0) bad = true;
  if (bad) {
    dawn_fault(dawn_str_lit("io_write_file: write failed", 27));
  }
  return DAWN_UNIT;
}

dawn_array *dawn_io_list_names(dawn_str path) {
  char *p = dawn_cpath(path);
  DIR *d = opendir(p);
  free(p);
  if (d == NULL) {
    dawn_fault(dawn_str_lit("io_list_names: cannot open directory", 36));
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

dawn_str dawn_io_cwd(void) {
  size_t cap = 1024;
  for (;;) {
    char *buf = (char *)dawn_alloc(cap);
    if (getcwd(buf, cap) != NULL) {
      dawn_str s = dawn_str_copy(buf, strlen(buf));
      free(buf);
      return s;
    }
    free(buf);
    if (errno != ERANGE) {
      dawn_fault(dawn_str_lit("io_cwd: cannot read the working directory", 40));
    }
    cap *= 2;
  }
}

dawn_adt *dawn_io_getenv(dawn_str name) {
  char *p = dawn_cpath(name);
  const char *v = getenv(p);
  free(p);
  if (v == NULL) return dawn_none();
  return dawn_some(dawn_box_str(dawn_str_copy(v, strlen(v))));
}

dawn_bytes *dawn_io_read_bytes(dawn_str path) {
  char *p = dawn_cpath(path);
  FILE *f = fopen(p, "rb");
  free(p);
  if (f == NULL) {
    dawn_fault(dawn_str_lit("io_read_bytes: cannot open file", 31));
  }
  size_t n = 0;
  bool bad = false;
  unsigned char *buf = dawn_slurp(f, &n, &bad);
  fclose(f);
  if (bad) {
    dawn_fault(dawn_str_lit("io_read_bytes: read failed", 26));
  }
  return dawn_bytes_of(buf, (int64_t)n);
}

dawn_unit dawn_io_write_bytes(dawn_str path, const dawn_bytes *content) {
  char *p = dawn_cpath(path);
  dawn_mkparents(p);
  FILE *f = fopen(p, "wb");
  free(p);
  if (f == NULL) {
    dawn_fault(dawn_str_lit("io_write_bytes: cannot open file", 32));
  }
  bool bad = content->len > 0 &&
             fwrite(content->p, 1, (size_t)content->len, f) != (size_t)content->len;
  if (fclose(f) != 0) bad = true;
  if (bad) {
    dawn_fault(dawn_str_lit("io_write_bytes: write failed", 28));
  }
  return DAWN_UNIT;
}

/* remove(3) takes both files and empty directories, which is what File.delete
 * does; a non-empty directory fails on both sides rather than recursing. */
bool dawn_io_delete(dawn_str path) {
  char *p = dawn_cpath(path);
  bool gone = remove(p) == 0;
  free(p);
  return gone;
}

dawn_unit dawn_io_rename(dawn_str src, dawn_str dst) {
  char *a = dawn_cpath(src);
  char *b = dawn_cpath(dst);
  bool bad = rename(a, b) != 0;
  free(a);
  free(b);
  if (bad) {
    dawn_fault(dawn_str_lit("io_rename: cannot rename (not one filesystem?)", 45));
  }
  return DAWN_UNIT;
}

dawn_str dawn_io_temp_dir(dawn_str parent, dawn_str prefix) {
  char *pbuf = NULL;
  const char *base;
  if (parent.len == 0) {
    base = getenv("TMPDIR");
    if (base == NULL || base[0] == '\0') base = "/tmp";
  } else {
    pbuf = dawn_cpath(parent);
    base = pbuf;
  }
  char *pre = dawn_cpath(prefix);
  size_t bl = strlen(base);
  size_t pl = strlen(pre);
  char *tmpl = (char *)dawn_alloc(bl + 1 + pl + 7);
  memcpy(tmpl, base, bl);
  tmpl[bl] = '/';
  memcpy(tmpl + bl + 1, pre, pl);
  memcpy(tmpl + bl + 1 + pl, "XXXXXX", 7); /* the NUL rides along */
  free(pre);
  free(pbuf);
  if (mkdtemp(tmpl) == NULL) {
    free(tmpl);
    dawn_fault(dawn_str_lit("io_temp_dir: cannot create a temporary directory", 47));
  }
  dawn_str s = dawn_str_copy(tmpl, strlen(tmpl));
  free(tmpl);
  return s;
}

bool dawn_io_is_symlink(dawn_str path) {
  char *p = dawn_cpath(path);
  struct stat st;
  bool yes = lstat(p, &st) == 0 && S_ISLNK(st.st_mode);
  free(p);
  return yes;
}

dawn_bytes *dawn_io_read_stdin(int64_t n) {
  if (n <= 0) return dawn_bytes_of((const unsigned char *)"", 0);
  unsigned char *buf = (unsigned char *)dawn_alloc((size_t)n);
  size_t got = 0;
  while (got < (size_t)n) {
    size_t step = fread(buf + got, 1, (size_t)n - got, stdin);
    if (step == 0) break; /* end of input, or an error the caller sees as one */
    got += step;
  }
  return dawn_bytes_of(buf, (int64_t)got);
}

/* Spawn and wait. `posix_spawnp` rather than fork+exec: fork duplicates the
 * whole address space only to throw it away, and this runs inside a compiler.
 * Redirection is a file action for the same reason the signature takes paths
 * at all -- see the note on `io_run` in types.dawn. */
extern char **environ;

int64_t dawn_io_run(dawn_array *argv, dawn_str out_path, dawn_str err_path) {
  int64_t n = dawn_array_len(argv);
  if (n <= 0) {
    dawn_fault(dawn_str_lit("io_run: argv is empty", 21));
  }
  char **args = (char **)dawn_alloc(sizeof(char *) * (size_t)(n + 1));
  for (int64_t i = 0; i < n; i++) {
    args[i] = dawn_cpath(((dawn_slot *)dawn_array_get(argv, i))->s);
  }
  args[n] = NULL;

  posix_spawn_file_actions_t fa;
  posix_spawn_file_actions_init(&fa);
  char *op = NULL;
  char *ep = NULL;
  if (out_path.len > 0) {
    op = dawn_cpath(out_path);
    posix_spawn_file_actions_addopen(&fa, 1, op, O_WRONLY | O_CREAT | O_TRUNC, 0644);
  }
  if (err_path.len > 0) {
    ep = dawn_cpath(err_path);
    posix_spawn_file_actions_addopen(&fa, 2, ep, O_WRONLY | O_CREAT | O_TRUNC, 0644);
  }
  pid_t pid = 0;
  int rc = posix_spawnp(&pid, args[0], &fa, NULL, args, environ);
  posix_spawn_file_actions_destroy(&fa);
  free(op);
  free(ep);
  for (int64_t i = 0; i < n; i++) free(args[i]);
  free(args);
  if (rc != 0) {
    dawn_fault(dawn_str_lit("io_run: cannot start the program", 32));
  }
  int status = 0;
  while (waitpid(pid, &status, 0) < 0) {
    if (errno != EINTR) {
      dawn_fault(dawn_str_lit("io_run: waiting for the child failed", 36));
    }
  }
  /* The two numbers the JVM's Process.exitValue() also reports on POSIX. */
  if (WIFEXITED(status)) return (int64_t)WEXITSTATUS(status);
  if (WIFSIGNALED(status)) return (int64_t)(128 + WTERMSIG(status));
  return -1;
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
