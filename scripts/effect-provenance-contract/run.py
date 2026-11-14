#!/usr/bin/env python3
"""Compile actual programs on both backends and judge independent expectations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from builder_oracle import judge as judge_builder
from tree_oracle import judge as judge_tree

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


class Run:
    def __init__(self, args):
        self.args = args
        self.out = args.out.resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.results = []

    def command(self, label, command):
        result = subprocess.run([str(x) for x in command], cwd=ROOT,
                                capture_output=True, text=True, timeout=self.args.timeout,
                                env=dict(os.environ, DAWN_PKG_CACHE=str(self.out/'pkgcache')))
        (self.out/(label+'.stdout')).write_text(result.stdout)
        (self.out/(label+'.stderr')).write_text(result.stderr)
        return result

    def compiler(self, *arguments):
        return [self.args.java, '-Xss512m', '-Xmx2g', '-jar', self.args.compiler,
                *arguments, '--std', getattr(self, 'std', ROOT/'std')]

    def build(self, name, source, backend, cc_extra=()):
        label = name+'-'+backend
        target = self.out/(label+('.jar' if backend == 'jvm' else '.c'))
        result = self.command(label+'-build', self.compiler(
            'build' if backend == 'jvm' else '__emitc', source, '-o', target))
        assert result.returncode == 0, (label, 'compile', result.stdout, result.stderr)
        if backend == 'native':
            exe = self.out/(label+'.bin')
            result = self.command(label+'-cc', [self.args.cc, '-std=c11', '-O2',
                '-fwrapv', '-fexceptions', '-fno-strict-aliasing', '-ffp-contract=off',
                '-pthread', '-I'+str(ROOT/'runtime/c'), target,
                ROOT/'runtime/c/dawn_rt.c', '-lm', *cc_extra, '-o', exe])
            assert result.returncode == 0, (label, 'C compile', result.stderr[-6000:])
            command = [exe]
        else:
            command = [self.args.java, '-Xverify:all', '-jar', target]
        return command

    def execute(self, name, source, judge, arguments=(), cc_extra=()):
        outputs = []
        for backend in ['jvm', 'native']:
            command = self.build(name, source, backend, cc_extra)
            result = self.command(name+'-'+backend+'-run', command+list(arguments))
            assert result.returncode == 0, (name, backend, 'run', result.stderr)
            judge(result.stdout)
            if '\nS1\t' in result.stdout or result.stdout.startswith('S1\t'):
                from snapshot_text import exports, negative_controls
                for raw, _value in exports(result.stdout):
                    if raw.startswith('S1\t'): negative_controls(raw)
            outputs.append(result.stdout)
            self.results.append({'case': name, 'backend': backend, 'passed': True})
            print('PASS', backend, name, flush=True)
        assert outputs[0] == outputs[1], (name, 'backend protocol differs')

    def rejection(self, name, source, message):
        for backend in ['jvm', 'native']:
            result = self.command(name+'-'+backend+'-reject', self.compiler(
                'build' if backend == 'jvm' else '__emitc', source,
                '-o', self.out/(name+'-'+backend+'.refused')))
            assert result.returncode != 0, (name, backend, 'accepted')
            assert message in result.stderr+result.stdout, (name, backend, message,
                                                          result.stdout, result.stderr)
            print('PASS', backend, name, 'precise refusal', flush=True)
            self.results.append({'case': name, 'backend': backend, 'passed': True})


def exact(expected):
    def judge(actual):
        assert actual == expected, ('expected', expected, 'actual', actual)
    return judge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--java', default='java')
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--only', nargs='*')
    parser.add_argument('--timeout', type=int, default=900,
                        help='seconds allowed per subprocess; a stall fails instead of waiting')
    args = parser.parse_args()
    args.compiler = args.compiler.resolve()
    run = Run(args)
    cases = ['continuation-modes', 'actual-goldens', 'cli-preview', 'w3-resources', 'w3-local-observer', 'w3-mutants', 'w3-foreign', 'w3-bounded', 'w3-control-matrix', 'method-size', 'snapshot', 'snapshot_bulk', 'snapshot_metadata', 'snapshot_defaults', 'snapshot_control', 'snapshot_flags', 'builder', 'modes', 'callbacks', 'bracket_exits', 'generic_capture', 'builtin_functions', 'bounded_functions', 'associated', 'origin_api', 'checkpoints', 'nested', 'shadow', 'evidence', 'unwind', 'staged', 'modules', 'packages', 'shared-probe', 'observed-bench', 'escape', 'runtime-errors', 'w3', 'mutations']
    selected = args.only if args.only is not None else cases
    for name in selected:
        if name == 'continuation-modes':
            run.execute(name,HERE/'continuation_modes.dawn',lambda output: None if output.startswith('42 saved Plain mode stays Plain under an observed driver\n') else (_ for _ in ()).throw(AssertionError(output)))
        elif name == 'actual-goldens':
            from full_golden import check
            check(run)
        elif name == 'cli-preview':
            from preview_matrix import check
            check(run)
        elif name == 'w3-resources':
            from w3_matrix import resources
            resources(run)
        elif name == 'w3-local-observer':
            run.execute(name, HERE/'local_observer.dawn', lambda output: None if output.startswith('42 Plain activation restores its later observer\n') else (_ for _ in ()).throw(AssertionError(output)))
        elif name == 'w3-mutants':
            from w3_matrix import mutants
            mutants(run)
        elif name == 'w3-foreign':
            from w3_matrix import foreign
            foreign(run)
        elif name == 'w3-bounded':
            from w3_matrix import bounded
            bounded(run)
        elif name == 'w3-control-matrix':
            from w3_matrix import control_matrix
            control_matrix(run)
        elif name == 'method-size':
            from method_size import check
            check(run)
        elif name == 'snapshot_metadata':
            from snapshot_matrix import snapshot_metadata
            snapshot_metadata(run)
        elif name == 'snapshot_bulk':
            def judge_bulk(output):
                assert output.startswith('42 bulk scalars equal immutable rows across rollback and scopes\n')
            run.execute(name, HERE/'snapshot_bulk.dawn', judge_bulk)
            for backend in ['jvm', 'native']:
                command = ([run.args.java, '-Xverify:all', '-jar', run.out/'snapshot_bulk-jvm.jar']
                           if backend == 'jvm' else [run.out/'snapshot_bulk-native.bin'])
                for mode, message in [('low', 'record index out of bounds'), ('high', 'record index out of bounds'), ('missing', 'missing index')]:
                    result = run.command('bulk-'+backend+'-'+mode, [*command, mode])
                    assert result.returncode != 0 and 'provenance: '+message in result.stderr, (backend, mode, result.stdout, result.stderr)
                    assert result.stdout == '42 public bulk rejection\n'
                    run.results.append({'case': 'bulk-'+mode, 'backend': backend, 'passed': True})
                    print('PASS', backend, 'public bulk', mode, 'refusal', flush=True)
        elif name == 'snapshot_defaults':
            def judge_defaults(output):
                assert output.startswith('50 independent default coordinates and implicit call identity\n')
            run.execute(name, HERE/'snapshot_defaults.dawn', judge_defaults)
        elif name == 'snapshot_flags':
            from snapshot_matrix import snapshot_flags
            snapshot_flags(run)
        elif name == 'snapshot_control':
            def judge_control_snapshot(output):
                assert output.startswith('42 frozen continuation snapshots resume and abandonment\n')
                assert '@@discarded\nS1\t2\t1\t0' in output
            run.execute(name, HERE/'snapshot_control.dawn', judge_control_snapshot)
        elif name == 'snapshot':
            def judge_snapshot(output):
                assert output.startswith('42 immutable snapshots rollback scopes and typed static indices\n')
                assert '@@trial\nS1\t1\t1\t0' in output
                assert '@@after\nS1\t1\t2\t0' in output
            run.execute(name, HERE/'snapshot.dawn', judge_snapshot)
        elif name in ['builder', 'modes', 'callbacks', 'bracket_exits', 'generic_capture', 'builtin_functions', 'bounded_functions', 'origin_api']:
            source = HERE/(name+'.dawn')
            judge = (lambda value: judge_builder(value, source.read_text())) if name == 'builder' else (
                lambda value: judge_tree(value, source.read_text(), name))
            run.execute(name, source, judge)
        elif name == 'associated':
            from scope_oracle import judge_associated
            source = HERE/'associated.dawn'
            run.execute(name, source, lambda value: judge_associated(value, source.read_text()))
        elif name == 'checkpoints':
            from scope_oracle import judge_checkpoints
            source = HERE/'checkpoints.dawn'
            run.execute(name, source, lambda value: judge_checkpoints(value, source.read_text()))
        elif name == 'shadow':
            from scope_oracle import judge_shadow
            source = HERE/'shadow.dawn'
            run.execute(name, source, lambda value: judge_shadow(value, source.read_text()))
        elif name == 'evidence':
            from scope_oracle import judge_evidence
            source = HERE/'evidence.dawn'
            run.execute(name, source, lambda value: judge_evidence(value, source.read_text()))
        elif name == 'unwind':
            from scope_oracle import judge_unwind
            source = HERE/'unwind.dawn'
            run.execute(name, source, lambda value: judge_unwind(value, source.read_text()))
        elif name == 'staged':
            from scope_oracle import judge_staged
            source = HERE/'staged.dawn'
            run.execute(name, source, lambda value: judge_staged(value, source.read_text()))
        elif name == 'nested':
            from scope_oracle import judge_nested
            source = HERE/'nested.dawn'
            run.execute(name, source, lambda value: judge_nested(value, source.read_text()))
        elif name == 'observed-bench':
            from scope_oracle import judge_observed_bench
            source = HERE/'observed_bench.dawn'
            run.execute(name, source, judge_observed_bench, ['tree', '2'])
        elif name == 'shared-probe':
            from shared_probe import shared_probe
            shared_probe(run)
        elif name == 'packages':
            from packages import packages
            packages(run)
        elif name == 'modules':
            from scope_oracle import judge_modules
            run.execute(name, HERE/'modules', judge_modules)
        elif name == 'mutations':
            from mutations import mutations
            mutations(run)
        elif name == 'escape':
            from scope_matrix import escape_matrix
            escape_matrix(run)
        elif name == 'w3':
            from scope_matrix import w3_controls
            w3_controls(run)
        elif name == 'runtime-errors':
            from scope_matrix import runtime_errors
            runtime_errors(run)
        else:
            raise AssertionError(('unknown contract case', name))
    sources = [*HERE.rglob('*.dawn'), *HERE.glob('*.py')]
    manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(sources)}
    (run.out/'result.json').write_text(json.dumps({'cases': run.results, 'inputs': manifest}, indent=2)+'\n')


if __name__ == '__main__':
    main()
