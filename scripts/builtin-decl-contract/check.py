#!/usr/bin/env python3
"""Hold `selfhost/builtins.dawn` level with the builtin table it mirrors.

## What the mirror is for, and why it needs a gate

The builtin table is a Dawn value spread over 400 lines of
`selfhost/src/check/types.dawn`, built by helper calls (`bsig`, `eff1`, `tp1`)
around loops that mint families of names. Reading a signature off it means
running the constructors in your head, and reading the *set* of them means
running the whole file. So the answer to "what can I call, and what does it
take" lived in three places that each showed a slice: `dawn doc --builtins`
(the 28 public ones), an LSP hover (one at a time), and the source.

`selfhost/builtins.dawn` is the whole table as declarations, one line each. It
is not compiled -- a declaration with no body is a parse error, which is what
keeps it out of every build -- and it is not the truth. The truth is the
table. This file is what makes the mirror worth reading: a mirror nothing
compares is a document that goes stale the day after it is written, and a
stale mirror of an API is worse than no mirror, because a reader believes it.

## The judgements

    P1  every name the mirror declares is in the table   (no invented builtin)
    P2  every name in the table is in the mirror         (nothing missing)
    P3  the signatures are equal character for character
    P4  `pub fn` in the mirror <=> the table says the name is not internal
    P5  the `# comptime: rejected` markers are exactly the table names the
        comptime interpreter refuses

P1 and P2 are separate judgements over the same two sets, and are deliberately
not written as one equality. "The sets differ" names neither side; a mirror
carrying a name the compiler dropped and a mirror missing one the compiler
gained are different mistakes with different fixes, and a gate that cannot
tell them apart makes the reader re-derive which happened.

## The meta-judgements

A comparison of two empty sets passes. Both sides are therefore held to
something that is not the comparison:

    M1  the dump's names, plus lowering's internal intrinsic names, are
        exactly the two lists in `ir/interp.dawn` -- every intrinsic in the
        program is either interpreted at comptime or refused by name, which
        that module's own test asserts and this re-derives from its source
    M2  the mirror parses to at least one declaration

M1 does two jobs. It is the emptiness guard on the dump side: a truncated or
absent dump cannot satisfy an equality against a list of 110 names. And it is
what makes P5 trustworthy, because P5's other input is `comptime_rejects()`
read out of `ir/interp.dawn` as *source text*. That reading is a small
evaluator for the three shapes that function is written in, and an evaluator
of source text can be wrong quietly. It cannot be wrong quietly here: an
under-read drops names from one side of M1's equality and an over-read adds
them, and either way M1 names the difference.

Reading the list from source at all is a compromise, and the reason is
visible: `interp_arms` and `comptime_rejects` are private to `ir/interp.dawn`.
The alternative was to publish them, which widens the compiler's export
surface to serve a gate -- a worse trade than a parser the gate's own
meta-judgement audits.

## Usage

    check.py --dump DUMP.tsv [--root REPO_ROOT]
    check.py --self-test        # synthetic tables; every judgement must red
    check.py --mutants          # the real inputs, perturbed in memory
"""

import argparse
import pathlib
import re
import sys

MIRROR = "selfhost/builtins.dawn"
INTERP = "selfhost/src/ir/interp.dawn"

SIG_LINE = re.compile(r"^(pub )?fn [a-z_][A-Za-z0-9_]*[\[(]")
MARKER = " # comptime: rejected"


# --- the mirror ------------------------------------------------------------


def parse_mirror(text, where=MIRROR):
    """name -> (is_pub, signature, comptime_rejected), in file order.

    Everything that is not a signature line is a comment or blank. A line that
    looks like neither is an error rather than something skipped: the mirror's
    whole claim is that it is nothing but declarations, and a gate that
    silently ignores what it cannot read would let a hand edit introduce a
    shape it does not check.
    """
    out = {}
    order = []
    for lineno, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        rejected = False
        if line.endswith(MARKER.strip()):
            if not line.endswith(MARKER):
                raise SystemExit(
                    f"{where}:{lineno}: the comptime marker is one space off "
                    f"the declaration and this line spaces it differently. "
                    f"`dawn fmt` decides that: it reads this file lexically, "
                    f"and does so even though the file does not parse"
                )
            line = line[: -len(MARKER)]
            rejected = True
        if not SIG_LINE.match(line):
            raise SystemExit(
                f"{where}:{lineno}: neither a comment nor a declaration: {raw!r}"
            )
        is_pub = line.startswith("pub ")
        sig = line[4:] if is_pub else line
        name = sig[len("fn ") :].split("[")[0].split("(")[0]
        if name in out:
            raise SystemExit(f"{where}:{lineno}: `{name}` is declared twice")
        out[name] = (is_pub, sig, rejected)
        order.append(name)
    return out, order


# --- the dump --------------------------------------------------------------


def parse_dump(text, where="the dump"):
    """(builtins, lowering): name -> (is_pub, signature), and the plain names."""
    builtins = {}
    lowering = []
    for lineno, raw in enumerate(text.split("\n"), start=1):
        if not raw.strip():
            continue
        fields = raw.split("\t")
        kind = fields[0]
        if kind == "builtin":
            if len(fields) != 4:
                raise SystemExit(f"{where}:{lineno}: expected 4 fields: {raw!r}")
            _, name, vis, sig = fields
            if vis not in ("pub", "internal"):
                raise SystemExit(f"{where}:{lineno}: unknown visibility {vis!r}")
            if not sig.startswith("fn "):
                raise SystemExit(f"{where}:{lineno}: not a signature: {sig!r}")
            if name in builtins:
                raise SystemExit(f"{where}:{lineno}: `{name}` dumped twice")
            builtins[name] = (vis == "pub", sig)
        elif kind == "lowering":
            if len(fields) != 2:
                raise SystemExit(f"{where}:{lineno}: expected 2 fields: {raw!r}")
            lowering.append(fields[1])
        else:
            raise SystemExit(f"{where}:{lineno}: unknown record kind {kind!r}")
    return builtins, lowering


# --- ir/interp.dawn, read as source ---------------------------------------

STRINGS = re.compile(r'"([^"\\]*)"')


def _strip_comment(line):
    """Drop a trailing `#` comment. No `#` occurs inside the string literals
    of either function, and this asserts that rather than assuming it."""
    if "#" not in line:
        return line
    head, _, tail = line.partition("#")
    if head.count('"') % 2:
        raise SystemExit(
            f"{INTERP}: a `#` falls inside a string literal, which this "
            f"reader cannot split on: {line!r}"
        )
    del tail
    return head


def _fn_body(text, name):
    start = text.find(f"\nfn {name}() -> List[String] =")
    if start < 0:
        raise SystemExit(f"{INTERP}: no `fn {name}() -> List[String] =` to read")
    if text.find(f"\nfn {name}() -> List[String] =", start + 1) >= 0:
        raise SystemExit(f"{INTERP}: `{name}` is declared more than once")
    end = text.find("\n}\n", start)
    stop = text.find("\n]\n", start)
    if end < 0 or (0 <= stop < end):
        end = stop
    if end < 0:
        raise SystemExit(f"{INTERP}: `{name}` has no closing line")
    return text[start:end]


def read_interp_arms(text):
    """`fn interp_arms() -> List[String] = [ ... ]`: one flat list literal."""
    body = _fn_body(text, "interp_arms")
    body = body[body.index("= [") + 2 :]
    out = []
    for raw in body.split("\n"):
        line = _strip_comment(raw).strip()
        if line in ("", "["):
            continue
        line = line.lstrip("[").strip()
        if not line:
            continue
        rest = STRINGS.sub("", line).replace(",", "").strip()
        if rest:
            raise SystemExit(f"{INTERP}: interp_arms carries {rest!r}, not names")
        out += STRINGS.findall(line)
    return out


def read_comptime_rejects(text):
    """`fn comptime_rejects() -> List[String] = { ... }`, in three shapes.

    Only three, and anything else stops the run:

        var out = ["a", "b"]                       a seed list
        out = out ++ ["a", "b"]                    an append of literals
        for op in ["x", "y"] { out = out ++ ["p_" ++ op] }   a family

    The families are the point: `io_*` is 25 names written as one loop over
    25 suffixes, and a reader that took the loop's literals for names would
    produce `print` where the table says `io_print`. A `for` may spread its
    suffix list and its body over as many lines as it likes, so the reader is
    a three-state machine rather than a line-at-a-time match.
    """
    body = _fn_body(text, "comptime_rejects")
    body = body[body.index("= {") + 3 :]
    out = []
    state = "idle"
    suffixes = []
    for raw in body.split("\n"):
        line = _strip_comment(raw).strip()
        if not line or line == "out":
            continue
        if state == "header":
            suffixes += STRINGS.findall(line)
            if "] {" not in line:
                continue
            line = line[line.index("] {") + 3 :].strip()
            state = "body"
            if not line:
                continue
        if state == "close":
            if line != "}":
                raise SystemExit(f"{INTERP}: a `for` body is followed by {line!r}")
            state = "idle"
            continue
        if state == "body":
            out += [_loop_prefix(line) + s for s in suffixes]
            suffixes = []
            state = "idle" if line.endswith("}") else "close"
            continue
        if line.startswith("for op in ["):
            head = line[len("for op in [") :]
            state = "header"
            if "] {" in head:
                suffixes = STRINGS.findall(head[: head.index("] {")])
                tail = head[head.index("] {") + 3 :].strip()
                state = "body"
                if tail:
                    out += [_loop_prefix(tail) + s for s in suffixes]
                    suffixes = []
                    state = "idle" if tail.endswith("}") else "close"
            else:
                suffixes = STRINGS.findall(head)
            continue
        if line.startswith("var out = [") or line.startswith("out = out ++ ["):
            literal = line[line.index("[") :]
            if not literal.endswith("]"):
                raise SystemExit(f"{INTERP}: unterminated list: {line!r}")
            rest = STRINGS.sub("", literal).strip("[]").replace(",", "").strip()
            if rest:
                raise SystemExit(f"{INTERP}: {line!r} is not a list of names")
            out += STRINGS.findall(literal)
            continue
        raise SystemExit(
            f"{INTERP}: comptime_rejects is written in a shape this reader "
            f"does not know: {line!r}"
        )
    if state != "idle":
        raise SystemExit(f"{INTERP}: a `for` in comptime_rejects never closes")
    return out


def _loop_prefix(tail):
    """`out = out ++ ["io_" ++ op] }` -> `io_`."""
    m = re.match(r'^out = out \+\+ \["([^"]*)" \+\+ op\]\s*\}?$', tail.strip())
    if not m:
        raise SystemExit(f"{INTERP}: unreadable loop body: {tail!r}")
    return m.group(1)


# --- the judgements --------------------------------------------------------


def judge(mirror_text, dump_text, interp_text):
    """Every failure, as a list of lines. Empty means green."""
    bad = []
    mirror, _ = parse_mirror(mirror_text)
    builtins, lowering = parse_dump(dump_text)
    arms = read_interp_arms(interp_text)
    rejects = read_comptime_rejects(interp_text)

    # M1 -- the dump is whole, and the source reading of interp.dawn is right
    partition = sorted(set(arms) | set(rejects))
    if len(set(arms) & set(rejects)) != 0:
        bad.append(
            "M1 ir/interp.dawn lists as both interpreted and refused: "
            + ", ".join(sorted(set(arms) & set(rejects)))
        )
    universe = sorted(set(builtins) | set(lowering))
    if universe != partition:
        missing = sorted(set(partition) - set(universe))
        extra = sorted(set(universe) - set(partition))
        if missing:
            bad.append(
                "M1 named by ir/interp.dawn but absent from the dumped "
                "intrinsic universe: " + ", ".join(missing)
            )
        if extra:
            bad.append(
                "M1 dumped as an intrinsic but named by neither list in "
                "ir/interp.dawn: " + ", ".join(extra)
            )

    # M2 -- the mirror was really read
    if not mirror:
        bad.append(f"M2 {MIRROR} declares nothing at all")

    # P1 / P2 -- the two directions, separately
    for name in sorted(set(mirror) - set(builtins)):
        bad.append(f"P1 {MIRROR} declares `{name}`, which is no builtin")
    for name in sorted(set(builtins) - set(mirror)):
        bad.append(f"P2 the builtin `{name}` is missing from {MIRROR}")

    for name in sorted(set(mirror) & set(builtins)):
        is_pub, sig, rejected = mirror[name]
        want_pub, want_sig = builtins[name]
        # P3
        if sig != want_sig:
            bad.append(f"P3 `{name}` reads\n      {sig}\n    and the table says\n      {want_sig}")
        # P4
        if is_pub != want_pub:
            said = "pub fn" if is_pub else "fn"
            means = "public" if want_pub else "std-only (internal)"
            bad.append(f"P4 `{name}` is declared `{said}`, and the table says it is {means}")
        # P5
        want_rejected = name in rejects
        if rejected != want_rejected:
            if want_rejected:
                bad.append(f"P5 `{name}` is refused at comptime and carries no marker")
            else:
                bad.append(f"P5 `{name}` is marked comptime-rejected and is not")
    return bad


# --- self-test: synthetic inputs, every judgement red ----------------------

GOOD_INTERP = '''
fn interp_arms() -> List[String] = [
  # a comment
  "keep", "fold_me"
]

fn comptime_rejects() -> List[String] = {
  # a comment
  var out = ["refuse"]
  for op in ["a", "b"] { out = out ++ ["fam_" ++ op] }
  for op in ["c",
    "d"] {
    out = out ++ ["wide_" ++ op]
  }
  out = out ++ ["late"]
  out
}
'''

GOOD_DUMP = "\n".join(
    [
        "builtin\tkeep\tpub\tfn keep(x: Int) -> Int",
        "builtin\trefuse\tpub\tfn refuse() -> Unit !io",
        "builtin\tfam_a\tinternal\tfn fam_a() -> Unit",
        "builtin\tfam_b\tinternal\tfn fam_b() -> Unit",
        "builtin\twide_c\tinternal\tfn wide_c() -> Unit",
        "builtin\twide_d\tinternal\tfn wide_d() -> Unit",
        "builtin\tlate\tinternal\tfn late() -> Unit",
        "lowering\tfold_me",
    ]
)

GOOD_MIRROR = """# a header
pub fn keep(x: Int) -> Int
pub fn refuse() -> Unit !io # comptime: rejected
fn fam_a() -> Unit # comptime: rejected
fn fam_b() -> Unit # comptime: rejected
fn wide_c() -> Unit # comptime: rejected
fn wide_d() -> Unit # comptime: rejected
fn late() -> Unit # comptime: rejected
"""

SELF_TESTS = [
    (
        "P1",
        GOOD_MIRROR + "fn invented() -> Unit\n",
        GOOD_DUMP,
        GOOD_INTERP,
    ),
    (
        "P2",
        GOOD_MIRROR.replace("fn late() -> Unit # comptime: rejected\n", ""),
        GOOD_DUMP,
        GOOD_INTERP,
    ),
    (
        "P3",
        GOOD_MIRROR.replace("fn keep(x: Int) -> Int", "fn keep(y: Int) -> Int"),
        GOOD_DUMP,
        GOOD_INTERP,
    ),
    (
        "P4",
        GOOD_MIRROR.replace("fn fam_a() -> Unit", "pub fn fam_a() -> Unit"),
        GOOD_DUMP,
        GOOD_INTERP,
    ),
    (
        "P5",
        GOOD_MIRROR.replace("pub fn refuse() -> Unit !io # comptime: rejected", "pub fn refuse() -> Unit !io"),
        GOOD_DUMP,
        GOOD_INTERP,
    ),
    (
        "M1",
        GOOD_MIRROR.replace("fn late() -> Unit # comptime: rejected\n", ""),
        GOOD_DUMP.replace("builtin\tlate\tinternal\tfn late() -> Unit\n", "").replace(
            "\nbuiltin\tlate\tinternal\tfn late() -> Unit", ""
        ),
        GOOD_INTERP,
    ),
    ("M2", "# nothing but a header\n", GOOD_DUMP, GOOD_INTERP),
]


def self_test():
    bad = judge(GOOD_MIRROR, GOOD_DUMP, GOOD_INTERP)
    if bad:
        print("SELF-TEST FAIL: the clean synthetic table is not green:")
        for line in bad:
            print("  " + line)
        return 1
    print("OK   the clean synthetic table is green (the positive control)")
    rc = 0
    for label, mirror, dump, interp in SELF_TESTS:
        found = judge(mirror, dump, interp)
        owned = [line for line in found if line.startswith(label)]
        if not owned:
            print(f"SELF-TEST FAIL: the {label} perturbation stayed green")
            for line in found:
                print("  (other) " + line)
            rc = 1
        else:
            print(f"PASS {label} perturbation -> {owned[0].splitlines()[0]}")
    return rc


# --- mutants: the real inputs, perturbed in memory -------------------------
#
# The self-test above proves each judgement can be red. It does not prove the
# judgements can be red *about this repository*: a synthetic table shares
# nothing with the real one but the shapes, and a checker pointed at the wrong
# file, or reading a real signature into the wrong field, would pass every
# synthetic case. These perturb what the gate actually reads. Nothing is
# written: the working tree never holds a mutant.


def mutate_p1_add(mirror, dump, interp):
    return mirror + "\nfn totally_invented(x: Int) -> Int\n", dump, interp


def mutate_p2_drop_popcount(mirror, dump, interp):
    return _drop_line(mirror, "fn popcount(n: Int) -> Int" + MARKER), dump, interp


def mutate_p3_param_name(mirror, dump, interp):
    return _sub(mirror, "fn popcount(n: Int) -> Int", "fn popcount(x: Int) -> Int"), dump, interp


def mutate_p3_return_type(mirror, dump, interp):
    return (
        _sub(mirror, "fn parse_int(s: String) -> Option[Int]", "fn parse_int(s: String) -> Int"),
        dump,
        interp,
    )


def mutate_p4_add_pub(mirror, dump, interp):
    return _sub(mirror, "\nfn str_lower(", "\npub fn str_lower("), dump, interp


def mutate_p4_drop_pub(mirror, dump, interp):
    return _sub(mirror, "\npub fn parse_int_radix(", "\nfn parse_int_radix("), dump, interp


def mutate_p5_move_marker(mirror, dump, interp):
    """Take the marker off a name that is refused and put it on one that is
    not: one edit, both directions of P5."""
    lines = mirror.split("\n")
    off = _index_of(lines, "fn bytes_utf8(s: String) -> Bytes" + MARKER)
    on = _index_of(lines, "pub fn parse_int(s: String) -> Option[Int]")
    lines[off] = lines[off][: -len(MARKER)]
    lines[on] = lines[on] + MARKER
    return "\n".join(lines), dump, interp


MUTANTS = [
    ("p1-declare-a-name-the-compiler-has-not", mutate_p1_add, "P1"),
    ("p2-drop-popcount", mutate_p2_drop_popcount, "P2"),
    ("p3-rename-a-parameter", mutate_p3_param_name, "P3"),
    ("p3-widen-a-return-type", mutate_p3_return_type, "P3"),
    ("p4-publish-str_lower", mutate_p4_add_pub, "P4"),
    ("p4-hide-parse_int_radix", mutate_p4_drop_pub, "P4"),
    ("p5-move-a-comptime-marker", mutate_p5_move_marker, "P5"),
]


def _sub(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"mutation anchor drifted: {old!r} occurs {text.count(old)} times")
    return text.replace(old, new)


def _drop_line(text, exact):
    lines = text.split("\n")
    at = _index_of(lines, exact)
    return "\n".join(lines[:at] + lines[at + 1 :])


def _index_of(lines, exact):
    hits = [i for i, line in enumerate(lines) if line == exact]
    if len(hits) != 1:
        raise SystemExit(f"mutation anchor drifted: {exact!r} occurs {len(hits)} times")
    return hits[0]


def run_mutants(mirror, dump, interp):
    rc = 0
    clean = judge(mirror, dump, interp)
    if clean:
        print("MUTANT FAIL: the real inputs are not green to begin with:")
        for line in clean:
            print("  " + line)
        return 1
    print("OK   the real mirror is green (the positive control)")
    for name, fn, label in MUTANTS:
        found = judge(*fn(mirror, dump, interp))
        owned = [line for line in found if line.startswith(label)]
        if not owned:
            print(f"MUTANT FAIL: {name} stayed green")
            rc = 1
        else:
            print(f"PASS {name} -> {owned[0].splitlines()[0]}")
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump", help="the dump project's output")
    ap.add_argument("--root", default=None)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--mutants", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    root = pathlib.Path(args.root) if args.root else pathlib.Path(__file__).resolve().parents[2]
    if not args.dump:
        ap.error("--dump is required (scripts/builtin-decl-contract/run.sh produces it)")
    mirror = (root / MIRROR).read_text(encoding="utf-8")
    dump = pathlib.Path(args.dump).read_text(encoding="utf-8")
    interp = (root / INTERP).read_text(encoding="utf-8")

    if args.mutants:
        return run_mutants(mirror, dump, interp)

    bad = judge(mirror, dump, interp)
    if bad:
        print(f"FAIL: {MIRROR} and the builtin table disagree")
        for line in bad:
            print("  " + line)
        print()
        print(f"  the table in selfhost/src/check/types.dawn is the truth; edit {MIRROR}")
        return 1
    mirror_decls, _ = parse_mirror(mirror)
    builtins, lowering = parse_dump(dump)
    pub = sum(1 for is_pub, _, _ in mirror_decls.values() if is_pub)
    rejected = sum(1 for _, _, r in mirror_decls.values() if r)
    print(
        f"OK: {MIRROR} mirrors all {len(builtins)} builtins "
        f"({pub} public, {len(builtins) - pub} std-only, {rejected} refused at "
        f"comptime), and the intrinsic universe of {len(builtins) + len(lowering)} "
        f"names is partitioned by ir/interp.dawn"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
