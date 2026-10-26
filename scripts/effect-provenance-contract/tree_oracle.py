#!/usr/bin/env python3
"""Independent expected trees for execution-mode and runtime-callback fixtures.

Rows below describe source calls by hand. Coordinates are selected from the
fixture text, never extracted from a compiler log or another backend's tree.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Decl:
    key: str
    start: str
    end: str


@dataclass(frozen=True)
class Call:
    parent: int
    caller: str
    expression: str
    name: str
    definition: str
    status: int = 1
    role: str = 'call'
    name_offset: int = 0


MODE_DECLS = {
    'main': Decl('Nf4:main', 'fn main()', '\n}'),
    'make': Decl('Nf4:make', 'fn make(', 'offset\n'),
    'library': Decl('Nf7:library', 'fn library(', 'f(n)\n'),
    'direct': Decl('Nf6:direct', 'fn direct(', 'n * 2\n'),
    'through': Decl('Nf7:through', 'fn through[', 'step(value)\n'),
    'defaults': Decl('Nf8:defaults', 'fn defaults[', 'twice(value)\n'),
    'step': Decl('I4:Stepn7:Counter0;0;Nm4:step', 'fn step(value: Counter)', 'value.value + 1\n'),
    'twice': Decl('Nr4:StepNm5:twice', 'fn twice(value:', 'step(value) * 2\n'),
}
# One root, one observer lambda, two nested dynamic calls, all three trait
# forms, and a factory whose result will be called after observation ends.
MODE_TREE = [
    Call(1, 'main', 'provenance.observe', 'observe', 'observer', 0),
    Call(2, 'main', 'library(before, 3)', 'library', 'library'),
    Call(3, 'library', 'f(n)', 'f', 'factory_lambda'),
    Call(4, 'make', 'direct(n)', 'direct', 'direct'),
    Call(2, 'main', 'through(Counter { value = 3 })', 'through', 'through'),
    Call(6, 'through', 'step(value)', 'step', 'step'),
    Call(2, 'main', 'defaults(Counter { value = 3 })', 'defaults', 'defaults'),
    Call(8, 'defaults', 'twice(value)', 'twice', 'twice'),
    Call(9, 'twice', 'step(value)', 'step', 'step'),
    Call(2, 'main', 'step(Counter { value = 3 })', 'step', 'step'),
    Call(2, 'main', 'make(2)', 'make', 'make'),
]
CALLBACK_DECLS = {
    'main': Decl('Nf4:main', 'fn main()', '\n}'),
    'direct': Decl('Nf6:direct', 'fn direct(', 'n + 1\n'),
    'fail': Decl('Nf4:fail', 'fn fail()', 'panic("callback failure")\n'),
    'release': Decl('Nf7:release', 'fn release(', '()\n'),
}
CALLBACK_TREE = [
    Call(1, 'main', 'provenance.observe', 'observe', 'observer', 0),
    Call(2, 'main', 'catch_panic(() => fail())', 'catch_panic', 'intrinsic:catch_panic'),
    Call(3, 'main', 'catch_panic(() => fail())', 'catch_panic', 'failure_lambda', 2, 'library-callback'),
    Call(4, 'main', 'fail()', 'fail', 'fail', 2),
    Call(5, 'fail', 'panic("callback failure")', 'panic', 'intrinsic:panic', 2),
    Call(2, 'main', 'bracket(7, release, n => direct(n))', 'bracket', 'intrinsic:bracket'),
    Call(7, 'main', 'bracket(7, release, n => direct(n))', 'bracket', 'use_lambda', 1, 'library-callback'),
    Call(8, 'main', 'direct(n)', 'direct', 'direct'),
    Call(7, 'main', 'bracket(7, release, n => direct(n))', 'bracket', 'release', 1, 'library-callback'),
    Call(2, 'main', 'direct(value)', 'direct', 'direct'),
]



BRACKET_DECLS = {
    'main': Decl('Nf4:main', 'fn main()', '\n}'),
    'fail': Decl('Nf4:fail', 'fn fail(', 'panic("body failure")\n'),
    'release': Decl('Nf7:release', 'fn release(', 'else { () }\n'),
    'sibling': Decl('Nf7:sibling', 'fn sibling(', 'n + 1\n'),
}
# Expected by structured call nesting, including both release paths and
# replacement of the original failure. Nothing here is read from a log.
BRACKET_TREE = [
    Call(1, 'main', 'provenance.observe', 'observe', 'observer', 0),
    Call(2, 'main', 'catch_panic(() => bracket(1, release, fail))', 'catch_panic', 'intrinsic:catch_panic'),
    Call(3, 'main', 'catch_panic(() => bracket(1, release, fail))', 'catch_panic', 'first_lambda', 2, 'library-callback'),
    Call(4, 'main', 'bracket(1, release, fail)', 'bracket', 'intrinsic:bracket', 2),
    Call(5, 'main', 'bracket(1, release, fail)', 'bracket', 'fail', 2, 'library-callback'),
    Call(6, 'fail', 'panic("body failure")', 'panic', 'intrinsic:panic', 2),
    Call(5, 'main', 'bracket(1, release, fail)', 'bracket', 'release', 1, 'library-callback'),
    Call(2, 'main', 'catch_panic(() => bracket(2, release, fail))', 'catch_panic', 'intrinsic:catch_panic'),
    Call(9, 'main', 'catch_panic(() => bracket(2, release, fail))', 'catch_panic', 'second_lambda', 2, 'library-callback'),
    Call(10, 'main', 'bracket(2, release, fail)', 'bracket', 'intrinsic:bracket', 2),
    Call(11, 'main', 'bracket(2, release, fail)', 'bracket', 'fail', 2, 'library-callback'),
    Call(12, 'fail', 'panic("body failure")', 'panic', 'intrinsic:panic', 2),
    Call(11, 'main', 'bracket(2, release, fail)', 'bracket', 'release', 2, 'library-callback'),
    Call(14, 'release', 'panic("release failure")', 'panic', 'intrinsic:panic', 2),
    Call(2, 'main', 'sibling(9)', 'sibling', 'sibling'),
]



GENERIC_DECLS = {
    'main': Decl('Nf4:main', 'fn main()', '\n}'),
    'make': Decl('Nf4:make', 'fn make[', '() => step(value)\n'),
    'step': Decl('I4:Stepn5:Value0;0;Nm4:step', 'fn step(value: Value)', 'value.n + 1'),
}
GENERIC_TREE = [
    Call(1, 'main', 'provenance.observe', 'observe', 'observer', 0),
    Call(2, 'main', 'before.run()', 'run', 'factory_lambda', name_offset=7),
    Call(3, 'make', 'step(value)', 'step', 'step'),
]



BUILTIN_DECLS = {
    'main': Decl('Nf4:main', 'fn main()', '\n}'),
    'fail': Decl('Nf4:fail', 'fn fail()', 'panic("function value failure")\n'),
}
BUILTIN_TREE = [
    Call(1, 'main', 'provenance.observe', 'observe', 'observer', 0),
    Call(2, 'main', 'convert(42)', 'convert', 'intrinsic:to_float'),
    Call(2, 'main', 'capture(() => fail())', 'capture', 'intrinsic:catch_panic'),
    Call(4, 'main', 'capture(() => fail())', 'capture', 'failure_lambda', 2, 'library-callback'),
    Call(5, 'main', 'fail()', 'fail', 'fail', 2),
    Call(6, 'fail', 'panic("function value failure")', 'panic', 'intrinsic:panic', 2),
]



BOUNDED_DECLS = {
    'main': Decl('Nf4:main', 'fn main()', '\n}'),
    'generic': Decl('Nf7:generic', 'fn generic[', 'step(value)\n'),
    'step': Decl('I4:Stepn5:Value0;0;Nm4:step', 'fn step(value: Value)', 'value.n + 1'),
}
BOUNDED_TREE = [
    Call(1, 'main', 'provenance.observe', 'observe', 'observer', 0),
    Call(2, 'main', 'function(Value { n = 41 })', 'function', 'generic'),
    Call(3, 'generic', 'step(value)', 'step', 'step'),
]


def extent(source, decl):
    base = source.index(decl.start)
    marker = source.index(decl.end, base)
    return base, marker + len(decl.end.rstrip('\n'))


def judge(output, source, module):
    if module == "origin_api":
        return judge_api(output, source)
    numeric, recording = output.split('\n', 1)
    if module == 'modes':
        assert numeric == '(7, 4, 8, 4, 8)', ('numeric output', numeric)
        decls, tree = MODE_DECLS, MODE_TREE
        lambdas = {'factory_lambda': ('make', 'n => direct(n) + offset')}
    elif module == 'callbacks':
        assert numeric == '(true, 9)', ('numeric output', numeric)
        decls, tree = CALLBACK_DECLS, CALLBACK_TREE
        lambdas = {'failure_lambda': ('main', '() => fail()'),
                   'use_lambda': ('main', 'n => direct(n)')}
    elif module == 'bracket_exits':
        assert numeric == '("body failure at bracket_exits.dawn:6:30", "release failure at bracket_exits.dawn:7:46", 10)', ('numeric output', numeric)
        decls, tree = BRACKET_DECLS, BRACKET_TREE
        lambdas = {'first_lambda': ('main', '() => bracket(1, release, fail)'),
                   'second_lambda': ('main', '() => bracket(2, release, fail)')}
    elif module == 'generic_capture':
        assert numeric == '42', ('numeric output', numeric)
        decls, tree = GENERIC_DECLS, GENERIC_TREE
        lambdas = {'factory_lambda': ('make', '() => step(value)')}
    elif module == 'builtin_functions':
        assert numeric == '(42.0, true)', ('numeric output', numeric)
        decls, tree = BUILTIN_DECLS, BUILTIN_TREE
        lambdas = {'failure_lambda': ('main', '() => fail()')}
    elif module == 'bounded_functions':
        assert numeric == '42', ('numeric output', numeric)
        decls, tree = BOUNDED_DECLS, BOUNDED_TREE
        lambdas = {}
    else:
        raise AssertionError('unknown handwritten tree')
    lines = recording.rstrip('\n').splitlines()
    assert lines[0] == 'S\t1\t1', ('scope prefix', lines[0])
    frames = [line.split('\t') for line in lines[1:]]
    assert len(frames) == len(tree)+1, ('call count', len(frames), len(tree)+1)
    assert frames[0] == ['F', '1', '1', '1', '0', '0', '0', '', ''], 'root'
    observer_base = source.index('provenance.observe')
    observer_end = source.index('\n  })', observer_base)+len('\n  })')
    for instance, (actual, expected) in enumerate(zip(frames[1:], tree), 2):
        assert actual[:6] == ['F', '1', '1', str(instance), str(expected.parent), str(expected.status)], ('instance/parent/completion', instance, actual)
        base, _ = extent(source, decls[expected.caller])
        lo = source.index(expected.expression, base)
        hi = observer_end if expected.definition == 'observer' else lo+len(expected.expression)
        nlo = lo+len('provenance.') if expected.definition == 'observer' else lo+expected.name_offset
        assert actual[7:15] == [module, decls[expected.caller].key,
                               str(lo-base), str(hi-base), str(nlo-base),
                               str(nlo+len(expected.name)-base), expected.role, ''], ('site', instance, actual[7:15])
        if expected.definition.startswith('intrinsic:'):
            definition = ['intrinsic', expected.definition.split(':')[1], '-1', '-1', 'intrinsic']
        elif expected.definition == 'observer':
            lambda_lo = source.index('scope =>', observer_base)
            definition = [module, decls['main'].key, str(lambda_lo-base),
                          str(observer_end-1-base), 'lambda']
        elif expected.definition in lambdas:
            owner, expression = lambdas[expected.definition]
            db, _ = extent(source, decls[owner])
            dl = source.index(expression, db)
            definition = [module, decls[owner].key, str(dl-db), str(dl+len(expression)-db), 'lambda']
        else:
            decl = decls[expected.definition]
            db, de = extent(source, decl)
            definition = [module, decl.key, '0', str(de-db), 'function']
        assert actual[15:20] == definition, ('definition', instance, definition, actual[15:20])
        assert len(actual) == 21 and int(actual[20]) > 0, ('definition ID', instance, actual)


# The Origin is captured at perform before the pure inspection calls run.
# Its parent chain has five frames even though the completion log has seven.
API_PARENTS = [0, 1, 2, 3, 4, 5, 6]
API_DEFINITIONS = ['', 'Nf4:main', 'Nf4:main', 'Nf6:helper', 'Nf4:main', 'Nf8:describe', 'Nf9:operation']


def judge_api(output, source):
    identity, operation, location, definition, *recording = output.rstrip('\n').splitlines()
    assert identity == '(1, 1, 5, 4, 5, true)', ('immutable identities', identity)
    assert operation == 'origin_api:Ne4:ReadNo3:ask', ('operation identity', operation)
    assert location == '("origin_api", "origin_api", "Nf6:helper", "perform", true)', ('static Site', location)
    assert definition == '("origin_api", "Nf6:helper", "function")', ('parent definition', definition)
    assert recording[0] == 'S\t1\t1'
    frames = [line.split('\t') for line in recording[1:]]
    assert len(frames) == 7, ('zero-result pure inspection calls', len(frames))
    assert [int(f[4]) for f in frames] == API_PARENTS
    assert [int(f[5]) for f in frames] == [0, 0, 0, 1, 1, 1, 1]
    assert [f[16] if len(f) > 16 else '' for f in frames] == API_DEFINITIONS
    # The last ordinary pure call crosses into std; the private byte reader
    # is a named intrinsic and must not manufacture another logical frame.
    assert frames[6][15] == 'std/provenance' and frames[6][19] == 'function'
    assert frames[4][13:15] == ['perform', operation]
    base = source.index('fn helper')
    start = source.index('ask(n)', base)-base
    assert [int(v) for v in frames[4][9:13]] == [start, start+6, start, start+3]
