#!/usr/bin/env python3
"""Pin the timing recovery without relying on scheduler luck or weakening heap checks."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("heap_contract", HERE / "run.py")
contract = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = contract
spec.loader.exec_module(contract)
bench = contract.load_module(contract.BENCH, "heap_sampling_bench")


class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.identity = bench.ProcessIdentity(42, 100)
        self.same = bench.ProcessStat(self.identity, 1)
        self.changed = bench.ProcessStat(bench.ProcessIdentity(42, 101), 1)
        self.runner = Mock(return_value=subprocess.CompletedProcess(
            [], 0, "-XX:MaxHeapSize=402653184\n", ""))

    def query(self, states):
        return bench.query_max_heap(Path("jcmd"), self.identity,
                                    identity_reader=Mock(side_effect=states),
                                    runner=self.runner)

    def test_live_sample(self):
        self.assertEqual(self.query([self.same, self.same]), 402653184)

    def test_exit_before_attach(self):
        with self.assertRaisesRegex(bench.HeapSampleWindowMiss, "before jcmd"):
            self.query([None])
        self.runner.assert_not_called()

    def test_exit_during_attach_records_latency_and_discards_flags(self):
        with patch.object(bench.time, "monotonic", side_effect=[10, 16.5]):
            with self.assertRaisesRegex(bench.HeapSampleWindowMiss, "during jcmd") as raised:
                self.query([self.same, None])
        self.assertEqual(raised.exception.elapsed_seconds, 6.5)

    def test_pid_reuse_is_not_retryable_before_or_after_attach(self):
        for states in ([self.changed], [self.same, self.changed]):
            with self.subTest(states=states):
                with self.assertRaisesRegex(bench.BenchError, "changed identity") as raised:
                    self.query(states)
                self.assertNotIsInstance(raised.exception, bench.HeapSampleWindowMiss)

    def test_timeout_only_becomes_retryable_if_target_disappeared(self):
        self.runner.side_effect = subprocess.TimeoutExpired("jcmd", 8)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.query([self.same, self.same])
        with self.assertRaises(bench.HeapSampleWindowMiss):
            self.query([self.same, None])
        with self.assertRaisesRegex(bench.BenchError, "changed identity") as raised:
            self.query([self.same, self.changed])
        self.assertNotIsInstance(raised.exception, bench.HeapSampleWindowMiss)

    def test_live_attach_failure_and_invalid_flags_stay_fatal(self):
        for result in (subprocess.CompletedProcess([], 1, "", "denied"),
                       subprocess.CompletedProcess([], 0, "no heap flag", "")):
            self.runner.return_value = result
            with self.assertRaises(bench.BenchError) as raised:
                self.query([self.same, self.same])
            self.assertNotIsInstance(raised.exception, bench.HeapSampleWindowMiss)

    def profile(self, outcomes):
        profiler = Mock(side_effect=outcomes)
        with tempfile.TemporaryDirectory() as raw, \
                patch.object(bench, "profile_command", profiler), \
                patch.object(bench, "resolve_toolchain", return_value=SimpleNamespace(
                    java=Path("/jdk/bin/java"), jcmd=Path("/jdk/bin/jcmd"))), \
                patch.object(contract, "write_fixture_source") as writer:
            result = contract.profile_case(bench, name="test", launcher=Path("dawn"),
                fixture=Path(raw) / "fixture.dawn", dependency=Path("empty.jar"),
                source_root=Path(raw), jvm_opts=None)
            return result, profiler, writer

    def result(self, heap=123):
        return SimpleNamespace(returncode=0, stdout=contract.FIXTURE_MARKER,
            complete_overlap_samples=1, roles={
                "compiler": {"process_count": 1, "max_heap_bytes": heap},
                "dependency_reexec": {"process_count": 1, "max_heap_bytes": heap + 1},
            })

    def test_miss_replays_with_adaptive_lifetime_and_keeps_mismatched_heap(self):
        result, profiler, writer = self.profile([
            bench.HeapSampleWindowMiss("exited during jcmd attach", 6.5), self.result()])
        self.assertEqual([call.args[1] for call in writer.call_args_list], [4000, 14000])
        self.assertEqual(profiler.call_count, 2)
        self.assertEqual(profiler.call_args.kwargs["timeout"], 44)
        self.assertEqual((result.parent_heap_bytes, result.child_heap_bytes), (123, 124))

    def test_no_retry_for_successful_sample_or_other_failures(self):
        _, profiler, _ = self.profile([self.result()])
        self.assertEqual(profiler.call_count, 1)
        for error in (bench.BenchError("changed identity"),
                      bench.BenchError("attach denied"), subprocess.TimeoutExpired("jcmd", 8)):
            with self.assertRaises(type(error)) as raised:
                self.profile([error, AssertionError("must not retry")])
            self.assertIs(raised.exception, error)

    def test_retries_are_bounded_and_lifetime_is_capped(self):
        miss = bench.HeapSampleWindowMiss("exited", 100)
        result, profiler, writer = self.profile([miss, miss, self.result()])
        self.assertEqual([call.args[1] for call in writer.call_args_list], [4000, 32000, 32000])
        self.assertEqual(profiler.call_count, 3)
        with self.assertRaisesRegex(contract.ContractError, "after 3 attempts"):
            self.profile([miss, miss, miss, AssertionError("unbounded retry")])


if __name__ == "__main__":
    unittest.main()
