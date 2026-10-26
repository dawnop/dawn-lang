"""Handwritten scope and cross-module trees, independent of runtime output."""

def rows(recording):
    sections = recording.rstrip('\n').split('\n\n')
    lines = sections[0].splitlines()
    return lines[0], [line.split('\t') for line in lines[1:]], sections[1:]


def judge_checkpoints(output, source):
    a, b, c, d, recording = output.split('\n', 4)
    assert [a, b, c, d] == ['(3, 4, 5)', '(1, 1, 5)', '(1, 2, 7)', '(1, 3, 9)'], 'tentative Origin identities are immutable'
    header, frames, notes = rows(recording)
    assert header == 'S\t1\t3'
    # Two rolled-back helpers and their operations disappear from the view.
    # IDs are never recycled; retained ancestors keep their original epochs.
    expected = [(1, 1, 0, 0), (2, 1, 1, 0), (3, 1, 2, 0),
                (8, 3, 3, 1), (9, 3, 8, 1)]
    assert len(frames) == len(expected), ('call count', len(frames))
    for actual, (instance, epoch, parent, status) in zip(frames, expected):
        assert actual[:6] == ['F', '1', str(epoch), str(instance), str(parent), str(status)], actual
    main = source.index('fn main()')
    helper = source.index('fn helper(')
    selected = [(frames[3], main, 'helper(4)', 'helper', 'call'),
                (frames[4], helper, 'ask(n)', 'ask', 'perform')]
    for actual, base, call, name, role in selected:
        lo = source.index(call, base)-base
        assert actual[9:14] == [str(lo), str(lo+len(call)), str(lo), str(lo+len(name)), role], actual
        assert len(actual) == 21 and int(actual[6]) > 0 and int(actual[20]) > 0
    assert frames[3][15:17] == ['checkpoints', 'Nf6:helper']
    assert frames[4][14] == 'checkpoints:Ne5:QueryNo3:ask'
    assert len(notes) == 1, 'rewind also truncates the observer projection notes'
    envelope, *chain = notes[0].splitlines()
    assert envelope.startswith('O\t')
    assert [int(line.split('\t')[3]) for line in chain] == [9, 8, 3, 2, 1]
    assert [int(line.split('\t')[2]) for line in chain] == [3, 3, 1, 1, 1]


def judge_associated(output, source):
    value, recording = output.split('\n', 1)
    assert value == '(42, 42)', ('projected evidence result', value)
    header, frames, notes = rows(recording)
    assert header == 'S\t1\t1' and not notes
    # Written from the source evaluation order: relay reads the projection
    # through both a dictionary method and a Fn; the default reads it twice.
    expected = [
        (0, 0, '', '', ''),
        (1, 0, 'Nf4:main', 'lambda', 'call'),
        (2, 0, 'Nf4:main', 'with', 'handler-rest'),
        (3, 1, 'Nf5:relay', 'function', 'call'),
        (4, 1, 'I6:Runnern5:Value0;0;Nm3:run', 'function', 'call'),
        (5, 1, 'Nf4:main', 'handler', 'perform'),
        (4, 1, 'Nf4:main', 'lambda', 'call'),
        (7, 1, 'Nf4:main', 'handler', 'perform'),
        (3, 1, 'Nf8:defaults', 'function', 'call'),
        (9, 1, 'Nr6:RunnerNm5:twice', 'function', 'call'),
        (10, 1, 'I6:Runnern5:Value0;0;Nm3:run', 'function', 'call'),
        (11, 1, 'Nf4:main', 'handler', 'perform'),
        (10, 1, 'I6:Runnern5:Value0;0;Nm3:run', 'function', 'call'),
        (13, 1, 'Nf4:main', 'handler', 'perform'),
    ]
    assert len(frames) == len(expected), ('associated call count', len(frames))
    for instance, (frame, (parent, status, definition, role, site_role)) in enumerate(zip(frames, expected), 1):
        assert frame[:6] == ['F', '1', '1', str(instance), str(parent), str(status)], frame
        if instance > 1:
            assert len(frame) == 21 and frame[15:17] == ['associated', definition], frame
            assert frame[19] == role and frame[13] == site_role, frame
            assert int(frame[6]) > 0 and int(frame[20]) > 0
            assert frame[14] == ('associated:Ne3:AskNo3:ask' if site_role == 'perform' else ''), frame
    # The repeated default-body call sites have one definition and two Sites.
    assert frames[10][20] == frames[12][20] and frames[10][6] != frames[12][6]
    base = source.index('fn relay[')
    for frame, expression in [(frames[4], 'run(value)'), (frames[6], 'f()')]:
        start = source.index(expression, base)-base
        assert frame[7:9] == ['associated', 'Nf5:relay']
        assert list(map(int, frame[9:11])) == [start, start+len(expression)]


def judge_modules(output):
    value, recording = output.split('\n', 1)
    assert value == '13', ('numeric output', value)
    header, frames, notes = rows(recording)
    assert header == 'S\t1\t1' and not notes
    expected = [(0, 0, '', '', ''), (1, 0, 'main', 'Nf4:main', 'lambda'),
                (2, 1, 'library', 'Nf7:through', 'function'),
                (3, 1, 'model', 'Nr4:StepNm5:twice', 'function'),
                (4, 1, 'model', 'I4:Stepn7:Counter0;0;Nm4:step', 'function'),
                (3, 1, 'model', 'Nf4:make', 'lambda')]
    assert len(frames) == len(expected), ('call count', len(frames))
    for instance, (actual, (parent, status, owner, definition, role)) in enumerate(zip(frames, expected), 1):
        assert actual[:6] == ['F', '1', '1', str(instance), str(parent), str(status)], actual
        if instance > 1:
            assert len(actual) == 21 and actual[15:17] == [owner, definition] and actual[19] == role, actual
    # The library-created dictionary copy and the Plain-created user closure
    # both route to the caller's Observed entry without a bridge frame.
    assert [(row[7], row[8]) for row in frames[2:]] == [
        ('main', 'Nf4:main'), ('library', 'Nf7:through'),
        ('model', 'Nr4:StepNm5:twice'), ('library', 'Nf7:through')]


def judge_nested(output, source):
    value, rest = output.split('\n', 1)
    assert value == '(1, 1, 6)', 'Origin uses the handler lexical capability'
    inner, outer = rest.split('\nOUTER\n')
    ih, ir, inn = rows(inner)
    oh, outer_rows, notes = rows(outer)
    assert ih == 'S\t2\t1' and oh == 'S\t1\t1'
    assert not inn and len(notes) == 1
    for scope, actual, parents, statuses in [
            (2, ir, [0, 1, 2, 3], [0, 0, 1, 1]),
            (1, outer_rows, [0, 1, 2, 3, 4, 5], [0, 0, 0, 1, 1, 1])]:
        assert len(actual) == len(parents), ('root call count', scope, len(actual))
        for instance, (frame, parent, status) in enumerate(zip(actual, parents, statuses), 1):
            assert frame[:6] == ['F', str(scope), '1', str(instance), str(parent), str(status)], frame
    assert ir[1][6:] == outer_rows[3][6:], 'nested observer has one static identity'
    assert ir[2][6:] == outer_rows[4][6:] and ir[3][6:] == outer_rows[5][6:]
    # The origin snapshot is frozen before any handler-side observation and
    # retains the outer with-rest and observer, rather than the inner root.
    envelope, *chain = notes[0].splitlines()
    assert envelope.startswith('O\t')
    assert [int(row.split('\t')[3]) for row in chain] == [6, 5, 4, 3, 2, 1]
    assert all(row.split('\t')[1] == '1' for row in chain)
    base = source.index('fn helper(')
    lo = source.index('ask()', base)-base
    assert ir[3][7:15] == ['nested', 'Nf6:helper', str(lo), str(lo+5), str(lo), str(lo+3), 'perform', 'nested:Ne3:AskNo3:ask']


# This sequence follows the specified staged lowering: open a cell, invoke the
# selected branch/body, then read the cell back. Operations belong to each
# StagedVar method, while synthetic calls retain var/if/for/literal roles.
# Symbolic parents keep this expectation reviewable against the source. The
# handler state cell creates one primitive frame and one read/write primitive
# for each operation arm; concrete pure literals are comptime conversions.
STAGED_TREE = [
    ('root', '', '', 'root'), ('observer', 'root', 'call', 'lambda'),
    ('state', 'observer', 'var', 'intrinsic:cell_new'),
    ('rest', 'observer', 'handler-rest', 'with'),
    ('program', 'rest', 'call', 'program'),
    ('literal', 'program', 'call', 'literal'),
    ('from_int', 'literal', 'literal', 'from_int'),
    ('if_open', 'program', 'var', 'var_open'),
    ('if_open_op', 'if_open', 'perform', 'handler'),
    ('if_open_state', 'if_open_op', 'var', 'intrinsic:cell_set'),
    ('if', 'program', 'if', 'staged_if'),
    ('yes', 'if', 'call', 'if-body'),
    ('if_read', 'yes', 'var', 'var_get'),
    ('if_read_op', 'if_read', 'perform', 'handler'),
    ('if_read_state', 'if_read_op', 'var', 'intrinsic:cell_get'),
    ('if_add', 'yes', 'operator', 'add'),
    ('if_write', 'yes', 'var', 'var_set'),
    ('if_write_op', 'if_write', 'perform', 'handler'),
    ('if_write_state', 'if_write_op', 'var', 'intrinsic:cell_set'),
    ('if_result', 'program', 'var', 'var_get'),
    ('if_result_op', 'if_result', 'perform', 'handler'),
    ('if_result_state', 'if_result_op', 'var', 'intrinsic:cell_get'),
    ('for_open', 'program', 'var', 'var_open'),
    ('for_open_op', 'for_open', 'perform', 'handler'),
    ('for_open_state', 'for_open_op', 'var', 'intrinsic:cell_set'),
    ('for', 'program', 'for', 'staged_for'),
    ('body', 'for', 'call', 'for-body'),
    ('for_read', 'body', 'var', 'var_get'),
    ('for_read_op', 'for_read', 'perform', 'handler'),
    ('for_read_state', 'for_read_op', 'var', 'intrinsic:cell_get'),
    ('for_add', 'body', 'operator', 'add'),
    ('for_write', 'body', 'var', 'var_set'),
    ('for_write_op', 'for_write', 'perform', 'handler'),
    ('for_write_state', 'for_write_op', 'var', 'intrinsic:cell_set'),
    ('for_result', 'program', 'var', 'var_get'),
    ('for_result_op', 'for_result', 'perform', 'handler'),
    ('for_result_state', 'for_result_op', 'var', 'intrinsic:cell_get'),
]


def judge_staged(output, source):
    value, recording = output.split('\n', 1)
    assert value == '7', ('numeric result', value)
    header, frames, notes = rows(recording)
    assert header == 'S\t1\t1' and not notes
    assert len(frames) == len(STAGED_TREE), ('complete staged tree', len(frames), len(STAGED_TREE))
    identities = {'': 0, **{entry[0]: i for i, entry in enumerate(STAGED_TREE, 1)}}
    for instance, (actual, (label, parent_name, role, callee)) in enumerate(zip(frames, STAGED_TREE), 1):
        parent = identities[parent_name]
        status = 0 if label in ['root', 'observer', 'rest'] else 1
        assert actual[:6] == ['F', '1', '1', str(instance), str(parent), str(status)], (instance, actual)
        if instance == 1:
            continue
        assert actual[13] == role, (instance, 'syntax role', role, actual)
        if callee in ['lambda', 'with', 'handler', 'if-body', 'for-body']:
            assert actual[19] == callee, (instance, 'definition role', callee, actual)
        elif callee in ['program', 'literal']:
            assert actual[16] == 'Nf'+str(len(callee))+':'+callee and actual[19] == 'function'
        elif callee.startswith('intrinsic:'):
            assert actual[15:17] == ['intrinsic', callee.split(':')[1]] and actual[19] == 'intrinsic'
        else:
            assert actual[16].endswith('Nm'+str(len(callee))+':'+callee), (instance, 'callee', callee, actual)
        assert len(actual) == 21 and int(actual[6]) > 0 and int(actual[20]) > 0
    # The original syntax is present even when the source had no callee name.
    assert all(frame[7] == 'staged' and int(frame[9]) >= 0 for frame in frames[1:])
    for role in ['literal', 'operator', 'var', 'for', 'if']:
        assert any(frame[13] == role for frame in frames[1:])


def judge_unwind(output, source):
    value, recording = output.split('\n', 1)
    assert value == '(7, None, 2, 3)', ('numeric answer', value)
    header, frames, notes = rows(recording)
    assert header == 'S\t1\t1' and not notes
    parents = [0, 1, 2, 2, 2, 5, 6, 2, 2]
    definitions = ['', 'Nf4:main', 'Nf5:early', 'Nf5:maybe',
                   'Nf5:depth', 'Nf5:depth', 'Nf5:depth', 'Nf4:bump', 'Nf4:bump']
    assert len(frames) == len(parents), ('full return tree', len(frames))
    for instance, (row, parent, definition) in enumerate(zip(frames, parents, definitions), 1):
        assert row[:6] == ['F', '1', '1', str(instance), str(parent), '0' if instance <= 2 else '1'], row
        if instance > 1:
            assert row[16] == definition and len(row) == 21
    # Both method calls have the same expression start and different complete
    # spans/name spans. A line or a definition alone cannot distinguish them.
    first, second = frames[7], frames[8]
    base = source.index('fn main()')
    lo = source.index('Counter { n = 1 }).bump()', base)-base
    first_end = lo+len('Counter { n = 1 }).bump()')
    second_end = first_end+len('.bump()')
    assert first[9:13] == [str(lo), str(first_end), str(first_end-6), str(first_end-2)]
    assert second[9:13] == [str(lo), str(second_end), str(second_end-6), str(second_end-2)]
    assert first[6] != second[6] and first[20] == second[20]
    assert frames[5][6] == frames[6][6] and frames[5][3] != frames[6][3]


def judge_evidence(output, source):
    value, recording = output.split('\n', 1)
    assert value == '111', 'handler helper resolves outer lexical evidence'
    header, frames, notes = rows(recording)
    assert header == 'S\t1\t1'
    parents = [0, 1, 2, 3, 4, 5, 6, 7]
    roles = ['', 'call', 'handler-rest', 'handler-rest', 'call', 'perform', 'call', 'perform']
    assert len(frames) == len(parents) and len(notes) == 2
    for instance, (frame, parent, role) in enumerate(zip(frames, parents, roles), 1):
        assert frame[:6] == ['F', '1', '1', str(instance), str(parent), '0' if instance <= 4 else '1'], frame
        if instance > 1:
            assert len(frame) == 21 and frame[13] == role
    for note, expected in zip(notes, [[6, 5, 4, 3, 2, 1], [8, 7, 6, 5, 4, 3, 2, 1]]):
        envelope, *chain = note.splitlines()
        assert envelope.startswith('O\t')
        assert [int(row.split('\t')[3]) for row in chain] == expected
    assert frames[5][6:15] == frames[7][6:15], 'same perform Site, separate instances'
    assert frames[5][20] != frames[7][20], 'different lexical handler definitions'


def judge_shadow(output, source):
    value, recording = output.split('\n', 1)
    assert value == '(42, 1, 4)', 'lexical capability identity survives name shadowing'
    header, frames, notes = rows(recording)
    assert header == 'S\t1\t1' and len(frames) == 4 and not notes
    for instance, (row, parent, status) in enumerate(zip(frames, [0, 1, 2, 3], [0, 0, 1, 1]), 1):
        assert row[:6] == ['F', '1', '1', str(instance), str(parent), str(status)], row
    assert frames[3][14] == 'shadow:Ne3:AskNo3:ask'
    assert frames[2][19] == 'with' and frames[3][19] == 'handler'


def judge_observed_bench(output):
    value, recording = output.split('\n', 1)
    assert value == '4', 'two builder iterations compute n squared'
    header, frames, notes = rows(recording)
    assert header == 'S\t1\t1' and len(frames) == 12 and len(notes) == 4
    parents = [0, 1, 2, 3, 4, 5, 5, 5, 4, 9, 9, 9]
    for instance, (frame, parent) in enumerate(zip(frames, parents), 1):
        assert frame[:6] == ['F', '1', '1', str(instance), str(parent), '0' if instance <= 3 else '1'], frame
    assert frames[4][20] == frames[8][20] and frames[5][20] == frames[9][20]
    expected = [[7, 5, 4, 3, 2, 1], [8, 5, 4, 3, 2, 1],
                [11, 9, 4, 3, 2, 1], [12, 9, 4, 3, 2, 1]]
    for note, chain in zip(notes, expected):
        envelope, *parents = note.splitlines()
        assert envelope.startswith('O\t')
        assert [int(row.split('\t')[3]) for row in parents] == chain
