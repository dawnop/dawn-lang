#!/usr/bin/env python3
"""Observe real checker reads without claiming complete dependency coverage.

Mutants alter the recording sites and captured facts, not the owning tests.
Compilation/link failures are never evidence that an observation was kept.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    variants = [
        ("checker", "qualified-recording", "Some(_) -> Cx { ..cx, function_reads: semantic_reads.qualified(cx.function_reads, qualifier, name, answer) }", "Some(_) -> cx"),
        ("checker", "alias-recording", "Some(_) -> Cx { ..cx, function_reads: semantic_reads.module_alias(cx.function_reads, name, path) }", "Some(_) -> cx"),
        ("checker", "qualified-value", "let (field_cx, answer) = qual_fn_read(cx, target, fname)", "let (_, answer) = qual_fn_read(cx, target, fname)\n      let field_cx = cx"),
        ("checker", "qualified-expectation", "let (next, answer) = qual_fn_read(cx, target, name)\n      match answer", "let (_, answer) = qual_fn_read(cx, target, name)\n      let next = cx\n      match answer"),
        ("checker", "qualified-call-decision", "let (next, answer) = module_fn_read(cx, rname, name)", "let (_, answer) = module_fn_read(cx, rname, name)\n          let next = cx"),
        ("checker", "qualified-partial", "(next, answer != None)\n    }", "(cx, answer != None)\n    }"),
        ("checker", "qualified-argument", "let (next, answer) = accepts_partial_expected_read(cx1, a)\n          cx1 = next", "let (next, answer) = accepts_partial_expected_read(cx1, a)\n          cx1 = cx1"),
        ("checker", "qualified-call", "let (next, answer) = module_fn_read(cx1, al, name)\n  cx1 = next", "let (next, answer) = module_fn_read(cx1, al, name)\n  cx1 = cx1"),
        ("checker", "qualified-apply", "let (next, is_alias) = module_alias_receiver_read(cx, recv)\n          cx = next", "let (next, is_alias) = module_alias_receiver_read(cx, recv)\n          cx = cx"),
        ("checker", "alias-shadow", "if lookup(cx, alias_name) != None { return (cx, false) }", "if false { return (cx, false) }"),
        ("semantic_reads", "qualified-reference", "Some(sig) -> Some(signature(sig)?)", "Some(sig) -> Some(sig)"),
        ("semantic_reads", "qualified-identity", "QualifiedFunction(qualifier, NamedFunctionRead { name: read.name, answer: answer })", "QualifiedFunction(\"wrong\", NamedFunctionRead { name: read.name, answer: answer })"),
        ("semantic_reads", "alias-path", "ModuleAlias(qualifier, path) -> ModuleAlias(qualifier, path)", "ModuleAlias(qualifier, path) -> ModuleAlias(qualifier, None)"),
        ("checker", "qualifier-alternative", "let (next, answer) = lookup_fn_sig_read(cx, q)", "let next = cx\n  let answer = lookup_fn_sig(cx, q)"),
        ("checker", "expectation-value", "let (next, answer) = lookup_fn_sig_read(cx, name)", "let next = cx\n      let answer = lookup_fn_sig(cx, name)"),
        ("checker", "expectation-call", "let (next, answer) = lookup_fn_sig_read(cx, callee)", "let next = cx\n          let answer = lookup_fn_sig(cx, callee)"),
        ("checker", "expectation-entry", "Some(t) -> check_expr_at(next, e, Some(t))\n    None -> check_expr_at(next, e, expected)", "Some(t) -> check_expr_at(cx, e, Some(t))\n    None -> check_expr_at(cx, e, expected)"),
        ("checker", "argument-decision", "let (next, answer) = needs_expected_read(cx1, a)\n        cx1 = next", "let (next, answer) = needs_expected_read(cx1, a)\n        cx1 = cx1"),
        ("checker", "recording", "Some(_) -> Cx { ..cx, function_reads: semantic_reads.record(cx.function_reads, name, answer) }", "Some(_) -> cx"),
        ("checker", "function-value", "let (cx2, answer) = lookup_fn_sig_read(cx1, name)", "let cx2 = cx1\n      let answer = lookup_fn_sig(cx1, name)"),
        ("checker", "direct-call", "let (next, answer) = lookup_fn_sig_read(cx1, callee)", "let next = cx1\n      let answer = lookup_fn_sig(cx1, callee)"),
        ("checker", "field-ambiguity", "let (next, answer) = lookup_fn_sig_read(cx1, name)", "let next = cx1\n                let answer = lookup_fn_sig(cx1, name)"),
        ("semantic_reads", "negative-answer", "Some(entries) -> Some(entries ++ [FunctionAnswer(NamedFunctionRead { name: name, answer: answer })])", "Some(entries) -> if answer == None { Some(entries) } else { Some(entries ++ [FunctionAnswer(NamedFunctionRead { name: name, answer: answer })]) }"),
        ("checker", "candidate-qualifier", "let (next, pool) = fn_pool_read(cx)", "let next = cx\n  let pool = fn_pool(cx)"),
        ("checker", "candidate-value", "let (cx3, pool) = fn_pool_read(cx2)", "let cx3 = cx2\n          let pool = fn_pool(cx2)"),
        ("checker", "candidate-assignment", "let (next, pool) = fn_pool_read(cx1)", "let next = cx1\n          let pool = fn_pool(cx1)"),
        ("checker", "candidate-call", "let (cxb, pool) = fn_pool_read(cxa)", "let cxb = cxa\n      let pool = fn_pool(cxa)"),
        ("semantic_reads", "candidate-answer", "Some(entries) -> Some(entries ++ [FunctionCandidates(names)])", "Some(entries) -> Some(entries)"),
        ("semantic_reads", "candidate-order", "Some(entries) -> Some(entries ++ [FunctionCandidates(names)])", "Some(entries) -> Some(entries ++ [FunctionCandidates(list.reverse(names))])"),
        ("semantic_reads", "candidate-projection", "FunctionCandidates(names) -> FunctionCandidates(names)", "FunctionCandidates(names) -> FunctionCandidates([])"),
        ("semantic_reads", "read-suffix", "Some(Some(list.drop(entries, len(prefix))))", "Some(Some(entries))"),
        ("semantic_reads", "read-reference", "Some(s) -> Some(signature(s)?)", "Some(s) -> Some(s)"),
        ("header_product", "header-invariant", "a.function_reads == b.function_reads", "true"),
    ]
    sources = {name: (ROOT / "selfhost/src/check" / (name + ".dawn")).read_text()
               for name in ("checker", "semantic_reads", "header_product")}
    subjects = [(module, "positive", source) for module, source in sources.items()]
    subjects += [(module, name, edit(sources[module], old, new)) for module, name, old, new in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-function-reads-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        for module, name, source in subjects:
            target = root / "selfhost/src/check" / (module + ".dawn")
            target.write_text(source)
            status, output = run("test", target)
            target.write_text(sources[module])
            if name == "positive":
                if status:
                    raise RuntimeError("Positive " + module + " failed\n" + output)
            elif not status or not re.search(r"^FAIL\s+(?:check/\w+ :: )?(?:function reads|semantic reads|header product) [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: function reads " + module + " " + name, flush=True)
    print(f"OK: function reads and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
