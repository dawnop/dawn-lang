#!/usr/bin/env python3
"""Rewrite the call sites in a Core dump to placeholders, for selfhost-core-diff.sh.

A declaration that only moved changes the line and column of every site baked
into it and nothing else, and the question the Core diff answers is whether a
program's meaning moved (docs/source-location-design.md 5.4). Sites reach Core
in two shapes, and each rule matches exactly one of them:

  1. A failure message's suffix, ` at <file>.dawn:<line>:<col>` (L2), inside any
     string: `panic`, `todo`, `expect`, `e!` and `assert` fold their site into
     the message. The column-less ` at <file>.dawn:<line>` older revisions
     baked is rewritten too, so a base from before L2 still compares.
  2. A `Loc` (L4): a call's site passed as a value, which lowering writes as a
     string bound to a local of type `Loc` (`lower_caller`), so the dump reads

         let v1 : Loc
           str "src/m.dawn:4:3"

     A literal has no type in Core; the typed binding is what tells a site
     from a program's own string that happens to read like one. That string
     is a value the program computes with, and it is compared as written:
     rule 2 looks at the line before a `str`, never at the string alone
     (docs/caller-location-design.md 6).

The path is kept by both rules: a module that moved to another file is news.

    core-site-normalise.py <in> <out>
    core-site-normalise.py --selftest
"""

import re
import sys

SUFFIX = re.compile(r'( at [^ "]+\.dawn):[0-9]+:[0-9]+')
SUFFIX_OLD = re.compile(r'( at [^ "]+\.dawn):[0-9]+')
LOC_LET = re.compile(r'^\s*let \S+ : Loc$')
LOC_STR = re.compile(r'^(\s*str ")([^ "]+\.dawn):[0-9]+:[0-9]+(")$')


def normalise(text: str) -> str:
    out = []
    prev = ""
    for line in text.split("\n"):
        line = SUFFIX.sub(r"\1:<line>:<col>", line)
        line = SUFFIX_OLD.sub(r"\1:<line>", line)
        if LOC_LET.match(prev):
            line = LOC_STR.sub(r"\1\2:<line>:<col>\3", line)
        out.append(line)
        prev = line
    return "\n".join(out)


def selftest() -> None:
    cases = [
        # rule 1, both shapes
        ('    str "boom at src/m.dawn:4:3"', '    str "boom at src/m.dawn:<line>:<col>"'),
        ('    str "unwrapped None from f() at src/m.dawn:9"',
         '    str "unwrapped None from f() at src/m.dawn:<line>"'),
        # rule 2: a site bound as a Loc
        ('      let v1 : Loc\n        str "src/m.dawn:22:33"',
         '      let v1 : Loc\n        str "src/m.dawn:<line>:<col>"'),
        # a program's own string that reads like a site is a value, not a site
        ('    str "x.dawn:1:2"', '    str "x.dawn:1:2"'),
        ('      let v1 : String\n        str "x.dawn:1:2"', '      let v1 : String\n        str "x.dawn:1:2"'),
        # and so is anything a Loc binding holds that is not a site literal
        ('      let v1 : Loc\n        local v0 : Loc', '      let v1 : Loc\n        local v0 : Loc'),
    ]
    for given, want in cases:
        got = normalise(given)
        if got != want:
            print(f"FAIL: normalise({given!r})\n  got  {got!r}\n  want {want!r}", file=sys.stderr)
            sys.exit(1)
    # the case the rule exists to refuse, as the diff sees it: two dumps that
    # differ only in a user string shaped like a site must still differ
    base = 'fn m.f -> String\n  str "x.dawn:1:2"\n'
    head = 'fn m.f -> String\n  str "x.dawn:5:2"\n'
    if normalise(base) == normalise(head):
        print("FAIL: a user string shaped like a site was normalised away", file=sys.stderr)
        sys.exit(1)
    # and two that differ only in a Loc's line compare equal
    base = 'fn m.g -> Unit\n  let v1 : Loc\n    str "src/m.dawn:3:5"\n'
    head = 'fn m.g -> Unit\n  let v1 : Loc\n    str "src/m.dawn:4:5"\n'
    if normalise(base) != normalise(head):
        print("FAIL: a moved Loc was not normalised", file=sys.stderr)
        sys.exit(1)
    print(f"OK: core-site-normalise self-test, {len(cases) + 2} cases")


def main() -> None:
    if sys.argv[1:] == ["--selftest"]:
        selftest()
        return
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], encoding="utf-8") as f:
        text = f.read()
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(normalise(text))


if __name__ == "__main__":
    main()
