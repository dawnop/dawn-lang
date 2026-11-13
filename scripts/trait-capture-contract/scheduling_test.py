#!/usr/bin/env python3
"""Exercise complete case scheduling and failures without compiler builds."""
import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import summary_cases as suite
import run as harness
import controls_shards as shards


class CaptureDispatch(unittest.TestCase):
    """A selected Capture family requires every complete selector."""

    @classmethod
    def setUpClass(cls):
        import yaml
        cls.workflow = yaml.safe_load((harness.ROOT / '.github/workflows/gates.yml').read_text())
        cls.step = next(step for step in cls.workflow['jobs']['mutant-shards-complete']['steps']
                        if step.get('id') == 'families')
        path = harness.ROOT / 'scripts/gates-external/gatesplan.py'
        spec = importlib.util.spec_from_file_location('capture_dispatch_plan', path)
        cls.plan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.plan)

    def dispatch(self, results, jvm="skipped skipped"):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'outputs'
            env = dict(os.environ, GITHUB_OUTPUT=str(output), CAPTURE=results)
            for key, expression in self.step['env'].items():
                if key == 'CAPTURE_JVM':
                    env[key] = jvm
                elif key != 'CAPTURE':
                    env[key] = ' '.join(['skipped'] * expression.count('.result'))
            result = subprocess.run(['bash', '-eu', '-o', 'pipefail', '-c', self.step['run']],
                                    env=env, text=True, capture_output=True)
            values = dict(line.split('=', 1) for line in output.read_text().splitlines())
            return result, values

    def test_unselected_capture_does_not_claim_a_union(self):
        result, values = self.dispatch('skipped skipped skipped')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values['capture_ran'], 'false')
        self.assertEqual(values['any_ran'], 'false')

    def test_partial_or_failed_capture_cannot_hide_a_selector(self):
        for results in ('success success skipped', 'success failure success',
                        'skipped skipped success'):
            with self.subTest(results=results):
                result, _ = self.dispatch(results)
                self.assertNotEqual(result.returncode, 0)

    def test_complete_capture_requires_the_union(self):
        result, values = self.dispatch('success success success')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values['capture_ran'], 'true')
        self.assertEqual(values['any_ran'], 'true')

    def test_source_dispatch_requires_both_complete_selectors(self):
        for result in ('success skipped', 'skipped success', 'success failure'):
            with self.subTest(result=result):
                process, _ = self.dispatch('skipped skipped skipped', result)
                self.assertNotEqual(process.returncode, 0)

    def test_complete_or_unselected_source_dispatch(self):
        for result, expected in [('success success', 'true'), ('skipped skipped', 'false')]:
            process, values = self.dispatch('skipped skipped skipped', result)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(values['capture_jvm_ran'], expected)
            self.assertEqual(values['any_ran'], expected)

    def test_existing_expression_grammar(self):
        for key in ('all', 'jobs', 'unreviewed'):
            with self.assertRaises(self.plan.PlanError):
                self.plan._env('fixture', {'PLAN': '${{ needs.plan.outputs.' + key + ' }}'}, ['plan'])
        self.plan.parse((harness.ROOT / '.github/workflows/gates.yml').read_text(),
                        (harness.ROOT / '.github/actions/dawn-toolchain/action.yml').read_text())

class CapturePlanning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = harness.ROOT / 'scripts/gate-map/plan.py'
        spec = importlib.util.spec_from_file_location('capture_family_plan', path)
        cls.plan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.plan)

    def view(self, selectors=('1/3', '2/3', '3/3'), observers=('control-a',)):
        gates = [SimpleNamespace(id=f'{job} / selector', workflow='gates.yml',
                                commands=[f'python3 scripts/trait-capture-contract/run.py --controls-shard {selector} --coverage-dir receipts'])
                 for job, selector in zip(('control-a', 'control-b', 'control-c'), selectors)]
        gates.append(SimpleNamespace(id='unrelated / fixture', workflow='gates.yml', commands=['echo complete']))
        gm = SimpleNamespace(gates=gates, unread=set(), by_path={}, unseen=lambda: [],
                             tree=SimpleNamespace(fileset={'fixture'}),
                             verdict=lambda *_: [SimpleNamespace(level='exact', gate_id=f'{job} / selector')
                                                for job in observers])
        if observers == ('unrelated',):
            gm.verdict = lambda *_: [SimpleNamespace(level='exact', gate_id='unrelated / fixture')]
        return self.plan.MapView(gm, None, ['control-a', 'control-b', 'control-c', 'unrelated'])

    def test_one_companion_selects_the_complete_family(self):
        for job in ('control-a', 'control-b', 'control-c'):
            with self.subTest(job=job):
                self.assertEqual(self.view(observers=(job,)).jobs_for('fixture'),
                                 {'control-a', 'control-b', 'control-c'})

    def test_unrelated_input_keeps_its_subset(self):
        self.assertEqual(self.view(observers=('unrelated',)).jobs_for('fixture'), {'unrelated'})

    def test_missing_duplicate_or_wrong_selector_cannot_make_a_partial_plan(self):
        for selectors in [('1/3', '2/3'), ('1/3', '2/3', '2/3'), ('1/3', '2/3', '4/3'),
                          ('1/3', '2/3', '3/4')]:
            with self.subTest(selectors=selectors), self.assertRaises(ValueError):
                self.view(selectors=selectors)


class SourcePlanning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = harness.ROOT / 'scripts/gate-map/plan.py'
        spec = importlib.util.spec_from_file_location('source_family_plan', path)
        cls.plan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.plan)

    def source_view(self, selectors=('1/2', '2/2'), backend='jvm', overlap=False):
        controls = ('shared', 'control-b', 'control-c') if overlap else ()
        fronts = ('shared', 'front-b') if overlap else ('front-a', 'front-b')
        gates = [SimpleNamespace(id=f'{job} / calls', workflow='gates.yml', commands=[
            f'python3 scripts/trait-capture-contract/run.py --calls-backend {backend} --calls-shard {part} --coverage-dir receipts'])
                 for job, part in zip(fronts, selectors)]
        gates.extend(SimpleNamespace(id=f'{job} / controls', workflow='gates.yml', commands=[
            f'python3 scripts/trait-capture-contract/run.py --controls-shard {i}/3 --coverage-dir receipts'])
                     for i, job in enumerate(controls, 1))
        observer = fronts[-1]
        gm = SimpleNamespace(gates=gates, unread=set(), by_path={}, unseen=lambda: [],
                             tree=SimpleNamespace(fileset={'fixture'}),
                             verdict=lambda *_: [SimpleNamespace(level='exact', gate_id=f'{observer} / calls')])
        return self.plan.MapView(gm, None, list(dict.fromkeys((*fronts, *controls))))

    def test_a_source_companion_requires_both_source_selectors(self):
        self.assertEqual(self.source_view().jobs_for('fixture'), {'front-a', 'front-b'})

    def test_overlapping_source_and_private_families_reach_a_complete_plan(self):
        self.assertEqual(self.source_view(overlap=True).jobs_for('fixture'),
                         {'shared', 'control-b', 'control-c', 'front-b'})

    def test_missing_repeated_or_wrong_source_selectors_are_refused(self):
        for selectors in [('1/2',), ('1/2', '1/2'), ('1/2', '3/2'), ('1/2', '2/3')]:
            with self.subTest(selectors=selectors), self.assertRaises(ValueError):
                self.source_view(selectors=selectors)
        with self.assertRaises(ValueError):
            self.source_view(backend='native')


class Scheduling(unittest.TestCase):
    def test_receipt_follows_success_and_temporary_cleanup(self):
        context = dict(commit='a' * 40, inputs='b' * 64, producer='c' * 64, plan='d' * 64)
        selected = shards.plan()[0]
        cases, embedded = shards.baseline_cases(selected)
        completed = dict(mutants=[dict(name=n, compiler_built=True, owning_test_failed=True) for n in selected],
                         tests=shards.baseline_tests(), subwitness=True, cases=cases, embedded=embedded)
        observed = []
        real_record = shards.record
        def execute(out, names, jobs):
            self.assertEqual(names, selected)
            self.assertEqual(jobs, 2)
            self.assertTrue(out.is_dir())
            observed.append(out)
            return completed
        def record(*args):
            self.assertFalse(observed[-1].exists())
            return real_record(*args)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'coverage'
            argv = ['run.py', '--controls-shard', '1/3', '--coverage-dir', str(destination)]
            with patch.object(harness.sys, 'argv', argv), patch.object(harness, 'controls', execute), \
                    patch.object(shards, 'input_identity', return_value=context), \
                    patch.object(shards, 'record', record), contextlib.redirect_stdout(io.StringIO()):
                harness.main()
                self.assertEqual(len(list(destination.glob('*.json'))), 1)
                with self.assertRaises(FileExistsError):
                    harness.main()

    def test_failed_selector_cannot_write_a_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'coverage'
            argv = ['run.py', '--controls-shard', '1/3', '--coverage-dir', str(destination)]
            with patch.object(harness.sys, 'argv', argv), \
                    patch.object(harness, 'controls', side_effect=RuntimeError('producer failed')), \
                    patch.object(shards, 'input_identity', return_value={}), \
                    patch.object(shards, 'record') as record, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'producer failed'):
                    harness.main()
                record.assert_not_called()
                self.assertFalse(destination.exists())

    def controls(self, broken=False):
        names = list(harness.MUTATIONS)[:4]
        first_wave = threading.Barrier(4, timeout=3)
        built = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for part in ("selfhost", "compiler-plan", "std", "packages"):
                (root / part).mkdir()
            out = root / "out"
            out.mkdir()

            def command(args, output, expected=0, **kwargs):
                text = ""
                if output.name == "build.log":
                    first_wave.wait()
                    built.append((output.parent.name, args[-1]))
                if output.name == "test.log":
                    name = output.parent.name
                    module = harness.MODULES.get(name, "check/trait_capture_test")
                    text = ("PASS  " if broken else "FAIL  ") + module + " :: " + harness.OWNERS[name]
                    code = 1
                else:
                    code = expected
                if output.name == "subwitness-baseline.log":
                    text = "error: impl subwitness support is not covered"
                output.write_text(text)
                return SimpleNamespace(returncode=code, stdout=text), 0.001

            output = io.StringIO()
            with patch.object(harness, "ROOT", root), patch.object(harness, "apply"), \
                    patch.object(harness.subprocess, "check_output", return_value="java"), \
                    patch.object(harness, "run", command), contextlib.redirect_stdout(output):
                harness.controls(out, names, 4)
            rows = json.loads((out / "results.json").read_text())
            self.assertEqual([r["name"] for r in rows], names)
            self.assertCountEqual([n for n, _ in built], names)
            self.assertEqual(len({p for _, p in built}), 4, "private compilers cannot share an output")
            self.assertTrue(all(r["compiler_built"] and r["owning_test_failed"] for r in rows))
            timings = [json.loads(line.removeprefix("CAPTURE_TELEMETRY "))
                       for line in output.getvalue().splitlines()
                       if line.startswith("CAPTURE_TELEMETRY ")]
            self.assertEqual(len(timings), 1, "private result recording must be timed")
            self.assertEqual(timings[0]["phase"], "private_results")
            self.assertGreaterEqual(timings[0]["seconds"], 0)

    def test_private_mutant_builds_and_owners(self):
        self.controls()

    def test_unrelated_red_cannot_replace_the_owning_failure(self):
        with self.assertRaisesRegex(RuntimeError, "owning executed test did not fail"):
            self.controls(broken=True)

    def exercise(self, broken=None):
        cases = {f"case_{i}": ({"exit": 0, "stdout": f"value {i}\n"} if i % 2 == 0
                              else {"exit": 1, "diagnostic": f"refusal {i}"})
                 for i in range(8)}
        lock = threading.Lock()
        first_wave = threading.Barrier(4, timeout=3)
        active = maximum = completed = 0
        seen = []
        checked = set()

        def command(args, output, expected=0, **kwargs):
            nonlocal active, maximum, completed
            action = args[1]
            case = Path(args[-1]).stem
            with lock:
                active += 1
                maximum = max(maximum, active)
                seen.append((action, case, output))
                if action == "run":
                    self.assertIn(case, checked)
            try:
                if action == "check" and int(case[-1]) < 4:
                    first_wave.wait()
                time.sleep(0.002 * (8 - int(case[-1])))
                contract = cases[case]
                stdout = contract.get("stdout", str(args[-1]) + ": " + contract.get("diagnostic", ""))
                if broken == (action, case):
                    stdout = "wrong answer"
                output.write_text(stdout)
                if action == "check":
                    checked.add(case)
                return SimpleNamespace(returncode=contract["exit"], stdout=stdout), 0.001
            finally:
                with lock:
                    active -= 1
                    completed += 1

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            with patch.object(suite, "CASES", cases), contextlib.redirect_stdout(output):
                try:
                    suite.matrix(command, [("fixture", ["compiler"])], destination, jobs=4)
                finally:
                    self.assertEqual(active, 0, "the executor must join failed siblings before cleanup")
            rows = json.loads((destination / "summary-cases.json").read_text())
            self.assertEqual([r["case"] for r in rows], list(cases))
            self.assertTrue(all(r["checked"] and r["ran"] for r in rows))
            self.assertEqual(maximum, 4)
            self.assertEqual(completed, 16)
            self.assertCountEqual([(a, c) for a, c, _ in seen],
                                  [(a, c) for c in cases for a in ("check", "run")])
            self.assertEqual(len({p for _, _, p in seen}), 16, "every command needs a private log")
            self.assertEqual([line for line in output.getvalue().splitlines() if line.startswith("PASS ")],
                             [f"PASS fixture {c}: check and run" for c in cases])
            timings = [json.loads(line.removeprefix("CAPTURE_TELEMETRY "))
                       for line in output.getvalue().splitlines()
                       if line.startswith("CAPTURE_TELEMETRY ")]
            self.assertEqual(len(timings), 1, "native and JVM result recording must be timed")
            self.assertEqual(timings[0]["phase"], "fixture_case_results")
            self.assertGreaterEqual(timings[0]["seconds"], 0)

    def test_whole_cases_and_deterministic_results(self):
        self.exercise()

    def test_accepted_case_keeps_its_runtime_oracle(self):
        with self.assertRaisesRegex(RuntimeError, "runtime output mismatch"):
            self.exercise(("run", "case_0"))

    def test_refused_case_keeps_its_check_oracle(self):
        with self.assertRaisesRegex(RuntimeError, "owning source refusal"):
            self.exercise(("check", "case_1"))

    def test_refused_case_keeps_its_run_oracle(self):
        with self.assertRaisesRegex(RuntimeError, "run did not retain the check refusal"):
            self.exercise(("run", "case_1"))


class SourceSelectors(unittest.TestCase):
    def context(self):
        return dict(commit='a' * 40, inputs='b' * 64, producer='c' * 64, plan='d' * 64)

    def source_rows(self):
        return [shards.calls_receipt(i, dict(
            baseline_checked=True, baseline_ran=True,
            cases=[dict(case=n, checked=True, ran=True, exit=suite.CASES[n]['exit'])
                   for n in names]), self.context())
                for i, names in enumerate(shards.calls_plan(), 1)]

    def write(self, directory, rows):
        for path in directory.glob('capture-calls-jvm-*.json'):
            path.unlink()
        for i, row in enumerate(rows):
            (directory / f'capture-calls-jvm-{i}.json').write_text(json.dumps(row))

    def test_private_receipts_cannot_stand_in_for_missing_source_selectors(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for i, names in enumerate(shards.plan(), 1):
                cases, embedded = shards.baseline_cases(names)
                row = shards.receipt(i, dict(
                    mutants=[dict(name=n, compiler_built=True, owning_test_failed=True) for n in names],
                    tests=shards.baseline_tests(), subwitness=True, cases=cases, embedded=embedded),
                    self.context())
                (directory / f'capture-controls-{i}.json').write_text(json.dumps(row))
            checker = getattr(shards, 'check_calls', shards.check)
            with self.assertRaisesRegex(ValueError, 'JVM'):
                checker(directory, self.context())

    def test_complete_source_union_and_every_refusal(self):
        import copy
        rows = self.source_rows()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['cases'] for r in rows))
        self.assertCountEqual([c['case'] for r in rows for c in r['cases']], list(suite.CASES))
        controls = [
            lambda r: r.pop(), lambda r: r.append(r[0]),
            lambda r: r[0].update(shard=0), lambda r: r[0].update(shards=3),
            lambda r: r[0].update(backend='native'),
            lambda r: r[0]['identity'].update(inputs='x' * 64),
            lambda r: r[0]['identity'].update(producer='x' * 64),
            lambda r: r[0]['cases'].pop(),
            lambda r: r[0]['cases'].append(r[0]['cases'][0]),
            lambda r: r[0]['cases'][0].update(checked=False),
            lambda r: r[0]['cases'][0].update(ran=False),
            lambda r: r[0]['cases'][0].update(exit=42),
            lambda r: r[0]['cases'][0].update(exit=True),
            lambda r: r[0].update(baseline_checked=False),
            lambda r: r[0].update(baseline_ran=False),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.write(directory, rows)
            shards.check_calls(directory, self.context())
            for mutate in controls:
                broken = copy.deepcopy(rows)
                mutate(broken)
                self.write(directory, broken)
                with self.assertRaises(ValueError):
                    shards.check_calls(directory, self.context())

    def test_source_receipt_follows_success_and_cleanup(self):
        selected = shards.calls_plan()[0]
        observed = []
        real_record = shards.record_calls
        def execute(out, backend, jobs, names=None):
            self.assertEqual((backend, jobs, names), ('jvm', 1, selected))
            self.assertTrue(out.is_dir())
            observed.append(out)
            return [dict(backend='jvm', case=n, checked=True, ran=True,
                         exit=suite.CASES[n]['exit'], started=1, ended=2) for n in names]
        def record(*args):
            self.assertFalse(observed[-1].exists())
            return real_record(*args)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'coverage'
            argv = ['run.py', '--calls-backend', 'jvm', '--calls-shard', '1/2',
                    '--coverage-dir', str(destination)]
            with patch.object(harness.sys, 'argv', argv), patch.object(harness, 'calls', execute), \
                    patch.object(shards, 'input_identity', return_value=self.context()), \
                    patch.object(shards, 'record_calls', record), contextlib.redirect_stdout(io.StringIO()):
                harness.main()
                self.assertEqual(len(list(destination.glob('capture-calls-jvm-*.json'))), 1)
                with self.assertRaises(FileExistsError):
                    harness.main()

    def test_failed_source_selector_cannot_write_a_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'coverage'
            argv = ['run.py', '--calls-backend', 'jvm', '--calls-shard', '2/2',
                    '--coverage-dir', str(destination)]
            with patch.object(harness.sys, 'argv', argv), \
                    patch.object(harness, 'calls', side_effect=RuntimeError('source failed')), \
                    patch.object(shards, 'input_identity', return_value=self.context()), \
                    patch.object(shards, 'record_calls') as record, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'source failed'):
                    harness.main()
                record.assert_not_called()
                self.assertFalse(destination.exists())

    def test_whole_cases_remain_checked_run_and_ordered_in_both_halves(self):
        calls = []
        def execute(args, output, expected=0, **kwargs):
            name = Path(args[-1]).stem
            contract = suite.CASES[name]
            calls.append((args[1], name))
            text = contract.get('stdout', str(args[-1]) + ': ' + contract.get('diagnostic', ''))
            output.write_text(text)
            return SimpleNamespace(returncode=expected, stdout=text), 0.001
        rows = []
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            for i, names in enumerate(shards.calls_plan()):
                out = Path(temporary) / str(i)
                out.mkdir()
                part = suite.matrix(execute, [('jvm', ['compiler'])], out, jobs=2, names=names)
                self.assertEqual([r['case'] for r in part], names)
                rows.extend(part)
        self.assertCountEqual([r['case'] for r in rows], list(suite.CASES))
        self.assertCountEqual(calls, [(a, n) for n in suite.CASES for a in ('check', 'run')])

    def test_each_source_selector_retains_the_ordinary_call_fixture(self):
        selected = shards.calls_plan()[0]
        for broken in (False, True):
            actions = []
            def execute(args, output, **kwargs):
                self.assertEqual(args[-1], harness.CALLS)
                actions.append(args[1])
                return SimpleNamespace(stdout='wrong' if broken else 'trait capture calls\n'), 0.001
            with tempfile.TemporaryDirectory() as temporary, \
                    patch.object(harness, 'run', execute), \
                    patch.object(harness.subprocess, 'check_output', return_value='java'), \
                    patch.object(harness, 'matrix', return_value=[]) as matrix, \
                    contextlib.redirect_stdout(io.StringIO()):
                if broken:
                    with self.assertRaisesRegex(RuntimeError, 'call fixture'):
                        harness.calls(Path(temporary), 'jvm', 1, names=selected)
                    matrix.assert_not_called()
                else:
                    harness.calls(Path(temporary), 'jvm', 1, names=selected)
                    self.assertEqual(matrix.call_args.kwargs['names'], selected)
                self.assertEqual(actions, ['check', 'run'])

    def test_empty_duplicate_or_unknown_source_selection_cannot_execute(self):
        first = next(iter(suite.CASES))
        with tempfile.TemporaryDirectory() as temporary, patch.object(suite, 'observe') as observe:
            for names in ([], [first, first], ['unknown']):
                with self.assertRaises(ValueError):
                    suite.matrix(None, [('jvm', ['compiler'])], Path(temporary), names=names)
            observe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
