#!/usr/bin/env python3
"""Both backends implement the same set of inline primitives.

    ./scripts/intrinsic-parity.py

`lower.inline_intrinsics()` names the primitives no runtime module owns and
lowering does not remove -- the ones each backend writes instructions for
itself -- and `lower.jvm_only_intrinsics()` names the two only the JVM owes.
Nothing checked that either emitter agreed. `emit.gen_cintrinsic` and
`emitc.emit_intrinsic` each end in a `panic` for a name they have no arm for,
so a primitive present in one backend and absent from the other was a failure
in the *user's* compile, on whichever backend was short, and only when
something reached that name. The two were level when this was written because
the differential corpus happened to cover them, not because anything said they
had to be -- which is the property scripts/spike-native/known-red.txt already
warns about itself: an empty file means the corpus stopped catching things.

So this walks the table and reads the arms. It is textual because an arm is
instructions rather than a value: there is nothing for a Dawn test to call and
compare. That makes the anchors load-bearing, and a gate that greps for
something no longer there passes by finding nothing -- so every lookup below
fails loudly when it comes up empty, and the arm sets are checked in both
directions (a declared primitive with no arm, and an arm for nothing
declared).

The complementary half is a real test, in lower.dawn: that the groups
partition `types.builtins()` + `lower.internal_intrinsics()`, so a primitive
added and classified nowhere is caught there.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "selfhost" / "src"

FAILURES = []


def fail(msg):
    FAILURES.append(msg)


def read(name):
    return (SRC / name).read_text().split("\n")


def body(lines, header, where):
    """The lines of a top-level function, from its header to the next one.

    Nested functions are indented, so they stay inside; comment lines are
    dropped, so a name that only appears in prose is not an arm.
    """
    start = None
    for i, line in enumerate(lines):
        if line.startswith(header):
            start = i
            break
    if start is None:
        fail(
            f"{where}: no `{header}` any more. This gate reads that function's "
            f"arms; renaming it silently empties the gate, so the rename has "
            f"to come here too."
        )
        return []
    # the header line is kept: a one-line function carries its whole body
    # there, and no header spells an arm
    out = [lines[start]]
    for line in lines[start + 1 :]:
        if re.match(r"^(pub )?(fn|type|test|const) ", line) or line.startswith("# ----"):
            break
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return out


def names(lines, pattern, where, what):
    found = re.findall(pattern, "\n".join(lines))
    if not found:
        fail(
            f"{where}: found no {what}. The pattern this gate matches on has "
            f"moved; it must be updated rather than left matching nothing."
        )
    return found


def declared():
    """`inline_intrinsics()` and `jvm_only_intrinsics()`, as literal lists."""
    lines = read("ir/lower.dawn")
    inline = names(
        body(lines, "pub fn inline_intrinsics()", "lower.dawn"),
        r'"([A-Za-z_0-9]+)"',
        "lower.dawn",
        "names in inline_intrinsics()",
    )
    host = names(
        body(lines, "pub fn jvm_only_intrinsics()", "lower.dawn"),
        r'"([A-Za-z_0-9]+)"',
        "lower.dawn",
        "names in jvm_only_intrinsics()",
    )
    return set(inline), set(host)


def jvm_arms():
    lines = read("jvm/emit.dawn")
    # `gen_list_intrinsic` dispatches twice: an inner `target` table for the
    # primitives that are a plain std/pvec call, then a chain for the ones
    # that need a List<->Array conversion around them.
    lst = body(lines, "fn gen_list_intrinsic(", "emit.dawn")
    arms = set(
        names(lst, r'(?m)^\s+"([A-Za-z_0-9]+)" -> Some\(', "emit.dawn", "std/pvec targets")
    )
    arms |= set(names(lst, r'name == "([A-Za-z_0-9]+)"', "emit.dawn", "list-crossing arms"))
    arms |= set(
        names(
            body(lines, "fn gen_cintrinsic(", "emit.dawn"),
            r'name == "([A-Za-z_0-9]+)"',
            "emit.dawn",
            "arms in gen_cintrinsic",
        )
    )
    return arms


def c_arms():
    lines = read("c/emitc.dawn")
    arms = set(
        names(
            body(lines, "fn emit_intrinsic(", "emitc.dawn"),
            r'name == "([A-Za-z_0-9]+)"',
            "emitc.dawn",
            "arms in emit_intrinsic",
        )
    )
    # the C side's copy of the std/pvec table, kept as a predicate so the
    # `else if` chain above it stays flat
    arms |= set(
        names(
            body(lines, "fn is_list_primitive(", "emitc.dawn"),
            r'n == "([A-Za-z_0-9]+)"',
            "emitc.dawn",
            "std/pvec targets",
        )
    )
    return arms


def check(backend, arms, owed):
    for n in sorted(owed - arms):
        fail(
            f"{backend} has no arm for `{n}`, which lower.dawn says every "
            f"backend writes itself. A program reaching it would compile on "
            f"the other backend and panic here."
        )
    for n in sorted(arms - owed):
        fail(
            f"{backend} has an arm for `{n}`, which is on no list in "
            f"lower.dawn. Either it is dead code, or the primitive is "
            f"implemented and undeclared -- and then nothing requires the "
            f"other backend to have it."
        )


def main():
    inline, host = declared()
    if FAILURES:
        report()
    both = inline
    check("emit.dawn (JVM)", jvm_arms(), both | host)
    check("emitc.dawn (native)", c_arms(), both)
    report()
    print(
        f"PASS  both backends implement the {len(both)} inline primitives, "
        f"and the JVM the {len(host)} host ones"
    )


def report():
    if FAILURES:
        for f in FAILURES:
            print(f"FAIL: {f}", file=sys.stderr)
        sys.exit(1)


main()
