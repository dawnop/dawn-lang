#!/usr/bin/env python3
"""Apply one lifecycle mutant's edit to a copy of the repository tree.

    scripts/lsp-lifecycle-contract/mutate.py <mutation> <tree-root>

The anchors used to live in a Python heredoc inside run.sh, which refused a
non-unique match only when the lsp-workspace job built that mutant's compiler.
lsp/server.dawn is rewritten by most editor-side changes, so a drifted anchor
surfaced as a red job long after the edit that moved it (#277). Declared here,
in the registry shape mutation-anchor-preflight.py discovers, the same
anchors have two consumers: run.sh applies one mutant per private selfhost
copy, and the preflight proves every one exactly-once before any build.

Which lifecycle case each mutant has to turn red, and with what message,
stays in run.sh beside its assertions. A mutation is an ordered tuple of
edits, each applied to the text the previous one left, with paths relative to
the tree root.
"""

from pathlib import Path
import sys

SERVER = "selfhost/src/lsp/server.dawn"

MUTATIONS = {
    "gate-after-update": ((
        SERVER,
        "          let gate = lifecycle_gate(st.lifecycle, msg)\n",
        """          match update_of(msg) {
            Some(update) -> { pending = Some(update) }
            None -> ()
          }
          let gate = lifecycle_gate(st.lifecycle, msg)
""",
    ),),
    "early-exit-zero": ((
        SERVER,
        "const ABNORMAL_EXIT_STATUS: Int = 1",
        "const ABNORMAL_EXIT_STATUS: Int = 0",
    ),),
    "shutdown-continues": ((
        SERVER,
        """    Shutdown -> {
      if method == "exit" && not request {
        LgExit(0)
      } else if request {
        LgReject(-32600, "Invalid Request")
      } else {
        LgIgnore
      }
    }""",
        """    Shutdown -> {
      if method == "exit" && not request {
        LgExit(0)
      } else if request {
        LgDispatch
      } else {
        LgIgnore
      }
    }""",
    ),),
    "shutdown-flushes": ((
        SERVER,
        """            LgBeginShutdown -> {
              pending = None
              st = LspState { ..st, lifecycle: Shutdown }""",
        """            LgBeginShutdown -> {
              st = flush(st, pending)
              pending = None
              st = LspState { ..st, lifecycle: Shutdown }""",
    ),),
    "repeat-initialize": ((
        SERVER,
        """      } else if method == "initialize" {
        if request { LgReject(-32600, "Invalid Request") } else { LgIgnore }""",
        """      } else if method == "initialize" {
        if request { LgDispatch } else { LgIgnore }""",
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
