#!/usr/bin/env python3
"""Both backends implement the same set of inline primitives.

    ./scripts/intrinsic-parity.py

`lower.inline_intrinsics()` names the primitives no runtime module owns and
lowering does not remove -- the ones each backend writes instructions for
itself -- and `lower.jvm_only_intrinsics()` names the ones only the JVM owes
(the two host-value primitives, which need a value `use java` is the only
producer of).
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

The list primitives are the one group neither emitter spells for itself:
which `std/pvec` function each one calls is `reach.list_primitive_table()`,
and both emitters dispatch on that table (#181). So their arms are read from
there, and the JVM's descriptor table is held to the same keys both ways.
The second half of this file holds the rest of that bargain: every
`std/pvec` call either emitter writes goes through its one checked helper
(`emit.call_pvec`, `emitc.pvec_call`), which refuses a name outside
`reach.list_root_names()`, the functions pruning keeps. A call written
around the helper is a function pruning may have dropped, and it would only
show up as a NoSuchMethodError in a user's program, so it is refused here by
spelling: no `"std/pvec"` literal and no `LIST_MOD` outside those helpers.
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
        if re.match(r"^(?:pub(?:\(pkg\))? )?(fn|type|test|const) ", line) or line.startswith("# ----"):
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


def list_primitives():
    """`reach.list_primitive_table()`: primitive -> std/pvec function."""
    found = names(
        body(read("ir/reach.dawn"), "pub fn list_primitive_table()", "reach.dawn"),
        r'\("([A-Za-z_0-9]+)", "([A-Za-z_0-9]+)"\)',
        "reach.dawn",
        "rows in list_primitive_table()",
    )
    return {prim for prim, _ in found}


def jvm_arms():
    lines = read("jvm/emit.dawn")
    # `gen_list_intrinsic` dispatches twice: on reach's table for the
    # primitives that are a plain std/pvec call, typed by
    # `list_primitive_desc`, then a chain for the ones that need a
    # List<->Array conversion around them.
    lst = body(lines, "fn gen_list_intrinsic(", "emit.dawn")
    if "reach.list_primitive_fn(name)" not in "\n".join(lst):
        fail(
            "emit.dawn: gen_list_intrinsic no longer dispatches on "
            "reach.list_primitive_fn(name); the list primitives' arms are read "
            "from reach's table on that premise."
        )
    table = list_primitives()
    descs = set(
        names(
            body(lines, "fn list_primitive_desc(", "emit.dawn"),
            r'(?m)^\s+"([A-Za-z_0-9]+)" ->',
            "emit.dawn",
            "list primitive descriptors",
        )
    )
    for n in sorted(table - descs):
        fail(f"emit.dawn: list primitive `{n}` is in reach's table but has no JVM descriptor.")
    for n in sorted(descs - table):
        fail(f"emit.dawn: a JVM descriptor for `{n}`, which reach's table does not list.")
    arms = set(table)
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
    # the list primitives: emit_intrinsic's `is_list_primitive` arm reads
    # reach's table, so every row of it is an arm here
    if "reach.list_primitive_fn(n)" not in "\n".join(body(lines, "fn is_list_primitive(", "emitc.dawn")):
        fail(
            "emitc.dawn: is_list_primitive no longer reads reach.list_primitive_fn; "
            "the list primitives' arms are read from reach's table on that premise."
        )
    arms |= list_primitives()
    return arms


# Where a `std/pvec` call may be spelled: the helper that checks the name
# against reach.list_root_names(), and nothing else. rc.dawn builds one Core
# call to from_array (a list literal it rewrites), by constant.
PVEC_FILES = ["jvm/emit.dawn", "jvm/help.dawn", "jvm/codegen.dawn", "c/emitc.dawn", "c/rc.dawn"]
PVEC_HELPERS = {"jvm/emit.dawn": "fn call_pvec(", "c/emitc.dawn": "fn pvec_call("}


def code_lines(lines):
    """(line number, text, enclosing top-level header) of non-comment code.

    Test blocks are skipped: a fixture may name std/pvec by string.
    """
    header = ""
    for i, line in enumerate(lines, 1):
        # a declaration starts in column 0; `}` and `)` there close one
        if line and not line[0].isspace() and line[0] not in "})#":
            header = line
        if header.startswith("test "):
            continue
        if line.lstrip().startswith("#"):
            continue
        yield i, line, header


def pvec_spellings():
    seen_helper = set()
    for name in PVEC_FILES:
        for no, line, header in code_lines(read(name)):
            where = f"{name}:{no}"
            if header.startswith("use "):
                continue
            if '"std/pvec"' in line or "PVEC_MOD" in line:
                fail(
                    f"{where}: names std/pvec by spelling. A std/pvec call goes "
                    f"through the checked helper with a reach.LIST_* name, so "
                    f"pruning is known to keep what it calls."
                )
            if "LIST_MOD" in line:
                helper = PVEC_HELPERS.get(name)
                if helper and header.startswith(helper):
                    seen_helper.add(name)
                elif name == "c/rc.dawn" and re.search(
                    r"CDirect\(LIST_MOD, LIST_(FROM_ARRAY|TO_ARRAY|CONCAT)\)", line
                ):
                    pass
                else:
                    fail(
                        f"{where}: LIST_MOD outside {helper or 'a checked helper'}. "
                        f"A std/pvec call written around the helper skips its "
                        f"check against reach.list_root_names()."
                    )
    for name, helper in PVEC_HELPERS.items():
        if name not in seen_helper:
            fail(
                f"{name}: `{helper}` no longer spells LIST_MOD. This gate "
                f"reads that helper as the one place a std/pvec call is "
                f"written; the rename has to come here too."
            )


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
    pvec_spellings()
    report()
    print(
        f"PASS  both backends implement the {len(both)} inline primitives, "
        f"and the JVM the {len(host)} it owes alone; every std/pvec call "
        f"goes through the helper that checks it against reach's list roots"
    )


def report():
    if FAILURES:
        for f in FAILURES:
            print(f"FAIL: {f}", file=sys.stderr)
        sys.exit(1)


main()
