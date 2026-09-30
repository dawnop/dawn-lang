#!/usr/bin/env python3
"""Apply one retained-root production mutation to a copy of the repository tree.

    scripts/wasm-dom-contract/mutate.py <mutation> <tree-root>

The anchors used to be arguments to retained.sh's `apply_exact_mutant` shell
helper, which refused a non-unique match. That made them self-once: correct,
but checked only when retained.sh ran, which needs the native driver, node and
a wasm toolchain before it reaches a mutant. They quote std/reactor.dawn.
Declared here, in the registry shape mutation-anchor-preflight.py already
discovers, the same anchors have two consumers: retained.sh applies one
mutation per private tree, and the preflight proves every one of them
exactly-once before any build (#254). The seam mutants in retained.sh append
text rather than replace it, so they have no anchor and stay there.

A mutation is an ordered tuple of edits, each applied to the text the previous
one left. The paths are relative to the tree root the caller passes:
retained.sh lays each mutant out as `<root>/std`, so the preflight can hand
this script the checkout.
"""

from pathlib import Path
import sys

REACTOR = "std/reactor.dawn"

MUTATIONS = {
    # The installed root is never read back.
    "drop-retained-state": ((
        REACTOR,
        "        if reactor_state_has() { Some(reactor_state_get()) } else { None }",
        "        None",
    ),),
    # Publish a provisional root before `step`, roll it back only after `step`
    # returns: a panicking init loses the old state.
    "commit-before-success": (
        (REACTOR,
         "      let attempted = catch_panic(() =>\n",
         "      match current {\n"
         "        Some(_) -> reactor_state_set(Root(advance: next_line => first(step, next_line)))\n"
         "        None -> ()\n"
         "      }\n"
         "      let attempted = catch_panic(() =>\n"),
        (REACTOR,
         "          Ok(answer) -> answer\n",
         "          Ok(answer) -> {\n"
         "            match current {\n"
         "              Some(root) -> reactor_state_set(root)\n"
         "              None -> ()\n"
         "            }\n"
         "            answer\n"
         "          }\n"),
    ),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    for rel, old, new in MUTATIONS[mutation]:
        path = root / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{mutation}: mutation anchor in {rel} is not unique "
                             f"({count} matches)")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
