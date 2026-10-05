#!/usr/bin/env python3
"""Put back one way of getting the JVM side table wrong, in a copy of the tree.

    scripts/jvm-map/mutate.py <mutation> <tree-root>

run.py beside this file applies each entry to a private copy, builds a
compiler from it and requires the named check to go red. Each entry is the
smallest edit that breaks one promise docs/source-span-map-design.md section
13 makes, and nothing else:

  leak            the classes `--map` writes come from the labelled emission:
                  `dead.dawn`'s class is then not the class written without
                  `--map` (check.py's same rule; design 13.4);
  no-compare      a labelled class is trusted without comparing it to the plain
                  one, so `dead.dawn` keeps pcs read off a class that was never
                  written (check.py's placed rule);
  inv-early       a direct call's instruction label goes in front of its
                  arguments, so `ipc` names the first argument's instruction
                  (check.py's called rule);
  hi-is-lo        a call's end label is its start label, so its range is empty
                  and its instruction outside it (check.py's bounds rule);
  absolute        the side table writes a site's declaration-relative offsets
                  as they are, without the declaration's base (check.py's
                  paired rule);
  len-off         classread reads a method's code length one byte long
                  (check.py's method rule);
  no-widen-check  a method ASM widened a jump in after the labels were read
                  keeps its pcs, which now point at the wrong instructions
                  (check.py's called and bounds rules, on the kernels'
                  `goto_w` method).

A mutation is an ordered tuple of edits, each applied to the text the previous
one left, each anchor matching exactly once (mutation-anchor-preflight.py
proves that on every push without building anything).
"""

from pathlib import Path
import sys

EMIT = "selfhost/src/jvm/emit.dawn"
JMAP = "selfhost/src/jvm/jmap.dawn"
CLASSREAD = "selfhost/src/jvm/classread.dawn"

MUTATIONS = {
    "leak": ((
        EMIT,
        "    own_trait_ids, own_adt_ids, tm, lm, live, ct, all_consts, src, decls, false)\n"
        "  let (labelled, rows, fns)",
        "    own_trait_ids, own_adt_ids, tm, lm, live, ct, all_consts, src, decls, true)\n"
        "  let (labelled, rows, fns)",
    ),),
    "no-compare": ((
        EMIT,
        "  let same = plain == class_of(labelled, class_name)\n",
        "  let same = true\n",
    ),),
    "inv-early": ((
        EMIT,
        "    CDirect(owner, name) -> {\n      let g1 = gen_cargs(gx, g, args)\n",
        "    CDirect(owner, name) -> {\n      visit_at(g.mv, at)\n      let g1 = gen_cargs(gx, g, args)\n",
    ), (
        EMIT,
        "      visit_at(g1.mv, at)\n      g1.mv.visitMethodInsn(OP_INVOKESTATIC, owner, name, d, false)\n",
        "      g1.mv.visitMethodInsn(OP_INVOKESTATIC, owner, name, d, false)\n",
    ),),
    "hi-is-lo": ((
        EMIT,
        "JMark { site: site, what: what, lo: lo, inv: inv, hi: hi }",
        "JMark { site: site, what: what, lo: lo, inv: inv, hi: lo }",
    ),),
    "absolute": ((
        JMAP,
        "    Some(b) -> match coresites.site_abs(b, r.site) {\n",
        "    Some(_) -> match coresites.site_abs(0, r.site) {\n",
    ),),
    "len-off": ((
        CLASSREAD,
        "{ return u4(b, at + 10) }",
        "{ return u4(b, at + 10) + 1 }",
    ),),
    "no-widen-check": ((
        JMAP,
        "      sound = map.insert(sound, symbol(f), mm.same && f.end == n)\n",
        "      sound = map.insert(sound, symbol(f), mm.same)\n",
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
