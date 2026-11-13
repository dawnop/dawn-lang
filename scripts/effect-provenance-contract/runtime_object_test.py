#!/usr/bin/env python3
"""Fixed artifact identity refusals, without building a compiler or runtime."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from native_runtime import RuntimeObject


class RuntimeObjectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = self.root/'runtime/c'
        self.runtime.mkdir(parents=True)
        (self.runtime/'dawn_rt.c').write_text('runtime source\n')
        (self.runtime/'dawn_rt.h').write_text('runtime header\n')
        self.compiler = self.root/'cc'
        self.compiler.write_text('compiler identity\n')
        self.compiler.chmod(0o755)
        self.system_header = self.root/'system.h'
        self.system_header.write_text('system header\n')
        self.out = self.root/'out'
        self.out.mkdir()
        self.prefix = [str(self.compiler), '-std=c11', '-O2', '-fwrapv',
                       '-fexceptions', '-fno-strict-aliasing', '-ffp-contract=off',
                       '-pthread', '-I'+str(self.runtime)]
        self.commands = []
        self.exit = 0
        self.during = None
        self.cache = RuntimeObject(self.runtime, self.out, self.command)

    def command(self, label, command):
        command = list(map(str, command))
        self.commands.append((label, command))
        if '-M' in command:
            return SimpleNamespace(returncode=0, stderr='', stdout='runtime-object: '+
                                   ' '.join(map(str,[self.runtime/'dawn_rt.c',self.runtime/'dawn_rt.h',self.system_header]))+'\n')
        if '-o' in command:
            Path(command[command.index('-o')+1]).write_bytes(b'object or artifact bytes')
        if self.during is not None:
            self.during()
        return SimpleNamespace(returncode=self.exit, stdout='', stderr='fixture compile result')

    def test_same_inputs_reuse_one_object(self):
        first = self.cache.get(self.prefix)
        self.assertEqual(first, self.cache.get(self.prefix))
        self.cache.confirm(self.prefix)
        self.assertEqual(self.cache.builds, 1)
        build = next(c for label,c in self.commands if label=='runtime-object-build')
        self.assertEqual(build, [*self.prefix, '-c', str(self.runtime/'dawn_rt.c'),
                                              '-o', str(first.with_suffix('.pending.o'))])

    def test_source_change_rebuilds(self):
        self.cache.get(self.prefix)
        (self.runtime/'dawn_rt.c').write_text('changed runtime\n')
        self.cache.get(self.prefix)
        self.assertEqual(self.cache.builds, 2, 'Reused a stale runtime source')

    def test_header_change_rebuilds(self):
        self.cache.get(self.prefix)
        (self.runtime/'dawn_rt.h').write_text('changed header\n')
        self.cache.get(self.prefix)
        self.assertEqual(self.cache.builds, 2, 'Reused a stale runtime header')

    def test_compiler_change_rebuilds(self):
        self.cache.get(self.prefix)
        self.compiler.write_text('different compiler bytes\n')
        self.cache.get(self.prefix)
        self.assertEqual(self.cache.builds, 2, 'Reused an object from another compiler')

    def test_system_header_change_rebuilds(self):
        self.cache.get(self.prefix)
        self.system_header.write_text('changed system header\n')
        self.cache.get(self.prefix)
        self.assertEqual(self.cache.builds, 2, 'Reused a stale system header')

    def test_flags_change_rebuilds(self):
        self.cache.get(self.prefix)
        self.cache.get([*self.prefix, '-DCHANGED=1'])
        self.assertEqual(self.cache.builds, 2, 'Reused an object with different flags')

    def test_object_change_refused(self):
        self.cache.get(self.prefix).write_bytes(b'tampered object')
        with self.assertRaisesRegex(RuntimeError, 'runtime object changed'):
            self.cache.get(self.prefix)

    def test_inputs_change_during_compile_refused(self):
        self.during = lambda: (self.runtime/'dawn_rt.h').write_text('changed during compile')
        with self.assertRaisesRegex(RuntimeError, 'inputs changed during compilation'):
            self.cache.get(self.prefix)
        self.assertIsNone(self.cache.key)
        self.assertEqual(self.cache.builds, 0)

    def test_inputs_change_during_link_refused(self):
        self.cache.get(self.prefix)
        (self.runtime/'dawn_rt.h').write_text('changed during link')
        with self.assertRaisesRegex(RuntimeError, 'inputs changed during linking'):
            self.cache.confirm(self.prefix)

    def test_failed_compile_not_cached(self):
        self.exit = 1
        with self.assertRaisesRegex(RuntimeError, 'compilation failed'):
            self.cache.get(self.prefix)
        self.assertIsNone(self.cache.key)
        self.exit = 0
        self.cache.get(self.prefix)
        self.assertEqual(sum(label=='runtime-object-build'for label,c in self.commands), 2)
        self.assertEqual(self.cache.builds, 1)

    def test_fresh_invocation_compiles_again(self):
        self.cache.get(self.prefix)
        other = self.root/'other'
        other.mkdir()
        RuntimeObject(self.runtime, other, self.command).get(self.prefix)
        self.assertEqual(sum(label=='runtime-object-build'for label,c in self.commands), 2)

    def test_case_link_flags_equal_runtime_compile_flags(self):
        import run
        args = SimpleNamespace(out=self.out, cc=str(self.compiler), java='java',
                               compiler=self.root/'compiler.jar', reuse_runtime=True)
        with patch.object(run, 'ROOT', self.root):
            invocation = run.Run(args)
            invocation.command = self.command
            invocation.runtime_object.command = self.command
            for name in ['first', 'second']:
                invocation.build(name, self.root/(name+'.dawn'), 'native')
        runtime = next(c for label,c in self.commands if label=='runtime-object-build')
        for label,command in self.commands:
            if label in ['first-native-cc', 'second-native-cc']:
                self.assertEqual(command[:len(self.prefix)], self.prefix)
                self.assertEqual(runtime[:len(self.prefix)], self.prefix)
                self.assertEqual(command[-4], str(self.out/'verified-runtime.o'))
        self.assertEqual(invocation.runtime_object.builds, 1)


if __name__ == '__main__':
    unittest.main()
