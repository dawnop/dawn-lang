#!/usr/bin/env python3
"""Apply one wasm-dom production mutation to a copy of the repository tree.

    scripts/wasm-dom-contract/mutate.py <mutation> <tree-root>

The anchors used to live in two harnesses of this directory, each checked
only when that harness reached the mutant, after the native driver, node and
a wasm toolchain had run the clean sessions. retained.sh passed its std/
reactor.dawn anchors to an `apply_exact_mutant` helper that refused a
non-unique match (#254). flags.sh was weaker: it applied sed programs and
counted a mutant applied when the file changed at all (#277). Declared here,
in the registry shape mutation-anchor-preflight.py discovers, every anchor
is a literal that must match exactly once: each harness applies one
mutation per private tree, and the preflight proves all of them before any
build. The seam mutants in retained.sh append text rather
than replace it, so they have no anchor and stay there.

A mutation is an ordered tuple of edits, each applied to the text the previous
one left. The paths are relative to the tree root the caller passes: each
harness lays its tree out as the checkout (`<root>/std`, `<root>/packages`),
so the preflight can hand this script the checkout.
"""

from pathlib import Path
import sys

REACTOR = "std/reactor.dawn"
DOM_REACTOR = "packages/tea-dom/src/reactor.dawn"
WIRE = "packages/tea-dom/src/wire.dawn"
JS_REACTOR = "packages/tea-dom/js/reactor.mjs"
JS_APP = "packages/tea-dom/js/app.mjs"

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

    # flags.sh: the host half of init flags, then the guest half.
    "absent-flag-becomes-empty": ((
        JS_REACTOR,
        'if (flags !== undefined) request.flags = flags;',
        'request.flags = flags === undefined ? "" : flags;',
    ),),
    "mount-drops-the-flags": ((
        JS_APP,
        'settle(reactor.init(flags));',
        'settle(reactor.init());',
    ),),
    "flags-ignored-at-the-turn": ((
        DOM_REACTOR,
        '      let m0 = init(flags)',
        '      let m0 = init(None)',
    ),),
    "flags-never-decoded": ((
        WIRE,
        'match as_opt_string(field(entries, "flags")) {',
        'match as_opt_string(field(entries, "nope")) {',
    ),),
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
