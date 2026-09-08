#!/usr/bin/env python3
"""Guard named header admission without weakening the ordinary error checker.

Each private mutation must compile and fail the precise owning assertion;
build failures and unrelated checker errors are not negative-control evidence.
"""
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run
from projection import owning


def main():
    started = time.monotonic()
    title = "function products bind entry signatures to stable current declarations"
    path = Path("selfhost/src/check/function_product.dawn")
    original = (ROOT / path).read_text()
    mutations = [
        ("source", 'path == "" || scope.source != path', 'path == ""'),
        ("owner", "checked.cx.owner_class != Some(scope.emission_owner)", "false"),
        ("signature-name", "signature.name != syntax.name ||", "false ||"),
        ("signature-tail", "if function != len(checked.sigs) { return None }", ""),
        ("ambiguous-identity", "if map.get(locations, key) != Some((declaration, None)) { return None }", "if false { return None }"),
    ]
    with tempfile.TemporaryDirectory(prefix="dawn-function-products-") as temp:
        private = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, private / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (private / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        subjects = [("positive", original)] + [(name, edit(original, old, new)) for name, old, new in mutations]
        for name, source in subjects:
            (private / path).write_text(source)
            status, output = run("test", private / path)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive function products failed\n" + output)
            elif not status or not owning(output, "check/function_product", title):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: function products " + name, flush=True)
    print(f"OK: named function headers and five compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
