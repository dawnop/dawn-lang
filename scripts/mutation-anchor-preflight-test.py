#!/usr/bin/env python3
"""Prove anchor drift is caught without running a compiler or editing the checkout."""

import importlib.util
from pathlib import Path
import runpy
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location("preflight", Path(__file__).with_name("mutation-anchor-preflight.py"))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PreflightTests(unittest.TestCase):
    def test_full_inventory(self):
        self.assertGreater(p.check(p.ROOT), 100)

    def test_spelling_and_duplicate_anchor_are_rejected(self):
        label = "scripts/export-surface-contract/mutate.py"
        module = runpy.run_path(str(p.ROOT / label))
        target, old, new = module["MUTATIONS"]["skip-list-element"]
        original = (p.ROOT / target).read_text()
        respelled = old.replace(" ++ ", "  ++ ", 1)
        self.assertNotEqual(respelled, old)
        for changed in (original.replace(old, respelled), original + old):
            with self.assertRaises(p.PreflightError) as raised:
                p.check(p.ROOT, {target: changed})
            self.assertIn("skip-list-element", str(raised.exception))
            self.assertIn(target, str(raised.exception))
        self.assertEqual((p.ROOT / target).read_text(), original)

    def test_secondary_export_edit_is_not_skipped(self):
        label = "scripts/export-surface-contract/mutate.py"
        module = runpy.run_path(str(p.ROOT / label))
        target, old, new = module["EXTRA_EDITS"]["surface-after-bodies"]
        original = (p.ROOT / target).read_text()
        with self.assertRaisesRegex(p.PreflightError, "surface-after-bodies"):
            p.exercise(p.ROOT, (p.ROOT / label).read_text(), label,
                       "surface-after-bodies", (".",), {target: original.replace(old, "")})

    def test_registry_reader_must_still_read_its_registry(self):
        # #254: export-surface's run.sh takes its self-test anchor from
        # mutate.py, so the registry's run is its proof. A reader that stops
        # naming the registry loses that proof and must drop out of the table.
        for reader in p.REGISTRY_READERS:
            rel = f"scripts/{reader}"
            original = (p.ROOT / rel).read_text()
            self.assertIn("mutate.py", original)
            with self.assertRaisesRegex(p.PreflightError, f"{rel}: listed in REGISTRY_READERS"):
                p.check(p.ROOT, {rel: original.replace("mutate.py", "registry.py")})
            self.assertEqual((p.ROOT / rel).read_text(), original)

    def test_dict_owner_anchor_drift_is_caught(self):
        # #254: shapes.py built these anchors inline and refused a stale one
        # only when contracts-1 ran it.
        lower = "selfhost/src/ir/lower.dawn"
        self.assert_registry_drift_is_red("dict-owner-contract", "constructor-arity", lower,
                                          "nargs: nargs,", "nargs: nargs ,")
        # The two-line anchor the bridge and prim mutants share a shape with.
        self.assert_registry_drift_is_red("dict-owner-contract", "bridge-shape", lower,
                                          'let name = "bridge$" ++ to_string(tid)',
                                          'let name = "bridge$" ++ show(tid)')
        self.assert_stale_registry_is_red("dict-owner-contract", "dictionary-shape", 0)

    def test_cold_reference_anchor_drift_is_caught(self):
        # #254: cold.py spelled these driver/analyze.dawn anchors in its main
        # and refused a stale one only when incremental-memo-3 ran it.
        analyze = "selfhost/src/driver/analyze.dawn"
        self.assert_registry_drift_is_red("incremental-semantics-contract", "cold/intern-table", analyze,
                                          "    identities: before.identities,",
                                          "    identities: before.identities ,")
        self.assert_registry_drift_is_red("incremental-semantics-contract", "cold/std-baseline", analyze,
                                          "      Some(before) -> { base_impls = before }",
                                          "      Some(prior) -> { base_impls = prior }")
        self.assert_stale_registry_is_red("incremental-semantics-contract", "cold/skip-comptime", 0)

    def test_lsp_observe_anchor_drift_is_caught(self):
        # #277: lsp-observe.py spelled its probes in its own main; the
        # prefix-stats one sat behind `if ... in text`, so a drifted anchor
        # dropped LSP_PREFIX_STATS from the trace without a word.
        server = "selfhost/src/lsp/server.dawn"
        self.assert_registry_drift_is_red("incremental-semantics-contract", "lsp-observe/inputs", server,
                                          "      let loaded = reusing.loaded\n",
                                          "      let loaded  = reusing.loaded\n")
        self.assert_registry_drift_is_red("incremental-semantics-contract", "lsp-observe/prefix-stats", server,
                                          "      let update = incremental.analyze(",
                                          "      let update  = incremental.analyze(")
        self.assert_stale_registry_is_red("incremental-semantics-contract", "lsp-observe/inputs", 0)

    def test_lsp_configured_anchor_drift_is_caught(self):
        # #277: lsp-configured.py spelled both anchors in configure, and CI
        # runs only its --self-test, whose fixture was a copy of them; a
        # drifted server anchor surfaced when someone next ran the benchmark.
        server = "selfhost/src/lsp/server.dawn"
        self.assert_registry_drift_is_red("incremental-semantics-contract", "lsp-configured/policy", server,
                                          "legacy_analysis_config())", "legacy_analysis_config() )")
        self.assert_registry_drift_is_red("incremental-semantics-contract", "lsp-configured/observe", server,
                                          "      let prog = update.program\n      Workspace {",
                                          "      let prog = update.program\n      Workspace  {")
        self.assert_stale_registry_is_red("incremental-semantics-contract", "lsp-configured/policy", 0)

    def test_lsp_module_memo_anchor_drift_is_caught(self):
        # #277: lsp-module-memo.py spelled its seven mutants in its main and
        # refused a stale one only when incremental-memo-2 ran it.
        self.assert_registry_drift_is_red("incremental-semantics-contract", "lsp-module-memo/drop-session",
                                          "selfhost/src/lsp/server.dawn",
                                          "        cache: update.session,", "        cache: update.session ,")
        self.assert_registry_drift_is_red("incremental-semantics-contract", "lsp-module-memo/stale-parse",
                                          "selfhost/src/driver/analyze.dawn",
                                          "if p.text == text { (p, true) }", "if text == p.text { (p, true) }")
        self.assert_registry_drift_is_red("incremental-semantics-contract",
                                          "lsp-module-memo/resolver-drops-the-declaration",
                                          "selfhost/src/check/checker.dawn",
                                          "syms: tast_positions.symbols(entered.resolver, after.syms, ",
                                          "syms: tast_positions.symbols(entered.resolver,  after.syms, ")
        self.assert_stale_registry_is_red("incremental-semantics-contract", "lsp-module-memo/drop-parses", 0)

    def test_body_executor_anchor_drift_is_caught(self):
        # #277: body-executor.py derived its thirteen controls from six calls
        # in its main and refused a stale one only when incremental-memo-3
        # ran it. The group entry is shared by two derived controls.
        checker = "selfhost/src/check/checker.dawn"
        self.assert_registry_drift_is_red("incremental-semantics-contract", "body-executor/bypass-constant",
                                          checker, "executor.constant(state, owner.cx, d, declared, visible)",
                                          "executor.constant(state, owner.cx, d, declared,  visible)")
        self.assert_registry_drift_is_red("incremental-semantics-contract", "body-executor/reset-state-inferred",
                                          checker, "attempt_inferred_group(state, cx1, inferred, settled,",
                                          "attempt_inferred_group(state, cx1, inferred,  settled,")
        self.assert_stale_registry_is_red("incremental-semantics-contract", "body-executor/bypass-test", 0)

    def test_module_memo_anchor_drift_is_caught(self):
        # #277: module-memo.py applied every anchor in every shard, but only
        # once incremental-memo-1..3 ran; its --self-test builds nothing and
        # reads no anchor. Two anchors here are shared by two mutants each.
        engine = "selfhost/src/driver/incremental.dawn"
        self.assert_registry_drift_is_red("incremental-semantics-contract", "module-memo/always-cold", engine,
                                          "identity == e.std_identity) { return None }",
                                          "e.std_identity == identity) { return None }")
        self.assert_registry_drift_is_red("incremental-semantics-contract", "module-memo/false-cutoff", engine,
                                          "              Some(before) -> if same_surface(own, before) {",
                                          "              Some(prior) -> if same_surface(own, prior) {")
        self.assert_registry_drift_is_red("incremental-semantics-contract", "module-memo/impl-positions",
                                          "selfhost/src/check/checker.dawn",
                                          "  if im.lo == 0 && im.hi == 0 { im }", "  if im.hi == 0 && im.lo == 0 { im }")
        self.assert_stale_registry_is_red("incremental-semantics-contract", "module-memo/stale-spans", 0)

    def test_identity_anchor_drift_is_caught(self):
        # #277: identity.py spelled its thirty-three mutants over six files in
        # its main and refused a stale one only when incremental-memo-1 ran it,
        # section by section, after building the sections before it.
        self.assert_registry_drift_is_red("incremental-semantics-contract", "identity/default-ambiguity",
                                          "selfhost/src/check/identity.dawn", "if same == 1 {", "if 1 == same {")
        self.assert_registry_drift_is_red("incremental-semantics-contract",
                                          "identity/symbol-table-carries-what-the-module-never-names",
                                          "selfhost/src/ir/lower.dawn",
                                          "moved_syms = map.insert(moved_syms, next, s) }\n      None -> ()",
                                          "moved_syms = map.insert(moved_syms, next, s) }\n      None -> {}")
        self.assert_registry_drift_is_red("incremental-semantics-contract", "identity/enter-keeps-the-previous-declaration",
                                          "selfhost/src/check/cx.dawn", "Cx { ..interned_cx, owner_decl: id }",
                                          "Cx { ..interned_cx, owner_decl: id  }")
        self.assert_registry_drift_is_red("incremental-semantics-contract", "identity/drop-std-identity-step",
                                          "selfhost/src/driver/stdlib.dawn", "interned = cx1.identities",
                                          "interned =  cx1.identities")
        self.assert_registry_drift_is_red("incremental-semantics-contract", "identity/mint-imported-effect",
                                          "selfhost/src/check/passes.dawn",
                                          "effects: map.insert(cx1.effects, local, eid) }",
                                          "effects: map.insert(cx1.effects, local, eid)  }")
        self.assert_stale_registry_is_red("incremental-semantics-contract", "identity/binder-spelling", 0)

    def test_tile_golden_anchor_drift_is_caught(self):
        # #254: these anchors were mutant_project arguments in run.sh, checked
        # only when the tile-golden shard holding that mutant next ran.
        self.assert_registry_drift_is_red("tile-golden", "make-token-as-iota",
                                          "packages/tileir/src/bytecode.dawn",
                                          "const OP_MAKE_TOKEN: Int = 0x44",
                                          "const OP_MAKE_TOKEN: Int = 68")
        self.assert_registry_drift_is_red("tile-golden", "load-dtype-f64",
                                          "packages/tileir/src/dev.dawn",
                                          "param_dtype(p), i, shape, strides, none, none, [])",
                                          "param_dtype(p), i, shape, strides, none, none, [ ])")
        self.assert_stale_registry_is_red("tile-golden", "region-stack-pop", 0)

    def test_lsp_lifecycle_anchor_drift_is_caught(self):
        # #277: these anchors were a heredoc in run.sh, checked only when
        # lsp-workspace built that mutant's compiler.
        server = "selfhost/src/lsp/server.dawn"
        self.assert_registry_drift_is_red("lsp-lifecycle-contract", "early-exit-zero", server,
                                          "const ABNORMAL_EXIT_STATUS: Int = 1",
                                          "const ABNORMAL_EXIT_STATUS: Int = 2")
        self.assert_registry_drift_is_red("lsp-lifecycle-contract", "shutdown-flushes", server,
                                          "            LgBeginShutdown -> {\n              pending = None\n",
                                          "            LgBeginShutdown -> {\n              pending = none\n")
        self.assert_stale_registry_is_red("lsp-lifecycle-contract", "repeat-initialize", 0)

    def test_project_plan_anchor_drift_is_caught(self):
        # #277: these anchors were heredocs in run.sh, checked only when
        # lsp-workspace reached that mutant after building the probe.
        self.assert_registry_drift_is_red("project-plan-contract", "fresh-replan-loader",
                                          "selfhost/src/driver/analyze.dawn",
                                          "    entry_file(plan),\n    previous\n  )\n",
                                          "    entry_file(plan), previous\n  )\n")
        self.assert_registry_drift_is_red("project-plan-contract", "fresh-completion",
                                          "selfhost/src/lsp/server.dawn",
                                          "completions_at(qc, analysis.modules,",
                                          "completions_at(qc, analysis.modules ,")
        self.assert_stale_registry_is_red("project-plan-contract", "fresh-completion", 0)

    def test_jsig_lease_anchor_drift_is_caught(self):
        # #277: these anchors were a heredoc in run.sh, checked only when
        # java-target-classpath reached that mutant after building fixtures.
        self.assert_registry_drift_is_red("jsig-lease-contract", "parent-is-system",
                                          "selfhost/src/jvm/jreflect.dawn",
                                          'expect("platform loader")', 'expect("platform class loader")')
        # The probe fixture is a subject too, at its checkout path.
        self.assert_registry_drift_is_red("jsig-lease-contract", "bypass-bracket",
                                          "scripts/jsig-lease-contract/probe.dawn",
                                          "probe => probe.lease.close()", "p => p.lease.close()")
        self.assert_stale_registry_is_red("jsig-lease-contract", "drop-close", 0)

    def test_builtin_type_anchor_drift_is_caught(self):
        # #277: these anchors were replace_once arguments and heredocs in
        # run.sh, checked only when the builtin-type shard holding that
        # mutant built its compiler.
        self.assert_registry_drift_is_red("builtin-type-contract", "reject-local-return",
                                          "selfhost/src/check/checker.dawn",
                                          "  let (cxb, ret) = resolve_return_type(cx1, ret_ref)",
                                          "  let (cxb, ret) = resolve_return_type(cx1, ret_ref )")
        # The second edit of a two-file mutant, in the embedded std source.
        self.assert_registry_drift_is_red("builtin-type-contract", "make-io-exit-bottom",
                                          "selfhost/src/embed/stdsrc.dawn",
                                          "pub fn exit(code: Int) -> Unit !Exit = exit_now(code)",
                                          "pub fn exit(code: Int) -> Unit !Exit = exit_now (code)")
        self.assert_stale_registry_is_red("builtin-type-contract", "allow-storage-tuple", 0)

    def test_declared_match_count_is_held_both_ways(self):
        # stale-checker-consumer renames both calls of public_builtin_type_names()
        # in cx.dawn. The registry declares the two, and a third call or a lost
        # one is as red as a respelled anchor, not quietly renamed or skipped.
        cx = "selfhost/src/check/cx.dawn"
        label = "scripts/builtin-type-contract/mutate.py"
        edit = runpy.run_path(str(p.ROOT / label))["MUTATIONS"]["stale-checker-consumer"][0]
        self.assertEqual(edit[0], cx)
        self.assertEqual(edit[3], 2)
        original = (p.ROOT / cx).read_text()
        self.assertEqual(original.count(edit[1]), 2)
        third = original + "\nfn third_call() -> List[String] = " + edit[1] + "\n"
        lost = original.replace(edit[1], "public_builtin_type_list()", 1)
        for changed, count in ((third, 3), (lost, 1)):
            with self.assertRaisesRegex(p.PreflightError, "builtin-type-contract/mutate.py:"
                                        f"stale-checker-consumer .*matches {count} times, expected 2"):
                p.check(p.ROOT, {cx: changed})
        self.assertEqual((p.ROOT / cx).read_text(), original)

    def test_tea_reconciler_anchor_drift_is_caught(self):
        # #277: these were sed programs in mutants.sh, which counted a mutant
        # applied when the file changed at all, and noticed a respelled line
        # only when contracts-2 reached it.
        self.assert_registry_drift_is_red("tea-reconciler-contract", "walk-path-not-extended",
                                          "packages/tea-core/src/walk.dawn",
                                          "go(ks[i], path ++ [i], acc, f)",
                                          "go(ks[i], path ++ [i], acc,  f)")
        self.assert_registry_drift_is_red("tea-reconciler-contract", "relate-ignores-the-key",
                                          "packages/tea-dom/src/node.dawn",
                                          "if t1 != t2 || k1 != k2 {", "if k1 != k2 || t1 != t2 {")
        self.assert_stale_registry_is_red("tea-reconciler-contract", "relate-descends-into-a-leaf", 0)

    def test_tea_reconciler_second_copy_is_red(self):
        # The sed it replaced mutated every copy and passed on any change; a
        # second copy of an anchor is now a red preflight, not a wider mutant.
        target = "packages/tea-core/src/diff.dawn"
        literal = "op: Replace(w: new)"
        original = (p.ROOT / target).read_text()
        self.assertEqual(original.count(literal), 1)
        with self.assertRaisesRegex(p.PreflightError,
                                    "tea-reconciler-contract/mutate.py:unrelated-becomes-inplace"):
            p.check(p.ROOT, {target: original + "\n# " + literal + "\n"})

    def test_gate_map_record_anchors_are_not_skipped(self):
        target = "scripts/gate-map/unseen.txt"
        original = (p.ROOT / target).read_text()
        changed = "\n".join(line for line in original.splitlines()
                            if not line.startswith("LICENSE ")) + "\n"
        self.assertNotEqual(changed, original)
        with self.assertRaisesRegex(p.PreflightError, "a-recorded-gap-with-no-reason") as raised:
            p.check(p.ROOT, {target: changed})
        self.assertIn(target, str(raised.exception))

    def test_former_self_once_anchor_drift_is_caught(self):
        # #249: delete-contract refused a stale anchor only when it ran itself,
        # so #248's rewrite of dawn_cpath passed this preflight. The contract's
        # anchors now live in its mutate.py; either side drifting must be red.
        label = "scripts/delete-contract/mutate.py"
        source = (p.ROOT / label).read_text()
        target, old, new = runpy.run_path(str(p.ROOT / label))["MUTATIONS"]["c-cpath-nul"]
        self.assertEqual(target, "runtime/c/dawn_rt.c")
        # The spelling of dawn_cpath before #248, which 95e59645's run.sh quoted.
        stale = old.replace("  dawn_reject_nul(s);\n", "  if (dawn_has_nul(s)) {\n"
                            "    dawn_fault(DAWN_LIT(\"path contains an embedded NUL byte\"));\n"
                            "  }\n")
        self.assertNotEqual(stale, old)
        self.assertEqual(source.count(old), 1)
        p.exercise(p.ROOT, source, label, "c-cpath-nul", p.ADAPTERS["delete-contract"])
        with self.assertRaisesRegex(p.PreflightError, "c-cpath-nul: mutation anchor") as raised:
            p.exercise(p.ROOT, source.replace(old, stale), label, "c-cpath-nul",
                       p.ADAPTERS["delete-contract"])
        self.assertIn(target, str(raised.exception))
        original = (p.ROOT / target).read_text()
        with self.assertRaisesRegex(p.PreflightError, "delete-contract/mutate.py:c-cpath-nul"):
            p.check(p.ROOT, {target: original.replace(old, stale)})
        self.assertEqual((p.ROOT / target).read_text(), original)

    def assert_registry_drift_is_red(self, name, mode, target, before, after):
        # A rewrite of the subject that leaves one registered anchor stale must
        # redden the whole-tree preflight, naming the registry and the mode.
        original = (p.ROOT / target).read_text()
        self.assertEqual(original.count(before), 1)
        with self.assertRaisesRegex(p.PreflightError, f"{name}/mutate.py:{mode}") as raised:
            p.check(p.ROOT, {target: original.replace(before, after)})
        self.assertIn(target, str(raised.exception))
        self.assertEqual((p.ROOT / target).read_text(), original)

    def assert_stale_registry_is_red(self, name, mode, index):
        # The other direction: a registry entry spelled differently from the
        # subject it quotes is refused, and the untouched registry is not.
        label = f"scripts/{name}/mutate.py"
        source = (p.ROOT / label).read_text()
        _target, old, _new = runpy.run_path(str(p.ROOT / label))["MUTATIONS"][mode][index]
        literal = old.rstrip("\n").split("\n")[-1]
        stale = literal[::-1].replace(" ", "  ", 1)[::-1]
        self.assertNotEqual(stale, literal)
        self.assertEqual(source.count(literal), 1)
        p.exercise(p.ROOT, source, label, mode, p.ADAPTERS[name])
        with self.assertRaisesRegex(p.PreflightError, f"{mode}: mutation anchor"):
            p.exercise(p.ROOT, source.replace(literal, stale), label, mode, p.ADAPTERS[name])

    def test_classfile_verify_anchor_drift_is_caught(self):
        # #254: these anchors were replace_never_once arguments in run.sh,
        # checked only when the contract built its seventeen mutant compilers.
        emit = "selfhost/src/jvm/emit.dawn"
        self.assert_registry_drift_is_red("classfile-verify", "omit-closure-bottom", emit,
                                          "  if is_bottom(b.fret) {", "  if is_bottom(b.ret) {")
        # The second edit of a two-edit mutant is reached and held too.
        self.assert_registry_drift_is_red("classfile-verify", "use-pop-for-wide-bottom", emit,
                                          "OP_NEW, OP_POP, OP_POP2, OP_PUTFIELD",
                                          "OP_NEW, OP_POP2, OP_POP, OP_PUTFIELD")
        self.assert_registry_drift_is_red("classfile-verify", "reject-wide-sam-bottom",
                                          "selfhost/src/check/checker.dawn",
                                          "    r == TyInt || r == TyNever",
                                          "    r == TyNever || r == TyInt")
        self.assert_stale_registry_is_red("classfile-verify", "omit-closure-bottom", 0)

    def test_syntax_small_anchor_drift_is_caught(self):
        # #254: these anchors were five Python heredocs in run.sh, checked only
        # when a syntax shard built the mutant that quotes them.
        parser = "selfhost/src/front/parser.dawn"
        self.assert_registry_drift_is_red("syntax-small-contract", "drop-rbracket-return-boundary",
                                          parser, "k == RBRACKET || k == COMMA || k == EOF\n",
                                          "k == COMMA || k == RBRACKET || k == EOF\n")
        # The second edit, reached only after the first inserted its table.
        self.assert_registry_drift_is_red("syntax-small-contract", "restore-parser-builtin-branch",
                                          parser, "  let aliasish = at_kind(p, st4, FN) ||",
                                          "  let aliasish = at_kind(p, st4, LPAREN) ||")
        # Two mutants share this anchor; the preflight reports the first in
        # its sorted order.
        self.assert_registry_drift_is_red("syntax-small-contract", "drop-builtin-alias-boundary",
                                          "selfhost/src/check/passes.dawn",
                                          "len(d.ctors) == 1 && len(c.fields) == 0\n",
                                          "len(c.fields) == 0 && len(d.ctors) == 1\n")
        self.assert_stale_registry_is_red("syntax-small-contract", "drop-rbracket-return-boundary", 0)

    def test_inflate_anchor_drift_is_caught(self):
        # #254: these anchors were arguments to run.sh's mutate helper, checked
        # only when the contract ran its six mutant packages. The subject is
        # package source, laid out repository-relative in the registry.
        self.assert_registry_drift_is_red("inflate-contract", "member-loop",
                                          "packages/inflate/src/gzip.dawn",
                                          "while cursor < n {", "while n > cursor {")
        self.assert_stale_registry_is_red("inflate-contract", "member-loop", 0)

    def test_narrow_anchor_drift_is_caught(self):
        # #254: these anchors were arguments to run.sh's patch_std helper,
        # checked only after a JVM and a native build per mutant. The subject
        # is std source, laid out repository-relative in the registry.
        narrow = "std/narrow.dawn"
        self.assert_registry_drift_is_red("narrow-contract", "emax-off-by-one", narrow,
                                          "round_binary(x, 8, -126, 127)",
                                          "round_binary(x, 8, -126, 127 )")
        # The comment lines are part of the anchor: they keep it off the
        # DIRECTED neighbour, so rewording them must be caught too.
        self.assert_registry_drift_is_red("narrow-contract", "no-subnormal-clamp", narrow,
                                          "      # to the subnormal grid below emin\n      let qe = (",
                                          "      # to the subnormal grid under emin\n      let qe = (")
        self.assert_stale_registry_is_red("narrow-contract", "emax-off-by-one", 0)

    def test_java_narrowing_anchor_drift_is_caught(self):
        # #254: these anchors were two Python heredocs in run.sh, checked only
        # when the contract tested two private selfhost copies.
        self.assert_registry_drift_is_red("java-narrowing-contract", "object-scorer-exception",
                                          "selfhost/src/check/checker.dawn",
                                          "} else if cx.jsig.is_assignable(p, fq) {",
                                          "} else if cx.jsig.is_assignable(p, fq) == true {")
        # The last of the backend mutant's three edits is reached and held too.
        self.assert_registry_drift_is_red("java-narrowing-contract", "backend-checkcast",
                                          "selfhost/src/jvm/help.dawn",
                                          "    m.visitInsn(OP_D2F)\n  }\n  ()",
                                          "    m.visitInsn(OP_D2F)\n  }\n  unit()")
        self.assert_stale_registry_is_red("java-narrowing-contract", "backend-checkcast", 1)

    def test_map_reuse_anchor_drift_is_caught(self):
        # #254: these anchors were two Python heredocs in run.sh, one behind a
        # private compiler build. One subject is compiler source, the other std.
        self.assert_registry_drift_is_red("map-reuse-contract", "keep-record-spread-source",
                                          "selfhost/src/c/rc.dawn",
                                          "schedule_record_update(st, stmts, tail)",
                                          "schedule_record_update(st, stmts,  tail)")
        self.assert_registry_drift_is_red("map-reuse-contract", "get-hamt-child-again",
                                          "std/hamt.dawn",
                                          "        let child = array_steal(kids, pos)\n",
                                          "        let child = array_steal(kids, pos) \n")
        self.assert_stale_registry_is_red("map-reuse-contract", "get-hamt-child-again", 0)

    def test_atomic_write_anchor_drift_is_caught(self):
        # #254: these anchors were arguments to run.sh's patch_std helper and
        # two heredocs, checked only when the contract ran. Three subjects:
        # std, the C runtime and compiler source.
        self.assert_registry_drift_is_red("atomic-write-contract", "follow-symlink",
                                          "std/io.dawn", "  } else if is_symlink(path) {",
                                          "  } else if is_symlink(path) == true {")
        # The second edit of the layered mutant is reached and held too.
        self.assert_registry_drift_is_red("atomic-write-contract", "skip-verify",
                                          "std/io.dawn", "          if seen != bytes_utf8(content) {",
                                          "          if bytes_utf8(content) != seen {")
        self.assert_registry_drift_is_red("atomic-write-contract", "inject-close",
                                          "runtime/c/dawn_rt.c",
                                          'DAWN_LIT("io_write_file: write failed")',
                                          'DAWN_LIT("io_write_file: write error")')
        self.assert_registry_drift_is_red("atomic-write-contract", "add-plain-write",
                                          "selfhost/src/pkg/add.dawn", "io.atomic_write_file(",
                                          "io.atomic_write_file (")
        self.assert_stale_registry_is_red("atomic-write-contract", "follow-symlink", 0)

    def test_wasm_dom_retained_anchor_drift_is_caught(self):
        # #254: these anchors were arguments to retained.sh's
        # apply_exact_mutant helper, reached only after the native driver,
        # node and a wasm toolchain had run the clean sessions. The literals
        # here avoid the intrinsic names: retained.sh's seam gate pins every
        # file that spells them.
        reactor = "std/reactor.dawn"
        self.assert_registry_drift_is_red("wasm-dom-contract", "drop-retained-state", reactor,
                                          "() { Some(", "() {  Some(")
        # The second edit of the two-edit mutant is reached and held too.
        self.assert_registry_drift_is_red("wasm-dom-contract", "commit-before-success", reactor,
                                          "          Ok(answer) -> answer\n",
                                          "          Ok(value) -> value\n")
        self.assert_stale_registry_is_red("wasm-dom-contract", "drop-retained-state", 0)

    def test_wasm_dom_flags_anchor_drift_is_caught(self):
        # #277: flags.sh applied these as sed programs and counted a mutant
        # applied when the file changed at all, and only once node and
        # bin/dawn had run both clean legs.
        self.assert_registry_drift_is_red("wasm-dom-contract", "mount-drops-the-flags",
                                          "packages/tea-dom/js/app.mjs",
                                          "settle(reactor.init(flags));",
                                          "settle(reactor.init(flags ));")
        self.assert_registry_drift_is_red("wasm-dom-contract", "flags-never-decoded",
                                          "packages/tea-dom/src/wire.dawn",
                                          'field(entries, "flags")', 'field(entries,  "flags")')
        self.assert_stale_registry_is_red("wasm-dom-contract", "flags-ignored-at-the-turn", 0)

    def test_wasm_dom_run_anchor_drift_is_caught(self):
        # #277: run.sh applied these as sed programs checked only for having
        # changed the file, and located no-catch's block by the shape of its
        # first line; all after building the native driver and both reactors.
        self.assert_registry_drift_is_red("wasm-dom-contract", "patch-order",
                                          "packages/tea-dom/js/dom.mjs",
                                          "    for (const patch of patches) {",
                                          "    for (const p of patches) {")
        self.assert_registry_drift_is_red("wasm-dom-contract", "todo-filter",
                                          "examples/projects/tea_dom_todo/src/todo.dawn",
                                          "    Done -> list.filter(m.todos, t => t.done)",
                                          "    Done -> list.filter(m.todos, (t) => t.done)")
        # The block literal that replaced the structural locator: a line
        # inside it, here its comment, is part of the anchor too.
        self.assert_registry_drift_is_red("wasm-dom-contract", "no-catch",
                                          "packages/tea-dom/src/reactor.dawn",
                                          "The message is passed through verbatim.",
                                          "The message passes through verbatim.")
        self.assert_stale_registry_is_red("wasm-dom-contract", "event-address", 0)

    def assert_stale_mutator_is_red(self, name, mode, literal):
        # For a mutate.py whose anchors are not a MUTATIONS table of edit
        # tuples: respell the first copy of one anchor line inside the
        # mutator, and the untouched mutator must still apply.
        label = f"scripts/{name}/mutate.py"
        source = (p.ROOT / label).read_text()
        stale = literal[::-1].replace(" ", "  ", 1)[::-1]
        self.assertNotEqual(stale, literal)
        self.assertIn(literal, source)
        p.exercise(p.ROOT, source, label, mode, p.ADAPTERS[name])
        with self.assertRaisesRegex(p.PreflightError, f"{label}:{mode}"):
            p.exercise(p.ROOT, source.replace(literal, stale, 1), label, mode, p.ADAPTERS[name])

    def test_rc_anchor_drift_is_caught(self):
        # #277: rc-contract/run.sh is not-anchor because its mutants all come
        # from this registry; its own source reads are the bare-free() count,
        # an assertion that is red on a match. Both subjects are held.
        self.assert_registry_drift_is_red("rc-contract", "revert-adt0-to-fresh-allocation",
                                          "runtime/c/dawn_rt.h",
                                          "    dawn_adt0_hits++;\n", "    dawn_adt0_hits += 1;\n")
        # Two mutants quote this line; the preflight names the first in order.
        self.assert_registry_drift_is_red("rc-contract", "slab-forgets-to-poison",
                                          "runtime/c/dawn_rt.c",
                                          "    s->used--; /* the current slab",
                                          "    s->used -= 1; /* the current slab")
        self.assert_stale_mutator_is_red("rc-contract", "revert-adt0-to-fresh-allocation",
                                         "    dawn_adt0_hits++;\n")

    def test_range_bound_order_anchor_drift_is_caught(self):
        # #277: range-bound-order-contract/run.sh is not-anchor because its
        # one mutant comes from this mutator; the harness greps only the
        # observed red set.
        self.assert_registry_drift_is_red("range-bound-order-contract", "restore-upper-first",
                                          "selfhost/src/ir/lower.dawn",
                                          "            CSLet(isym, item_ty, lo_v),\n",
                                          "            CSLet(isym, item_ty, lo_v) ,\n")
        self.assert_stale_mutator_is_red("range-bound-order-contract", "restore-upper-first",
                                         "CSLet(bsym, TyInt, hi_v),")

    def test_source_loop_label_anchor_drift_is_caught(self):
        # #277: source-loop-label-contract/run.sh is not-anchor because its
        # one mutant comes from this mutator; the harness greps only a Core
        # dump and the observed red set.
        self.assert_registry_drift_is_red("source-loop-label-contract",
                                          "drop-terminal-loop-jump-guard",
                                          "selfhost/src/c/rc.dawn",
                                          "not yields(x) && not jumps(x, lid, true, true)",
                                          "not yields(x) && not jumps(x, lid, true,true)")
        self.assert_stale_mutator_is_red("source-loop-label-contract",
                                         "drop-terminal-loop-jump-guard",
                                         "not jumps(x, lid, true, true)")

    def test_ctl_live_anchor_drift_is_caught(self):
        # #277: ctl-live-contract/run.sh is not-anchor because its mutants all
        # come from this registry; the harness copies runtime/c and greps only
        # the probe's stderr.
        rt = "runtime/c/dawn_rt.c"
        self.assert_registry_drift_is_red("ctl-live-contract", "ctl-discard-skips-cleanups", rt,
                                          "  dawn_ctl_discard_walking = run_releases;\n"
                                          "  dawn_unwind_to(h);",
                                          "  dawn_ctl_discard_walking = run_releases;\n"
                                          "  dawn_unwind_to(h );")
        self.assert_registry_drift_is_red("ctl-live-contract", "ctl-signals-one-waiter", rt,
                                          "  c->turn = 1;\n  pthread_cond_broadcast(&c->cv);",
                                          "  c->turn = 1;\n  pthread_cond_broadcast(&c->cv );")
        self.assert_stale_mutator_is_red("ctl-live-contract", "ctl-never-reclaims",
                                         "c->die = true;")

    def test_display_layering_anchor_drift_is_caught(self):
        # #277: display-layering-contract/run.sh is not-anchor because both
        # mutants come from this mutator; the harness greps only the observed
        # red set.
        lower = "selfhost/src/ir/lower.dawn"
        self.assert_registry_drift_is_red("display-layering-contract", "drop-display-question",
                                          lower,
                                          "    display_at(st, e, t)\n  } else if t == TyString {\n",
                                          "    display_at(st, e,  t)\n  } else if t == TyString {\n")
        self.assert_registry_drift_is_red("display-layering-contract", "inherit-display", lower,
                                          "      TyVar(_, _) ->\n        match wit {",
                                          "      TyVar(_,  _) ->\n        match wit {")
        self.assert_stale_mutator_is_red("display-layering-contract", "drop-display-question",
                                         "display_at(st, e, t)")

    def test_dependency_heap_anchor_drift_is_caught(self):
        # #277: dependency-heap-contract/run.py is not-anchor because its one
        # mutant comes from this registry; the harness's replaces edit its
        # matrix in a self-test.
        self.assert_registry_drift_is_red("dependency-heap-contract", "drop-inherited-max-heap",
                                          "selfhost/src/main.dawn",
                                          '"-Xss512m", own_xmx(), ',
                                          '"-Xss512m", own_xmx() , ')
        self.assert_stale_mutator_is_red("dependency-heap-contract", "drop-inherited-max-heap",
                                         '"-Xss512m", own_xmx(), ')

    def test_bootstrap_input_manifest_anchor_drift_is_caught(self):
        # #277: bootstrap-input-manifest-contract/run.sh is not-anchor because
        # its mutants all come from this mutator; the harness's count and
        # replace fill its own manifest fixture.
        source = "compiler-plan/src/source.dawn"
        self.assert_registry_drift_is_red("bootstrap-input-manifest-contract",
                                          "drop-package-manifest", source,
                                          '    SourceInput { kind: InputFile, path: parent ++ "/dawn.toml" },\n',
                                          '    SourceInput { kind: InputFile, path: parent ++ "/dawn.toml" } ,\n')
        self.assert_registry_drift_is_red("bootstrap-input-manifest-contract",
                                          "persist-internal-absolute", source,
                                          '        ("R", str.drop(input.path, str.len(prefix)))\n',
                                          '        ("R", str.drop(input.path, str.len(prefix) ))\n')
        self.assert_stale_mutator_is_red("bootstrap-input-manifest-contract",
                                         "drop-package-manifest",
                                         'SourceInput { kind: InputFile, path: parent ++ "/dawn.toml" },')

    def test_unknown_mutator_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            script = root / "scripts/new-contract/mutate.py"
            script.parent.mkdir(parents=True)
            script.touch()
            with self.assertRaisesRegex(p.PreflightError, "unregistered=.*new-contract/mutate.py"):
                p.check(root)

    def test_inventory_does_not_claim_all_scripts_as_covered(self):
        gm = runpy.run_path(str(p.ROOT / "scripts/gate-map/gatemap.py"))
        tree = gm["Tree"](p.ROOT, files=["scripts/manual.sh", "scripts/example/mutate.py"])
        source = (p.ROOT / "scripts/mutation-anchor-preflight.py").read_text()
        inputs = gm["python_inputs"](source, tree) | gm["path_tokens"](source, tree)
        self.assertIn("scripts/example/mutate.py", inputs)
        self.assertNotIn("scripts/manual.sh", inputs)

    def test_shell_anchors_use_the_real_embedded_mutator(self):
        label = "scripts/java-target-classpath-contract/run.sh"
        source = p.shell_source((p.ROOT / label).read_text(), label)
        target = "selfhost/src/driver/analyze.dawn"
        original = (p.ROOT / target).read_text()
        changed = original.replace("pub fn project_plan_for_load(", "pub fn changed_plan_for_load(")
        with self.assertRaisesRegex(p.PreflightError, "plan-before-preflight") as raised:
            p.exercise(p.ROOT, source, label, "plan-before-preflight",
                       p.SHELL_ADAPTERS["java-target-classpath-contract"], {target: changed})
        self.assertIn(target, str(raised.exception))

    def test_shell_block_selection_fails_closed(self):
        for source in ("", 'python3 - "$name" <<\'PY\'\npass\nPY\n' * 2):
            with self.assertRaises(p.PreflightError):
                p.shell_source(source, "fixture.sh")

    def test_embedded_std_probe_anchor_is_checked(self):
        label = "scripts/std-version-contract/run.sh"
        source = p.shell_source((p.ROOT / label).read_text(), label,
                                "$probe/selfhost/src/embed/stdsrc.dawn")
        target = "selfhost/src/embed/stdsrc.dawn"
        original = (p.ROOT / target).read_text()
        changed = original.replace('if name == "modules.txt"', 'if name == "missing.txt"')
        with self.assertRaisesRegex(p.PreflightError, "embedded-probe"):
            p.exercise(p.ROOT, source, label, "embedded-probe", (target,),
                       {target: changed}, pass_mode=False)

    def test_no_builds_or_direct_writes(self):
        for source in (
            'import subprocess; subprocess.run(["dawn", "build"])',
            'from pathlib import Path; Path("/tmp/mutation-preflight-forbidden").write_bytes(b"bad")',
            'open("/tmp/mutation-preflight-forbidden", "w")',
        ):
            with self.assertRaises(p.PreflightError):
                p.exercise(p.ROOT, source, "fixture.py", "bad", ())

    def test_discovery_reads_new_literal_modes_and_rejects_unknown_registry_shape(self):
        self.assertEqual(p.modes('MUTATIONS = {"one": (), "two": ()}', "fixture"), ["one", "two"])
        self.assertEqual(p.modes('if name == "one": pass\nelif name == "two": pass', "fixture"), ["one", "two"])
        with self.assertRaises(p.PreflightError):
            p.modes('MUTATIONS = load_registry()', "fixture")

    def test_in_memory_sequential_mutations_do_not_leak(self):
        label = "scripts/java-target-classpath-contract/run.sh"
        source = p.shell_source((p.ROOT / label).read_text(), label)
        args = p.SHELL_ADAPTERS["java-target-classpath-contract"]
        original = (p.ROOT / args[0]).read_text()
        changed = p.exercise(p.ROOT, source, label, "instrument-close", args)
        p.exercise(p.ROOT, source, label, "bypass-bracket", args, changed)
        with self.assertRaises(p.PreflightError):
            p.exercise(p.ROOT, source, label, "bypass-bracket", args)
        self.assertEqual((p.ROOT / args[0]).read_text(), original)


if __name__ == "__main__":
    unittest.main()
