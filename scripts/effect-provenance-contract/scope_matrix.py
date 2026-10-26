"""Source-level capability and checkpoint controls with exact outcomes."""
from run import exact
import re

PRELUDE = '''use std/io.{println}
'''


def source(run, name, declarations, expression):
    path = run.out/(name.replace('-', '_')+'.dawn')
    text = declarations+'\n'+expression
    imports = 'use std/provenance\n' if 'provenance.' in text else ''
    types = [name for name in ['TraceScope', 'Checkpoint', 'Origin'] if re.search(r'\b'+name+r'\b', text)]
    if types:
        imports += 'use std/provenance.{'+', '.join(types)+'}\n'
    path.write_text(PRELUDE+imports+declarations+'\npub fn main() -> Unit !io = {\n'
                    +'  let value = '+expression+'\n  println("${value}")\n}\n')
    return path


def escape_matrix(run):
    # Each refused source has a separately executed, type-correct control.
    # Refusal must name the capability rule, never a parser/type accident.
    cases = [
        ('alias', '', '{ let copy = scope\n 42 }', 'TraceScope is a lexical handle'),
        ('tuple', '', '{ let box = (scope, 1)\n 42 }', 'TraceScope is a lexical handle'),
        ('list', '', '{ let box = [scope]\n 42 }', 'TraceScope is a lexical handle'),
        ('option', '', '{ let box = Some(scope)\n 42 }', 'TraceScope is a lexical handle'),
        ('record', 'type Box = { handle: TraceScope }', '{ let box = Box { handle = scope }\n 42 }', 'TraceScope is a lexical handle'),
        ('handler-cell', 'effect Keep { fn keep() -> Unit }', '{ with handle Keep { var saved: TraceScope = scope\n keep() => () }\n keep()\n 42 }', 'TraceScope is a lexical handle'),
        ('mutable', '', '{ var copy = scope\n 42 }', 'TraceScope is a lexical handle'),
        ('return', '', '{ let escaped = provenance.observe(inner => inner)\n 42 }', 'TraceScope is a lexical handle'),
        ('capture', '', '{ let escaped = () => provenance.completed(scope)\n 42 }', 'TraceScope cannot be captured by an escaping closure'),
        ('implicit-capture', 'effect Ask { fn ask() -> Origin }', '{ let escaped = () => { let scope = 0\n with handle Ask { ask() origin source => source }\n ask() }\n 42 }', 'TraceScope cannot be captured by an escaping closure'),
        ('argument', 'fn take(value: TraceScope) -> Int = 42', 'take(scope)', 'TraceScope is a lexical handle'),
        ('generic', 'fn take[T](value: T) -> Int = 42', 'take(scope)', 'TraceScope is a lexical handle'),
        ('dynamic', '', '{ let take: fn(TraceScope) -> Int = value => 42\n take(scope) }', 'TraceScope is a lexical handle'),
        ('computed-list', '', '{ let rows = provenance.completed([scope][0])\n 42 }', 'TraceScope argument must be its lexical binding'),
        ('computed-if', '', '{ let rows = provenance.completed(if true { scope } else { scope })\n 42 }', 'TraceScope argument must be its lexical binding'),
    ]
    for name, declarations, body, message in cases:
        positive = source(run, 'escape-'+name+'-positive', declarations,
                          'provenance.observe(scope => { let rows = provenance.completed(scope)\n 42 })')
        run.execute('escape-'+name+'-positive', positive, exact('42\n'))
        negative = source(run, 'escape-'+name+'-negative', declarations,
                          'provenance.observe(scope => '+body+')')
        run.rejection('escape-'+name+'-negative', negative, message)
    cases = [
        ('comptime', '', 'comptime { provenance.observe(scope => 42) }', 'observation is not supported by the interpreter or at compile time'),
        ('value', '', '{ let observer = provenance.observe\n 42 }', 'observe cannot be used as a function value'),
        ('nonliteral', '', '{ let body: fn(TraceScope) -> Int = scope => 42\n provenance.observe(body) }', 'observe requires a literal callback'),
        ('outside', 'effect Ask { fn ask() -> Int }', '{ with handle Ask { ask() origin source => 42 }\n ask() }', 'origin requires a lexical observation scope'),
    ]
    for name, declarations, body, message in cases:
        positive = source(run, 'entry-'+name+'-positive', declarations,
                          'comptime { 42 }' if name == 'comptime' else 'provenance.observe(scope => 42)')
        run.execute('entry-'+name+'-positive', positive, exact('42\n'))
        negative = source(run, 'entry-'+name+'-negative', declarations, body)
        run.rejection('entry-'+name+'-negative', negative, message)
    # Textual spelling has no privilege. Both a local function and a renamed
    # standard import exercise resolved declaration identity.
    identity = source(run, 'resolved-entry', 'fn observe(n: Int) -> Int = n + 1',
                      'observe(provenance.observe(scope => 41))')
    run.execute('resolved-entry', identity, exact('42\n'))


def runtime_errors(run):
    cases = [
        ('invalidated', '',
         'provenance.observe(scope => { let a = provenance.checkpoint(scope)\n let b = provenance.checkpoint(scope)\n provenance.rewind(scope, a)\n provenance.rewind(scope, b)\n 42 })',
         'provenance.observe(scope => { let a = provenance.checkpoint(scope)\n let b = provenance.checkpoint(scope)\n provenance.rewind(scope, a)\n provenance.rewind(scope, a)\n 42 })',
         'checkpoint has been invalidated'),
        ('other', '',
         'provenance.observe(scope => { let c = provenance.checkpoint(scope)\n provenance.observe(inner => { provenance.rewind(inner, c)\n 42 }) })',
         'provenance.observe(scope => { let c = provenance.checkpoint(scope)\n provenance.observe(inner => { let d = provenance.checkpoint(inner)\n provenance.rewind(inner, d)\n 42 }) })',
         'checkpoint belongs to another scope'),
        ('exited', '',
         '{ let c = provenance.observe(scope => provenance.checkpoint(scope))\n provenance.observe(inner => { provenance.rewind(inner, c)\n 42 }) }',
         '{ let c = provenance.observe(scope => provenance.checkpoint(scope))\n provenance.observe(inner => { let d = provenance.checkpoint(inner)\n provenance.rewind(inner, d)\n 42 }) }',
         'scope has exited'),
        ('deeper', 'effect Visit { fn go() -> Unit }',
         'provenance.observe(scope => { let c = provenance.checkpoint(scope)\n with handle Visit { go() => provenance.rewind(scope, c) }\n go()\n 42 })',
         'provenance.observe(scope => { let c = provenance.checkpoint(scope)\n with handle Visit { go() => { let d = provenance.checkpoint(scope)\n provenance.rewind(scope, d) } }\n go()\n 42 })',
         'not in the creating frame'),
        ('finished', 'effect Make { fn make() -> Checkpoint }',
         'provenance.observe(scope => { with handle Make { make() => provenance.checkpoint(scope) }\n let c = make()\n provenance.rewind(scope, c)\n 42 })',
         'provenance.observe(scope => { with handle Make { make() => provenance.checkpoint(scope) }\n let c = make()\n let d = provenance.checkpoint(scope)\n provenance.rewind(scope, d)\n 42 })',
         'creating frame has finished'),
        ('same-site', 'effect Make { fn make() -> Checkpoint }\nfn create() -> Checkpoint !Make = make()',
         'provenance.observe(scope => { with handle Make { make() => provenance.checkpoint(scope) }\n let first = create()\n let second = create()\n provenance.rewind(scope, first)\n 42 })',
         'provenance.observe(scope => { with handle Make { make() => provenance.checkpoint(scope) }\n let first = create()\n let second = create()\n let d = provenance.checkpoint(scope)\n provenance.rewind(scope, d)\n 42 })',
         'creating frame has finished'),
    ]
    storage = 'effect Slot { fn put(c: Checkpoint) -> Unit\n fn get() -> Checkpoint }\neffect Make { fn make() -> Option[Int] }'
    prefix = 'provenance.observe(scope => { with handle Slot { var saved: Option[Checkpoint] = None\n put(c) => { saved = Some(c) }\n get() => saved.expect("missing checkpoint") }\n with handle Make { make() => { let c = provenance.checkpoint(scope)\n put(c)\n '
    for ending, operation in [('option', 'let none: Option[Int] = None\n let value = none?\n Some(value)'),
                              ('panic', 'panic("creator panic")')]:
        invoke = 'let result = catch_panic(() => make())' if ending == 'panic' else 'let result = make()'
        body = prefix+operation+' } }\n '+invoke+'\n let c = get()\n '
        negative = body+'provenance.rewind(scope, c)\n 42 })'
        positive = body+'let d = provenance.checkpoint(scope)\n provenance.rewind(scope, d)\n 42 })'
        cases.append(('finished-'+ending, storage, negative, positive, 'creating frame has finished'))
    for name, declarations, negative, positive, message in cases:
        control = source(run, 'checkpoint-'+name+'-positive', declarations, positive)
        run.execute('checkpoint-'+name+'-positive', control, exact('42\n'))
        expression = 'match catch_panic(() => '+negative+') { Ok(value) -> "accepted"\n Err(message) -> message.message }'
        invalid = source(run, 'checkpoint-'+name+'-negative', declarations, expression)
        run.execute('checkpoint-'+name+'-negative', invalid, exact('provenance: '+message+'\n'))


def w3_refusals(run):
    cases = [
        ('resume', 'ctl effect Ask { fn ask() -> Int }',
         '{ with handle Ask { ask() resume k => k(7) }\n ask() }', 7),
        ('discard', 'ctl effect Ask { fn ask() -> Int }',
         '{ with handle Ask { ask() resume k => { discard(k)\n 7 } }\n ask() }', 7),
        ('suspend', 'ctl effect Ask { fn ask() -> Int }',
         '{ with handle Ask { ask() resume k => 7 }\n ask() }', 7),
        ('tail', 'fn loop(n: Int) -> Int = if n == 0 { 7 } else { loop(n - 1) }',
         'loop(2)', 7),
    ]
    for name, declarations, body, expected in cases:
        # A named helper outside lexical observation reaches the runtime
        # refusal. Lexically observed control arms are refused even earlier.
        if name != 'tail':
            declarations += '\nfn scenario() -> Int = '+body
            body = 'scenario()'
        positive = source(run, 'w3-'+name+'-positive', declarations, body)
        run.execute('w3-'+name+'-positive', positive, exact(str(expected)+'\n'))
        expression = 'match catch_panic(() => provenance.observe(scope => '+body+')) { Ok(value) -> "accepted"\n Err(error) -> error.message }'
        negative = source(run, 'w3-'+name+'-negative', declarations, expression)
        boundary = 'tail calls' if name == 'tail' else 'control operations'
        run.execute('w3-'+name+'-negative', negative,
                    exact('provenance: '+boundary+' under observation is not supported in W2\n'))
    for origin in ['', ' origin event']:
        label = 'combined-origin' if origin else 'lexical-control'
        declarations = 'ctl effect Ask { fn ask() -> Int }'
        positive = source(run, 'w3-'+label+'-positive', declarations,
                          '{ with handle Ask { ask() resume k => k(7) }\n ask() }')
        run.execute('w3-'+label+'-positive', positive, exact('7\n'))
        body = 'provenance.observe(scope => { with handle Ask { ask()'+origin+' resume k => k(7) }\n ask() })'
        negative = source(run, 'w3-'+label+'-negative', declarations, body)
        run.rejection('w3-'+label+'-negative', negative, 'control arms under observation are not supported in W2')
    base = source(run, 'tail-base-positive', cases[-1][1], 'provenance.observe(scope => loop(0))')
    run.execute('tail-base-positive', base, exact('7\n'))
