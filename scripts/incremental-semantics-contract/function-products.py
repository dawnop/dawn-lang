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
    method_title = "method products preserve impl and default owners across declaration reorder"
    value_title = "value products preserve constant visibility and separate test identities"
    path = Path("selfhost/src/check/function_product.dawn")
    original = (ROOT / path).read_text()
    mutations = [
        ("source", 'path == "" || scope.source != path', 'path == ""'),
        ("owner", "checked.cx.owner_class != Some(scope.emission_owner)", "false"),
        ("signature-name", "signature.name != syntax.name ||", "false ||"),
        ("signature-tail", "if function != len(checked.sigs) { return None }", ""),
        ("ambiguous-identity", "if map.get(locations, key) != Some((declaration, None)) { return None }", "if false { return None }"),
    ]
    method_mutations = [
        ("impl-groups", "groups = groups ++ [ImplGroup { key: parent_key, trait_name: trait_name, subject: subject, methods: group_keys }]", "groups = groups"),
        ("impl-owner", "info.owner == checked.cx.owner_class", "true"),
        ("impl-parameters", "sig.tparams != info.tparams ||", "false ||"),
        ("impl-role", "sig.is_builtin || sig.trait_id != None || sig.op_of != None", "false"),
        ("trait-default", "not method.has_default", "false"),
        ("trait-owner", "info.name != name || info.owner != checked.cx.owner_class || info.src_path != checked.cx.src_path",
         "info.name != name || info.src_path != checked.cx.src_path"),
    ]
    value_mutations = [
        ("constant-type", "if map.get(checked.cx.consts, name) != Some(declared) { return None }", ""),
        ("constant-tail", "if ci != len(checked.const_tys) { return None }", ""),
        ("constant-visibility", "ConstantHeader(key, syntax, declared, visible)", "ConstantHeader(key, syntax, declared, set.empty())"),
        ("test-role", "tests = tests ++ [key]", "tests = constants ++ [key]"),
    ]
    with tempfile.TemporaryDirectory(prefix="dawn-function-products-") as temp:
        private = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, private / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (private / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        subjects = [("positive", original, title)]
        subjects += [(name, edit(original, old, new), title) for name, old, new in mutations]
        subjects += [(name, edit(original, old, new), method_title) for name, old, new in method_mutations]
        subjects += [(name, edit(original, old, new), value_title) for name, old, new in value_mutations]
        for name, source, owner in subjects:
            (private / path).write_text(source)
            status, output = run("test", private / path)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive function products failed\n" + output)
            elif not status or not owning(output, "check/function_product", owner):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: function products " + name, flush=True)
    print(f"OK: named function/method/value headers and fifteen compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
