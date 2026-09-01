#!/usr/bin/env python3
"""One machine-readable snapshot of everything this tree publishes as public API.

`dawn doc` already knows the answer -- it renders every public signature with
its effect row (`selfhost/src/doc.dawn`, `sig_render` in
`selfhost/src/check/types.dawn`) and it is deterministic. What was missing is a
single file per release holding *all* of it, so that two releases can be
compared by a machine instead of by a reader. `scripts/api-diff.py` consumes
this file; the release workflow publishes it beside the jar.

What goes in, and why the shape is ours rather than `dawn doc`'s:

  * one entry per unit -- `std` plus every directory under `packages/` -- so
    the stdlib and the packages are compared by the same code. A package's
    entry carries the version its `dawn.toml` declares; the file as a whole
    carries the toolchain VERSION.
  * dependency modules are dropped. `dawn doc packages/tea-dom` reports
    `json2/value` and `tea_core/tree` alongside `dsl` and `wire`, because it
    documents what the package compiles against. In a *published surface*
    snapshot those modules belong to their own unit, and leaving them in would
    report one change in json2 eight times over. The filter is the package's
    own `src/**/*.dawn` relative paths, which is exactly the set `dawn doc`
    prints unprefixed.
  * builtins and prelude traits become synthetic modules (`<builtins>/io`,
    `<prelude>`). `dawn doc --stdlib` returns them outside `modules`, and they
    are surface too: `println` is as public as anything in `std/list`, and a
    builtin acquiring an effect is precisely the change this whole line of
    work exists to show. The angle brackets cannot collide with a module path.
  * doc comments are dropped. This is an API snapshot, not a documentation
    archive: prose churns every release, it would dominate both the file size
    and any diff of two files, and `api-diff.py` deliberately never reads it.

Unknown keys are an error, not a silent drop. If `dawn doc` grows a field --
another kind of declaration, another attribute on a signature -- a snapshot
that quietly ignored it would keep passing while the surface it claims to
cover stopped being covered. That failure mode is invisible from the outside,
so the script refuses instead.

    scripts/api-snapshot.py [-o FILE] [--dawn CMD] [--root DIR]

`--dawn` takes a whole command line, so a release can point at the jar it just
built (`--dawn 'java -Xss512m -jar dawn-selfhost.jar'`) instead of at
`./bin/dawn`, which would rebuild the toolchain from the seed.
"""

import argparse
import glob
import json
import os
import shlex
import subprocess
import sys

SCHEMA = 1

# Every key each level of `dawn doc` output may carry, and which of them this
# snapshot keeps. Anything outside the union is a surface this file would be
# blind to, and the script stops rather than pretend otherwise.
DOC_KEYS = {"modules", "groups", "traits"}
MODULE_KEYS = {"path", "doc", "fns", "types", "consts", "traits", "effects", "impls"}
ENTRY_KEYS = {
    "fns": {"name", "sig", "doc"},
    "consts": {"name", "type", "doc"},
    "types": {"name", "record", "typeParams", "ctors", "doc"},
    "traits": {"name", "typeParam", "assoc", "effectAssoc", "methods", "doc"},
    "effects": {"name", "ops", "doc"},
}
CTOR_KEYS = {"name", "fields"}
FIELD_KEYS = {"name", "type"}
ASSOC_KEYS = {"name", "doc"}
EFFECT_ASSOC_KEYS = {"name", "default", "doc"}
METHOD_KEYS = {"name", "sig", "hasDefault"}
OP_KEYS = {"name", "sig", "doc"}
GROUP_KEYS = {"name", "fns"}

KINDS = ("fns", "types", "consts", "traits", "effects")


class SnapshotError(Exception):
    """The tree, or `dawn doc`, said something this script will not guess at."""


def check_keys(obj: dict, allowed: set, where: str) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise SnapshotError(f"{where}: unknown key(s) from dawn doc: {', '.join(unknown)}")


def strip_doc(obj: dict, allowed: set, where: str) -> dict:
    check_keys(obj, allowed, where)
    return {k: v for k, v in obj.items() if k != "doc"}


def assoc_name(assoc, where: str) -> str:
    if isinstance(assoc, str):
        return assoc
    if isinstance(assoc, dict):
        name = strip_doc(assoc, ASSOC_KEYS, where).get("name")
        if isinstance(name, str):
            return name
    raise SnapshotError(f"{where}: an associated type has no name")


def clean_entry(kind: str, entry: dict, where: str) -> dict:
    out = strip_doc(entry, ENTRY_KEYS[kind], where)
    name = out.get("name")
    if not isinstance(name, str):
        raise SnapshotError(f"{where}: a {kind} entry has no name")
    at = f"{where}: {kind[:-1]} {name!r}"
    if kind == "types":
        ctors = []
        for ctor in out.get("ctors", []):
            ctor = strip_doc(ctor, CTOR_KEYS, at)
            ctor["fields"] = [strip_doc(f, FIELD_KEYS, at) for f in ctor.get("fields", [])]
            ctors.append(ctor)
        out["ctors"] = ctors
    elif kind == "traits":
        # `assoc` has two spellings in `dawn doc`: a module's traits carry
        # `{"name": ..., "doc": ...}` (doc.dawn:357-364) and the prelude's
        # carry the bare name (doc.dawn:757-760). The only thing the object
        # form adds is the doc this snapshot drops, so both become the name.
        out["assoc"] = [assoc_name(a, at) for a in out.get("assoc", [])]
        if "effectAssoc" in out:
            out["effectAssoc"] = [
                strip_doc(a, EFFECT_ASSOC_KEYS, at) for a in out["effectAssoc"]
            ]
        out["methods"] = [strip_doc(m, METHOD_KEYS, at) for m in out.get("methods", [])]
    elif kind == "effects":
        out["ops"] = [strip_doc(o, OP_KEYS, at) for o in out.get("ops", [])]
    return out


def clean_module(module: dict, path: str, where: str) -> dict:
    out = {"path": path}
    for kind in KINDS:
        out[kind] = [clean_entry(kind, e, f"{where} {path}") for e in module.get(kind, [])]
    out["impls"] = sorted(module.get("impls", []))
    return out


def normalize(doc: dict, own: "set[str] | None", where: str) -> list:
    """`dawn doc` output as this snapshot's uniform module list."""
    check_keys(doc, DOC_KEYS, where)
    modules = []
    for module in doc.get("modules", []):
        check_keys(module, MODULE_KEYS, where)
        path = module.get("path")
        if not isinstance(path, str):
            raise SnapshotError(f"{where}: a module has no path")
        if own is not None and path not in own:
            continue  # a dependency's module; it belongs to the dependency's unit
        modules.append(clean_module(module, path, where))
    for group in doc.get("groups", []):
        check_keys(group, GROUP_KEYS, where)
        modules.append(clean_module({"fns": group["fns"]}, f"<builtins>/{group['name']}", where))
    if doc.get("traits"):
        modules.append(clean_module({"traits": doc["traits"]}, "<prelude>", where))
    modules.sort(key=lambda m: m["path"])
    return modules


def run_doc(dawn: list, args: list, root: str) -> dict:
    cmd = dawn + ["doc"] + args
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
    if proc.returncode != 0:
        raise SnapshotError(
            f"{' '.join(cmd)} exited {proc.returncode}\n{proc.stderr.strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"{' '.join(cmd)} did not print JSON: {exc}") from exc


def manifest(path: str) -> dict:
    """`name` and `version` from a package manifest's root table.

    Deliberately not a TOML parser and deliberately not a regex over the whole
    file: `[deps]` entries are `key = "value"` too, and reading a name out of
    the wrong table is the kind of mistake that produces a plausible snapshot.
    """
    fields = {}
    section = ""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("["):
                section = line
                continue
            if section or "=" not in line:
                continue
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip().strip('"')
    for key in ("name", "version"):
        if key not in fields:
            raise SnapshotError(f"{path}: root table declares no {key}")
    return fields


def toolchain_version(root: str) -> str:
    path = os.path.join(root, "selfhost", "src", "version.dawn")
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("pub const VERSION"):
                return line.split('"')[1]
    raise SnapshotError(f"{path}: no VERSION declaration")


def snapshot(root: str, dawn: list) -> dict:
    units = {
        "std": {
            "version": toolchain_version(root),
            "modules": normalize(run_doc(dawn, ["--stdlib"], root), None, "std"),
        }
    }
    for manifest_path in sorted(glob.glob(os.path.join(root, "packages", "*", "dawn.toml"))):
        pkg = os.path.dirname(manifest_path)
        rel = os.path.relpath(pkg, root)
        fields = manifest(manifest_path)
        src = os.path.join(pkg, "src")
        own = {
            os.path.splitext(os.path.relpath(f, src))[0].replace(os.sep, "/")
            for f in glob.glob(os.path.join(src, "**", "*.dawn"), recursive=True)
        }
        if not own:
            raise SnapshotError(f"{rel}: no sources under src/")
        name = fields["name"]
        if name in units:
            raise SnapshotError(f"{rel}: unit name {name!r} is already taken")
        units[name] = {
            "version": fields["version"],
            "modules": normalize(run_doc(dawn, [rel], root), own, name),
        }
    return {"schema": SCHEMA, "toolchain": units["std"]["version"], "units": units}


CLEAN_DOC = {
    "modules": [{
        "path": "m",
        "doc": "prose that must not reach the snapshot",
        "fns": [{"name": "f", "sig": "fn f() -> Int !io", "doc": "prose"}],
        "types": [{"name": "T", "record": True, "typeParams": [], "doc": "prose",
                   "ctors": [{"name": "T", "fields": [{"name": "a", "type": "Int"}]}]}],
        "traits": [{"name": "Tr", "typeParam": "W", "assoc": [{"name": "It", "doc": None}],
                    "methods": [{"name": "go", "sig": "fn go[W: Tr](w: W) -> W",
                                 "hasDefault": False}]}],
        "impls": ["Show[T]"],
    }, {
        "path": "dep/mod",
        "fns": [{"name": "g", "sig": "fn g() -> Int"}],
    }],
    "groups": [{"name": "io", "fns": [{"name": "println",
                                       "sig": "fn println(s: String) -> Unit !io"}]}],
    "traits": [{"name": "Eq", "typeParam": "T", "assoc": ["Item"],
                "methods": [{"name": "eq", "sig": "fn eq[T: Eq](a: T, b: T) -> Bool",
                             "hasDefault": False}]}],
}


def self_test(verbose: bool = True) -> int:
    """The unknown-key guard has to be seen refusing something.

    Its whole job is to fail on a `dawn doc` this script has never seen, which
    is a shape nobody can produce on purpose today. Without these it is a
    branch that has never once been taken, and one of those is indistinguishable
    from a branch that cannot be taken.
    """
    failures = []
    modules = normalize(CLEAN_DOC, {"m"}, "control")
    paths = [m["path"] for m in modules]
    for want, why in (
        (paths == ["<builtins>/io", "<prelude>", "m"], f"unexpected modules {paths}"),
        ("doc" not in json.dumps(modules), "a doc comment survived into the snapshot"),
        ("dep/mod" not in paths, "a dependency's module was not filtered out"),
        (modules[2]["traits"][0]["assoc"] == ["It"], "the object assoc form was not flattened"),
        (modules[1]["traits"][0]["assoc"] == ["Item"], "the string assoc form was not kept"),
    ):
        if not want:
            failures.append(why)

    def mutate(path, mutation):
        doc = json.loads(json.dumps(CLEAN_DOC))
        node = doc
        for step in path:
            node = node[step]
        mutation(node)
        return doc

    mutants = (
        ("an unknown key at the top level",
         mutate([], lambda d: d.update({"macros": []}))),
        ("an unknown key on a module",
         mutate(["modules", 0], lambda m: m.update({"aliases": []}))),
        ("an unknown key on a function",
         mutate(["modules", 0, "fns", 0], lambda f: f.update({"inline": True}))),
        ("an unknown key on a constructor field",
         mutate(["modules", 0, "types", 0, "ctors", 0, "fields", 0],
                lambda f: f.update({"mutable": True}))),
        ("a module with no path",
         mutate(["modules", 0], lambda m: m.pop("path"))),
        ("a function with no name",
         mutate(["modules", 0, "fns", 0], lambda f: f.pop("name"))),
        ("an associated type that is neither a name nor an object",
         mutate(["modules", 0, "traits", 0], lambda t: t.update({"assoc": [7]}))),
    )
    for label, doc in mutants:
        try:
            normalize(doc, {"m"}, "mutant")
        except SnapshotError:
            if verbose:
                print(f"  refused: {label}")
        else:
            failures.append(f"mutant not caught: {label}")

    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print(f"selftest: {len(mutants)} mutant(s) refused, the clean shape accepted")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", help="write here instead of stdout")
    ap.add_argument("--self-test", action="store_true",
                    help="run the unknown-key mutants and stop")
    ap.add_argument("--dawn", default="./bin/dawn",
                    help="the toolchain command line (default: ./bin/dawn)")
    ap.add_argument("--root", default=os.path.join(os.path.dirname(__file__), ".."),
                    help="repository root (default: the one holding this script)")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    root = os.path.abspath(args.root)
    try:
        snap = snapshot(root, shlex.split(args.dawn))
    except SnapshotError as exc:
        print(f"api-snapshot: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(snap, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        modules = sum(len(u["modules"]) for u in snap["units"].values())
        print(f"OK: {len(snap['units'])} unit(s), {modules} module(s), "
              f"{len(text)} bytes -> {args.out}")
    else:
        sys.stdout.write(text)
        return 0  # stdout is the snapshot; keep the self-test's chatter out of it
    return self_test(verbose=False)


if __name__ == "__main__":
    sys.exit(main())
