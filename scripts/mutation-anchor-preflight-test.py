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
