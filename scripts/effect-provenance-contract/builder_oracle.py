#!/usr/bin/env python3
"""Judge the builder against a handwritten call tree and source selections.

The expected tree is not inferred from either backend's recording. IDs below
are execution instances, with separate expected definition and call-site keys.
"""
from pathlib import Path

# Each row is (instance, parent, callee, status, expression, enclosing declaration).
TREE = [
    (1, 0, 'root', 0, '', ''),
    (2, 1, 'lambda', 0, 'provenance.observe', 'main'),
    (3, 2, 'with', 0, 'with handle Builder', 'main'),
    (4, 3, 'helper', 1, 'helper(1)', 'main'),
    (5, 4, 'pure', 1, 'pure(n)', 'helper'),
    (6, 4, 'query', 1, 'query(value)', 'helper'),
    (7, 4, 'output', 1, 'output(answer)', 'helper'),
    (8, 3, 'helper', 1, 'helper(2)', 'main'),
    (9, 8, 'pure', 1, 'pure(n)', 'helper'),
    (10, 8, 'query', 1, 'query(value)', 'helper'),
    (11, 8, 'output', 1, 'output(answer)', 'helper'),
]
NOTE_CHAINS = [[6, 4, 3, 2, 1], [7, 4, 3, 2, 1], [10, 8, 3, 2, 1], [11, 8, 3, 2, 1]]


def judge(output: str, source: str):
    value, recording = output.split('\n', 1)
    assert value == '(3, 5)', ('numeric output', value)
    sections = recording.rstrip('\n').split('\n\n')
    lines = sections[0].splitlines()
    assert lines[0] == 'S\t1\t1', ('prefix header', lines[0])
    actual = [line.split('\t') for line in lines[1:]]
    assert len(actual) == len(TREE), ('call count', len(actual))
    for fields, expected in zip(actual, TREE):
        instance, parent, callee, status, expression, declaration = expected
        assert fields[:7] == ['F', '1', '1', str(instance), str(parent), str(status), fields[6]]
        if callee == 'root':
            assert fields[6:] == ['0', '', '']
            continue
        assert len(fields) == 21, ('frame shape', fields)
        assert fields[7] == 'builder'
        assert fields[8] == 'Nf'+str(len(declaration))+':'+declaration
        base = source.index('fn '+declaration)
        lo = source.index(expression, base)-base
        assert int(fields[9]) == lo, ('call span start', instance)
        if callee == 'lambda':
            end = source.index('\n  })', base)+len('\n  })')-base
            assert [int(v) for v in fields[9:13]] == [lo, end, lo+len('provenance.'), lo+len('provenance.observe')]
            assert fields[19] == 'lambda'
        elif callee == 'with':
            end = source.index('\n  })', base)+len('\n  ')-base
            assert [int(v) for v in fields[9:13]] == [lo, end, -1, -1]
            assert fields[13] == 'handler-rest' and fields[19] == 'with'
        else:
            assert [int(v) for v in fields[9:13]] == [lo, lo+len(expression), lo, lo+len(callee)]
            if callee in {'query', 'output'}:
                assert fields[13] == 'perform'
                assert fields[14] == 'builder:Ne7:BuilderNo'+str(len(callee))+':'+callee
                assert fields[19] == 'handler'
            else:
                assert fields[13:15] == ['call', '']
                assert fields[15:17] == ['builder', 'Nf'+str(len(callee))+':'+callee]
                assert fields[19] == 'function'
    assert actual[3][20] == actual[7][20], 'same helper definition across instances'
    assert actual[4][20] == actual[8][20], 'same pure definition across instances'
    assert len({actual[i][20] for i in [1, 2, 3, 4, 5, 6]}) == 6, 'distinct definitions'
    assert all(int(row[20]) > 0 for row in actual[1:])
    assert len(sections[1:]) == 4, 'operation count'
    for note, chain in zip(sections[1:], NOTE_CHAINS):
        envelope, *parents = note.splitlines()
        assert envelope.startswith('O\t')
        rows = [line.split('\t') for line in parents]
        assert [int(row[3]) for row in rows] == chain, ('immutable origin parent chain', chain, rows)
        assert all(row[5] == '0' for row in rows), 'Origin must retain the perform-time prefix'
    return True


if __name__ == '__main__':
    import sys
    judge(Path(sys.argv[1]).read_text(), Path(sys.argv[2]).read_text())
    print('PASS handwritten builder tree, numeric output, spans, operation sequence and immutable parent chains')
