#!/usr/bin/env python3
"""Remove one F1 boundary in a private compiler copy.

The contract requires the owning checker test to fail, or requires ASan to
name use-after-free in the emitted call. Compilation failures never count.
The preflight applies these same exactly-once anchors before any build.
"""
from pathlib import Path
import sys

CHECKER = "selfhost/src/check/checker.dawn"
MUTATIONS = {
    "pub-open": ((CHECKER, "      if d.vis == VisPub {", "      if d.vis == VisPub && false {"),),
    "io-open": (
        (CHECKER, '      if d.effs != ["io"] || s.eff != EIo {', "      if false {"),
        (CHECKER, 'cx1 = record_effect(cx1, EIo, lo, hi, "extern c " ++ sym)',
         'cx1 = record_effect(cx1, EPure, lo, hi, "extern c " ++ sym)'),
    ),
    "symbol-open": ((CHECKER, "      if not extern_symbol_ok(sym) {", "      if false {"),),
    "borrow-drop": (("selfhost/src/c/emitc.dawn",
        '      let (st1, cargs) = emit_ordered(st, args, borrowed)\n',
        '      let (st0, cargs) = emit_ordered(st, args, borrowed)\n'
        '      let st1 = if sym == "f1_text" {\n'
        '        line(st0, "dawn_drop(" ++ cargs[0] ++ ");")\n'
        '      } else { st0 }\n'),),
}

def main():
    name, root = sys.argv[1], Path(sys.argv[2])
    for rel, old, new in MUTATIONS[name]:
        p = root / rel
        source = p.read_text()
        if source.count(old) != 1:
            raise SystemExit(f"{name}: mutation anchor in {rel} is not unique ({source.count(old)} matches)")
        p.write_text(source.replace(old, new))

if __name__ == "__main__":
    main()
