#!/usr/bin/env python3
"""Keep qualified type decisions observable without conflating reference domains.

The checker owns consumer assertions; the leaf read module owns projection.
Compilation failures are not accepted as evidence that a dependency was kept.
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
        # `effect-callback` is gone: relocating an effect row is the identity
        # once a binder is `identity.pack` of its declaration and its slot, so
        # a control that replaced the callback with `Some` could not be told
        # from the production code (K5). The alias and constant source
        # callbacks went with `body_product` and the replay engine
        # (2026-09-27); the recording side below is what is left.
        ("cx", "observation", "semantic_reads.observe(cx.function_reads, fact)", "cx.function_reads"),
        ("cx", "alias-header", "semantic_reads.QualifiedAliasHeader(q, name, header_answer)", "semantic_reads.QualifiedAliasHeader(q, name, None)"),
        ("cx", "alias-type-binders", "tparams: al.tparams, eparams: al.eparams,", "tparams: [], eparams: al.eparams,"),
        ("cx", "alias-effect-binders", "tparams: al.tparams, eparams: al.eparams,", "tparams: al.tparams, eparams: [],"),
        ("cx", "opaque-identity", "opaque_id: if al.is_opaque { Some(al.id) } else { None }", "opaque_id: None"),
        ("cx", "alias-target-answer", "semantic_reads.QualifiedAliasTarget(q, name, target_answer)", "semantic_reads.QualifiedAliasTarget(q, name, None)"),
        ("cx", "alias-target-consumer", "earg_subst(target_cx, al.eparams, eargs)", "earg_subst(cxe, al.eparams, eargs)"),
        ("cx", "nominal-name", "semantic_reads.NominalTypeName(Some(q), name, nominal_answer)", "semantic_reads.NominalTypeName(Some(q), name, None)"),
        ("cx", "nominal-shape", "let shape_cx = observe_type_read(cx, semantic_reads.NominalTypeShape(aid, info.name,\n        len(info.tparams), info.eparams, info.is_record))", "let shape_cx = observe_type_read(cx, semantic_reads.NominalTypeShape(aid, info.name,\n        len(info.tparams) + 1, info.eparams, info.is_record))"),
        ("cx", "local-name", "semantic_reads.NominalTypeName(None, name, local_nominal)", "semantic_reads.NominalTypeName(None, name, None)"),
        ("cx", "local-shape", "refuse_nominal_earg(local_shape_cx, info.name,", "refuse_nominal_earg(cx, info.name,"),
        ("cx", "local-diagnostic", "semantic_reads.LocalTypeDiagnostic(name, diagnostic)", "semantic_reads.LocalTypeDiagnostic(name, ExportDiagnostic { ..diagnostic, hint: None })"),
        ("cx", "local-alias-answer", "semantic_reads.LocalAliasTarget(al.name, cached)", "semantic_reads.LocalAliasTarget(al.name, None)"),
        ("cx", "local-alias-cache-consumer", "match cached {\n    Some(t) -> return (cx, t)", "match cached {\n    Some(t) -> return (initial, t)"),
        ("cx", "local-alias-cycle", "semantic_reads.LocalAliasResolving(al.name, active)", "semantic_reads.LocalAliasResolving(al.name, false)"),
        ("cx", "local-alias-cycle-consumer", "cx = observe_type_read(cx, semantic_reads.LocalAliasResolving(al.name, active))", "cx = cx"),
        ("cx", "local-alias-source", "semantic_reads.LocalAliasSource(al.name, al.owner, al.target)", "semantic_reads.LocalAliasSource(al.name, al.owner, None)"),
        ("cx", "local-alias-source-owner", "semantic_reads.LocalAliasSource(al.name, al.owner, al.target)", "semantic_reads.LocalAliasSource(al.name, \"wrong-owner\", al.target)"),
        ("cx", "local-alias-header", "semantic_reads.LocalAliasHeader(name, local_header)", "semantic_reads.LocalAliasHeader(name, None)"),
        ("cx", "local-alias-header-consumer", "cx = observe_type_read(cx, semantic_reads.LocalAliasHeader(name, local_header))", "cx = cx"),
        ("cx", "local-alias-binder-types", "semantic_reads.LocalAliasBinders(al.name, al.tparams, al.eparams)", "semantic_reads.LocalAliasBinders(al.name, [], al.eparams)"),
        ("cx", "local-alias-binder-effects", "semantic_reads.LocalAliasBinders(al.name, al.tparams, al.eparams)", "semantic_reads.LocalAliasBinders(al.name, al.tparams, [])"),
        ("cx", "local-alias-binder-consumer", "cx = observe_type_read(cx, semantic_reads.LocalAliasBinders(al.name, al.tparams, al.eparams))", "cx = cx"),
        ("cx", "nominal-shape-consumer", "refuse_nominal_earg(shape_cx, info.name,", "refuse_nominal_earg(cx, info.name,"),
        ("cx", "diagnostic-kind", "semantic_reads.ExportDiagnosticAnswer(semantic_reads.TypeDiagnostic,", "semantic_reads.ExportDiagnosticAnswer(semantic_reads.ValueDiagnostic,"),
        ("cx", "diagnostic-consumer", "cerr_h(diagnostic_cx, message, lo, hi, hint)", "cerr_h(cx, message, lo, hi, hint)"),
        # Fourteen projection controls stood here and are gone with the
        # read-log projection they mutated (K7b): `type-binder-domain`,
        # `effect-binder-domain`, `opaque-domain`, `transparent-sentinel`,
        # `alias-target-domain`, `nominal-name-domain`, `nominal-shape-domain`,
        # `local-diagnostic-message`, `local-diagnostic-hint`,
        # `local-alias-target-domain`, `local-alias-cycle-projection`,
        # `local-alias-header-projection`, `local-alias-type-projection` and
        # `local-alias-effect-projection`. The alias source below is the one
        # reference a fact carries that is spelled in another declaration's
        # file, so it is the only one left to move.
        ("semantic_reads", "alias-source-projection", "Some(source_value(owner, source)?)", "Some(source)"),
        ("semantic_reads", "alias-source-owner", "Some(source_value(owner, source)?)", "Some(source_value(name, source)?)"),
    ]
    sources = {name: (ROOT / "selfhost/src/check" / (name + ".dawn")).read_text()
               for name in ("cx", "semantic_reads")}
    subjects = [(module, "positive", source) for module, source in sources.items()]
    subjects += [(module, name, edit(sources[module], old, new)) for module, name, old, new in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-type-reads-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        for module, name, source in subjects:
            target = root / "selfhost/src/check" / (module + ".dawn")
            target.write_text(source)
            owner = root / "selfhost/src/check" / ("checker.dawn" if module == "cx" else module + ".dawn")
            status, output = run("test", owner)
            target.write_text(sources[module])
            if name == "positive":
                if status:
                    raise RuntimeError("Positive " + module + " failed\n" + output)
            elif not status or not re.search(r"^FAIL\s+(?:check/\w+ :: )?(?:type reads|semantic reads) [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: type reads " + module + " " + name, flush=True)
    print(f"OK: type reads and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
