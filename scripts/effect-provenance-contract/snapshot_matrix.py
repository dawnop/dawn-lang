"""Public structured export controls, including flags unavailable in W2.

The producers deliberately set runtime flags to isolate frozen representation.
This is not a capacity-policy acceptance test; actual bounded recording has its
own source controls. Consumers always call the public compiled Dawn readers.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def snapshot_flags(run):
    def judge(output):
        assert output.startswith('(1, 1, 5, 1) Complete Active Known ')
        assert '\nS1\t1\t1\t0\n' in output and '\nO1\t' in output
    run.execute('snapshot_flags', HERE/'snapshot_flags.dawn', judge)
    import shutil
    java = Path(shutil.which(run.args.java) or run.args.java).resolve()
    jar = run.out/'snapshot_flags-jvm.jar'
    built = run.command('snapshot-flags-producer-javac', [java.with_name('javac'), '--release', '8', '-Xlint:-options', '-g:none', '-cp', jar, '-d', run.out, HERE/'ProbeTables.java', HERE/'SnapshotFlagsProbe.java'])
    assert built.returncode == 0, built.stderr
    jvm = run.command('snapshot-flags-producer-jvm', [java, '-Xverify:all', '-Xss32m', '-cp', str(jar)+':'+str(run.out), 'SnapshotFlagsProbe'])
    exe = run.out/'snapshot-flags-producer-native.bin'
    built = run.command('snapshot-flags-producer-cc', [run.args.cc, '-std=c11', '-O2', '-fwrapv', '-fexceptions', '-fno-strict-aliasing', '-ffp-contract=off', '-pthread', '-I'+str(ROOT/'runtime/c'), '-I'+str(run.out), HERE/'snapshot_flags_probe.c', ROOT/'runtime/c/dawn_rt.c', '-lm', '-o', exe])
    assert built.returncode == 0, built.stderr
    native = run.command('snapshot-flags-producer-native', [exe])
    for name, result in [('jvm', jvm), ('native', native)]:
        assert result.returncode == 0 and not result.stderr, (name, result.stderr)
        lines = result.stdout.splitlines()
        assert lines[0].startswith('(1, 1, 2, 1) Truncated Abandoned UnknownBoundary ')
        assert lines[1].startswith('(1, 1, 2, 1) Complete Returned Known ')
        for line in lines[:2]:
            assert ' Suspended UnknownBoundary Truncated 2 true ' in line
        assert '\nS1\t1\t1\t1\n' in result.stdout and '@@fresh\nS1\t1\t1\t0\n' in result.stdout
        run.results.append({'case': 'snapshot-flags-export', 'backend': name, 'passed': True})
        print('PASS', name, 'frozen typed flags and immutable notes after scope exit', flush=True)
    assert jvm.stdout == native.stdout, 'all typed and rendered fields must agree'


def snapshot_metadata(run):
    run.execute('snapshot_metadata', HERE/'snapshot_metadata.dawn', lambda output: output == '42 metadata reader compiled\n')
    import shutil
    java = Path(shutil.which(run.args.java) or run.args.java).resolve()
    jar = run.out/'snapshot_metadata-jvm.jar'
    built = run.command('metadata-producer-javac', [java.with_name('javac'), '--release', '8', '-Xlint:-options', '-g:none', '-cp', jar, '-d', run.out, HERE/'MetadataProbe.java'])
    assert built.returncode == 0, built.stderr
    jvm = run.command('metadata-producer-jvm', [java, '-Xverify:all', '-cp', str(jar)+':'+str(run.out), 'MetadataProbe'])
    exe = run.out/'metadata-producer-native.bin'
    built = run.command('metadata-producer-cc', [run.args.cc, '-std=c11', '-O2', '-fwrapv', '-fexceptions', '-fno-strict-aliasing', '-ffp-contract=off', '-pthread', '-I'+str(ROOT/'runtime/c'), '-I'+str(run.out), HERE/'metadata_probe.c', ROOT/'runtime/c/dawn_rt.c', '-lm', '-o', exe])
    assert built.returncode == 0, built.stderr
    native = run.command('metadata-producer-native', [exe])
    from snapshot_text import exports
    for name, result in [('jvm', jvm), ('native', native)]:
        assert result.returncode == 0 and not result.stderr, (name, result.stderr)
        assert result.stdout.startswith('42 typed metadata preserves escaped text and Unicode after table release\n')
        for raw, value in exports(result.stdout):
            assert value.frames[1].site[0] == 'unit%09\t雪'
            assert value.frames[1].definition[1] == 'decl%25\n雪'
        run.results.append({'case': 'typed-static-metadata', 'backend': name, 'passed': True})
        print('PASS', name, 'structured static fields and escaped text roundtrip', flush=True)
    assert jvm.stdout == native.stdout
