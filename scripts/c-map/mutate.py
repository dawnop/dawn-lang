#!/usr/bin/env python3
"""Put back one way of getting the C side table wrong, in a copy of the tree.

    scripts/c-map/mutate.py <mutation> <tree-root>

run.py beside this file applies each entry to a private copy, builds a
compiler from it and requires the named check to go red. Each entry is the
smallest edit that breaks one promise docs/source-span-map-design.md section
12 makes, and nothing else:

  text-leak         `line` writes a different line when the map is on: the C
                    is no longer the same with and without `--map` (check.py's
                    same rule; design 12.4);
  no-claim          `line` never looks at the waiting calls, so no expression
                    call finds its line (check.py's paired rule);
  head-shift        `emit_fn` moves a body's rows by the transcript before it
                    but not by the function's own head lines, so every row of
                    a function with a frame or a shadowed parameter is a line
                    or more early (check.py's named rule);
  col-pad           a line's columns are counted without its indentation
                    (check.py's named rule);
  unit-off          the unit table starts every unit one line late, so a row
                    moved into its `--split` file lands on the wrong line
                    (check.py's units rule);
  same-line-twin    a claimed occurrence does not move the text's cursor, so
                    the second of two identical calls on one line takes the
                    first one's occurrence. The emitter never writes two
                    identical call texts on one line today, so this is the
                    `claim` test block's to catch (`dawn test selfhost`); the
                    checker's own rule is held red by `check.py --self-test`;
  prefix-enclosing  one cursor for every text, so a call whose text sits at
                    the start of its enclosing call's text is claimed and the
                    enclosing call is then looked for only after it: it never
                    finds its line (check.py's paired rule, on `h(h(x))` in the
                    corpus).

A mutation is an ordered tuple of edits, each applied to the text the previous
one left, each anchor matching exactly once (mutation-anchor-preflight.py
proves that on every push without building anything).
"""

from pathlib import Path
import sys

EMITC = "selfhost/src/c/emitc.dawn"
CDRIVER = "selfhost/src/c/cdriver.dawn"

MUTATIONS = {
    "text-leak": ((
        EMITC,
        "  let st1 = CSt { ..st, out: st.out ++ [l] }\n",
        "  let st1 = CSt { ..st, out: st.out ++ [if st.mapping { pad(st.ind) ++ text ++ \" \\n\" } else { l }] }\n",
    ),),
    "no-claim": ((
        EMITC,
        "  if len(st.pend) == 0 { st1 } else { claim(st1, l, len(st.out)) }\n",
        "  st1\n",
    ),),
    "head-shift": ((
        EMITC,
        "placed_rows(st3, f, len(st.out) + len(head))",
        "placed_rows(st3, f, len(st.out))",
    ),),
    "col-pad": ((
        EMITC,
        "  if len(st.pend) == 0 { st1 } else { claim(st1, l, len(st.out)) }\n",
        "  if len(st.pend) == 0 { st1 } else { claim(st1, text ++ \"\\n\", len(st.out)) }\n",
    ),),
    "unit-off": ((
        CDRIVER,
        "    out = out ++ [(k, unit_file(k), marks[k] + 1, last)]\n",
        "    out = out ++ [(k, unit_file(k), marks[k] + 2, last)]\n",
    ),),
    "same-line-twin": ((
        EMITC,
        "        cursor = map.insert(cursor, p.text, hi)\n",
        "        cursor = map.insert(cursor, p.text, lo)\n",
    ),),
    "prefix-enclosing": ((
        EMITC,
        "    let from = match map.get(cursor, p.text) {\n",
        "    let from = match map.get(cursor, \"\") {\n",
    ), (
        EMITC,
        "        cursor = map.insert(cursor, p.text, hi)\n",
        "        cursor = map.insert(cursor, \"\", hi)\n",
    ),),
}


def apply(name: str, root: Path) -> None:
    for rel, old, new in MUTATIONS[name]:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise SystemExit(f"mutate.py: {name}: {rel} has {text.count(old)} of its anchor, expected 1")
        path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in MUTATIONS:
        raise SystemExit(f"usage: mutate.py <{'|'.join(MUTATIONS)}> <tree-root>")
    apply(sys.argv[1], Path(sys.argv[2]))


if __name__ == "__main__":
    main()
