// Drive target changes through the real pane and its DOM. Different tables
// deliberately reuse ids for different calls, so carrying an index goes red.
import { parseHTML } from 'linkedom'
import { EditorState } from '@codemirror/state'
import { keymap, type EditorView } from '@codemirror/view'
import { callMarks, marksOf, pickCall, rangesOf, setCalls } from '../src/call-marks'
import { ComparePane } from '../src/compile-view'
import { identityOf, matchIdentity, SELECTION_MISSING } from '../src/compile-state'
import type { XCall } from '../src/explorer-core'

type Expect = (name: string, got: unknown, want: unknown) => void
const calls: XCall[] = [
  { id: 0, parent: -1, name: 'outer', from: [1, 1], to: [1, 15], nfrom: [1, 1], nto: [1, 6] },
  { id: 1, parent: 0, name: 'inner', from: [1, 7], to: [1, 14], nfrom: [1, 7], nto: [1, 12] },
  { id: 2, parent: -1, name: 'later', from: [1, 17], to: [1, 24], nfrom: [1, 17], nto: [1, 22] },
]
const paired = calls.slice(1).map((c, i) => ({ ...c, id: i, parent: -1 }))
const wire = (target: string, cs = calls, build = 'b1:same', cached = false) => ({
  ok: true, phase: 'compile-view', target, build, cached, ms: 1,
  src: { first: 1, last: 1 }, calls: cs, calls_total: cs.length, calls_truncated: false,
  pane: { kind: target, text: ['outer', 'inner', 'later'], total: 3, shown: 3, truncated: false,
    outs: cs.map(c => ({ call: c.id, lines: [[c.name === 'inner' ? 2 : c.name === 'outer' ? 1 : 3, c.name === 'inner' ? 3 : c.name === 'outer' ? 2 : 4]], marks: [], key: [] })) },
  gaps: { count: 0, first: [] },
})

export async function comparePaneTests(expect: Expect): Promise<number> {
  let fails = 0
  const t: Expect = (n, got, want) => { if (JSON.stringify(got) !== JSON.stringify(want)) fails++; expect(n, got, want) }
  const { document, window } = parseHTML('<!doctype html><html><body></body></html>')
  const saved = { document: globalThis.document, window: globalThis.window, fetch: globalThis.fetch }
  Object.assign(globalThis, { document, window })
  let code = 'outer(inner()); later()\nuse tileir/dev.{Dev}'
  let marked: XCall[] = []
  let picked: number | null = null
  const pending: { target: string; resolve: (r: unknown) => void }[] = []
  globalThis.fetch = ((_url: unknown, options: { body: string }) => new Promise(resolve => {
    pending.push({ target: JSON.parse(options.body).target, resolve })
  })) as typeof fetch
  const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() }
  const answer = async (body: unknown, status = 200) => {
    const req = pending.shift()!
    req.resolve({ status, json: async () => body })
    await tick()
  }
  let pane: ComparePane
  let editor = EditorState.create({ doc: code, extensions: [callMarks({ pick: id => pane.pick(id), none() {}, release: () => { pane.pick(null); return true } })] })
  pane = new ComparePane({
    endpoint: '/compile', code: () => code, opened() {},
    calls: cs => { marked = cs; editor = editor.update({ effects: setCalls.of(rangesOf(editor.doc, cs)) }).state },
    picked: id => { picked = id; editor = editor.update({ effects: pickCall.of(id) }).state },
  })
  document.body.appendChild(pane.root as never)
  const statusText = () => pane.root.querySelector('.xp-status')!.textContent
  try {
    const identity = identityOf(code, 'b1:same', calls[1])
    t('identity resolves a different local id', matchIdentity(identity, code, 'b1:same', paired), 0)
    t('identity rejects duplicates, edits, builds and same-name spans', [
      matchIdentity(identity, code, 'b1:same', [paired[0], { ...paired[0], id: 1 }]),
      matchIdentity(identity, code + ' ', 'b1:same', paired),
      matchIdentity(identity, code, 'other', paired),
      matchIdentity(identity, code, 'b1:same', [{ ...paired[0], to: [1, 15] }]),
    ], [null, null, null, null])
    pane.open('c'); await answer(wire('c'))
    editor = editor.update({ selection: { anchor: 8 } }).state
    const altEnter = editor.facet(keymap).flat().find(k => k.key === 'Alt-Enter')!.run!
    altEnter({ state: editor } as EditorView)
    t('Alt-Enter picks the source span through CodeMirror', [marksOf(editor).picked, marksOf(editor).calls[1].span], [1, [6, 13]])
    t('C installs its local table and pick', [marked.length, picked], [3, 1])
    pane.open('jvm')
    t('cold switch clears source marks until its answer arrives', [marked.length, picked], [0, null])
    await answer(wire('jvm', paired))
    t('cold JVM switch resolves inner to id zero', picked, 0)
    t('JVM remapping installs the same CodeMirror source span under its local id', [marksOf(editor).picked, marksOf(editor).calls[0].span], [0, [6, 13]])
    pane.open('c')
    t('existing C answer restores inner to id one', picked, 1)
    pane.pick(0)
    pane.open('jvm')
    t('C-only outer has no JVM highlight or guessed neighbor', [picked, statusText()], [null, SELECTION_MISSING])
    pane.open('c')
    t('return restores missing outer', picked, 0)
    pane.open('tile'); await answer({ ...wire('tile'), calls: undefined, pane: { kind: 'tile', text: ['tile'], shown: 1, total: 1, truncated: false } })
    t('plain Tile transit explains the absent selection', [picked, statusText()], [null, SELECTION_MISSING])
    pane.open('c'); t('Tile transit retains source identity', picked, 0)
    pane.open('jvm'); void pane.compile(true) // fetch remains pending
  // A request may be pending across switches. Resolve it only after a newer
  // C request, even though the fetch stub deliberately ignores AbortSignal.
  pane.open('c')
  const fresh = pane.compile(true)
  const old = pending.shift()!
  await answer(wire('c', calls, 'b1:same', true))
  await fresh
  old.resolve({ status: 503, json: async () => ({ output: 'no javap' }) }); await tick()
  t('an old target response cannot replace C', [picked, pane.root.classList.contains('dp-stale')], [0, false])
  pane.open('jvm')
  const jtask = pane.compile(true)
  await answer({ ok: false, phase: 'error', output: 'no javap' }, 503)
  await jtask
  t('unavailable JVM keeps tab, marks listing stale, clears active source selection', [
    pane.root.querySelector('[data-kind="jvm"]')!.hasAttribute('hidden'),
    pane.root.classList.contains('dp-stale'), picked, marked.length,
  ], [false, true, null, 0])
  pane.open('c'); t('JVM failure leaves C and selection intact', [picked, pane.root.classList.contains('dp-stale')], [0, false])
  pane.edited(); code += ' '
  t('editing clears retained identity and marks', [pane.hasPick(), picked, marked.length], [false, null, 0])
  pane.open('jvm'); await answer(wire('jvm', paired))
  t('editing never revives an old numeric pick', picked, null)
  pane.pick(0)
  const ev = new window.Event('keydown', { bubbles: true, cancelable: true })
  Object.assign(ev, { key: 'Escape' }); pane.root.dispatchEvent(ev as never)
  t('Escape clears active and retained identity', [pane.hasPick(), picked], [false, null])
  pane.pick(0); pane.close(); pane.open('c'); await answer(wire('c'))
  t('closing clears the identity', [pane.hasPick(), picked], [false, null])
  pane.pick(1); await (async () => { const task = pane.compile(true); await answer(wire('c', calls, 'new-build')); await task })()
  t('new build clears selection context', [pane.hasPick(), picked], [false, null])
  pane.pick(1)
  const cut = pane.compile(true)
  await answer({ ...wire('c', [calls[0]], 'new-build'), calls_total: 2001, calls_truncated: true })
  await cut
  t('a truncated destination clears highlight and explains the missing identity', [picked, statusText()], [null, SELECTION_MISSING])
  pane.pick(null)
  t('Escape or cancel also clears a missing retained identity', pane.hasPick(), false)
  const restored = pane.compile(true); await answer(wire('c', calls, 'new-build')); await restored
  pane.root.querySelector('.xl[data-n="2"]')!.dispatchEvent(new window.Event('click', { bubbles: true }) as never)
  t('listing click selects the local inner call', picked, 1)
  const line = pane.root.querySelector('.xl[data-n="3"]')!
  const key = new window.Event('keydown', { bubbles: true, cancelable: true })
  Object.assign(key, { key: 'Enter' }); line.dispatchEvent(key as never)
  t('keyboard listing activation agrees with line ownership', picked, 2)

  return fails
  } finally {
    pane.close()
    Object.assign(globalThis, saved)
  }
}
