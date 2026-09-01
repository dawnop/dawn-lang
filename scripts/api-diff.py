#!/usr/bin/env python3
"""Classify the public-API difference between two snapshots, as a report.

    scripts/api-diff.py OLD.json NEW.json [-o REPORT.md]
    scripts/api-diff.py NEW.json          [-o REPORT.md]   # no baseline
    scripts/api-diff.py --self-test

Inputs are `scripts/api-snapshot.py` files. Output is Markdown, published as a
release asset (`.github/workflows/release.yml`).

A report, not a gate. Nothing here fails a release, and no version number is
policed: consumers pin bytes by content hash (`[deps.*]` requires url +
version + hash), so the only thing a semver check could protect is a
convention the machine does not read. What is worth having is the sentence a
reader cannot get anywhere else, which in an effect-typed language is this one:

    `sha2/sha256`: `fn digest` **EFFECT ROW EXPANDED** (+!io)

A dependency that quietly started doing IO says so in its type, and this is
where that shows up between two releases.

## Why effect *atoms* and not the rendered string

`sig_render` is one function and it changes. In one month it changed six
times; one of those changes (0f94836, "Render a signature's effect
parameters") turned `fn map[T, U](...)` into `fn map[T, U, !e](...)` for 21
signatures with no semantic movement whatsoever. A classifier comparing
rendered strings would have called that 21 breaking changes, and a reader who
has been shown 21 false breaks stops reading the report.

So every signature is reduced to two facts before comparison:

  * its **effect atoms**, the set of `!name` occurrences anywhere in it. This
    is what the headline is about, and it is invariant under where the
    renderer chooses to put them: 0f94836 moved `!e` into the binder list,
    which the set does not notice.
  * its **shape**, the signature with every effect atom deleted and the
    resulting punctuation normalized (`[T, U, ]` -> `[T, U]`, `[]` -> nothing).
    A parameter type change survives this; a renderer that relocates effects
    does not.

Two signatures agreeing on both are reported as no change at all, and the
count of such pairs is printed in the summary so that "renderer moved" is
visible as a number rather than as silence.

## Known limitations, restated in every report header

  * It sees signatures, not semantics. A behavior change under an unchanged
    signature is invisible here, and that includes the whole class of bugs.
  * Doc comments are not compared (the snapshot does not carry them).
  * Renaming an effect *variable* (`!e` -> `!f`) is a change of atoms and is
    reported as one, though it means nothing.

## Self-test

Every run ends by reproducing the golden cases in `GOLDEN` and by feeding
malformed snapshots to the loader (`MUTANTS`), because a diff tool's normal
output is "nothing changed" and that is also what a broken one prints. The
malformed inputs are the half that matters: a snapshot that failed to parse
must be an error, never an empty report.
"""

import argparse
import json
import re
import sys

SCHEMA = 1

BREAK, ADD, NARROW = "break", "addition", "narrowing"
SECTIONS = (
    (BREAK, "Breaking"),
    (ADD, "Additions"),
    (NARROW, "Narrowings"),
)

# An effect atom: `!io`, `!M.E`, or the empty row `!()`.
EFFECT_ATOM = re.compile(r"!\(\)|![A-Za-z_][A-Za-z0-9_.]*")

KINDS = ("fns", "types", "consts", "traits", "effects")
SINGULAR = {"fns": "fn", "types": "type", "consts": "const",
            "traits": "trait", "effects": "effect"}


class DiffError(Exception):
    """An input this script will not guess at. Never an empty report."""


# --------------------------------------------------------------------------
# signatures


def effects_of(sig: str) -> set:
    """Every effect atom mentioned anywhere in a rendered signature."""
    return {a[1:] for a in EFFECT_ATOM.findall(sig or "")}


def shape_of(sig: str) -> str:
    """The signature with its effect atoms removed and punctuation repaired.

    Deleting `!e` from `fn map[T, U, !e](xs: List[T], f: fn(T) -> U !e)` leaves
    `[T, U, ]` and a stray space before `)`; deleting it from `fn f[!e](x: Int)`
    leaves an empty `[]` where the pre-0f94836 renderer printed nothing at all.
    Both have to come back to the same string as the version that never
    mentioned the effect, or the renderer tolerance this function exists for
    does not hold.
    """
    s = EFFECT_ATOM.sub("", sig or "")
    s = re.sub(r"\s+", " ", s)
    for _ in range(3):  # `[T, !e, !f]` sheds one comma per pass
        s = re.sub(r"\s*,\s*", ", ", s)
        s = re.sub(r"([\[(])\s*,\s*", r"\1", s)
        s = re.sub(r",\s*([\])])", r"\1", s)
        s = re.sub(r"\s+([\])])", r"\1", s)
        s = re.sub(r"([\[(])\s+", r"\1", s)
        s = re.sub(r"\[\]", "", s)
    return s.strip()


class Event:
    def __init__(self, severity: str, where: str, what: str, detail=()):
        self.severity = severity
        self.where = where
        self.what = what
        self.detail = list(detail)

    def lines(self) -> list:
        out = [f"- {self.where}: {self.what}"]
        out += [f"    - {d}" for d in self.detail]
        return out


def was_now(old: str, new: str) -> list:
    return [f"was: `{old}`", f"now: `{new}`"]


class Diff:
    """Accumulates events, and counts what it deliberately did not report."""

    def __init__(self):
        self.events = []
        self.rendering_only = 0

    def add(self, severity, where, what, detail=()):
        self.events.append(Event(severity, where, what, detail))

    def signature(self, where, what, old, new):
        """One signature-shaped string pair: the effect-aware comparison."""
        if old == new:
            return
        gained = sorted(effects_of(new) - effects_of(old))
        lost = sorted(effects_of(old) - effects_of(new))
        if gained:
            note = "**EFFECT ROW EXPANDED** (+" + ", ".join("!" + g for g in gained) + ")"
            if lost:
                note += " and narrowed (-" + ", ".join("!" + m for m in lost) + ")"
            self.add(BREAK, where, f"{what} {note}", was_now(old, new))
        elif shape_of(old) != shape_of(new):
            self.add(BREAK, where, f"{what} signature changed", was_now(old, new))
        elif lost:
            note = "effect row narrowed (-" + ", ".join("!" + m for m in lost) + ")"
            self.add(NARROW, where, f"{what} {note}", was_now(old, new))
        else:
            self.rendering_only += 1


# --------------------------------------------------------------------------
# loading


def by_name(entries: list, where: str, kind: str) -> dict:
    out = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise DiffError(f"{where}: a {kind} entry has no name")
        if entry["name"] in out:
            raise DiffError(f"{where}: {kind} {entry['name']!r} appears twice")
        out[entry["name"]] = entry
    return out


def load_obj(snap, where: str) -> dict:
    """Validate a snapshot and index it by name.

    Source order is not stable -- `dawn doc` prints `wire` before `dsl` in one
    package and the reverse would be as correct -- so every level is indexed
    here and nothing downstream may iterate a list. The validation is not
    ceremony: an unreadable snapshot has to reach the caller as an exception,
    because the alternative is a report that says nothing changed.
    """
    if not isinstance(snap, dict):
        raise DiffError(f"{where}: not a JSON object")
    if snap.get("schema") != SCHEMA:
        raise DiffError(f"{where}: schema {snap.get('schema')!r}, expected {SCHEMA}")
    units = snap.get("units")
    if not isinstance(units, dict) or not units:
        raise DiffError(f"{where}: no units")
    indexed = {}
    for uname, unit in sorted(units.items()):
        if not isinstance(unit, dict):
            raise DiffError(f"{where}: unit {uname!r} is not an object")
        modules = unit.get("modules")
        if not isinstance(modules, list):
            raise DiffError(f"{where}: unit {uname!r} has no module list")
        mods = {}
        for module in modules:
            if not isinstance(module, dict) or not isinstance(module.get("path"), str):
                raise DiffError(f"{where}: unit {uname!r} has a module with no path")
            path = module["path"]
            if path in mods:
                raise DiffError(f"{where}: unit {uname!r} lists module {path!r} twice")
            at = f"{where} {uname}/{path}"
            entry = {k: by_name(module.get(k, []), at, SINGULAR[k]) for k in KINDS}
            impls = module.get("impls", [])
            if not isinstance(impls, list):
                raise DiffError(f"{at}: impls is not a list")
            entry["impls"] = set(impls)
            mods[path] = entry
        indexed[uname] = {"version": unit.get("version"), "modules": mods}
    return {"toolchain": snap.get("toolchain"), "units": indexed}


def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            snap = json.load(fh)
    except json.JSONDecodeError as exc:
        raise DiffError(f"{path}: not JSON ({exc})") from exc
    except OSError as exc:
        raise DiffError(f"{path}: {exc}") from exc
    return load_obj(snap, path)


# --------------------------------------------------------------------------
# classification


def diff_type(d: Diff, where: str, name: str, old: dict, new: dict) -> None:
    what = f"type `{name}`"
    if bool(old.get("record")) != bool(new.get("record")):
        d.add(BREAK, where, f"{what} changed between record and variant form")
    if old.get("typeParams") != new.get("typeParams"):
        d.add(BREAK, where, f"{what} type parameters changed",
              was_now(", ".join(old.get("typeParams") or []),
                      ", ".join(new.get("typeParams") or [])))
    oc = by_name(old.get("ctors", []), where, "ctor")
    nc = by_name(new.get("ctors", []), where, "ctor")
    for cname in sorted(set(oc) - set(nc)):
        d.add(BREAK, where, f"{what}: constructor `{cname}` removed")
    for cname in sorted(set(nc) - set(oc)):
        # Additive only for code that never matches on this type; every
        # exhaustive `match` over it stops compiling.
        d.add(BREAK, where, f"{what}: constructor `{cname}` added "
                            "(exhaustive matches must grow a case)")
    for cname in sorted(set(oc) & set(nc)):
        of = by_name(oc[cname].get("fields", []), where, "field")
        nf = by_name(nc[cname].get("fields", []), where, "field")
        for fname in sorted(set(of) - set(nf)):
            d.add(BREAK, where, f"{what}: constructor `{cname}` field `{fname}` removed")
        for fname in sorted(set(nf) - set(of)):
            d.add(BREAK, where, f"{what}: constructor `{cname}` field `{fname}` added",
                  [f"now: `{fname}: {nf[fname].get('type')}`"])
        oorder = [f["name"] for f in oc[cname].get("fields", []) if f["name"] in nf]
        norder = [f["name"] for f in nc[cname].get("fields", []) if f["name"] in of]
        if oorder != norder:
            d.add(BREAK, where, f"{what}: constructor `{cname}` field order changed",
                  was_now(", ".join(oorder), ", ".join(norder)))
        for fname in sorted(set(of) & set(nf)):
            d.signature(where, f"{what}: constructor `{cname}` field `{fname}`",
                        of[fname].get("type"), nf[fname].get("type"))


def diff_trait(d: Diff, where: str, name: str, old: dict, new: dict) -> None:
    what = f"trait `{name}`"
    if old.get("typeParam") != new.get("typeParam"):
        d.add(BREAK, where, f"{what} type parameter changed",
              was_now(old.get("typeParam"), new.get("typeParam")))
    oa, na = set(old.get("assoc") or []), set(new.get("assoc") or [])
    for aname in sorted(oa - na):
        d.add(BREAK, where, f"{what}: associated type `{aname}` removed")
    for aname in sorted(na - oa):
        d.add(BREAK, where, f"{what}: associated type `{aname}` added "
                            "(every impl must provide it)")
    oe = by_name(old.get("effectAssoc") or [], where, "associated effect")
    ne = by_name(new.get("effectAssoc") or [], where, "associated effect")
    for aname in sorted(set(oe) - set(ne)):
        d.add(BREAK, where, f"{what}: associated effect `{aname}` removed")
    for aname in sorted(set(ne) - set(oe)):
        d.add(BREAK, where, f"{what}: associated effect `{aname}` added")
    for aname in sorted(set(oe) & set(ne)):
        d.signature(where, f"{what}: associated effect `{aname}` default",
                    oe[aname].get("default", "!()"), ne[aname].get("default", "!()"))
    om = by_name(old.get("methods") or [], where, "method")
    nm = by_name(new.get("methods") or [], where, "method")
    for mname in sorted(set(om) - set(nm)):
        d.add(BREAK, where, f"{what}: method `{mname}` removed")
    for mname in sorted(set(nm) - set(om)):
        if nm[mname].get("hasDefault"):
            d.add(ADD, where, f"{what}: method `{mname}` added (has a default)")
        else:
            d.add(BREAK, where, f"{what}: method `{mname}` added "
                                "(every impl must provide it)")
    for mname in sorted(set(om) & set(nm)):
        if om[mname].get("hasDefault") and not nm[mname].get("hasDefault"):
            d.add(BREAK, where, f"{what}: method `{mname}` lost its default")
        elif nm[mname].get("hasDefault") and not om[mname].get("hasDefault"):
            d.add(ADD, where, f"{what}: method `{mname}` gained a default")
        d.signature(where, f"{what}: method `{mname}`",
                    om[mname].get("sig"), nm[mname].get("sig"))


def diff_effect(d: Diff, where: str, name: str, old: dict, new: dict) -> None:
    what = f"effect `{name}`"
    oo = by_name(old.get("ops") or [], where, "operation")
    no = by_name(new.get("ops") or [], where, "operation")
    for oname in sorted(set(oo) - set(no)):
        d.add(BREAK, where, f"{what}: operation `{oname}` removed")
    for oname in sorted(set(no) - set(oo)):
        d.add(BREAK, where, f"{what}: operation `{oname}` added "
                            "(every handler must grow a case)")
    for oname in sorted(set(oo) & set(no)):
        d.signature(where, f"{what}: operation `{oname}`",
                    oo[oname].get("sig"), no[oname].get("sig"))


def diff_module(d: Diff, where: str, old: dict, new: dict) -> None:
    for kind in KINDS:
        om, nm = old[kind], new[kind]
        for name in sorted(set(om) - set(nm)):
            d.add(BREAK, where, f"{SINGULAR[kind]} `{name}` removed")
        for name in sorted(set(nm) - set(om)):
            d.add(ADD, where, f"{SINGULAR[kind]} `{name}` added")
        for name in sorted(set(om) & set(nm)):
            if kind == "fns":
                d.signature(where, f"`fn {name}`", om[name].get("sig"), nm[name].get("sig"))
            elif kind == "consts":
                d.signature(where, f"const `{name}`", om[name].get("type"),
                            nm[name].get("type"))
            elif kind == "types":
                diff_type(d, where, name, om[name], nm[name])
            elif kind == "traits":
                diff_trait(d, where, name, om[name], nm[name])
            else:
                diff_effect(d, where, name, om[name], nm[name])
    for impl in sorted(old["impls"] - new["impls"]):
        d.add(BREAK, where, f"impl `{impl}` removed")
    for impl in sorted(new["impls"] - old["impls"]):
        d.add(ADD, where, f"impl `{impl}` added")


def diff(old: dict, new: dict) -> Diff:
    d = Diff()
    ou, nu = old["units"], new["units"]
    for uname in sorted(set(ou) - set(nu)):
        d.add(BREAK, f"`{uname}`", "unit removed from the release")
    for uname in sorted(set(nu) - set(ou)):
        d.add(ADD, f"`{uname}`", "unit added to the release")
    for uname in sorted(set(ou) & set(nu)):
        om, nm = ou[uname]["modules"], nu[uname]["modules"]
        for path in sorted(set(om) - set(nm)):
            d.add(BREAK, f"`{uname}`", f"module `{path}` removed")
        for path in sorted(set(nm) - set(om)):
            d.add(ADD, f"`{uname}`", f"module `{path}` added")
        for path in sorted(set(om) & set(nm)):
            diff_module(d, f"`{uname}` `{path}`", om[path], nm[path])
    return d


def event_lines(d: Diff) -> list:
    """The classified events, and nothing else. What the golden cases pin."""
    out = []
    for severity, title in SECTIONS:
        rows = [e for e in d.events if e.severity == severity]
        if not rows:
            continue
        out.append(f"## {title} ({len(rows)})")
        out.append("")
        for event in rows:
            out += event.lines()
        out.append("")
    return out[:-1] if out else []


# --------------------------------------------------------------------------
# report


HEADER = """\
# Public API diff

Generated by `scripts/api-diff.py` from two `scripts/api-snapshot.py`
snapshots: the stdlib plus every package under `packages/`, with dependency
modules attributed to the unit that owns them.

**What this report cannot see.** It compares declared signatures, not
semantics: a behavior change under an unchanged signature does not appear
here at all. Doc comments are not compared. Renaming an effect variable
(`!e` to `!f`) is a change of effect atoms and is reported as one, although
it means nothing.

**What it is for.** Effect rows are in the types, so a unit that started
doing IO cannot do it quietly: the row grows, and that is a `break` line
below. Signatures are compared as effect-atom sets plus an effect-free shape,
so a change to the signature *renderer* moves no line in this report.

This is a report, not a gate. No release is blocked by anything below.
"""

NO_BASELINE = """\
No previous snapshot was published, so there is nothing to compare against.
This is the expected state for the first release carrying `dawn-pub-api.json`;
the next release will diff against this one.
"""


def units_table(old, new) -> list:
    names = sorted(set(old["units"]) | set(new["units"])) if old else sorted(new["units"])
    rows = ["| unit | before | after |", "| --- | --- | --- |"]
    ov = (old or {"units": {}})["units"]
    rows.append(f"| toolchain | {(old or {}).get('toolchain', '--')} | "
                f"{new.get('toolchain', '--')} |")
    for name in names:
        rows.append(f"| {name} | {ov.get(name, {}).get('version', '--')} | "
                    f"{new['units'].get(name, {}).get('version', '--')} |")
    return rows


def report(old, new) -> str:
    out = [HEADER]
    if old is None:
        out.append(NO_BASELINE)
        out.append("## Units\n")
        out.append("\n".join(units_table(None, new)) + "\n")
        return "\n".join(out)

    d = diff(old, new)
    counts = {sev: sum(1 for e in d.events if e.severity == sev) for sev, _ in SECTIONS}
    out.append("## Summary\n")
    out.append(f"- breaking: {counts[BREAK]}\n"
               f"- additions: {counts[ADD]}\n"
               f"- narrowings: {counts[NARROW]}\n"
               f"- rendering-only signature differences (not reported): "
               f"{d.rendering_only}\n")
    out.append("## Units\n")
    out.append("\n".join(units_table(old, new)) + "\n")
    body = event_lines(d)
    out.append("\n".join(body) + "\n" if body else "No public API change.\n")
    return "\n".join(out)


# --------------------------------------------------------------------------
# golden cases


def _snap(units) -> dict:
    return {"schema": SCHEMA, "toolchain": "1.0.0", "units": units}


def _unit(*modules, version="1.0.0") -> dict:
    return {"version": version, "modules": list(modules)}


def _mod(path, **kinds) -> dict:
    module = {"path": path}
    module.update(kinds)
    return module


def _fn(name, sig) -> dict:
    return {"name": name, "sig": sig}


def _one(module) -> dict:
    """A snapshot holding a single unit `u` with a single module."""
    return _snap({"u": _unit(module)})


_FN_MAP_OLD = "fn map[T, U](xs: List[T], f: fn(T) -> U !e) -> List[U] !e"
_FN_MAP_NEW = "fn map[T, U, !e](xs: List[T], f: fn(T) -> U !e) -> List[U] !e"

GOLDEN = (
    (
        "fn removed",
        _one(_mod("m", fns=[_fn("a", "fn a() -> Int"), _fn("b", "fn b() -> Int")])),
        _one(_mod("m", fns=[_fn("a", "fn a() -> Int")])),
        ["## Breaking (1)", "", "- `u` `m`: fn `b` removed"],
    ),
    (
        "fn added",
        _one(_mod("m", fns=[_fn("a", "fn a() -> Int")])),
        _one(_mod("m", fns=[_fn("a", "fn a() -> Int"), _fn("b", "fn b() -> Int")])),
        ["## Additions (1)", "", "- `u` `m`: fn `b` added"],
    ),
    (
        "effect row expanded",
        _one(_mod("m", fns=[_fn("digest", "fn digest(b: Bytes) -> String")])),
        _one(_mod("m", fns=[_fn("digest", "fn digest(b: Bytes) -> String !io")])),
        ["## Breaking (1)", "",
         "- `u` `m`: `fn digest` **EFFECT ROW EXPANDED** (+!io)",
         "    - was: `fn digest(b: Bytes) -> String`",
         "    - now: `fn digest(b: Bytes) -> String !io`"],
    ),
    (
        "effect row contracted",
        _one(_mod("m", fns=[_fn("digest", "fn digest(b: Bytes) -> String !io")])),
        _one(_mod("m", fns=[_fn("digest", "fn digest(b: Bytes) -> String")])),
        ["## Narrowings (1)", "",
         "- `u` `m`: `fn digest` effect row narrowed (-!io)",
         "    - was: `fn digest(b: Bytes) -> String !io`",
         "    - now: `fn digest(b: Bytes) -> String`"],
    ),
    (
        "param type changed",
        _one(_mod("m", fns=[_fn("put", "fn put(k: String, v: Int) -> Unit")])),
        _one(_mod("m", fns=[_fn("put", "fn put(k: String, v: Int64) -> Unit")])),
        ["## Breaking (1)", "",
         "- `u` `m`: `fn put` signature changed",
         "    - was: `fn put(k: String, v: Int) -> Unit`",
         "    - now: `fn put(k: String, v: Int64) -> Unit`"],
    ),
    (
        "ctor field added",
        _one(_mod("m", types=[{"name": "Cfg", "record": True, "typeParams": [], "ctors": [
            {"name": "Cfg", "fields": [{"name": "host", "type": "String"}]}]}])),
        _one(_mod("m", types=[{"name": "Cfg", "record": True, "typeParams": [], "ctors": [
            {"name": "Cfg", "fields": [{"name": "host", "type": "String"},
                                       {"name": "port", "type": "Int"}]}]}])),
        ["## Breaking (1)", "",
         "- `u` `m`: type `Cfg`: constructor `Cfg` field `port` added",
         "    - now: `port: Int`"],
    ),
    (
        "trait method added",
        _one(_mod("m", traits=[{"name": "Tree", "typeParam": "W", "assoc": [], "methods": [
            {"name": "kids", "sig": "fn kids[W: Tree](w: W) -> List[W]",
             "hasDefault": False}]}])),
        _one(_mod("m", traits=[{"name": "Tree", "typeParam": "W", "assoc": [], "methods": [
            {"name": "kids", "sig": "fn kids[W: Tree](w: W) -> List[W]",
             "hasDefault": False},
            {"name": "relate", "sig": "fn relate[W: Tree](a: W, b: W) -> Bool",
             "hasDefault": False}]}])),
        ["## Breaking (1)", "",
         "- `u` `m`: trait `Tree`: method `relate` added (every impl must provide it)"],
    ),
    (
        "impl removed",
        _one(_mod("m", impls=["Show[Cursor]", "Eq[Cursor]"])),
        _one(_mod("m", impls=["Eq[Cursor]"])),
        ["## Breaking (1)", "", "- `u` `m`: impl `Show[Cursor]` removed"],
    ),
    (
        "module removed",
        _snap({"u": _unit(_mod("keep"), _mod("gone"))}),
        _snap({"u": _unit(_mod("keep"))}),
        ["## Breaking (1)", "", "- `u`: module `gone` removed"],
    ),
    (
        "effect operation added",
        _one(_mod("m", effects=[{"name": "Ctx", "ops": [
            {"name": "get", "sig": "fn get() -> Int !Ctx"}]}])),
        _one(_mod("m", effects=[{"name": "Ctx", "ops": [
            {"name": "get", "sig": "fn get() -> Int !Ctx"},
            {"name": "put", "sig": "fn put(v: Int) -> Unit !Ctx"}]}])),
        ["## Breaking (1)", "",
         "- `u` `m`: effect `Ctx`: operation `put` added (every handler must grow a case)"],
    ),
    (
        "record field type gained an effect",
        _one(_mod("m", types=[{"name": "Route", "record": True, "typeParams": [], "ctors": [
            {"name": "Route", "fields": [
                {"name": "handler", "type": "fn(Request) -> Response"}]}]}])),
        _one(_mod("m", types=[{"name": "Route", "record": True, "typeParams": [], "ctors": [
            {"name": "Route", "fields": [
                {"name": "handler", "type": "fn(Request) -> Response !io"}]}]}])),
        ["## Breaking (1)", "",
         "- `u` `m`: type `Route`: constructor `Route` field `handler` "
         "**EFFECT ROW EXPANDED** (+!io)",
         "    - was: `fn(Request) -> Response`",
         "    - now: `fn(Request) -> Response !io`"],
    ),
    (
        # The case the whole design is built around: source order is not
        # stable, so a reordered snapshot is the same snapshot.
        "no-op reorder",
        _snap({"u": _unit(
            _mod("a", fns=[_fn("one", "fn one() -> Int"), _fn("two", "fn two() -> Int")],
                 impls=["Eq[A]", "Show[A]"]),
            _mod("b", fns=[_fn("three", "fn three() -> Int")]))}),
        _snap({"u": _unit(
            _mod("b", fns=[_fn("three", "fn three() -> Int")]),
            _mod("a", fns=[_fn("two", "fn two() -> Int"), _fn("one", "fn one() -> Int")],
                 impls=["Show[A]", "Eq[A]"]))}),
        [],
    ),
    (
        # 0f94836's shape: `sig_render` began printing the effect binders it
        # had always left out. 21 signatures moved, nothing meant anything
        # different. This must stay empty for as long as the renderer is
        # allowed to change, which is the reason the comparison is on atoms.
        "renderer started printing effect binders (0f94836)",
        _one(_mod("m", fns=[_fn("map", _FN_MAP_OLD)])),
        _one(_mod("m", fns=[_fn("map", _FN_MAP_NEW)])),
        [],
    ),
)

# Inputs the loader must refuse. An empty report is the normal output of this
# script, so every way of producing one by accident has to be an exception
# instead -- otherwise "no API change" and "the snapshot never parsed" are the
# same green.
MUTANTS = (
    ("not an object", "[]"),
    ("truncated JSON", '{"schema": 1, "units": {'),
    ("unknown schema", '{"schema": 99, "units": {"u": {"modules": []}}}'),
    ("no units key", '{"schema": 1, "toolchain": "1.0.0"}'),
    ("units empty", '{"schema": 1, "units": {}}'),
    ("unit is not an object", '{"schema": 1, "units": {"u": 3}}'),
    ("modules is not a list", '{"schema": 1, "units": {"u": {"modules": {}}}}'),
    ("module without a path", '{"schema": 1, "units": {"u": {"modules": [{"fns": []}]}}}'),
    ("module listed twice",
     '{"schema": 1, "units": {"u": {"modules": [{"path": "m"}, {"path": "m"}]}}}'),
    ("entry without a name",
     '{"schema": 1, "units": {"u": {"modules": [{"path": "m", "fns": [{"sig": "x"}]}]}}}'),
    ("entry named twice",
     '{"schema": 1, "units": {"u": {"modules": [{"path": "m", "fns": ['
     '{"name": "a", "sig": "fn a()"}, {"name": "a", "sig": "fn a()"}]}]}}}'),
    ("impls is not a list",
     '{"schema": 1, "units": {"u": {"modules": [{"path": "m", "impls": 7}]}}}'),
)


def self_test(verbose: bool = True) -> int:
    failures = []
    for label, old, new, expected in GOLDEN:
        got = event_lines(diff(load_obj(old, "old"), load_obj(new, "new")))
        if got != expected:
            failures.append(f"golden {label!r}:\n  expected {expected}\n  got      {got}")
        elif verbose:
            print(f"  reproduced: {label}" + ("  (empty diff)" if not expected else ""))

    for label, text in MUTANTS:
        try:
            snap = json.loads(text)
        except json.JSONDecodeError:
            if verbose:
                print(f"  refused: {label}")
            continue
        try:
            load_obj(snap, "mutant")
        except DiffError:
            if verbose:
                print(f"  refused: {label}")
        else:
            failures.append(f"malformed input accepted: {label}")

    # Positive control: the loader must accept a snapshot that is merely small,
    # or "refused everything" would read as a pass above.
    try:
        load_obj(_one(_mod("m", fns=[_fn("a", "fn a() -> Int")])), "control")
    except DiffError as exc:
        failures.append(f"the clean control input was refused: {exc}")

    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print(f"selftest: {len(GOLDEN)} golden case(s) reproduced, "
          f"{len(MUTANTS)} malformed input(s) refused")
    return 0


# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("snapshots", nargs="*", metavar="SNAPSHOT",
                    help="OLD.json NEW.json, or just NEW.json for no baseline")
    ap.add_argument("-o", "--out", help="write the report here instead of stdout")
    ap.add_argument("--self-test", action="store_true",
                    help="run the golden cases and the malformed inputs, then stop")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if len(args.snapshots) not in (1, 2):
        ap.error("expected one snapshot (no baseline) or two (old, new)")

    try:
        old = load(args.snapshots[0]) if len(args.snapshots) == 2 else None
        new = load(args.snapshots[-1])
        text = report(old, new)
    except DiffError as exc:
        print(f"api-diff: {exc}", file=sys.stderr)
        return 1

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"OK: report -> {args.out}")
    else:
        sys.stdout.write(text)

    # Every run, not only `--self-test`: the release step runs this script once
    # and that run is where the golden cases have to be executed, since there is
    # no gates job for them (issue #29 asks for a release step, not a gate).
    return self_test(verbose=False)


if __name__ == "__main__":
    sys.exit(main())
