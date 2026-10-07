// The explorer's decisions, without a DOM: which lines a picked call owns,
// which lines the calls inside it own, which instruction is its own, who a
// clicked line belongs to, where the arrow keys go, and what the status line
// says. The Playground's compile pane (compile-view.ts) draws these answers
// and the editor (call-marks.ts) underlines the spans; neither decides
// anything, so every rule here is testable in node (test/selftest.ts).
//
// Why this is a second copy of site/assets/explorer.js's rules and not the
// one file both pages import. explorer.js is a plain script the site ships
// byte for byte (fingerprinted, no build step, no modules) and it reads its
// facts from attributes in server-generated HTML, which is the only form the
// page without script can be complete in. This bundle receives JSON and draws
// the lines itself, so the two cannot share a function, only a contract, and
// the contract is the DOM's: the same class names (`xl`, `xp-hit`, `xp-in`,
// `xp-ipc`, `xp-on`), the same `data-o` / `data-i` / `data-k` attributes on a
// line, and the same words in the status line. The stylesheet is the site's
// (`.xl`, `.xp-tab` ...), and test/selftest.ts fails when style.css stops
// carrying a selector this pane uses. Making explorer.js a build product of
// this bundle would change published bytes and put node under the static
// page's build for a hundred lines; sharing the rules the page can state is
// cheaper than sharing code it cannot.
//
// What the wire holds (docs/playground-compile-design.md 6.1): lines are 1
// based and a run `[a, z)` is half open; positions are `[line, column]`, 1
// based, in code points, and `to` is exclusive; a C mark `[line, a, z]` is a
// 0 based, half open column range of that listing line.

export type Pos = [number, number]

export interface XCall {
  id: number
  parent: number
  name: string
  from: Pos
  to: Pos
  nfrom: Pos
  nto: Pos
}

export interface XOut {
  call: number
  lines: [number, number][]
  marks: [number, number, number][]
  key: number[]
}

export interface XPane {
  kind: string
  total: number
  shown: number
  truncated: boolean
  text: string[]
  outs: XOut[]
}

export interface XGaps {
  count: number
  first: string[]
}

export interface XView {
  calls: XCall[]
  callsTotal: number
  callsTruncated: boolean
  pane: XPane
  gaps: XGaps
}

function isInt(x: unknown): x is number {
  return typeof x === 'number' && Number.isInteger(x)
}
function isPos(x: unknown): x is Pos {
  return Array.isArray(x) && x.length === 2 && isInt(x[0]) && isInt(x[1]) && x[0] >= 1 && x[1] >= 1
}
function before(a: Pos, b: Pos): boolean {
  return a[0] < b[0] || (a[0] === b[0] && a[1] < b[1])
}

// The answer's tables, checked the way the static page checks its own
// (gen/explorer.dawn `check`): a call is its row, its parent comes before it,
// its spans are ordered, every line is in the text and every mark is in its
// line. Anything else is `null`, so a service that drifts from the wire shows
// as "cannot read" and not as a pane that highlights the wrong line.
export function readView(j: unknown): XView | null {
  if (typeof j !== 'object' || j === null) return null
  const o = j as Record<string, unknown>
  const p = o.pane as Record<string, unknown> | undefined
  const g = o.gaps as Record<string, unknown> | undefined
  if (!p || !g || !Array.isArray(o.calls) || !Array.isArray(p.text) || !Array.isArray(p.outs)) return null
  if (typeof p.kind !== 'string' || !isInt(p.total) || !isInt(p.shown) || !Array.isArray(g.first) || !isInt(g.count)) {
    return null
  }
  const text = p.text as unknown[]
  if (!text.every((t) => typeof t === 'string') || text.length !== p.shown) return null
  const calls: XCall[] = []
  for (const c of o.calls as unknown[]) {
    const r = c as Record<string, unknown>
    if (typeof c !== 'object' || c === null) return null
    if (r.id !== calls.length || !isInt(r.parent) || typeof r.name !== 'string') return null
    if (r.parent < -1 || r.parent >= calls.length) return null
    if (!isPos(r.from) || !isPos(r.to) || !isPos(r.nfrom) || !isPos(r.nto)) return null
    if (!before(r.from, r.to) || !before(r.nfrom, r.nto)) return null
    calls.push({ id: r.id, parent: r.parent, name: r.name, from: r.from, to: r.to, nfrom: r.nfrom, nto: r.nto })
  }
  const shown = p.shown
  const outs: XOut[] = []
  for (const x of p.outs as unknown[]) {
    const r = x as Record<string, unknown>
    if (typeof x !== 'object' || x === null) return null
    if (!isInt(r.call) || r.call < 0 || r.call >= calls.length) return null
    if (!Array.isArray(r.lines) || !Array.isArray(r.marks) || !Array.isArray(r.key)) return null
    const lines: [number, number][] = []
    for (const l of r.lines as unknown[]) {
      if (!Array.isArray(l) || l.length !== 2 || !isInt(l[0]) || !isInt(l[1])) return null
      if (l[0] < 1 || l[0] >= l[1] || l[1] > shown + 1) return null
      lines.push([l[0], l[1]])
    }
    const marks: [number, number, number][] = []
    for (const m of r.marks as unknown[]) {
      if (!Array.isArray(m) || m.length !== 3 || !m.every(isInt)) return null
      const [l, a, z] = m as number[]
      if (l < 1 || l > shown || a < 0 || a >= z || z > [...text[l - 1]].length) return null
      marks.push([l, a, z])
    }
    const key: number[] = []
    for (const l of r.key as unknown[]) {
      if (!isInt(l) || l < 1 || l > shown) return null
      key.push(l)
    }
    outs.push({ call: r.call, lines, marks, key })
  }
  const src = o.src as Record<string, unknown> | undefined
  if (!src || !isInt(src.first) || !isInt(src.last)) return null
  return {
    calls,
    callsTotal: isInt(o.calls_total) ? o.calls_total : calls.length,
    callsTruncated: o.calls_truncated === true,
    pane: { kind: p.kind, total: p.total, shown, truncated: p.truncated === true, text: text as string[], outs },
    gaps: { count: g.count, first: (g.first as unknown[]).filter((s): s is string => typeof s === 'string') },
  }
}

// ---- the model ----

export interface Marked {
  hit: number[] // the lines the call wrote itself
  inner: number[] // the lines only the calls inside it wrote
  ipc: number[] // the lines holding its own instruction (JVM)
  marks: [number, number, number][] // the columns it holds (C)
}

export class Model {
  readonly parent: number[]
  // Per listing line, its owners, the innermost first (deeper in the tree,
  // the earlier; at one depth, the earlier row): gen/explorer.dawn owners_of.
  private readonly owners = new Map<number, number[]>()
  private readonly made = new Map<number, number[]>()
  private readonly outOf = new Map<number, XOut>()

  constructor(readonly view: XView) {
    this.parent = view.calls.map((c) => c.parent)
    const depth = view.calls.map((_, i) => this.depthOf(i))
    for (const o of view.pane.outs) {
      this.outOf.set(o.call, o)
      for (const [a, z] of o.lines) {
        for (let n = a; n < z; n++) {
          const list = this.owners.get(n) ?? []
          list.push(o.call)
          this.owners.set(n, list)
        }
      }
      for (const n of o.key) {
        const list = this.made.get(n) ?? []
        list.push(o.call)
        this.made.set(n, list)
      }
    }
    for (const list of this.owners.values()) list.sort((a, b) => depth[b] - depth[a] || a - b)
  }

  private depthOf(id: number): number {
    let d = 0
    for (let k = this.parent[id]; k >= 0 && d < 64; k = this.parent[k]) d++
    return d
  }

  ownersOf(line: number): number[] {
    return this.owners.get(line) ?? []
  }
  madeBy(line: number): number[] {
    return this.made.get(line) ?? []
  }

  // Whether call `k` is `id` or inside it, by the call tree.
  under(k: number, id: number): boolean {
    for (let n = 0; k >= 0 && n < 64; n++) {
      if (k === id) return true
      k = this.parent[k]
    }
    return false
  }

  // The lines a pick marks. A call's own lines are `hit`; a line owned only by
  // calls inside it is `inner` (fainter); `ipc` is the instruction.
  mark(id: number): Marked {
    const hit: number[] = []
    const inner: number[] = []
    for (const [n, os] of [...this.owners.entries()].sort((a, b) => a[0] - b[0])) {
      if (os.includes(id)) hit.push(n)
      else if (os.some((o) => this.under(o, id))) inner.push(n)
    }
    const ipc = [...this.made.entries()].filter(([, cs]) => cs.includes(id)).map(([n]) => n).sort((a, b) => a - b)
    return { hit, inner, ipc, marks: this.outOf.get(id)?.marks ?? [] }
  }

  // The call a clicked listing line stands for: its innermost owner.
  innermostAt(line: number): number | null {
    const os = this.ownersOf(line)
    return os.length ? os[0] : null
  }

  // The lines that can be picked, in order: the listing's tab stops.
  ownedLines(): number[] {
    return [...this.owners.keys()].sort((a, b) => a - b)
  }

  // The innermost call whose span holds the code point at `line:col` (the
  // smallest span; a deeper call wins a tie), or null. Spans are half open.
  innermostCallAt(line: number, col: number): number | null {
    let best: number | null = null
    let bestSize = 0
    for (const c of this.view.calls) {
      const at: Pos = [line, col]
      if (before(at, c.from) || !before(at, c.to)) continue
      const size = (c.to[0] - c.from[0]) * 100000 + (c.to[1] - c.from[1])
      if (best === null || size < bestSize || (size === bestSize && c.id > best)) {
        best = c.id
        bestSize = size
      }
    }
    return best
  }
}

// ---- the keyboard ----

export type Move = 'ArrowDown' | 'ArrowUp' | 'Home' | 'End'

// Where an arrow key goes from the focused owned line, among the owned lines;
// null when the key is not a move. Ends do not wrap (static explorer.js).
export function moveAmong(owned: number[], at: number, key: string): number | null {
  if (!owned.length) return null
  const i = owned.indexOf(at)
  if (key === 'ArrowDown') return owned[Math.min(owned.length - 1, i + 1)]
  if (key === 'ArrowUp') return owned[Math.max(0, i - 1)]
  if (key === 'Home') return owned[0]
  if (key === 'End') return owned[owned.length - 1]
  return null
}

// The tab an arrow key activates (automatic activation, wrapping).
export function moveTab(n: number, at: number, key: string): number | null {
  if (key === 'ArrowRight') return (at + 1) % n
  if (key === 'ArrowLeft') return (at + n - 1) % n
  if (key === 'Home') return 0
  if (key === 'End') return n - 1
  return null
}

// ---- the words ----

// `3, 5–7, 9`: the lines as runs.
export function runs(ns: number[]): string {
  const out: [number, number][] = []
  for (const n of ns) {
    const last = out[out.length - 1]
    if (last && n === last[1] + 1) last[1] = n
    else out.push([n, n])
  }
  return out.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`)).join(', ')
}

export function place(c: XCall): string {
  return `${c.from[0]}:${c.from[1]}–${c.to[0]}:${c.to[1]}`
}

// What the live region says after a pick: the call, where it is, and where it
// landed in the open listing (explorer.js `say`, and its words).
export function statusText(c: XCall, label: string, hit: number[]): string {
  const where = hit.length
    ? `${label} ${hit.length > 1 ? 'lines' : 'line'} ${runs(hit)}`
    : `${label}: no lines of its own`
  return `${c.name} · ${place(c)} → ${where}`
}
