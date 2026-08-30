#include "dawn_rt.h"

#include <stdint.h>
#include <stdio.h>

#include "unicode_stubs.h"

/* Exercise the configuration edge where one logical slab's last complete
 * block ends before its last materialization batch. The next request must
 * advance to the next 64KiB slot, not extend the previous slab past its
 * boundary. run.sh compiles this with DAWN_SL_BATCH=1024; 56 * 1152 is
 * exactly 63 batches, leaving one batch that contains no further block. */
int main(int argc, char **argv) {
  enum { slab_bytes = 65536, block_bytes = 1152 };
  enum { blocks_per_slab = slab_bytes / block_bytes };
  dawn_str *blocks[blocks_per_slab + 1];

  dawn_rt_init(argc, argv);
  for (size_t i = 0; i <= blocks_per_slab; i++) {
    blocks[i] = dawn_str_new(block_bytes - sizeof(dawn_str) - 1);
  }

  if (!dawn_slab_owns(blocks[0]) ||
      (uintptr_t)blocks[blocks_per_slab] !=
          (uintptr_t)blocks[0] + slab_bytes) {
    fprintf(stderr, "a batch tail crossed its logical slab boundary\n");
    return 1;
  }

  for (size_t i = 0; i <= blocks_per_slab; i++) {
    dawn_drop(blocks[i]);
  }
  puts("slab batch tail contract: OK");
  return 0;
}
