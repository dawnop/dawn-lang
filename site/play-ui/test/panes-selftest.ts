// The pane borders (src/panes.ts) without a browser: the arithmetic of a drag
// and a key, the clamp, storage that is there, absent or throwing, and one
// border driven through its DOM events. linkedom stands in for the document;
// it has no layout, so the border is handed a measure that reads the size it
// wrote back off the pane, which is all a drag needs: the container is 1000
// pixels, the pane starts at the stylesheet's 300. selftest.ts runs this after
// its own cases and adds the failures up.
import { readFileSync } from 'node:fs'
import { parseHTML } from 'linkedom'
import {
  KEY_STEP,
  STORE_KEY,
  Splitter,
  applyBasis,
  clampSize,
  dragSize,
  keyAction,
  loadRatio,
  percent,
  saveRatio,
  type Axis,
  type Mode,
  type Store,
} from '../src/panes'

type Expect = (name: string, got: unknown, want: unknown) => void

class MemStore {
  data = new Map<string, string>()
  getItem(k: string) { return this.data.get(k) ?? null }
  setItem(k: string, v: string) { this.data.set(k, v) }
}
// a private window: the object is there and every call throws
const throwing = {
  getItem(): string | null { throw new Error('SecurityError') },
  setItem(): void { throw new Error('QuotaExceededError') },
}

export function panesTests(expect: Expect): number {
  let fails = 0
  const t: Expect = (name, got, want) => {
    if (JSON.stringify(got) !== JSON.stringify(want)) fails++
    expect(name, got, want)
  }

  // ---- arithmetic ----
  t('a pane before its border grows with the drag', dragSize(300, 40, false), 340)
  t('a pane after its border shrinks with it', dragSize(300, 40, true), 260)
  t('clamp: a size in range is kept', clampSize(400, 128, 1000, 384), 400)
  t('clamp: no smaller than the pane minimum', clampSize(20, 128, 1000, 384), 128)
  t('clamp: leaves the rest its minimum', clampSize(900, 128, 1000, 384), 616)
  t('clamp: too small for both, the dragged pane stays visible', clampSize(300, 128, 400, 384), 128)
  t('arrows along a vertical border', [keyAction('ArrowLeft', 'x', false, false), keyAction('ArrowRight', 'x', false, false)],
    [{ delta: -KEY_STEP }, { delta: KEY_STEP }])
  t('Left grows a pane after the border, and Shift goes four times as far',
    keyAction('ArrowLeft', 'x', true, true), { delta: KEY_STEP * 4 })
  t('Up/Down move a horizontal border', [keyAction('ArrowUp', 'y', true, false), keyAction('ArrowDown', 'y', false, false)],
    [{ delta: KEY_STEP }, { delta: KEY_STEP }])
  t('the cross-axis arrows do nothing', [keyAction('ArrowUp', 'x', false, false), keyAction('ArrowLeft', 'y', false, false)], [null, null])
  t('Home and End are the ends', [keyAction('Home', 'x', false, false), keyAction('End', 'y', true, false)], ['min', 'max'])
  t('other keys are not the border\'s', keyAction('a', 'x', false, false), null)
  t('aria-valuenow is a whole percentage', [percent(333, 1000), percent(5, 0)], [33, 0])

  // ---- storage ----
  const mem = new MemStore()
  const memStore = () => mem as unknown as Store
  t('nothing stored reads as nothing', loadRatio(memStore, 'wide', 'view'), null)
  t('a ratio is stored', saveRatio(memStore, 'wide', 'view', 0.123456), true)
  t('and read back, rounded', loadRatio(memStore, 'wide', 'view'), 0.1235)
  t('per layout: the narrow one has its own', loadRatio(memStore, 'narrow', 'view'), null)
  saveRatio(memStore, 'narrow', 'view', 0.5)
  t('two layouts in one key', JSON.parse(mem.getItem(STORE_KEY)!), { wide: { view: 0.1235 }, narrow: { view: 0.5 } })
  saveRatio(memStore, 'wide', 'view', null)
  t('forgetting one leaves the other', [loadRatio(memStore, 'wide', 'view'), loadRatio(memStore, 'narrow', 'view')], [null, 0.5])
  mem.setItem(STORE_KEY, '{not json')
  t('a garbled value reads as nothing', loadRatio(memStore, 'narrow', 'view'), null)
  mem.setItem(STORE_KEY, JSON.stringify({ wide: { view: 7 } }))
  t('a ratio out of (0, 1) reads as nothing', loadRatio(memStore, 'wide', 'view'), null)
  const throws = () => throwing as unknown as Store
  t('throwing storage: read falls back', loadRatio(throws, 'wide', 'view'), null)
  t('throwing storage: write is refused, not thrown', saveRatio(throws, 'wide', 'view', 0.3), false)
  t('no storage at all', [loadRatio(() => null, 'wide', 'side'), saveRatio(() => null, 'wide', 'side', 0.3)], [null, false])
  t('a store accessor that throws', loadRatio(() => { throw new Error('denied') }, 'wide', 'side'), null)

  // ---- one border, through its events ----
  const { document: dom, window: win } = parseHTML('<!doctype html><html><body><div id="c"><div id="p"></div></div></body></html>')
  const g = globalThis as unknown as { document?: unknown }
  const before = g.document
  g.document = dom
  try {
    const container = dom.getElementById('c') as unknown as HTMLElement
    const pane = dom.getElementById('p') as unknown as HTMLElement
    const sizeOf = (el: HTMLElement) => (el === container ? 1000 : parseFloat(el.style.flexBasis) || 300)
    let resized = 0
    function border(store: () => Store, mode: Mode = 'wide', after = true) {
      return new Splitter({
        name: 'view',
        label: 'Resize the generated code',
        pane,
        container,
        after,
        axis: (m) => (m === 'wide' ? 'x' : 'y'),
        min: () => 200,
        restMin: () => 250,
        apply: applyBasis,
      }, { mode: () => mode, store, resized: () => resized++, measure: (el: HTMLElement, _a: Axis) => sizeOf(el) })
    }
    const ev = (type: string, fields: Record<string, unknown>) =>
      Object.assign(new win.Event(type, { cancelable: true }), fields) as unknown as Event
    const pointer = (s: Splitter, type: string, x: number) =>
      s.el.dispatchEvent(ev(type, { pointerId: 1, pointerType: 'mouse', button: 0, clientX: x, clientY: 0 }))
    const key = (s: Splitter, k: string, shift = false) => s.el.dispatchEvent(ev('keydown', { key: k, shiftKey: shift }))

    const store2 = new MemStore()
    const s = border(() => store2 as unknown as Store)
    t('the border is a focusable separator', [s.el.getAttribute('role'), s.el.getAttribute('tabindex'), s.el.getAttribute('aria-orientation')],
      ['separator', '0', 'vertical'])
    t('nothing stored: the stylesheet sizes the pane', [pane.style.flexBasis, s.el.getAttribute('aria-valuenow')], ['', '30'])
    t('its range is the clamp', [s.el.getAttribute('aria-valuemin'), s.el.getAttribute('aria-valuemax')], ['20', '75'])

    pointer(s, 'pointerdown', 500)
    t('a drag marks the page so no text is selected', dom.documentElement.classList.contains('dp-resizing'), true)
    pointer(s, 'pointermove', 400)
    t('dragging the border left by 100 grows the pane after it', pane.style.flexBasis, '400px')
    t('and the editor is told to relayout', resized > 0, true)
    pointer(s, 'pointermove', 0)
    t('the rest keeps its minimum', pane.style.flexBasis, '750px')
    pointer(s, 'pointermove', 900)
    t('the pane keeps its own', pane.style.flexBasis, '200px')
    pointer(s, 'pointermove', 450)
    pointer(s, 'pointerup', 450)
    t('the drag ends', dom.documentElement.classList.contains('dp-resizing'), false)
    t('the ratio is remembered for this layout', JSON.parse(store2.getItem(STORE_KEY)!), { wide: { view: 0.35 } })
    t('aria-valuenow follows', s.el.getAttribute('aria-valuenow'), '35')
    pointer(s, 'pointermove', 100)
    t('a move after the drag ended does nothing', pane.style.flexBasis, '350px')

    key(s, 'ArrowLeft')
    t('Left grows the pane by a step', pane.style.flexBasis, `${350 + KEY_STEP}px`)
    key(s, 'ArrowRight', true)
    t('Shift-Right shrinks it by four', pane.style.flexBasis, `${350 + KEY_STEP - 4 * KEY_STEP}px`)
    key(s, 'Home')
    t('Home: the smallest', pane.style.flexBasis, '200px')
    key(s, 'End')
    t('End: the largest', pane.style.flexBasis, '750px')

    // a new page in the same browser picks the ratio up
    applyBasis(pane, 'x', null)
    const again = border(() => store2 as unknown as Store)
    t('a reload applies the remembered ratio', pane.style.flexBasis, '750px')
    again.el.dispatchEvent(ev('dblclick', {}))
    t('double click hands the size back to the stylesheet', pane.style.flexBasis, '')
    t('and forgets it', JSON.parse(store2.getItem(STORE_KEY)!), { wide: {} })

    // storage that throws: the border still works, nothing is kept
    applyBasis(pane, 'x', null)
    const priv = border(() => throwing as unknown as Store)
    t('throwing storage: the default layout', pane.style.flexBasis, '')
    pointer(priv, 'pointerdown', 500)
    pointer(priv, 'pointermove', 450)
    pointer(priv, 'pointerup', 450)
    t('throwing storage: the drag still resizes', pane.style.flexBasis, '350px')

    // the narrow layout: a horizontal border, moved with Up and Down
    applyBasis(pane, 'x', null)
    const narrow = border(() => null, 'narrow')
    t('narrow: the border lies across', [narrow.el.getAttribute('aria-orientation'), narrow.el.dataset.axis], ['horizontal', 'y'])
    key(narrow, 'ArrowUp')
    t('narrow: Up grows the pane under it', pane.style.flexBasis, `${300 + KEY_STEP}px`)
    key(narrow, 'ArrowLeft')
    t('narrow: Left is not its key', pane.style.flexBasis, `${300 + KEY_STEP}px`)

    // a border that only the wide layout has (the sample list's): crossing
    // the breakpoint hands every size back to the stylesheet
    applyBasis(pane, 'x', null)
    let mode: Mode = 'wide'
    const sideOnly = new Splitter({
      name: 'side', label: 'Resize the sample list', pane, container, after: false,
      axis: (m) => (m === 'wide' ? 'x' : null),
      min: () => 100, restMin: () => 100, apply: applyBasis,
    }, { mode: () => mode, store: () => null, resized: () => {}, measure: (el: HTMLElement) => sizeOf(el) })
    key(sideOnly, 'ArrowRight')
    t('wide: the sample list is sized', [pane.style.flexBasis, pane.style.width], [`${300 + KEY_STEP}px`, 'auto'])
    mode = 'narrow'
    sideOnly.layout()
    t('narrow: no border, and no size left behind', [sideOnly.el.hidden, pane.style.flexBasis, pane.style.width], [true, '', ''])
  } finally {
    g.document = before
  }

  // ---- one scrollbar ----
  // The editor's scroller and the generated code once drew different bars
  // (the browser's default and the site's thin `pre`). Both must stay in the
  // one rule that sets them, for each engine's mechanism.
  const css = readFileSync(new URL('../src/playground.css', import.meta.url), 'utf8')
  const lists = [...css.matchAll(/\.dp-ide :is\(([^)]*)\)\s*\{/g)].map((m) => m[1])
  t('two scrollbar rules: the standard pair, and its reset for ::-webkit-scrollbar', lists.length, 2)
  t('both cover the editor and the listing', lists.map((l) => l.includes('.cm-scroller') && l.includes('.dp-view pre.xp-code')), [true, true])
  t('the two lists are the same', lists[0]?.replace(/\s+/g, ' ') === lists[1]?.replace(/\s+/g, ' '), true)
  return fails
}
