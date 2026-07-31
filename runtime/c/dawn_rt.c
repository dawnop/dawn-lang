/* See dawn_rt.h. Phase -1 scope only. */

/* stat/opendir/readdir are POSIX, and -std=c11 hides them without this. */
#define _POSIX_C_SOURCE 200809L

#include "dawn_rt.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
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

/* Stderr, so a differential run comparing stdout byte for byte stays clean
 * even with the stats on. */
static void dawn_rc_stats_dump(void) {
  fprintf(stderr, "rc-stats: array_with in-place %llu, copied %llu\n",
          (unsigned long long)dawn_array_with_inplace,
          (unsigned long long)dawn_array_with_copied);
}

void dawn_rt_init(int argc, char **argv) {
  dawn_argc = argc;
  dawn_argv = argv;
  /* stdout is compared byte for byte against the JVM backend by the
   * differential harness, so it must not be reordered by buffering
   * when stdout is a pipe and stderr is not. */
  setvbuf(stdout, NULL, _IOFBF, 1 << 16);
  /* Read at run time rather than compiled in, so one binary can be run both
   * ways. Rebuilding to switch would change the layout, which is the variable
   * the mode exists to hold still (plan 6 R3). */
  dawn_rc_leak = getenv("DAWN_RC_LEAK") != NULL;
  if (getenv("DAWN_RC_STATS") != NULL) {
    atexit(dawn_rc_stats_dump);
  }
}

/* See dawn_rt.h: the entry point runs on a DAWN_STACK_BYTES stack, not on
 * whatever the OS gave the main thread. Held in a static because casting an
 * object pointer to a function pointer is not conforming C, only POSIX. */
static void (*dawn_entry_fn)(void);

static void *dawn_stack_thread(void *unused) {
  (void)unused;
  dawn_entry_fn();
  return NULL;
}

int dawn_rt_main(int argc, char **argv, void (*entry)(void)) {
  pthread_attr_t at;
  pthread_t th;
  dawn_rt_init(argc, argv);
  dawn_entry_fn = entry;
  if (pthread_attr_init(&at) == 0) {
    int ok = pthread_attr_setstacksize(&at, DAWN_STACK_BYTES) == 0 &&
             pthread_create(&th, &at, dawn_stack_thread, NULL) == 0;
    pthread_attr_destroy(&at);
    if (ok) {
      pthread_join(th, NULL);
      return 0;
    }
  }
  /* Run anyway rather than refuse to start -- but say so, because the whole
   * point of the big stack is that the failure it prevents is silent. */
  fputs("dawn: no big stack; deep recursion may crash without a message\n",
        stderr);
  entry();
  return 0;
}

static void *dawn_alloc(size_t n) {
  void *p = malloc(n);
  if (p == NULL) {
    fputs("dawn: out of memory\n", stderr);
    exit(1);
  }
  return p;
}

/* Every heap object is born with one reference: the one the caller is holding
 * when the constructor returns. */
static void dawn_hdr_init(dawn_hdr *h, int32_t kind) {
  h->rc = 1;
  h->kind = kind;
}

dawn_str dawn_str_empty_obj = {{DAWN_IMMORTAL, DAWN_K_STR}, 0, ""};

dawn_str *dawn_str_new(int64_t len) {
  dawn_str *s = (dawn_str *)dawn_alloc(sizeof(dawn_str) + (size_t)len + 1);
  dawn_hdr_init(&s->h, DAWN_K_STR);
  s->len = len;
  s->p = (const char *)(s + 1);
  /* not part of the value (len is authoritative); a convenience for the seams
   * that hand `p` to the C library */
  ((char *)(s + 1))[len] = '\0';
  return s;
}

dawn_str *dawn_str_copy(const char *p, int64_t n) {
  dawn_str *s = dawn_str_new(n);
  if (n > 0) memcpy(dawn_str_data(s), p, (size_t)n);
  return s;
}

/* Trim a just-built string to its measured length, for the producers whose
 * worst case is known but whose exact size is not worth a second pass. The
 * block may move, so only the builder's own reference may exist yet. */
static dawn_str *dawn_str_shrink(dawn_str *s, int64_t len) {
  dawn_str *r = (dawn_str *)realloc(s, sizeof(dawn_str) + (size_t)len + 1);
  if (r == NULL) {
    fputs("dawn: out of memory\n", stderr);
    exit(1);
  }
  r->len = len;
  r->p = (const char *)(r + 1);
  ((char *)(r + 1))[len] = '\0';
  return r;
}

dawn_adt *dawn_adt_new(int32_t tag, int32_t nfields, uint64_t mask) {
  dawn_adt *a =
      (dawn_adt *)dawn_alloc(sizeof(dawn_adt) + (size_t)nfields * sizeof(dawn_slot));
  dawn_hdr_init(&a->h, DAWN_K_ADT);
  a->tag = tag;
  a->nfields = nfields;
  a->ptrmask.narrow = mask;
  return a;
}

dawn_adt *dawn_adt_new_wide(int32_t tag, int32_t nfields, const uint64_t *mask) {
  dawn_adt *a =
      (dawn_adt *)dawn_alloc(sizeof(dawn_adt) + (size_t)nfields * sizeof(dawn_slot));
  dawn_hdr_init(&a->h, DAWN_K_ADT);
  a->tag = tag;
  a->nfields = nfields;
  a->ptrmask.wide = mask;
  return a;
}

dawn_clo *dawn_clo_new(void *fn, int32_t ncap, uint64_t mask) {
  dawn_clo *c =
      (dawn_clo *)dawn_alloc(sizeof(dawn_clo) + (size_t)ncap * sizeof(dawn_slot));
  dawn_hdr_init(&c->h, DAWN_K_CLO);
  c->fn = fn;
  c->ncap = ncap;
  c->capmask.narrow = mask;
  return c;
}

dawn_clo *dawn_clo_new_wide(void *fn, int32_t ncap, const uint64_t *mask) {
  dawn_clo *c =
      (dawn_clo *)dawn_alloc(sizeof(dawn_clo) + (size_t)ncap * sizeof(dawn_slot));
  dawn_hdr_init(&c->h, DAWN_K_CLO);
  c->fn = fn;
  c->ncap = ncap;
  c->capmask.wide = mask;
  return c;
}

/* Dictionaries are outside reference counting by design (perceus-design.md
 * 3): no header, never freed. An argument-carrying dictionary is built here
 * at run time and lives forever, so LeakSanitizer is told it is owned --
 * without this, leak detection on the corpus (the whole point of counting
 * strings) would drown in reports about a decided design. */
#ifdef __SANITIZE_ADDRESS__
#include <sanitizer/lsan_interface.h>
#define DAWN_LSAN_OWN(p) __lsan_ignore_object(p)
#elif defined(__has_feature)
#if __has_feature(address_sanitizer)
#include <sanitizer/lsan_interface.h>
#define DAWN_LSAN_OWN(p) __lsan_ignore_object(p)
#else
#define DAWN_LSAN_OWN(p) ((void)0)
#endif
#else
#define DAWN_LSAN_OWN(p) ((void)0)
#endif

dawn_dict *dawn_dict_new(const dawn_dict *tmpl, int32_t nargs, ...) {
  dawn_dict *d = (dawn_dict *)dawn_alloc(sizeof(dawn_dict));
  DAWN_LSAN_OWN(d);
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

static dawn_box *dawn_box_new(void) {
  dawn_box *b = (dawn_box *)dawn_alloc(sizeof(dawn_box));
  dawn_hdr_init(&b->h, DAWN_K_BOX);
  return b;
}

dawn_box *dawn_box_int(int64_t v) {
  dawn_box *s = dawn_box_new();
  s->val.i = v;
  return s;
}

dawn_box *dawn_box_float(double v) {
  dawn_box *s = dawn_box_new();
  s->val.f = v;
  return s;
}

dawn_box *dawn_box_bool(bool v) {
  dawn_box *s = dawn_box_new();
  s->val.b = v;
  return s;
}

dawn_box *dawn_box_unit(dawn_unit v) {
  dawn_box *s = dawn_box_new();
  s->val.u = v;
  return s;
}


/* Read a box out and release it in one move. These are for the one place a
 * box exists that no Core node owns: the erased call boundary. A dynamic
 * call's adapter boxes its scalar result for the caller, and the caller boxes
 * scalar arguments for the adapter -- in both directions the box is invisible
 * to the RC pass (it sees a call typed Int, not the void* underneath), so the
 * reader is the only party who can free it. Slot reads the pass CAN see
 * (CUnbox of an ADT field) borrow instead and must not come through here. */
int64_t dawn_unbox_int(void *b) {
  int64_t v = ((dawn_box *)b)->val.i;
  dawn_drop(b);
  return v;
}

double dawn_unbox_float(void *b) {
  double v = ((dawn_box *)b)->val.f;
  dawn_drop(b);
  return v;
}

bool dawn_unbox_bool(void *b) {
  bool v = ((dawn_box *)b)->val.b;
  dawn_drop(b);
  return v;
}

dawn_unit dawn_unbox_unit(void *b) {
  dawn_unit v = ((dawn_box *)b)->val.u;
  dawn_drop(b);
  return v;
}


/* ---- reference counting (docs/perceus-design.md) ---- */

bool dawn_rc_leak = false;

void *dawn_dup(void *p) {
  if (p == NULL) {
    return p;
  }
  dawn_hdr *h = (dawn_hdr *)p;
  if (h->rc != DAWN_IMMORTAL) {
    h->rc++;
  }
  return p;
}

bool dawn_is_unique(const void *p) {
  return p != NULL && ((const dawn_hdr *)p)->rc == 1;
}

/* Bit i of a field mask. Narrow masks live in the object; wider ones point at
 * a static array the emitter wrote, and 64 is the discriminator. */
static bool dawn_mask_bit(const dawn_mask *m, int32_t n, int32_t i) {
  if (n <= 64) {
    return ((m->narrow >> (unsigned)i) & UINT64_C(1)) != 0;
  }
  return ((m->wide[i >> 6] >> (unsigned)(i & 63)) & UINT64_C(1)) != 0;
}

/* The work list `dawn_drop` walks instead of recursing. It starts on the C
 * stack and only reaches the heap for structures deeper than 32 -- which a
 * persistent vector or a HAMT certainly is, and which C recursion certainly
 * cannot take at the sizes std reaches. */
#define DAWN_WS_INLINE 32

typedef struct {
  void **items;
  size_t len;
  size_t cap;
  void *inline_items[DAWN_WS_INLINE];
} dawn_ws;

static void dawn_ws_init(dawn_ws *s) {
  s->items = s->inline_items;
  s->len = 0;
  s->cap = DAWN_WS_INLINE;
}

static void dawn_ws_push(dawn_ws *s, void *p) {
  if (p == NULL) {
    return;
  }
  if (s->len == s->cap) {
    size_t cap = s->cap * 2;
    void **grown = (void **)dawn_alloc(cap * sizeof(void *));
    memcpy(grown, s->items, s->len * sizeof(void *));
    if (s->items != s->inline_items) {
      free(s->items);
    }
    s->items = grown;
    s->cap = cap;
  }
  s->items[s->len++] = p;
}

static void dawn_ws_free(dawn_ws *s) {
  if (s->items != s->inline_items) {
    free(s->items);
  }
}

void dawn_drop(void *p) {
  if (dawn_rc_leak || p == NULL) {
    return;
  }
  dawn_ws s;
  dawn_ws_init(&s);
  dawn_ws_push(&s, p);
  while (s.len > 0) {
    void *q = s.items[--s.len];
    dawn_hdr *h = (dawn_hdr *)q;
    if (h->rc == DAWN_IMMORTAL) {
      continue;
    }
    if (h->rc <= 0) {
      fprintf(stderr, "dawn: drop of a value with rc=%d (kind %d)\n", h->rc, h->kind);
      exit(1);
    }
    if (--h->rc > 0) {
      continue;
    }
    switch (h->kind) {
      case DAWN_K_ADT: {
        dawn_adt *a = (dawn_adt *)q;
        for (int32_t i = 0; i < a->nfields; i++) {
          if (dawn_mask_bit(&a->ptrmask, a->nfields, i)) {
            dawn_ws_push(&s, a->fields[i].p);
          }
        }
        break;
      }
      case DAWN_K_CLO: {
        dawn_clo *c = (dawn_clo *)q;
        for (int32_t i = 0; i < c->ncap; i++) {
          if (dawn_mask_bit(&c->capmask, c->ncap, i)) {
            dawn_ws_push(&s, c->caps[i].p);
          }
        }
        break;
      }
      case DAWN_K_ARRAY:
        dawn_ws_push(&s, ((dawn_array *)q)->buf);
        break;
      case DAWN_K_ARRAY_BUF: {
        /* to `high`, not `len`: `len` is one version's length, `high` is every
         * slot this buffer ever handed out, which is what it actually holds */
        dawn_array_buf *b = (dawn_array_buf *)q;
        for (int32_t i = 0; i < b->high; i++) {
          dawn_ws_push(&s, b->data[i]);
        }
        free(b->data);
        break;
      }
      case DAWN_K_BOX:
        break; /* a scalar; a reference never went through a box */
      case DAWN_K_BYTES:
        /* every constructor allocates the buffer fresh, so it goes with the
         * struct -- the leaked-by-contract era ended with counted strings */
        free((void *)((dawn_bytes *)q)->p);
        break;
      case DAWN_K_STR:
        break; /* one block: the bytes sit right after the header */
      default:
        fprintf(stderr, "dawn: drop of an unheaded pointer (kind %d)\n", h->kind);
        exit(1);
    }
    free(q);
  }
  dawn_ws_free(&s);
}

/* The prelude's own constructors: one erased field, so bit 0 of the mask. */
#define DAWN_MASK_ONE_BOXED UINT64_C(1)

dawn_adt *dawn_some(void *boxed) {
  dawn_adt *a = dawn_adt_new(DAWN_TAG_SOME, 1, DAWN_MASK_ONE_BOXED);
  a->fields[0].p = boxed;
  return a;
}

dawn_adt *dawn_none(void) { return dawn_adt_new(DAWN_TAG_NONE, 0, 0); }

static dawn_adt *dawn_ok(void *boxed) {
  dawn_adt *a = dawn_adt_new(DAWN_TAG_OK, 1, DAWN_MASK_ONE_BOXED);
  a->fields[0].p = boxed;
  return a;
}

static dawn_adt *dawn_err(void *boxed) {
  dawn_adt *a = dawn_adt_new(DAWN_TAG_ERR, 1, DAWN_MASK_ONE_BOXED);
  a->fields[0].p = boxed;
  return a;
}

dawn_unit dawn_io_print(dawn_str *s) {
  if (s->len > 0) {
    fwrite(s->p, 1, (size_t)s->len, stdout);
  }
  return DAWN_UNIT;
}

dawn_unit dawn_io_println(dawn_str *s) {
  dawn_io_print(s);
  fputc('\n', stdout);
  return DAWN_UNIT;
}

/* stdout is block-buffered here (dawn_rt_init) and stderr is not, so the two
 * would interleave in the wrong order if a program used both. Flushing stdout
 * before writing stderr is what System.err's autoflush gets for free. */
dawn_unit dawn_io_eprint(dawn_str *s) {
  fflush(stdout);
  if (s->len > 0) {
    fwrite(s->p, 1, (size_t)s->len, stderr);
  }
  return DAWN_UNIT;
}

dawn_unit dawn_io_eprintln(dawn_str *s) {
  dawn_io_eprint(s);
  fputc('\n', stderr);
  return DAWN_UNIT;
}

dawn_unit dawn_io_exit(int64_t code) {
  /* exit() flushes stdio, which the block buffering above makes load-bearing */
  exit((int)code);
}

dawn_str *dawn_str_concat(dawn_str *a, dawn_str *b) {
  /* the shortcut hands back a value the caller will own; its own reference
   * to the operand still stands, so the result needs one of its own */
  if (a->len == 0) return (dawn_str *)dawn_dup(b);
  if (b->len == 0) return (dawn_str *)dawn_dup(a);
  dawn_str *r = dawn_str_new(a->len + b->len);
  char *buf = dawn_str_data(r);
  memcpy(buf, a->p, (size_t)a->len);
  memcpy(buf + a->len, b->p, (size_t)b->len);
  return r;
}

bool dawn_str_eq(dawn_str *a, dawn_str *b) {
  if (a->len != b->len) return false;
  if (a->len == 0) return true;
  return memcmp(a->p, b->p, (size_t)a->len) == 0;
}

dawn_str *dawn_str_of_int(int64_t v) {
  char buf[32];
  int n = snprintf(buf, sizeof buf, "%lld", (long long)v);
  return dawn_str_copy(buf, (size_t)n);
}

dawn_str *dawn_str_of_float(double v) {
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

dawn_str *dawn_str_of_bytes(const dawn_bytes *b) {
  /* A summary, not the contents: `Bytes` is one of the show scalars
   * (types.dawn's `show_scalars`) and the language renders it as `<N bytes>`.
   * That is what `dawn/rt/Show` answers for a `byte[]` on the JVM, and this
   * is the same rendering compiled for the other backend rather than a second
   * opinion about what a Bytes looks like. */
  char buf[32];
  int n = snprintf(buf, sizeof buf, "<%lld bytes>", (long long)b->len);
  return dawn_str_copy(buf, (size_t)n);
}

/* Static, not `dawn_str_lit`: the macro's storage is the enclosing block,
 * and a return hands the pointer out of it. */
static dawn_str dawn_true_str = {{DAWN_IMMORTAL, DAWN_K_STR}, 4, "true"};
static dawn_str dawn_false_str = {{DAWN_IMMORTAL, DAWN_K_STR}, 5, "false"};

dawn_str *dawn_str_of_bool(bool v) {
  return v ? &dawn_true_str : &dawn_false_str;
}

dawn_str *dawn_str_quote(dawn_str *s) {
  /* Worst case every byte doubles, plus the two quotes. Bytes above 0x7f are
   * copied through: the escapes are the five the JVM backend applies, and a
   * multi-byte code point has no continuation byte in that set. */
  dawn_str *r = dawn_str_new(2 * s->len + 2);
  char *buf = dawn_str_data(r);
  int64_t n = 0;
  buf[n++] = '"';
  for (int64_t i = 0; i < s->len; i++) {
    char c = s->p[i];
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
  return dawn_str_shrink(r, n);
}

/* ---- hashing and ordering ------------------------------------------------
 *
 * Two currencies, on purpose (spec 3.5). `hash(String)` is Java's
 * String.hashCode, defined over UTF-16 code units, so native walks a string
 * the way the JVM sees it rather than the way it holds it. Everything in the
 * BMP -- CJK included -- is one unit either way; only astral code points
 * split into a surrogate pair, and that is the only case where the walks
 * differ. `cmp(String)` is *code point* order (RP-06), which for UTF-8 bytes
 * is plain memcmp -- hash deliberately did not follow the order's currency
 * change, since a hash only has to agree with `==`. */

/* Next UTF-16 code unit, or -1 at the end. `*i` is the byte cursor and
 * `*pending` carries the low surrogate a previous step left behind. */
static int32_t dawn_utf16_next(dawn_str *s, int64_t *i, int32_t *pending) {
  if (*pending >= 0) {
    int32_t u = *pending;
    *pending = -1;
    return u;
  }
  if (*i >= s->len) return -1;
  unsigned char c = (unsigned char)s->p[*i];
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
  if (*i + n > s->len) n = s->len - *i;
  for (int64_t k = 1; k < n; k++) {
    cp = (cp << 6) | ((unsigned char)s->p[*i + k] & 0x3Fu);
  }
  *i += n;
  if (cp >= 0x10000u) {
    cp -= 0x10000u;
    *pending = (int32_t)(0xDC00u + (cp & 0x3FFu));
    return (int32_t)(0xD800u + (cp >> 10));
  }
  return (int32_t)cp;
}

int64_t dawn_hash_int(int64_t v) {
  return (int32_t)((uint32_t)((uint64_t)v ^ ((uint64_t)v >> 32)));
}

int64_t dawn_hash_bool(bool v) { return v ? 1231 : 1237; }

int64_t dawn_hash_str(dawn_str *s) {
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

int64_t dawn_cmp_str(dawn_str *a, dawn_str *b) {
  /* Code point order, and only the sign: `cmp` contracts -1/0/1 (spec 3.5),
   * the magnitude is not a value a program may rely on. Comparing UTF-8
   * bytewise *is* comparing by code point -- the encoding was designed so --
   * and when one string is a prefix of the other the shorter one is smaller
   * in either currency, so the byte lengths settle it. */
  int64_t n = a->len < b->len ? a->len : b->len;
  int c = memcmp(a->p, b->p, (size_t)n);
  if (c != 0) return c < 0 ? -1 : 1;
  return a->len < b->len ? -1 : (a->len > b->len ? 1 : 0);
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

int64_t dawn_int_of_float(double v) {
  /* `to_int` is the JVM's D2L, and D2L saturates: NaN is 0, and a value past
   * either end of the range is that end (JVMS 6.5 d2l). A plain `(int64_t)v`
   * is undefined for all three (C11 6.3.1.4), and on x86-64 `cvttsd2si`
   * answers INT64_MIN for all three -- so `to_int(0.0 / 0.0)` was 0 on the
   * JVM and INT64_MIN here.
   *
   * The bounds are compared in double, and 2^63 is written out rather than
   * spelled INT64_MAX: 2^63 is exactly representable and INT64_MAX is not, so
   * `(double)INT64_MAX` rounds *up* to 2^63 and a `v > (double)INT64_MAX`
   * test would let 2^63 itself through into the undefined cast. INT64_MIN is
   * exactly -2^63, so its end is inclusive. */
  if (v != v) return 0;
  if (v >= 9223372036854775808.0) return INT64_MAX;
  if (v <= -9223372036854775808.0) return INT64_MIN;
  return (int64_t)v;
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

/* The message is copied here rather than kept by pointer: the raiser's frame
 * -- and with it a `dawn_str_lit` compound literal, or a heap message whose
 * owner unwound -- is gone by the time the catcher reads it. */
#define DAWN_FAILURE_MAX 512
static char dawn_failure_buf[DAWN_FAILURE_MAX];
static int64_t dawn_failure_len;

/* The failure's kind, as the name `ForeignError.kind` hands back. A static
 * string rather than a copy: the two are compile-time literals, not something
 * a raiser computes. */
static const char *dawn_failure_kind = "panic";

static void dawn_raise(dawn_str *msg, bool is_panic) {
  dawn_handler *h = dawn_handlers;
  while (h != NULL && is_panic && !h->catches_panic) h = h->prev;
  if (h != NULL) {
    /* The skipped frames go with it: they sit above `h`, and `h`'s own
     * setjmp branch restores the list to `h->prev`. */
    dawn_failure_kind = is_panic ? "panic" : "fault";
    dawn_failure_len = msg->len < DAWN_FAILURE_MAX ? msg->len : DAWN_FAILURE_MAX;
    if (dawn_failure_len > 0) {
      memcpy(dawn_failure_buf, msg->p, (size_t)dawn_failure_len);
    }
    longjmp(h->jb, 1);
  }
  /* Nothing stopped it, so the program is over either way -- which is why
   * both kinds report under the same word. */
  fflush(stdout);
  fputs("panic: ", stderr);
  if (msg->len > 0) fwrite(msg->p, 1, (size_t)msg->len, stderr);
  fputc('\n', stderr);
  exit(1);
}

void dawn_panic(dawn_str *msg) { dawn_raise(msg, true); }

void dawn_fault(dawn_str *msg) { dawn_raise(msg, false); }

/* `ForeignError { kind, message, cause }` out of what the raise left behind.
 * Three reference fields, so all three mask bits: the record owns each one
 * and a drop of the whole releases them. */
#define DAWN_MASK_THREE_BOXED UINT64_C(7)

static dawn_adt *dawn_foreign_error(void) {
  dawn_adt *a = dawn_adt_new(DAWN_TAG_FOREIGN_ERROR, 3, DAWN_MASK_THREE_BOXED);
  a->fields[0].p = dawn_str_copy(dawn_failure_kind, (int64_t)strlen(dawn_failure_kind));
  a->fields[1].p = dawn_str_copy(dawn_failure_buf, dawn_failure_len);
  a->fields[2].p = dawn_none();
  return a;
}

/* The closure returns an erased slot whatever `T` is, so one cast covers
 * every instantiation -- see the header. */
static dawn_adt *dawn_run_caught(dawn_clo *f, bool catches_panic) {
  dawn_handler h;
  h.prev = dawn_handlers;
  h.catches_panic = catches_panic;
  dawn_handlers = &h;
  if (setjmp(h.jb) != 0) {
    dawn_handlers = h.prev;
    return dawn_err(dawn_foreign_error());
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
  /* n == 0 is not an empty set -- no real table is empty. It is the emitter
   * saying nothing reachable reads this one (reach.dawn), so getting here
   * means the pruning was wrong; answer loudly rather than "false". */
  if (n == 0) dawn_panic(dawn_str_lit("unicode table pruned but reached", 32));
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
  dawn_hdr_init(&b->h, DAWN_K_ARRAY_BUF);
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
  dawn_hdr_init(&a->h, DAWN_K_ARRAY);
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
    b->data[a->len] = dawn_dup(x);
    b->high = a->len + 1;
    return dawn_array_of(dawn_dup(b), a->len + 1);
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
    nb->data[k] = dawn_dup(a->buf->data[k]);
  }
  nb->data[a->len] = dawn_dup(x);
  nb->high = a->len + 1;
  return dawn_array_of(nb, a->len + 1);
}

/* `a = push(a, x)` with the references handled: consumes the element and the
 * old header. The borrowing push returns a fresh header, so a loop that just
 * reassigns floors one header and one element reference per iteration -- the
 * runtime's own accumulation loops did (perceus-design.md 5.5: a runtime
 * function calling a primitive owes the same references emitted code would),
 * and so did the emitter's list-literal loop, whose elements arrive owned. */
dawn_array *dawn_array_push_own(dawn_array *a, void *x) {
  dawn_array *r = dawn_array_push(a, x);
  dawn_drop(x);
  dawn_drop(a);
  return r;
}

uint64_t dawn_array_with_inplace = 0;
uint64_t dawn_array_with_copied = 0;

/* Consumes `a` and `x` -- see the header: no watermark can say who still
 * reads slot `i`, but the counts can. Both the array and its buffer have to
 * be unique: an array alone at rc 1 may still share its buffer with another
 * version whose slots these are too. */
dawn_array *dawn_array_with(dawn_array *a, int64_t i, void *x) {
  if (i < 0 || i >= (int64_t)a->len) {
    dawn_panic(dawn_str_lit("Array index out of bounds", 24));
  }
  if (!dawn_rc_leak && dawn_is_unique(a) && dawn_is_unique(a->buf)) {
    dawn_array_with_inplace++;
    void *old = a->buf->data[i];
    a->buf->data[i] = x;
    dawn_drop(old);
    return a;
  }
  dawn_array_with_copied++;
  dawn_array_buf *nb = dawn_array_buf_new(a->len);
  for (int32_t k = 0; k < a->len; k++) {
    /* the consumed `x` lands with the reference the caller handed over */
    nb->data[k] = (k == (int32_t)i) ? x : dawn_dup(a->buf->data[k]);
  }
  nb->high = a->len;
  dawn_array *r = dawn_array_of(nb, a->len);
  dawn_drop(a);
  return r;
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
static bool dawn_utf8_boundary(dawn_str *s, int64_t i) {
  return i == s->len || ((unsigned char)s->p[i] & 0xC0) != 0x80;
}

/* The code point starting at `i`; `*n` receives its length in bytes. */
static uint32_t dawn_utf8_at(dawn_str *s, int64_t i, int64_t *n) {
  unsigned char c = (unsigned char)s->p[i];
  int64_t k = dawn_utf8_seq(c);
  if (i + k > s->len) k = s->len - i;
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
    cp = (cp << 6) | ((unsigned char)s->p[i + j] & 0x3Fu);
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

int64_t dawn_cursor_start(dawn_str *s) {
  (void)s;
  return 0;
}

int64_t dawn_cursor_end(dawn_str *s) { return s->len; }

bool dawn_cursor_done(dawn_str *s, int64_t c) { return c >= s->len; }

int64_t dawn_cursor_char(dawn_str *s, int64_t c) {
  if (c < 0 || c >= s->len) return -1;
  int64_t n;
  return (int64_t)dawn_utf8_at(s, c, &n);
}

int64_t dawn_cursor_next(dawn_str *s, int64_t c) {
  if (c < 0) return 0;
  if (c >= s->len) return s->len;
  int64_t k = dawn_utf8_seq((unsigned char)s->p[c]);
  return c + k > s->len ? s->len : c + k;
}

int64_t dawn_cursor_prev(dawn_str *s, int64_t c) {
  if (c <= 0) return 0;
  if (c > s->len) c = s->len;
  int64_t i = c - 1;
  while (i > 0 && ((unsigned char)s->p[i] & 0xC0) == 0x80) i--;
  return i;
}

/* A copy now, not a shared-buffer view: a counted string's header has to be
 * findable from its pointer, and a mid-buffer pointer has no header. Slices
 * are token-sized in practice (the lexer is the caller that matters). */
dawn_str *dawn_cursor_slice(dawn_str *s, int64_t from, int64_t to) {
  if (from < 0 || to > s->len || from > to ||
      !dawn_utf8_boundary(s, from) || !dawn_utf8_boundary(s, to)) {
    dawn_panic(dawn_str_lit("cursor_slice: invalid cursor range", 34));
  }
  return dawn_str_copy(s->p + from, to - from);
}

/* ---- the str_* primitives ---- */

/* Only `parse_int`'s leading/trailing strip uses this now; the language's
 * `str.trim` is a cursor walk in std/str (native-backend-plan.md 14.12).
 * Answers as a byte span into `s` rather than a string, so the parsers can
 * strip without an allocation. */
static void dawn_str_trim_span(dawn_str *s, int64_t *from, int64_t *to) {
  int64_t a = 0;
  while (a < s->len) {
    int64_t n;
    if (!dawn_char_is_space((int64_t)dawn_utf8_at(s, a, &n))) break;
    a += n;
  }
  int64_t b = s->len;
  while (b > a) {
    int64_t prev = dawn_cursor_prev(s, b);
    int64_t n;
    if (!dawn_char_is_space((int64_t)dawn_utf8_at(s, prev, &n))) break;
    b = prev;
  }
  *from = a;
  *to = b;
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
static dawn_str *dawn_case(dawn_str *s, bool up) {
  const dawn_case_range *rs = up ? dawn_upper_ranges : dawn_lower_ranges;
  size_t rn = (size_t)(up ? dawn_upper_ranges_n : dawn_lower_ranges_n);
  /* same contract as dawn_cp_in: a zero-length table is the emitter's claim
   * that this call cannot run (reach.dawn), not a mapping with no rows */
  if (rn == 0) dawn_panic(dawn_str_lit("unicode table pruned but reached", 32));
  int64_t out = 0;
  for (int64_t i = 0; i < s->len;) {
    int64_t n;
    uint32_t cp = dawn_utf8_at(s, i, &n);
    char scratch[4];
    out += dawn_utf8_put(scratch, (uint32_t)dawn_case_cp((int32_t)cp, rs, rn));
    i += n;
  }
  dawn_str *r = dawn_str_new(out);
  char *buf = dawn_str_data(r);
  int64_t at = 0;
  for (int64_t i = 0; i < s->len;) {
    int64_t n;
    uint32_t cp = dawn_utf8_at(s, i, &n);
    at += dawn_utf8_put(buf + at, (uint32_t)dawn_case_cp((int32_t)cp, rs, rn));
    i += n;
  }
  return r;
}

dawn_str *dawn_str_lower(dawn_str *s) { return dawn_case(s, false); }

dawn_str *dawn_str_upper(dawn_str *s) { return dawn_case(s, true); }

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

static dawn_adt *dawn_parse_radix(dawn_str *s, int64_t radix) {
  if (radix < 2 || radix > 36) return dawn_none();
  int64_t i, end;
  dawn_str_trim_span(s, &i, &end);
  bool neg = false;
  if (i < end && (s->p[i] == '+' || s->p[i] == '-')) {
    neg = s->p[i] == '-';
    i++;
  }
  if (i >= end) return dawn_none();
  /* accumulated as the magnitude, so that LONG_MIN parses */
  uint64_t limit = neg ? (uint64_t)INT64_MAX + 1u : (uint64_t)INT64_MAX;
  uint64_t acc = 0;
  for (; i < end; i++) {
    int64_t d = dawn_digit_val(s->p[i]);
    if (d < 0 || d >= radix) return dawn_none();
    if (acc > (limit - (uint64_t)d) / (uint64_t)radix) return dawn_none();
    acc = acc * (uint64_t)radix + (uint64_t)d;
  }
  /* negated as unsigned: LONG_MIN's magnitude has no int64_t to be negated in */
  int64_t v = neg ? (int64_t)(0u - acc) : (int64_t)acc;
  return dawn_some(dawn_box_int(v));
}

dawn_adt *dawn_parse_int(dawn_str *s) { return dawn_parse_radix(s, 10); }

dawn_adt *dawn_parse_int_radix(dawn_str *s, int64_t radix) {
  return dawn_parse_radix(s, radix);
}

dawn_adt *dawn_parse_float(dawn_str *s) {
  /* strtod's grammar is close to Double.parseDouble's but not equal to it:
   * Java also accepts a trailing f/F/d/D and spells the infinities
   * "Infinity", while strtod also takes hex floats. Floats are already out of
   * the differential corpus over dawn_str_of_float; this is the same gap. */
  int64_t a, b;
  dawn_str_trim_span(s, &a, &b);
  if (b - a == 0) return dawn_none();
  char *buf = (char *)dawn_alloc((size_t)(b - a) + 1);
  memcpy(buf, s->p + a, (size_t)(b - a));
  buf[b - a] = '\0';
  char *end = NULL;
  double v = strtod(buf, &end);
  bool whole = end != NULL && *end == '\0';
  free(buf);
  return whole ? dawn_some(dawn_box_float(v)) : dawn_none();
}

/* ---- code points, and the list primitives that cross through Array ---- */

dawn_array *dawn_code_points(dawn_str *s) {
  dawn_array *a = dawn_array_new();
  int64_t i = 0;
  while (i < s->len) {
    int64_t n;
    uint32_t cp = dawn_utf8_at(s, i, &n);
    a = dawn_array_push_own(a, dawn_box_int((int64_t)cp));
    i += n;
  }
  return a;
}

/* Consumes `cps`: the array is the emitter's list-to-Array crossing temp
 * (emitc `to_host`), a value no Core node owns -- the reader is the only
 * party who can free it. Same for `join` and `io_run` below. */
dawn_str *dawn_from_code_points(dawn_array *cps) {
  int64_t n = dawn_array_len(cps);
  dawn_str *r = dawn_str_new(4 * n);
  char *buf = dawn_str_data(r);
  int64_t at = 0;
  for (int64_t i = 0; i < n; i++) {
    int64_t cp = ((dawn_box *)dawn_array_get(cps, i))->val.i;
    if (cp < 0 || cp > 0x10FFFF) {
      dawn_panic(dawn_str_lit("from_code_points: not a valid code point", 39));
    }
    at += dawn_utf8_put(buf + at, (uint32_t)cp);
  }
  dawn_drop(cps);
  return dawn_str_shrink(r, at);
}

/* Consumes `parts` -- the crossing temp, see `from_code_points`. */
dawn_str *dawn_join(dawn_array *parts, dawn_str *sep) {
  int64_t n = dawn_array_len(parts);
  if (n == 0) {
    dawn_drop(parts);
    return dawn_str_empty;
  }
  int64_t total = sep->len * (n - 1);
  for (int64_t i = 0; i < n; i++) {
    /* a string element rides in the erased slot as itself, not in a box */
    total += ((dawn_str *)dawn_array_get(parts, i))->len;
  }
  dawn_str *r = dawn_str_new(total);
  char *buf = dawn_str_data(r);
  int64_t at = 0;
  for (int64_t i = 0; i < n; i++) {
    if (i > 0 && sep->len > 0) {
      memcpy(buf + at, sep->p, (size_t)sep->len);
      at += sep->len;
    }
    dawn_str *part = (dawn_str *)dawn_array_get(parts, i);
    if (part->len > 0) {
      memcpy(buf + at, part->p, (size_t)part->len);
      at += part->len;
    }
  }
  dawn_drop(parts);
  return r;
}

/* ---- bytes ---- */

static dawn_bytes *dawn_bytes_of(const unsigned char *p, int64_t len) {
  dawn_bytes *b = (dawn_bytes *)dawn_alloc(sizeof(dawn_bytes));
  dawn_hdr_init(&b->h, DAWN_K_BYTES);
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

dawn_bytes *dawn_bytes_utf8(dawn_str *s) {
  unsigned char *buf = (unsigned char *)dawn_alloc((size_t)s->len + 1);
  if (s->len > 0) memcpy(buf, s->p, (size_t)s->len);
  return dawn_bytes_of(buf, s->len);
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
static bool dawn_charset_is(dawn_str *cs, const char *name) {
  size_t n = strlen(name);
  if ((size_t)cs->len != n) return false;
  for (size_t i = 0; i < n; i++) {
    char a = cs->p[i];
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
    dawn_box *s = (dawn_box *)dawn_array_get(a, i);
    buf[i] = (unsigned char)(s->val.i & 0xFF);
  }
  return dawn_bytes_of(buf, n);
}

dawn_adt *dawn_bytes_decode(const dawn_bytes *b, dawn_str *charset) {
  if (dawn_charset_is(charset, "UTF-8") || dawn_charset_is(charset, "UTF8")) {
    /* Malformed input is replaced, not refused -- what `new String(bytes,
     * charset)` does. A byte that starts no valid sequence becomes U+FFFD. */
    dawn_str *r = dawn_str_new(3 * b->len);
    char *buf = dawn_str_data(r);
    int64_t at = 0;
    int64_t i = 0;
    /* a borrowed view over the byte buffer, so the UTF-8 walker can read it */
    dawn_str src = {{DAWN_IMMORTAL, DAWN_K_STR}, b->len, (const char *)b->p};
    while (i < b->len) {
      int64_t n;
      uint32_t cp = dawn_utf8_at(&src, i, &n);
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
    return dawn_some(dawn_str_shrink(r, at));
  }
  if (dawn_charset_is(charset, "ISO-8859-1") || dawn_charset_is(charset, "latin1")) {
    dawn_str *r = dawn_str_new(2 * b->len);
    char *buf = dawn_str_data(r);
    int64_t at = 0;
    for (int64_t i = 0; i < b->len; i++) {
      at += dawn_utf8_put(buf + at, b->p[i]);
    }
    return dawn_some(dawn_str_shrink(r, at));
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
  dawn_str *line = dawn_str_copy(buf, (int64_t)n);
  free(buf);
  return dawn_some(line);
}

/* A Dawn string is not NUL-terminated; every path handed to the C library
 * has to be copied to get the terminator. */
static char *dawn_cpath(dawn_str *s) {
  char *p = (char *)dawn_alloc((size_t)s->len + 1);
  if (s->len > 0) memcpy(p, s->p, (size_t)s->len);
  p[s->len] = '\0';
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

bool dawn_io_is_dir(dawn_str *path) {
  char *p = dawn_cpath(path);
  struct stat st;
  bool yes = stat(p, &st) == 0 && S_ISDIR(st.st_mode);
  free(p);
  return yes;
}

bool dawn_io_exists(dawn_str *path) {
  char *p = dawn_cpath(path);
  struct stat st;
  bool yes = stat(p, &st) == 0;
  free(p);
  return yes;
}

/* Every prefix of the path, `mkdir -p` style. An existing directory is not a
 * failure; an existing *file* is, which is what Files.createDirectories does
 * and File.mkdirs does not. */
dawn_unit dawn_io_mkdirs(dawn_str *path) {
  char *p = dawn_cpath(path);
  for (int64_t i = 1; i <= path->len; i++) {
    if (i != path->len && p[i] != '/') continue;
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

dawn_str *dawn_io_read_file(dawn_str *path) {
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
  dawn_str *s = dawn_str_copy((const char *)buf, (int64_t)n);
  free(buf);
  return s;
}

dawn_unit dawn_io_write_file(dawn_str *path, dawn_str *content) {
  char *p = dawn_cpath(path);
  dawn_mkparents(p);
  FILE *f = fopen(p, "wb");
  free(p);
  if (f == NULL) {
    dawn_fault(dawn_str_lit("io_write_file: cannot open file", 31));
  }
  bool bad = content->len > 0 &&
             fwrite(content->p, 1, (size_t)content->len, f) != (size_t)content->len;
  if (fclose(f) != 0) bad = true;
  if (bad) {
    dawn_fault(dawn_str_lit("io_write_file: write failed", 27));
  }
  return DAWN_UNIT;
}

dawn_array *dawn_io_list_names(dawn_str *path) {
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
      a = dawn_array_push_own(a, dawn_str_copy(e->d_name, (int64_t)n));
    }
    e = readdir(d);
  }
  closedir(d);
  return a;
}

dawn_str *dawn_io_cwd(void) {
  size_t cap = 1024;
  for (;;) {
    char *buf = (char *)dawn_alloc(cap);
    if (getcwd(buf, cap) != NULL) {
      dawn_str *s = dawn_str_copy(buf, (int64_t)strlen(buf));
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

dawn_adt *dawn_io_getenv(dawn_str *name) {
  char *p = dawn_cpath(name);
  const char *v = getenv(p);
  free(p);
  if (v == NULL) return dawn_none();
  return dawn_some(dawn_str_copy(v, (int64_t)strlen(v)));
}

dawn_bytes *dawn_io_read_bytes(dawn_str *path) {
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

dawn_unit dawn_io_write_bytes(dawn_str *path, const dawn_bytes *content) {
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
bool dawn_io_delete(dawn_str *path) {
  char *p = dawn_cpath(path);
  bool gone = remove(p) == 0;
  free(p);
  return gone;
}

dawn_unit dawn_io_rename(dawn_str *src, dawn_str *dst) {
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

dawn_str *dawn_io_temp_dir(dawn_str *parent, dawn_str *prefix) {
  char *pbuf = NULL;
  const char *base;
  if (parent->len == 0) {
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
  dawn_str *s = dawn_str_copy(tmpl, (int64_t)strlen(tmpl));
  free(tmpl);
  return s;
}

bool dawn_io_is_symlink(dawn_str *path) {
  char *p = dawn_cpath(path);
  struct stat st;
  bool yes = lstat(p, &st) == 0 && S_ISLNK(st.st_mode);
  free(p);
  return yes;
}

dawn_bytes *dawn_io_read_stdin(int64_t n) {
  /* an owned empty buffer, not a static "": drop frees `p` now */
  if (n <= 0) return dawn_bytes_of((unsigned char *)dawn_alloc(1), 0);
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

int64_t dawn_io_run(dawn_array *argv, dawn_str *out_path, dawn_str *err_path) {
  int64_t n = dawn_array_len(argv);
  if (n <= 0) {
    dawn_fault(dawn_str_lit("io_run: argv is empty", 21));
  }
  char **args = (char **)dawn_alloc(sizeof(char *) * (size_t)(n + 1));
  for (int64_t i = 0; i < n; i++) {
    args[i] = dawn_cpath((dawn_str *)dawn_array_get(argv, i));
  }
  args[n] = NULL;

  posix_spawn_file_actions_t fa;
  posix_spawn_file_actions_init(&fa);
  char *op = NULL;
  char *ep = NULL;
  if (out_path->len > 0) {
    op = dawn_cpath(out_path);
    posix_spawn_file_actions_addopen(&fa, 1, op, O_WRONLY | O_CREAT | O_TRUNC, 0644);
  }
  if (err_path->len > 0) {
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
  dawn_drop(argv);
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
    a = dawn_array_push_own(a, dawn_str_copy(dawn_argv[i], (int64_t)strlen(dawn_argv[i])));
  }
  return a;
}
