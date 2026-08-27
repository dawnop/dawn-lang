/* What the slab allocator does to memory safety, asked of a build that has
 * both the allocator and AddressSanitizer in it (-DDAWN_SLAB_FORCE).
 *
 * The oracle here is a report, and a sanitizer report is an abort, so unlike
 * rc_test.c this cannot be a roster inside one process: each probe is its own
 * run, named by argv[1], and run.sh turns what came out on stderr into the
 * `<name> PASS|FAIL` line the rest of the harness reads. The report to look
 * for is `use-after-poison` rather than `heap-use-after-free`: these blocks
 * are not malloc chunks, so what the sanitizer knows about them is only what
 * dawn_rt.c's poisoning told it. It also carries no allocation or free
 * stack, only the stack of the access, for the same reason.
 *
 * Nothing here calls libc's deallocator: a block the runtime made has to go
 * back through dawn_drop or dawn_free, and run.sh greps this directory to
 * keep it that way.
 *
 * A probe that reaches the end of main without a report prints "no report"
 * and exits 0. Whether it gets there is the answer being read, so nothing
 * below tries to keep the program in a sane state past the mistake it
 * makes. */
#include "unicode_stubs.h"

#include <stdio.h>
#include <string.h>

/* one boxed field, as in rc_test.c */
#define MASK1 UINT64_C(1)

/* Two blocks of this size are neighbours inside one slab: a dawn_str of 15
 * payload bytes is 16 + 15 + 1 = 32 bytes, exactly two grains, so the block
 * is its size class and there is no slack at the end to absorb an overflow.
 * A slab's free list is built in address order, so two of these taken in a
 * row are adjacent. */
#define NEIGHBOUR_PAYLOAD 15
#define NEIGHBOUR_BLOCK (2 * DAWN_SLAB_GRAIN)

int main(int argc, char **argv) {
  dawn_rt_init(argc, argv);
  const char *which = argc > 1 ? argv[1] : "";

  if (strcmp(which, "live") == 0) {
    /* The control. Everything a program is supposed to do with a block, so a
     * poisoning that is too eager reddens here and nowhere else. */
    dawn_adt *a = dawn_adt_new(0, 1, MASK1);
    a->fields[0].p = NULL;
    printf("rc while live = %u\n", (unsigned)a->h.rc);
    dawn_drop(a);
  } else if (strcmp(which, "uaf") == 0) {
    /* Offset zero, which is where the free list's link lives and where a
     * reference-counted object keeps its header. This is the probe that says
     * the link may stay inside the block: the block is poisoned whole on the
     * way out and unpoisoned whole on the way in, so outside the allocator
     * even its first word is unreadable. */
    dawn_adt *a = dawn_adt_new(0, 1, MASK1);
    a->fields[0].p = NULL;
    dawn_drop(a);
    printf("rc after free = %u\n", (unsigned)a->h.rc);
  } else if (strcmp(which, "uaf-write") == 0) {
    /* Past the first word, so a poisoning that only covered the link would
     * still be caught here. */
    dawn_str *s = dawn_str_new(24);
    void *p = s;
    dawn_drop(s);
    memset((char *)p + sizeof(dawn_str), 'x', 8);
  } else if (strcmp(which, "double-free") == 0) {
    /* The second drop reads the header of a block that is already on a free
     * list, so it is caught before it can corrupt the list. */
    dawn_adt *a = dawn_adt_new(0, 1, MASK1);
    a->fields[0].p = NULL;
    dawn_drop(a);
    dawn_drop(a);
  } else if (strcmp(which, "overflow") == 0) {
    /* Overflowing into a block that was never handed out. A slab is poisoned
     * whole when it is laid out, so the neighbour is unreadable. The write
     * runs one whole block past the end and no further, so what it reaches
     * is the neighbour and not the one after it. */
    dawn_str *a = dawn_str_new(NEIGHBOUR_PAYLOAD);
    memset(dawn_str_data(a), 'y', 2 * NEIGHBOUR_BLOCK - sizeof(dawn_str));
    dawn_drop(a);
  } else if (strcmp(which, "overflow-live") == 0) {
    /* The recorded gap, and the one probe here that is expected to report
     * nothing. Both neighbours are live, so both are unpoisoned, and without
     * red zones between blocks there is nothing in the shadow to trip over.
     * Red zones are not free: they change the block layout, which is the
     * free variable behind every number the allocator was written for, and
     * an allocator that walks its own arena cannot have them at all
     * (dawn_rt.c, "manual poisoning"). Kept as a probe rather than a comment
     * so the day that changes, this reddens and the record has to be
     * rewritten on purpose. Neither block is dropped afterwards: the
     * neighbour's header is 'y' bytes now, and dropping that would be a
     * different error from the one being asked about. */
    dawn_str *a = dawn_str_new(NEIGHBOUR_PAYLOAD);
    dawn_str *b = dawn_str_new(NEIGHBOUR_PAYLOAD);
    (void)b;
    memset(dawn_str_data(a), 'y', 2 * NEIGHBOUR_BLOCK - sizeof(dawn_str));
  } else {
    fprintf(stderr, "unknown probe: %s\n", which);
    return 2;
  }

  printf("no report\n");
  return 0;
}
