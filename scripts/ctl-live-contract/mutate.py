#!/usr/bin/env python3
"""Apply one production mutation to a copy of runtime/c.

Same arrangement as scripts/rc-contract/mutate.py: the copy is what gets
compiled, the working tree is never touched, and every anchor must match
exactly once or the mutation refuses to apply. A drifted anchor that patched
nothing would leave the harness measuring the unmutated runtime, which is the
one failure a mutant matrix exists to rule out.

The first three are the standing form of knife 5's hand-run negative controls
2, 4 and (new) a positive one; docs/oneshot-design.md 11.10 records what each
was observed to do when it was run by hand. The last two are knife 6's, and
they are here rather than hand-run for the same reason: `discard` running the
releases is a behaviour with no other watcher, and a runtime that stopped
running them prints exactly what a correct one prints on stdout.
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
    c->run_releases = run_releases;
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
        """  dawn_ctl_discard_walking = run_releases;
  dawn_unwind_to(h);""",
        """  dawn_ctl_discard_walking = run_releases;
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
    # Knife 6. The landing predicate goes back to what it was before
    # `discard` existed: the walk skips every intermediate frame and stops
    # only at the base, so the frames are reclaimed and nothing a program
    # wrote runs on the way. That is exactly the bare-drop behaviour, applied
    # to the path that is supposed to differ from it -- and it is invisible on
    # stdout, which is why `releases_ran` is an assertion of its own.
    "ctl-discard-skips-releases": (
        """  if (dawn_ctl_discard_walking && h->discard_lands) {
    h->discard_lands = false;
    longjmp(h->jb, 1);
  }
""",
        "",
    ),
    # Knife 6. `discard` stops asking whether the ticket is still good. The
    # second discard then finds the carrier already gone and answers Unit
    # quietly instead of panicking, which is the #641 shape one step short of
    # running a release twice.
    "ctl-discard-ignores-the-ticket": (
        """  if (k->caps[1].i != f->gen) {
    dawn_panic(DAWN_LIT("dawn: continuation discarded after it was already "
                        "used"));
  }
""",
        "",
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
