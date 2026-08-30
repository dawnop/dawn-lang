#!/usr/bin/env python3
"""Apply one production mutation to a copy of runtime/c.

The copy is what gets compiled; this never touches the working tree. Every
anchor is matched exactly once or the mutation refuses to apply -- a drifted
anchor that silently patched nothing would leave the harness measuring the
unmutated runtime, which is the failure a mutant matrix exists to rule out.
"""

from pathlib import Path
import sys


MUTATIONS = {
    # The retreat this knife came from: hand back a fresh allocation for every
    # field-less constructor instead of the shared immortal object. Byte for
    # byte the behaviour before the singleton landed, so everything the rest of
    # this file checks stays green under it.
    "revert-adt0-to-fresh-allocation": (
        "dawn_rt.h",
        """static inline dawn_adt *dawn_adt0(int32_t tag) {
  if (tag >= 0 && tag < DAWN_ADT0_TAGS) {
    dawn_adt0_hits++;
    return (dawn_adt *)&dawn_adt0_table[tag];
  }
  dawn_adt0_missed++;
  return dawn_adt_new(tag, 0, 0);
}""",
        """static inline dawn_adt *dawn_adt0(int32_t tag) {
  dawn_adt0_missed++;
  return dawn_adt_new(tag, 0, 0);
}""",
    ),
    # ---- the slab allocator -------------------------------------------
    #
    # Five ways to lose one of the allocator's properties while staying a
    # working allocator, which is why they need their own assertions: a
    # program compiled against any of these still prints the right answers.
    # The third is the one the whole knife rests on -- it is correct in every
    # respect except the one the allocator was written for.
    #
    # None of them may hand a caller fewer bytes than it asked for. That
    # rules out the most literal spelling of the second (one free list for
    # every size, which would corrupt the heap of every case downstream of
    # it and cost the harness its per-assertion answer) in favour of merging
    # neighbouring classes, which reaches the same assertion by handing back
    # a block from the wrong class while still being large enough to use.
    #
    # Free blocks are never put back, so a slab only ever hands out the
    # blocks it was laid out with. Everything else holds: the counts are
    # right, the objects are right, and each slab still empties and retires.
    "slab-never-recycles": (
        "dawn_rt.c",
        """  if (s == dawn_sl_cur[cls]) {
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
  if (--s->used == 0) {""",
        """  if (s == dawn_sl_cur[cls]) {
    ASAN_POISON_MEMORY_REGION(p, cls * DAWN_SL_GRAIN);
    s->used--; /* the current slab is kept even at zero; see the heading */
    return;
  }
  ASAN_POISON_MEMORY_REGION(p, cls * DAWN_SL_GRAIN);
  if (--s->used == 0) {""",
    ),
    # Every class index is rounded up to the next odd one, so neighbouring
    # classes share a free list. Blocks are still big enough for what they
    # are handed to, so the damage is confined to the one property: a block
    # freed by one size class is reused by another.
    "slab-merges-size-classes": (
        "dawn_rt.c",
        """  size_t cls = (n + (DAWN_SL_GRAIN - 1)) / DAWN_SL_GRAIN;
  if (cls == 0) {
    cls = 1; /* a zero-byte request still answers a distinct address */
  }""",
        """  size_t cls = ((n + (DAWN_SL_GRAIN - 1)) / DAWN_SL_GRAIN) | 1u;""",
    ),
    # The load-bearing one. Empty slabs are kept without limit instead of
    # being handed back past DAWN_SLAB_KEEP, which is what the allocator was
    # written to do and the only property here that no answer a program
    # prints depends on. Every other assertion in this file stays green under
    # it, and so would every gate in the tree.
    "slab-never-retires": (
        "dawn_rt.c",
        """  if (dawn_sl_empty_n[cls] < DAWN_SL_KEEP) {
    dawn_sl_layout(s, cls);""",
        """  if (1) {
    dawn_sl_layout(s, cls);""",
    ),
    # The cap on what a size class covers is raised, so blocks the allocator
    # documents as malloc's come out of the reserve instead.
    "slab-swallows-oversize": (
        "dawn_rt.h",
        "#define DAWN_SLAB_MAX 2048u /* a bigger request goes to malloc */",
        "#define DAWN_SLAB_MAX 8192u /* a bigger request goes to malloc */",
    ),
    # Revert the on-demand first touch while leaving the logical slab size,
    # block count, lists and retirement policy alone. Programs still compute
    # the same answers; only a one-object class writes through all 64KiB again.
    "slab-eagerly-materializes": (
        "dawn_rt.c",
        "#define DAWN_SL_BATCH ((size_t)32768)",
        "#define DAWN_SL_BATCH ((size_t)65536)",
    ),
    # ---- argument-carrying dictionaries -------------------------------
    #
    # Three ways to get the interning wrong, and the reason all three are
    # here is that only one of them is a wrong answer. A program compiled
    # against any of them prints exactly what it printed before; what moves
    # is how much memory it is still holding when it has printed it.
    #
    # The retreat: nothing is ever found in the table, so every call
    # allocates, which is byte for byte the behaviour before the interning
    # landed. The wasm DOM contract's plateau leg is what this reddens out
    # in the tree; here it is the sharing assertion.
    "dict-intern-never-hits": (
        "dawn_rt.c",
        """static bool dawn_dict_same(const dawn_dict_entry *e, const dawn_dict *tmpl,
                           int32_t nargs, dawn_dict *const *args) {
  if (e->tmpl != tmpl || e->d->nargs != nargs) return false;""",
        """static bool dawn_dict_same(const dawn_dict_entry *e, const dawn_dict *tmpl,
                           int32_t nargs, dawn_dict *const *args) {
  return false;
  if (e->tmpl != tmpl || e->d->nargs != nargs) return false;""",
    ),
    # The key loses the arguments, so a template is one dictionary rather
    # than a family of them and the first instantiation is handed to every
    # later one. Nothing in the tree can construct that shape -- measured,
    # not assumed -- so the assertion it reddens is the only thing anywhere
    # that would notice, which is the whole reason that assertion is written
    # out by hand.
    #
    # Both halves of the key move, which is what makes this the mutant it is
    # named for. Narrowing the comparison alone is nearly a no-op: the hash
    # still spreads the family across buckets, so the wrong entry is one a
    # linear probe walks past only when the two collide, and a mutant whose
    # damage depends on a hash collision is a mutant that measures nothing.
    "dict-intern-ignores-args": (
        "dawn_rt.c",
        """  size_t h = dawn_dict_mix((size_t)0, (size_t)(uintptr_t)tmpl);
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
}""",
        """  return dawn_dict_mix((size_t)0, (size_t)(uintptr_t)tmpl);
}

static bool dawn_dict_same(const dawn_dict_entry *e, const dawn_dict *tmpl,
                           int32_t nargs, dawn_dict *const *args) {
  return e->tmpl == tmpl;
}""",
    ),
    # The positive control, and the only mutant in this file that must stay
    # green: every key hashes to the same bucket. Open addressing with an
    # exact comparison degrades to a linear scan under that, which is slower
    # and nothing else -- so a harness that reddened here would be reading
    # the probing rather than the identity.
    "dict-intern-hash-collides": (
        "dawn_rt.c",
        """    h = dawn_dict_mix(h, (size_t)(uintptr_t)args[i]);
  }
  return h;
}""",
        """    h = dawn_dict_mix(h, (size_t)(uintptr_t)args[i]);
  }
  return 0;
}""",
    ),
    # ---- the manual poisoning -----------------------------------------
    #
    # These two are invisible to everything above: without the sanitizer
    # there is no poisoning to break, so a plain build of either passes
    # every assertion in the file. They are read off poison_probe.c
    # instead, on a build that has both the sanitizer and the allocator.
    #
    # Free blocks stop being poisoned when they are handed back. The
    # allocator still allocates, still recycles and still retires, so every
    # answer stays right; what is lost is that a use-after-free on a slab
    # block is reported. This is the one that says the poisoning is load
    # bearing rather than decorative.
    "slab-forgets-to-poison": (
        "dawn_rt.c",
        """  if (s == dawn_sl_cur[cls]) {
    *(void **)p = dawn_sl_head[cls];
    dawn_sl_head[cls] = p;
    ASAN_POISON_MEMORY_REGION(p, cls * DAWN_SL_GRAIN);
    s->used--; /* the current slab is kept even at zero; see the heading */
    return;
  }
  *(void **)p = s->freelist;
  s->freelist = p;
  ASAN_POISON_MEMORY_REGION(p, cls * DAWN_SL_GRAIN);""",
        """  if (s == dawn_sl_cur[cls]) {
    *(void **)p = dawn_sl_head[cls];
    dawn_sl_head[cls] = p;
    s->used--; /* the current slab is kept even at zero; see the heading */
    return;
  }
  *(void **)p = s->freelist;
  s->freelist = p;""",
    ),
    # A free block is poisoned from its ninth byte on, leaving the free
    # list's link addressable. That is the shape someone reaches for when
    # they read "the link lives in the block" and conclude the first word
    # has to stay readable, and it is exactly what dawn_rt.c's argument for
    # keeping the link in the block rules out: the argument is that the
    # order of the calls leaves the whole block poisoned, offset zero
    # included, everywhere outside the allocator. Without this mutant that
    # argument is a paragraph; with it, it is the difference between a
    # probe that reports and one that does not.
    "slab-leaves-the-link-live": (
        "dawn_rt.c",
        """  if (s == dawn_sl_cur[cls]) {
    *(void **)p = dawn_sl_head[cls];
    dawn_sl_head[cls] = p;
    ASAN_POISON_MEMORY_REGION(p, cls * DAWN_SL_GRAIN);
    s->used--; /* the current slab is kept even at zero; see the heading */
    return;
  }
  *(void **)p = s->freelist;
  s->freelist = p;
  ASAN_POISON_MEMORY_REGION(p, cls * DAWN_SL_GRAIN);""",
        """  if (s == dawn_sl_cur[cls]) {
    *(void **)p = dawn_sl_head[cls];
    dawn_sl_head[cls] = p;
    ASAN_POISON_MEMORY_REGION((char *)p + sizeof(void *),
                              cls * DAWN_SL_GRAIN - sizeof(void *));
    s->used--; /* the current slab is kept even at zero; see the heading */
    return;
  }
  *(void **)p = s->freelist;
  s->freelist = p;
  ASAN_POISON_MEMORY_REGION((char *)p + sizeof(void *),
                            cls * DAWN_SL_GRAIN - sizeof(void *));""",
    ),
    # ---- a handler's state cells --------------------------------------
    #
    # `dawn_cell_set` is the runtime's only overwrite: everywhere else a value
    # is built once and never superseded, so this is the one place a release
    # can be forgotten. Forget it and the displaced value is held forever by a
    # slot that no longer names it -- for the accumulating arm this primitive
    # exists for, that is a leak per operation. Nothing a program prints
    # changes, and the corpus that exercises cells end to end runs under the
    # leak sanitizer but reports against the whole program rather than against
    # the store that caused it. The assertion below is what names the store.
    "cell-set-forgets-the-old-value": (
        "dawn_rt.c",
        """void dawn_cell_set(void *c, void *x) {
  dawn_adt *cell = (dawn_adt *)c;
  void *old = cell->fields[0].p;
  cell->fields[0].p = x;
  dawn_drop(old);
}""",
        """void dawn_cell_set(void *c, void *x) {
  dawn_adt *cell = (dawn_adt *)c;
  cell->fields[0].p = x;
}""",
    ),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <runtime-dir>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    name, old, new = MUTATIONS[mutation]
    path = root / name
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{mutation}: mutation anchor drifted ({count} matches)")
    path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
