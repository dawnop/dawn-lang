import { dawn, dawnCompletions } from '../src/dawn-lang'
import { parseDawnDiagnostics } from '../src/lint'
import { EditorState, Text } from '@codemirror/state'
import { ensureSyntaxTree } from '@codemirror/language'
import { CompletionContext } from '@codemirror/autocomplete'

let fails = 0
function expect(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) { fails++; console.log(`FAIL  ${name}: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`) }
  else console.log(`  ok  ${name}`)
}

// ---- diagnostics parser, fed real compiler output (strip_dir applied) ----
const report = `error: main must be pub
  --> prog.dawn:1:4
  |
1 | fn main() -> Unit !io = {
  |    ^^^^
  = hint: write pub fn main() -> Unit !io
error: annotated type is Int but the initializer is String
  --> prog.dawn:2:16
  |
2 |   let x: Int = "oops"
  |                ^^^^^^
error: undefined variable: y
  --> prog.dawn:3:11
  |
3 |   println(y)
  |           ^
3 errors`
const docText = Text.of(`fn main() -> Unit !io = {
  let x: Int = "oops"
  println(y)
}`.split('\n'))
const diags = parseDawnDiagnostics(report, docText)
expect('three diagnostics', diags.length, 3)
expect('d1 span = main', [diags[0].from, diags[0].to], [3, 7])
expect('d1 hint folded in', diags[0].message.includes('hint: write pub'), true)
expect('d2 span = "oops"', [diags[1].from, diags[1].to], [docText.line(2).from + 15, docText.line(2).from + 21])
expect('d3 severity', diags[2].severity, 'error')

// ---- completion context awareness ----
function completeAt(doc: string, marker = '‸') {
  const pos = doc.indexOf(marker)
  const text = doc.replace(marker, '')
  const state = EditorState.create({ doc: text, extensions: [dawn()] })
  ensureSyntaxTree(state, text.length, 5000)
  return dawnCompletions(new CompletionContext(state, pos, false))
}
expect('inside string: none', completeAt('fn f() -> Unit = println("pri‸")'), null)
expect('inside comment: none', completeAt('# comment pri‸'), null)
expect('after fn: none', completeAt('fn ma‸'), null)
expect('after let: none', completeAt('fn f() -> Unit = { let co‸'), null)
expect('use line: none', completeAt('use pl‸'), null)
expect('after dot: none', completeAt('fn f() -> Unit = x.le‸'), null)
expect('after bang: none', completeAt('fn f() -> Unit !i‸'), null)
const expr = completeAt('pub fn main() -> Unit !io = pri‸')
expect('expression: has println', expr!.options.some((o) => o.label === 'println'), true)
const local = completeAt('fn my_helper(n: Int) -> Int = n\npub fn main() -> Unit !io = my‸')
expect('own fn completes', local!.options.some((o) => o.label === 'my_helper' && o.type === 'function'), true)
const ctor = completeAt('type Shape =\n  | Circle(r: Float)\n  | Square(s: Float)\npub fn main() -> Unit !io = { let x = Ci‸ }')
expect('ADT ctor completes', ctor!.options.some((o) => o.label === 'Circle'), true)
expect('uppercase filters lowercase', ctor!.options.every((o) => /^[A-Z]/.test(o.label)), true)
const interp = completeAt('pub fn main() -> Unit !io = { let name = "x"\n  println("hi $na‸") }')
expect('interp still completes', interp !== null, true)
const self = completeAt('fn solo() -> Int = so‸')
expect('recursive self-reference completes', self!.options.some((o) => o.label === 'solo'), true)

console.log(fails === 0 ? 'ALL PASS' : `${fails} FAILURES`)
process.exit(fails === 0 ? 0 : 1)
