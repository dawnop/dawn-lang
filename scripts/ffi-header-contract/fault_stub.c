/* A stub that reaches past the surface, on purpose: it calls `dawn_fault`,
 * which dawn_ffi.h does not export. run.sh compiles it against the real header
 * and requires the compile to FAIL (the poison), then against the header with
 * that name taken out of the fence and requires it to compile, so the red above
 * is the fence and not some other mistake in this file. */
#include "dawn_ffi.h"

int64_t DAWN_EXTERN(t_fault)(int64_t i) {
  if (i < 0) {
    dawn_fault(dawn_str_lit("no", 2));
  }
  return i;
}
