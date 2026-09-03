/* See dawn_rt.h. */

/* stat/opendir/readdir are POSIX, and -std=c11 hides them without this. */
#define _POSIX_C_SOURCE 200809L
/* madvise is not in that set. This is the wider one, so it has to be asked
 * for by name; it is file-wide and only widens what is declared. */
#define _DEFAULT_SOURCE 1

#include "dawn_rt.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>
#ifndef __wasi__
#include <pthread.h>
#include <setjmp.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unwind.h>
#endif

#ifdef __wasi__
/* ---- wasm32-wasi ------------------------------------------------------
 *
 * The same translation unit, minus what the target does not have: threads,
 * processes, signals, setjmp and a platform unwinder (wasi-libc leaves all
 * five out). RC, strings, collections and file io through WASI preopens are
 * the untouched code above and below; what follows is the honest spelling
 * of each absence, not an emulation.
 *
 * Failure *recovery* is real here since the A1 shadow-stack landing (see
 * "landing at a handler on wasm32-wasi" further down): raise runs the
 * discarded frames' drops off a shadow stack the frames registered on, and
 * the trip to the handler is a wasm exception a small C++ shim catches
 * (runtime/c/dawn_rt_wasi_eh.cc -- clang will not lower C landing pads for
 * this target, so the two catch sites live in the one C++ TU). */

/* wasi-libc cuts these out of its headers on purpose ("WASI has no temp
 * directories", "WASI has no chmod"). The temp makers report failure and
 * the callers' existing faults say the rest; chmod succeeds vacuously --
 * a target without file modes has nothing to copy and nothing to fail. */
static char *dawn_wasi_mkdtemp(char *tmpl) {
  (void)tmpl;
  errno = ENOTSUP;
  return NULL;
}
static int dawn_wasi_mkstemp(char *tmpl) {
  (void)tmpl;
  errno = ENOTSUP;
  return -1;
}
static int dawn_wasi_chmod(const char *path, mode_t mode) {
  (void)path;
  (void)mode;
  return 0;
}
#define mkdtemp dawn_wasi_mkdtemp
#define mkstemp dawn_wasi_mkstemp
#define chmod dawn_wasi_chmod
#endif

/* ---- the small-object allocator -----------------------------------------
 *
 * Reference counting frees eagerly, so a Dawn program's allocator traffic is
 * a torrent of short-lived blocks in a handful of sizes: the self-hosted
 * compiler compiling itself makes 2.06e8 of them, over half of those 32
 * bytes. Two things about glibc's malloc cost real money on that shape. The
 * pair costs about 8.7ns, which is 1.8s of a 10.3s compile; and it never
 * gives the pages back, because small chunks sit under an arena's top chunk
 * and the resident set is therefore the historical high-water mark.
 *
 * So blocks are carved from 64KiB size-class slabs inside one reserved
 * range. Three consequences, in the order they matter:
 *
 *   * A block carries no header of ours. Which slab a pointer belongs to is
 *     a subtraction and a shift from the base of the reserve, and the slab's
 *     bookkeeping lives in a side array indexed by that number. This is what
 *     keeps the resident set from growing rather than shrinking: a per-block
 *     size word pushes the dominant 32-byte object into the next chunk size,
 *     and a cache of free blocks with headers measured +18% to +37% resident
 *     against plain malloc on every load tried.
 *   * Allocation is a pop from the current slab's free list, freeing a push
 *     onto the owning slab's. There is no bump pointer on the hot path beside
 *     the free list: mimalloc measured that second branch "consistently about
 *     2% worse" (free-list sharding in action, 2.2). The slow path links one
 *     DAWN_SL_BATCH tranche at a time instead. A class with a one-object live
 *     set therefore keeps the one-load, one-branch pop without first writing
 *     through all 64KiB of its logical slab.
 *   * A slab whose last block is freed is retired: up to DAWN_SL_KEEP empty
 *     slabs per class are held for reuse, and past that the pages go back to
 *     the kernel with madvise(MADV_DONTNEED) while the address range returns
 *     to the spare list. Retiring at the container is where every allocator
 *     that gives memory back does it (mimalloc pages, jemalloc slabs,
 *     tcmalloc spans). A bound on how many free *blocks* are cached, which
 *     is the shape tried first, gives nothing back at all: what it bounds is
 *     how much sits idle, and that was never the resident set.
 *
 * The one slab a class is currently allocating from is not retired when it
 * empties. Without that, a class holding one object at a time would take the
 * slow path on every single allocation; mimalloc says the same thing as a
 * tick count ("important to not retire too quickly"), and one pinned logical
 * slab per live class is the cheapest deterministic version of it. Only its
 * materialized prefix is resident under the incremental policy above.
 *
 * Requests over DAWN_SL_MAX go to malloc, which is why no size class has to
 * cover them and why one range comparison answers "is this block mine".
 *
 * The reserve is address space, not memory: MAP_NORESERVE, and a page is
 * only resident once something is written to it. It does count against
 * RLIMIT_AS, though, so a program run under `ulimit -v` has 1GiB less of it
 * than before. That is the one visible cost, and it is why running out of
 * reserve falls back to malloc instead of failing.
 *
 * Single-threaded on purpose: only the thread `dawn_rt_main` starts ever
 * runs Dawn code, so there is no lock here and none is needed.
 *
 * Which builds do not get any of this, and why, is in dawn_rt.h beside
 * DAWN_SLAB_ACTIVE. */

#if DAWN_SLAB_ACTIVE

#include <sys/mman.h>

/* ---- manual poisoning ---------------------------------------------------
 *
 * A block that is not malloc's is a block AddressSanitizer knows nothing
 * about, so on a -DDAWN_SLAB_FORCE build the allocator has to say what is
 * live itself: a free block is poisoned, an issued one is not. That is the
 * whole protocol, and it is what mimalloc's MI_TRACK_ASAN and LLVM's
 * BumpPtrAllocator do too. The two macros come from the sanitizer's own
 * header with their own feature guard, so on a build without -fsanitize
 * they expand to `((void)(addr), (void)(size))` and cost nothing. The
 * include sits inside DAWN_SLAB_ACTIVE rather than at the top of the file
 * because wasi-sdk need not ship the header, and wasi is one of the builds
 * that never reaches here.
 *
 * The order matters, and it is the reason the free list may stay inside the
 * blocks. Freeing writes the link first and poisons the whole block after;
 * allocating unpoisons the whole block first and reads the link after. So a
 * free block is poisoned *including its first eight bytes* everywhere
 * outside these functions, and a use-after-free that reads an object header
 * at offset zero -- the commonest shape there is under reference counting --
 * is reported rather than served. The window where the link is readable is
 * straight-line code inside the allocator, which no program can observe
 * because only the thread dawn_rt_main starts runs Dawn code (see the
 * heading). Two changes would break that argument and force a block-number
 * side table instead: making the runtime multi-threaded, or poisoning from
 * p + 8 to leave the link addressable. scripts/rc-contract's
 * `slab-leaves-the-link-live` mutant is what holds the second one shut.
 *
 * Poisoning is per slab, never over the reserve as a whole: poisoning all
 * 1GiB up front costs 131MiB of shadow, while per-slab shadow is
 * proportional to the slabs a program actually carves.
 *
 * Deliberately not done, so none of it reads as an oversight:
 *
 *   * No red zones, so an overflow into a *live* neighbour is not caught
 *     (an overflow into a free one is). Two reasons, either alone enough.
 *     A red zone changes the block layout, and the layout is the free
 *     variable behind every number the allocator was written for. And LLVM
 *     states the other one in code, at SpecificBumpPtrAllocator's
 *     setRedZoneSize(0): an allocator that walks its own arena cannot have
 *     red zones between allocations. dawn_sl_extend eventually walks every
 *     block a logical slab issues.
 *   * No quarantine. Reuse is already not "the same address back at once",
 *     and a quarantine would have to be a side table anyway.
 *   * No leak detection on this leg, and no __lsan_register_root_region.
 *     LSan reports leaks by iterating its own allocator's chunks, so an
 *     object it never allocated cannot be reported however it is annotated;
 *     root regions only add places to scan *from*, which cures the false
 *     positive of a malloc block reachable only through a slab block at the
 *     price of hiding real leaks behind stale pointer-shaped bytes. False
 *     red traded for false green is not a trade worth making. If a leak
 *     oracle is ever wanted here, the shape that fits is the births-minus-
 *     deaths ledger further down (DAWN_RC_BALANCE), which exists for the
 *     other target LSan cannot reach.
 */
#include <sanitizer/asan_interface.h>

/* The four the header states, under shorter names for the code that uses
 * them on every line. */
#define DAWN_SL_GRAIN DAWN_SLAB_GRAIN
#define DAWN_SL_MAX DAWN_SLAB_MAX
#define DAWN_SL_CLASSES DAWN_SLAB_CLASSES
#define DAWN_SL_KEEP DAWN_SLAB_KEEP

/* Materialize a fresh logical slab one measurement-selected tranche at a
 * time. Kept overrideable for the batch-tail contract and for repeating the
 * lexer/compiler/rbtree extent curve without editing the state machine. */
#ifndef DAWN_SL_BATCH
#define DAWN_SL_BATCH ((size_t)32768)
#endif

#define DAWN_SL_BITS 16 /* one slab is 64KiB */
#define DAWN_SL_SIZE ((size_t)1 << DAWN_SL_BITS)
#define DAWN_SL_SLOTS 16384u /* so the reserve is 1GiB of address space */
#define DAWN_SL_BATCHES (DAWN_SL_SIZE / DAWN_SL_BATCH)

/* The largest block has to fit, or a class would have no slab to live in.
 * The smallest has to hold the free list's link. The second one also buys
 * the poisoning above its exactness: the sanitizer's shadow has an eight
 * byte grain and rounds poison right-down and unpoison left-down, so a
 * partial grain would silently under-poison. A block is a multiple of
 * DAWN_SL_GRAIN from a 64KiB-aligned base, so with GRAIN >= 8 every start
 * and every end is already on a grain and neither rounding can bite. */
_Static_assert(DAWN_SL_MAX <= DAWN_SL_SIZE, "a block must fit inside a slab");
_Static_assert(DAWN_SL_GRAIN >= sizeof(void *), "a free block holds one pointer");
_Static_assert(DAWN_SL_BATCH > 0, "a batch must contain bytes");
_Static_assert(DAWN_SL_BATCH <= DAWN_SL_SIZE, "a batch fits inside a slab");
_Static_assert(DAWN_SL_SIZE % DAWN_SL_BATCH == 0, "batches cover a slab exactly");
_Static_assert(DAWN_SL_BATCHES <= UINT8_MAX, "the batch count fits in one byte");

/* Where a slab is, beyond current-or-not: on its class's list of slabs with
 * free blocks, on its class's list of empty ones, or on neither (full, or
 * the class's current slab). */
#define DAWN_SL_OFF 0
#define DAWN_SL_PARTIAL 1
#define DAWN_SL_EMPTY 2

/* One row per 64KiB of the reserve, indexed by the slab's number. Kept out
 * of the slab itself so a block has nothing but the program's bytes in it. */
typedef struct dawn_sl_slab {
  void *freelist;
  struct dawn_sl_slab *next;
  struct dawn_sl_slab *prev;
  uint32_t used;
  uint16_t cls; /* 0 while the slot holds no slab */
  uint8_t list;
  uint8_t batches; /* prefix whose complete blocks have joined a free list */
} dawn_sl_slab;

/* `batches` occupies the byte that used to be tail padding. The side table is
 * 512KiB on a 64-bit target either way; growing every one of its 16384 rows to
 * carry the incremental state would spend more resident memory than the
 * policy is meant to recover on the small-live-set shape.
 *
 * The 32 is a literal rather than a sum over the fields on purpose. A sum
 * follows the struct wherever it goes: add a field and both sides move
 * together, and the assertion that is supposed to hold the row size fixed
 * agrees with the new one. What is being claimed here is the 512KiB in the
 * sentence above -- 16384 rows of 32 bytes -- so the number that appears in
 * the claim is the number written down. Every target this allocator is
 * active on has 8-byte pointers (wasm32 and the bypassed sanitized builds
 * are excluded in dawn_rt.h); one where the row is not 32 bytes has never
 * run it, and should stop here rather than quietly carry a bigger table. */
_Static_assert(sizeof(dawn_sl_slab) == 32,
               "incremental layout must not grow a slab metadata row");

static dawn_sl_slab dawn_sl_grid[DAWN_SL_SLOTS];
static dawn_sl_slab *dawn_sl_spare; /* retired slots, address range reusable */
static uint32_t dawn_sl_next;       /* slots carved out of the reserve so far */

/* The reserve, as one subtraction and one unsigned compare. Zero span before
 * the first allocation and after a failed reservation, so the test is false
 * of every pointer and the allocator is simply absent. */
static uintptr_t dawn_sl_lo;
static size_t dawn_sl_span;
static int dawn_sl_refused; /* mmap said no; do not ask again */

#define DAWN_SL_MINE(p) (((uintptr_t)(p) - dawn_sl_lo) < dawn_sl_span)

/* The current slab of each class, with its free list hoisted out so the fast
 * path is one load and one branch. */
static void *dawn_sl_head[DAWN_SL_CLASSES];
static dawn_sl_slab *dawn_sl_cur[DAWN_SL_CLASSES];
static dawn_sl_slab *dawn_sl_partial[DAWN_SL_CLASSES];
static dawn_sl_slab *dawn_sl_empty[DAWN_SL_CLASSES];
static uint32_t dawn_sl_empty_n[DAWN_SL_CLASSES];
static uint64_t dawn_sl_live;    /* slabs holding pages */
static uint64_t dawn_sl_retired; /* slabs whose pages went back to the kernel */

static char *dawn_sl_addr(const dawn_sl_slab *s) {
  return (char *)dawn_sl_lo + (size_t)(s - dawn_sl_grid) * DAWN_SL_SIZE;
}

static void dawn_sl_link(dawn_sl_slab **list, dawn_sl_slab *s, uint8_t which) {
  s->prev = NULL;
  s->next = *list;
  if (*list != NULL) {
    (*list)->prev = s;
  }
  *list = s;
  s->list = which;
}

static void dawn_sl_unlink(dawn_sl_slab **list, dawn_sl_slab *s) {
  if (s->prev != NULL) {
    s->prev->next = s->next;
  } else {
    *list = s->next;
  }
  if (s->next != NULL) {
    s->next->prev = s->prev;
  }
  s->prev = NULL;
  s->next = NULL;
  s->list = DAWN_SL_OFF;
}

/* Add the next tranche's complete blocks to an empty free list. A block that
 * crosses a tranche boundary joins the later tranche: after the last call the
 * count is therefore still exactly floor(64KiB / bsize), including for sizes
 * that do not divide the tranche. This is only called when `s->freelist` (and, for a
 * current slab, dawn_sl_head[cls]) is empty, so no chain has to be spliced.
 *
 * The whole-block unpoison/write/poison order is the same one the old whole-
 * slab layout used. In particular the first link may begin before this
 * tranche's byte boundary when its block crosses that boundary; unpoisoning
 * from the block's true start before writing the link is what keeps forced
 * ASAN builds exact in that case. */
static int dawn_sl_extend(dawn_sl_slab *s, size_t cls) {
  size_t bsize = cls * DAWN_SL_GRAIN;
  char *start = dawn_sl_addr(s);
  size_t old_blocks = (size_t)s->batches * DAWN_SL_BATCH / bsize;
  size_t capacity = DAWN_SL_SIZE / bsize;
  if (old_blocks == capacity) {
    /* A block wider than a batch can leave a tail of batches that contains no
     * further complete block. Consume that tail logically instead of walking
     * the next extension past this 64KiB slot. */
    s->batches = (uint8_t)DAWN_SL_BATCHES;
    return 0;
  }
  size_t new_batches = (size_t)s->batches;
  size_t new_blocks = old_blocks;
  /* Normally this advances once. Keeping the loop makes the allocator remain
   * a working allocator if a configured block is wider than a batch: the
   * slow path advances to the first boundary that contains a whole block
   * instead of installing a NULL free list. */
  while (new_blocks == old_blocks && new_batches < DAWN_SL_BATCHES) {
    new_batches++;
    new_blocks = new_batches * DAWN_SL_BATCH / bsize;
  }
  if (new_blocks == old_blocks) {
    s->batches = (uint8_t)DAWN_SL_BATCHES;
    return 0;
  }
  char *first = start + old_blocks * bsize;
  size_t bytes = (new_blocks - old_blocks) * bsize;
  ASAN_UNPOISON_MEMORY_REGION(first, bytes);
  void *fl = NULL;
  /* Backwards, so this tranche's list comes out in address order. */
  for (size_t i = new_blocks; i-- > old_blocks;) {
    void *b = start + i * bsize;
    *(void **)b = fl;
    fl = b;
  }
  ASAN_POISON_MEMORY_REGION(first, bytes);
  s->freelist = fl;
  s->batches = (uint8_t)new_batches;
  return 1;
}

/* Initialise a newly carved (or previously madvised) slot without touching
 * its data pages. Poisoning writes ASAN shadow, not the mapped data; the first
 * dawn_sl_extend in the slow path is what materializes the first free list. */
static void dawn_sl_init(dawn_sl_slab *s, size_t cls) {
  char *start = dawn_sl_addr(s);
  ASAN_POISON_MEMORY_REGION(start, DAWN_SL_SIZE);
  s->freelist = NULL;
  s->used = 0;
  s->cls = (uint16_t)cls;
  s->batches = 0;
}

/* Relayout a non-current slab after its last live block is freed. Such a slab
 * could only stop being current after every batch had been issued, so all of
 * its pages have already participated in the workload. Preserve the existing
 * empty-cache contract: rebuild the complete address-ordered free list, keep
 * it fully materialized for burst reuse, and leave madvise to the over-bound
 * branch in dawn_sl_retire. Incremental first touch is only for a fresh slot. */
static void dawn_sl_layout(dawn_sl_slab *s, size_t cls) {
  size_t bsize = cls * DAWN_SL_GRAIN;
  char *start = dawn_sl_addr(s);
  ASAN_UNPOISON_MEMORY_REGION(start, DAWN_SL_SIZE);
  void *fl = NULL;
  for (size_t i = DAWN_SL_SIZE / bsize; i-- > 0;) {
    void *b = start + i * bsize;
    *(void **)b = fl;
    fl = b;
  }
  ASAN_POISON_MEMORY_REGION(start, DAWN_SL_SIZE);
  s->freelist = fl;
  s->used = 0;
  s->cls = (uint16_t)cls;
  s->batches = (uint8_t)DAWN_SL_BATCHES;
}

/* Take a slot and initialise it for one class. NULL when the reserve is
 * used up, which is a caller's cue to fall back to malloc rather than a
 * fatal condition: a program whose shape the 1GiB reserve does not fit
 * should get slower, not stop. */
static dawn_sl_slab *dawn_sl_carve(size_t cls) {
  dawn_sl_slab *s;
  if (dawn_sl_spare != NULL) {
    s = dawn_sl_spare;
    dawn_sl_spare = s->next;
  } else if (dawn_sl_next < DAWN_SL_SLOTS) {
    s = &dawn_sl_grid[dawn_sl_next++];
  } else {
    return NULL;
  }
  dawn_sl_init(s, cls);
  s->next = NULL;
  s->prev = NULL;
  s->list = DAWN_SL_OFF;
  dawn_sl_live++;
  return s;
}

static void dawn_sl_reserve(void) {
  size_t span = (size_t)DAWN_SL_SLOTS * DAWN_SL_SIZE;
  void *p = mmap(NULL, span, PROT_READ | PROT_WRITE,
                 MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
  if (p == MAP_FAILED) {
    dawn_sl_refused = 1;
    return;
  }
#ifdef MADV_NOHUGEPAGE
  /* Incremental first touch is a page-retention policy. Do not let an
   * anonymous-THP=always host turn a small set of faults into a resident 2MiB extent
   * and make both the policy and its mincore contract host-mode dependent. */
  (void)madvise(p, span, MADV_NOHUGEPAGE);
#endif
  dawn_sl_lo = (uintptr_t)p;
  dawn_sl_span = span;
}

/* The class's free list is empty: find or make a slab, make it current, and
 * hand out its first block. Reached on the first allocation of every class
 * too, which is where the reserve gets made. */
static void *dawn_sl_slow(size_t cls, size_t n) {
  if (dawn_sl_span == 0) {
    if (dawn_sl_refused) {
      return malloc(n);
    }
    dawn_sl_reserve();
    if (dawn_sl_span == 0) {
      return malloc(n);
    }
  }
  dawn_sl_slab *s = dawn_sl_cur[cls];
  if (s != NULL && s->batches < DAWN_SL_BATCHES) {
    /* The current tranche is fully issued -- a free would have made the hot
     * head non-NULL -- but the logical slab is not full yet. Refill that same
     * current slab before any list/state transition. */
    if (dawn_sl_extend(s, cls)) {
      void *b = s->freelist;
      ASAN_UNPOISON_MEMORY_REGION(b, cls * DAWN_SL_GRAIN);
      dawn_sl_head[cls] = *(void **)b;
      s->freelist = NULL;
      s->used++;
      return b;
    }
  }
  s = dawn_sl_partial[cls];
  if (s != NULL) {
    dawn_sl_unlink(&dawn_sl_partial[cls], s);
  } else if ((s = dawn_sl_empty[cls]) != NULL) {
    dawn_sl_unlink(&dawn_sl_empty[cls], s);
    dawn_sl_empty_n[cls]--;
  } else if ((s = dawn_sl_carve(cls)) == NULL) {
    return malloc(n);
  }
  /* The class's previous current slab, if there was one, has materialized all
   * its batches and has an empty free list -- that is why the growth case
   * above did not return. It is now logically full and on no list; a free into
   * it will link it onto the partial list. */
  dawn_sl_cur[cls] = s;
  if (s->freelist == NULL) {
    /* A fresh/spare slot is metadata-only until it becomes current. Partial
     * and cached-empty slabs already carry their existing complete lists. */
    if (!dawn_sl_extend(s, cls)) {
      /* Every supported class fits at least once, so only a broken internal
       * configuration can make a fresh logical slab have no complete block. */
      return malloc(n);
    }
  }
  void *b = s->freelist;
  ASAN_UNPOISON_MEMORY_REGION(b, cls * DAWN_SL_GRAIN);
  dawn_sl_head[cls] = *(void **)b;
  s->freelist = NULL;
  s->used++;
  return b;
}

static void *dawn_sl_get(size_t n) {
  size_t cls = (n + (DAWN_SL_GRAIN - 1)) / DAWN_SL_GRAIN;
  if (cls == 0) {
    cls = 1; /* a zero-byte request still answers a distinct address */
  }
  if (cls >= DAWN_SL_CLASSES) {
    return malloc(n);
  }
  void *b = dawn_sl_head[cls];
  if (b == NULL) {
    return dawn_sl_slow(cls, n);
  }
  ASAN_UNPOISON_MEMORY_REGION(b, cls * DAWN_SL_GRAIN);
  dawn_sl_head[cls] = *(void **)b;
  dawn_sl_cur[cls]->used++;
  return b;
}

static void dawn_sl_retire(dawn_sl_slab *s, size_t cls) {
  if (s->list == DAWN_SL_PARTIAL) {
    dawn_sl_unlink(&dawn_sl_partial[cls], s);
  }
  if (dawn_sl_empty_n[cls] < DAWN_SL_KEEP) {
    dawn_sl_layout(s, cls);
    dawn_sl_link(&dawn_sl_empty[cls], s, DAWN_SL_EMPTY);
    dawn_sl_empty_n[cls]++;
    return;
  }
  /* Past the bound the pages go back. The address range does not: the slot
   * joins the spare list, so a program that churns slabs does not eat the
   * reserve. */
  madvise(dawn_sl_addr(s), DAWN_SL_SIZE, MADV_DONTNEED);
  /* The pages are gone but the address range is not, and a retired slot is
   * carved again later; poisoned is the right state for it in between. */
  ASAN_POISON_MEMORY_REGION(dawn_sl_addr(s), DAWN_SL_SIZE);
  s->freelist = NULL;
  s->prev = NULL;
  s->cls = 0;
  s->list = DAWN_SL_OFF;
  s->batches = 0;
  s->next = dawn_sl_spare;
  dawn_sl_spare = s;
  dawn_sl_live--;
  dawn_sl_retired++;
}

static void dawn_sl_put(void *p) {
  dawn_sl_slab *s = &dawn_sl_grid[((uintptr_t)p - dawn_sl_lo) >> DAWN_SL_BITS];
  size_t cls = s->cls;
  if (s == dawn_sl_cur[cls]) {
    *(void **)p = dawn_sl_head[cls];
    dawn_sl_head[cls] = p;
    ASAN_POISON_MEMORY_REGION(p, cls * DAWN_SL_GRAIN);
    s->used--; /* the current slab is kept even at zero; see the heading */
    return;
  }
  *(void **)p = s->freelist;
  s->freelist = p;
  ASAN_POISON_MEMORY_REGION(p, cls * DAWN_SL_GRAIN);
  if (s->list == DAWN_SL_OFF) {
    dawn_sl_link(&dawn_sl_partial[cls], s, DAWN_SL_PARTIAL);
  }
  if (--s->used == 0) {
    dawn_sl_retire(s, cls);
  }
}

static void *dawn_sl_realloc(void *p, size_t n) {
  if (p == NULL) {
    return dawn_sl_get(n);
  }
  if (!DAWN_SL_MINE(p)) {
    /* A block malloc made stays with malloc, in both directions: its size is
     * not written down anywhere this code can read. */
    return realloc(p, n);
  }
  size_t old = (size_t)dawn_sl_grid[((uintptr_t)p - dawn_sl_lo) >> DAWN_SL_BITS].cls *
               DAWN_SL_GRAIN;
  size_t cls = (n + (DAWN_SL_GRAIN - 1)) / DAWN_SL_GRAIN;
  if (cls != 0 && cls < DAWN_SL_CLASSES && cls * DAWN_SL_GRAIN == old) {
    return p;
  }
  void *q = dawn_sl_get(n);
  if (q == NULL) {
    return NULL;
  }
  memcpy(q, p, n < old ? n : old);
  dawn_sl_put(p);
  return q;
}

void dawn_free(void *p) {
  if (DAWN_SL_MINE(p)) {
    dawn_sl_put(p);
    return;
  }
  free(p);
}

bool dawn_slab_owns(const void *p) { return DAWN_SL_MINE(p); }

void dawn_slab_stats(uint64_t *live, uint64_t *cached, uint64_t *retired) {
  uint64_t held = 0;
  for (size_t c = 0; c < DAWN_SL_CLASSES; c++) {
    held += dawn_sl_empty_n[c];
  }
  *live = dawn_sl_live;
  *cached = held;
  *retired = dawn_sl_retired;
}

#ifdef DAWN_RC_CONTRACT
size_t dawn_slab_materialized_bytes(const void *p) {
  if (!DAWN_SL_MINE(p)) return 0;
  const dawn_sl_slab *s =
      &dawn_sl_grid[((uintptr_t)p - dawn_sl_lo) >> DAWN_SL_BITS];
  if (s->cls == 0) return 0;
  return (size_t)s->batches * DAWN_SL_BATCH;
}
#endif

/* From here down the runtime's allocation is the allocator's, everywhere and
 * without a call site having to remember. The macros reach this translation
 * unit only, which is why `dawn_free` is exported for the one caller that is
 * not in it. */
#define malloc(n) dawn_sl_get(n)
#define realloc(p, n) dawn_sl_realloc((p), (n))
#define free(p) dawn_free(p)

#else

void dawn_free(void *p) { free(p); }

bool dawn_slab_owns(const void *p) {
  (void)p;
  return false;
}

void dawn_slab_stats(uint64_t *live, uint64_t *cached, uint64_t *retired) {
  *live = 0;
  *cached = 0;
  *retired = 0;
}

#ifdef DAWN_RC_CONTRACT
size_t dawn_slab_materialized_bytes(const void *p) {
  (void)p;
  return 0;
}
#endif

#endif /* DAWN_SLAB_ACTIVE */

static int dawn_argc;
static char **dawn_argv;
/* A process is one native/JVM session; a wasm module instance is one browser
 * session. Unlike a Dawn local this root therefore survives the reactor shim
 * calling main again for the next `dawn_turn`. */
static void *dawn_reactor_state;
static int dawn_reactor_cleanup_registered;
static int dawn_rc_stats_registered;
#ifdef __wasi__
static int dawn_wasi_balance_registered;
#endif

static void dawn_reactor_state_clear(void) {
  dawn_drop(dawn_reactor_state);
  dawn_reactor_state = NULL;
}

#ifdef __wasi__
/* Births minus deaths minus immortal marks: the LeakSanitizer stand-in for a
 * target LSan cannot reach. Zero at a clean exit means every counted object
 * the program made was released -- the same claim lsan's "0 leaks" makes for
 * the native corpus. Printed at exit under DAWN_RC_BALANCE (stderr, so a
 * stdout-byte differential stays clean); meaningless under DAWN_RC_LEAK,
 * which turns the deaths off. */
static int64_t dawn_wasi_live_objs;

static void dawn_wasi_balance_dump(void) {
  fprintf(stderr, "rc-balance: %lld\n", (long long)dawn_wasi_live_objs);
}
#define DAWN_LEDGER_BIRTH() (dawn_wasi_live_objs++)
#define DAWN_LEDGER_DEATH() (dawn_wasi_live_objs--)
#else
#define DAWN_LEDGER_BIRTH() ((void)0)
#define DAWN_LEDGER_DEATH() ((void)0)
#endif

/* Stderr, so a differential run comparing stdout byte for byte stays clean
 * even with the stats on. */
static void dawn_rc_stats_dump(void) {
  fprintf(stderr,
          "rc-stats: array_with in-place %llu, copied %llu, "
          "array_steal taken %llu, dup %llu, "
          "adt0 singleton hits %llu, missed %llu\n",
          (unsigned long long)dawn_array_with_inplace,
          (unsigned long long)dawn_array_with_copied,
          (unsigned long long)dawn_array_steal_taken,
          (unsigned long long)dawn_array_steal_dup,
          (unsigned long long)dawn_adt0_hits,
          (unsigned long long)dawn_adt0_missed);
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
  /* A reactor enters this function once per turn. Register each process-exit
   * observer once, both to bound the atexit table and to keep the retained
   * root's cleanup later (therefore earlier in LIFO order) than every report. */
  if (getenv("DAWN_RC_STATS") != NULL && !dawn_rc_stats_registered) {
    atexit(dawn_rc_stats_dump);
    dawn_rc_stats_registered = 1;
  }
#ifdef __wasi__
  if (getenv("DAWN_RC_BALANCE") != NULL && !dawn_wasi_balance_registered) {
    atexit(dawn_wasi_balance_dump);
    dawn_wasi_balance_registered = 1;
  }
#endif
  /* Register after the balance reporter so LIFO exit order releases the
   * intentional process-lifetime root before the reporter counts live
   * objects. `dawn_rt_init` runs once per wasm turn, hence the guard. */
  if (!dawn_reactor_cleanup_registered) {
    atexit(dawn_reactor_state_clear);
    dawn_reactor_cleanup_registered = 1;
  }
}

#ifdef __wasi__
int dawn_rt_main(int argc, char **argv, void (*entry)(void)) {
  /* No pthread here, and no substitute either: the wasm call stack belongs
   * to the engine, so a DAWN_STACK_BYTES thread has no equivalent. Deep
   * recursion on this target is a recorded limit (the native fallback below
   * would print its warning on every run, which is noise, not a message --
   * the warning exists for a big stack that unexpectedly failed to appear,
   * and here one was never on offer). */
  dawn_rt_init(argc, argv);
  entry();
  return 0;
}
#else
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
#endif

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
  DAWN_LEDGER_BIRTH();
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

/* See dawn_rt.h: one immortal object per tag for the field-less
 * constructors. The initialiser is written by doubling because 256 rows
 * differing only in a constant are not worth 256 lines, and the `+ n` inside
 * each row is what makes a row know its own tag. */
_Static_assert(sizeof(dawn_adt0_cell) == sizeof(dawn_adt),
               "dawn_adt0_cell must be a dawn_adt with the tail cut off");
_Static_assert(offsetof(dawn_adt0_cell, tag) == offsetof(dawn_adt, tag),
               "dawn_adt0_cell.tag must sit where dawn_adt.tag sits");
_Static_assert(offsetof(dawn_adt0_cell, nfields) == offsetof(dawn_adt, nfields),
               "dawn_adt0_cell.nfields must sit where dawn_adt.nfields sits");
_Static_assert(offsetof(dawn_adt0_cell, ptrmask) == offsetof(dawn_adt, ptrmask),
               "dawn_adt0_cell.ptrmask must sit where dawn_adt.ptrmask sits");

#define DAWN_ADT0_ROW(t) {{DAWN_IMMORTAL, DAWN_K_ADT}, (t), 0, {0}}
#define DAWN_ADT0_2(t) DAWN_ADT0_ROW(t), DAWN_ADT0_ROW((t) + 1)
#define DAWN_ADT0_4(t) DAWN_ADT0_2(t), DAWN_ADT0_2((t) + 2)
#define DAWN_ADT0_8(t) DAWN_ADT0_4(t), DAWN_ADT0_4((t) + 4)
#define DAWN_ADT0_16(t) DAWN_ADT0_8(t), DAWN_ADT0_8((t) + 8)
#define DAWN_ADT0_32(t) DAWN_ADT0_16(t), DAWN_ADT0_16((t) + 16)
#define DAWN_ADT0_64(t) DAWN_ADT0_32(t), DAWN_ADT0_32((t) + 32)
#define DAWN_ADT0_128(t) DAWN_ADT0_64(t), DAWN_ADT0_64((t) + 64)
#define DAWN_ADT0_256(t) DAWN_ADT0_128(t), DAWN_ADT0_128((t) + 128)

_Static_assert(DAWN_ADT0_TAGS == 256, "the doubling initialiser below writes 256 rows");
dawn_adt0_cell dawn_adt0_table[DAWN_ADT0_TAGS] = {DAWN_ADT0_256(0)};
uint64_t dawn_adt0_hits = 0;
uint64_t dawn_adt0_missed = 0;

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
 * strings) would drown in reports about a decided design. The interning
 * table below is owned for the same reason and in the same sense: reachable
 * for the life of the process, not lost. */
#if DAWN_ASAN
#include <sanitizer/lsan_interface.h>
#define DAWN_LSAN_OWN(p) __lsan_ignore_object(p)
#else
#define DAWN_LSAN_OWN(p) ((void)0)
#endif

/* One dictionary per (template, arguments), not one per call.
 *
 * Never freed and one per call is a leak in any program that does not exit:
 * a reactor turn over a `Node[Msg]` builds 28 of them, so a page clicked ten
 * thousand times holds ten thousand copies of the same 28 relations
 * (4KB/turn, measured on tea-dom's counter). Sharing them is sound because a
 * dictionary is a pure function of its inputs: nothing writes `slots` or
 * `args` after this function returns -- the assignment below is the only one
 * in the runtime or in emitted code -- and no caller compares dictionary
 * pointers for identity, so handing back the same address changes no answer.
 *
 * The key is the template's address plus the argument dictionaries'
 * addresses. Addresses rather than contents: two distinct templates with
 * identical slots stay distinct, which costs a duplicate and cannot make two
 * different relations collide. All the arguments are in the key, not just
 * the template, because a template with a type-variable body is a *family*;
 * that no program in this tree instantiates one twice with different
 * arguments is a fact about today's emitter rather than a contract, so
 * scripts/rc-contract holds the key to the family shape directly.
 *
 * The table is open addressed, never deletes, and doubles. It is bounded by
 * the instantiations a program has, which is a property of its types, so
 * what it holds plateaus where the old behaviour rose forever. Single
 * threaded for the reason the slab allocator is: only the thread
 * dawn_rt_main starts runs Dawn code. */
typedef struct {
  const dawn_dict *tmpl;
  dawn_dict *d;
} dawn_dict_entry;

static dawn_dict_entry *dawn_dict_tab;
static size_t dawn_dict_cap; /* a power of two, or zero before the first use */
static size_t dawn_dict_used;

static size_t dawn_dict_mix(size_t h, size_t x) {
  h ^= x + (size_t)0x9e3779b9u + (h << 6) + (h >> 2);
  return h;
}

static size_t dawn_dict_hash(const dawn_dict *tmpl, int32_t nargs,
                             dawn_dict *const *args) {
  size_t h = dawn_dict_mix((size_t)0, (size_t)(uintptr_t)tmpl);
  h = dawn_dict_mix(h, (size_t)nargs);
  for (int32_t i = 0; i < nargs; i++) {
    h = dawn_dict_mix(h, (size_t)(uintptr_t)args[i]);
  }
  return h;
}

static bool dawn_dict_same(const dawn_dict_entry *e, const dawn_dict *tmpl,
                           int32_t nargs, dawn_dict *const *args) {
  if (e->tmpl != tmpl || e->d->nargs != nargs) return false;
  for (int32_t i = 0; i < nargs; i++) {
    if (e->d->args[i] != args[i]) return false;
  }
  return true;
}

static void dawn_dict_grow(void) {
  size_t cap = dawn_dict_cap == 0 ? 64 : dawn_dict_cap * 2;
  dawn_dict_entry *tab = (dawn_dict_entry *)dawn_alloc(cap * sizeof *tab);
  memset(tab, 0, cap * sizeof *tab);
  DAWN_LSAN_OWN(tab);
  for (size_t i = 0; i < dawn_dict_cap; i++) {
    dawn_dict_entry e = dawn_dict_tab[i];
    if (e.d == NULL) continue;
    size_t j = dawn_dict_hash(e.tmpl, e.d->nargs, e.d->args) & (cap - 1);
    while (tab[j].d != NULL) j = (j + 1) & (cap - 1);
    tab[j] = e;
  }
  free(dawn_dict_tab);
  dawn_dict_tab = tab;
  dawn_dict_cap = cap;
}

dawn_dict *dawn_dict_new(const dawn_dict *tmpl, int32_t nargs, ...) {
  dawn_dict *args[DAWN_DICT_MAX];
  va_list ap;
  va_start(ap, nargs);
  for (int32_t i = 0; i < nargs; i++) {
    args[i] = va_arg(ap, dawn_dict *);
  }
  va_end(ap);

  if ((dawn_dict_used + 1) * 2 > dawn_dict_cap) dawn_dict_grow();
  size_t mask = dawn_dict_cap - 1;
  size_t j = dawn_dict_hash(tmpl, nargs, args) & mask;
  while (dawn_dict_tab[j].d != NULL) {
    if (dawn_dict_same(&dawn_dict_tab[j], tmpl, nargs, args)) {
      return dawn_dict_tab[j].d;
    }
    j = (j + 1) & mask;
  }

  dawn_dict *d = (dawn_dict *)dawn_alloc(sizeof(dawn_dict));
  DAWN_LSAN_OWN(d);
  *d = *tmpl;
  d->nargs = nargs;
  for (int32_t i = 0; i < nargs; i++) {
    d->args[i] = args[i];
  }
  dawn_dict_tab[j].tmpl = tmpl;
  dawn_dict_tab[j].d = d;
  dawn_dict_used++;
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

/* See the header: one immortal object for every boxed Unit. */
dawn_box dawn_unit_box_obj = {{DAWN_IMMORTAL, DAWN_K_BOX}, {.u = DAWN_UNIT}};

dawn_box *dawn_box_unit(dawn_unit v) {
  /* Unit has one value, so `v` carries nothing the shared object does not
   * already say. Taken by parameter anyway because a call site may have
   * computed it (an adapter boxes the result of the body it just called), and
   * C evaluates that argument whether this reads it or not. */
  (void)v;
  return dawn_unit_box;
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

/* See dawn_rt.h. The same traversal `dawn_drop` does, minus the freeing: one
 * work list, the same per-kind child rules, so a kind that gains children has
 * one place to gain them in both walks. `dawn_rc_leak` is not consulted --
 * that mode turns releases off, and this is not a release; the constant has to
 * be immortal in both modes or `dawn_is_unique` answers differently in one of
 * them. */
void dawn_immortal(void *p) {
  dawn_ws s;
  dawn_ws_init(&s);
  dawn_ws_push(&s, p);
  while (s.len > 0) {
    void *q = s.items[--s.len];
    dawn_hdr *h = (dawn_hdr *)q;
    if (h->rc == DAWN_IMMORTAL) {
      continue; /* already out of the ledger; string literals end here */
    }
    h->rc = DAWN_IMMORTAL;
    DAWN_LEDGER_DEATH(); /* out of the ledger for good, not a leak */
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
        dawn_array_buf *b = (dawn_array_buf *)q;
        for (int32_t i = 0; i < b->high; i++) {
          dawn_ws_push(&s, b->data[i]);
        }
        break;
      }
      case DAWN_K_BOX:
      case DAWN_K_BYTES:
      case DAWN_K_STR:
        break; /* no counted children */
      default:
        fprintf(stderr, "dawn: immortal of an unheaded pointer (kind %d)\n", h->kind);
        exit(1);
    }
  }
  dawn_ws_free(&s);
}

/* An activation of a control handler releases the frames it is holding
 * suspended before its own struct goes, and that runs on another stack; see
 * "one-shot resumption" below. Declared here because the walk is above it. */
#ifndef __wasi__
static void dawn_ctl_dispose(void *p);
#endif

void dawn_drop(void *p) {
  if (dawn_rc_leak || p == NULL) {
    return;
  }
  /* Fast path: on scan-shaped code nearly every drop is decrement-only (the
   * lexer corpus measured 12M drops to 28 frees), and the work-list setup is
   * most of what those drops cost. rc > 1 means nothing dies and no child is
   * visited, so decrement and return. Immortal headers return here too --
   * DAWN_IMMORTAL reads as a large rc, so the guard keeps them unwritten.
   * rc <= 0 and rc == 1 fall through to the walk below, which already owns
   * the misuse diagnostic and the release. */
  {
    dawn_hdr *h0 = (dawn_hdr *)p;
    if (h0->rc > 1) {
      if (h0->rc != DAWN_IMMORTAL) {
        h0->rc--;
      }
      return;
    }
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
#ifndef __wasi__
      case DAWN_K_CTL:
        /* Not pushed onto the work list like every other child: the frames
         * this holds have to be unwound on their own stack, and their drops
         * run there rather than here. */
        dawn_ctl_dispose(q);
        break;
#endif
      default:
        fprintf(stderr, "dawn: drop of an unheaded pointer (kind %d)\n", h->kind);
        exit(1);
    }
    DAWN_LEDGER_DEATH();
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

/* The runtime's own `None`, through the same shared object emitted code
 * takes: field-less is field-less whoever builds it. */
dawn_adt *dawn_none(void) { return dawn_adt0(DAWN_TAG_NONE); }

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

/* System.out is a PrintStream with autoFlush on, and its rule is exactly
 * this: `print` flushes when what it wrote contains a newline, `println`
 * always does. Copying the rule rather than the buffering mode is what makes
 * a native program that talks a line-framed protocol -- an LSP server over
 * stdio, a REPL prompting before a read -- answer its peer instead of sitting
 * on a 64 KiB buffer until exit. Measured, 200k println into a pipe: 0.040 s
 * before, 0.11 s after -- 0.35 us a line, and it buys `dawnc lsp` answering
 * an editor at all rather than at exit. It is also the price the JVM backend
 * has always paid, which is the point: this is a contract, not a tuning
 * knob. Bulk output is unaffected: one `print` of a whole C translation unit
 * still flushes once. */
dawn_unit dawn_io_print(dawn_str *s) {
  if (s->len > 0) {
    fwrite(s->p, 1, (size_t)s->len, stdout);
    if (memchr(s->p, '\n', (size_t)s->len) != NULL) {
      fflush(stdout);
    }
  }
  return DAWN_UNIT;
}

dawn_unit dawn_io_println(dawn_str *s) {
  if (s->len > 0) {
    fwrite(s->p, 1, (size_t)s->len, stdout);
  }
  fputc('\n', stdout);
  fflush(stdout);
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

/* Set by the three places the process ends on purpose: an uncaught panic, an
 * uncaught fault, and `io.exit` just below. It suppresses the
 * live-continuation report at exit (dawn_ctl_report, see "one-shot
 * resumption"): a program that has already said why it is ending, or that
 * asked for a status, must not have that overridden by a second line about
 * what it was holding on the way out. Defined here rather than beside the
 * report because `dawn_io_exit` is the earliest of the three writers. */
static bool dawn_ctl_dying;

dawn_unit dawn_io_exit(int64_t code) {
  /* the arm that calls this may be a `ctl` handler arm holding a suspended
   * continuation; the report at exit must not turn a requested status into 70 */
  dawn_ctl_dying = true;
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
    dawn_panic(DAWN_LIT("/ by zero"));
  }
  /* INT64_MIN / -1 overflows and is UB in C; the JVM defines it as
   * wrapping back to INT64_MIN. */
  if (a == INT64_MIN && b == -1) return INT64_MIN;
  return a / b;
}

int64_t dawn_imod(int64_t a, int64_t b) {
  if (b == 0) {
    dawn_panic(DAWN_LIT("/ by zero"));
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

/* Is this a pack node? The shape test both evidence primitives make, and the
 * whole reason they are runtime calls rather than emitted C.
 *
 * Three questions, and the first one carries it. `kind` separates a pack node
 * from the boxed Unit placeholder (DAWN_K_BOX) and from a string or a closure
 * that a widened slot might be carrying; the tag and field count then
 * separate it from another record that happens to be an ADT. Only the first
 * is strictly needed today -- a walk meets nothing but pack nodes, the
 * placeholder and NULL -- and the other two are here because "the pack is a
 * scope, not a transcript of a row" means a superset can be handed over, and
 * a cheap check that cannot go wrong is worth more than an argument that it
 * never has to. */
static bool dawn_ev_is_node(const void *p) {
  if (p == NULL || ((const dawn_hdr *)p)->kind != DAWN_K_ADT) {
    return false;
  }
  const dawn_adt *node = (const dawn_adt *)p;
  return node->tag == DAWN_TAG_EV_PACK && node->nfields == DAWN_EV_PACK_FIELDS;
}

/* The evidence-pack walk; see the header, and `types.ev_pack_adt` for the
 * contract it implements. */
void *dawn_ev_get(void *pack, int64_t key) {
  void *p = pack;
  while (dawn_ev_is_node(p)) {
    dawn_adt *node = (dawn_adt *)p;
    if (node->fields[0].i == key) return node->fields[1].p;
    p = node->fields[2].p;
  }
  /* One unbroken literal on purpose: emitc's test reads this file out of
   * `rtsrc` and looks for `types.EV_MISS_MSG` in it, and C's adjacent-literal
   * concatenation would hide the text from that search. */
  dawn_panic(DAWN_LIT(
      "effect evidence missing: no pack entry for the atom this call site asked for"));
  return NULL; /* unreachable: dawn_panic does not return */
}

/* The evidence-pack join: `front`'s nodes rebuilt onto `back`, front's order
 * kept, and `front`'s own terminator dropped rather than copied so that the
 * result is one flat chain. No miss to have -- an empty `front` is an
 * ordinary answer (`back` itself), which is why only the lookup panics.
 *
 * Written forward with a running `prev`: a node's `outer` is an ordinary
 * field here, so the loop can fill it in after the fact. Neither of the other
 * two can, and each pays differently for it -- the JVM's fields are final, so
 * it reverses `front` and rebuilds, and the interpreter's values are
 * immutable, so it recurses.
 *
 * OWNERSHIP. Both arguments are BORROWED, like `dawn_ev_get`'s pack; the
 * result is OWNED, because it is freshly allocated and `rc.dawn` wraps no
 * intrinsic result -- so the emitter must not dup it, and does not. Every
 * reference the result reaches is counted for: each copied `ev` payload gets
 * a dup, the tail gets a dup of `back`, and the fresh nodes are born at rc 1
 * owned by the node in front of them. Dropping the head therefore releases
 * exactly what this function retained and nothing that it borrowed. */
void *dawn_ev_append(void *front, void *back) {
  if (!dawn_ev_is_node(front)) {
    return dawn_dup(back);
  }
  dawn_adt *head = NULL;
  dawn_adt *prev = NULL;
  void *p = front;
  while (dawn_ev_is_node(p)) {
    dawn_adt *src = (dawn_adt *)p;
    dawn_adt *node = dawn_adt_new(DAWN_TAG_EV_PACK, DAWN_EV_PACK_FIELDS, DAWN_EV_PACK_MASK);
    node->fields[0].i = src->fields[0].i;
    node->fields[1].p = dawn_dup(src->fields[1].p);
    node->fields[2].p = NULL;
    if (prev == NULL) {
      head = node;
    } else {
      prev->fields[2].p = node;
    }
    prev = node;
    p = src->fields[2].p;
  }
  prev->fields[2].p = dawn_dup(back);
  return head;
}

/* ---- handler-local cells ------------------------------------------------
 *
 * The one mutable slot in the language, and the header says why it is not a
 * hole in the cycle argument. Four functions, each of them the shortest thing
 * that can be written, because the whole content here is the counting: a
 * missed drop leaks the superseded value and a missed transfer double-frees
 * the current one, and neither shows up as a wrong answer.
 *
 * `dawn_adt` with one boxed field, so `dawn_dup` and `dawn_drop` already
 * cover a cell -- see the note at the declarations. */

/* OWNERSHIP. `x` is OWNED: the slot keeps the reference the caller hands
 * over, so nothing is dup'd here. The RESULT IS OWNED, by whoever installed
 * the handler -- it is a fresh allocation, and the emitter does not dup it. */
void *dawn_cell_new(void *x) {
  dawn_adt *c = dawn_adt_new(DAWN_TAG_CELL, DAWN_CELL_FIELDS, DAWN_CELL_MASK);
  c->fields[0].p = x;
  return c;
}

/* OWNERSHIP. `c` is BORROWED and the result is BORROWED out of the slot,
 * exactly like an ADT field read: the slot keeps its reference. The emitter
 * dups, because a Core expression hands back an owned value and `rc.dawn`
 * wraps no intrinsic result -- the same split `dawn_ev_get` has against
 * `dawn_ev_append` above. */
void *dawn_cell_get(void *c) {
  return ((dawn_adt *)c)->fields[0].p;
}

/* OWNERSHIP. `c` is BORROWED, `x` is OWNED. The reference the slot held is
 * released here, and this is the only overwrite in the runtime: everywhere
 * else a value is built once and never superseded, so there is nowhere else a
 * release could be forgotten.
 *
 * The store happens before the release, which costs nothing and removes the
 * question of what happens when `x` is the value already in the slot. Under
 * the contract that case is safe either way -- the caller's owned reference is
 * a second count -- but the order that needs no argument is the better one to
 * write down. `dawn_drop(NULL)` returns immediately, so an emptied slot (see
 * `dawn_cell_take`) is not a special case. */
void dawn_cell_set(void *c, void *x) {
  dawn_adt *cell = (dawn_adt *)c;
  void *old = cell->fields[0].p;
  cell->fields[0].p = x;
  dawn_drop(old);
}

/* OWNERSHIP. `c` is BORROWED, the RESULT IS OWNED: the slot's own reference
 * is transferred out and the slot left NULL, so the emitter does not dup and
 * the caller owes the store the header describes.
 *
 * Not `dawn_cell_get` plus a dup, and the difference is the point. A dup pins
 * a second count on the value for as long as the slot still names it, so an
 * accumulator read out of a cell is never unique and every container
 * operation on it copies instead of reusing in place. */
void *dawn_cell_take(void *c) {
  dawn_adt *cell = (dawn_adt *)c;
  void *x = cell->fields[0].p;
  cell->fields[0].p = NULL;
  return x;
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
#ifndef __wasi__
  jmp_buf jb;
#endif
  struct dawn_handler *prev;
  bool catches_panic;
  /* A bracket, as opposed to a barrier. A discard unwind (see "one-shot
   * resumption") lands at every one of these on its way to the base and runs
   * its release; it lands at no barrier, because a discard is not a failure
   * and `catch_panic`/`catch_fault` are defined not to see it. Only
   * `dawn_bracket` sets it, and the landing clears it before jumping so that
   * the walk it restarts does not meet the same frame again. */
  bool discard_lands;
#ifdef __wasi__
  /* how deep the shadow own-frame stack was when this handler was pushed:
   * the raise walk stops here (see "landing at a handler on wasm32-wasi") */
  size_t own_depth;
#endif
} dawn_handler;

/* The failure machinery is per *stack*, and since one-shot resumption a Dawn
 * program has more than one: a suspended continuation is a carrier thread
 * holding its frames (see "one-shot resumption" below), and the chain, the
 * in-flight payload and the unwinder's target all describe a walk over one
 * particular stack. Only one of those stacks runs at a time -- the handoff is
 * a mutex, so this is a change of stack and not concurrency -- but they
 * interleave: reclaiming a dropped continuation forces an unwind on its
 * carrier while the driver is itself mid-unwind, and a shared
 * `dawn_unwind_target` would have the inner walk clear the outer walk's
 * target and the outer walk would then run off the end of its stack.
 *
 * Nothing hot reads these: a bracket, a barrier, and a raise. On wasm32-wasi
 * there are no threads at all, so the qualifier is empty there. */
#ifdef __wasi__
#define DAWN_STACK_LOCAL
#else
#define DAWN_STACK_LOCAL _Thread_local
#endif

static DAWN_STACK_LOCAL dawn_handler *dawn_handlers;

/* One failure, as a value: what a raise hands to the handler that takes it.
 *
 * `msg` is a counted heap string the payload owns -- copied at the raise,
 * because the raiser's frame (and with it a `dawn_str_lit` compound literal,
 * or a heap message whose owner unwound) is gone by the time the catcher
 * reads it. A real string rather than a fixed buffer is the whole of the
 * ARC-03 fix: no length limit (the spec has no truncation clause), and no
 * cut mid-character breaking the String well-formedness invariant (#113).
 *
 * `kind` stays a static literal, not a copy: the two spellings are
 * compile-time constants, not something a raiser computes.
 *
 * `is_panic` is the kind as a bit, for the one reader that has to *route* by
 * it rather than report it: `dawn_reraise`. A re-raise that lost this would
 * offer a panic to the next `catch_fault` down the chain, which is precisely
 * the failure `catch_fault` is defined not to take (spec 9.8). Comparing the
 * kind string would work and would also make the routing depend on a name
 * the design says is the backend's own to change. */
typedef struct dawn_failure {
  dawn_str *msg;
  const char *kind;
  bool is_panic;
} dawn_failure;

/* The failure in flight, between a raise and the `setjmp` return it lands
 * on. This is global, and may be: no user code ever runs while it is
 * occupied. `dawn_raise` fills it and longjmps in the same breath, and every
 * `setjmp` branch *moves* it into the frame's own locals before doing
 * anything else. That move is the ARC-04 fix -- the old arrangement kept the
 * payload global across a bracket's `release`, which is arbitrary user code,
 * and a failure raised and caught inside the release overwrote the one
 * crossing the bracket: message, kind, and the routing bit, so `catch_fault`
 * could end up taking a panic. Now the crossing failure sits in the
 * bracket's frame, where a nested handler cannot reach it. */
static DAWN_STACK_LOCAL dawn_failure dawn_inflight;

/* A cleanup for a frame-held payload (DAWN_CLEANUP), same NULL discipline as
 * dawn_unwind_drop: a slot whose message was handed onward is cleared by the
 * hand-over, so the cleanup only fires when the payload is being abandoned
 * -- today that is one path, a bracket release escaping (see dawn_bracket).
 * Native-only: the wasi bracket rides the shadow own-frame stack instead. */
#ifndef __wasi__
static void dawn_failure_release(dawn_failure *f) {
  if (f->msg != NULL) dawn_drop(f->msg);
}
#endif

/* The innermost handler that will take a failure of this kind, or NULL. */
static dawn_handler *dawn_find_handler(bool is_panic) {
  dawn_handler *h = dawn_handlers;
  while (h != NULL && is_panic && !h->catches_panic) h = h->prev;
  return h;
}

#ifndef __wasi__
/* ---- landing at a handler: a forced unwind, not a bare longjmp ----------
 *
 * A bare `longjmp` discards every C frame between the raise and the handler
 * without running anything in them, and with it every reference those frames
 * held (#193 ARC-05, docs/native-failure-design.md route A3). So the trip
 * down is made by the platform unwinder instead: `_Unwind_ForcedUnwind`
 * walks the frames one by one and runs each one's cleanups -- the
 * `__attribute__((cleanup))` slots the C emitter puts on owned locals, real
 * landing pads because everything here is compiled with `-fexceptions`.
 *
 * The walk ends at the handler's own frame, and the frame announces itself:
 * the handler struct carries a cleanup of its own (`dawn_handler_landing`,
 * planted by `dawn_run_caught` and `dawn_bracket`), and when the unwinder
 * reaches the frame that holds the *target* handler -- pointer identity
 * against `dawn_unwind_target`, no address arithmetic -- that cleanup
 * longjmps into the handler's setjmp branch. The design's original stop
 * function compared the unwinder's CFA against the struct's address and
 * stopped at the first frame at or above it; AddressSanitizer broke that,
 * measurably: it moves locals onto its fake stack, a heap region with no
 * ordering relation to the real stack, so the comparison stopped the walk at
 * the very first frame and every landing pad between raise and handler was
 * skipped -- exactly the leak the mechanism exists to fix, visible only
 * under the sanitizer that was supposed to prove it fixed. Identity does not
 * order anything, so the fake stack cannot confuse it, and inlining cannot
 * either -- the cleanup travels with the variable, wherever its frame is.
 * The stop function is left with one job: abort loudly if the walk runs off
 * the stack, which would mean the handler chain and the real stack disagree.
 *
 * A handler frame that is merely *skipped* -- a panic passing an io barrier
 * -- runs the same cleanup, fails the identity test, and does nothing; the
 * target's setjmp branch restores the chain to its own `prev`, which drops
 * the skipped frames' entries with it, exactly as the longjmp always had.
 *
 * The exception object is static and so is this whole arrangement's
 * single-threadedness: the program runs on the runtime's one big-stack
 * thread (dawn_rt.h, "the program's stack"), same assumption the handler
 * chain itself already makes.
 *
 * This is Itanium-ABI machinery (glibc and friends); macOS and musl are
 * recorded as unverified in the design and route A1 (a shadow cleanup
 * stack) is the fallback if one of them turns out not to carry it. */
static DAWN_STACK_LOCAL struct _Unwind_Exception dawn_uexc;

static DAWN_STACK_LOCAL dawn_handler *dawn_unwind_target;

/* The three pieces of discard state, declared here because the landing above
 * reads one of them. All are per-stack: a discard of an inner activation
 * nested inside a discard of an outer one is two walks on two carriers.
 *
 *   `walking`  a discard unwind is between two landings on this stack. It is
 *              cleared while a release runs, so an ordinary failure raised
 *              inside a release finds its own handler by the ordinary rule.
 *   `discarding` the whole span, from the first forced unwind to the base.
 *              The carrier's base reads it to tell a discard from a failure.
 *   `owed`     the first failure a release raised during the walk. Lua's
 *              `__close` rule: the remaining releases still run, the first
 *              error is the one delivered, and it surfaces at the caller of
 *              `discard` once the unwind is over. */
static DAWN_STACK_LOCAL bool dawn_ctl_discard_walking;

static DAWN_STACK_LOCAL bool dawn_ctl_discarding;

static DAWN_STACK_LOCAL dawn_failure dawn_ctl_discard_owed;

/* Where the walk is going: the base handler at the bottom of this carrier.
 * Kept apart from `dawn_unwind_target`, which a failure raised by a release
 * overwrites and then clears at its own landing. */
static DAWN_STACK_LOCAL dawn_handler *dawn_ctl_discard_target;

static void dawn_uexc_cleanup(_Unwind_Reason_Code r, struct _Unwind_Exception *e) {
  (void)r;
  (void)e;
}

/* The cleanup on every handler struct. On a normal exit the target is NULL
 * and this is a comparison and nothing else.
 *
 * The second test is the discard unwind's, and it is why `discard_lands`
 * exists (see "one-shot resumption"): a discard walks to the carrier's base
 * but has to stop at every bracket on the way and run its release, which is
 * the one thing a bare drop does not do. Barriers are skipped by the same
 * predicate -- a discard is not a failure, so `catch_panic` and `catch_fault`
 * must not see it. The flag is cleared before the jump because the bracket
 * restarts the walk from its own frame, and a frame that still announced
 * itself would answer the restarted walk with itself, forever. */
static void dawn_handler_landing(dawn_handler *h) {
  if (dawn_unwind_target == h) {
    dawn_unwind_target = NULL;
    longjmp(h->jb, 1);
  }
  if (dawn_ctl_discard_walking && h->discard_lands) {
    h->discard_lands = false;
    longjmp(h->jb, 1);
  }
}

static _Unwind_Reason_Code dawn_unwind_stop(int version, _Unwind_Action actions,
                                            _Unwind_Exception_Class cls,
                                            struct _Unwind_Exception *exc,
                                            struct _Unwind_Context *ctx, void *arg) {
  (void)version;
  (void)cls;
  (void)exc;
  (void)ctx;
  (void)arg;
  if (actions & _UA_END_OF_STACK) {
    /* dawn_raise found a handler on the chain, so the walk running out of
     * stack means the chain and the stack disagree -- a runtime bug, and
     * answering quietly would turn it into a wrong answer somewhere else. */
    fflush(stdout);
    fputs("dawn: unwound past the failure handler\n", stderr);
    abort();
  }
  return _URC_NO_REASON;
}

static _Noreturn void dawn_unwind_to(dawn_handler *h) {
  dawn_unwind_target = h;
  memset(&dawn_uexc, 0, sizeof dawn_uexc);
  dawn_uexc.exception_class = 0x4441574e2d465031ULL; /* "DAWN-FP1" */
  dawn_uexc.exception_cleanup = dawn_uexc_cleanup;
  _Unwind_ForcedUnwind(&dawn_uexc, dawn_unwind_stop, NULL);
  /* ForcedUnwind only returns when the stop function never stopped it. */
  fflush(stdout);
  fputs("dawn: the unwinder returned without reaching its handler\n", stderr);
  abort();
}
#else
/* ---- landing at a handler on wasm32-wasi: the A1 shadow cleanup stack ---
 *
 * The native landing is forced unwind + longjmp, and this target has
 * neither: wasi-libc ships no setjmp and no unwinder, wasm SjLj
 * (`-mllvm -wasm-enable-sjlj`) comes out of apt's clang 18 and 20 as
 * structurally invalid modules (the setjmp dispatch loop needs a block
 * parameter the backend never emits), and `-fexceptions` on a C TU crashes
 * the wasm instruction selector outright (landingpad IR meets a
 * funclet-only isel; the #309 probe pinned both). So the two jobs the
 * unwinder did are split, and neither half needs it:
 *
 *   cleanups   Every emitted frame's own array registers on a shadow stack
 *              (DAWN_OWN_FRAME in dawn_rt.h): push at entry, pop by the
 *              same cleanup attribute that already runs on ordinary scope
 *              exits. A raise walks the stack top-down to the target
 *              handler's recorded depth and runs the drops itself -- same
 *              slots, same order (innermost first, slot 1 upward) as the
 *              forced unwind runs them natively. This is route A1 of
 *              docs/native-failure-design.md 4.1, whose reopening condition
 *              ("a target with no usable unwinder") is this target.
 *
 *   the trip   The raise then throws a wasm exception
 *              (`__builtin_wasm_throw`, out of line -- inlining it into a
 *              frame with cleanups is the isel crash again) and every
 *              barrier runs its closure under `dawn_wasi_try`, a C++
 *              `try { } catch (...) { }` in runtime/c/dawn_rt_wasi_eh.cc:
 *              C++ funclet lowering is the one shape today's clang compiles
 *              for wasm. catch(...) needs exactly two libc++abi entry
 *              points, stubbed below; no personality, no libunwind.
 *
 * A skipped handler -- a panic passing an io barrier -- catches first (its
 * try is innermost), fails the same pointer-identity test the native
 * landing uses, and throws again; the payload waits in `dawn_inflight`
 * either way, and the target's landing restores the chain to its own
 * `prev`, dropping the skipped frames' entries with it. The frames between
 * raise and handler are discarded by the wasm unwind without running
 * anything (no landing pads in C on this target) -- their drops already ran
 * off the shadow stack, so the cleanup attribute firing would be the double
 * release, not the fix.
 *
 * Engine traps (unreachable, call-stack exhaustion) are not wasm exceptions
 * and no catch here sees them -- the same "resource exhaustion passes every
 * barrier" answer the native runtime gives (spec 9.8). */
int dawn_wasi_try(void *(*body)(void *), void *ctx, void **out);

/* The two entry points a bare `catch (...)` references under -fno-rtti.
 * Identity is enough: the payload travels in `dawn_inflight`, not in the
 * exception object, so there is nothing to adjust or free here. */
void *__cxa_begin_catch(void *exc) { return exc; }
void __cxa_end_catch(void) {}

/* The shadow own-frame stack. Entries are the `dawn_own` arrays of live
 * emitted frames (slot 0 the count, slots 1..n the owned locals), plus the
 * one hand-written frame in dawn_bracket. Growable and never shrunk: the
 * high-water mark of the call stack, a few thousand entries at worst. */
static void ***dawn_wasi_owns;
static size_t dawn_wasi_own_len;
static size_t dawn_wasi_own_cap;

void dawn_wasi_own_push(void *frame) {
  if (dawn_wasi_own_len == dawn_wasi_own_cap) {
    size_t cap = dawn_wasi_own_cap == 0 ? 256 : dawn_wasi_own_cap * 2;
    void ***grown = (void ***)realloc(dawn_wasi_owns, cap * sizeof *grown);
    if (grown == NULL) {
      fputs("dawn: out of memory\n", stderr);
      exit(1);
    }
    dawn_wasi_owns = grown;
    dawn_wasi_own_cap = cap;
  }
  dawn_wasi_owns[dawn_wasi_own_len++] = (void **)frame;
}

/* LIFO by construction -- a frame pops only after everything it called has
 * returned. A mismatch means the shadow stack and the real stack disagree,
 * the same runtime bug the native stop function aborts on. */
void dawn_wasi_own_pop(void *frame) {
  if (dawn_wasi_own_len == 0 ||
      dawn_wasi_owns[dawn_wasi_own_len - 1] != (void **)frame) {
    fflush(stdout);
    fputs("dawn: own-frame shadow stack out of order\n", stderr);
    abort();
  }
  dawn_wasi_own_len--;
}

static DAWN_STACK_LOCAL dawn_handler *dawn_unwind_target;

/* Out of line and never inlined: __builtin_wasm_throw inside a frame that
 * has cleanup attributes is the isel crash from the probe. Tag 0 is the C++
 * exception tag, which is what makes catch(...) in the shim take it; the
 * token is not the payload (dawn_inflight is). */
static char dawn_wasi_exc_token;

__attribute__((noinline)) static _Noreturn void dawn_wasi_throw(void) {
  __builtin_wasm_throw(0, &dawn_wasi_exc_token);
}

static _Noreturn void dawn_unwind_to(dawn_handler *h) {
  dawn_unwind_target = h;
  while (dawn_wasi_own_len > h->own_depth) {
    void **fr = dawn_wasi_owns[--dawn_wasi_own_len];
    int64_t n = (int64_t)(intptr_t)fr[0];
    for (int64_t i = 1; i <= n; i++) {
      if (fr[i] != NULL) dawn_drop(fr[i]);
    }
  }
  dawn_wasi_throw();
}
#endif

static void dawn_raise(dawn_str *msg, bool is_panic) {
  dawn_handler *h = dawn_find_handler(is_panic);
  if (h != NULL) {
    /* The skipped frames go with it: they sit above `h`, and `h`'s own
     * setjmp branch restores the list to `h->prev`. */
    dawn_inflight.msg = dawn_str_copy(msg->p, msg->len);
    dawn_inflight.kind = is_panic ? "panic" : "fault";
    dawn_inflight.is_panic = is_panic;
    dawn_unwind_to(h);
  }
  /* Nothing stopped it, so the program is over either way -- which is why
   * both kinds report under the same word. */
  dawn_ctl_dying = true;
  fflush(stdout);
  fputs("panic: ", stderr);
  if (msg->len > 0) fwrite(msg->p, 1, (size_t)msg->len, stderr);
  fputc('\n', stderr);
  exit(1);
}

void dawn_panic(dawn_str *msg) { dawn_raise(msg, true); }

void dawn_fault(dawn_str *msg) { dawn_raise(msg, false); }

/* `ForeignError { kind, message, cause }` out of a failure payload. Three
 * reference fields, so all three mask bits: the record owns each one and a
 * drop of the whole releases them. The message *transfers* -- the payload's
 * reference becomes the record's, no copy -- which is also why every caller
 * must have moved the payload out of `dawn_inflight` first: this consumes
 * it. */
#define DAWN_MASK_THREE_BOXED UINT64_C(7)

static dawn_adt *dawn_foreign_error(dawn_failure f) {
  dawn_adt *a = dawn_adt_new(DAWN_TAG_FOREIGN_ERROR, 3, DAWN_MASK_THREE_BOXED);
  a->fields[0].p = dawn_str_copy(f.kind, (int64_t)strlen(f.kind));
  a->fields[1].p = f.msg;
  a->fields[2].p = dawn_none();
  return a;
}

/* The closure returns an erased slot whatever `T` is, so one cast covers
 * every instantiation -- see the header. */
#ifndef __wasi__
/* `f` is a Dawn `fn() -> T`, which is a one-slot function value: the written
 * parameters are none and the evidence pack is one, and `ev` is what goes in
 * it. The barriers bind `!e` over the protected closure since 2026-08-25
 * (`types.builtins`), so their ABI row is `!(e|io)`, worth one evidence slot
 * at the call site -- the same arithmetic `dawn_bracket` next door has always
 * had. It was NULL until then, which was correct while the barriers declared
 * `f: fn() -> T !io` and refused anything owing evidence at the argument, and
 * that refusal was the defect rather than the guarantee.
 *
 * The pack is borrowed like every other intrinsic argument and a closure's
 * parameters arrive owned, so the call takes a reference of its own
 * (perceus-design.md 5.1, and see dawn_bracket for the same `dawn_dup`). */
static dawn_adt *dawn_run_caught(dawn_clo *f, void *ev, bool catches_panic) {
  /* designated init so the rest (the jmp_buf) is zeroed: the landing cleanup
   * may run before setjmp has ever filled it, and reads it only behind the
   * identity test -- but a zeroed struct keeps that path defined either way */
  dawn_handler h DAWN_CLEANUP(dawn_handler_landing) = {
    .prev = dawn_handlers, .catches_panic = catches_panic
  };
  dawn_handlers = &h;
  if (setjmp(h.jb) != 0) {
    /* first thing on landing: the in-flight failure becomes this frame's.
     * Nothing has run between the raise and here, so it is still ours. */
    dawn_failure mine = dawn_inflight;
    dawn_handlers = h.prev;
    return dawn_err(dawn_foreign_error(mine));
  }
  void *v = ((void *(*)(dawn_clo *, void *))f->fn)(f, dawn_dup(ev));
  dawn_handlers = h.prev;
  return dawn_ok(v);
}
#else
/* The body needs two things and `dawn_wasi_try` carries one, so they ride a
 * struct on this frame -- the same shape `dawn_bracket`'s wasi branch uses for
 * the same reason. */
struct dawn_wasi_caught_box {
  dawn_clo *f;
  void *ev;
};

static void *dawn_wasi_caught_body(void *ctx) {
  struct dawn_wasi_caught_box *b = (struct dawn_wasi_caught_box *)ctx;
  return ((void *(*)(dawn_clo *, void *))b->f->fn)(b->f, dawn_dup(b->ev));
}

/* `f` is a Dawn `fn() -> T`, which is a one-slot function value: the written
 * parameters are none and the evidence pack is one, and `ev` is what goes in
 * it. See the native branch above for why it is a pack and not a NULL. */
static dawn_adt *dawn_run_caught(dawn_clo *f, void *ev, bool catches_panic) {
  dawn_handler h = {
    .prev = dawn_handlers,
    .catches_panic = catches_panic,
    .own_depth = dawn_wasi_own_len
  };
  dawn_handlers = &h;
  struct dawn_wasi_caught_box box = { f, ev };
  void *v = NULL;
  if (dawn_wasi_try(dawn_wasi_caught_body, &box, &v) != 0) {
    if (dawn_unwind_target != &h) {
      /* caught only because this try is innermost -- a panic passing an io
       * barrier. Hand the throw onward; the chain repair happens at the
       * target, same as the native skipped frames. */
      dawn_wasi_throw();
    }
    dawn_unwind_target = NULL;
    /* first thing on landing: the in-flight failure becomes this frame's.
     * Nothing has run between the raise and here, so it is still ours. */
    dawn_failure mine = dawn_inflight;
    dawn_handlers = h.prev;
    return dawn_err(dawn_foreign_error(mine));
  }
  dawn_handlers = h.prev;
  return dawn_ok(v);
}
#endif

dawn_adt *dawn_catch_fault(dawn_clo *f, void *ev) {
  return dawn_run_caught(f, ev, false);
}

dawn_adt *dawn_catch_panic(dawn_clo *f, void *ev) {
  return dawn_run_caught(f, ev, true);
}

/* Hand a failure this frame is holding to the next handler out.
 *
 * This is what `bracket` needs and neither barrier does: the barriers stop a
 * failure and turn it into a value, so the failure is over by the time they
 * are. A bracket takes one only to run a release, and then owes the program
 * the *same* failure -- same kind, same message -- as though nothing had
 * been protected. The payload travels by value through the bracket's frame:
 * nothing a release does can touch it, and the routing runs again by the
 * saved `is_panic` rather than by the kind string.
 *
 * With no handler left, the program is over, and it reports the message
 * whole -- the payload is a real string now, so a failure that crossed a
 * bracket prints exactly what an unprotected raise would have printed. */
static _Noreturn void dawn_reraise(dawn_failure f) {
  dawn_handler *h = dawn_find_handler(f.is_panic);
  if (h != NULL) {
    dawn_inflight = f;
    dawn_unwind_to(h);
  }
  dawn_ctl_dying = true;
  fflush(stdout);
  fputs("panic: ", stderr);
  if (f.msg->len > 0) fwrite(f.msg->p, 1, (size_t)f.msg->len, stderr);
  fputc('\n', stderr);
  dawn_drop(f.msg);
  exit(1);
}

#ifndef __wasi__
/* ---- the two halves of a bracket landing during a discard ---------------
 *
 * A discard resumes an abandoned computation with a poison and lets the
 * ordinary unwinder do the work, which is what every system that runs cleanup
 * on abandonment does (OCaml `discontinue`, Python `GeneratorExit`, Wasm
 * `resume_throw`). Here the poison is the forced unwind itself, and these two
 * are what a bracket does when it meets one: run the release, then put the
 * walk back where it was.
 *
 * A failure raised by a release does not stop the walk. Lua's `__close` is
 * the precedent and the rule is its rule: the remaining releases still run,
 * the first failure is the one kept, and it is delivered to whoever called
 * `discard` after the unwind has finished. Stopping the walk instead would
 * leave the frames below this one holding everything they hold, which is the
 * leak the discard exists to close. */
static void dawn_ctl_discard_release(dawn_clo *release, void *resource,
                                     void *ev) {
  dawn_handler g DAWN_CLEANUP(dawn_handler_landing) = {
    .prev = dawn_handlers, .catches_panic = true
  };
  /* Not walking while user code runs: a failure the release raises and
   * catches inside itself must meet the ordinary landing rule, and a bracket
   * the release opens of its own is an ordinary bracket. */
  dawn_ctl_discard_walking = false;
  dawn_handlers = &g;
  if (setjmp(g.jb) == 0) {
    dawn_drop(((void *(*)(dawn_clo *, void *, void *))release->fn)(
      release, dawn_dup(resource), dawn_dup(ev)));
    dawn_handlers = g.prev;
  } else {
    dawn_failure mine = dawn_inflight;
    dawn_handlers = g.prev;
    if (dawn_ctl_discard_owed.msg == NULL) {
      dawn_ctl_discard_owed = mine;
    } else {
      dawn_drop(mine.msg);
    }
  }
}

static _Noreturn void dawn_ctl_discard_resume(void) {
  dawn_ctl_discard_walking = true;
  dawn_unwind_to(dawn_ctl_discard_target);
}
#endif

/* `bracket(resource, release, use)` -- the parameter order is the intrinsic's:
 * the resource first, and the use-closure last.
 *
 * The resource arrives already acquired rather than as a thunk to call. That
 * is not a simplification of Haskell's `bracket` but a consequence of Dawn
 * having no asynchronous failures: nothing can raise between the caller
 * evaluating the argument and this function pushing its handler, so there is
 * no window for a thunk to close. Acquisition is ordinary code at the call
 * site, where a failure needs no release because nothing was acquired.
 *
 * The handler takes everything -- `catches_panic` is true -- because a release
 * that runs for a fault and not for a panic is not a release. It does not stop
 * anything: `dawn_reraise` hands the failure straight back to the chain, and
 * the frame is already off it by then (`dawn_handlers = h.prev`), so the next
 * handler out is found exactly as if this one had never existed.
 *
 * Counting: an intrinsic borrows its arguments (perceus-design.md 5.1), so the
 * resource stays the caller's and each closure call needs a reference of its
 * own -- a closure's parameters arrive owned and it releases them (see
 * emitc.adapter_signature). Hence one `dawn_dup` per call and none for the
 * caller's.
 *
 * The trailing `ev` each call passes is the evidence pack, and it is this
 * function's fourth parameter rather than a NULL. Every Dawn function value
 * carries one erased slot for it whatever its row (types.fn_arity), and
 * `bracket` is the one primitive that can fill it honestly: its two closures
 * share the row `e`, so its own row buys one evidence slot at the call site
 * (types.nev) and the caller packs it there. `gen_bracket` loads the same slot
 * in the same three places on the JVM.
 *
 * It was NULL until 2026-08-25, on the ground that a hand-written shim has no
 * evidence and nothing reads a pack. The second half stopped being true when
 * `ev_get` landed, and a labelled closure through `bracket` then panicked with
 * "effect evidence missing" on a program that checks clean.
 *
 * The pack is borrowed like every other intrinsic argument, and a closure's
 * parameters arrive owned, so each call takes a reference of its own -- the
 * same `dawn_dup` the resource gets, and for the same reason.
 * On the unwind path `use`'s reference is released by `use`'s own
 * frame cleanups as the forced unwind walks it -- the leak that used to sit
 * here, "the documented cost of the mechanism", is what #193 ARC-05 closed,
 * and scripts/spike-native/recover_bracket.dawn is the corpus that holds it
 * shut. The Unit each release call hands back is a box the emitter made for
 * the erased return, so it is dropped here -- nobody else can see it. */
#ifndef __wasi__
void *dawn_bracket(void *resource, dawn_clo *release, dawn_clo *use, void *ev) {
  dawn_handler h DAWN_CLEANUP(dawn_handler_landing) = {
    .prev = dawn_handlers, .catches_panic = true, .discard_lands = true
  };
  dawn_handlers = &h;
  if (setjmp(h.jb) != 0) {
    /* A discard, not a failure: nothing is in flight and nothing is owed
     * onward. Run the release and hand the walk back to where it was, which
     * is the whole of "an abandoned computation still releases what it
     * held". `dawn_handler_landing` cleared the flag on the way in, so the
     * restarted walk passes this frame instead of landing on it again. */
    if (dawn_ctl_discard_walking) {
      dawn_handlers = h.prev;
      dawn_ctl_discard_release(release, resource, ev);
      dawn_ctl_discard_resume();
    }
    /* The crossing failure becomes this frame's before the release runs:
     * `release` is arbitrary user code, and a failure it raises and swallows
     * must find `dawn_inflight` free rather than the one owed onward
     * (spec 9.8.2 guarantee 2).
     *
     * The cleanup attribute is for the release *escaping* -- raising and not
     * catching. That failure replaces the crossing one (spec 9.8.2), and the
     * unwind to whatever stops it passes through this frame, where the
     * replaced message would otherwise be the one reference nothing
     * releases. On the ordinary path the slot is handed to `dawn_reraise`
     * and cleared first, so the cleanup finds nothing to do while the
     * unwinder walks this frame on the way down. */
    dawn_failure crossing DAWN_CLEANUP(dawn_failure_release) = dawn_inflight;
    dawn_handlers = h.prev;
    dawn_drop(((void *(*)(dawn_clo *, void *, void *))release->fn)(
      release, dawn_dup(resource), dawn_dup(ev)));
    dawn_failure owed = crossing;
    crossing.msg = NULL;
    dawn_reraise(owed);
  }
  void *r = ((void *(*)(dawn_clo *, void *, void *))use->fn)(use, dawn_dup(resource),
                                                          dawn_dup(ev));
  dawn_handlers = h.prev;
  dawn_drop(
    ((void *(*)(dawn_clo *, void *, void *))release->fn)(release,
                                                        dawn_dup(resource),
                                                        dawn_dup(ev)));
  return r;
}
#else
struct dawn_wasi_use_box {
  dawn_clo *use;
  void *resource;
  void *ev;
};

static void *dawn_wasi_use_body(void *ctx) {
  struct dawn_wasi_use_box *b = (struct dawn_wasi_use_box *)ctx;
  return ((void *(*)(dawn_clo *, void *, void *))b->use->fn)(
      b->use, dawn_dup(b->resource), dawn_dup(b->ev));
}

void *dawn_bracket(void *resource, dawn_clo *release, dawn_clo *use, void *ev) {
  dawn_handler h = {
    .prev = dawn_handlers, .catches_panic = true,
    .own_depth = dawn_wasi_own_len
  };
  dawn_handlers = &h;
  struct dawn_wasi_use_box box = { use, resource, ev };
  void *r = NULL;
  if (dawn_wasi_try(dawn_wasi_use_body, &box, &r) != 0) {
    if (dawn_unwind_target != &h) {
      /* a bracket takes every kind, so a failure that lands here was
       * targeted here; anything else is the chain and the stack
       * disagreeing */
      fflush(stdout);
      fputs("dawn: a bracket caught a failure it was not the target of\n",
            stderr);
      abort();
    }
    dawn_unwind_target = NULL;
    /* Same discipline as the native branch: the crossing failure becomes
     * this frame's before the release runs (spec 9.8.2 guarantee 2). The
     * native branch guards the message with a frame cleanup for the case
     * where the release *escapes*; here the unwinder that would run it does
     * not exist, so the message rides a hand-written shadow-stack frame --
     * the raise walk of the escaping failure is what drops it. */
    dawn_failure crossing = dawn_inflight;
    dawn_handlers = h.prev;
    void *cross_own[2] = { (void *)(intptr_t)1, NULL };
    dawn_wasi_own_push(cross_own);
    cross_own[1] = crossing.msg;
    dawn_drop(((void *(*)(dawn_clo *, void *, void *))release->fn)(
      release, dawn_dup(resource), dawn_dup(ev)));
    dawn_failure owed = crossing;
    owed.msg = (dawn_str *)dawn_take(&cross_own[1]);
    dawn_wasi_own_pop(cross_own);
    dawn_reraise(owed);
  }
  dawn_handlers = h.prev;
  dawn_drop(
    ((void *(*)(dawn_clo *, void *, void *))release->fn)(release,
                                                        dawn_dup(resource),
                                                        dawn_dup(ev)));
  return r;
}
#endif

/* ---- one-shot resumption (docs/oneshot-design.md 11.10) ----------------
 *
 * A control arm receives the block's remainder as a first-class function
 * value. The route is yield bubbling (design 5): the raise site hands the
 * operation to the nearest matching installation, that installation's driver
 * runs the arm, and resuming hands a value back to the raise site.
 *
 * WHAT HOLDS THE SUSPENDED FRAMES. Not a copy of them. A copied stack is off
 * the table on this backend and the reason is structural rather than a price
 * (design 3.1): the handler chain is a list of stack addresses, a `jmp_buf`
 * holds SP/FP, and every `dawn_own` slot is a `void **` into a frame. So the
 * frames are left exactly where they are and the *stack* is what gets
 * switched: each activation runs its remainder on a carrier thread of its
 * own, and a suspension is a handoff back to the thread that drove it.
 *
 * The thread is the mechanism, not a concurrency model -- the same sentence
 * dawn_rt.h already writes about the big-stack thread, and for the same
 * reason. The handoff is a mutex and a condition variable with one baton:
 * exactly one thread runs Dawn code at any instant, and the two sides of
 * every switch are ordered by that mutex. So the non-atomic reference counts,
 * the slab's lock-free free lists and the dict-intern table keep the property
 * they were written against; what changes is that "the one stack" became "one
 * stack at a time". The three things that really were per-stack moved to
 * `DAWN_STACK_LOCAL` above.
 *
 * WHY A THREAD RATHER THAN A SIDE STACK. Three measured walls, all from the
 * recon (design 3.2), and the thread walks around each rather than fixing it:
 * `_Unwind_ForcedUnwind` aborts when it crosses a hand-made stack boundary,
 * and here it never does -- every unwind runs on one thread, from a raise to
 * a handler on that same thread's stack. AddressSanitizer prints
 * "doesn't fully support makecontext/swapcontext" on every sanitized run, and
 * the sanitized run is this project's native correctness argument; it supports
 * threads outright. And a `ucontext` switch costs two `sigprocmask` syscalls,
 * which is most of its 339 ns -- a price a handoff pays too, but neither
 * number is the binding constraint on a corpus that suspends dozens of times.
 *
 * THE SECOND EXIT, AND PERCEUS. Risk R1 in the ledger is that a captured
 * continuation gives every frame a second way out, while `c/rc.dawn`'s oracle
 * insists every binding is released exactly once on every path *assuming
 * control flow returns*. Under this arrangement there is no second exit in
 * the emitted C at all: a suspension returns from nothing, it stops running.
 * A frame's owned slots stay in the frame, which stays on the carrier. So
 * `rc.dawn` is unchanged and its oracle keeps meaning what it meant.
 *
 * What the frames need instead is a way to be released when the continuation
 * is *dropped* -- the path the recon measured LeakSanitizer to be blind to,
 * 800 KB genuinely leaked and not one report. That path is the existing #193
 * machinery pointed at its own stack: the reclaim wakes the carrier with
 * `die` set, the carrier forces an unwind of its whole stack to a base
 * handler planted at the bottom, and the unwinder runs every frame's
 * `dawn_own_drop` cleanup on the way. Exactly-once, by exactly the mechanism
 * that already holds for a raise. A bracket's `release` does *not* run on
 * that path -- the identity test in `dawn_handler_landing` fails for every
 * frame but the base -- which is what the JVM does too, where dropping a
 * `Continuation` runs no finally block.
 *
 * And because LSan cannot see this class of leak (a parked thread's stack is
 * a root, so everything it holds looks reachable), the counting is explicit:
 * `dawn_ctl_live` is asserted zero at exit, loudly, on stderr.
 *
 * FAILURES CROSS BY RELAY. A fault or panic raised inside a remainder may be
 * owed to a barrier that stands *outside* the block, on the driver's stack.
 * It cannot be unwound to directly -- that is the wall above. So each carrier
 * plants a base handler that takes every kind: the raise unwinds the carrier
 * normally (running its brackets and its drops), lands at the base, and the
 * payload is carried across the handoff and re-raised by the driver, where
 * the rest of the chain is. Kind and message travel untouched, so
 * `catch_fault` still refuses a panic that crossed a suspension. */
#ifndef __wasi__

/* The widest operation a control arm can answer, and the same number the JVM
 * caps at (`rtclasses.ctl_max_op_params`): an arm takes the operation's
 * parameters, the continuation and the evidence slot. */
#define DAWN_CTL_MAX_ARGS 7

typedef struct dawn_carrier dawn_carrier;

typedef struct dawn_ctl {
  dawn_hdr h;
  int64_t hid;   /* the installation's identity; the prompt */
  /* The one-shot token. A continuation is valid exactly while it equals this,
   * and resuming bumps it -- so a second call of one continuation and a call
   * of a continuation superseded by a later suspension are the same test. */
  int64_t gen;
  struct dawn_ctl *prev; /* the prompt chain, borrowed: frames outlive it */
  dawn_carrier *carrier;
  void *rest; /* owned: the block's remainder, a `fn() -> A` value */
  void *evs;  /* owned: the pack the remainder is applied with */
  /* Set by a yield and taken by the drive that answers it, both borrowed --
   * the raise site's frame is suspended, not gone, so it still holds them. */
  void *arm;
  void *env;
  void *args[DAWN_CTL_MAX_ARGS];
  int64_t nargs;
  void *result; /* owned: what the remainder produced */
  void *resume; /* owned in, transferred out at the raise site */
  bool failed;
  /* This activation's `drive` frame is parked in the bubble loop -- a
   * suspension went past this prompt and froze the driver with it, so the
   * frame sits on the stack of whichever activation the bubble reached. That
   * is the one shape "an inner handler activation inside the frozen span" can
   * take, and discarding the outer one discards this one too. The JVM needs
   * no flag for it: the poison is thrown at a raise site *below* the inner
   * driver's frame and unwinds through it on the way out. */
  bool bubbling;
  dawn_failure fail;
} dawn_ctl;

struct dawn_carrier {
  pthread_t th;
  pthread_mutex_t m;
  pthread_cond_t cv;
  /* the baton: 1 = the carrier runs, 0 = whoever drove it runs */
  int turn;
  bool spawned;
  bool finished;
  bool joined;
  bool die;
  /* `die` says the stack is going away; this says whether the brackets on it
   * get to release what they hold. False for a bare drop, true for `discard`. */
  bool run_releases;
  dawn_ctl *act;
};

/* The prompt chain. A plain global and not `DAWN_STACK_LOCAL`, and that is
 * the difference from the handler chain next door: the failure chain
 * describes one stack, while the prompt chain is the *logical* Dawn stack,
 * which now spans carriers. A raise deep inside an inner remainder has to see
 * the outer installation, and the frame that pushed it is parked on another
 * thread. The JVM keeps this in a ThreadLocal for the same reason it can:
 * there, one thread holds every frozen frame. */
static dawn_ctl *dawn_ctl_top;

/* The activation a suspension in flight is aimed at. Read by every drive the
 * yield bubbles through, and one is in flight at a time by the same argument
 * `dawn_inflight` makes: no user code runs while it is occupied. */
static dawn_ctl *dawn_ctl_pending;

/* The carrier whose stack is running Dawn code, or NULL for the big-stack
 * thread. Saved and restored around every handoff. */
static dawn_carrier *dawn_ctl_cur;

/* Carriers alive: spawned and not yet reclaimed. THE MEMORY ORACLE FOR
 * DROPPED CONTINUATIONS. LeakSanitizer answers nothing here and it was
 * measured answering nothing (see the heading), because a parked thread's
 * stack is a root and everything the suspended frames hold is reachable from
 * it. A count that has to come back to zero is the check that can fail. */
static int64_t dawn_ctl_live;

/* How many discards are in progress program-wide. A global and not per-stack,
 * unlike the three flags next to `dawn_unwind_target`, because it answers a
 * different question: those describe *a walk*, this one is the ban -- no `ctl`
 * operation may suspend anywhere while a discard is running, the strictness
 * Python spells "generator ignored GeneratorExit". A release runs on the
 * carrier being discarded, but a release may also resume some other
 * continuation, which runs on a third stack, and the ban covers that too. One
 * baton means one Dawn stack at a time, so a plain counter is enough. */
static int64_t dawn_ctl_discard_depth;

static void dawn_ctl_report(void) {
  if (dawn_ctl_dying || dawn_ctl_live == 0) return;
  fflush(stdout);
  fprintf(stderr, "dawn: %lld suspended continuation(s) still live at exit\n",
          (long long)dawn_ctl_live);
  _exit(70);
}

static bool dawn_ctl_report_registered;

/* One baton, two waits. `switch_to` is what a driver calls; `hand_back` is
 * what the carrier calls, and it returns when someone resumes it -- or never,
 * because a reclaim answers `die` by unwinding instead. */
static void dawn_ctl_switch_to(dawn_carrier *c) {
  dawn_carrier *saved = dawn_ctl_cur;
  /* Nothing hands the baton to a carrier that has run out: the one-shot token
   * on the continuation is what stops a second resumption, and every other
   * caller here tests `finished` first. So this is the same kind of assertion
   * `dawn_unwind_stop` makes about the handler chain, and it is worth having
   * for the same reason: without it the failure is a wait nobody will ever
   * answer, which reads as a hang rather than as a bug. */
  if (c->finished) {
    fflush(stdout);
    fputs("dawn: a continuation was resumed after its stack ran out\n", stderr);
    abort();
  }
  pthread_mutex_lock(&c->m);
  c->turn = 1;
  pthread_cond_broadcast(&c->cv);
  while (c->turn == 1) pthread_cond_wait(&c->cv, &c->m);
  pthread_mutex_unlock(&c->m);
  dawn_ctl_cur = saved;
}

/* Abandon this carrier's stack: force an unwind of every frame down to the
 * base handler this carrier planted. `run_releases` is the difference between
 * the two ways a continuation ends without being resumed. A bare drop runs
 * nothing a program wrote -- only `dawn_own_drop`, which the unwinder runs
 * whatever anyone asked for, because reference counting is not a cleanup the
 * program can observe. An explicit `discard` also lands at every bracket on
 * the way and runs its release. */
static _Noreturn void dawn_ctl_discard(bool run_releases) {
  dawn_handler *h = dawn_handlers;
  while (h != NULL && h->prev != NULL) h = h->prev;
  if (h == NULL) {
    fflush(stdout);
    fputs("dawn: a carrier has no base handler to discard to\n", stderr);
    abort();
  }
  dawn_ctl_discarding = true;
  dawn_ctl_discard_target = h;
  dawn_ctl_discard_walking = run_releases;
  dawn_unwind_to(h);
}

static void dawn_ctl_hand_back(dawn_carrier *c) {
  pthread_mutex_lock(&c->m);
  c->turn = 0;
  pthread_cond_broadcast(&c->cv);
  while (c->turn == 0) pthread_cond_wait(&c->cv, &c->m);
  pthread_mutex_unlock(&c->m);
  dawn_ctl_cur = c;
  if (c->die) dawn_ctl_discard(c->run_releases);
}

/* The last handoff: the carrier is done and nothing will resume it. */
static void dawn_ctl_hand_back_final(dawn_carrier *c) {
  pthread_mutex_lock(&c->m);
  c->finished = true;
  c->turn = 0;
  pthread_cond_broadcast(&c->cv);
  pthread_mutex_unlock(&c->m);
}

static void *dawn_ctl_carrier_main(void *arg) {
  dawn_carrier *c = (dawn_carrier *)arg;
  dawn_ctl *f = c->act;
  pthread_mutex_lock(&c->m);
  while (c->turn == 0) pthread_cond_wait(&c->cv, &c->m);
  pthread_mutex_unlock(&c->m);
  dawn_ctl_cur = c;
  if (!c->die) {
    /* The base of this stack. It takes every kind, and it is the only thing
     * on the chain that this carrier's own frames can unwind to -- see
     * "failures cross by relay" in the heading. Designated init so the
     * jmp_buf is zeroed before the landing cleanup can ever read it, the same
     * discipline `dawn_run_caught` writes for the same reason. */
    dawn_handler base DAWN_CLEANUP(dawn_handler_landing) = {
      .prev = NULL, .catches_panic = true
    };
    dawn_handlers = &base;
    if (setjmp(base.jb) == 0) {
      dawn_clo *r = (dawn_clo *)f->rest;
      f->result = ((void *(*)(dawn_clo *, void *))r->fn)(r, dawn_dup(f->evs));
    } else if (dawn_ctl_discarding) {
      dawn_ctl_discarding = false;
      dawn_ctl_discard_walking = false;
      dawn_ctl_discard_target = NULL;
      /* A release that failed during the walk owes its failure to whoever
       * asked for the discard. It travels the way every other failure out of
       * a carrier travels -- by relay, in the activation -- and `discard`
       * re-raises it once the stack it came from is gone. */
      if (dawn_ctl_discard_owed.msg != NULL) {
        f->fail = dawn_ctl_discard_owed;
        f->failed = true;
        dawn_ctl_discard_owed.msg = NULL;
      }
    } else {
      /* first thing on landing, exactly as every other setjmp branch here */
      f->fail = dawn_inflight;
      f->failed = true;
    }
    dawn_handlers = NULL;
  }
  dawn_ctl_hand_back_final(c);
  return NULL;
}

/* 64 MiB of address space, not memory: the pages are touched only as the
 * stack grows, the same arrangement DAWN_STACK_BYTES describes. Smaller than
 * the big stack because a remainder is a block's tail rather than a whole
 * program, and because there is one of these per live activation. */
#define DAWN_CTL_STACK_BYTES ((size_t)64 << 20)

static dawn_carrier *dawn_ctl_carrier_new(dawn_ctl *f) {
  pthread_attr_t at;
  dawn_carrier *c = (dawn_carrier *)dawn_alloc(sizeof *c);
  memset(c, 0, sizeof *c);
  c->act = f;
  if (pthread_mutex_init(&c->m, NULL) != 0 || pthread_cond_init(&c->cv, NULL) != 0) {
    fputs("dawn: cannot make a continuation carrier\n", stderr);
    exit(1);
  }
  if (!dawn_ctl_report_registered) {
    atexit(dawn_ctl_report);
    dawn_ctl_report_registered = true;
  }
  if (pthread_attr_init(&at) != 0) {
    fputs("dawn: cannot make a continuation carrier\n", stderr);
    exit(1);
  }
  (void)pthread_attr_setstacksize(&at, DAWN_CTL_STACK_BYTES);
  if (pthread_create(&c->th, &at, dawn_ctl_carrier_main, c) != 0) {
    pthread_attr_destroy(&at);
    fputs("dawn: cannot make a continuation carrier\n", stderr);
    exit(1);
  }
  pthread_attr_destroy(&at);
  c->spawned = true;
  dawn_ctl_live++;
  return c;
}

/* Give the carrier back, whether it ran out or is being abandoned. An
 * abandoned one is told to `die` and handed the baton: it unwinds its whole
 * stack to the base handler, running every frame's cleanup, and finishes.
 * `run_releases` also lands the walk at every bracket on the way; see
 * `dawn_ctl_discard`. */
static void dawn_ctl_carrier_reclaim(dawn_carrier *c, bool run_releases) {
  /* A stack cannot discard itself: the discard is an unwind of the carrier's
   * frames, and the frame that asked for it is one of them. Reachable, barely
   * -- a remainder that ends up holding the last reference to a continuation
   * over its own activation, which takes an operation whose result type
   * contains the continuation. Refusing by name beats waiting for a baton
   * nobody will pass, which is the same trade the test above makes. */
  if (c == dawn_ctl_cur) {
    fflush(stdout);
    fputs("dawn: a suspended computation dropped the last reference to its "
          "own continuation\n", stderr);
    abort();
  }
  if (!c->finished) {
    c->die = true;
    c->run_releases = run_releases;
    dawn_ctl_switch_to(c);
  }
  if (!c->joined) {
    pthread_join(c->th, NULL);
    c->joined = true;
  }
  pthread_mutex_destroy(&c->m);
  pthread_cond_destroy(&c->cv);
  dawn_ctl_live--;
  free(c);
}

/* `dawn_drop` reaching a DAWN_K_CTL. The frames this activation is holding go
 * first: they own references, and the walk that releases them has to run on
 * the carrier's own stack. `dawn_drop` frees the struct itself afterwards.
 *
 * THE ONE CASE THAT INHERITS A DISCARD. Two facts decide the third parameter.
 * A drop here is a bare drop and a bare drop runs no release -- that is the
 * ruling, and it is what a JVM program does too, where an unreachable
 * `Continuation` runs no finally. But an inner activation whose driver is
 * parked in the bubble loop is *inside* the outer computation's frozen span,
 * not merely a value it holds, and on the JVM the poison thrown to discard the
 * outer one physically unwinds through the inner driver's frame and every
 * bracket below it. So the two backends agree only if that one case inherits,
 * and `bubbling` is exactly it. `walking` rather than `discarding` is the test
 * for the same reason: a continuation dropped by ordinary code inside a
 * release is a bare drop like any other. */
static void dawn_ctl_dispose(void *p) {
  dawn_ctl *f = (dawn_ctl *)p;
  dawn_ctl *saved_top = dawn_ctl_top;
  dawn_ctl *saved_pending = dawn_ctl_pending;
  if (f->carrier != NULL) {
    dawn_ctl_carrier_reclaim(f->carrier, dawn_ctl_discard_walking && f->bubbling);
    f->carrier = NULL;
  }
  /* A reclaim runs arbitrary Dawn cleanup on another stack, and a nested
   * activation inside it drives and pops the chain as it goes. Neither is
   * this walk's business, so both are put back. */
  dawn_ctl_top = saved_top;
  dawn_ctl_pending = saved_pending;
  dawn_drop(f->rest);
  dawn_drop(f->evs);
  dawn_drop(f->result);
  dawn_drop(f->resume);
  if (f->failed && f->fail.msg != NULL) dawn_drop(f->fail.msg);
}

/* The innermost activation of this prompt, or a panic.
 *
 * The miss is a panic and not a fault for `ev_get`'s reason: an operation
 * with no handler is a program the checker refuses, so arriving here means an
 * invariant broke. The one way a *correct* program gets here is the residual
 * design 11.6 H1 leaves open, and the message names it. Word for word the
 * JVM's, because the differential compares stderr. */
static dawn_ctl *dawn_ctl_lookup(int64_t hid) {
  dawn_ctl *f = dawn_ctl_top;
  while (f != NULL) {
    if (f->hid == hid) return f;
    f = f->prev;
  }
  dawn_panic(DAWN_LIT("dawn: no `ctl` handler is installed for this operation "
                      "-- a suspendable function value was called from outside "
                      "the `with handle` that answers it"));
  return NULL;
}

static void *dawn_ctl_drive(dawn_ctl *f);

/* The continuation, as an ordinary Dawn function value: `fn(R) -> A` with a
 * pure row, so one written parameter plus the evidence slot every function
 * value carries (design 11.2). Capture 0 is the activation and is counted;
 * capture 1 is the one-shot token and is a scalar, so the mask is 1. */
static void *dawn_ctl_k_apply(dawn_clo *self, void *v, void *ev) {
  dawn_ctl *f = (dawn_ctl *)self->caps[0].p;
  if (self->caps[1].i != f->gen) {
    dawn_drop(v);
    dawn_drop(ev);
    dawn_panic(DAWN_LIT("dawn: continuation resumed twice"));
  }
  /* This pack answers nothing: the one the remainder needs was built at the
   * installation and is inside the suspended frames already (design 11.2). */
  dawn_drop(ev);
  f->gen++;
  f->resume = v; /* transferred; the raise site's `yield` takes it out */
  return dawn_ctl_drive(f);
}

static dawn_clo *dawn_ctl_k_new(dawn_ctl *f) {
  dawn_clo *k = dawn_clo_new((void *)dawn_ctl_k_apply, 2, UINT64_C(1));
  k->caps[0].p = dawn_dup(f);
  k->caps[1].i = f->gen;
  return k;
}

/* Apply the arm: its parameters, then the continuation, then the pack the
 * handler was installed with. A chain on the argument count for the JVM's
 * reason -- which arm suspended is not known until it does -- and the
 * arguments are borrowed here and owned by a closure's parameters, so each
 * one is duplicated exactly like `dawn_bracket` duplicates its resource. */
static void *dawn_ctl_apply_arm(dawn_clo *arm, int64_t n, void **args,
                                dawn_clo *k, void *env) {
  void *e = dawn_dup(env);
  switch (n) {
    case 0:
      return ((void *(*)(dawn_clo *, void *, void *))arm->fn)(arm, k, e);
    case 1:
      return ((void *(*)(dawn_clo *, void *, void *, void *))arm->fn)(
        arm, dawn_dup(args[0]), k, e);
    case 2:
      return ((void *(*)(dawn_clo *, void *, void *, void *, void *))arm->fn)(
        arm, dawn_dup(args[0]), dawn_dup(args[1]), k, e);
    case 3:
      return ((void *(*)(dawn_clo *, void *, void *, void *, void *, void *))arm->fn)(
        arm, dawn_dup(args[0]), dawn_dup(args[1]), dawn_dup(args[2]), k, e);
    case 4:
      return ((void *(*)(dawn_clo *, void *, void *, void *, void *, void *,
                         void *))arm->fn)(
        arm, dawn_dup(args[0]), dawn_dup(args[1]), dawn_dup(args[2]),
        dawn_dup(args[3]), k, e);
    case 5:
      return ((void *(*)(dawn_clo *, void *, void *, void *, void *, void *,
                         void *, void *))arm->fn)(
        arm, dawn_dup(args[0]), dawn_dup(args[1]), dawn_dup(args[2]),
        dawn_dup(args[3]), dawn_dup(args[4]), k, e);
    case 6:
      return ((void *(*)(dawn_clo *, void *, void *, void *, void *, void *,
                         void *, void *, void *))arm->fn)(
        arm, dawn_dup(args[0]), dawn_dup(args[1]), dawn_dup(args[2]),
        dawn_dup(args[3]), dawn_dup(args[4]), dawn_dup(args[5]), k, e);
    case 7:
      return ((void *(*)(dawn_clo *, void *, void *, void *, void *, void *,
                         void *, void *, void *, void *))arm->fn)(
        arm, dawn_dup(args[0]), dawn_dup(args[1]), dawn_dup(args[2]),
        dawn_dup(args[3]), dawn_dup(args[4]), dawn_dup(args[5]),
        dawn_dup(args[6]), k, e);
    default:
      break;
  }
  dawn_panic(DAWN_LIT("dawn: a control arm answers an operation with more "
                      "than 7 parameters"));
  return NULL;
}

/* Run this activation until it either finishes or suspends into *this*
 * prompt, and answer the block either way.
 *
 * Finished: the block's value is what the remainder produced. Suspended here:
 * the arm gets the operation's arguments and a fresh continuation, and the
 * arm's value is the block's value (design 11.1). Suspended past here: the
 * loop parks the stack this drive is running on and the bubble carries on
 * outward, which is the whole of "a yield bubbles past handlers it is not
 * for". Nothing iterates for a resumption -- resuming is a call to `k` and
 * `k` calls this again -- so a handler that resumes ten times is ten nested
 * drives, which is what makes a dropped continuation cost nothing but its
 * carrier. */
static void *dawn_ctl_drive(dawn_ctl *f) {
  dawn_clo *arm;
  dawn_clo *k;
  void *env;
  void *args[DAWN_CTL_MAX_ARGS];
  int64_t n;
  int64_t i;
  /* Read here rather than kept from the first entry: a continuation resumed
   * somewhere else is answered by the handlers standing *there*, which is the
   * whole of "k is deep up to this prompt and no further". */
  f->prev = dawn_ctl_top;
  dawn_ctl_top = f;
  for (;;) {
    dawn_ctl_switch_to(f->carrier);
    if (f->carrier->finished) {
      dawn_ctl_top = f->prev;
      if (f->failed) {
        dawn_failure owed = f->fail;
        f->failed = false;
        f->fail.msg = NULL;
        dawn_reraise(owed);
      }
      {
        void *r = f->result;
        f->result = NULL;
        return r;
      }
    }
    if (dawn_ctl_pending == f) break;
    /* Not this prompt. This drive's own frame is part of what the suspension
     * captured, so it stops running too and the baton goes one further out;
     * it is a carrier that is running when that happens, never the big-stack
     * thread, because `lookup` already found the target on the chain. */
    if (dawn_ctl_cur == NULL) {
      fflush(stdout);
      fputs("dawn: a suspension bubbled past every prompt\n", stderr);
      abort();
    }
    f->bubbling = true;
    dawn_ctl_hand_back(dawn_ctl_cur);
    f->bubbling = false;
  }
  dawn_ctl_pending = NULL;
  dawn_ctl_top = f->prev;
  /* Take the pending operation out of the activation before the arm runs: the
   * arm may resume, and a resumed remainder may raise again into this one. */
  arm = (dawn_clo *)f->arm;
  env = f->env;
  n = f->nargs;
  for (i = 0; i < n; i++) args[i] = f->args[i];
  f->arm = NULL;
  f->env = NULL;
  f->nargs = 0;
  k = dawn_ctl_k_new(f);
  return dawn_ctl_apply_arm(arm, n, args, k, env);
}

static void dawn_ctl_slot_drop(dawn_ctl **slot) {
  if (*slot != NULL) dawn_drop(*slot);
}

void *dawn_ctl_enter(int64_t hid, void *rest, void *evs) {
  /* The activation is released by a cleanup rather than at the return, so
   * that a failure or a discard unwinding through this frame releases it too
   * -- and with it the carrier, if no continuation escaped holding one. */
  dawn_ctl *f DAWN_CLEANUP(dawn_ctl_slot_drop) = dawn_alloc(sizeof(dawn_ctl));
  memset(f, 0, sizeof *f);
  dawn_hdr_init(&f->h, DAWN_K_CTL);
  f->hid = hid;
  f->rest = dawn_dup(rest);
  f->evs = dawn_dup(evs);
  f->carrier = dawn_ctl_carrier_new(f);
  return dawn_ctl_drive(f);
}

void *dawn_ctl_yield(int64_t hid, void *arm, void *env, int64_t nargs,
                     void **args) {
  dawn_ctl *f;
  dawn_ctl *saved;
  int64_t i;
  void *v;
  /* The release-discipline ban (docs/oneshot-design.md 11.12). A discard is
   * an unwind, and an unwind that suspends is an unwind that may never
   * finish: the frames below it are already committed to going away, and
   * nothing can resume into them. Python answers the same question the same
   * way, by name -- "generator ignored GeneratorExit". A release may do io,
   * may fail, may open a bracket of its own; it may not suspend. */
  if (dawn_ctl_discard_depth > 0) {
    dawn_panic(DAWN_LIT("dawn: a `ctl` operation was raised while a "
                        "continuation was being discarded"));
  }
  f = dawn_ctl_lookup(hid);
  if (nargs > DAWN_CTL_MAX_ARGS) {
    dawn_panic(DAWN_LIT("dawn: a control arm answers an operation with more "
                        "than 7 parameters"));
  }
  f->arm = arm;
  f->env = env;
  f->nargs = nargs;
  for (i = 0; i < nargs; i++) f->args[i] = args[i];
  dawn_ctl_pending = f;
  /* The prompts between this raise and the target are saved across the
   * suspension and put back on the way in. Every drive between here and `f`
   * stops in the loop above without popping its own frame off the chain, and
   * nothing re-pushes them when the outer prompt resumes. Restoring the saved
   * head restores the right chain rather than a stale one, because the
   * activations are shared objects and `drive` rewrites `prev` on every
   * entry: the saved head still ends at `f`, and `f`'s `prev` is whatever was
   * installed where the resumption happened. That is the deep-handler rule
   * and the "resumed somewhere else" rule in one line. */
  saved = dawn_ctl_top;
  if (dawn_ctl_cur == NULL) {
    fflush(stdout);
    fputs("dawn: a `ctl` operation was raised outside every carrier\n", stderr);
    abort();
  }
  dawn_ctl_hand_back(dawn_ctl_cur);
  dawn_ctl_top = saved;
  v = f->resume;
  f->resume = NULL;
  return v;
}

/* `discard(k)` -- abandon a computation and let it release what it holds.
 *
 * WHAT IT IS. Every system in the survey that runs cleanup on abandonment
 * turns the drop into a run: an abort is injected at the suspension point and
 * the ordinary unwinder does the rest (OCaml `discontinue`, Wasm
 * `resume_throw`, Python `GeneratorExit`, Koka `k(Finalize(v))`). Here the
 * injected abort is the forced unwind of the carrier and the "ordinary
 * unwinder" is #193's, so this function is mostly bookkeeping around
 * `dawn_ctl_carrier_reclaim`.
 *
 * WHY THE CHECK IS DYNAMIC. `k` is an ordinary `fn(R) -> A` (design 11.2) and
 * nothing in the type says which function values are continuations. So this
 * asks the value: a closure whose code pointer is `dawn_ctl_k_apply` and
 * nothing else. That is the same discipline one-shot itself runs under -- the
 * type does not say "at most once" either, and the second call is a panic.
 *
 * THE TICKET. `gen` is bumped here exactly as a resumption bumps it, so
 * discard-then-resume, resume-then-discard and discard-twice are one test and
 * one family of messages.
 *
 * The argument is borrowed, like every intrinsic's (perceus-design.md 5.1).
 * `ev` is the evidence slot the `!e` binder buys and is not read: the
 * continuation carries its own pack (see the header). */
dawn_unit dawn_discard(void *kv, void *ev) {
  dawn_clo *k;
  dawn_ctl *f;
  dawn_carrier *c;
  (void)ev;
  if (kv == NULL || ((dawn_hdr *)kv)->kind != DAWN_K_CLO ||
      ((dawn_clo *)kv)->fn != (void *)dawn_ctl_k_apply) {
    dawn_panic(DAWN_LIT("dawn: `discard` expects a continuation"));
  }
  k = (dawn_clo *)kv;
  f = (dawn_ctl *)k->caps[0].p;
  if (k->caps[1].i != f->gen) {
    dawn_panic(DAWN_LIT("dawn: continuation discarded after it was already "
                        "used"));
  }
  f->gen++;
  c = f->carrier;
  if (c != NULL) {
    dawn_ctl_discard_depth++;
    dawn_ctl_carrier_reclaim(c, true);
    f->carrier = NULL;
    dawn_ctl_discard_depth--;
    /* A release failed on the way down. The walk finished first -- every
     * other release still ran -- and the failure is delivered here, where the
     * caller of `discard` stands. */
    if (f->failed) {
      dawn_failure owed = f->fail;
      f->failed = false;
      f->fail.msg = NULL;
      dawn_reraise(owed);
    }
  }
  return DAWN_UNIT;
}

#else

/* wasm32-wasi has no threads, and the reason one-shot resumption stops here
 * is not the missing primitive: every turn re-enters `main` from scratch
 * (nmain's reactor driver), so no Dawn stack survives a turn boundary, which
 * is the only place a reactor would want to suspend one (design 3.4). The
 * refusal is at run time rather than in the emitter because the emitter is
 * shared: the same C is compiled for both targets. */
void *dawn_ctl_enter(int64_t hid, void *rest, void *evs) {
  (void)hid;
  (void)rest;
  (void)evs;
  dawn_panic(DAWN_LIT("dawn: one-shot resumption is not available on wasm"));
  return NULL;
}

void *dawn_ctl_yield(int64_t hid, void *arm, void *env, int64_t nargs,
                     void **args) {
  (void)hid;
  (void)arm;
  (void)env;
  (void)nargs;
  (void)args;
  dawn_panic(DAWN_LIT("dawn: one-shot resumption is not available on wasm"));
  return NULL;
}

dawn_unit dawn_discard(void *kv, void *ev) {
  (void)kv;
  (void)ev;
  dawn_panic(DAWN_LIT("dawn: one-shot resumption is not available on wasm"));
  return DAWN_UNIT;
}

#endif

/* ---- code-point classification (char_is_*) ---------------------------- */

/* Membership in a sorted, disjoint set of ranges (dawn_rt.h). Out-of-range and
 * negative inputs fall out as false, which is the answer: the intrinsic takes
 * an Int and nothing says it is a code point. */
static bool dawn_cp_in(int64_t c, const dawn_cp_range *rs, size_t n) {
  /* n == 0 is not an empty set -- no real table is empty. It is the emitter
   * saying nothing reachable reads this one (reach.dawn), so getting here
   * means the pruning was wrong; answer loudly rather than "false". */
  if (n == 0) dawn_panic(DAWN_LIT("unicode table pruned but reached"));
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
    dawn_panic(DAWN_LIT("Array index out of bounds"));
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
    dawn_panic(DAWN_LIT("Array index out of bounds"));
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

uint64_t dawn_array_steal_taken = 0;
uint64_t dawn_array_steal_dup = 0;

/* Borrows `a` and answers an owned reference to slot `i`. Alone -- the array
 * and its buffer both unique, the same test `dawn_array_with` runs and for
 * the same reason: an array at rc 1 may still share its buffer with another
 * version whose slot this is too -- the slot's own reference is transferred
 * out and the slot left NULL. Shared, this is get+dup: someone else may still
 * read the slot, so its reference stays put.
 *
 * The caller's obligation on the unique path: overwrite slot `i` before
 * anything reads it (std/pvec steals a child and hands the array straight to
 * `dawn_array_with` on the same slot). Dropping the array instead is safe --
 * the release walk skips NULL slots -- but a read of the emptied slot is not.
 * Under --rc=leak counts only grow, so rc==1 cannot prove uniqueness and the
 * transfer is skipped, exactly as in `dawn_array_with`. */
void *dawn_array_steal(dawn_array *a, int64_t i) {
  if (i < 0 || i >= (int64_t)a->len) {
    dawn_panic(DAWN_LIT("Array index out of bounds"));
  }
  if (!dawn_rc_leak && dawn_is_unique(a) && dawn_is_unique(a->buf)) {
    dawn_array_steal_taken++;
    void *x = a->buf->data[i];
    a->buf->data[i] = NULL;
    return x;
  }
  dawn_array_steal_dup++;
  return dawn_dup(a->buf->data[i]);
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

/* `dawn_utf8_seq`, `dawn_utf8_boundary` and `dawn_utf8_at` above assume what
 * they walk is well-formed, and they are entitled to: every string the runtime
 * builds is built from valid UTF-8 or from a code point, and the doors foreign
 * bytes come through -- `dawn_bytes_decode_utf8` and `dawn_str_from_os` --
 * both validate. Do not make them strict -- they are on the cursor and case
 * paths, and the cost would be paid on every character of every lexer run.
 *
 * (The io_* readers used to copy operating-system bytes into a string without
 * looking at them, which is how a `c0 af` in a filename became a `/`. They go
 * through the walker now; #113 is that half, #112 was the decoder.)
 *
 * Strict UTF-8, for the decoder below. Rejects the overlong forms, the
 * surrogate halves and anything above U+10FFFF; on malformed input it answers
 * U+FFFD and reports, in `*n`, how many bytes go with that one replacement.
 * The rules are the JVM's, byte for byte, because `bytes_decode_utf8` has to
 * answer what `new String(bytes, UTF_8)` answers and
 * scripts/spike-native/bytes_decode.dawn compares them. */

static bool dawn_utf8_cont(unsigned char b) { return (b & 0xC0u) == 0x80u; }

/* The second byte of a three-byte sequence: E0 80..9F would be an overlong
 * form, and a non-continuation ends the sequence early. */
static bool dawn_utf8_bad3_2(unsigned char b1, unsigned char b2) {
  return (b1 == 0xE0u && (b2 & 0xE0u) == 0x80u) || !dawn_utf8_cont(b2);
}

/* The second byte of a four-byte sequence: below F0 90 is overlong, above
 * F4 8F is past U+10FFFF. */
static bool dawn_utf8_bad4_2(unsigned char b1, unsigned char b2) {
  return (b1 == 0xF0u && (b2 < 0x90u || b2 > 0xBFu)) ||
         (b1 == 0xF4u && (b2 & 0xF0u) != 0x80u) || !dawn_utf8_cont(b2);
}

/* One step: the code point starting at `i`, or U+FFFD for a malformed
 * sequence. `*n` is how far to advance -- never zero, so this terminates. */
static uint32_t dawn_utf8_step(const unsigned char *p, int64_t len, int64_t i,
                               int64_t *n) {
  unsigned char b1 = p[i];
  int64_t rest = len - i - 1;
  if (b1 < 0x80u) {
    *n = 1;
    return b1;
  }
  /* C0 and C1 lead only overlong forms, so the two-byte leads start at C2 */
  if (b1 >= 0xC2u && b1 <= 0xDFu) {
    if (rest >= 1 && dawn_utf8_cont(p[i + 1])) {
      *n = 2;
      return ((uint32_t)(b1 & 0x1Fu) << 6) | (uint32_t)(p[i + 1] & 0x3Fu);
    }
    *n = 1;
    return 0xFFFDu;
  }
  if (b1 >= 0xE0u && b1 <= 0xEFu) {
    if (rest >= 2) {
      unsigned char b2 = p[i + 1], b3 = p[i + 2];
      if (dawn_utf8_bad3_2(b1, b2)) {
        *n = 1;
        return 0xFFFDu;
      }
      if (!dawn_utf8_cont(b3)) {
        *n = 2;
        return 0xFFFDu;
      }
      uint32_t cp = ((uint32_t)(b1 & 0x0Fu) << 12) |
                    ((uint32_t)(b2 & 0x3Fu) << 6) | (uint32_t)(b3 & 0x3Fu);
      *n = 3;
      /* a surrogate half is not a code point a string may hold, and unlike
       * the two checks above this one costs the whole sequence */
      return (cp >= 0xD800u && cp <= 0xDFFFu) ? 0xFFFDu : cp;
    }
    /* cut short by the end of the input */
    if (rest == 1 && dawn_utf8_bad3_2(b1, p[i + 1])) {
      *n = 1;
      return 0xFFFDu;
    }
    *n = rest + 1;
    return 0xFFFDu;
  }
  if (b1 >= 0xF0u && b1 <= 0xF7u) {
    if (rest >= 3) {
      unsigned char b2 = p[i + 1], b3 = p[i + 2], b4 = p[i + 3];
      uint32_t cp =
          ((uint32_t)(b1 & 0x07u) << 18) | ((uint32_t)(b2 & 0x3Fu) << 12) |
          ((uint32_t)(b3 & 0x3Fu) << 6) | (uint32_t)(b4 & 0x3Fu);
      if (dawn_utf8_cont(b2) && dawn_utf8_cont(b3) && dawn_utf8_cont(b4) &&
          cp >= 0x10000u && cp <= 0x10FFFFu) {
        *n = 4;
        return cp;
      }
      /* malformed, and how much of it goes with the one replacement is
       * decided by how far the sequence got before it went wrong */
      if (b1 > 0xF4u || dawn_utf8_bad4_2(b1, b2)) {
        *n = 1;
        return 0xFFFDu;
      }
      if (!dawn_utf8_cont(b3)) {
        *n = 2;
        return 0xFFFDu;
      }
      *n = 3;
      return 0xFFFDu;
    }
    if (b1 > 0xF4u || (rest >= 1 && dawn_utf8_bad4_2(b1, p[i + 1]))) {
      *n = 1;
      return 0xFFFDu;
    }
    /* the lead and its second byte go together; a third byte that is not a
     * continuation is left for the next step to answer for */
    if (rest >= 2 && !dawn_utf8_cont(p[i + 2])) {
      *n = 2;
      return 0xFFFDu;
    }
    *n = rest + 1;
    return 0xFFFDu;
  }
  /* a continuation byte with nothing to continue, or F8..FF */
  *n = 1;
  return 0xFFFDu;
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

/* Every byte of `p[0, len)` is part of a well-formed sequence -- the same
 * question `dawn_utf8_step` already answers, asked without building anything.
 * One walker, two answers: a second copy of the rules would be a second place
 * for them to drift from the JVM's.
 *
 * `dawn_utf8_step` reports a malformed sequence as U+FFFD, and U+FFFD is also
 * a character a well-formed input may contain, so the two are told apart by
 * what was consumed: the real one is exactly its own three bytes, EF BF BD. */
static bool dawn_utf8_valid(const unsigned char *p, int64_t len) {
  int64_t i = 0;
  while (i < len) {
    int64_t n;
    uint32_t cp = dawn_utf8_step(p, len, i, &n);
    if (cp == 0xFFFDu &&
        !(n == 3 && p[i] == 0xEFu && p[i + 1] == 0xBFu && p[i + 2] == 0xBDu)) {
      return false;
    }
    i += n;
  }
  return true;
}

/* The replacement walk itself. Three bounds at 3 bytes per input byte: a valid
 * sequence never grows, and a replacement is three bytes for at least one byte
 * consumed. */
static dawn_str *dawn_utf8_replace(const unsigned char *p, int64_t len) {
  dawn_str *r = dawn_str_new(3 * len);
  char *buf = dawn_str_data(r);
  int64_t at = 0;
  int64_t i = 0;
  while (i < len) {
    int64_t n;
    uint32_t cp = dawn_utf8_step(p, len, i, &n);
    at += dawn_utf8_put(buf + at, cp);
    i += n;
  }
  return dawn_str_shrink(r, at);
}

/* Operating-system bytes -- a filename, an environment value, a line of stdin
 * -- as a string. The other door into the set of valid strings, and the one
 * #113 put a check on: these bytes used to be copied verbatim, so a malformed
 * name reached `dawn_utf8_at`, which is entitled to assume it never would.
 *
 * Replacement rather than refusal, because that is what the JVM does with the
 * same bytes: `System.getenv`, `File.list` and the `InputStreamReader` behind
 * `io_read_line` all decode with `CodingErrorAction.REPLACE`. Only
 * `io_read_file` reports, and it is the one primitive here that does not go
 * through this function.
 *
 * Valid input -- every read, on every machine whose paths are UTF-8 -- pays a
 * scan and then the same copy as before, rather than a scan and a rebuild. */
static dawn_str *dawn_str_from_os(const char *p, int64_t len) {
  if (dawn_utf8_valid((const unsigned char *)p, len)) return dawn_str_copy(p, len);
  return dawn_utf8_replace((const unsigned char *)p, len);
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
    dawn_panic(DAWN_LIT("cursor_slice: invalid cursor range"));
  }
  return dawn_str_copy(s->p + from, to - from);
}

/* ---- the str_* primitives ---- */

/* Simple (1:1) Unicode case mapping, out of the table the generated program
 * carries (dawn_rt.h, selfhost/src/embed/unicode_case.dawn). The JVM backend decodes
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
  if (rn == 0) dawn_panic(DAWN_LIT("unicode table pruned but reached"));
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
 * The accepted language of `parse_int`/`parse_float`/`parse_int_radix` is an
 * EBNF in spec 11, and the scanner that enforces it is Dawn source
 * (std/fmt, audit RP-05) -- the integer parsers never reach this runtime at
 * all. What remains here is one conversion: fmt.atod hands over a string its
 * scanner already validated and trimmed, and asks for the IEEE 754
 * round-to-nearest-even reading of it. On that subset strtod and Java's
 * Double.parseDouble are the same function (correct rounding is required of
 * both), so delegating cannot reintroduce host grammar skew; every input the
 * two hosts ever disagreed on (hex floats, "1.5f", "inf", Unicode digits) is
 * refused by the scanner before either host can see it. */

dawn_adt *dawn_parse_float(dawn_str *s) {
  if (s->len == 0) return dawn_none();
  char *buf = (char *)dawn_alloc((size_t)s->len + 1);
  memcpy(buf, s->p, (size_t)s->len);
  buf[s->len] = '\0';
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
      dawn_panic(DAWN_LIT("from_code_points: not a valid code point"));
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

dawn_bytes *dawn_bytes_from_array(const dawn_array *a) {
  int64_t n = dawn_array_len(a);
  unsigned char *buf = (unsigned char *)dawn_alloc((size_t)n + 1);
  for (int64_t i = 0; i < n; i++) {
    dawn_box *s = (dawn_box *)dawn_array_get(a, i);
    buf[i] = (unsigned char)(s->val.i & 0xFF);
  }
  return dawn_bytes_of(buf, n);
}

/* Malformed input is replaced, not refused -- what `new String(bytes,
 * charset)` does. One U+FFFD per malformed sequence, not per byte: how many
 * bytes a replacement stands for is `dawn_utf8_step`'s answer, and it is the
 * JVM's answer.
 *
 * This is one of the two doors foreign bytes enter a string through -- the
 * other is `dawn_str_from_os`, which walks the same rules -- so it is one of
 * the two places validity is established, and everything downstream may assume
 * it. */
dawn_str *dawn_bytes_decode_utf8(const dawn_bytes *b) {
  return dawn_utf8_replace(b->p, b->len);
}

/* One code point per byte, 0..255 -- so every byte string decodes and the
 * result is never longer than two UTF-8 bytes per input byte. */
dawn_str *dawn_bytes_decode_latin1(const dawn_bytes *b) {
  dawn_str *r = dawn_str_new(2 * b->len);
  char *buf = dawn_str_data(r);
  int64_t at = 0;
  for (int64_t i = 0; i < b->len; i++) {
    at += dawn_utf8_put(buf + at, b->p[i]);
  }
  return dawn_str_shrink(r, at);
}

/* ---- io ---- */

bool dawn_reactor_state_has(void) { return dawn_reactor_state != NULL; }

void *dawn_reactor_state_get(void) {
  /* The runtime keeps its root. A Core expression owns its result, so hand a
   * second reference to the caller rather than lending the global's one. */
  return dawn_dup(dawn_reactor_state);
}

dawn_unit dawn_reactor_state_set(void *state) {
  /* Take the new root before releasing the old one: replacing a state with
   * the very same object is legal and must not free it in between. */
  void *next = dawn_dup(state);
  dawn_drop(dawn_reactor_state);
  dawn_reactor_state = next;
  return DAWN_UNIT;
}

/* Standard input is read through `read(2)` and never through stdio.
 *
 * That is an invariant of this file, not a style choice: `dawn_io_stdin_ready`
 * answers by asking the *kernel* what is queued on fd 0, and a buffer between
 * the two lies to it. Both readers below used stdio until 2026-08-05, and the
 * measurement that ended it is in docs/audit/lsp-robustness-design.md 2.2.1:
 * after `fread(1)` on a 20-byte frame, `poll` timed out and `FIONREAD` said 0
 * while 19 bytes sat in glibc's buffer. A debounced language server built on
 * that would start analysing while its next message was already in hand.
 *
 * The price is one syscall per byte in `io_read_line`, which reads until a
 * newline it cannot know the position of in advance. That is the honest cost
 * of "no buffer": a buffer fast enough to matter here would have to be
 * consulted by the readiness query too, and then the invariant is a pair of
 * things that must agree rather than a fact. `io_read_stdin` -- the one the
 * language server uses -- reads its whole frame in one call and pays nothing.
 * Neither reader may consume a byte the caller did not ask for. */
dawn_adt *dawn_io_read_line(void) {
  size_t cap = 128;
  size_t n = 0;
  char *buf = (char *)dawn_alloc(cap);
  bool any = false;
  for (;;) {
    char c;
    ssize_t k = read(0, &c, 1);
    if (k < 0) {
      if (errno == EINTR) continue;
      k = 0; /* an error the caller sees as end of input, as ferror did */
    }
    if (k == 0) break;
    any = true;
    if (c == '\n') break;
    if (n == cap) {
      char *bigger = (char *)dawn_alloc(cap * 2);
      memcpy(bigger, buf, n);
      free(buf);
      buf = bigger;
      cap *= 2;
    }
    buf[n++] = c;
  }
  /* end of input before a single byte is None; a last line without a
   * terminator is still a line, as BufferedReader.readLine has it */
  if (!any) {
    free(buf);
    return dawn_none();
  }
  /* BufferedReader.readLine keeps neither terminator */
  if (n > 0 && buf[n - 1] == '\r') n--;
  /* the JVM reads this stream through an InputStreamReader built on UTF_8,
   * whose decoder replaces rather than reports -- so a malformed line is a
   * line, here too */
  dawn_str *line = dawn_str_from_os(buf, (int64_t)n);
  free(buf);
  return dawn_some(line);
}

static bool dawn_has_nul(const dawn_str *s) {
  return s->len > 0 && memchr(s->p, '\0', (size_t)s->len) != NULL;
}

/* A Dawn string is not NUL-terminated; every path, environment name, or argv
 * entry handed to the C library has to be copied to get the terminator. A C
 * string cannot represent an embedded NUL, so reject one before allocating
 * instead of silently naming a prefix. Bool path queries and getenv check
 * dawn_has_nul first because their public failure values are false and None;
 * operations with a Result/fault channel keep this fail-closed default. */
static char *dawn_cpath(dawn_str *s) {
  if (dawn_has_nul(s)) {
    dawn_fault(DAWN_LIT("path contains an embedded NUL byte"));
  }
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
  if (dawn_has_nul(path)) return false;
  char *p = dawn_cpath(path);
  struct stat st;
  bool yes = stat(p, &st) == 0 && S_ISDIR(st.st_mode);
  free(p);
  return yes;
}

bool dawn_io_exists(dawn_str *path) {
  if (dawn_has_nul(path)) return false;
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
        dawn_fault(DAWN_LIT("io_mkdirs: path exists and is not a directory"));
      }
    } else if (mkdir(p, 0777) != 0) {
      free(p);
      dawn_fault(DAWN_LIT("io_mkdirs: cannot create directory"));
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
    dawn_fault(DAWN_LIT("io_read_file: cannot open file"));
  }
  size_t n = 0;
  bool bad = false;
  unsigned char *buf = dawn_slurp(f, &n, &bad);
  fclose(f);
  if (bad) {
    dawn_fault(DAWN_LIT("io_read_file: read failed"));
  }
  /* The one reader that refuses. `Files.readString` decodes with
   * `CodingErrorAction.REPORT` and throws a `MalformedInputException`, so a
   * file that is not UTF-8 is a failed read on the JVM rather than a string
   * full of U+FFFD -- and a text reader that quietly answers something other
   * than what is on disk is the failure mode this whole pair of issues is
   * about. `read_bytes` is the primitive for input that is not text.
   *
   * The buffer goes back before the raise: `dawn_fault` longjmps past every
   * frame between here and the barrier, so anything still owned at the call is
   * owned by nobody. Same shape as the `free(p)` before the raises in
   * `io_mkdirs`. */
  if (!dawn_utf8_valid(buf, (int64_t)n)) {
    free(buf);
    dawn_fault(DAWN_LIT("io_read_file: malformed UTF-8"));
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
    dawn_fault(DAWN_LIT("io_write_file: cannot open file"));
  }
  bool bad = content->len > 0 &&
             fwrite(content->p, 1, (size_t)content->len, f) != (size_t)content->len;
  if (fclose(f) != 0) bad = true;
  if (bad) {
    dawn_fault(DAWN_LIT("io_write_file: write failed"));
  }
  return DAWN_UNIT;
}

dawn_array *dawn_io_list_names(dawn_str *path) {
  char *p = dawn_cpath(path);
  DIR *d = opendir(p);
  free(p);
  if (d == NULL) {
    dawn_fault(DAWN_LIT("io_list_names: cannot open directory"));
  }
  /* readdir order, deliberately: the intrinsic's order is unspecified, and
   * std/io's list_dir sorts (code-point order) so every backend agrees. */
  dawn_array *a = dawn_array_new();
  struct dirent *e = readdir(d);
  while (e != NULL) {
    if (strcmp(e->d_name, ".") != 0 && strcmp(e->d_name, "..") != 0) {
      size_t n = strlen(e->d_name);
      a = dawn_array_push_own(a, dawn_str_from_os(e->d_name, (int64_t)n));
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
      dawn_str *s = dawn_str_from_os(buf, (int64_t)strlen(buf));
      free(buf);
      return s;
    }
    free(buf);
    if (errno != ERANGE) {
      dawn_fault(DAWN_LIT("io_cwd: cannot read the working directory"));
    }
    cap *= 2;
  }
}

dawn_adt *dawn_io_getenv(dawn_str *name) {
  if (dawn_has_nul(name)) return dawn_none();
  char *p = dawn_cpath(name);
  const char *v = getenv(p);
  free(p);
  if (v == NULL) return dawn_none();
  return dawn_some(dawn_str_from_os(v, (int64_t)strlen(v)));
}

dawn_bytes *dawn_io_read_bytes(dawn_str *path) {
  char *p = dawn_cpath(path);
  FILE *f = fopen(p, "rb");
  free(p);
  if (f == NULL) {
    dawn_fault(DAWN_LIT("io_read_bytes: cannot open file"));
  }
  size_t n = 0;
  bool bad = false;
  unsigned char *buf = dawn_slurp(f, &n, &bad);
  fclose(f);
  if (bad) {
    dawn_fault(DAWN_LIT("io_read_bytes: read failed"));
  }
  return dawn_bytes_of(buf, (int64_t)n);
}

dawn_unit dawn_io_write_bytes(dawn_str *path, const dawn_bytes *content) {
  char *p = dawn_cpath(path);
  dawn_mkparents(p);
  FILE *f = fopen(p, "wb");
  free(p);
  if (f == NULL) {
    dawn_fault(DAWN_LIT("io_write_bytes: cannot open file"));
  }
  bool bad = content->len > 0 &&
             fwrite(content->p, 1, (size_t)content->len, f) != (size_t)content->len;
  if (fclose(f) != 0) bad = true;
  if (bad) {
    dawn_fault(DAWN_LIT("io_write_bytes: write failed"));
  }
  return DAWN_UNIT;
}

/* remove(3) takes both files and empty directories, matching
 * Files.deleteIfExists without recursing. ENOENT is the sole false result;
 * every other errno is a fault for std/io's catch_fault barrier. */
bool dawn_io_delete(dawn_str *path) {
  char *p = dawn_cpath(path);
  int rc = remove(p);
  int saved_errno = errno;
  free(p);
  if (rc == 0) return true;
  if (saved_errno == ENOENT) return false;
  dawn_fault(DAWN_LIT("io_delete: cannot delete path"));
  return false;
}

dawn_unit dawn_io_rename(dawn_str *src, dawn_str *dst) {
  char *a = dawn_cpath(src);
  char *b = dawn_cpath(dst);
  bool bad = rename(a, b) != 0;
  free(a);
  free(b);
  if (bad) {
    dawn_fault(DAWN_LIT("io_rename: cannot rename (not one filesystem?)"));
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
    dawn_fault(DAWN_LIT("io_temp_dir: cannot create a temporary directory"));
  }
  /* `prefix` was already a string, but the base may be `$TMPDIR` */
  dawn_str *s = dawn_str_from_os(tmpl, (int64_t)strlen(tmpl));
  free(tmpl);
  return s;
}

/* The file half of io_temp_dir. mkstemp(3) is the whole point: it picks the
 * name and creates the file in one step, with mode 0600, so no second caller
 * can be handed the same name and no other user can have pre-created it as a
 * symlink. A name spelled here and opened afterwards would have a window
 * between the two, which is exactly what an atomic replace must not have. */
dawn_str *dawn_io_temp_file(dawn_str *parent, dawn_str *prefix) {
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
  int fd = mkstemp(tmpl);
  if (fd < 0) {
    free(tmpl);
    dawn_fault(DAWN_LIT("io_temp_file: cannot create a temporary file"));
  }
  close(fd);
  /* `prefix` was already a string, but the base may be `$TMPDIR` */
  dawn_str *s = dawn_str_from_os(tmpl, (int64_t)strlen(tmpl));
  free(tmpl);
  return s;
}

/* lstat(2), not stat(2): the mode copied is the one on the object named, never
 * the one a symlink points at. There is no POSIX-permission fallback branch
 * here the way there is on the JVM, because this runtime has no host without
 * st_mode to fall back for. */
dawn_unit dawn_io_copy_permissions(dawn_str *src, dawn_str *dst) {
  char *a = dawn_cpath(src);
  char *b = dawn_cpath(dst);
  struct stat st;
  bool bad = lstat(a, &st) != 0 || chmod(b, st.st_mode & 07777) != 0;
  free(a);
  free(b);
  if (bad) {
    dawn_fault(DAWN_LIT("io_copy_permissions: cannot copy the file mode"));
  }
  return DAWN_UNIT;
}

bool dawn_io_is_symlink(dawn_str *path) {
  if (dawn_has_nul(path)) return false;
  char *p = dawn_cpath(path);
  struct stat st;
  bool yes = lstat(p, &st) == 0 && S_ISLNK(st.st_mode);
  free(p);
  return yes;
}

/* Exactly `n` bytes, short only at end of input. See the note on
 * `dawn_io_read_line` for why this is `read(2)` and not `fread`. */
dawn_bytes *dawn_io_read_stdin(int64_t n) {
  /* an owned empty buffer, not a static "": drop frees `p` now */
  if (n <= 0) return dawn_bytes_of((unsigned char *)dawn_alloc(1), 0);
  unsigned char *buf = (unsigned char *)dawn_alloc((size_t)n);
  size_t got = 0;
  while (got < (size_t)n) {
    ssize_t step = read(0, buf + got, (size_t)n - got);
    if (step < 0) {
      if (errno == EINTR) continue;
      break; /* an error the caller sees as end of input, as ferror did */
    }
    if (step == 0) break; /* end of input */
    got += (size_t)step;
  }
  return dawn_bytes_of(buf, (int64_t)got);
}

/* True when at least one byte can be read from standard input right now.
 *
 * End of input is deliberately *not* readiness: it is reported by the
 * blocking read, which stays the only reader. So a loop driven by this alone
 * would spin at end of input -- the third branch of the read loop in
 * selfhost/src/lsp/server.dawn (block when there is nothing else to do) is what
 * closes that, and it is the shape the design argues for rather than a patch.
 *
 * `timeout_ms` is an upper bound and not a lower one: a regular file at end of
 * input answers `false` in microseconds, and every `false` here is safe to
 * return early because the only thing a caller may do with it is stop waiting
 * and block. A `true` that is wrong would not be safe -- the caller would read
 * and hang -- so every uncertain answer below is `false`.
 *
 * `poll` alone cannot answer it. A pipe whose writer is gone reports POLLHUP
 * with no POLLIN, but a *regular file* at end of input reports POLLIN forever
 * (it is always readable; the read just returns 0). So the count comes from
 * the kernel via FIONREAD, and POLLIN is only the wake-up. Measured, both
 * rows, in docs/audit/lsp-robustness-design.md 2.2.1. */
bool dawn_io_stdin_ready(int64_t timeout_ms) {
  int ms;
  if (timeout_ms <= 0) {
    ms = 0;
  } else if (timeout_ms > 2147483647) {
    ms = 2147483647;
  } else {
    ms = (int)timeout_ms;
  }
  struct pollfd p;
  p.fd = 0;
  p.events = POLLIN;
  p.revents = 0;
  int r = poll(&p, 1, ms);
  /* EINTR is not retried: waiting less than asked is inside the contract, and
   * a retry with the full window back would put it outside. */
  if (r <= 0) return false;
  if ((p.revents & POLLIN) == 0) return false; /* POLLHUP alone: end of input */
  int queued = 0;
  /* ENOTTY on /dev/null and anything else that does not implement the count.
   * `false` there is right rather than merely safe: there is nothing to read. */
  if (ioctl(0, FIONREAD, &queued) != 0) return false;
  return queued > 0;
}

#ifdef __wasi__
/* No processes on wasi, so `io.run` is a fault, same shape as the other
 * honest refusals above. The signal-forwarding machinery below it goes with
 * the spawn: it exists to keep a spawned child reachable, and there is
 * nothing to spawn. */
int64_t dawn_io_run(dawn_array *argv, dawn_str *out_path, dawn_str *err_path) {
  (void)out_path;
  (void)err_path;
  dawn_drop(argv);
  dawn_fault(DAWN_LIT("io_run: no processes on wasi"));
  return -1;
}
#else
/* Spawn and wait. `posix_spawnp` rather than fork+exec: fork duplicates the
 * whole address space only to throw it away, and this runs inside a compiler.
 * Redirection is a file action for the same reason the signature takes paths
 * at all -- see the note on `io_run` in types.dawn. */
extern char **environ;

/* The child `io_run` is currently waiting on, so the handler below can reach
 * it. One slot, not a table: the runtime is single threaded -- the one thread
 * it creates is the deep main stack (`dawn_stack_thread`), which the original
 * thread only joins -- so there is never a second `io_run` in flight.
 * `sig_atomic_t` because a handler may read nothing else. */
static volatile sig_atomic_t dawn_run_child = 0;

/* Pass the signal on to the child and go back to waiting for it.
 *
 * Without this, a program whose whole job is to spawn something and wait --
 * which is what the native driver's `run` and `test` are (nmain.dawn,
 * build_and_exec) -- answered SIGTERM by dying and leaving the child behind,
 * measured at 99.9% CPU and reparented to init after `timeout` had given up on
 * the driver. Forwarding means the child gets the signal the caller meant for
 * the work, the `waitpid` below reports how it died, and `io.run` answers
 * 128+signal, which is the number the shell would have printed anyway. A child
 * that ignores the signal keeps this process waiting, which is the same
 * bargain `Process.destroy` makes on the JVM.
 *
 * The JVM `io_run` answers the same question with the lever that backend has:
 * a shutdown hook destroying the armed child (rtclasses.dawn, gen_io_reaper).
 * The two agree on the number a caller reads back -- 128+signal -- and differ
 * after it: forwarding leaves this program running, a shutdown hook means the
 * JVM is already on its way out. A hook is also told nothing about which
 * signal it runs for, so it can only send SIGTERM.
 *
 * Only `kill`, `signal` and `raise` are called here, all async-signal-safe;
 * `errno` is saved because the syscall this interrupts sets it afterwards.
 *
 * With no child recorded the handler is not wanted at all, so it puts the
 * default back and re-raises: the disposition is installed just before the
 * spawn (a window where nothing is running yet, but one that no thread may
 * spend taking the default action, or the parent would die and orphan the
 * child that was about to start). What remains uncovered is the instant
 * between `posix_spawnp` returning and the store below, and SIGKILL, which no
 * handler ever sees -- that one is the caller's process-group kill (#167). */
static void dawn_run_forward(int sig) {
  int saved = errno;
  pid_t p = (pid_t)dawn_run_child;
  if (p > 0) {
    kill(p, sig);
  } else {
    signal(sig, SIG_DFL);
    raise(sig);
  }
  errno = saved;
}

/* SIGINT is in the set even though a terminal already delivers it to the whole
 * foreground group: `kill -INT <driver>` does not, and this is what makes the
 * two agree. */
static const int DAWN_RUN_SIGNALS[3] = {SIGTERM, SIGINT, SIGHUP};

int64_t dawn_io_run(dawn_array *argv, dawn_str *out_path, dawn_str *err_path) {
  int64_t n = dawn_array_len(argv);
  if (n <= 0) {
    dawn_drop(argv);
    dawn_fault(DAWN_LIT("io_run: argv is empty"));
  }
  char **args = (char **)dawn_alloc(sizeof(char *) * (size_t)(n + 1));
  for (int64_t i = 0; i < n; i++) {
    args[i] = dawn_cpath((dawn_str *)dawn_array_get(argv, i));
  }
  args[n] = NULL;
  /* Released here rather than on the way out: `args` holds copies, so argv is
   * dead from this line on, and every path below it can fault. A fault is not
   * the end of the process -- `catch_fault` resumes -- so a drop placed after
   * the spawn leaks the list on exactly the paths a caller can observe. */
  dawn_drop(argv);

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
  /* Armed before the spawn and disarmed after the wait; `dawn_run_child` is
   * what tells the handler which of the two it is in. SA_RESTART keeps the
   * `waitpid` below from having to distinguish "a signal we forwarded" from a
   * real failure -- it simply resumes waiting. */
  struct sigaction sa;
  struct sigaction old[3];
  memset(&sa, 0, sizeof sa);
  sa.sa_handler = dawn_run_forward;
  sigemptyset(&sa.sa_mask);
  sa.sa_flags = SA_RESTART;
  dawn_run_child = 0;
  for (int i = 0; i < 3; i++) sigaction(DAWN_RUN_SIGNALS[i], &sa, &old[i]);

  pid_t pid = 0;
  int rc = posix_spawnp(&pid, args[0], &fa, NULL, args, environ);
  /* Guarded, and before the tidying below rather than after it: what is stored
   * here is a signal's target, so a failed spawn -- where POSIX leaves `pid`
   * unspecified -- must not reach it, and every instruction between the spawn
   * and the store is one where a signal would find no child to forward to. */
  if (rc == 0) dawn_run_child = (sig_atomic_t)pid;
  posix_spawn_file_actions_destroy(&fa);
  free(op);
  free(ep);
  for (int64_t i = 0; i < n; i++) free(args[i]);
  free(args);
  if (rc != 0) {
    /* Restore first: a fault is not the end of the process (`catch_fault`
     * resumes), and leaving this program's signal dispositions rewritten
     * behind a failed spawn would outlive the call that set them. */
    dawn_run_child = 0;
    for (int i = 0; i < 3; i++) sigaction(DAWN_RUN_SIGNALS[i], &old[i], NULL);
    dawn_fault(DAWN_LIT("io_run: cannot start the program"));
  }
  int status = 0;
  while (waitpid(pid, &status, 0) < 0) {
    if (errno != EINTR) {
      dawn_run_child = 0;
      for (int i = 0; i < 3; i++) sigaction(DAWN_RUN_SIGNALS[i], &old[i], NULL);
      dawn_fault(DAWN_LIT("io_run: waiting for the child failed"));
    }
  }
  dawn_run_child = 0;
  for (int i = 0; i < 3; i++) sigaction(DAWN_RUN_SIGNALS[i], &old[i], NULL);
  /* The two numbers the JVM's Process.exitValue() also reports on POSIX. */
  if (WIFEXITED(status)) return (int64_t)WEXITSTATUS(status);
  if (WIFSIGNALED(status)) return (int64_t)(128 + WTERMSIG(status));
  return -1;
}
#endif

dawn_array *dawn_args(void) {
  /* argv[0] is the program, which `args` does not include -- the JVM backend
   * gets the same list from main's parameter. */
  dawn_array *a = dawn_array_new();
  for (int i = 1; i < dawn_argc; i++) {
    a = dawn_array_push_own(a,
      dawn_str_from_os(dawn_argv[i], (int64_t)strlen(dawn_argv[i])));
  }
  return a;
}

/* ---- GPU: the CUDA driver behind std/gpu's with_gpu_real -------------------
 *
 * The dawn_gpu_*_host family is the `RtGpu` runtime module
 * (docs/tile-backend-design.md 4.4). It reaches the driver through
 * dlopen("libcuda.so.1") rather than a link-time -lcuda, so a machine with
 * no GPU compiles and runs every other native program unchanged and learns
 * about the gap only when a program installs `with_gpu_real` and issues an
 * operation. (glibc 2.34 and later carry dlopen in libc itself, so no -ldl
 * is added to any link line.)
 *
 * Every function answers a `Result[_, ForeignError]` itself and never
 * faults. A driver refusal becomes `Err(ForeignError { kind, message })`
 * with kind = "cuda." ++ cuGetErrorName(result), message naming the driver
 * call and the numeric CUresult; a missing library or symbol is
 * `gpu.no_driver`. The one exception to "the raw device outcome" is a grid
 * or length that does not fit the driver's unsigned parameter, refused here
 * as `gpu.bad_grid` / `gpu.bad_length` rather than truncated into a launch
 * of the wrong size.
 *
 * State is one process-wide context, opened by the first operation that
 * needs it (cuInit, device 0, cuCtxCreate_v2) and released by
 * dawn_gpu_close_host, which std/gpu calls when the handler's body has
 * returned: cuCtxDestroy_v2 frees every allocation and module of the
 * context, then the library handle is dlclose'd. The versioned symbol names
 * (`_v2`) are the ones cuda.h maps the plain names to; dlsym has to spell
 * them itself.
 *
 * The launch shape is cuda-tile's host example: a Tile IR kernel is
 * launched with the grid counting tile blocks, block dims (1, 1, 1) and no
 * dynamic shared memory; the kernel's parameters are its entry's pointer
 * arguments, one 8-byte device pointer each, in order.
 *
 * The section between these two markers is what scripts/tile-gpu-diff's
 * ledger gate compares across commits; keep it contiguous.
 * === DAWN_RT_GPU_BEGIN === */

#ifndef __wasi__
#include <dlfcn.h>

typedef int dawn_cu_result;
typedef int dawn_cu_device;
typedef void *dawn_cu_context;
typedef void *dawn_cu_module;
typedef void *dawn_cu_function;
typedef unsigned long long dawn_cu_deviceptr;

static struct {
  void *lib;
  dawn_cu_context ctx;
  bool ready;
  int driver_version; /* cuDriverGetVersion: 12060 for 560.94, 13000 and up for r580 */
  dawn_cu_result (*init)(unsigned int);
  dawn_cu_result (*driver_get_version)(int *);
  dawn_cu_result (*device_get)(dawn_cu_device *, int);
  dawn_cu_result (*ctx_create)(dawn_cu_context *, unsigned int, dawn_cu_device);
  dawn_cu_result (*ctx_destroy)(dawn_cu_context);
  dawn_cu_result (*ctx_synchronize)(void);
  dawn_cu_result (*mem_alloc)(dawn_cu_deviceptr *, size_t);
  dawn_cu_result (*mem_free)(dawn_cu_deviceptr);
  dawn_cu_result (*memcpy_htod)(dawn_cu_deviceptr, const void *, size_t);
  dawn_cu_result (*memcpy_dtoh)(void *, dawn_cu_deviceptr, size_t);
  dawn_cu_result (*module_load_data)(dawn_cu_module *, const void *);
  dawn_cu_result (*module_get_function)(dawn_cu_function *, dawn_cu_module, const char *);
  dawn_cu_result (*launch_kernel)(dawn_cu_function, unsigned int, unsigned int, unsigned int,
                                  unsigned int, unsigned int, unsigned int, unsigned int,
                                  void *, void **, void **);
  dawn_cu_result (*get_error_name)(dawn_cu_result, const char **);
} dawn_gpu;

/* `Err(ForeignError { kind, message, cause: None })`, both strings copied. */
static dawn_adt *dawn_gpu_refuse(const char *kind, const char *message) {
  dawn_adt *a = dawn_adt_new(DAWN_TAG_FOREIGN_ERROR, 3, DAWN_MASK_THREE_BOXED);
  a->fields[0].p = dawn_str_copy(kind, (int64_t)strlen(kind));
  a->fields[1].p = dawn_str_copy(message, (int64_t)strlen(message));
  a->fields[2].p = dawn_none();
  return dawn_err(a);
}

/* A driver refusal as the error model spells it: the CUresult's own name
 * under `cuda.`, and a message that says which call and which number. */
static dawn_adt *dawn_gpu_cu_error(const char *call, dawn_cu_result r) {
  const char *name = NULL;
  if (dawn_gpu.get_error_name == NULL || dawn_gpu.get_error_name(r, &name) != 0 || name == NULL) {
    name = "CUDA_ERROR_UNKNOWN";
  }
  char kind[128];
  char message[256];
  snprintf(kind, sizeof kind, "cuda.%s", name);
  snprintf(message, sizeof message, "%s: CUresult %d (%s)", call, r, name);
  return dawn_gpu_refuse(kind, message);
}

static void dawn_gpu_reset(void) {
  if (dawn_gpu.lib != NULL) dlclose(dawn_gpu.lib);
  memset(&dawn_gpu, 0, sizeof dawn_gpu);
}

/* One symbol, or the reason there is none (NULL means it was found). */
static dawn_adt *dawn_gpu_sym(void **slot, const char *name) {
  *slot = dlsym(dawn_gpu.lib, name);
  if (*slot != NULL) return NULL;
  char message[256];
  snprintf(message, sizeof message, "libcuda.so.1 has no %s", name);
  return dawn_gpu_refuse("gpu.no_driver", message);
}

#define DAWN_GPU_SYM(field, name) \
  do { \
    dawn_adt *e_ = dawn_gpu_sym((void **)&dawn_gpu.field, name); \
    if (e_ != NULL) { dawn_gpu_reset(); return e_; } \
  } while (0)

/* The library, the entry points and one context on device 0. NULL when the
 * device is ready; otherwise the refusal, with everything opened so far
 * released again. */
static dawn_adt *dawn_gpu_open(void) {
  if (dawn_gpu.ready) return NULL;
  dawn_gpu.lib = dlopen("libcuda.so.1", RTLD_NOW | RTLD_LOCAL);
  if (dawn_gpu.lib == NULL) {
    const char *why = dlerror();
    char message[512];
    snprintf(message, sizeof message, "cannot load libcuda.so.1: %s", why == NULL ? "dlopen failed" : why);
    memset(&dawn_gpu, 0, sizeof dawn_gpu);
    return dawn_gpu_refuse("gpu.no_driver", message);
  }
  DAWN_GPU_SYM(get_error_name, "cuGetErrorName");
  DAWN_GPU_SYM(init, "cuInit");
  DAWN_GPU_SYM(driver_get_version, "cuDriverGetVersion");
  DAWN_GPU_SYM(device_get, "cuDeviceGet");
  DAWN_GPU_SYM(ctx_create, "cuCtxCreate_v2");
  DAWN_GPU_SYM(ctx_destroy, "cuCtxDestroy_v2");
  DAWN_GPU_SYM(ctx_synchronize, "cuCtxSynchronize");
  DAWN_GPU_SYM(mem_alloc, "cuMemAlloc_v2");
  DAWN_GPU_SYM(mem_free, "cuMemFree_v2");
  DAWN_GPU_SYM(memcpy_htod, "cuMemcpyHtoD_v2");
  DAWN_GPU_SYM(memcpy_dtoh, "cuMemcpyDtoH_v2");
  DAWN_GPU_SYM(module_load_data, "cuModuleLoadData");
  DAWN_GPU_SYM(module_get_function, "cuModuleGetFunction");
  DAWN_GPU_SYM(launch_kernel, "cuLaunchKernel");
  dawn_cu_result r = dawn_gpu.init(0);
  if (r != 0) { dawn_adt *e = dawn_gpu_cu_error("cuInit", r); dawn_gpu_reset(); return e; }
  if (dawn_gpu.driver_get_version(&dawn_gpu.driver_version) != 0) dawn_gpu.driver_version = 0;
  dawn_cu_device dev = 0;
  r = dawn_gpu.device_get(&dev, 0);
  if (r != 0) { dawn_adt *e = dawn_gpu_cu_error("cuDeviceGet", r); dawn_gpu_reset(); return e; }
  r = dawn_gpu.ctx_create(&dawn_gpu.ctx, 0, dev);
  if (r != 0) { dawn_adt *e = dawn_gpu_cu_error("cuCtxCreate_v2", r); dawn_gpu_reset(); return e; }
  dawn_gpu.ready = true;
  return NULL;
}

/* The CUDA generation that built a cubin is in its ELF header: EI_ABIVERSION
 * (byte 8) is 8 from CUDA 13 on, and a Tile IR cubin needs a driver of that
 * generation (r580, API 13000). A driver of an older generation does not
 * refuse such an image cleanly: 560.94 (API 12060) answers
 * CUDA_ERROR_INVALID_IMAGE from cuModuleLoadData on some heap layouts and
 * writes through a null pointer inside it on others (measured across
 * optimisation levels and std variants, 2026-09-02). So the refusal is made
 * here, before the loader sees the bytes, and it names both numbers. */
static dawn_adt *dawn_gpu_image_needs_newer_driver(const dawn_bytes *cubin) {
  if (cubin->len < 16 || memcmp(cubin->p, "\x7f" "ELF", 4) != 0) return NULL;
  int abi = cubin->p[8];
  int need = abi >= 8 ? 13000 : 0;
  if (dawn_gpu.driver_version >= need) return NULL;
  char message[256];
  snprintf(message, sizeof message,
           "cuModuleLoadData: a cubin with ELF ABI version %d needs driver API %d and this driver is %d",
           abi, need, dawn_gpu.driver_version);
  return dawn_gpu_refuse("gpu.driver_too_old", message);
}

dawn_adt *dawn_gpu_load_module_host(const dawn_bytes *cubin) {
  dawn_adt *e = dawn_gpu_open();
  if (e != NULL) return e;
  e = dawn_gpu_image_needs_newer_driver(cubin);
  if (e != NULL) return e;
  dawn_cu_module mod = NULL;
  dawn_cu_result r = dawn_gpu.module_load_data(&mod, cubin->p);
  if (r != 0) return dawn_gpu_cu_error("cuModuleLoadData", r);
  return dawn_ok(dawn_box_int((int64_t)(intptr_t)mod));
}

dawn_adt *dawn_gpu_alloc_host(int64_t nbytes) {
  dawn_adt *e = dawn_gpu_open();
  if (e != NULL) return e;
  if (nbytes < 0) return dawn_gpu_refuse("gpu.bad_length", "gpu_alloc_host: negative byte count");
  dawn_cu_deviceptr p = 0;
  dawn_cu_result r = dawn_gpu.mem_alloc(&p, (size_t)nbytes);
  if (r != 0) return dawn_gpu_cu_error("cuMemAlloc_v2", r);
  return dawn_ok(dawn_box_int((int64_t)p));
}

dawn_adt *dawn_gpu_upload_host(int64_t devptr, const dawn_array *data) {
  dawn_adt *e = dawn_gpu_open();
  if (e != NULL) return e;
  int64_t n = dawn_array_len(data);
  double *buf = (double *)dawn_alloc((size_t)(n > 0 ? n : 1) * sizeof(double));
  /* the slots are borrowed: read them, do not `dawn_unbox_*` them, which
   * releases the box (see the note above dawn_unbox_int) */
  for (int64_t i = 0; i < n; i++) buf[i] = ((dawn_box *)dawn_array_get(data, i))->val.f;
  dawn_cu_result r = dawn_gpu.memcpy_htod((dawn_cu_deviceptr)devptr, buf, (size_t)n * sizeof(double));
  free(buf);
  if (r != 0) return dawn_gpu_cu_error("cuMemcpyHtoD_v2", r);
  return dawn_ok(dawn_box_unit(DAWN_UNIT));
}

dawn_adt *dawn_gpu_download_host(int64_t devptr, int64_t len) {
  dawn_adt *e = dawn_gpu_open();
  if (e != NULL) return e;
  if (len < 0) return dawn_gpu_refuse("gpu.bad_length", "gpu_download_host: negative element count");
  double *buf = (double *)dawn_alloc((size_t)(len > 0 ? len : 1) * sizeof(double));
  dawn_cu_result r = dawn_gpu.memcpy_dtoh(buf, (dawn_cu_deviceptr)devptr, (size_t)len * sizeof(double));
  if (r != 0) {
    free(buf);
    return dawn_gpu_cu_error("cuMemcpyDtoH_v2", r);
  }
  dawn_array *a = dawn_array_new();
  for (int64_t i = 0; i < len; i++) a = dawn_array_push_own(a, dawn_box_float(buf[i]));
  free(buf);
  return dawn_ok(a);
}

/* The packed-format seam: std/gpu has already laid the buffer out byte for
 * byte (bf16: std/gpu.pack_bf16), so the runtime copies and knows no
 * format. */
dawn_adt *dawn_gpu_upload_bytes_host(int64_t devptr, const dawn_bytes *data) {
  dawn_adt *e = dawn_gpu_open();
  if (e != NULL) return e;
  dawn_cu_result r = dawn_gpu.memcpy_htod((dawn_cu_deviceptr)devptr, data->p, (size_t)data->len);
  if (r != 0) return dawn_gpu_cu_error("cuMemcpyHtoD_v2", r);
  return dawn_ok(dawn_box_unit(DAWN_UNIT));
}

dawn_adt *dawn_gpu_download_bytes_host(int64_t devptr, int64_t nbytes) {
  dawn_adt *e = dawn_gpu_open();
  if (e != NULL) return e;
  if (nbytes < 0) return dawn_gpu_refuse("gpu.bad_length", "gpu_download_bytes_host: negative byte count");
  unsigned char *buf = (unsigned char *)dawn_alloc((size_t)(nbytes > 0 ? nbytes : 1));
  dawn_cu_result r = dawn_gpu.memcpy_dtoh(buf, (dawn_cu_deviceptr)devptr, (size_t)nbytes);
  if (r != 0) {
    free(buf);
    return dawn_gpu_cu_error("cuMemcpyDtoH_v2", r);
  }
  return dawn_ok(dawn_bytes_of(buf, nbytes));
}

dawn_adt *dawn_gpu_launch_host(int64_t module, dawn_str *kernel, int64_t gx, int64_t gy,
                               int64_t gz, const dawn_array *args) {
  dawn_adt *e = dawn_gpu_open();
  if (e != NULL) return e;
  /* each grid dimension is an unsigned int and the driver's own ceiling is
   * 2^31 - 1: a count that does not fit is refused, never truncated into a
   * smaller grid */
  if (gx < 0 || gx > 0x7fffffff || gy < 0 || gy > 0x7fffffff || gz < 0 || gz > 0x7fffffff) {
    return dawn_gpu_refuse("gpu.bad_grid", "gpu_launch_host: a grid dimension does not fit a launch dimension");
  }
  if (dawn_has_nul(kernel)) {
    return dawn_gpu_refuse("gpu.bad_kernel_name", "gpu_launch_host: kernel name contains NUL");
  }
  char *name = (char *)dawn_alloc((size_t)kernel->len + 1);
  if (kernel->len > 0) memcpy(name, kernel->p, (size_t)kernel->len);
  name[kernel->len] = '\0';
  dawn_cu_function fn = NULL;
  dawn_cu_result r = dawn_gpu.module_get_function(&fn, (dawn_cu_module)(intptr_t)module, name);
  free(name);
  if (r != 0) return dawn_gpu_cu_error("cuModuleGetFunction", r);
  int64_t n = dawn_array_len(args);
  dawn_cu_deviceptr *ptrs =
    (dawn_cu_deviceptr *)dawn_alloc((size_t)(n > 0 ? n : 1) * sizeof(dawn_cu_deviceptr));
  void **params = (void **)dawn_alloc((size_t)(n > 0 ? n : 1) * sizeof(void *));
  for (int64_t i = 0; i < n; i++) {
    ptrs[i] = (dawn_cu_deviceptr)((dawn_box *)dawn_array_get(args, i))->val.i; /* borrowed */
    params[i] = &ptrs[i];
  }
  r = dawn_gpu.launch_kernel(fn, (unsigned int)gx, (unsigned int)gy, (unsigned int)gz, 1, 1, 1, 0,
                             NULL, params, NULL);
  free(params);
  free(ptrs);
  if (r != 0) return dawn_gpu_cu_error("cuLaunchKernel", r);
  return dawn_ok(dawn_box_unit(DAWN_UNIT));
}

dawn_adt *dawn_gpu_free_host(int64_t devptr) {
  dawn_adt *e = dawn_gpu_open();
  if (e != NULL) return e;
  dawn_cu_result r = dawn_gpu.mem_free((dawn_cu_deviceptr)devptr);
  if (r != 0) return dawn_gpu_cu_error("cuMemFree_v2", r);
  return dawn_ok(dawn_box_unit(DAWN_UNIT));
}

dawn_adt *dawn_gpu_sync_host(void) {
  dawn_adt *e = dawn_gpu_open();
  if (e != NULL) return e;
  dawn_cu_result r = dawn_gpu.ctx_synchronize();
  if (r != 0) return dawn_gpu_cu_error("cuCtxSynchronize", r);
  return dawn_ok(dawn_box_unit(DAWN_UNIT));
}

dawn_unit dawn_gpu_close_host(void) {
  if (dawn_gpu.ready && dawn_gpu.ctx != NULL) dawn_gpu.ctx_destroy(dawn_gpu.ctx);
  dawn_gpu_reset();
  return DAWN_UNIT;
}

#else /* __wasi__: no dlopen, no driver, no device */

static dawn_adt *dawn_gpu_refuse_wasi(const char *call) {
  dawn_adt *a = dawn_adt_new(DAWN_TAG_FOREIGN_ERROR, 3, DAWN_MASK_THREE_BOXED);
  a->fields[0].p = DAWN_LIT("gpu.unsupported_backend");
  char message[128];
  snprintf(message, sizeof message, "%s: the GPU runtime is not available on wasm", call);
  a->fields[1].p = dawn_str_copy(message, (int64_t)strlen(message));
  a->fields[2].p = dawn_none();
  return dawn_err(a);
}

dawn_adt *dawn_gpu_load_module_host(const dawn_bytes *cubin) {
  (void)cubin;
  return dawn_gpu_refuse_wasi("gpu_load_module_host");
}
dawn_adt *dawn_gpu_alloc_host(int64_t nbytes) {
  (void)nbytes;
  return dawn_gpu_refuse_wasi("gpu_alloc_host");
}
dawn_adt *dawn_gpu_upload_host(int64_t devptr, const dawn_array *data) {
  (void)devptr;
  (void)data;
  return dawn_gpu_refuse_wasi("gpu_upload_host");
}
dawn_adt *dawn_gpu_download_host(int64_t devptr, int64_t len) {
  (void)devptr;
  (void)len;
  return dawn_gpu_refuse_wasi("gpu_download_host");
}
dawn_adt *dawn_gpu_upload_bytes_host(int64_t devptr, const dawn_bytes *data) {
  (void)devptr;
  (void)data;
  return dawn_gpu_refuse_wasi("gpu_upload_bytes_host");
}
dawn_adt *dawn_gpu_download_bytes_host(int64_t devptr, int64_t nbytes) {
  (void)devptr;
  (void)nbytes;
  return dawn_gpu_refuse_wasi("gpu_download_bytes_host");
}
dawn_adt *dawn_gpu_launch_host(int64_t module, dawn_str *kernel, int64_t gx, int64_t gy,
                               int64_t gz, const dawn_array *args) {
  (void)module;
  (void)kernel;
  (void)gx;
  (void)gy;
  (void)gz;
  (void)args;
  return dawn_gpu_refuse_wasi("gpu_launch_host");
}
dawn_adt *dawn_gpu_free_host(int64_t devptr) {
  (void)devptr;
  return dawn_gpu_refuse_wasi("gpu_free_host");
}
dawn_adt *dawn_gpu_sync_host(void) { return dawn_gpu_refuse_wasi("gpu_sync_host"); }
dawn_unit dawn_gpu_close_host(void) { return DAWN_UNIT; }
#endif
/* === DAWN_RT_GPU_END === */
