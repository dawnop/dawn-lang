// The compile pane's decisions, without a browser: the wire shape and its
// checks, who owns which listing line, what a click or a key means, what each
// answer of /compile becomes, where the open tab lives in the URL, and that
// the stylesheets still carry what the pane is drawn with. selftest.ts runs
// this after its own cases and adds the failures up.
//
// The fixture is one line, `let x = f(g(k(1)))`, three calls nested in each
// other, so that a line can have more than one owner and "innermost" is
// something a wrong answer can get wrong.
import { readFileSync } from 'node:fs'
import { EditorState, Text } from '@codemirror/state'
import { callAtPos, callMarks, marksOf, offsetOf, pickCall, rangesOf, setCalls } from '../src/call-marks'
import {
  AutoPolicy,
  NETWORK_MESSAGE,
  classify,
  messageOf,
  notesOf,
  TILE_NEEDS,
  TARGETS,
  targetOfSearch,
  tileNotes,
  wantsTileir,
  withView,
} from '../src/compile-state'
import { Model, moveAmong, moveTab, readView, runs, statusText } from '../src/explorer-core'

type Expect = (name: string, got: unknown, want: unknown) => void

const CALLS = [
  { id: 0, parent: -1, name: 'f', from: [2, 11], to: [2, 21], nfrom: [2, 11], nto: [2, 12] },
  { id: 1, parent: 0, name: 'g', from: [2, 13], to: [2, 20], nfrom: [2, 13], nto: [2, 14] },
  { id: 2, parent: 1, name: 'k', from: [2, 15], to: [2, 19], nfrom: [2, 15], nto: [2, 16] },
]

// C lines 1..4. Line 3 is f's and g's, line 2 is g's and k's, line 1 is k's,
// line 4 is nobody's. Call 0's instruction is on line 3.
function wire(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ok: true,
    phase: 'compile-view',
    target: 'c',
    build: 'b1:x',
    cached: false,
    ms: 12,
    src: { first: 1, last: 3 },
    calls_total: 3,
    calls_truncated: false,
    calls: CALLS,
    pane: {
      kind: 'c',
      total: 4,
      shown: 4,
      truncated: false,
      text: ['int a = 1;', 'int b = k(a);', 'int c = f(b);', '}'],
      outs: [
        { call: 0, lines: [[3, 4]], marks: [[3, 8, 12]], key: [3] },
        { call: 1, lines: [[2, 4]], marks: [], key: [] },
        { call: 2, lines: [[1, 3]], marks: [[2, 8, 9]], key: [] },
      ],
    },
    gaps: { count: 0, first: [] },
    ...over,
  }
}

function model(): Model {
  const v = readView(wire())
  if (!v) throw new Error('the fixture does not read')
  return new Model(v)
}

// `f` is not at the same place in the text and in the table, which is exactly
// what a stale answer looks like.
const SRC = 'fn main() {\n  let x = f(g(k(1)))\n}'

export function compileViewTests(expect: Expect): number {
  let fails = 0
  const t: Expect = (name, got, want) => {
    if (JSON.stringify(got) !== JSON.stringify(want)) fails++
    expect(name, got, want)
  }

  // ---- the wire ----
  t('the fixture reads', readView(wire()) !== null, true)
  const bad = (name: string, over: Record<string, unknown>) => t(`a malformed answer is refused: ${name}`, readView(wire(over)), null)
  bad('a call whose row is not its id', { calls: [{ ...CALLS[0], id: 5 }] })
  bad('a parent that comes after', { calls: [{ ...CALLS[0], parent: 1 }, CALLS[1], CALLS[2]] })
  bad('a span that ends before it starts', { calls: [{ ...CALLS[0], to: [2, 3] }, CALLS[1], CALLS[2]] })
  bad('text that is not the shown count', { pane: { ...(wire().pane as object), shown: 3 } })
  bad(
    'a run past the text',
    { pane: { ...(wire().pane as object), outs: [{ call: 0, lines: [[3, 9]], marks: [], key: [] }] } },
  )
  bad(
    'a mark outside its line',
    { pane: { ...(wire().pane as object), outs: [{ call: 0, lines: [[3, 4]], marks: [[3, 8, 99]], key: [] }] } },
  )
  bad(
    'an account of a call that is not there',
    { pane: { ...(wire().pane as object), outs: [{ call: 7, lines: [], marks: [], key: [] }] } },
  )
  t('null and a string are not an answer', [readView(null), readView('x')], [null, null])

  // ---- who owns what ----
  const m = model()
  t('a line is owned by every call that wrote it, the innermost first', [1, 2, 3, 4].map((n) => m.ownersOf(n)), [[2], [2, 1], [1, 0], []])
  t('a clicked line is the innermost owner', [1, 2, 3, 4].map((n) => m.innermostAt(n)), [2, 2, 1, null])
  t('only owned lines are tab stops', m.ownedLines(), [1, 2, 3])
  t('the outermost call marks its own line and the lines of the calls inside it fainter', m.mark(0), {
    hit: [3], inner: [1, 2], ipc: [3], marks: [[3, 8, 12]],
  })
  t('the middle call', m.mark(1), { hit: [2, 3], inner: [1], ipc: [], marks: [] })
  t('the innermost call has no fainter lines', m.mark(2), { hit: [1, 2], inner: [], ipc: [], marks: [[2, 8, 9]] })
  t('a call is under itself and its ancestors, not the other way', [m.under(2, 0), m.under(0, 2), m.under(1, 1)], [true, false, true])
  t('the caret picks the smallest span that holds it', [[2, 16], [2, 14], [2, 12], [2, 11], [2, 5], [3, 1]].map(([l, c]) => m.innermostCallAt(l, c)), [2, 1, 0, 0, null, null])

  // ---- the keyboard ----
  t('the arrows go between owned lines and stop at the ends', ['ArrowDown', 'ArrowUp', 'Home', 'End'].map((k) => moveAmong([1, 2, 3], 2, k)), [3, 1, 1, 3])
  t('the ends do not wrap', [moveAmong([1, 2, 3], 3, 'ArrowDown'), moveAmong([1, 2, 3], 1, 'ArrowUp')], [3, 1])
  t('a key that is not a move goes nowhere', [moveAmong([1], 1, 'a'), moveAmong([], 0, 'Home')], [null, null])
  t('the tabs wrap and Home and End jump', ['ArrowRight', 'ArrowLeft', 'Home', 'End', 'x'].map((k) => moveTab(2, 0, k)), [1, 1, 0, 1, null])

  // ---- the words ----
  t('lines read as runs', [runs([3]), runs([1, 2, 3, 5, 7, 8])], ['3', '1–3, 5, 7–8'])
  t('the status line says the call, its place and where it landed', statusText(CALLS[0] as never, 'C', [3]), 'f · 2:11–2:21 → C line 3')
  t('several lines are lines', statusText(CALLS[1] as never, 'JVM', [2, 3, 6]), 'g · 2:13–2:20 → JVM lines 2–3, 6')
  t('a call with no lines says so', statusText(CALLS[2] as never, 'C', []), 'k · 2:15–2:19 → C: no lines of its own')

  // ---- the editor's ranges ----
  const doc = Text.of(SRC.split('\n'))
  t('a column is in code points, from 1', offsetOf(doc, [2, 11]), 12 + 10)
  t('a column past the end is the end', offsetOf(doc, [3, 99]), SRC.length)
  t('a line that is not there has no offset', [offsetOf(doc, [9, 1]), offsetOf(doc, [0, 1])], [null, null])
  const astral = Text.of(['let s = "😀"; f()'])
  t('an astral character counts as one column', offsetOf(astral, [1, 14]), 14)
  const rs = rangesOf(doc, CALLS as never)
  t('a call is its name and its span', rs.map((r) => [r.id, r.name, r.span]), [
    [0, [22, 23], [22, 32]], [1, [24, 25], [24, 31]], [2, [26, 27], [26, 30]],
  ])
  t('the innermost call at a position', [22, 24, 26, 28, 5].map((p) => callAtPos({ calls: rs }, p)), [0, 1, 2, 2, null])
  t('a call that is not in the text is left out', rangesOf(Text.of(['x']), CALLS as never), [])

  const st0 = EditorState.create({ doc: SRC, extensions: [callMarks({ pick() {}, none() {}, release: () => false })] })
  const st1 = st0.update({ effects: [setCalls.of(rs), pickCall.of(1)] }).state
  t('the state holds the calls and the pick', [marksOf(st1).calls.length, marksOf(st1).picked], [3, 1])
  const typed = st1.update({ changes: { from: 0, insert: 'XX' } }).state
  t('typing before a call moves its ranges with it', marksOf(typed).calls[0].span, [24, 34])
  const inside = st1.update({ changes: { from: 28, to: 29, insert: 'zz' } }).state
  t('typing inside a call keeps it', marksOf(inside).calls.map((c) => c.id), [0, 1, 2])
  const gone = st1.update({ changes: { from: 22, to: 33, insert: '' } }).state
  t('deleting a call drops it, and the pick if it was that call', [marksOf(gone).calls.length, marksOf(gone).picked], [0, null])
  const kept = st1.update({ changes: { from: 26, to: 30, insert: '' } }).state
  t('deleting an inner call leaves the pick on the outer one', [marksOf(kept).calls.map((c) => c.id), marksOf(kept).picked], [[0, 1], 1])
  const fresh = st1.update({ effects: setCalls.of(rs.slice(0, 1)) }).state
  t('a new table without the picked call lets go of it', marksOf(fresh).picked, null)

  // ---- what an answer means ----
  const ok = classify(200, wire(), 'c')
  t('a good answer is a view', [ok.kind, ok.kind === 'ok' ? [ok.cached, ok.ms] : null], ['ok', [false, 12]])
  t('an answer for the other tab is not this tab\'s', classify(200, wire(), 'jvm').kind, 'unreadable')
  t('a listing that does not check is unreadable', classify(200, wire({ calls: 'x' }), 'c').kind, 'unreadable')
  const diag = classify(200, { ok: false, phase: 'compile', output: 'error: no\n  --> prog.dawn:1:1' }, 'c')
  t('compile errors carry the diagnostics verbatim', diag, { kind: 'diagnostics', text: 'error: no\n  --> prog.dawn:1:1' })
  t('429 is busy, 413 too long, 422 too large, 503 unavailable', [429, 413, 422, 503].map((s) => classify(s, { ok: false, phase: 'error', output: 'x' }, 'c').kind), ['busy', 'too-long', 'too-large', 'unavailable'])
  t('anything else names the status', classify(500, { ok: false, phase: 'error', output: 'boom' }, 'c'), { kind: 'failed', status: 500, detail: 'boom' })
  t('a body that is not JSON is a failure, not a crash', classify(502, null, 'c'), { kind: 'failed', status: 502, detail: '' })
  const said = [429, 413, 422, 503, 500].map((s) => messageOf(classify(s, null, 'c')))
  t('every failure has its own sentence', new Set(said).size, 5)
  t('503 says javap is the reason', said[3].includes('javap'), true)
  t('a network error has a sentence', NETWORK_MESSAGE.length > 0, true)
  t('a clean answer has no notes', notesOf(readView(wire())!, 'C'), [])
  const gappy = readView(wire({ gaps: { count: 2, first: ['a', 'b'] }, calls_truncated: true, calls_total: 9 }))!
  t('gaps and a cut call table are notes, not errors', notesOf(gappy, 'C').length, 2)
  const cut = readView(wire({ pane: { ...(wire().pane as object), truncated: true, total: 99 } }))!
  t('a cut listing says how much is shown', notesOf(cut, 'C'), ['The C listing is cut: showing 4 of 99 lines.'])

  // ---- the Tile IR tab ----
  const tileWire = (over: Record<string, unknown> = {}) => ({
    ok: true,
    phase: 'compile-view',
    target: 'tile',
    build: 'b1:x',
    cached: false,
    ms: 2600,
    pane: { kind: 'tile', total: 2, shown: 2, truncated: false, text: ['cuda_tile.module @m {', '}'] },
    ...over,
  })
  t('the tab is offered for a program that imports tileir', [wantsTileir('use tileir/dev.{Dev}\n'), wantsTileir('use std/io\n'), wantsTileir('use tileir.dev')], [true, false, false])
  t('the tabs are C, JVM and Tile IR', TARGETS.map((x) => x.label), ['C', 'JVM', 'Tile IR'])
  t('the program\'s text is the pane', classify(200, tileWire(), 'tile'), {
    kind: 'tile', tile: { text: ['cuda_tile.module @m {', '}'], total: 2, truncated: false }, cached: false, ms: 2600,
  })
  // a kernel whose calls were paired with the source answers as a listing
  const paired = (over: Record<string, unknown> = {}) =>
    wire({ target: 'tile', pane: { ...(wire().pane as object), kind: 'tile' }, ...over })
  const pk = classify(200, paired(), 'tile')
  t('a paired kernel is a listing of the tile tab', [pk.kind, pk.kind === 'ok' ? pk.view.pane.kind : null], ['ok', 'tile'])
  t('a paired answer with another pane kind is unreadable', classify(200, wire({ target: 'tile' }), 'tile').kind, 'unreadable')
  t('a paired answer whose calls do not check is unreadable', classify(200, paired({ calls: [{ ...CALLS[0], id: 5 }] }), 'tile').kind, 'unreadable')
  t('a paired answer is not the C tab\'s', classify(200, paired(), 'c').kind, 'unreadable')
  t('without calls the tile tab keeps the plain text, with the reason', classify(200, tileWire({ unmapped: 'a call under host control flow at line 9' }), 'tile'), {
    kind: 'tile', tile: { text: ['cuda_tile.module @m {', '}'], total: 2, truncated: false, unmapped: 'a call under host control flow at line 9' }, cached: false, ms: 2600,
  })
  t('the reason is a note under the tabs', tileNotes({ text: ['a'], total: 1, truncated: false, unmapped: 'x' }), ['Calls are not matched to the Tile IR: x.'])
  t('a tile answer is not another tab\'s', [classify(200, tileWire(), 'c').kind, classify(200, wire(), 'tile').kind], ['unreadable', 'unreadable'])
  t('a tile pane whose count is not its text is unreadable', classify(200, tileWire({ pane: { kind: 'tile', total: 2, shown: 5, truncated: false, text: ['a'] } }), 'tile').kind, 'unreadable')
  t('a program that fails shows its output under its own heading', [
    classify(200, { ok: false, phase: 'run', exit: 1, output: 'boom' }, 'tile'),
    classify(200, { ok: false, phase: 'timeout', output: 'x' }, 'tile'),
  ], [{ kind: 'program', title: 'Run error', text: 'boom' }, { kind: 'program', title: 'Timed out', text: 'x' }])
  t('a compile error of the tile program is the diagnostics', classify(200, { ok: false, phase: 'compile', output: 'e' }, 'tile').kind, 'diagnostics')
  t('the server\'s one-sentence refusal is what the reader sees', messageOf(classify(400, { ok: false, phase: 'error', output: 'the Tile IR view needs a program that imports tileir' }, 'tile')), 'the Tile IR view needs a program that imports tileir')
  t('503 for the tile tab does not blame javap', [messageOf(classify(503, null, 'tile')).includes('javap'), messageOf(classify(503, null, 'c')).includes('javap')], [false, true])
  t('without tileir the tab says what it needs', TILE_NEEDS.includes('tileir'), true)
  t('a cut tile text says how much is shown', tileNotes({ text: ['a'], total: 9, truncated: true }), ['The Tile IR text is cut: showing 1 of 9 lines.'])
  t('a whole tile text has no notes', tileNotes({ text: ['a'], total: 1, truncated: false }), [])

  // ---- automatic compiling ----
  const p = new AutoPolicy()
  t('automatic compiling starts on', p.auto, true)
  p.busy()
  p.accepted(false)
  t('busy turns it off and an automatic answer does not turn it on', p.auto, false)
  p.accepted(true)
  t('a compile the reader asked for turns it back on', p.auto, true)

  // ---- the URL ----
  t('view names the tab', [targetOfSearch('?view=c'), targetOfSearch('?view=jvm'), targetOfSearch('?view=tile'), targetOfSearch('?a=1&view=jvm')], ['c', 'jvm', 'tile', 'jvm'])
  t('no view, or a tab this build does not have, is closed', [targetOfSearch(''), targetOfSearch('?view=asm'), targetOfSearch('?view=output'), targetOfSearch('?view=')], [null, null, null, null])
  t('the tab goes in the query and the program stays in the hash', withView('https://x.test/play.html#bGV0', 'jvm'), 'https://x.test/play.html?view=jvm#bGV0')
  t('closing removes only view', withView('https://x.test/play.html?a=1&view=c#bGV0', null), 'https://x.test/play.html?a=1#bGV0')
  t('switching tabs replaces it', withView('https://x.test/play.html?view=c#h', 'jvm'), 'https://x.test/play.html?view=jvm#h')

  // ---- the stylesheets ----
  // The pane is drawn with the static explorer's classes, whose rules are the
  // site's. If style.css stops saying how they look, the pane would keep
  // working and quietly stop being drawn: say so here.
  const site = readFileSync(new URL('../../assets/style.css', import.meta.url), 'utf8')
  for (const sel of ['.xl {', '.xl.xp-hit', '.xl.xp-in', '.xl.xp-ipc', '.xp [data-k].xp-on', '.xp-tab[aria-selected="true"]', '.xp-status', '.xp pre.xp-code', '.xp-live .xl[data-o]']) {
    t(`style.css still styles ${sel}`, site.includes(sel), true)
  }
  // No horizontal page scroll at 375 px: in the narrow layout the generated
  // code goes under the editor, every flex item that holds text may shrink,
  // and the listing scrolls in its own box. The real width is measured in a
  // browser (test/layout-check.mjs); this holds the rules that make it so.
  const css = readFileSync(new URL('../src/playground.css', import.meta.url), 'utf8')
  const narrow = css.slice(css.indexOf('@media (max-width: 44rem)'))
  t('narrow: the work area stacks', /\.dp-work\s*\{\s*flex-direction:\s*column/.test(narrow), true)
  t('narrow: the pane is the screen wide, not wider', /\.dp-view\s*\{[^}]*width:\s*100%/.test(narrow), true)
  t('the pane and the work area may shrink', [/\.dp-work\s*\{[^}]*min-width:\s*0/.test(css), /\.dp-view\s*\{[^}]*min-width:\s*0/.test(css)], [true, true])
  t('the listing scrolls in its own box', /\.xp pre\.xp-code[^}]*overflow:\s*auto/.test(site), true)

  // The run limits live in a "?" popover in the output header, not on a row
  // of their own: if these rules go, the note would render as a bare line.
  for (const sel of ['.dp-help {', '.dp-help[aria-expanded', '.dp-limits[hidden]', '.dp-limits {', 'bottom: calc(100% + 0.3rem)']) {
    t(`playground.css still styles ${sel}`, css.includes(sel), true)
  }

  return fails
}
