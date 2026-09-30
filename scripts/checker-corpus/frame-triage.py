#!/usr/bin/env python3
"""Every field of the checker's `Cx` says why it is not frame state (#204).

`checker.enter_isolated` builds an isolated body's context as
`Cx { ..cx, frame: Frame { ... } }`. The `Frame` literal is spelled out, so a
field added to `Frame` has to be answered for there. Nothing did the same for
a field added to `Cx`: it reaches the isolated body through the spread, asked
or not, and `initializing` (#198) did exactly that until #204 moved it into
`Frame`. What goes wrong then is a diagnostic, and no byte-level gate sees a
diagnostic change (docs/arch-split-design.md §5.4).

So the triage is written where the field is: the comment block directly above
each `Cx` field carries a line

    # frame-triage: <why this is not frame state>

and this script fails the corpus gate on a field without one, or with an empty
reason. It checks that the reason is there, not that it is right; the
`isolated_*` cases next door and the tests beside `leave_isolated` are what
hold the fields that did go into `Frame`.

Why a script and not an inline test in cx.dawn: a Dawn test that reads its
own source depends on the directory `dawn test` runs from, in two runners
(JVM and native) whose working directories nothing pins, and no test in
selfhost/ reads a repository file today. This runs from the corpus gate, which
every change under selfhost/ reaches.

It reads the `Cx` declaration as a whole-block inventory and locates nothing
to edit; a declaration it cannot find, or one with no fields, is red rather
than an empty pass.

    frame-triage.py             check selfhost/src/check/cx.dawn
    frame-triage.py --selftest  the parser on fixtures, including the controls
"""
import pathlib
import re
import sys

sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CX = "selfhost/src/check/cx.dawn"
HEAD = re.compile(r"^pub(?:\(pkg\))? type Cx = \{\s*$")
FIELD = re.compile(r"^  ([a-z_][a-z0-9_]*): ")
COMMENT = re.compile(r"^\s*#")
TRIAGE = re.compile(r"^\s*# frame-triage: (\S.*)$")


def untriaged(text: str) -> tuple[list[str], list[str]]:
    """The Cx fields, and those among them without a frame-triage reason."""
    lines = text.split("\n")
    heads = [i for i, line in enumerate(lines) if HEAD.match(line)]
    if len(heads) != 1:
        raise ValueError(f"expected exactly one `type Cx = {{` line, found {len(heads)}")
    fields: list[str] = []
    missing: list[str] = []
    block: list[str] = []
    for line in lines[heads[0] + 1:]:
        if line.startswith("}"):
            break
        if COMMENT.match(line):
            block.append(line)
            continue
        m = FIELD.match(line)
        if m:
            fields.append(m.group(1))
            if not any(TRIAGE.match(c) for c in block):
                missing.append(m.group(1))
        block = []
    else:
        raise ValueError("the `Cx` declaration is not closed")
    if not fields:
        raise ValueError("the `Cx` declaration has no fields")
    return fields, missing


def selftest() -> None:
    ok = ("pub(pkg) type Cx = {\n"
          "  # what it is\n"
          "  # frame-triage: an output\n"
          "  diags: List[Diag],\n"
          "  # frame-triage: module scope\n"
          "  fns: Map[String, Sig]\n"
          "}\n")
    assert untriaged(ok) == (["diags", "fns"], [])
    # the negative control: a field added without a reason
    added = ok.replace("  fns: Map[String, Sig]\n", "  fns: Map[String, Sig],\n  later: Int\n")
    assert untriaged(added) == (["diags", "fns", "later"], ["later"])
    # a reason belongs to the field below it, not to the next one as well
    shared = ok.replace("  # frame-triage: module scope\n", "")
    assert untriaged(shared)[1] == ["fns"]
    # a blank line ends the block the reason was in
    gap = ok.replace("  # frame-triage: an output\n", "  # frame-triage: an output\n\n")
    assert untriaged(gap)[1] == ["diags"]
    # an empty reason is no reason
    empty = ok.replace("# frame-triage: an output", "# frame-triage:")
    assert untriaged(empty)[1] == ["diags"]
    # a declaration it cannot find is red, not an empty pass
    for broken in ("pub type Frame = {\n  a: Int\n}\n", "pub(pkg) type Cx = {\n}\n",
                   "pub(pkg) type Cx = {\n  # frame-triage: x\n  a: Int\n"):
        try:
            untriaged(broken)
        except ValueError:
            continue
        raise AssertionError(f"accepted {broken!r}")
    print("OK: frame-triage self-test")


def main(argv: list[str]) -> int:
    if argv == ["--selftest"]:
        selftest()
        return 0
    if argv:
        print(__doc__.strip().split("\n\n")[-1], file=sys.stderr)
        return 2
    try:
        fields, missing = untriaged((ROOT / CX).read_text())
    except ValueError as e:
        print(f"FAIL: {CX}: {e}", file=sys.stderr)
        return 1
    if missing:
        for name in missing:
            print(f"FAIL: {CX}: Cx field `{name}` has no `# frame-triage:` reason. "
                  "Say why an isolated body may see it through `..cx`, or move it "
                  "into Frame (docs/arch-split-design.md §5.4)", file=sys.stderr)
        return 1
    print(f"OK: frame triage -- all {len(fields)} Cx fields say why they are not frame state")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
