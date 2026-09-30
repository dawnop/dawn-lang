#!/usr/bin/env python3
"""Apply one JsigLease mutant's edit to a copy of the repository tree.

    scripts/jsig-lease-contract/mutate.py <mutation> <tree-root> <first-jar> <second-jar>

The anchors used to be a Python heredoc in run.sh, which refused a moved
anchor only when the java-target-classpath job reached that mutant, after
building the fixture jars and the positive case (#277). Declared here, in the
registry shape mutation-anchor-preflight.py discovers, the same anchors have
two consumers: run.sh applies one mutant per case, and the preflight proves
every one exactly-once before any build.

The paths are the ones the edited files have in the checkout: jvm/jreflect.dawn
and this directory's probe.dawn. run.sh mutates a tree holding copies of those
two files and assembles each case's subject and app from it, so the anchors
are proven against the same text they are applied to. `merge-loaders` loads
the two fixture jars through one loader, and their paths exist only once
run.sh has built them, so its replacement names them by placeholder and the
jar arguments fill it in, as JSON strings, which Dawn reads as string
literals. The preflight passes stand-in paths: it proves anchors, not
replacements.

A mutation is an ordered tuple of edits, each applied to the text the
previous one left, with paths relative to the tree root.
"""

import json
from pathlib import Path
import sys

REFLECT = "selfhost/src/jvm/jreflect.dawn"
PROBE = "scripts/jsig-lease-contract/probe.dawn"
FIRST_JAR = "@FIRST_JAR@"
SECOND_JAR = "@SECOND_JAR@"

JSIG_FOR = """pub fn jsig_for(jars: List[String]) -> JsigLease !io = {
  let loader = loader_for(jars)
  lease_with(loader, target_has_asm(loader.base))
}"""

MUTATIONS = {
    "queries-use-system": ((
        REFLECT,
        JSIG_FOR,
        """pub fn jsig_for(jars: List[String]) -> JsigLease !io = {
  let loader = loader_for(jars)
  JsigLease { jsig: jsig_real(), close: () => loader.closeable.close() }
}""",
    ),),
    "parent-is-system": ((
        REFLECT,
        'let parent = ClassLoader.getPlatformClassLoader().expect("platform loader")',
        'let parent = ClassLoader.getSystemClassLoader().expect("system loader")',
    ),),
    "merge-loaders": ((
        REFLECT,
        JSIG_FOR,
        f"""pub fn jsig_for(jars: List[String]) -> JsigLease !io = {{
  let loader = loader_for([{FIRST_JAR}, {SECOND_JAR}])
  lease_with(loader, target_has_asm(loader.base))
}}""",
    ),),
    "drop-close": ((
        REFLECT,
        "JsigLease { jsig: jsig_with(loader.base, asm_bridge), close: () => loader.closeable.close() }",
        "JsigLease { jsig: jsig_with(loader.base, asm_bridge), close: () => () }",
    ),),
    "bypass-bracket": ((
        PROBE,
        "bracket(guarded, probe => probe.lease.close(), fail_after_load)",
        "fail_after_load(guarded)",
    ),),
}


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit("usage: mutate.py <mutation> <tree-root> <first-jar> <second-jar>")
    mutation, root, first_jar, second_jar = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    for rel, old, new in MUTATIONS[mutation]:
        path = root / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{mutation}: mutation anchor in {rel} is not unique "
                             f"({count} matches)")
        new = new.replace(FIRST_JAR, json.dumps(first_jar)).replace(SECOND_JAR, json.dumps(second_jar))
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
