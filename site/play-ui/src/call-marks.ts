// The editor's half of the explorer: the calls the compile pane can follow,
// drawn in the source, and the picked call's whole span underlined.
//
// Why the ranges live in editor state and not in the pane's model. They are
// positions in a document the reader keeps typing in, so they are mapped
// through every change (a call whose text is deleted drops out, one that
// is typed beside keeps its place) by the same machinery that moves the
// squiggles. The pane's listing cannot follow an edit, so it goes stale when
// the text changes (compile-view.ts says so), but the underline under the call
// the reader has just picked is still on that call.
//
// A call's name is the thing to pick (a dashed underline, as on the static
// page); picking draws the span of the whole call, its arguments and the
// calls inside them included. CodeMirror's content is editable text, so a name
// cannot be a tab stop the way it is on the static page; the keyboard way in
// is Alt-Enter on the call under the caret, and Escape lets go. Enter itself
// stays a newline: it is the editor.
import { EditorView, Decoration, keymap, type DecorationSet } from '@codemirror/view'
import { StateEffect, StateField, type Extension, type Text } from '@codemirror/state'
import type { Pos, XCall } from './explorer-core'

export interface CallRange {
  id: number
  name: [number, number]
  span: [number, number]
}

export const setCalls = StateEffect.define<CallRange[]>()
export const pickCall = StateEffect.define<number | null>()

// The offset of `line:col` (both from 1, the column in code points) in `doc`,
// or null when the line is not there. A column past the end is the end.
export function offsetOf(doc: Text, at: Pos): number | null {
  const [line, col] = at
  if (line < 1 || line > doc.lines) return null
  const l = doc.line(line)
  let off = 0
  let n = 0
  for (const ch of l.text) {
    if (n >= col - 1) break
    off += ch.length
    n++
  }
  return l.from + off
}

// The ranges of `calls` in `doc`; a call whose position is not in the text is
// left out.
export function rangesOf(doc: Text, calls: XCall[]): CallRange[] {
  const out: CallRange[] = []
  for (const c of calls) {
    const a = offsetOf(doc, c.nfrom)
    const b = offsetOf(doc, c.nto)
    const s = offsetOf(doc, c.from)
    const e = offsetOf(doc, c.to)
    if (a === null || b === null || s === null || e === null || a >= b || s >= e) continue
    out.push({ id: c.id, name: [a, b], span: [s, e] })
  }
  return out
}

interface Marks {
  calls: CallRange[]
  picked: number | null
}

const field = StateField.define<Marks>({
  create: () => ({ calls: [], picked: null }),
  update(m, tr) {
    let { calls, picked } = m
    if (tr.docChanged) {
      const mapped: CallRange[] = []
      for (const c of calls) {
        const name: [number, number] = [tr.changes.mapPos(c.name[0], 1), tr.changes.mapPos(c.name[1], -1)]
        const span: [number, number] = [tr.changes.mapPos(c.span[0], 1), tr.changes.mapPos(c.span[1], -1)]
        if (name[0] < name[1] && span[0] < span[1]) mapped.push({ id: c.id, name, span })
      }
      calls = mapped
      if (picked !== null && !calls.some((c) => c.id === picked)) picked = null
    }
    for (const e of tr.effects) {
      if (e.is(setCalls)) {
        calls = e.value
        if (picked !== null && !calls.some((c) => c.id === picked)) picked = null
      }
      if (e.is(pickCall)) picked = e.value
    }
    return calls === m.calls && picked === m.picked ? m : { calls, picked }
  },
  provide: (f) =>
    EditorView.decorations.from(f, (m): DecorationSet => {
      const ds = []
      for (const c of m.calls) {
        const on = c.id === m.picked
        ds.push(
          Decoration.mark({
            class: on ? 'dp-call dp-call-pick' : 'dp-call',
            attributes: { 'data-call': String(c.id) },
          }).range(c.name[0], c.name[1]),
        )
        if (on) ds.push(Decoration.mark({ class: 'dp-call-on' }).range(c.span[0], c.span[1]))
      }
      return Decoration.set(ds, true)
    }),
})

// The innermost call at `pos`: the smallest span holding it, a later row
// (deeper) winning a tie.
export function callAtPos(m: { calls: CallRange[] }, pos: number): number | null {
  let best: CallRange | null = null
  for (const c of m.calls) {
    if (pos < c.span[0] || pos > c.span[1]) continue
    if (!best || c.span[1] - c.span[0] < best.span[1] - best.span[0] ||
        (c.span[1] - c.span[0] === best.span[1] - best.span[0] && c.id > best.id)) {
      best = c
    }
  }
  return best ? best.id : null
}

export function marksOf(state: EditorView['state']): { calls: CallRange[]; picked: number | null } {
  return state.field(field)
}

export interface CallHandlers {
  // a call's name was clicked, or Alt-Enter pressed on it
  pick(id: number): void
  // Alt-Enter with no call under the caret
  none(): void
  // Escape; true when it let go of something
  release(): boolean
}

export function callMarks(h: CallHandlers): Extension {
  return [
    field,
    EditorView.domEventHandlers({
      click(ev, view) {
        const t = ev.target as HTMLElement | null
        const el = t && t.closest ? t.closest<HTMLElement>('.dp-call') : null
        if (!el || !view.state.selection.main.empty) return false
        const id = Number(el.dataset.call)
        if (Number.isInteger(id)) h.pick(id)
        return false
      },
    }),
    keymap.of([
      {
        key: 'Alt-Enter',
        run: (view) => {
          const id = callAtPos(view.state.field(field), view.state.selection.main.head)
          if (id === null) h.none()
          else h.pick(id)
          return true
        },
      },
      { key: 'Escape', run: () => h.release() },
    ]),
  ]
}
