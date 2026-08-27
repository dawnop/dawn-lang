#!/usr/bin/env python3
"""Apply one production mutation to a copy of runtime/c.

The copy is what gets compiled; this never touches the working tree. Every
anchor is matched exactly once or the mutation refuses to apply -- a drifted
anchor that silently patched nothing would leave the harness measuring the
unmutated runtime, which is the failure a mutant matrix exists to rule out.
"""

from pathlib import Path
import sys


MUTATIONS = {
    # The retreat this knife came from: hand back a fresh allocation for every
    # field-less constructor instead of the shared immortal object. Byte for
    # byte the behaviour before the singleton landed, so everything the rest of
    # this file checks stays green under it.
    "revert-adt0-to-fresh-allocation": (
        "dawn_rt.h",
        """static inline dawn_adt *dawn_adt0(int32_t tag) {
  if (tag >= 0 && tag < DAWN_ADT0_TAGS) {
    dawn_adt0_hits++;
    return (dawn_adt *)&dawn_adt0_table[tag];
  }
  dawn_adt0_missed++;
  return dawn_adt_new(tag, 0, 0);
}""",
        """static inline dawn_adt *dawn_adt0(int32_t tag) {
  dawn_adt0_missed++;
  return dawn_adt_new(tag, 0, 0);
}""",
    ),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <runtime-dir>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    name, old, new = MUTATIONS[mutation]
    path = root / name
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{mutation}: mutation anchor drifted ({count} matches)")
    path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
