#!/usr/bin/env python3
"""Prove each query-observer guard with an independently compiled mutant.

Only private copies are changed. The shared Jsig module has no project imports,
so these small subjects test the actual implementation without rebuilding a
compiler per mutation. The production compiler is built once by bin/dawn.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DAWN = os.environ.get("DAWN_BIN", str(ROOT / "bin/dawn"))
SOURCE = ROOT / "selfhost/src/check/jsig.dawn"
OWNER = "query observation precedes every hook including a failing query"
GUARD_OWNER = "a refused probe cannot claim an enabled oracle is query free"
HOOKS = (
    "find_class", "class_info", "methods_of", "ctors_of",
    "static_fields_of", "is_assignable", "sam_of", "component_of",
)


def run(*args):
    result = subprocess.run(
        [DAWN, *map(str, args)], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
    )
    return result.returncode, result.stdout


def require_green(*args):
    status, output = run(*args)
    if status:
        raise RuntimeError(f"positive/build failed: {args}\n{output}")
    return output


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise RuntimeError(f"query observer mutation anchor drifted: {before!r}")
    return text.replace(before, after)


def main():
    original = SOURCE.read_text()
    mutations = []
    for hook in HOOKS:
        args = "(sup, sub)" if hook == "is_assignable" else "name"
        before = f"    {hook}: {args} => {{\n      note()\n"
        after = f"    {hook}: {args} => {{\n"
        mutations.append((hook, replace_once(original, before, after), OWNER))
    guard = '  if js.on { panic("jsig: an enabled oracle needs a host query probe") }\n'
    mutations.append(("enabled-refusal", replace_once(original, guard, ""), GUARD_OWNER))

    # Validate all anchors before doing any compiler work. A source rename is
    # a harness failure, never evidence that the corresponding mutant is red.
    with tempfile.TemporaryDirectory(prefix="dawn-query-probe-") as temp:
        root = Path(temp)
        positive = root / "positive.dawn"
        positive.write_text(original)
        output = require_green("test", positive)
        if OWNER not in output or GUARD_OWNER not in output:
            raise RuntimeError("positive subject did not run both owning tests")
        for name, source, owner in mutations:
            subject = root / (name.replace("-", "_") + ".dawn")
            subject.write_text(source)
            require_green("check", subject)
            status, output = run("test", subject)
            if not status or not re.search(r"^FAIL\s+.*" + re.escape(owner), output, re.M):
                raise RuntimeError(f"mutant {name} missed its owning assertion\n{output}")
            print(f"OK: compiling mutant {name} rejected by its owning test", flush=True)
    print("OK: query probe positive and 9 compiling negative controls")


if __name__ == "__main__":
    main()
