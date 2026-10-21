/* The public header deliberately provides no dup/drop. These implementations
 * copy borrowed inputs and hand an owned result back to the generated wrapper.
 * Reusing each input after its call catches an accidental ownership transfer. */
#include "dawn_ffi.h"
DAWN_FFI_REQUIRE(1);
int64_t DAWN_EXTERN(f1_add)(int64_t x) { return x + 11; }
dawn_str *DAWN_EXTERN(f1_text)(dawn_str *s) {
  return dawn_ffi_str_copy(dawn_ffi_str_data(s), dawn_ffi_str_len(s));
}
dawn_bytes *DAWN_EXTERN(f1_blob)(dawn_bytes *b) {
  return dawn_ffi_bytes_copy(dawn_ffi_bytes_data(b), dawn_ffi_bytes_len(b));
}
dawn_adt *DAWN_EXTERN(f1_result)(dawn_adt *r) {
  if (dawn_ffi_is_ok(r)) {
    const dawn_str *s = dawn_ffi_payload(r);
    return dawn_ffi_ok(dawn_ffi_str_copy(dawn_ffi_str_data(s), dawn_ffi_str_len(s)));
  }
  return dawn_ffi_err(dawn_ffi_cstr(dawn_ffi_err_kind(r)), dawn_ffi_cstr(dawn_ffi_err_message(r)));
}
dawn_adt *DAWN_EXTERN(f1_option)(dawn_adt *o) {
  if (!dawn_ffi_is_some(o)) return dawn_ffi_none();
  const dawn_str *s = dawn_ffi_payload(o);
  return dawn_ffi_some(dawn_ffi_str_copy(dawn_ffi_str_data(s), dawn_ffi_str_len(s)));
}
double DAWN_EXTERN(f1_float)(double x) { return x + 0.5; }
bool DAWN_EXTERN(f1_bool)(bool x) { return !x; }
dawn_unit DAWN_EXTERN(f1_unit)(void) { return DAWN_UNIT; }
