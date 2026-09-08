#!/usr/bin/env python3
"""Keep export observations at real consumers and preserve reference domains.

Corrupt only production reads/projection. A compilation or linkage failure
is not evidence that a missing export dependency was detected.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    # Local constructors now share the inner projection expression. Anchor the
    # qualified arm so these controls still corrupt only export dependencies.
    constructor_projection = """QualifiedConstructor(qualifier, name, answer) -> {
            let moved_answer = match answer {
              None -> None
              Some(pair) -> { let (adt, slot) = pair
                Some((nominal(adt)?, slot))"""
    variants = [
        ("checker", "pattern-presence", "let (presence_cx, _) = export_presence_read(cx, q)", "let (discarded, _) = export_presence_read(cx, q)\n      let presence_cx = cx"),
        ("checker", "pattern-constructor", "let (pattern_cx, constructor) = qual_ctor_key_read(presence_cx, q, cname)", "let (discarded, constructor) = qual_ctor_key_read(presence_cx, q, cname)\n          let pattern_cx = presence_cx"),
        ("checker", "pattern-diagnostic", "semantic_reads.ConstructorDiagnostic, q, cname, Some(diagnostic)", "semantic_reads.ConstructorDiagnostic, q, cname, None"),
        ("checker", "pattern-diagnostic-kind", "semantic_reads.ConstructorDiagnostic, q, cname, Some(diagnostic)", "semantic_reads.ValueDiagnostic, q, cname, Some(diagnostic)"),
        ("checker", "refutability-let", "cx1 = let_read_cx", "cx1 = cx1"),
        ("checker", "refutability-for", "cx1 = for_read_cx", "cx1 = cx1"),
        ("checker", "refutability-context", "let (start, key_answer) = qual_ctor_key_read(cx, q, cname)\n      var next = start", "let (start, key_answer) = qual_ctor_key_read(cx, q, cname)\n      var next = cx"),
        ("checker", "refutability-tuple", "let (observed, answer) = refutable_span_read(next, e)\n        next = observed", "let (observed, answer) = refutable_span_read(next, e)\n        next = next"),
        ("checker", "constant-consumer", "field_cx = const_cx", "field_cx = field_cx"),
        ("checker", "constructor-value", "field_cx = ctor_cx", "field_cx = field_cx"),
        ("checker", "constructor-apply", "let (next, constructor) = qual_ctor_read(cx, recv, fname)\n      cx = next", "let (next, constructor) = qual_ctor_read(cx, recv, fname)\n      cx = cx"),
        ("checker", "value-diagnostic", "scope_cx = diagnostic_cx", "scope_cx = scope_cx"),
        ("checker", "function-diagnostic", "cx1 = diagnostic_cx", "cx1 = cx1"),
        ("checker", "presence-consumer", "let (next, present) = export_presence_read(cx1, rname)\n        cx1 = next", "let (next, present) = export_presence_read(cx1, rname)\n        cx1 = cx1"),
        ("checker", "constant-answer", "semantic_reads.QualifiedConstant(alias_name, fname, answer)", "semantic_reads.QualifiedConstant(alias_name, fname, None)"),
        ("checker", "constructor-answer", "semantic_reads.QualifiedConstructor(alias_name, fname, answer)", "semantic_reads.QualifiedConstructor(alias_name, fname, None)"),
        ("checker", "value-hint-answer", "semantic_reads.ExportDiagnosticAnswer(semantic_reads.ValueDiagnostic, q, name, answer)", "semantic_reads.ExportDiagnosticAnswer(semantic_reads.ValueDiagnostic, q, name, None)"),
        ("checker", "function-hint-answer", "semantic_reads.ExportDiagnosticAnswer(semantic_reads.FunctionDiagnostic, q, name, answer)", "semantic_reads.ExportDiagnosticAnswer(semantic_reads.FunctionDiagnostic, q, name, None)"),
        ("semantic_reads", "observation", "Some(entries) -> Some(entries ++ [fact])", "Some(entries) -> Some(entries)"),
        ("semantic_reads", "constant-type", "Some((owner, type_value(ty)?))", "Some((owner, ty))"),
        ("semantic_reads", "constructor-id", constructor_projection, constructor_projection.replace("Some((nominal(adt)?, slot))", "Some((adt, slot))")),
        ("semantic_reads", "constructor-slot", constructor_projection, constructor_projection.replace("Some((nominal(adt)?, slot))", "Some((nominal(adt)?, nominal(slot)?))")),
        ("semantic_reads", "presence-answer", "ExportPresence(qualifier, present) -> ExportPresence(qualifier, present)", "ExportPresence(qualifier, present) -> ExportPresence(qualifier, not present)"),
        ("semantic_reads", "diagnostic-kind", "ExportDiagnosticAnswer(kind, qualifier, name, answer) -> ExportDiagnosticAnswer(kind, qualifier, name, answer)", "ExportDiagnosticAnswer(kind, qualifier, name, answer) -> ExportDiagnosticAnswer(FunctionDiagnostic, qualifier, name, answer)"),
        ("body_product", "constant-domain", "t => relocate.ty(v.ids, t), id => relocate.nominal(v.ids, id)", "t => Some(t), id => relocate.nominal(v.ids, id)"),
        ("body_product", "constructor-domain", "t => relocate.ty(v.ids, t), id => relocate.nominal(v.ids, id)", "t => relocate.ty(v.ids, t), id => Some(id)"),
    ]
    sources = {name: (ROOT / "selfhost/src/check" / (name + ".dawn")).read_text()
               for name in ("checker", "semantic_reads", "body_product")}
    subjects = [(module, "positive", source) for module, source in sources.items()]
    subjects += [(module, name, edit(sources[module], old, new)) for module, name, old, new in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-export-reads-") as temp:
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
            elif not status or not re.search(r"^FAIL\s+(?:check/\w+ :: )?(?:export reads|semantic reads|body product) [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: export reads " + module + " " + name, flush=True)
    print(f"OK: export reads and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
