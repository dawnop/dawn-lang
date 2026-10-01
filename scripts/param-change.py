#!/usr/bin/env python3
"""Hold every std parameter-name change to a line in a commit message.

Named arguments (#207) made a parameter name something a caller writes:
`str.split(s, sep: ",")` compiles, so renaming `sep` breaks that call while
every positional caller and every gate that compiles positional code stays
green. api-diff.py lists it, under "Parameter renames", but only when a
release is cut and only as a report: two same-typed parameters trading names
compile every positional call unchanged and reach no other gate at all. So
from v0.80.0 (#210) a parameter rename has to say so, the way a moved output
does:

    Param-Change(<item>): <old> -> <new>

    Param-Change(str.split): sep -> delim
    Param-Change(gpu.unpack_from): raw -> b
    Param-Change(narrow.Narrow.add): a -> lhs
    Param-Change(io.Fs.fs_rename): src -> from
    Param-Change(prelude.Index.index): c -> it
    Param-Change(builtins.join): sep -> -

<item> is `<module>.<fn>`, `<module>.<Trait>.<method>`, `<module>.<Effect>.<op>`,
`prelude.<Trait>.<method>` or `builtins.<fn>`, where <module> is a name in
std/modules.txt (checked: `prelude` and `builtins` may never be one). One slot
per line; `<old> -> -` says the parameter is gone. There is no reason field:
the commit body around the lines is the reason, and the pair itself is what
gets checked.

## What it compares

Both sides are `dawn doc --stdlib`: the N-1 side from the seed toolchain on the
seed's released std, the other from HEAD. For every callee present on both
sides, parameter names are compared BY POSITION, so a swap of two parameters is
two changes. When the arity differs, pairing is unknowable, so every N-1 name
missing from HEAD needs a line (its new name, or `-`), and a new parameter
needs none (api-diff reports an added parameter; a caller naming it did not
exist yet). A callee on one side only is not a rename (api-diff, std/moved.txt
and std-version own additions and removals).

Refused: an undeclared change; a declaration whose item is not an N-1 callee;
a declaration whose <old> is not that callee's N-1 name, or whose <new> is not
what HEAD has. A declaration HEAD does not bear out is a NOTE, not a failure:
the window is read from commit messages, which cannot be edited once pushed, so
a rename that was declared and then reverted would otherwise stay red until
the next release. The residual that choice leaves is the one emitchange.sh
names for itself: a line stays in the window until the seed advances.

## The language, and why it is not Emit-Change's

The rules are emitchange.sh's (its header has the history): no globs, no bare
`Param-Change:`, and a line that starts like a declaration and does not parse
is an error rather than something read generously. The window is the same
too, the commits after the release in scripts/seed-release.txt, so a release
resets it.

What is not shared is the label registry. Emit-Change labels are a fixed set
of checks listed in scripts/emit-labels.txt; the set of items here is the N-1
snapshot itself (a few hundred callees, different every release), so listing them
there would mean editing a registry for every std function added, and that
registry exists precisely because its set is fixed. The meaning differs as
well: Emit-Change says "this label's difference is intended" and checks no
value, while a Param-Change line is checked against the difference it claims,
the way `Gate-Budget(push-total): <old>s -> <new>s` is
(check-gate-budget-trailers.py). Hence its own parser, in Python.

## Modes

    param-change.py compare --old SEED.json --new HEAD.json --range TAG..HEAD
    param-change.py compare --old SEED.json --new HEAD.json --messages FILE
    param-change.py --self-test

`compare` also refuses an N-1 dump with fewer callees than half of HEAD's,
or fewer than an absolute floor of 100 (--min-callees replaces that floor when
given): a dump that parsed to almost nothing is a broken oracle, not a std
with nothing to check. The floor used to be a fixed 400, set when std had
about 480 callees; when #332 moved 169 GPU references out of std/gpu into
packages/tileref, the whole std of v0.82.0 had 321, and a real release was
refused as broken. A count of today's std is a pin on std's size, which is
not what the check is for, so the floor now follows HEAD's own dump. The shell around it, scripts/selfhost-param-diff.sh,
is what proves the N-1 dump came from the seed's own std; its header says how.
Every `compare` run ends with the self-test, as api-diff.py does, because this
script's normal output is "nothing changed", and so is a broken one's.
"""

import argparse
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent

IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
# The keyword followed by `(` or `:`, in any case: what "starts like a
# declaration" means. The keyword alone is not enough, since prose about the
# rule can wrap onto a line that begins with it.
DECL_START = re.compile(r"^Param-Change\s*[(:]", re.I)
DECL = re.compile(
    rf"^Param-Change\((?P<item>{IDENT}(?:\.{IDENT})+)\): "
    rf"(?P<old>{IDENT}) -> (?P<new>{IDENT}|-)[ \t]*$")
PSEUDO = ("prelude", "builtins")
# Where the two pseudo-modules' signatures are declared, named in the message
# for an undeclared change to one of them: a std item says which file moved by
# its module name, and these two would otherwise send the reader to std/.
PSEUDO_SOURCE = "selfhost/src/check/types.dawn"
# The absolute floor: below it a dump parsed to almost nothing, whatever HEAD
# has. The relative half-of-HEAD rule is what scales with std.
MIN_CALLEES = 100


class ParamError(Exception):
    """An input this script will not guess at."""


# --------------------------------------------------------------------------
# reading `dawn doc --stdlib`


def _close(sig, i, open_ch, close_ch):
    """Index of the bracket closing the one at sig[i], nesting ([{ alike."""
    depth = 0
    for j in range(i, len(sig)):
        ch = sig[j]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                if ch != close_ch:
                    break
                return j
    raise ParamError(f"unbalanced {open_ch}{close_ch} in signature: {sig}")


def param_names(sig):
    """The parameter names of one rendered signature, in order.

    `fn name[T: Ord, !e](xs: List[T], f: fn(T) -> U !e) -> R !e`: the list
    after the optional type-parameter brackets, split at its top-level commas,
    each entry's name being what precedes its first `:`. Anything else is an
    error, never an empty list: an empty list compares equal to an empty list.
    """
    m = re.match(rf"fn ({IDENT})", sig or "")
    if not m:
        raise ParamError(f"not a function signature: {sig!r}")
    i = m.end()
    if i < len(sig) and sig[i] == "[":
        i = _close(sig, i, "[", "]") + 1
    if i >= len(sig) or sig[i] != "(":
        raise ParamError(f"no parameter list in signature: {sig}")
    j = _close(sig, i, "(", ")")
    inner = sig[i + 1:j]
    parts, depth, cur = [], 0, ""
    for ch in inner:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    names = []
    for part in parts:
        name, colon, _ = part.partition(":")
        name = name.strip()
        if not colon or not re.fullmatch(IDENT, name):
            raise ParamError(f"cannot read parameter {part.strip()!r} in: {sig}")
        names.append(name)
    if len(set(names)) != len(names):
        raise ParamError(f"a parameter name repeats in: {sig}")
    return names


def callees(doc, where):
    """{item: [parameter names]} for every callee a named argument can reach."""
    if not isinstance(doc, dict):
        raise ParamError(f"{where}: not a JSON object")
    for key in ("modules", "groups", "traits"):
        if not isinstance(doc.get(key), list):
            raise ParamError(f"{where}: no `{key}` list; is this `dawn doc --stdlib`?")
    out = {}

    def put(item, sig):
        if item in out:
            raise ParamError(f"{where}: callee {item} appears twice")
        out[item] = param_names(sig)

    for module in doc["modules"]:
        path = module.get("path", "")
        if not path.startswith("std/") or "/" in path[4:] or not path[4:]:
            raise ParamError(f"{where}: module path {path!r} is not std/<name>")
        name = path[4:]
        if name in PSEUDO:
            raise ParamError(f"{where}: a std module is named {name!r}, which this"
                             " gate reserves for the prelude and the builtins")
        for fn in module.get("fns", []):
            put(f"{name}.{fn['name']}", fn["sig"])
        for trait in module.get("traits", []):
            for method in trait.get("methods", []):
                put(f"{name}.{trait['name']}.{method['name']}", method["sig"])
        for effect in module.get("effects", []):
            for op in effect.get("ops", []):
                put(f"{name}.{effect['name']}.{op['name']}", op["sig"])
    for group in doc["groups"]:
        for fn in group.get("fns", []):
            put(f"builtins.{fn['name']}", fn["sig"])
    for trait in doc["traits"]:
        for method in trait.get("methods", []):
            put(f"prelude.{trait['name']}.{method['name']}", method["sig"])
    return out


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ParamError(f"{path}: {exc}") from exc
    return callees(doc, path)


# --------------------------------------------------------------------------
# reading the declarations


def declarations(lines):
    """-> ({(item, old): {new, ...}}, problems) from commit-message lines."""
    decls, problems = {}, []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not DECL_START.match(line):
            continue
        m = DECL.match(line)
        if m:
            decls.setdefault((m["item"], m["old"]), set()).add(m["new"])
            continue
        head = line.split(")", 1)[0]
        if re.match(r"^Param-Change\s*:", line, re.I):
            why = ("unscoped: a bare `Param-Change:` names no callee; write one"
                   " `Param-Change(<item>): <old> -> <new>` per slot, or leave"
                   " the line out if nothing changed")
        elif any(ch in head for ch in "*?[{"):
            why = ("a glob covers callees that did not exist when it was"
                   " written; name each one")
        else:
            why = ("unparseable; the form is `Param-Change(<item>): <old> ->"
                   " <new>` with bare identifiers, `-` for a removed"
                   " parameter, and nothing after")
        problems.append(f"FAIL {line}\n     {why}")
    return decls, problems


def window_lines(rev_range):
    """The commit-message lines of a range. A range git cannot read is an
    error: an empty window would silently mean "nothing declared"."""
    proc = subprocess.run(["git", "-C", str(ROOT), "log", rev_range, "--format=%B"],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ParamError(f"git log {rev_range} failed: {proc.stderr.strip()}")
    return proc.stdout.splitlines()


# --------------------------------------------------------------------------
# the comparison


def compare(old, new, decls):
    """-> (failures, notes, changes seen). Pure: the self-test drives it."""
    fails, notes, used = [], [], set()
    changes = 0
    for (item, name), news in sorted(decls.items()):
        if item not in old:
            near = difflib.get_close_matches(item, list(old), n=3)
            fails.append(f"FAIL Param-Change({item}): no such N-1 item"
                         + (f" (closest: {', '.join(near)})" if near else ""))
            used.add((item, name))
        elif name not in old[item]:
            fails.append(f"FAIL Param-Change({item}): {name} -> ...: `{name}` is not"
                         f" a parameter of {item} in N-1 ({', '.join(old[item]) or 'none'})")
            used.add((item, name))
        elif len(news) > 1:
            fails.append(f"FAIL Param-Change({item}): {name} is declared as"
                         f" {' and '.join(sorted(news))}; one slot, one new name")
            used.add((item, name))
    for item in sorted(set(old) & set(new)):
        a, b = old[item], new[item]
        if len(a) == len(b):
            moved = [(k, x, y) for k, (x, y) in enumerate(zip(a, b)) if x != y]
        else:
            moved = [(a.index(x), x, None) for x in a if x not in b]
        for slot, x, y in moved:
            changes += 1
            key = (item, x)
            if key in used:
                continue
            said = decls.get(key)
            shown = y if y is not None else "<gone or moved>"
            if not said:
                where = (f"; {item.split('.')[0]} is declared in {PSEUDO_SOURCE}"
                         if item.split(".")[0] in PSEUDO else "")
                fails.append(
                    f"FAIL {item}: parameter {slot + 1} `{x}` -> `{shown}` and no"
                    f" commit since the tag declares it{where}\n     (declare it with"
                    f" 'Param-Change({item}): {x} -> {y if y is not None else '<new>|-'}')")
                continue
            used.add(key)
            (z,) = tuple(said)
            ok = z == y if y is not None else (z == "-" or (z in b and z not in a))
            if ok:
                notes.append(f"OK   {item}: {x} -> {z} (declared)")
            else:
                fails.append(f"FAIL Param-Change({item}): {x} -> {z}, but HEAD has"
                             f" `{shown}` in that slot ({', '.join(b)})")
    for key in sorted(set(decls) - used):
        item, name = key
        why = "not in HEAD" if item not in new else "unchanged in HEAD"
        notes.append(f"NOTE Param-Change({item}): {name} -> {'/'.join(sorted(decls[key]))}"
                     f" is declared, and the callee is {why}")
    return fails, notes, changes


def check_whole(name, n_old, n_new, floor=MIN_CALLEES):
    """Refuse an N-1 dump too small to be a whole std. Pure: the self-test
    drives it."""
    if n_old < floor:
        raise ParamError(f"{name}: {n_old} callees, fewer than {floor};"
                         " the N-1 dump is not a whole std")
    if 2 * n_old < n_new:
        raise ParamError(f"{name}: {n_old} callees, fewer than half of HEAD's"
                         f" {n_new}; the N-1 dump is not a whole std")


def run_compare(args):
    old, new = load(args.old), load(args.new)
    check_whole(args.old, len(old), len(new), args.min_callees)
    if args.messages:
        lines = Path(args.messages).read_text(encoding="utf-8").splitlines()
    else:
        lines = window_lines(args.range)
    decls, problems = declarations(lines)
    fails, notes, changes = compare(old, new, decls)
    for note in notes:
        print(note)
    for fail in problems + fails:
        print(fail)
    shared = len(set(old) & set(new))
    print(f"# {shared} callees compared ({len(old)} in N-1, {len(new)} in HEAD),"
          f" {changes} parameter-name change(s), {sum(len(v) for v in decls.values())}"
          f" declaration(s), {len(problems) + len(fails)} failure(s)")
    if problems:
        print("FAIL: the Param-Change declarations in this window do not parse;"
              " fix the commit message (see scripts/param-change.py)")
    return 1 if problems or fails else 0


# --------------------------------------------------------------------------
# self-test


def _doc(fns=(), builtins=(), prelude=(), traits=(), effects=()):
    return {
        "groups": [{"name": "g", "fns": [{"name": n, "sig": s} for n, s in builtins]}],
        "traits": [{"name": "Idx", "methods": [{"name": n, "sig": s} for n, s in prelude]}],
        "modules": [{"path": "std/str",
                     "fns": [{"name": n, "sig": s} for n, s in fns],
                     "traits": [{"name": "Tr", "methods": [{"name": n, "sig": s}
                                                            for n, s in traits]}],
                     "effects": [{"name": "Ef", "ops": [{"name": n, "sig": s}
                                                         for n, s in effects]}]}],
    }


_SPLIT = ("split", "fn split(s: String, sep: String) -> List[String]")
_REMF = ("ref_remf", "fn ref_remf(a: Float, b: Float) -> Float")
_MAP = ("map", "fn map[T, U, !e](xs: List[T], f: fn(T, Int) -> U !e) -> List[U] !e")
_BASE = dict(fns=[_SPLIT, _REMF, _MAP],
             builtins=[("join", "fn join(xs: List[String], sep: String) -> String")],
             prelude=[("index", "fn index[T: Idx](c: T, i: T.Idx) -> T.Item")],
             traits=[("add", "fn add[T: Tr](a: T, b: T) -> T")],
             effects=[("fs_rename", "fn fs_rename(src: String, dst: String) -> Unit !Ef")])


def _with(**over):
    spec = {k: list(v) for k, v in _BASE.items()}
    for key, (name, sig) in over.items():
        kind = key.split("__")[0]
        spec[kind] = [(n, sig if n == name else s) for n, s in spec[kind]]
    return _doc(**spec)


CASES = (
    # (label, new doc, message lines, want failures)
    ("nothing changed", _with(), [], 0),
    ("a rename, undeclared", _with(fns=("split", "fn split(s: String, delim: String) -> List[String]")),
     [], 1),
    ("a rename, declared", _with(fns=("split", "fn split(s: String, delim: String) -> List[String]")),
     ["Param-Change(str.split): sep -> delim"], 0),
    ("a swap of two same-typed parameters is two changes",
     _with(fns=("ref_remf", "fn ref_remf(b: Float, a: Float) -> Float")), [], 2),
    ("a swap, both slots declared",
     _with(fns=("ref_remf", "fn ref_remf(b: Float, a: Float) -> Float")),
     ["Param-Change(str.ref_remf): a -> b", "Param-Change(str.ref_remf): b -> a"], 0),
    ("an item N-1 does not have", _with(), ["Param-Change(str.splt): sep -> delim"], 1),
    ("an old name N-1 does not have", _with(), ["Param-Change(str.split): delim -> sep"], 1),
    ("a declared new name HEAD does not have",
     _with(fns=("split", "fn split(s: String, delim: String) -> List[String]")),
     ["Param-Change(str.split): sep -> separator"], 1),
    ("a glob", _with(), ["Param-Change(str.*): sep -> delim"], 1),
    ("a bare declaration", _with(), ["Param-Change: none"], 1),
    ("trailing text", _with(), ["Param-Change(str.split): sep -> delim because"], 1),
    ("declared and unchanged is a note", _with(), ["Param-Change(str.split): sep -> delim"], 0),
    ("prose that wraps onto the keyword", _with(), ["Param-Change lines are checked"], 0),
    ("a removed parameter, undeclared",
     _with(fns=("split", "fn split(s: String) -> List[String]")), [], 1),
    ("a removed parameter, declared",
     _with(fns=("split", "fn split(s: String) -> List[String]")),
     ["Param-Change(str.split): sep -> -"], 0),
    ("an added parameter needs nothing",
     _with(fns=("split", "fn split(s: String, sep: String, n: Int) -> List[String]")), [], 0),
    ("a nested function type keeps its commas",
     _with(fns=("map", "fn map[T, U, !e](xs: List[T], g: fn(T, Int) -> U !e) -> List[U] !e")),
     [], 1),
    ("the prelude", _with(prelude=("index", "fn index[T: Idx](it: T, i: T.Idx) -> T.Item")),
     ["Param-Change(prelude.Idx.index): c -> it"], 0),
    ("the prelude, undeclared",
     _with(prelude=("index", "fn index[T: Idx](it: T, i: T.Idx) -> T.Item")), [], 1),
    ("a builtin", _with(builtins=("join", "fn join(xs: List[String], by: String) -> String")),
     ["Param-Change(builtins.join): sep -> by"], 0),
    ("a std trait method", _with(traits=("add", "fn add[T: Tr](x: T, b: T) -> T")),
     ["Param-Change(str.Tr.add): a -> x"], 0),
    ("an effect operation",
     _with(effects=("fs_rename", "fn fs_rename(from: String, dst: String) -> Unit !Ef")),
     ["Param-Change(str.Ef.fs_rename): src -> from"], 0),
    ("one slot declared two ways",
     _with(fns=("split", "fn split(s: String, delim: String) -> List[String]")),
     ["Param-Change(str.split): sep -> delim", "Param-Change(str.split): sep -> by"], 1),
)

# Inputs the reader must refuse rather than read as "no callees".
MUTANTS = (
    ("not an object", []),
    ("no modules list", {"groups": [], "traits": []}),
    ("a module outside std/", {"groups": [], "traits": [], "modules": [{"path": "x"}]}),
    ("a std module named prelude",
     {"groups": [], "traits": [], "modules": [{"path": "std/prelude"}]}),
    ("a signature with no parameter list",
     _doc(fns=[("f", "fn f -> Int")])),
    ("an unbalanced signature", _doc(fns=[("f", "fn f(a: List[Int) -> Int")])),
    ("a parameter with no type", _doc(fns=[("f", "fn f(a) -> Int")])),
    ("a callee listed twice", _doc(fns=[_SPLIT, _SPLIT])),
)

# The whole-std check: (label, N-1 callees, HEAD callees, the refusal's
# wording or None for accepted). The floor case has HEAD as small as N-1, so
# only the absolute floor can refuse it.
SIZES = (
    ("an N-1 dump under half of HEAD's", 160, 321, "fewer than half of HEAD's 321"),
    ("an N-1 dump at exactly half of HEAD's", 160, 320, None),
    ("an N-1 dump under the absolute floor", 99, 99, "fewer than 100;"),
    ("an N-1 dump at the absolute floor", 100, 150, None),
)


def self_test(verbose=True):
    failures = []
    base = callees(_with(), "base")
    for label, new_doc, lines, want in CASES:
        decls, problems = declarations(lines)
        fails, _notes, _n = compare(base, callees(new_doc, label), decls)
        got = len(problems) + len(fails)
        if got != want:
            failures.append(f"{label}: expected {want} failure(s), got {got}:"
                            f" {problems + fails}")
        elif verbose:
            print(f"  {'refused' if want else 'accepted'}: {label}"
                  + (f" ({got})" if got > 1 else ""))
    for label, doc in MUTANTS:
        try:
            callees(doc, "mutant")
        except ParamError:
            if verbose:
                print(f"  refused: {label}")
        else:
            failures.append(f"malformed input accepted: {label}")
    for label, n_old, n_new, want in SIZES:
        try:
            check_whole("seed.json", n_old, n_new)
        except ParamError as exc:
            got = True
            if want and (want not in str(exc)
                         or "the N-1 dump is not a whole std" not in str(exc)):
                failures.append(f"{label}: refused with the wrong message: {exc}")
        else:
            got = False
        if got != bool(want):
            failures.append(f"{label}: expected {'refused' if want else 'accepted'}")
        elif verbose:
            print(f"  {'refused' if want else 'accepted'}: {label}")
    for failure in failures:
        print(f"SELFTEST FAIL: {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"selftest: {len(CASES)} case(s) as expected, {len(MUTANTS)} malformed"
          f" input(s) refused, {len(SIZES)} whole-std size(s) as expected")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="mode")
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--old", required=True, help="the N-1 `dawn doc --stdlib`")
    cmp_.add_argument("--new", required=True, help="HEAD's `dawn doc --stdlib`")
    src = cmp_.add_mutually_exclusive_group(required=True)
    src.add_argument("--range", help="the declaration window, TAG..HEAD")
    src.add_argument("--messages", help="a file of commit-message lines instead")
    cmp_.add_argument("--min-callees", type=int, default=MIN_CALLEES)
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.mode != "compare":
        ap.error("expected `compare` or --self-test")
    try:
        code = run_compare(args)
    except ParamError as exc:
        print(f"param-change: {exc}", file=sys.stderr)
        return 1
    return code or self_test(verbose=False)


if __name__ == "__main__":
    sys.exit(main())
