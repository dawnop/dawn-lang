#include "dawn_rt.h"

#include <stdint.h>
#include <stdio.h>

#include "unicode_stubs.h"

/* Exercise the configuration edge where one logical slab's last complete
 * block ends before its last materialization batch. The next request must
 * advance to the next 64KiB slot, not extend the previous slab past its
 * boundary. run.sh compiles this with DAWN_SL_BATCH=1024; 56 * 1152 is
 * exactly 63 batches, leaving one batch that contains no further block.
 *
 * A roster of its own, in a configuration of its own, because the production
 * batch of 32KiB never leaves such a tail: no assertion in rc_test.c can go
 * red when this boundary moves, so this file is the only thing that can tell.
 * matrix.txt's `slab-tail-crosses-the-slot` is that claim written down and
 * executed -- it reddens the line below and leaves the whole production
 * roster green. Without it this leg was a green nobody had ever seen fail,
 * and it stayed green against a runtime with no batching in it at all.
 *
 * The verdict is printed as `<name> PASS|FAIL`, the stream rc_test.c and the
 * probes already produce, so run.sh reads one kind of red set whichever leg
 * produced it. The exit status still says whether anything failed. */
int main(int argc, char **argv) {
  enum { slab_bytes = 65536, block_bytes = 1152 };
  enum { blocks_per_slab = slab_bytes / block_bytes };
  dawn_str *blocks[blocks_per_slab + 1];
  int failures = 0;

  dawn_rt_init(argc, argv);
  for (size_t i = 0; i <= blocks_per_slab; i++) {
    blocks[i] = dawn_str_new(block_bytes - sizeof(dawn_str) - 1);
  }

  /* Ownership is part of the same question rather than a check of its own: on
   * a build without the allocator the address below is malloc's and the
   * comparison would be meaningless, so that build has to fail here rather
   * than report a boundary it never had. */
  if (!dawn_slab_owns(blocks[0]) ||
      (uintptr_t)blocks[blocks_per_slab] !=
          (uintptr_t)blocks[0] + slab_bytes) {
    failures++;
  }
  printf("slab_tail_stays_in_its_slot %s\n", failures > 0 ? "FAIL" : "PASS");

  for (size_t i = 0; i <= blocks_per_slab; i++) {
    dawn_drop(blocks[i]);
  }
  return failures > 0 ? 1 : 0;
}
