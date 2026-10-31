/* Identical atom keys with different domains must remain distinguishable,
 * including after pack concatenation. No buffer identity is consulted. */
#include "dawn_rt.h"
#include <assert.h>

static dawn_adt *node(int64_t domain, int64_t payload, void *tail) {
  dawn_adt *p = dawn_adt_new(DAWN_TAG_EV_PACK, DAWN_EV_PACK_FIELDS, 6);
  p->fields[0].i = 21;
  p->fields[1].p = dawn_box_int(payload);
  p->fields[2].p = tail;
  p->fields[3].i = domain;
  return p;
}
int main(void) {
  dawn_adt *one = node(1, 11, dawn_unit_box);
  dawn_adt *two = node(2, 22, one);
  dawn_adt *bare = node(0, 33, two);
  void *joined = dawn_ev_append(one, bare);
  assert(dawn_unbox_int(dawn_ev_get_scoped(joined, 21, 1)) == 11);
  assert(dawn_unbox_int(dawn_ev_get_scoped(joined, 21, 2)) == 22);
  assert(dawn_unbox_int(dawn_ev_get(joined, 21)) == 33);
  assert(dawn_scope_new_key() != dawn_scope_new_key());
  dawn_drop(joined);
  dawn_drop(bare);
  return 0;
}
