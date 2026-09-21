#!/usr/bin/env python3
"""Run existing source mutations against in-memory files before any compiler build.

The executable mutator remains the owner of its anchors and their ordering.
Adapters describe only invocation shape, not copies of source strings. Discovery
fails closed when a new mutate.py has no adapter; generated-bytecode helpers have
explicit exclusions because their subjects do not exist in a source checkout.
"""

import argparse
import ast
import builtins
from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import re
import runpy
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = {
    "bootstrap-input-manifest-contract": ("compiler-plan/src/source.dawn",),
    "ctl-live-contract": ("runtime/c",),
    "dependency-heap-contract": ("selfhost/src/main.dawn",),
    "display-layering-contract": (".",),
    "export-surface-contract": (".",),
    "for-pattern-contract": ("selfhost",),
    "list-elems-contract": (".",),
    "lsp-workspace-contract": ("selfhost",),
    "pattern-or-contract": ("selfhost",),
    "pipe-contract": (".",),
    "range-bound-order-contract": (".",),
    "rc-contract": ("runtime/c",),
    "selfhost-bench-contract": ("scripts/selfhost-bench.py",),
    "source-loop-label-contract": (".",),
}
EXCLUSIONS = {
    "classfile-verify": "mutates generated classfile bytes, not source anchors",
    "tile-gpu-diff": "generic replacement helper; all anchor text is supplied by callers",
}
SHELL_ADAPTERS = {
    "java-target-classpath-contract": ("selfhost/src/main.dawn",
        "selfhost/src/driver/analyze.dawn", "selfhost/src/jvm/jreflect.dawn"),
    "std-version-contract": ("selfhost/src/driver/stdlib.dawn",),
}


class PreflightError(RuntimeError):
    pass


def modes(source, label):
    """Read public keys from literal registries or explicit CLI dispatch arms."""
    tree = ast.parse(source, filename=label)
    keys = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "MUTATIONS"
                for target in node.targets):
            if not isinstance(node.value, ast.Dict):
                raise PreflightError(f"{label}: MUTATIONS is no longer a literal registry")
            for key in node.value.keys:
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    raise PreflightError(f"{label}: nonliteral mutation key")
                keys.append(key.value)
        if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
                and node.left.id in {"name", "mutation"} and len(node.ops) == 1
                and isinstance(node.ops[0], (ast.Eq, ast.NotEq))
                and isinstance(node.comparators[0], ast.Constant)
                and isinstance(node.comparators[0].value, str)):
            keys.append(node.comparators[0].value)
    if not keys:
        raise PreflightError(f"{label}: no executable mutation modes found")
    return sorted(set(keys))


def shell_source(text, label):
    # Select the existing mutation block by its mode argument, not by copying
    # its contents or executing the build-heavy shell surrounding it.
    blocks = re.findall(r'(?m)^\s*python3 - "\$name"[^\n]*(?:\\\n[^\n]*)*<<\'PY\'\n(.*?)^PY$',
                        text, re.S | re.M)
    if len(blocks) != 1:
        raise PreflightError(f"{label}: expected one mutation Python block, found {len(blocks)}")
    return blocks[0]


def exercise(root, source, label, mode, arguments, overrides=None):
    """Intercept the mutator's file API; writes never reach the repository."""
    original_read = Path.read_text
    original_open = builtins.open
    original_io_open = io.open
    virtual = {root / key: value for key, value in (overrides or {}).items()}
    touched = set()
    read = set()

    def readonly_open(opener):
        def open_file(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise PreflightError(f"{label}: unsupported direct file write: {file}")
            return opener(file, mode, *args, **kwargs)
        return open_file

    def read_text(path, *args, **kwargs):
        path = path.resolve()
        read.add(path)
        return virtual[path] if path in virtual else original_read(path, *args, **kwargs)

    def write_text(path, text, *args, **kwargs):
        path = path.resolve()
        if not path.is_relative_to(root):
            raise PreflightError(f"{label}: write outside subject tree: {path}")
        virtual[path] = text
        touched.add(path)
        return len(text)

    output = io.StringIO()
    argv = [label, mode, *(str((root / arg).resolve()) for arg in arguments)]
    try:
        with patch.object(Path, "read_text", read_text), \
                patch.object(Path, "write_text", write_text), \
                patch.object(builtins, "open", readonly_open(original_open)), \
                patch.object(io, "open", readonly_open(original_io_open)), \
                patch.object(subprocess, "Popen", side_effect=PreflightError("preflight must not spawn a build")), \
                patch.object(sys, "argv", argv), redirect_stdout(output), redirect_stderr(output):
            try:
                exec(compile(source, label, "exec"), {"__name__": "__main__", "__file__": str(root / label)})
            except SystemExit as error:
                if error.code not in (None, 0):
                    raise PreflightError(str(error)) from error
        if not touched:
            raise PreflightError("mutation wrote no subject")
    except (Exception, SystemExit) as error:
        targets = ", ".join(sorted(str(path.relative_to(root)) for path in read if path.is_relative_to(root)))
        raise PreflightError(f"{label}:{mode} [{targets}]: {error}\n{output.getvalue().strip()}") from error
    return {str(path.relative_to(root)): virtual[path] for path in touched}


def check(root, overrides=None):
    root = root.resolve()
    found = {str(path.relative_to(root)) for path in (root / "scripts").rglob("mutate.py")}
    expected = {f"scripts/{name}/mutate.py" for name in ADAPTERS.keys() | EXCLUSIONS.keys()}
    if found != expected:
        raise PreflightError(f"mutator inventory drift: unregistered={sorted(found - expected)}, missing={sorted(expected - found)}")
    count = 0
    for name, arguments in ADAPTERS.items():
        label = f"scripts/{name}/mutate.py"
        source = (root / label).read_text()
        for mode in modes(source, label):
            exercise(root, source, label, mode, arguments, overrides)
            count += 1
    for name, arguments in SHELL_ADAPTERS.items():
        label = f"scripts/{name}/run.sh"
        source = shell_source((root / label).read_text(), label)
        for mode in modes(source, label):
            subject = overrides
            if name == "java-target-classpath-contract" and mode == "bypass-bracket":
                subject = dict(overrides or {})
                subject.update(exercise(root, source, label, "instrument-close", arguments, overrides))
            exercise(root, source, label, mode, arguments, subject)
            count += 1

    gm = runpy.run_path(str(root / "scripts/gate-map/gatemap.py"))
    tree = gm["Tree"](root, overrides=overrides)
    baseline = gm["Baseline"](tree)
    for mutant in gm["mutants"](baseline):
        for rel, edit in mutant.edits.items():
            try:
                edit(tree.read(rel), rel)
            except (Exception, SystemExit) as error:
                raise PreflightError(f"scripts/gate-map/gatemap.py:{mutant.name} [{rel}]: {error}") from error
            count += 1
    path = "selfhost/src/check/passes.dawn"
    hits = tree.read(path).count(gm["BUNDLED_MODULE_EXPRESSION"])
    if hits != 1:
        raise PreflightError(f"scripts/gate-map/gatemap.py:BUNDLED_MODULE_EXPRESSION [{path}]: {hits} matches, expected 1")
    reader = runpy.run_path(str(root / "scripts/builtin-decl-contract/check.py"))
    path = "selfhost/src/ir/interp.dawn"
    try:
        reader["read_comptime_rejects"](tree.read(path))
    except (Exception, SystemExit) as error:
        raise PreflightError(f"scripts/builtin-decl-contract/check.py:comptime_rejects [{path}]: {error}") from error
    return count + 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    started = time.monotonic()
    try:
        count = check(args.root)
    except (Exception, SystemExit) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"OK: {count} mutation applications/locators checked in {time.monotonic() - started:.2f}s; no build or source writes")
    for name, reason in EXCLUSIONS.items():
        print(f"NOTE: scripts/{name}/mutate.py: {reason}")
    return 0


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.exit(main())
