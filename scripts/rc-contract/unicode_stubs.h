/* The Unicode tables are `extern` in the runtime and emitted by the compiler
 * alongside the program (emitc's `emit_case_table`). Nothing in this
 * directory touches case or classification, so empty ones are enough to
 * link. Shared by rc_test.c and poison_probe.c rather than copied, because
 * two copies of a link-time stub drift silently: the second one only breaks
 * when the table's shape changes, and then it breaks as a linker error in
 * whichever program happened to be built second. */
#ifndef DAWN_RC_CONTRACT_UNICODE_STUBS_H
#define DAWN_RC_CONTRACT_UNICODE_STUBS_H

#include "dawn_rt.h"

const dawn_case_range dawn_upper_ranges[] = {{0, 0, 0}};
const int64_t dawn_upper_ranges_n = 0;
const dawn_case_range dawn_lower_ranges[] = {{0, 0, 0}};
const int64_t dawn_lower_ranges_n = 0;
const dawn_cp_range dawn_letter_ranges[] = {{0, 0}};
const int64_t dawn_letter_ranges_n = 0;
const dawn_cp_range dawn_digit_ranges[] = {{0, 0}};
const int64_t dawn_digit_ranges_n = 0;
const dawn_cp_range dawn_upper_class_ranges[] = {{0, 0}};
const int64_t dawn_upper_class_ranges_n = 0;
const dawn_cp_range dawn_lower_class_ranges[] = {{0, 0}};
const int64_t dawn_lower_class_ranges_n = 0;
const dawn_cp_range dawn_space_ranges[] = {{0, 0}};
const int64_t dawn_space_ranges_n = 0;

#endif /* DAWN_RC_CONTRACT_UNICODE_STUBS_H */
