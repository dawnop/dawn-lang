/* Contract test for the tagged immediates (docs/native-immediates-design.md).
 *
 * An erased Int or Bool is a word whose low bit is 1 and which points at
 * nothing; every point in the runtime that reads a header or a box has to
 * ask first (the table in the design doc, section 4). A point that forgets
 * does not compute a wrong answer: it dereferences `(void *)3`. That is why
 * each case here runs in its own process and is read off its exit status,
 * not off an assertion inside it: the mutants in mutate.py remove one
 * question each, and what they must produce is a red, which for most of them
 * is a signal.
 *
 * The runtime is #included rather than linked so that a case can reach the
 * file-local state it needs (the GPU launch table is `static`), and so that
 * one translation unit sees the mutated runtime and the mutated header
 * together.
 *
 * Usage:  imm_test            every case, one process each, `<name> PASS|FAIL`
 *         imm_test --list     the roster
 *         imm_test --case N   one case in this process (exit 0 = pass) */

#define _DEFAULT_SOURCE 1
#define _POSIX_C_SOURCE 200809L

#include <dawn_rt.c>

#include "../rc-contract/unicode_stubs.h"

#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
/* gcc defines __SANITIZE_ADDRESS__ under -fsanitize=address; clang does not,
 * it answers __has_feature(address_sanitizer). Testing only the first meant a
 * clang build never took the leak exemptions below and LeakSanitizer reported
 * the immortal constants as leaks. */
#if defined(__SANITIZE_ADDRESS__)
#define IMM_ASAN 1
#elif defined(__has_feature)
#if __has_feature(address_sanitizer)
#define IMM_ASAN 1
#endif
#endif
#ifdef IMM_ASAN
#include <sanitizer/lsan_interface.h>
#endif

#define REQUIRE(cond)                                                       \
  do {                                                                      \
    if (!(cond)) {                                                          \
      fprintf(stderr, "%s:%d: REQUIRE failed: %s\n", __FILE__, __LINE__,   \
              #cond);                                                       \
      exit(1);                                                              \
    }                                                                       \
  } while (0)

#define P2(e) (INT64_C(1) << (e))

/* Every value a boundary can sit on: the 63-bit edge, the 31-bit edge a
 * wasm32 build has (and a DAWN_IMM_BITS=31 build emulates), the extremes. */
static const int64_t boundary_values[] = {
  0, 1, -1, 2, -2, 255, -256, 65535,
  P2(30) - 1, P2(30), -P2(30), -P2(30) - 1,
  P2(31) - 1, P2(31), -P2(31), -P2(31) - 1,
  P2(32),
  P2(61), -P2(61),
  P2(62) - 1, P2(62), P2(62) + 1,
  -P2(62) + 1, -P2(62), -P2(62) - 1,
  INT64_MAX - 1, INT64_MAX, INT64_MIN + 1, INT64_MIN,
};
#define NBOUNDARY ((int)(sizeof boundary_values / sizeof boundary_values[0]))

static bool fits(int64_t v) { return v >= DAWN_IMM_MIN && v <= DAWN_IMM_MAX; }

/* ---- the box itself ------------------------------------------------------ */

/* Which side of the boundary each value lands on, and that both sides read
 * back to the same 64 bits. */
static void case_box_boundaries(void) {
  for (int i = 0; i < NBOUNDARY; i++) {
    int64_t v = boundary_values[i];
    void *p = dawn_box_int(v);
    REQUIRE(dawn_is_imm(p) == fits(v));
    REQUIRE(p != NULL);
    if (!dawn_is_imm(p)) {
      REQUIRE(((dawn_hdr *)p)->rc == 1 && ((dawn_hdr *)p)->kind == DAWN_K_BOX);
    }
    REQUIRE(dawn_peek_int(p) == v);
    dawn_drop(p); /* a no-op for an immediate, the free for a heap box */
  }
}

/* The owning read: the value comes out and a heap box is released with it. */
static void case_unbox_int_owning(void) {
  for (int i = 0; i < NBOUNDARY; i++) {
    int64_t v = boundary_values[i];
    REQUIRE(dawn_unbox_int(dawn_box_int(v)) == v);
  }
}

/* The range test is the only thing between a value and a truncation: one off
 * at either edge keeps most values right and loses exactly these. */
static void case_box_range_edges(void) {
  REQUIRE(dawn_is_imm(dawn_box_int(DAWN_IMM_MAX)));
  REQUIRE(dawn_is_imm(dawn_box_int(DAWN_IMM_MIN)));
  void *over = dawn_box_int(DAWN_IMM_MAX + 1);
  void *under = dawn_box_int(DAWN_IMM_MIN - 1);
  REQUIRE(!dawn_is_imm(over) && !dawn_is_imm(under));
  REQUIRE(dawn_peek_int(over) == DAWN_IMM_MAX + 1);
  REQUIRE(dawn_peek_int(under) == DAWN_IMM_MIN - 1);
  dawn_drop(over);
  dawn_drop(under);
  /* a heap box and an immediate of the same value are the same Int */
  void *a = dawn_box_int(7);
  dawn_box *b = dawn_box_int_heap(7);
  REQUIRE(dawn_is_imm(a) && !dawn_is_imm(b));
  REQUIRE(dawn_peek_int(a) == dawn_peek_int(b));
  dawn_drop(b);
}

/* Arithmetic is on the concrete i64 (-fwrapv); what crosses the boundary is
 * the result, boxed afterwards. */
static void case_wrapping_results(void) {
  volatile int64_t top = DAWN_IMM_MAX;
  volatile int64_t bottom = DAWN_IMM_MIN;
  volatile int64_t max = INT64_MAX;
  volatile int64_t min = INT64_MIN;
  volatile int64_t one = 1;
  int64_t r[] = {top + one, bottom - one, max + one, min - one, max * 2,
                 min * 2, top * 2, bottom * 2, -min, (top + one) - one};
  int64_t want[] = {DAWN_IMM_MAX + 1, DAWN_IMM_MIN - 1, INT64_MIN, INT64_MAX, -2,
                    0, DAWN_IMM_MAX * 2, DAWN_IMM_MIN * 2, INT64_MIN, DAWN_IMM_MAX};
  for (size_t i = 0; i < sizeof r / sizeof r[0]; i++) {
    REQUIRE(r[i] == want[i]);
    void *p = dawn_box_int(r[i]);
    REQUIRE(dawn_is_imm(p) == fits(r[i]));
    REQUIRE(dawn_unbox_int(p) == r[i]);
  }
}

static void case_bool_box(void) {
  for (int b = 0; b <= 1; b++) {
    void *p = dawn_box_bool(b != 0);
    REQUIRE(dawn_is_imm(p) && p != NULL);
    REQUIRE(dawn_peek_bool(p) == (b != 0));
    REQUIRE(dawn_unbox_bool(p) == (b != 0));
    dawn_drop(dawn_dup(p));
  }
  REQUIRE(dawn_box_bool(false) != dawn_box_bool(true));
}

/* Float and Unit keep the heap box and must not have moved. */
static void case_float_and_unit_unchanged(void) {
  dawn_box *f = dawn_box_float(2.5);
  REQUIRE(!dawn_is_imm(f) && f->val.f == 2.5 && f->h.kind == DAWN_K_BOX);
  REQUIRE(dawn_unbox_float(f) == 2.5);
  dawn_box *u = dawn_box_unit(DAWN_UNIT);
  REQUIRE(u == dawn_unit_box && !dawn_is_imm(u));
  dawn_dup(u);
  dawn_drop(u);
  dawn_drop(u);
  REQUIRE(((dawn_hdr *)u)->rc == DAWN_IMMORTAL);
}

/* ---- the reference-count points ------------------------------------------ */

static void case_dup_imm(void) {
  for (int i = 0; i < NBOUNDARY; i++) {
    void *p = dawn_box_int(boundary_values[i]);
    void *q = dawn_dup(p);
    REQUIRE(q == p);
    if (!dawn_is_imm(p)) {
      REQUIRE(((dawn_hdr *)p)->rc == 2);
      dawn_drop(p);
    }
    dawn_drop(p);
  }
  void *t = dawn_box_bool(true);
  REQUIRE(dawn_dup(t) == t);
}

static void case_drop_imm(void) {
  for (int i = 0; i < NBOUNDARY; i++) {
    dawn_drop(dawn_box_int(boundary_values[i]));
  }
  dawn_drop(dawn_box_bool(true));
  dawn_drop(dawn_box_bool(false));
}

/* The out-of-line half of an inline-RC build. Nothing but a direct call
 * reaches it with an immediate, because the inline front already returned;
 * its own guard is what the plain build's dawn_drop is. */
static void case_drop_slow_imm(void) {
#ifdef DAWN_RT_INLINE_RC
  dawn_drop_slow(dawn_box_int(5));
  dawn_drop_slow(dawn_box_bool(true));
#else
  dawn_drop(dawn_box_int(5)); /* the same function in this build */
#endif
}

static void case_is_unique_imm(void) {
  REQUIRE(!dawn_is_unique(dawn_box_int(3)));
  REQUIRE(!dawn_is_unique(dawn_box_bool(true)));
  void *big = dawn_box_int(INT64_MAX);
  REQUIRE(dawn_is_unique(big));
  dawn_drop(big);
}

/* The work list: an immediate child must not be queued. One case for each
 * container the walk visits -- ADT fields, closure captures, the array
 * buffer -- and the immortal walk beside them, which shares the push. */
static void case_drop_walks_adt_fields(void) {
  dawn_box *heap = dawn_box_int_heap(INT64_MAX);
  dawn_dup(heap);
  dawn_adt *a = dawn_adt_new(1, 4, 15);
  a->fields[0].p = dawn_box_int(1);
  a->fields[1].p = heap;
  a->fields[2].p = dawn_box_bool(true);
  a->fields[3].p = dawn_box_int(-1);
  dawn_drop(a);
  REQUIRE(heap->h.rc == 1);
  dawn_drop(heap);
}

static void case_drop_walks_closure_caps(void) {
  dawn_box *heap = dawn_box_int_heap(INT64_MIN);
  dawn_dup(heap);
  dawn_clo *c = dawn_clo_new((void *)0, 3, 7);
  c->caps[0].p = dawn_box_int(41);
  c->caps[1].p = heap;
  c->caps[2].p = dawn_box_bool(false);
  dawn_drop(c);
  REQUIRE(heap->h.rc == 1);
  dawn_drop(heap);
}

static void case_drop_walks_array_buffer(void) {
  dawn_box *heap = dawn_box_int_heap(P2(62));
  dawn_dup(heap);
  dawn_array *xs = dawn_array_new();
  xs = dawn_array_push_own(xs, dawn_box_int(1));
  xs = dawn_array_push_own(xs, heap);
  xs = dawn_array_push_own(xs, dawn_box_bool(true));
  dawn_drop(xs);
  REQUIRE(heap->h.rc == 1);
  dawn_drop(heap);
}

static void case_immortal_walk(void) {
  dawn_box *heap = dawn_box_int_heap(INT64_MAX);
  dawn_adt *a = dawn_adt_new(1, 3, 7);
  a->fields[0].p = dawn_box_int(9);
  a->fields[1].p = heap;
  a->fields[2].p = dawn_box_bool(true);
  dawn_immortal(a);
#ifdef IMM_ASAN
  /* An immortal object outlives the program on purpose and is never freed.
   * Exempt exactly these two from the leak check rather than the whole case,
   * so a leak anywhere else in it is still reported. */
  __lsan_ignore_object(a);
  __lsan_ignore_object(heap);
#endif
  REQUIRE(a->h.rc == DAWN_IMMORTAL && heap->h.rc == DAWN_IMMORTAL);
  dawn_immortal(dawn_box_int(5)); /* a constant that is itself an immediate */
}

/* Reset and its steal variant move and count fields of a node; an immediate
 * field is released and counted like a reference, i.e. not at all. */
static void case_reset_and_steal_imm(void) {
  dawn_adt *a = dawn_adt_new(1, 2, 3);
  a->fields[0].p = dawn_box_int(1);
  a->fields[1].p = dawn_box_int(2);
  dawn_adt *tok = dawn_adt_reset(a);
  REQUIRE(tok != NULL);
  tok = dawn_adt_reuse(tok, 2, 2, 3);
  void *big = dawn_box_int(P2(62)); /* an immediate here, a heap box at 31 bits */
  tok->fields[0].p = big;
  tok->fields[1].p = dawn_box_int(3);
  dawn_dup(tok);
  dawn_adt *shared = dawn_adt_reset_steal(tok, 1);
  REQUIRE(shared == NULL); /* shared: dup'd the stolen field, dropped once */
  dawn_drop(big);          /* the reference the caller moved out of the node */
  dawn_drop(tok);
}

/* ---- containers ---------------------------------------------------------- */

static void case_array_of_ints(void) {
  dawn_array *xs = dawn_array_new();
  for (int i = 0; i < NBOUNDARY; i++) {
    xs = dawn_array_push_own(xs, dawn_box_int(boundary_values[i]));
  }
  REQUIRE(dawn_array_len(xs) == NBOUNDARY);
  for (int i = 0; i < NBOUNDARY; i++) {
    REQUIRE(dawn_peek_int(dawn_array_get(xs, i)) == boundary_values[i]);
  }
  dawn_array *ys = dawn_array_with(dawn_array_slice(xs, 0, NBOUNDARY), 3,
                                   dawn_box_int(INT64_MIN));
  REQUIRE(dawn_peek_int(dawn_array_get(ys, 3)) == INT64_MIN);
  REQUIRE(dawn_peek_int(dawn_array_get(xs, 3)) == boundary_values[3]);
  dawn_array *zs = dawn_array_extend(xs, ys);
  REQUIRE(dawn_array_len(zs) == 2 * NBOUNDARY);
  void *taken = dawn_array_steal(zs, NBOUNDARY + 5);
  REQUIRE(dawn_peek_int(taken) == boundary_values[5]);
  zs = dawn_array_with(zs, NBOUNDARY + 5, taken);
  dawn_drop(zs);
  dawn_drop(ys);
  dawn_drop(xs);
}

static void case_cell_of_ints(void) {
  void *c = dawn_cell_new(dawn_box_int(1));
  REQUIRE(dawn_peek_int(dawn_cell_get(c)) == 1);
  dawn_cell_set(c, dawn_box_int(INT64_MAX));
  void *g = dawn_cell_get(c);
  REQUIRE(dawn_peek_int(g) == INT64_MAX);
  dawn_cell_set(c, dawn_box_int(-7)); /* get borrows: nothing to drop */
  void *t = dawn_cell_take(c);
  REQUIRE(dawn_peek_int(t) == -7);
  dawn_cell_set(c, dawn_box_bool(true));
  dawn_drop(c);
}

static void case_option_of_ints(void) {
  for (int i = 0; i < NBOUNDARY; i++) {
    dawn_adt *o = dawn_some(dawn_box_int(boundary_values[i]));
    REQUIRE(dawn_peek_int(o->fields[0].p) == boundary_values[i]);
    dawn_drop(o);
  }
  dawn_adt *ob = dawn_some(dawn_box_bool(true));
  REQUIRE(dawn_peek_bool(ob->fields[0].p));
  dawn_drop(ob);
}

/* ---- the kind readers ---------------------------------------------------- */

/* Each of these ends in a panic when handed something that is not what it
 * wants; with an immediate that has to be the panic, not a read through the
 * tag. The panic is an exit(1) with a message, which the child reports. */
static void expect_panic(void (*body)(void), const char *needle) {
  int fds[2];
  REQUIRE(pipe(fds) == 0);
  fflush(NULL);
  pid_t pid = fork();
  REQUIRE(pid >= 0);
  if (pid == 0) {
#ifdef IMM_ASAN
    __lsan_disable();
#endif
    dup2(fds[1], 2);
    close(fds[0]);
    close(fds[1]);
    body();
    _exit(0); /* returned: no panic */
  }
  close(fds[1]);
  char buf[512];
  size_t n = 0;
  ssize_t r;
  while ((r = read(fds[0], buf + n, sizeof buf - 1 - n)) > 0) n += (size_t)r;
  buf[n] = 0;
  close(fds[0]);
  int st = 0;
  REQUIRE(waitpid(pid, &st, 0) == pid);
  REQUIRE(WIFEXITED(st) && WEXITSTATUS(st) == 1);
  REQUIRE(strstr(buf, needle) != NULL);
}

static void body_ev_get(void) { (void)dawn_ev_get(dawn_box_int(5), 1); }
static void body_ev_get_big(void) { (void)dawn_ev_get(dawn_box_bool(true), 1); }

static void case_ev_get_imm(void) {
  expect_panic(body_ev_get, "effect evidence missing");
  expect_panic(body_ev_get_big, "effect evidence missing");
}

static void case_ev_append_imm(void) {
  /* a join over a non-node front is the back unchanged (an empty pack) */
  void *back = dawn_box_int(5);
  void *r = dawn_ev_append(dawn_box_int(3), back);
  REQUIRE(r == back);
  dawn_drop(r);
}

static void body_discard(void) { (void)dawn_discard(dawn_box_int(7), NULL); }

static void case_discard_imm(void) {
  expect_panic(body_discard, "`discard` expects a continuation");
}

/* ---- the bulk readers ---------------------------------------------------- */

static void case_from_code_points_imm(void) {
  dawn_array *cps = dawn_array_new();
  int64_t cp[] = {0x68, 0x69, 0x4e2d, 0x1F600, 0x21};
  for (int i = 0; i < 5; i++) {
    /* alternate forms: the reader has to take both in one array */
    void *b = (i == 2) ? (void *)dawn_box_int_heap(cp[i]) : dawn_box_int(cp[i]);
    cps = dawn_array_push_own(cps, b);
  }
  dawn_str *s = dawn_from_code_points(cps);
  const char want[] = "hi\xe4\xb8\xad\xf0\x9f\x98\x80!";
  REQUIRE(s->len == (int64_t)sizeof want - 1 && memcmp(s->p, want, (size_t)s->len) == 0);
  dawn_drop(s);
}

static void case_bytes_pack_imm(void) {
  int64_t vs[] = {1, -2, P2(62), -P2(62) - 1, INT64_MAX, INT64_MIN};
  dawn_array *a = dawn_array_new();
  for (int i = 0; i < 6; i++) a = dawn_array_push_own(a, dawn_box_int(vs[i]));
  dawn_bytes *b = dawn_bytes_pack_int(a, 8, true);
  REQUIRE(b->len == 48);
  for (int i = 0; i < 6; i++) {
    uint64_t x = 0;
    memcpy(&x, b->p + 8 * i, 8);
    REQUIRE((int64_t)x == vs[i]);
  }
  dawn_drop(b);
  dawn_drop(a);
  /* narrow widths read the low bytes of the same word */
  dawn_array *c = dawn_array_new();
  c = dawn_array_push_own(c, dawn_box_int(0x0102));
  dawn_bytes *d = dawn_bytes_pack_int(c, 2, false);
  REQUIRE(d->len == 2 && d->p[0] == 1 && d->p[1] == 2);
  dawn_drop(d);
  dawn_drop(c);
}

/* The GPU launch reads each device pointer out of an Array[Int]. The driver
 * is replaced by two functions that record what they were handed, which the
 * runtime's file-local table lets a test do because the runtime is #included.
 * Without a device the call would refuse before it reached the read. */
static int gpu_expect_n;
static unsigned long long gpu_seen[8];

static int fake_get_function(dawn_cu_function *f, dawn_cu_module m, const char *name) {
  (void)m;
  (void)name;
  *f = (dawn_cu_function)1;
  return 0;
}

static int fake_launch(dawn_cu_function f, unsigned a, unsigned b, unsigned c, unsigned d,
                       unsigned e, unsigned g, unsigned h, void *shared, void **params,
                       void **extra) {
  (void)f; (void)a; (void)b; (void)c; (void)d; (void)e; (void)g; (void)h;
  (void)shared; (void)extra;
  for (int i = 0; i < gpu_expect_n; i++) {
    gpu_seen[i] = *(unsigned long long *)params[i];
  }
  return 0;
}

static void case_gpu_launch_args_imm(void) {
#ifdef __wasi__
  return;
#else
  dawn_gpu.ready = true;
  dawn_gpu.module_get_function = fake_get_function;
  dawn_gpu.launch_kernel = fake_launch;
  /* device addresses: small ones are immediates, the high ones are not */
  int64_t ptrs[] = {0x1000, 0x7f0000000000, P2(62), 0x7fffffffffffffffLL};
  dawn_array *args = dawn_array_new();
  for (int i = 0; i < 4; i++) args = dawn_array_push_own(args, dawn_box_int(ptrs[i]));
  gpu_expect_n = 4;
  dawn_adt *r = dawn_gpu_launch_host(1, DAWN_LIT("k"), 1, 1, 1, args);
  REQUIRE(r->tag == DAWN_TAG_OK);
  for (int i = 0; i < 4; i++) REQUIRE((int64_t)gpu_seen[i] == ptrs[i]);
  dawn_drop(r);
  dawn_drop(args);
#endif
}

/* ---- roster -------------------------------------------------------------- */

typedef struct {
  const char *name;
  void (*fn)(void);
} imm_case;

#define CASE(n) {#n, case_##n}
static const imm_case cases[] = {
  CASE(box_boundaries),
  CASE(unbox_int_owning),
  CASE(box_range_edges),
  CASE(wrapping_results),
  CASE(bool_box),
  CASE(float_and_unit_unchanged),
  CASE(dup_imm),
  CASE(drop_imm),
  CASE(drop_slow_imm),
  CASE(is_unique_imm),
  CASE(drop_walks_adt_fields),
  CASE(drop_walks_closure_caps),
  CASE(drop_walks_array_buffer),
  CASE(immortal_walk),
  CASE(reset_and_steal_imm),
  CASE(array_of_ints),
  CASE(cell_of_ints),
  CASE(option_of_ints),
  CASE(ev_get_imm),
  CASE(ev_append_imm),
  CASE(discard_imm),
  CASE(from_code_points_imm),
  CASE(bytes_pack_imm),
  CASE(gpu_launch_args_imm),
};
#define NCASES ((int)(sizeof cases / sizeof cases[0]))

int main(int argc, char **argv) {
  if (argc == 2 && strcmp(argv[1], "--list") == 0) {
    for (int i = 0; i < NCASES; i++) puts(cases[i].name);
    return 0;
  }
  if (argc == 3 && strcmp(argv[1], "--case") == 0) {
    for (int i = 0; i < NCASES; i++) {
      if (strcmp(argv[2], cases[i].name) == 0) {
        cases[i].fn();
        return 0;
      }
    }
    fprintf(stderr, "no such case: %s\n", argv[2]);
    return 2;
  }
  int failed = 0;
  for (int i = 0; i < NCASES; i++) {
    fflush(NULL);
    pid_t pid = fork();
    if (pid == 0) {
      cases[i].fn();
      exit(0); /* through atexit, so a sanitizer's leak check runs */
    }
    int st = 0;
    waitpid(pid, &st, 0);
    bool ok = WIFEXITED(st) && WEXITSTATUS(st) == 0;
    printf("%s %s\n", cases[i].name, ok ? "PASS" : "FAIL");
    if (!ok) failed++;
  }
  return failed == 0 ? 0 : 1;
}
