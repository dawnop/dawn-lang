#!/usr/bin/env python3
"""Apply one production mutation to a copy of runtime/c.

Same arrangement as scripts/rc-contract/mutate.py: the copy is what gets
compiled, the working tree is never touched, and every anchor must match
exactly once or the mutation refuses to apply. A drifted anchor that patched
nothing would leave the harness measuring the unmutated runtime, which is the
one failure a mutant matrix exists to rule out.

The three below are the standing form of knife 5's hand-run negative controls
2, 4 and (new) a positive one; docs/oneshot-design.md 11.10 records what each
was observed to do when it was run by hand.
"""

from pathlib import Path
import sys


MUTATIONS = {
    # Knife 5's negative control 2. A carrier that has not run out is dropped
    # on the floor instead of being told to die and unwound: the thread stays
    # parked forever, holding its frames and everything they own.
    #
    # This is the mutant the leg rests on. Every answer the program prints
    # under it is correct, and LeakSanitizer says nothing -- a parked thread's
    # stack is a root, so the leaked frames are all reachable. `dawn_ctl_live`
    # is the only thing in the tree that can tell, which is why a gate that
    # cannot go red here is a gate that has stopped watching it.
    "ctl-never-reclaims": (
        """  if (!c->finished) {
    c->die = true;
    dawn_ctl_switch_to(c);
  }""",
        """  if (!c->finished) {
    return;
  }""",
    ),
    # Knife 5's negative control 4, and the other half of the pair. The
    # carrier is still reclaimed -- the count comes back to zero and the
    # report stays quiet -- but it gets there by jumping straight to the base
    # handler instead of forcing an unwind through the frames, so no frame's
    # `dawn_own_drop` runs. The thread then exits, its stack goes away, and
    # what it held becomes unreachable: exactly the leak LeakSanitizer *can*
    # see, on the same code path where the mutant above leaves it blind.
    "ctl-discard-skips-cleanups": (
        """  dawn_ctl_discarding = true;
  dawn_unwind_to(h);""",
        """  dawn_ctl_discarding = true;
  longjmp(h->jb, 1);""",
    ),
    # The positive control. One waiter is all a baton ever has, so waking one
    # rather than all of them is the same handoff -- and the whole roster has
    # to stay green under it. Without a mutant of this role, "reddened
    # nothing" and "was never built" are the same empty red set.
    "ctl-signals-one-waiter": (
        """  pthread_mutex_lock(&c->m);
  c->turn = 1;
  pthread_cond_broadcast(&c->cv);""",
        """  pthread_mutex_lock(&c->m);
  c->turn = 1;
  pthread_cond_signal(&c->cv);""",
    ),
}


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: mutate.py <mutation> <runtime-dir>", file=sys.stderr)
        return 2
    name, out = sys.argv[1], Path(sys.argv[2])
    if name not in MUTATIONS:
        print(f"unknown mutation {name}", file=sys.stderr)
        return 2
    old, new = MUTATIONS[name]
    path = out / "dawn_rt.c"
    src = path.read_text()
    hits = src.count(old)
    if hits != 1:
        print(f"{name}: anchor matched {hits} times, expected 1", file=sys.stderr)
        return 1
    path.write_text(src.replace(old, new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
