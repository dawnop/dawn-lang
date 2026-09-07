#!/usr/bin/env python3
"""Hold statement fallthrough to real emitted classes, not source spelling."""
import sys
import tempfile
from pathlib import Path

from never_probe import ADD_EXPORTS, ROOT, compiler_command, run


def main():
    jar = Path(sys.argv[1]).resolve()
    verifier = Path(sys.argv[2]).resolve()
    source = ROOT / 'scripts/spike-native/never_statements.dawn'
    expected = source.with_suffix('.expect').read_text()
    checked = run(compiler_command(jar, 'check', str(source)))
    if checked.returncode:
        raise RuntimeError('statement fixture did not check: ' + checked.stderr)
    with tempfile.TemporaryDirectory(prefix='dawn-statement-flow-') as temp:
        out = Path(temp)
        emitted = run(compiler_command(jar, '__emit', str(source), '-o', str(out)))
        if emitted.returncode:
            if 'has no slot' not in emitted.stderr + emitted.stdout:
                raise RuntimeError('unexpected emission failure: ' + emitted.stderr + emitted.stdout)
            print('ASSERT: NEVER_STATEMENT_FLOW')
            return 1
        verified = run(['java', *ADD_EXPORTS, '-cp', f'{verifier}:{jar}', 'Verify', str(out)])
        if verified.returncode:
            raise RuntimeError('statement class verification failed: ' + verified.stderr + verified.stdout)
        executed = run(['java', *ADD_EXPORTS, '-cp', str(out), 'never_statements'])
        if executed.returncode or executed.stdout != expected or executed.stderr:
            print('ASSERT: NEVER_STATEMENT_FLOW')
            print(executed.stdout + executed.stderr)
            return 1
        taken = run(['java', *ADD_EXPORTS, '-cp', str(out), 'never_statements', 'take-lists'])
        taken_expected = expected.replace('21\n22\n', 'stop\nstop\n')
        if taken.returncode or taken.stdout != taken_expected or taken.stderr:
            print('ASSERT: NEVER_STATEMENT_FLOW')
            print(taken.stdout + taken.stderr)
            return 1
    print('classfile statement fallthrough contract: OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
