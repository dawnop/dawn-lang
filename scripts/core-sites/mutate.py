#!/usr/bin/env python3
"""Put back one way of getting Core's call sites wrong, in a copy of the tree.

    scripts/core-sites/mutate.py <mutation> <tree-root>

run.py beside this file applies each entry to a private copy, builds a
compiler from it and requires the named check to go red. Each entry is the
smallest edit that breaks one promise docs/source-span-map-design.md section 7
makes, and nothing else:

  absolute       lowering stores file positions instead of declaration
                 offsets, so a site is placed one declaration base too far
                 (check.py's sound rule);
  nlo            the callee-name start points somewhere other than where the
                 rule in force says (check.py's NLO rule; while NLO is "stub"
                 that is the call's own start);
  rc-drops-site  the Perceus pass rebuilds a call without the site it had,
                 which only a listing taken after rc can see (check.py's
                 complete rule);
  dump-prints    the Core dump prints a site, the thing the earlier "Core has
                 no spans" rulings forbade; run.py requires the dump of the
                 corpus to change, which is what selfhost-core-diff.sh would
                 then report on every pure move.

A mutation is an ordered tuple of edits, each applied to the text the previous
one left, each anchor matching exactly once (mutation-anchor-preflight.py
proves that on every push without building anything).
"""

from pathlib import Path
import sys

LOWER = "selfhost/src/ir/lower.dawn"
RC = "selfhost/src/c/rc.dawn"
DUMP = "selfhost/src/ir/coredump.dawn"

MUTATIONS = {
    "absolute": ((
        LOWER,
        "if st.base < 0 { CNoSite } else { CAt(lo - st.base, hi - st.base, nlo - st.base) }",
        "if st.base < 0 { CNoSite } else { CAt(lo, hi, nlo) }",
    ),),
    "nlo": ((
        LOWER,
        """      let site = if str.contains(name, "\\$default\\$") { CNoSite } else { site_at(st, lo, hi, lo) }""",
        """      let site = if str.contains(name, "\\$default\\$") { CNoSite } else { site_at(st, lo, hi, hi - 1) }""",
    ),),
    "rc-drops-site": ((
        RC,
        """          let (st2, lets2, args1, temps2) = consume_all(st1, args, cbase)
          wrap(st2, lets ++ lets2, CCall(c1, args1, cty, site), cty, temps ++ temps2)""",
        """          let (st2, lets2, args1, temps2) = consume_all(st1, args, cbase)
          wrap(st2, lets ++ lets2, CCall(c1, args1, cty, CNoSite), cty, temps ++ temps2)""",
    ),),
    "dump-prints": ((
        DUMP,
        "  CModule, CFun, CParam, CMode, COwned, CBorrowed,\n",
        "  CModule, CFun, CParam, CMode, COwned, CBorrowed, CNoSite,\n",
    ), (
        DUMP,
        """    CCall(callee, args, t, _) -> {
      var out = ind(d) ++ "call " ++ callee_line(adts, callee) ++ ty(adts, t) ++ "\\n\"""",
        """    CCall(callee, args, t, site) -> {
      let at = match site {
        CNoSite -> ""
        _ -> " sited"
      }
      var out = ind(d) ++ "call " ++ callee_line(adts, callee) ++ ty(adts, t) ++ at ++ "\\n\"""",
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
