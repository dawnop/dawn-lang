#!/usr/bin/env python3
"""The contract's cases are scheduled in several jobs; none may be dropped or repeated.

Reads every run.sh invocation in gates.yml and holds the union of the cases
they select equal to run.CASES, with no case in two jobs. Fixed text only.
"""
from pathlib import Path
import re
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run  # noqa: E402

GATES = HERE.parents[1]/'.github/workflows/gates.yml'
INVOCATION = re.compile(r'^\s*run: \./scripts/effect-provenance-contract/run\.sh(.*)$', re.M)


def invocations(text=None):
    text = GATES.read_text() if text is None else text
    return [line.split() for line in INVOCATION.findall(text)]


def selected(words):
    """Cases one invocation runs, and whether it owns the generator and runtime checks."""
    if '--cases' in words:
        return words[words.index('--cases')+1:], False
    if '--except' in words:
        skipped = words[words.index('--except')+1:]
        return [c for c in run.CASES if c not in skipped], True
    return list(run.CASES), True


class SchedulingTests(unittest.TestCase):
    def test_every_case_runs_exactly_once(self):
        runs = [selected(w) for w in invocations()]
        flat = [c for cases, _ in runs for c in cases]
        self.assertEqual(sorted(flat), sorted(run.CASES))
        self.assertEqual(len(flat), len(set(flat)))

    def test_one_owner_of_generator_and_runtime_checks(self):
        self.assertEqual([owns for _, owns in map(selected, invocations())].count(True), 1)

    def test_unknown_case_is_refused(self):
        import tempfile
        from unittest.mock import patch
        for flag in ('--only', '--except'):
            with tempfile.TemporaryDirectory() as out, \
                 patch.object(sys, 'argv', ['run.py', '--compiler', 'unused.jar', '--out', out, flag, 'nonesuch']):
                with self.assertRaisesRegex(AssertionError, 'unknown contract case'):
                    run.main()

    def test_a_dropped_case_is_detected(self):
        text = GATES.read_text().replace('--cases method-size', '--cases method-size-gone')
        runs = [selected(w) for w in invocations(text)]
        flat = [c for cases, _ in runs for c in cases]
        self.assertNotEqual(sorted(flat), sorted(run.CASES))

    def test_a_repeated_case_is_detected(self):
        text = GATES.read_text().replace('--except actual-goldens method-size', '--except actual-goldens')
        flat = [c for cases, _ in map(selected, invocations(text)) for c in cases]
        self.assertNotEqual(len(flat), len(set(flat)))


if __name__ == '__main__':
    unittest.main()
