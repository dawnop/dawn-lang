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

    def test_unknown_mutator_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            script = root / "scripts/new-contract/mutate.py"
            script.parent.mkdir(parents=True)
            script.touch()
            with self.assertRaisesRegex(p.PreflightError, "unregistered=.*new-contract/mutate.py"):
                p.check(root)

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
