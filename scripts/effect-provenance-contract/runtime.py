#!/usr/bin/env python3
"""Compare both runtime protocols to independent checkpoint expectations.

These probes isolate runtime invariants. Compiler-generated trees require the
Dawn fixtures as well; passing this probe is not the compiler ABI contract.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    'cleanup': (0, 'clean\n', ''),
    'cross_thread': (1, '', 'panic: provenance: different execution context\n'),
    'reuse': (0, 'S\t1\t5\nF\t1\t1\t1\t0\t0\t0\t\t\nF\t1\t1\t2\t1\t1\t11\thelper\thelper\n', ''),
    'invalidated': (1, '', 'panic: provenance: checkpoint has been invalidated\n'),
    'other': (1, '', 'panic: provenance: checkpoint belongs to another scope\n'),
    'exited': (1, '', 'panic: provenance: scope has exited\n'),
    'deeper': (1, '', 'panic: provenance: not in the creating frame\n'),
    'finished': (1, '', 'panic: provenance: creating frame has finished\n'),
    'same_site': (1, '', 'panic: provenance: creating frame has finished\n'),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--java-home', type=Path, required=True)
    parser.add_argument('--cc', default='clang')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='provenance-runtime-') as directory:
        work = Path(directory)
        stub = work/'dawn/rt/PanicError.java'
        stub.parent.mkdir(parents=True)
        stub.write_text('package dawn.rt; public final class PanicError extends Error { public PanicError(String message) { super(message); } }\n')
        fn_stubs = []
        for arity in [1, 2]:
            file = work/f'Fn{arity}.java'
            parameters = ', '.join(f'Object a{i}' for i in range(arity))
            file.write_text(f'package dawn.rt; public interface Fn{arity} {{ Object apply({parameters}); Object applyObserved({parameters}, long context); }}\n')
            fn_stubs.append(file)
        subprocess.run([str(args.java_home/'bin/javac'), '--release', '8', '-Xlint:-options', '-g:none', '-d', str(work), str(stub), *(str(f) for f in fn_stubs), str(ROOT/'runtime/jvm/Provenance.java'), str(ROOT/'scripts/effect-provenance-contract/RuntimeProbe.java')], check=True)
        exe = work/'probe'
        subprocess.run([args.cc, '-std=c11', '-O2', '-fwrapv', '-fexceptions', '-fno-strict-aliasing', '-ffp-contract=off', '-pthread', '-I'+str(ROOT/'runtime/c'), '-I'+str(ROOT/'scripts/rc-contract'), str(ROOT/'scripts/effect-provenance-contract/runtime_probe.c'), str(ROOT/'runtime/c/dawn_rt.c'), '-lm', '-o', str(exe)], check=True)
        for name, expected in EXPECTED.items():
            for backend, command in [('JVM', [str(args.java_home/'bin/java'), '-Xverify:all', '-cp', str(work), 'RuntimeProbe']), ('native', [str(exe)])]:
                result = subprocess.run(command+[name], capture_output=True, text=True)
                actual = (result.returncode, result.stdout, result.stderr)
                if actual != expected:
                    raise SystemExit(f'{backend} {name}: expected {expected!r}, got {actual!r}')
                print(f'PASS {backend} checkpoint {name}')


if __name__ == '__main__':
    main()
