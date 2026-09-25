#!/usr/bin/env python3
"""Exercise canonical bounded entry proofs without widening replay admission.

Every negative subject must compile and fail its precise forged-input owner.
Compiler/link failures and unrelated runtime failures are never evidence.
"""
import argparse
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from cold import ROOT, HERE, edit, install_probe, run


def owning_failure(status, output, owner):
    """Accept only the observed reflection wrapper and one precise panic stack."""
    if status != 1:
        return False
    lines = output.strip().splitlines()
    expected = "Caused by: dawn.rt.PanicError: " + owner
    if not lines or lines[0] != 'Exception in thread "main" java.lang.reflect.InvocationTargetException':
        return False
    if lines.count(expected) != 1:
        return False
    return all(line == expected or re.fullmatch(r"\s+at [\w.$/<>]+\([^\r\n]*\)", line)
               or re.fullmatch(r"\s+\.\.\. \d+ more", line) for line in lines[1:])


def classifier_selftest():
    owner = "bounded entry proof accepted dictionary metadata"
    stack = ('Exception in thread "main" java.lang.reflect.InvocationTargetException\n'
             '\tat java.base/java.lang.reflect.Method.invoke(Method.java:580)\n'
             'Caused by: dawn.rt.PanicError: ' + owner + '\n'
             '\tat dawn$pkg$selfhost.contract.reference.refused(Unknown Source)\n\t... 2 more\n')
    assert owning_failure(1, stack, owner)
    for status, output in [
        (0, stack), (-9, stack), (124, stack), (2, stack),
        (1, stack.replace(owner, "bounded entry proof accepted wrong owner")),
        (1, stack + 'Caused by: dawn.rt.PanicError: another failure\n'),
        (1, stack + 'java.lang.LinkageError: broken\n'),
        (1, stack + 'java.lang.VerifyError: broken\n'),
        (1, stack + 'Exception in thread "worker" java.lang.RuntimeException\n'),
        (1, stack + 'timeout\n'),
        (1, 'Caused by: dawn.rt.PanicError: ' + owner + '\n'),
    ]:
        assert not owning_failure(status, output, owner), (status, output)
    print("OK: bounded entry classifier rejects wrong owner, extra failures, signals and timeouts", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    classifier_selftest()
    if args.self_test:
        return
    started = time.monotonic()
    source = (ROOT / "selfhost/src/check/function_entry_proof.dawn").read_text()
    variants = [
        ("symbol-metadata", "map.get(symbols, id) != map.get(entry.cx.syms, id)", "false", "dictionary metadata"),
        ("parameter-order", "product.tree.param_syms != entry.parameters", "false", "parameter order"),
        ("dictionary-frame", "product.frame != final_frame", "false", "dictionary frame"),
        ("owner", "product.owner_decl != candidate.owner_decl", "false", "owner identity"),
        ("slots", "product.owner_slots != slot_of(entry.cx)", "false", "allocation interval"),
        ("journal", "product.body_writes != entry.cx.body_writes", "false", "entry journal"),
        ("reads", "not entry_prefix(reads, entry_reads)", "false", "entry read prefix"),
        ("header-bounds", "map.get(candidate.current_tparam_bounds, id) != Some(signature.constraints[index])", "false", "header bounds"),
        ("written-bounds", "len(resolved.diags) != len(candidate.diags) || bounds != signature.constraints", "false", "written bounds"),
    ]
    subjects = [("positive", source, None)]
    if not args.positive_only:
        subjects += [(name, edit(source, old, new), "bounded entry proof accepted " + owner)
                     for name, old, new, owner in variants]
        subjects.append(("body-check", edit(source,
            "product: Product) -> Option[Proof] = {\n",
            "product: Product) -> Option[Proof] !io = {\n  let _ = checker.check_fn(candidate, declaration, signature)\n"),
            "bounded entry proof executed body checker"))
    checker = (ROOT / "selfhost/src/check/checker.dawn").read_text()
    for name in ("check_fn", "check_fn_inferred", "check_const_init", "check_trait_default", "check_test"):
        checker, count = re.subn(r"(pub\(pkg\) fn " + name + r"\([^{}]*?!io = \{\n)",
                                 r"\1  GenericTrace.enter()\n", checker)
        if count != 1:
            raise RuntimeError("Bounded entry counter anchor drifted: " + name)
    checker = 'use java "contract.GenericTrace"\n' + checker
    with tempfile.TemporaryDirectory(prefix="dawn-bounded-entry-") as temp:
        root = Path(temp)
        classes = root / "classes"
        classes.mkdir()
        subprocess.run(["javac", "--release", "21", "-d", str(classes),
                        *[str(HERE / name) for name in
                          ("SemanticSnapshot.java", "GenericTrace.java", "BoundedEntryProofTrace.java")]], check=True)
        oracle = root / "trace.jar"
        subprocess.run(["jar", "cf", str(oracle), "-C", str(classes), "."], check=True)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        (root / "selfhost/src/check/checker.dawn").write_text(checker)
        text = (HERE / "generic-trace.dawn.txt").read_text()
        for old, new in [
            (".{ModuleBodies}", ".{ModuleBodies, ModuleHeaders, BodyExecutor}"),
            (".{cx_new, slots_of}", ".{Cx, Frame, cx_new, slots_of}"),
            (".{Product}", ".{Product, BodyProduct, Change}"),
            (".{TyVar, Sym}", ".{TyVar, Sym, Sig}"),
            (".{Key, BoundsKey, SymbolKey}", ".{Key, BoundsKey, SymbolKey, SignatureKey}"),
        ]:
            text = edit(text, old, new)
        reference = text + "\n" + (HERE / "bounded-entry-proof.dawn.txt").read_text()
        for name, subject, owner in subjects:
            # The body-check mutant adds !io to a deliberately pure API. Once
            # production admission calls that API, mutating it in place fails
            # effect checking before the runtime counter can observe anything.
            # Exercise that one mutation through a private proof-module copy;
            # keep the real admission path pure and the counter owner unchanged.
            isolated = name == "body-check"
            (root / "selfhost/src/check/function_entry_proof.dawn").write_text(source if isolated else subject)
            if isolated:
                (root / "selfhost/src/check/function_entry_probe.dawn").write_text(subject)
            fixture = install_probe(root, {"reference": edit(reference,
                'use check/function_entry_proof as proof',
                'use check/function_entry_probe as proof') if isolated else reference})
            status, output = run("build", "--cp", oracle, fixture, "-o", root / "subject.jar")
            if status:
                raise RuntimeError(f"Bounded entry {name} failed to compile\n{output}")
            result = subprocess.run(["java", "-Xss64m", "-Xmx2g", "-cp",
                                     str(oracle) + os.pathsep + str(root / "subject.jar"),
                                     "contract.BoundedEntryProofTrace"], cwd=ROOT, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            if owner is None:
                if result.returncode or "PASS: bounded entry proof 16 accepted entries, 16 full cold histories" not in result.stdout:
                    raise RuntimeError("Bounded entry positive failed\n" + result.stdout)
            else:
                if not owning_failure(result.returncode, result.stdout, owner):
                    raise RuntimeError(f"Bounded entry {name} missed {owner}\n{result.stdout}")
            print(f"OK: bounded entry {name}" + (f" -> {owner}" if owner else ""), flush=True)
    print(f"OK: bounded entry proof {len(subjects) - 1} compiling controls; elapsed={time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
