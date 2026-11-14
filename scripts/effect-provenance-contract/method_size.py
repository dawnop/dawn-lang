"""Hold final Code sizes on generated control flow and the whole tile corpus.

The padded JAR still runs with identical facts. Only the independent size
reader must reject it; the product compiler never rewrites a finished JAR.
"""
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GATE = ROOT/'scripts/method-size-gate.py'


def observed_corpus(directory):
    source = (ROOT/'scripts/tile-golden/kernels.dawn').read_text()
    tokens = [(m.group(), m.start(), m.end()) for m in re.finditer(
        r'\#[^\n]*|"(?:\\.|[^"\\])*"|->|[{}]|\S', source)
        if not m.group().startswith('#')]

    def dispatch(name):
        start = source.index('fn '+name+'(')
        opening = source.index('{', start)
        depth = 0
        arms = []
        for i, (token, at, end) in enumerate(tokens):
            if at < opening:
                continue
            if token == '{':
                depth += 1
            elif token == '}':
                depth -= 1
                if depth == 0:
                    if arms:
                        arms[-1][2] = at
                    return start, end, {key: source[lo:hi].strip()
                                        for key, lo, hi in arms if key != '_'}
            if depth == 1 and (token.startswith('"') or token == '_') and tokens[i+1][0] == '->':
                if arms:
                    arms[-1][2] = at
                arms.append([json.loads(token) if token != '_' else '_', tokens[i+1][2], None])
        raise AssertionError('missing complete kernel dispatcher '+name)

    a, b, first = dispatch('trace')
    c, d, second = dispatch('trace_after')
    cut = source.index('# Trace `name` twice')
    body = source[:a]+source[b:c]+source[d:cut]
    body = body.replace('use tileir/prog.{TileOp, TileProg', 'use tileir/prog.{TileProg')
    body = body.replace('use tileir/asm.{tileiras_args}\n', '')
    body = body.replace('use tileir/bytecode.{encode, bytecode_version}', 'use tileir/bytecode.{encode}')
    # The corpus drops the golden program's emitters and tables, so imports
    # only they used are unused here and the checker rejects them.
    unused = ['CellViewOf', 'IdxConst', 'IdxMul', 'Load', 'MakeToken', 'lanes_strided',
              'retile', 't_idx_const', 'to_hex', 'write_file']
    def drop(match):
        names = [n.strip() for n in match.group(2).split(',') if n.strip()]
        kept = [n for n in names if n not in unused]
        seen.update(set(names) & set(unused))
        return match.group(1)+'{'+', '.join(kept)+'}' if kept else ''
    seen = set()
    body = re.sub(r'(?m)^(use [\w/]+\.)\{([^}]*)\}', drop, body)
    assert seen == set(unused), 'size corpus import list moved: '+str(set(unused)-seen)
    body = body.replace('use std/io.{', 'use std/provenance\nuse std/io.{', 1)
    cases = first | second
    names = sorted(path.stem for path in (ROOT/'scripts/tile-golden').glob('*.tilebc'))
    assert names and set(names) == set(cases), 'the size corpus must contain every golden kernel'
    selector = '\nfn select_case(name: String) -> fn() -> TileProg = match name {\n'
    selector += ''.join('  '+json.dumps(name)+' -> () => { '+cases[name]+' }\n' for name in names)
    selector += '  _ -> panic("unknown size corpus kernel")\n}\n'
    wrapper = '''
pub fn main() -> Unit !io = {
  let work = select_case(args()[0])
  let program = provenance.observe(scope => {
    let value = work()
    let _ = provenance.completed(scope)
    value
  })
  let argv = args()
  if len(argv) > 1 {
    match with_fs_real(() => write_bytes(argv[1], encode(program))) {
      Ok(_) -> (), Err(_) -> panic("cannot write size corpus bytecode")
    }
  } else { println(render(program)) }
}
'''
    (directory/'src').mkdir(parents=True)
    (directory/'src/main.dawn').write_text(body+selector+wrapper)
    (directory/'dawn.toml').write_text('schema = 1\nname = "observed_size_corpus"\n[deps]\n'
        +'tileir = '+json.dumps(str(ROOT/'packages/tileir'))+'\n'
        +'tileref = '+json.dumps(str(ROOT/'packages/tileref'))+'\n')
    return names


def check(run):
    fixture = run.out/'size_regions.dawn'
    arms = '\n'.join(f'  {i} -> leaf(n) + leaf(n + 1)' for i in range(512))
    fixture.write_text('''# Every branch runs; outlining must preserve all public frozen facts.
use std/provenance
fn leaf(n: Int) -> Int = n + 1
fn branch(n: Int) -> Int = match n {
'''+arms+'''
  _ -> panic("unreachable branch")
}
pub fn main() -> Unit !io = {
  let (sum, snapshot) = provenance.observe(scope => {
    var total = 0
    for i in 0..512 { total = total + branch(i) }
    (total, provenance.completed(scope))
  })
  if sum != 263168 { panic("size control value mismatch") }
  println("42")
  println(provenance.render_snapshot(snapshot))
}
''')
    def judge(text):
        assert text.startswith('42\nS1\t'), 'missing size control facts'
    # This is a JVM Code-size input. Give the comparison C frontend enough
    # parser nesting for all 512 arms; this option changes no emitted code.
    frontend=run.command('size-native-frontend',[run.args.cc,'--version'])
    assert frontend.returncode==0,frontend.stderr
    cc_extra=['-fbracket-depth=1024','-Wno-parentheses-equality'] if 'clang' in frontend.stdout.lower() else []
    run.execute('size-regions', fixture, judge, cc_extra=cc_extra)
    target = run.out/'size-regions-jvm.jar'
    gate = [sys.executable, GATE, '--jar', run.args.compiler, '--observed-jar', target]
    result = run.command('size-regions-gate', gate)
    assert result.returncode == 0, result.stderr+result.stdout
    javac = Path(run.args.java).with_name('javac')
    result = run.command('size-mutator-build', [javac, '-cp', run.args.compiler,
                          '-d', run.out, HERE/'MethodSizeMutator.java'])
    assert result.returncode == 0, result.stderr
    mutant = run.out/'size-regions-oversized.jar'
    result = run.command('size-mutator', [run.args.java, '-cp', str(run.args.compiler)+':'+str(run.out),
                          'MethodSizeMutator', target, mutant, 'branch$observed'])
    assert result.returncode == 0, result.stderr
    result = run.command('size-mutant-run', [run.args.java, '-Xverify:all', '-jar', mutant])
    assert result.returncode == 0, result.stderr
    assert result.stdout == (run.out/'size-regions-jvm-run.stdout').read_text()
    result = run.command('size-mutant-gate', [sys.executable, GATE, '--jar', run.args.compiler,
                          '--observed-jar', mutant])
    assert result.returncode == 1 and 'METHOD SIZE FAIL' in result.stderr
    run.results.append({'case': 'oversized hot method', 'backend': 'jvm', 'passed': True})
    capacity = run.out/'size_capacity.dawn'
    # A straight dynamic list exceeds Code capacity without first exhausting
    # the independent static Site table limit. It is deliberately not run.
    capacity.write_text('# Preserve the existing hard JVM classfile diagnostic.\n'
        +'use std/provenance\n'
        +'fn large(n: Int) -> List[Int] = ['+', '.join(['n']*12000)+']\n'
        +'pub fn main() -> Unit !io = println(to_string(len(provenance.observe(_scope => large(0)))))\n')
    result = run.command('size-capacity-refusal', run.compiler('build', capacity,
                          '-o', run.out/'size-capacity-refused.jar'))
    assert result.returncode != 0 and 'Method too large:' in result.stderr, result.stderr
    assert '64 KiB' in result.stderr and 'Exception in thread' not in result.stderr, result.stderr
    run.results.append({'case': 'hard classfile capacity retains normal diagnostic', 'backend': 'jvm', 'passed': True})
    project = run.out/'observed-size-corpus'
    names = observed_corpus(project)
    run.build('observed-size-corpus', project, 'jvm')
    result = run.command('observed-corpus-size-gate', [sys.executable, GATE, '--jar', run.args.compiler,
                          '--observed-jar', run.out/'observed-size-corpus-jvm.jar', '--top', '10'])
    assert result.returncode == 0, result.stderr+result.stdout
    run.results.append({'case': 'all golden kernels final observed Code', 'backend': 'jvm',
                        'cases': len(names), 'passed': True})
    print('PASS JVM compiler and whole emitted observed corpus Code size, executable negative control', flush=True)
