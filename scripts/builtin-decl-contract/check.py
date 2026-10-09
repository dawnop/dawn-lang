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
    P6  every signature, parsed back as the declaration it claims to be and
        rendered again, comes out the same string
    P7  the `# owned:` markers (and, for the lowering-internal names the
        mirror does not declare, its `# owned: <name> ...` comment records)
        are exactly the table's owned argument positions
    P8  the `DAWN_CONSUMES(...)` marks in runtime/c/dawn_rt.h are exactly the
        table's owned positions for every intrinsic whose primitive is
        declared there, and each names a parameter the prototype has
    P9  the `"comptime"` field `dawn doc --builtins` publishes is on every
        builtin's entry and on nothing else, and says "refused" exactly where
        the mirror carries `# comptime: rejected`

P1 and P2 are separate judgements over the same two sets, and are deliberately
not written as one equality. "The sets differ" names neither side; a mirror
carrying a name the compiler dropped and a mirror missing one the compiler
gained are different mistakes with different fixes, and a gate that cannot
tell them apart makes the reader re-derive which happened.

## Why P6 is a separate question from P3

P1 to P5 hold the mirror against the table. All five stay green if the
rendering itself loses something, because both sides are the same rendering:
the mirror is copied from what `sig_render_fqn` printed, so it agrees with the
table about a signature the compiler cannot read back. P6 is the only
judgement that asks whether the printed line means what the entry means, and
the reader is the compiler's own parser -- `parse_module` plus
`pass_fn_signatures`, the two the dump project runs, so the answer is the one
a source file would get.

It found three when it was written. `sort_by`, `map_fold` and `bracket` each
raised an effect variable without recording that they bound it, so they
rendered `fn sort_by[T](xs: List[T], cmp: fn(T, T) -> Int !e) -> List[T] !e`
-- a signature mentioning `!e` with nowhere it was introduced, and one that
comes back as `[T, !e]` when the parser mints the variable where it is first
met. The table was fixed rather than the renderer.

## The meta-judgements

A comparison of two empty sets passes. Both sides are therefore held to
something that is not the comparison:

    M1  the dump's names, plus lowering's internal intrinsic names, are
        exactly three pairwise-disjoint lists: `interp_arms` and
        `comptime_rejects` in `ir/interp.dawn`, and `lowered_intrinsics` in
        `ir/lower.dawn` -- every intrinsic in the program is interpreted at
        comptime, removed by lowering before the interpreter could see it, or
        refused by name, which `ir/interp.dawn`'s own test asserts and this
        re-derives from source. The names a `const` still cannot use after
        lowering (`comptime_refused_after_lowering`) are lowered names.
    M2  the mirror parses to at least one declaration
    M3  the owned-argument table is not empty and names only intrinsics
        (the table's own names, or lowering's internal ones)

M1 does two jobs. It is the emptiness guard on the dump side: a truncated or
absent dump cannot satisfy an equality against a list of 110 names. And it is
what makes P5 trustworthy, because P5's other inputs are `comptime_rejects()`
and `comptime_refused_after_lowering()` read out of `ir/interp.dawn` as
*source text*. That reading is a small evaluator for the three shapes those
functions are written in, and an evaluator of source text can be wrong
quietly. It cannot be wrong quietly here: an under-read drops names from one
side of M1's equality and an over-read adds them, and either way M1 names the
difference.

Reading the lists from source at all is a compromise, and the reason is
visible: `interp_arms` and `comptime_rejects` are private to `ir/interp.dawn`.
The alternative was to publish them, which widens the compiler's export
surface to serve a gate -- a worse trade than a parser the gate's own
meta-judgement audits. `lowered_intrinsics` is public, but the dump is a
table of builtins and this is lowering's classification; it is read from
`ir/lower.dawn` by the same evaluator rather than added to the dump.

## The third group, and why P5 is two lists

Until 2026-09-30 the partition was two lists, and a name lowering removes had
to be put in one of them: `parse_int` got an interpreter arm nothing could
reach, and `parse_int_radix` got a refusal this mirror then published as a
marker, while `const Z = parse_int_radix("ff", 16)` folds to `Some(255)`
through std/fmt's Core (#185). The lowered names are a group of their own now.
Map and Set are lowered too, and a `const` still cannot use them -- lowering
routes them to std/hamt, whose Core the interpreter refuses -- so P5's
"refused at comptime" is `comptime_rejects` plus that second list.

## The published comptime flag, and why P9 reads the export itself (#213)

Spec §7.2 does not list the builtins a `const` cannot call; it sends the
reader to the `comptime` field of `dawn doc --builtins`. That field is
computed from the same two interpreter lists P5 holds the markers to
(`interp.comptime_refuses`), so P5 and P9 together make the markers, the
interpreter and the published flag one answer. P9 reads what the command
prints rather than what `doc.dawn` would compute: a field computed right and
written against the wrong entry, or dropped from one of the two places a
builtin can appear (a hand-written group or `internal`), is a failure only
the output shows. The field is on builtins alone -- a std function's
foldability is a property of its body, not of this table -- so an entry that
is no builtin and carries it is red too, including a std module's function
that shares a builtin's name (`std/bytes.len` and `len`).

## The owned-argument positions, and why they are three places (#212)

`types.intr_owned_args` answers which argument positions of an intrinsic
the native runtime consumes rather than borrows; the rc pass asks it at every
intrinsic node, and a wrong answer is a use-after-free or a leak that only a
sanitizer run over the right corpus program would see. It stays a name-keyed
constant rather than an `Intr` field: three of its four names are
lowering-internal and have no `Intr`. So it is held to the two other places
that state ownership, each at a declaration: the mirror line (P7) and the C
prototype of the primitive (P8). P8 is the one that sees a new consuming
primitive whose intrinsic nobody registered -- the mark goes on the
prototype, where the author writing it is looking. `list_push` has no C
primitive (it lowers to `std/pvec.push`, a Dawn function), so P8 has nothing
to ask about it and P7 is its check.

## Usage

    check.py --dump DUMP.tsv --export BUILTINS.json [--root REPO_ROOT]
    check.py --self-test        # synthetic tables; every judgement must red
    check.py --mutants          # the real inputs, perturbed in memory
"""

import argparse
import json
import pathlib
import re
import sys

MIRROR = "selfhost/builtins.dawn"
HEADER = "runtime/c/dawn_rt.h"
INTERP = "selfhost/src/ir/interp.dawn"
LOWER = "selfhost/src/ir/lower.dawn"

# The signatures P6 does not read back, held here so that adding one is an
# edit to the checker rather than a line the dump can quietly stop producing.
# `roundtrip_skips()` in `selfhost/src/driver/builtin_mirror.dawn` names the same set and carries the
# reason; this is the assertion that it still names only that.
ROUNDTRIP_SKIPS = ["cast"]

SIG_LINE = re.compile(r"^(pub )?fn [a-z_][A-Za-z0-9_]*[\[(]")
MARKER = " # comptime: rejected"
POSITIONS = r"(\d+(?:, \d+)*)"
OWNED_MARKER = re.compile(r" # owned: " + POSITIONS + r"$")
OWNED_RECORD = re.compile(r"^# owned: ([a-z_][a-z0-9_]*) " + POSITIONS + r"$")


def _positions(text):
    return tuple(int(p) for p in re.split(r",\s*", text))


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
        if " # owned:" in line:
            m = OWNED_MARKER.search(line)
            if not m:
                raise SystemExit(
                    f"{where}:{lineno}: an owned marker is ` # owned: 0, 2` at "
                    f"the end of the declaration, before any comptime marker: {raw!r}"
                )
            line = line[: m.start()]
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


def parse_mirror_owned(text, where=MIRROR):
    """name -> (positions, declared): every owned marker, and every
    `# owned: <name> ...` comment record. `declared` says which of the two
    it came from, because a record for a name the file also declares is the
    fact in the wrong place."""
    out = {}
    for lineno, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip("\n")
        if line.startswith("# owned:"):
            m = OWNED_RECORD.match(line)
            if not m:
                raise SystemExit(
                    f"{where}:{lineno}: an owned record is `# owned: <name> 0, 2`: {raw!r}"
                )
            name, declared, positions = m.group(1), False, _positions(m.group(2))
        elif " # owned:" in line and SIG_LINE.match(line):
            sig = line[: -len(MARKER)] if line.endswith(MARKER) else line
            m = OWNED_MARKER.search(sig)
            if not m:
                raise SystemExit(f"{where}:{lineno}: unreadable owned marker: {raw!r}")
            head = sig[4:] if sig.startswith("pub ") else sig
            name = head[len("fn ") :].split("[")[0].split("(")[0]
            declared, positions = True, _positions(m.group(1))
        else:
            continue
        if name in out:
            raise SystemExit(f"{where}:{lineno}: `{name}` is marked owned twice")
        out[name] = (positions, declared)
    return out


# --- runtime/c/dawn_rt.h, read as source -------------------------------------

CONSUMES_DEFINE = "#define DAWN_CONSUMES(...)"
CONSUMES_DECL = re.compile(
    r"^[A-Za-z_][^;(]*\bdawn_([a-z0-9_]+)\(([^()]*)\) DAWN_CONSUMES\(" + POSITIONS + r"\);$"
)
PROTOTYPE = re.compile(r"^[A-Za-z_][^;(]*\bdawn_([a-z0-9_]+)\(")


def read_runtime_consumes(text, where=HEADER):
    """(marks, prototypes): `dawn_<name>` -> (positions, arity) for every
    prototype carrying `DAWN_CONSUMES(...)`, and the set of names every
    top-level prototype in the header declares.

    A mark anywhere other than at the end of a one-line prototype stops the
    run: a reader that skipped a mark it could not parse would leave P8 green
    about exactly the primitive it was written for. The `#define` must be
    there once, so a read of the wrong file is red rather than empty."""
    if text.count(CONSUMES_DEFINE) != 1:
        raise SystemExit(f"{where}: `{CONSUMES_DEFINE}` is not defined exactly once")
    marks = {}
    prototypes = set()
    for lineno, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip()
        p = PROTOTYPE.match(line)
        if p:
            prototypes.add(p.group(1))
        if "DAWN_CONSUMES" not in line or line.startswith(CONSUMES_DEFINE):
            continue
        if line.lstrip().startswith(("*", "/*", "//")):
            continue
        m = CONSUMES_DECL.match(line)
        if not m:
            raise SystemExit(
                f"{where}:{lineno}: DAWN_CONSUMES goes at the end of a one-line "
                f"prototype, `T dawn_name(params) DAWN_CONSUMES(0, 2);`: {raw!r}"
            )
        name, params = m.group(1), m.group(2).strip()
        arity = 0 if params in ("", "void") else len(params.split(","))
        if name in marks:
            raise SystemExit(f"{where}:{lineno}: `dawn_{name}` is marked twice")
        marks[name] = (_positions(m.group(3)), arity)
    if not marks:
        raise SystemExit(f"{where}: no prototype carries DAWN_CONSUMES")
    return marks, prototypes


# --- the dump --------------------------------------------------------------


def parse_dump(text, where="the dump"):
    """The four record kinds.

    Returns (builtins, lowering, roundtrips, skips, owned): name -> (is_pub,
    signature), the plain lowering names, name -> (rendered, re-rendered), the
    names the dump declined to read back, and name -> owned positions.
    """
    builtins = {}
    lowering = []
    roundtrips = {}
    skips = []
    owned = {}
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
        elif kind == "roundtrip":
            if len(fields) != 4:
                raise SystemExit(f"{where}:{lineno}: expected 4 fields: {raw!r}")
            _, name, rendered, reread = fields
            if name in roundtrips:
                raise SystemExit(f"{where}:{lineno}: `{name}` read back twice")
            roundtrips[name] = (rendered, reread)
        elif kind == "roundtrip-skip":
            if len(fields) != 2:
                raise SystemExit(f"{where}:{lineno}: expected 2 fields: {raw!r}")
            skips.append(fields[1])
        elif kind == "lowering":
            if len(fields) != 2:
                raise SystemExit(f"{where}:{lineno}: expected 2 fields: {raw!r}")
            lowering.append(fields[1])
        elif kind == "owned":
            if len(fields) != 3 or not re.fullmatch(r"\d+(,\d+)*", fields[2]):
                raise SystemExit(f"{where}:{lineno}: expected owned<TAB>name<TAB>0,2: {raw!r}")
            if fields[1] in owned:
                raise SystemExit(f"{where}:{lineno}: `{fields[1]}` owned twice")
            owned[fields[1]] = _positions(fields[2])
        else:
            raise SystemExit(f"{where}:{lineno}: unknown record kind {kind!r}")
    return builtins, lowering, roundtrips, skips, owned


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


def _fn_body(text, name, where=INTERP):
    heads = [f"\nfn {name}() -> List[String] =", f"\npub fn {name}() -> List[String] ="]
    found = [(text.find(h), h) for h in heads if text.find(h) >= 0]
    if not found:
        raise SystemExit(f"{where}: no `fn {name}() -> List[String] =` to read")
    if len(found) > 1 or text.find(found[0][1], found[0][0] + 1) >= 0:
        raise SystemExit(f"{where}: `{name}` is declared more than once")
    start = found[0][0]
    end = text.find("\n}\n", start)
    stop = text.find("\n]\n", start)
    if end < 0 or (0 <= stop < end):
        end = stop
    if end < 0:
        raise SystemExit(f"{where}: `{name}` has no closing line")
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
    """`fn comptime_rejects() -> List[String] = { ... }`: see read_name_list."""
    return read_name_list(text, "comptime_rejects", INTERP)


def read_refused_after_lowering(text):
    """`fn comptime_refused_after_lowering()` in `ir/interp.dawn`."""
    return read_name_list(text, "comptime_refused_after_lowering", INTERP)


def read_lowered(text):
    """`pub fn lowered_intrinsics()` in `ir/lower.dawn`."""
    return read_name_list(text, "lowered_intrinsics", LOWER)


def read_name_list(text, name, where):
    """`fn <name>() -> List[String] = { ... }`, in three shapes.

    Only three, and anything else stops the run:

        var out = ["a", "b"]                       a seed list
        var out: List[String] = []                 (the same, empty)
        out = out ++ ["a", "b"]                    an append of literals
        for op in ["x", "y"] { out = out ++ ["p_" ++ op] }   a family
        for op in ["x", "y"] { out = out ++ ["p_${op}"] }    (the same)

    The families are the point: `io_*` is 25 names written as one loop over
    25 suffixes, and a reader that took the loop's literals for names would
    produce `print` where the table says `io_print`. A `for` may spread its
    suffix list and its body over as many lines as it likes, so the reader is
    a three-state machine rather than a line-at-a-time match.
    """
    body = _fn_body(text, name, where)
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
                raise SystemExit(f"{where}: a `for` body is followed by {line!r}")
            state = "idle"
            continue
        if state == "body":
            out += [_loop_prefix(line, where) + s for s in suffixes]
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
                    out += [_loop_prefix(tail, where) + s for s in suffixes]
                    suffixes = []
                    state = "idle" if tail.endswith("}") else "close"
            else:
                suffixes = STRINGS.findall(head)
            continue
        seeds = ("var out = [", "var out: List[String] = [", "out = out ++ [")
        if line.startswith(seeds):
            literal = line[line.index("= [") + 2 :] if line.startswith("var") else line[line.index("[") :]
            if not literal.endswith("]"):
                raise SystemExit(f"{where}: unterminated list: {line!r}")
            rest = STRINGS.sub("", literal).strip("[]").replace(",", "").strip()
            if rest:
                raise SystemExit(f"{where}: {line!r} is not a list of names")
            out += STRINGS.findall(literal)
            continue
        raise SystemExit(
            f"{where}: {name} is written in a shape this reader "
            f"does not know: {line!r}"
        )
    if state != "idle":
        raise SystemExit(f"{where}: a `for` in {name} never closes")
    return out


def _loop_prefix(tail, where=INTERP):
    """`out = out ++ ["io_" ++ op] }` or `out = out ++ ["io_${op}"]` -> `io_`."""
    tail = tail.strip()
    m = re.match(r'^out = out \+\+ \["([^"$]*)" \+\+ op\]\s*\}?$', tail)
    if not m:
        m = re.match(r'^out = out \+\+ \["([^"$]*)\$\{op\}"\]\s*\}?$', tail)
    if not m:
        raise SystemExit(f"{where}: unreadable loop body: {tail!r}")
    return m.group(1)


# --- the `dawn doc --builtins` export ---------------------------------------

COMPTIME_VALUES = ("ok", "refused")


def read_export(text, where="dawn doc --builtins"):
    """(flags, stray): every entry of the export that is a place a builtin can
    appear -- a hand-written group or `internal` -- as `(name, flag or None)`,
    and every std module function (a `std/...` group) that carries a flag at
    all, as `(module, name)`.

    A shape this reader does not recognise stops the run instead of reading
    as zero entries, which would leave P9 comparing against nothing."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{where}: not JSON: {exc}")
    if not isinstance(doc, dict) or "groups" not in doc or "internal" not in doc:
        raise SystemExit(f"{where}: no `groups` and `internal` keys")
    flags = []
    stray = []
    for group in doc["groups"]:
        gname = group["name"]
        for fn in group["fns"]:
            if gname.startswith("std/"):
                if "comptime" in fn:
                    stray.append((gname, fn["name"]))
            else:
                flags.append((fn["name"], fn.get("comptime")))
    for fn in doc["internal"]:
        flags.append((fn["name"], fn.get("comptime")))
    return flags, stray


# --- the judgements --------------------------------------------------------


def judge(mirror_text, dump_text, interp_text, lower_text, header_text, export_text,
          skips_expected=None):
    """Every failure, as a list of lines. Empty means green."""
    if skips_expected is None:
        skips_expected = ROUNDTRIP_SKIPS
    bad = []
    mirror, _ = parse_mirror(mirror_text)
    mirror_owned = parse_mirror_owned(mirror_text)
    builtins, lowering, roundtrips, skips, owned = parse_dump(dump_text)
    marks, prototypes = read_runtime_consumes(header_text)
    arms = read_interp_arms(interp_text)
    rejects = read_comptime_rejects(interp_text)
    after = read_refused_after_lowering(interp_text)
    lowered = read_lowered(lower_text)

    # M1 -- the dump is whole, and the source readings of interp.dawn and
    # lower.dawn are right: three groups, pairwise disjoint, covering it
    groups = [
        ("interpreted (interp_arms)", arms),
        ("removed by lowering (lowered_intrinsics)", lowered),
        ("refused (comptime_rejects)", rejects),
    ]
    for i, (a_name, a) in enumerate(groups):
        for b_name, b in groups[i + 1 :]:
            both = sorted(set(a) & set(b))
            if both:
                bad.append(f"M1 listed as both {a_name} and {b_name}: " + ", ".join(both))
    stray = sorted(set(after) - set(lowered))
    if stray:
        bad.append(
            "M1 comptime_refused_after_lowering names what lowering does not "
            "remove: " + ", ".join(stray)
        )
    partition = sorted(set(arms) | set(rejects) | set(lowered))
    universe = sorted(set(builtins) | set(lowering))
    if universe != partition:
        missing = sorted(set(partition) - set(universe))
        extra = sorted(set(universe) - set(partition))
        if missing:
            bad.append(
                "M1 named by ir/interp.dawn or ir/lower.dawn but absent from the "
                "dumped intrinsic universe: " + ", ".join(missing)
            )
        if extra:
            bad.append(
                "M1 dumped as an intrinsic but in none of the three comptime "
                "groups: " + ", ".join(extra)
            )

    # M2 -- the mirror was really read
    if not mirror:
        bad.append(f"M2 {MIRROR} declares nothing at all")

    # M3 -- the owned table was really dumped, and names intrinsics
    if not owned:
        bad.append("M3 the dump carries no owned-argument record at all")
    for name in sorted(set(owned) - set(builtins) - set(lowering)):
        bad.append(
            f"M3 the owned-argument table (types.intr_owned_args) names "
            f"`{name}`, which is no intrinsic"
        )

    # P7 -- the mirror states the same ownership, both directions
    def said(ps):
        return ", ".join(str(p) for p in ps)

    for name in sorted(set(mirror_owned) - set(owned)):
        bad.append(
            f"P7 {MIRROR} marks `{name}` owned at {said(mirror_owned[name][0])}, "
            f"and the table (types.intr_owned_args) says it borrows every argument"
        )
    for name in sorted(set(owned) - set(mirror_owned)):
        bad.append(
            f"P7 the table (types.intr_owned_args) says `{name}` consumes "
            f"argument(s) {said(owned[name])}, and {MIRROR} does not say so"
        )
    for name in sorted(set(owned) & set(mirror_owned)):
        positions, declared = mirror_owned[name]
        if positions != owned[name]:
            bad.append(
                f"P7 `{name}` is owned at {said(positions)} in {MIRROR} and at "
                f"{said(owned[name])} in the table"
            )
        if not declared and name in mirror:
            bad.append(
                f"P7 `{name}` is declared in {MIRROR}, so its ownership is a "
                f"marker on that line, not a comment record"
            )

    # P8 -- the runtime's prototypes state the same ownership
    for name in sorted(set(marks) - set(owned)):
        bad.append(
            f"P8 {HEADER} marks `dawn_{name}` DAWN_CONSUMES({said(marks[name][0])}), "
            f"and the table (types.intr_owned_args) says `{name}` borrows every argument"
        )
    for name in sorted((set(owned) & prototypes) - set(marks)):
        bad.append(
            f"P8 the table says `{name}` consumes argument(s) {said(owned[name])}, "
            f"and `dawn_{name}` in {HEADER} carries no DAWN_CONSUMES"
        )
    for name in sorted(set(owned) & set(marks)):
        positions, arity = marks[name]
        if positions != owned[name]:
            bad.append(
                f"P8 `dawn_{name}` is DAWN_CONSUMES({said(positions)}) and the "
                f"table says {said(owned[name])}"
            )
        for p in positions:
            if p >= arity:
                bad.append(
                    f"P8 `dawn_{name}` takes {arity} parameter(s) and "
                    f"DAWN_CONSUMES names position {p}"
                )

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
        want_rejected = name in rejects or name in after
        if rejected != want_rejected:
            if want_rejected:
                bad.append(f"P5 `{name}` is refused at comptime and carries no marker")
            else:
                bad.append(f"P5 `{name}` is marked comptime-rejected and is not")

    # P9 -- the published comptime flag says what the markers say, on every
    # builtin and on nothing else
    flags, stray = read_export(export_text)
    for module, name in stray:
        bad.append(
            f"P9 `{module}.{name}` is a std function and carries a comptime flag; "
            f"the flag is a fact about builtins only"
        )
    seen = {}
    for name, flag in flags:
        if name not in builtins:
            if flag is not None:
                bad.append(f"P9 `{name}` is no builtin and the export flags it comptime {flag!r}")
            continue
        if flag is None:
            bad.append(f"P9 the builtin `{name}` is exported without a comptime flag")
            continue
        if flag not in COMPTIME_VALUES:
            bad.append(f"P9 `{name}` is exported comptime {flag!r}, which is neither \"ok\" nor \"refused\"")
            continue
        if name in seen:
            bad.append(f"P9 the builtin `{name}` is exported twice")
            continue
        seen[name] = flag
    for name in sorted(set(builtins) - {n for n, _ in flags}):
        bad.append(f"P9 the builtin `{name}` is missing from the export")
    for name in sorted(set(seen) & set(mirror)):
        marked = mirror[name][2]
        if seen[name] == "refused" and not marked:
            bad.append(
                f"P9 the export says `{name}` is refused at comptime, and {MIRROR} "
                f"carries no marker for it"
            )
        if seen[name] == "ok" and marked:
            bad.append(
                f"P9 the export says a `const` may call `{name}`, and {MIRROR} "
                f"marks it comptime-rejected"
            )

    # P6 -- a rendering is a spelling of the signature, not a picture of it
    #
    # Three things, and the first two are what keep the third from being
    # satisfied by an empty set: a dump that stopped reading signatures back
    # covers nobody, and a dump that declared them all unreadable skips
    # everybody. Coverage and the skip list are therefore checked before the
    # comparison rather than assumed by it.
    covered = set(roundtrips) | set(skips)
    for name in sorted(set(builtins) - covered):
        bad.append(f"P6 the builtin `{name}` was neither read back nor skipped")
    for name in sorted(covered - set(builtins)):
        bad.append(f"P6 `{name}` was read back and is no builtin")
    if sorted(skips) != sorted(skips_expected):
        bad.append(
            "P6 the signatures the dump declines to read back are "
            + (", ".join(f"`{n}`" for n in sorted(skips)) or "none")
            + ", and the recorded set is "
            + (", ".join(f"`{n}`" for n in sorted(skips_expected)) or "none")
        )
    for name in sorted(set(roundtrips) & set(builtins)):
        rendered, reread = roundtrips[name]
        if rendered != reread:
            bad.append(
                f"P6 `{name}` renders\n      {rendered}\n"
                f"    and reading that back gives\n      {reread}"
            )
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

fn comptime_refused_after_lowering() -> List[String] = {
  var out: List[String] = []
  for op in ["a"] { out = out ++ ["trie_" ++ op] }
  out
}
'''

GOOD_LOWER = '''
pub fn lowered_intrinsics() -> List[String] = {
  var out = ["gone"]
  for op in ["a",
    "b"] {
    out = out ++ ["trie_${op}"]
  }
  out
}
'''

GOOD_DUMP = "\n".join(
    [
        "builtin\tkeep\tpub\tfn keep(x: Int) -> Int",
        "roundtrip\tkeep\tfn keep(x: Int) -> Int\tfn keep(x: Int) -> Int",
        "builtin\trefuse\tpub\tfn refuse() -> Unit !io",
        "roundtrip\trefuse\tfn refuse() -> Unit !io\tfn refuse() -> Unit !io",
        "builtin\tfam_a\tinternal\tfn fam_a() -> Unit",
        "roundtrip\tfam_a\tfn fam_a() -> Unit\tfn fam_a() -> Unit",
        "builtin\tfam_b\tinternal\tfn fam_b() -> Unit",
        "roundtrip\tfam_b\tfn fam_b() -> Unit\tfn fam_b() -> Unit",
        "builtin\twide_c\tinternal\tfn wide_c() -> Unit",
        "roundtrip\twide_c\tfn wide_c() -> Unit\tfn wide_c() -> Unit",
        "builtin\twide_d\tinternal\tfn wide_d() -> Unit",
        "roundtrip\twide_d\tfn wide_d() -> Unit\tfn wide_d() -> Unit",
        "builtin\tlate\tinternal\tfn late() -> Unit",
        "roundtrip-skip\tlate",
        "builtin\tgone\tpub\tfn gone(s: String) -> Int",
        "roundtrip\tgone\tfn gone(s: String) -> Int\tfn gone(s: String) -> Int",
        "builtin\ttrie_a\tinternal\tfn trie_a() -> Unit",
        "roundtrip\ttrie_a\tfn trie_a() -> Unit\tfn trie_a() -> Unit",
        "builtin\ttrie_b\tinternal\tfn trie_b() -> Unit",
        "roundtrip\ttrie_b\tfn trie_b() -> Unit\tfn trie_b() -> Unit",
        "lowering\tfold_me",
        "owned\tkeep\t0",
        "owned\tfold_me\t1",
    ]
)

GOOD_HEADER = """/* a header */
#define DAWN_CONSUMES(...)
int64_t dawn_keep(int64_t x) DAWN_CONSUMES(0);
void dawn_fold_me(void *a, void *b) DAWN_CONSUMES(1);
void dawn_gone(void *s);
"""

# The synthetic table's own skip set. P6 holds the dump's skips against a
# recorded list, and the list the real dump answers to is `cast`, which this
# table has no reason to carry: the judgement takes the expected set as an
# argument so that the self-test can prove it fires without borrowing a name
# from the repository.
GOOD_SKIPS = ["late"]

GOOD_MIRROR = """# a header
#
# owned: fold_me 1
pub fn keep(x: Int) -> Int # owned: 0
pub fn refuse() -> Unit !io # comptime: rejected
fn fam_a() -> Unit # comptime: rejected
fn fam_b() -> Unit # comptime: rejected
fn wide_c() -> Unit # comptime: rejected
fn wide_d() -> Unit # comptime: rejected
fn late() -> Unit # comptime: rejected
pub fn gone(s: String) -> Int
fn trie_a() -> Unit # comptime: rejected
fn trie_b() -> Unit
"""

# The export in the shape `dawn doc --builtins` prints, cut to what P9 reads:
# the builtins across a hand-written group and `internal`, a group entry the
# prelude implements in std (`wrapped`, no flag), and a std module function
# sharing a builtin's name (`std/k.keep`, no flag).
GOOD_EXPORT_DOC = {
    "types": [],
    "groups": [
        {"name": "misc", "fns": [
            {"name": "keep", "sig": "fn keep(x: Int) -> Int", "comptime": "ok", "doc": ""},
            {"name": "refuse", "sig": "fn refuse() -> Unit !io", "comptime": "refused", "doc": ""},
            {"name": "gone", "sig": "fn gone(s: String) -> Int", "comptime": "ok", "doc": ""},
            {"name": "wrapped", "sig": "fn wrapped() -> Int", "doc": ""},
        ]},
        {"name": "std/k", "fns": [{"name": "keep", "sig": "fn keep() -> Int", "doc": ""}],
         "effects": []},
    ],
    "internal": [
        {"name": n, "sig": f"fn {n}() -> Unit", "comptime": "refused"}
        for n in ("fam_a", "fam_b", "wide_c", "wide_d", "late", "trie_a")
    ] + [{"name": "trie_b", "sig": "fn trie_b() -> Unit", "comptime": "ok"}],
}


def export_with(edit, doc=None):
    """The export as text after `edit` changed a deep copy of it in place."""
    doc = json.loads(json.dumps(GOOD_EXPORT_DOC if doc is None else doc))
    edit(doc)
    return json.dumps(doc, indent=2)


GOOD_EXPORT = export_with(lambda d: None)


def _entry(doc, group, name):
    fns = doc["internal"] if group is None else next(
        g["fns"] for g in doc["groups"] if g["name"] == group
    )
    hits = [f for f in fns if f["name"] == name]
    if len(hits) != 1:
        raise SystemExit(f"mutation anchor drifted: `{name}` in {group or 'internal'} "
                         f"occurs {len(hits)} times")
    return hits[0]


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
        "P6",
        GOOD_MIRROR,
        GOOD_DUMP.replace(
            "roundtrip\tkeep\tfn keep(x: Int) -> Int\tfn keep(x: Int) -> Int",
            "roundtrip\tkeep\tfn keep(x: Int) -> Int\tfn keep[!e](x: Int) -> Int",
        ),
        GOOD_INTERP,
    ),
    (
        "P6",
        GOOD_MIRROR,
        GOOD_DUMP.replace(
            "roundtrip\tfam_a\tfn fam_a() -> Unit\tfn fam_a() -> Unit\n", ""
        ),
        GOOD_INTERP,
    ),
    (
        "P6",
        GOOD_MIRROR,
        GOOD_DUMP.replace(
            "roundtrip\tfam_b\tfn fam_b() -> Unit\tfn fam_b() -> Unit",
            "roundtrip-skip\tfam_b",
        ),
        GOOD_INTERP,
    ),
    (
        "M1",
        GOOD_MIRROR.replace("fn late() -> Unit # comptime: rejected\n", ""),
        GOOD_DUMP.replace(
            "builtin\tlate\tinternal\tfn late() -> Unit\nroundtrip-skip\tlate\n", ""
        ).replace("\nbuiltin\tlate\tinternal\tfn late() -> Unit\nroundtrip-skip\tlate", ""),
        GOOD_INTERP,
    ),
    (
        # an arm for a name lowering removes: the dead `parse_int` arm (#185)
        "M1",
        GOOD_MIRROR,
        GOOD_DUMP,
        GOOD_INTERP.replace('"keep", "fold_me"', '"keep", "fold_me", "gone"'),
    ),
    (
        # a name refused after lowering that lowering does not remove
        "M1",
        GOOD_MIRROR,
        GOOD_DUMP,
        GOOD_INTERP.replace('["trie_" ++ op]', '["tree_" ++ op]'),
    ),
    (
        # a Map/Set-style name loses its marker: refused after lowering is
        # refused all the same
        "P5",
        GOOD_MIRROR.replace("fn trie_a() -> Unit # comptime: rejected", "fn trie_a() -> Unit"),
        GOOD_DUMP,
        GOOD_INTERP,
    ),
    (
        # a lowered name that folds is marked anyway: the #185 marker on
        # `parse_int_radix`
        "P5",
        GOOD_MIRROR.replace("pub fn gone(s: String) -> Int", "pub fn gone(s: String) -> Int # comptime: rejected"),
        GOOD_DUMP,
        GOOD_INTERP,
    ),
    ("M2", "# nothing but a header\n", GOOD_DUMP, GOOD_INTERP),
    # the owned positions, against the mirror (P7) ...
    ("P7", GOOD_MIRROR.replace(" # owned: 0\n", "\n"), GOOD_DUMP, GOOD_INTERP),
    ("P7", GOOD_MIRROR.replace("# owned: fold_me 1\n", ""), GOOD_DUMP, GOOD_INTERP),
    ("P7", GOOD_MIRROR.replace("# owned: fold_me 1", "# owned: fold_me 0"), GOOD_DUMP, GOOD_INTERP),
    # a declared name's ownership written as a comment record, not a marker
    ("P7", GOOD_MIRROR.replace(" # owned: 0\n", "\n") + "# owned: keep 0\n", GOOD_DUMP, GOOD_INTERP),
    # ... against the runtime's prototypes (P8) ...
    (
        "P8",
        GOOD_MIRROR,
        GOOD_DUMP,
        GOOD_INTERP,
        GOOD_HEADER.replace("void dawn_gone(void *s);", "void dawn_gone(void *s) DAWN_CONSUMES(0);"),
    ),
    ("P8", GOOD_MIRROR, GOOD_DUMP, GOOD_INTERP, GOOD_HEADER.replace("(int64_t x) DAWN_CONSUMES(0);", "(int64_t x);")),
    (
        "P8",
        GOOD_MIRROR.replace("# owned: fold_me 1", "# owned: fold_me 2"),
        GOOD_DUMP.replace("owned\tfold_me\t1", "owned\tfold_me\t2"),
        GOOD_INTERP,
        GOOD_HEADER.replace("DAWN_CONSUMES(1)", "DAWN_CONSUMES(2)"),
    ),
    # ... the published comptime flag (P9): flipped either way, missing on a
    # builtin, on a std function or a prelude-in-std name, absent, or unreadable
    ("P9", GOOD_MIRROR, GOOD_DUMP, GOOD_INTERP, GOOD_HEADER,
     export_with(lambda d: _entry(d, "misc", "refuse").update({"comptime": "ok"}))),
    ("P9", GOOD_MIRROR, GOOD_DUMP, GOOD_INTERP, GOOD_HEADER,
     export_with(lambda d: _entry(d, None, "trie_b").update({"comptime": "refused"}))),
    ("P9", GOOD_MIRROR, GOOD_DUMP, GOOD_INTERP, GOOD_HEADER,
     export_with(lambda d: _entry(d, "misc", "keep").pop("comptime"))),
    ("P9", GOOD_MIRROR, GOOD_DUMP, GOOD_INTERP, GOOD_HEADER,
     export_with(lambda d: _entry(d, "std/k", "keep").update({"comptime": "ok"}))),
    ("P9", GOOD_MIRROR, GOOD_DUMP, GOOD_INTERP, GOOD_HEADER,
     export_with(lambda d: _entry(d, "misc", "wrapped").update({"comptime": "ok"}))),
    ("P9", GOOD_MIRROR, GOOD_DUMP, GOOD_INTERP, GOOD_HEADER,
     export_with(lambda d: d["internal"].remove(_entry(d, None, "late")))),
    ("P9", GOOD_MIRROR, GOOD_DUMP, GOOD_INTERP, GOOD_HEADER,
     export_with(lambda d: _entry(d, None, "late").update({"comptime": "maybe"}))),
    # ... and the table names something that is no intrinsic (M3)
    (
        "M3",
        GOOD_MIRROR + "# owned: nobody 0\n",
        GOOD_DUMP + "\nowned\tnobody\t0",
        GOOD_INTERP,
    ),
    (
        "M3",
        GOOD_MIRROR.replace(" # owned: 0\n", "\n").replace("# owned: fold_me 1\n", ""),
        GOOD_DUMP.replace("\nowned\tkeep\t0\nowned\tfold_me\t1", ""),
        GOOD_INTERP,
        GOOD_HEADER.replace(" DAWN_CONSUMES(0);", ";"),
    ),
]


def self_test():
    bad = judge(GOOD_MIRROR, GOOD_DUMP, GOOD_INTERP, GOOD_LOWER, GOOD_HEADER, GOOD_EXPORT, GOOD_SKIPS)
    if bad:
        print("SELF-TEST FAIL: the clean synthetic table is not green:")
        for line in bad:
            print("  " + line)
        return 1
    print("OK   the clean synthetic table is green (the positive control)")
    rc = 0
    for case in SELF_TESTS:
        label, mirror, dump, interp = case[:4]
        header = case[4] if len(case) > 4 else GOOD_HEADER
        export = case[5] if len(case) > 5 else GOOD_EXPORT
        found = judge(mirror, dump, interp, GOOD_LOWER, header, export, GOOD_SKIPS)
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


def mutate_p1_add(mirror, dump, interp, lower, header, export):
    return mirror + "\nfn totally_invented(x: Int) -> Int\n", dump, interp, lower, header, export


def mutate_p2_drop_popcount(mirror, dump, interp, lower, header, export):
    return _drop_line(mirror, "fn popcount(n: Int) -> Int" + MARKER), dump, interp, lower, header, export


def mutate_p3_param_name(mirror, dump, interp, lower, header, export):
    return _sub(mirror, "fn popcount(n: Int) -> Int", "fn popcount(x: Int) -> Int"), dump, interp, lower, header, export


def mutate_p3_return_type(mirror, dump, interp, lower, header, export):
    return (
        _sub(mirror, "fn parse_float(s: String) -> Option[Float]", "fn parse_float(s: String) -> Float"),
        dump,
        interp,
        lower,
        header,
        export,
    )


def mutate_p4_add_pub(mirror, dump, interp, lower, header, export):
    return _sub(mirror, "\nfn str_lower(", "\npub fn str_lower("), dump, interp, lower, header, export


def mutate_p4_drop_pub(mirror, dump, interp, lower, header, export):
    return _sub(mirror, "\npub fn parse_float(", "\nfn parse_float("), dump, interp, lower, header, export


def mutate_p5_move_marker(mirror, dump, interp, lower, header, export):
    """Take the marker off a name that is refused and put it on one that is
    not: one edit, both directions of P5."""
    lines = mirror.split("\n")
    off = _index_of(lines, "fn bytes_utf8(s: String) -> Bytes" + MARKER)
    on = _index_of(lines, "pub fn parse_float(s: String) -> Option[Float]")
    lines[off] = lines[off][: -len(MARKER)]
    lines[on] = lines[on] + MARKER
    return "\n".join(lines), dump, interp, lower, header, export


def mutate_m1_arm_for_parse_float(mirror, dump, interp, lower, header, export):
    """Give a lowered parser an interpreter arm: the dead `parse_int` arm #185
    removed, on the one numeric parser still a builtin since K19 made
    `parse_int` a std function. Lowering rewrites every call to `parse_float`,
    so the name is in the lowered group and an arm for it is in two groups at
    once."""
    return mirror, dump, _sub(interp, '"str_lower", "str_upper", ', '"str_lower", "str_upper", "parse_float", '), lower, header, export


def mutate_p5_mark_parse_float(mirror, dump, interp, lower, header, export):
    """The marker #185 took off `parse_int_radix`, put on the lowered parser
    left in the table since K19: `parse_float` folds through std/fmt's Core,
    so a mirror saying a `const` cannot use it is wrong."""
    return (
        _sub(
            mirror,
            "pub fn parse_float(s: String) -> Option[Float]\n",
            "pub fn parse_float(s: String) -> Option[Float]" + MARKER + "\n",
        ),
        dump,
        interp,
        lower,
        header,
        export,
    )


SORT_BY_BOUND = "fn sort_by[T, !e](xs: List[T], cmp: fn(T, T) -> Int !e) -> List[T] !e"
SORT_BY_UNBOUND = "fn sort_by[T](xs: List[T], cmp: fn(T, T) -> Int !e) -> List[T] !e"


def mutate_p6_unbind_sort_by(mirror, dump, interp, lower, header, export):
    """The table before this judgement existed: `sort_by` raises `!e` and does
    not record that it bound it (`eff1` rather than `effp1` in
    `check/types.dawn`), so the binder is missing from what it renders.

    The mirror is moved with it, which is the point. An author who reverts the
    table and dutifully re-records the mirror leaves P1 to P5 green -- the two
    sides agree, character for character, about a signature the compiler
    cannot read back -- and P6 is the only one that says so.
    """
    mirror = _sub(mirror, "pub " + SORT_BY_BOUND, "pub " + SORT_BY_UNBOUND)
    lines = dump.split("\n")
    at = _index_of(lines, "builtin\tsort_by\tpub\t" + SORT_BY_BOUND)
    lines[at] = "builtin\tsort_by\tpub\t" + SORT_BY_UNBOUND
    rt = _index_of(lines, "roundtrip\tsort_by\t" + SORT_BY_BOUND + "\t" + SORT_BY_BOUND)
    lines[rt] = "roundtrip\tsort_by\t" + SORT_BY_UNBOUND + "\t" + SORT_BY_BOUND
    return mirror, "\n".join(lines), interp, lower, header, export


def mutate_p6_skip_popcount(mirror, dump, interp, lower, header, export):
    """Declare a signature unreadable that reads back fine. This is how P6
    would erode: not by going red, but by the dump quietly excusing whatever
    stopped agreeing with itself. The skip list is held to what is recorded,
    so growing it is red until somebody writes down why."""
    lines = dump.split("\n")
    at = _index_of(
        lines, "roundtrip\tpopcount\tfn popcount(n: Int) -> Int\tfn popcount(n: Int) -> Int"
    )
    lines[at] = "roundtrip-skip\tpopcount"
    return mirror, "\n".join(lines), interp, lower, header, export


def mutate_p7_drop_list_push(mirror, dump, interp, lower, header, export):
    """The issue's negative control, in memory: `list_push` loses its `[0]` in
    the table, and nothing else moves. The mirror still says it consumes its
    list, and P7 is what says the two parted -- `list_push` has no C
    primitive, so P8 has nothing to say about it."""
    return mirror, _drop_line(dump, "owned\tlist_push\t0"), interp, lower, header, export


def mutate_p7_drop_array_with_marker(mirror, dump, interp, lower, header, export):
    return (
        _sub(mirror, "-> Array[T] # owned: 0, 2 # comptime: rejected", "-> Array[T] # comptime: rejected"),
        dump,
        interp,
        lower,
        header,
        export,
    )


def mutate_p8_consume_where_the_table_borrows(mirror, dump, interp, lower, header, export):
    """A primitive declared as consuming whose intrinsic nobody registered:
    the failure P8 exists for. `array_push` borrows; say otherwise in C."""
    return (
        mirror,
        dump,
        interp,
        lower,
        _sub(
            header,
            "dawn_array *dawn_array_push(dawn_array *a, void *x);",
            "dawn_array *dawn_array_push(dawn_array *a, void *x) DAWN_CONSUMES(0);",
        ),
        export,
    )


def mutate_p8_drop_cell_set_mark(mirror, dump, interp, lower, header, export):
    return (
        mirror,
        dump,
        interp,
        lower,
        _sub(header, "void dawn_cell_set(void *c, void *x) DAWN_CONSUMES(1);", "void dawn_cell_set(void *c, void *x);"),
        export,
    )


def mutate_m3_owned_names_no_intrinsic(mirror, dump, interp, lower, header, export):
    """A table entry spelling no intrinsic, and the mirror dutifully agreeing:
    P7 is green about it, and M3 is what reads the name."""
    return (
        mirror + "\n# owned: no_such_intrinsic 0\n",
        dump + "\nowned\tno_such_intrinsic\t0",
        interp,
        lower,
        header,
        export,
    )


def _flip_export(export, group, name, flag):
    doc = json.loads(export)
    entry = _entry(doc, group, name)
    if flag is None:
        entry.pop("comptime")
    else:
        entry["comptime"] = flag
    return json.dumps(doc, indent=2)


def mutate_p9_flip_bytes_utf8(mirror, dump, interp, lower, header, export):
    """The issue's negative control, in memory: the export says a `const` may
    call `bytes_utf8`, and nothing else moves. P5 is green -- the marker and
    the interpreter still agree -- so P9 is the only judgement that reads it."""
    return mirror, dump, interp, lower, header, _flip_export(export, None, "bytes_utf8", "ok")


def mutate_p9_drop_get_s_flag(mirror, dump, interp, lower, header, export):
    return mirror, dump, interp, lower, header, _flip_export(export, "list", "get", None)


def mutate_p9_flag_std_bytes_len(mirror, dump, interp, lower, header, export):
    """`std/bytes.len` is a Dawn function whose name a builtin carried until the
    `Len` trait took it. A flag keyed on the name alone would put it there;
    P9 keys on where the entry sits."""
    return mirror, dump, interp, lower, header, _flip_export(export, "std/bytes", "len", "ok")


MUTANTS = [
    ("p1-declare-a-name-the-compiler-has-not", mutate_p1_add, "P1"),
    ("p2-drop-popcount", mutate_p2_drop_popcount, "P2"),
    ("p3-rename-a-parameter", mutate_p3_param_name, "P3"),
    ("p3-widen-a-return-type", mutate_p3_return_type, "P3"),
    ("p4-publish-str_lower", mutate_p4_add_pub, "P4"),
    ("p4-hide-parse_float", mutate_p4_drop_pub, "P4"),
    ("p5-move-a-comptime-marker", mutate_p5_move_marker, "P5"),
    ("m1-arm-for-parse_float", mutate_m1_arm_for_parse_float, "M1"),
    ("p5-mark-parse_float", mutate_p5_mark_parse_float, "P5"),
    ("p6-drop-sort_by-s-effect-binder", mutate_p6_unbind_sort_by, "P6"),
    ("p6-skip-a-signature-that-reads-back", mutate_p6_skip_popcount, "P6"),
    ("p7-drop-list_push-s-owned-position", mutate_p7_drop_list_push, "P7"),
    ("p7-drop-array_with-s-owned-marker", mutate_p7_drop_array_with_marker, "P7"),
    ("p8-consume-where-the-table-borrows", mutate_p8_consume_where_the_table_borrows, "P8"),
    ("p8-drop-cell_set-s-consumes-mark", mutate_p8_drop_cell_set_mark, "P8"),
    ("m3-owned-names-no-intrinsic", mutate_m3_owned_names_no_intrinsic, "M3"),
    ("p9-flip-bytes_utf8-in-the-export", mutate_p9_flip_bytes_utf8, "P9"),
    ("p9-drop-get-s-flag", mutate_p9_drop_get_s_flag, "P9"),
    ("p9-flag-std-bytes-len", mutate_p9_flag_std_bytes_len, "P9"),
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


def run_mutants(mirror, dump, interp, lower, header, export):
    rc = 0
    clean = judge(mirror, dump, interp, lower, header, export)
    if clean:
        print("MUTANT FAIL: the real inputs are not green to begin with:")
        for line in clean:
            print("  " + line)
        return 1
    print("OK   the real mirror is green (the positive control)")
    for name, fn, label in MUTANTS:
        found = judge(*fn(mirror, dump, interp, lower, header, export))
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
    ap.add_argument("--export", help="what `dawn doc --builtins` printed")
    ap.add_argument("--root", default=None)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--mutants", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    root = pathlib.Path(args.root) if args.root else pathlib.Path(__file__).resolve().parents[2]
    if not args.dump:
        ap.error("--dump is required (scripts/builtin-decl-contract/run.sh produces it)")
    if not args.export:
        ap.error("--export is required (scripts/builtin-decl-contract/run.sh produces it)")
    mirror = (root / MIRROR).read_text(encoding="utf-8")
    dump = pathlib.Path(args.dump).read_text(encoding="utf-8")
    interp = (root / INTERP).read_text(encoding="utf-8")
    lower = (root / LOWER).read_text(encoding="utf-8")
    header = (root / HEADER).read_text(encoding="utf-8")
    export = pathlib.Path(args.export).read_text(encoding="utf-8")

    if args.mutants:
        return run_mutants(mirror, dump, interp, lower, header, export)

    bad = judge(mirror, dump, interp, lower, header, export)
    if bad:
        print(f"FAIL: {MIRROR} and the builtin table disagree")
        for line in bad:
            print("  " + line)
        print()
        print(f"  the table in selfhost/src/check/types.dawn is the truth; edit {MIRROR}")
        if any(line.startswith("P9") for line in bad):
            print(
                f"  (P9: the export is selfhost/src/doc.dawn's `comptime_field`, which "
                f"reads ir/interp.dawn's lists; if P5 is green the wrong side is the export)"
            )
        if any(line.startswith(("P7", "P8", "M3")) for line in bad):
            print(
                f"  (P7, P8, M3: an owned position is a fact about the runtime, "
                f"so the wrong side may be the table, {MIRROR} or {HEADER})"
            )
        return 1
    mirror_decls, _ = parse_mirror(mirror)
    builtins, lowering, roundtrips, skips, owned = parse_dump(dump)
    marks, _ = read_runtime_consumes(header)
    flagged = sum(1 for _, flag in read_export(export)[0] if flag == "refused")
    pub = sum(1 for is_pub, _, _ in mirror_decls.values() if is_pub)
    rejected = sum(1 for _, _, r in mirror_decls.values() if r)
    print(
        f"OK: {MIRROR} mirrors all {len(builtins)} builtins "
        f"({pub} public, {len(builtins) - pub} std-only, {rejected} refused at "
        f"comptime), the intrinsic universe of {len(builtins) + len(lowering)} "
        f"names is partitioned three ways by ir/interp.dawn and ir/lower.dawn, "
        f"and {len(roundtrips)} of the "
        f"signatures read back as themselves ({len(skips)} named as spellings "
        f"the parser is not offered); {len(owned)} intrinsics consume an "
        f"argument, and the mirror and {len(marks)} runtime prototypes say which; "
        f"`dawn doc --builtins` flags {flagged} of its {len(builtins)} builtins "
        f"refused at comptime, the same ones"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
