/* Ownership contract for the C retained root.
 *
 * This sits with the cross-backend session rather than exposing a test-only
 * clearing primitive. Replacement is observable through a second holder's
 * count; process-exit cleanup is observable through a child held by both the
 * retained parent and an atexit probe registered before dawn_rt_init. */
#define _POSIX_C_SOURCE 200809L

#include "dawn_rt.h"

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "../rc-contract/unicode_stubs.h"

static dawn_box *exit_child;

static void exit_probe(void) {
  if (dawn_reactor_state_has() || exit_child == NULL ||
      !dawn_is_unique(exit_child) || exit_child->val.i != 77) {
    fputs("FAIL: retained root was not released before the exit probe\n", stderr);
    _Exit(1);
  }
  dawn_drop(exit_child);
  exit_child = NULL;
  puts("retained_rc_exit PASS");
  fflush(stdout);
}

int main(int argc, char **argv) {
  if (atexit(exit_probe) != 0) return 2;
  dawn_rt_init(argc, argv);
  if (dawn_reactor_state_has()) return 3;

  /* set borrows and roots its own reference; get returns another owned one. */
  dawn_box *first = dawn_box_int(11);
  dawn_box *held = (dawn_box *)dawn_dup(first);
  dawn_reactor_state_set(first);
  dawn_drop(first);
  dawn_box *seen = (dawn_box *)dawn_reactor_state_get();
  if (seen != held || held->h.rc != 3 || seen->val.i != 11) return 4;
  dawn_drop(seen);

  /* Replacing releases exactly the slot's old reference. */
  dawn_box *second = dawn_box_int(22);
  dawn_reactor_state_set(second);
  dawn_drop(second);
  if (!dawn_is_unique(held) || held->val.i != 11) return 5;
  dawn_drop(held);

  /* Replacing a root by the value returned from get is alias-safe. */
  dawn_box *same = (dawn_box *)dawn_reactor_state_get();
  dawn_reactor_state_set(same);
  dawn_drop(same);
  same = (dawn_box *)dawn_reactor_state_get();
  if (same->h.rc != 2 || same->val.i != 22) return 6;
  dawn_drop(same);

  /* The retained parent owns one child reference; the exit probe owns the
   * other. Cleanup must drop the parent first, leaving that probe unique. */
  exit_child = dawn_box_int(77);
  dawn_adt *parent = dawn_adt_new(0, 1, UINT64_C(1));
  parent->fields[0].p = dawn_dup(exit_child);
  dawn_reactor_state_set(parent);
  dawn_drop(parent);

  puts("retained_rc_replace PASS");
  return 0;
}
