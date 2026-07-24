/* See dawn_rt.h. Phase -1 scope only. */
#include "dawn_rt.h"

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
