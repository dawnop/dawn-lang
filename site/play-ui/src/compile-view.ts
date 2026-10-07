// The compile pane: the C or JVM listing of the program in the editor, beside
// it, and the two-way pointing between a call in the source and the lines it
// wrote. Closed until asked for; opening it compiles.
//
// Why a pane and a listing of its own and not the Output console. The console
// answers a Run, the pane answers "what does this become", and the second one
// is recomputed while the reader types. They share the editor's column but not
// a tab strip: the console is a result to read once, the pane is something to
// point at, and pointing needs the room beside the source, not under it
// (docs/playground-compile-design.md 5.1).
//
// What is decided here and what is not. Which lines a call owns, who a clicked
// line belongs to and where the keys go are explorer-core.ts's, tested without
// a DOM; compile-state.ts decides what each answer means. This file only
// draws those answers (the same classes as the static explorer, so the site's
// stylesheet paints them) and runs the request: the 1.5 s idle recompile that
// is cancelled by the next keystroke (ruling 3), one request per visible tab
// (the service keeps the other half of the build), and an answer that is kept,
// marked "out of date", when the next one fails.
import {
  Model,
  moveAmong,
  moveTab,
  statusText,
  type XCall,
} from './explorer-core'
import {
  AutoPolicy,
  NETWORK_MESSAGE,
  TARGETS,
  classify,
  messageOf,
  notesOf,
  type Outcome,
  type Target,
} from './compile-state'

// How long the editor must be quiet before an open pane recompiles.
export const IDLE_MS = 1500

// What the live region says when a listing is there and nothing is picked: the
// two ways in, since the source's calls are text in an editor and cannot be
// tab stops (call-marks.ts).
export const HINT = 'Click a call in the source, or press Alt-Enter on it, to see what it wrote.'

export interface PaneHost {
  endpoint: string
  code(): string
  // the open tab changed (null: closed), for the URL and the toolbar
  opened(target: Target | null): void
  // the calls of the listing now shown, for the source's underlines
  calls(calls: XCall[]): void
  // a call is picked (null: none), for the source's span
  picked(id: number | null): void
}

interface Answer {
  code: string
  model: Model
  meta: string
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string): HTMLElementTagNameMap[K] {
  const n = document.createElement(tag)
  if (cls) n.className = cls
  if (text) n.textContent = text
  return n
}

export class ComparePane {
  readonly root = el('section', 'dp-view xp')
  private readonly tabs: HTMLButtonElement[] = []
  private readonly meta = el('span', 'dp-viewmeta')
  private readonly compileBtn = el('button', 'dp-viewgo', 'Compile')
  private readonly closeBtn = el('button', 'dp-outclose', '×')
  private readonly notice = el('div', 'dp-viewnote')
  private readonly errBox = el('div', 'dp-viewerr')
  private readonly errText = el('pre', 'dp-viewerrtext')
  private readonly panel = el('div', 'xp-pane')
  private readonly code = el('pre', 'xp-code')
  private readonly codeIn = el('code')
  private readonly status = el('p', 'xp-status')

  private target: Target | null = null
  private answers: Partial<Record<Target, Answer>> = {}
  private picked: number | null = null
  private lineEls = new Map<number, HTMLElement>()
  private keyEls = new Map<number, HTMLElement[]>()
  private touched: HTMLElement[] = []
  private ctl: AbortController | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private stale = false
  private readonly policy = new AutoPolicy()
  private busyNote = ''

  constructor(private readonly host: PaneHost) {
    const root = this.root
    root.id = 'dp-view'
    root.hidden = true
    root.setAttribute('aria-label', 'Generated code')

    const head = el('div', 'dp-viewhead')
    const strip = el('div', 'xp-tabs')
    strip.setAttribute('role', 'tablist')
    strip.setAttribute('aria-label', 'Generated code')
    TARGETS.forEach((t, i) => {
      const b = el('button', 'xp-tab', t.label)
      b.type = 'button'
      b.id = `dp-view-tab-${t.target}`
      b.dataset.kind = t.target
      b.setAttribute('role', 'tab')
      b.setAttribute('aria-controls', 'dp-view-panel')
      b.setAttribute('aria-selected', 'false')
      b.tabIndex = -1
      b.addEventListener('click', () => this.open(t.target))
      b.addEventListener('keydown', (ev) => {
        const to = moveTab(TARGETS.length, i, ev.key)
        if (to === null) return
        ev.preventDefault()
        this.open(TARGETS[to].target)
        this.tabs[to].focus()
      })
      this.tabs.push(b)
      strip.appendChild(b)
    })
    this.compileBtn.type = 'button'
    this.compileBtn.title = 'Compile the program in the editor now'
    this.compileBtn.addEventListener('click', () => this.compile(true))
    this.closeBtn.type = 'button'
    this.closeBtn.title = 'Close the generated code'
    this.closeBtn.setAttribute('aria-label', 'Close the generated code')
    this.closeBtn.addEventListener('click', () => this.close())
    this.meta.setAttribute('role', 'status')
    head.append(strip, this.meta, this.compileBtn, this.closeBtn)

    this.notice.hidden = true
    this.errBox.hidden = true
    this.errBox.setAttribute('role', 'alert')
    this.errBox.append(el('div', 'dp-viewerrhead', 'Compile error'), this.errText)

    this.panel.id = 'dp-view-panel'
    this.panel.setAttribute('role', 'tabpanel')
    this.code.setAttribute('aria-label', 'Generated code')
    this.code.append(this.codeIn)
    this.panel.append(this.code)

    this.status.setAttribute('role', 'status')
    this.status.setAttribute('aria-live', 'polite')
    root.classList.add('xp-live')
    root.append(head, this.notice, this.errBox, this.panel, this.status)

    this.panel.addEventListener('click', (ev) => {
      const sel = window.getSelection && window.getSelection()
      if (sel && !sel.isCollapsed && this.panel.contains(sel.anchorNode)) return
      const l = (ev.target as HTMLElement).closest<HTMLElement>('.xl[data-o]')
      const m = this.model()
      if (!l || !m) return
      const id = m.innermostAt(Number(l.dataset.n))
      if (id !== null) this.pick(id)
    })
    root.addEventListener('keydown', (ev) => this.keydown(ev))
  }

  // ---- state the page asks about ----

  isOpen(): boolean {
    return this.target !== null
  }
  hasPick(): boolean {
    return this.picked !== null
  }
  // A line for the live region, when the pane is there to be heard.
  announce(message: string) {
    if (this.target !== null) this.say(message)
  }

  private model(): Model | null {
    const a = this.target && this.answers[this.target]
    return a ? a.model : null
  }
  private label(): string {
    return TARGETS.find((t) => t.target === this.target)?.label ?? ''
  }

  // ---- opening, closing, the tabs ----

  // Show `target` (the pane opens if it was closed) and compile unless the
  // listing for exactly this code is already in hand.
  open(target: Target) {
    this.target = target
    this.root.hidden = false
    this.tabs.forEach((b) => {
      const on = b.dataset.kind === target
      b.setAttribute('aria-selected', on ? 'true' : 'false')
      b.tabIndex = on ? 0 : -1
    })
    this.panel.setAttribute('aria-labelledby', `dp-view-tab-${target}`)
    this.host.opened(target)
    const a = this.answers[target]
    this.mark(!!a && a.code !== this.host.code())
    if (!a) {
      this.drawNothing()
    } else {
      this.draw(a)
      if (!this.stale) {
        // the calls of every tab are the same table, but the source's
        // underlines are only right for the code this listing is of
        this.host.calls(a.model.view.calls)
        this.reapply()
        this.say(this.pickText())
        return
      }
    }
    this.compile(false)
  }

  close() {
    if (this.target === null) return
    this.abort()
    this.target = null
    this.root.hidden = true
    this.clearMarks()
    this.picked = null
    this.host.calls([])
    this.host.picked(null)
    this.host.opened(null)
  }

  // ---- the request ----

  private abort() {
    if (this.timer !== null) clearTimeout(this.timer)
    this.timer = null
    if (this.ctl) this.ctl.abort()
    this.ctl = null
    this.root.classList.remove('dp-busy')
  }

  // The editor changed: whatever was asked is moot, what is shown is out of
  // date, and, while automatic compiling is on, a quiet 1.5 s asks again.
  edited() {
    if (this.target === null) return
    this.abort()
    this.stale = Object.keys(this.answers).length > 0
    this.root.classList.toggle('dp-stale', this.stale)
    if (this.policy.auto) {
      this.meta.textContent = this.stale ? 'Out of date' : ''
      this.timer = setTimeout(() => {
        this.timer = null
        this.compile(false)
      }, IDLE_MS)
    } else {
      this.meta.textContent = this.stale ? 'Out of date, press Compile' : ''
    }
  }

  // The run service said it is busy: the permits are shared, so stop asking
  // on our own until the reader asks.
  serviceBusy() {
    this.policy.busy()
    if (this.target !== null) {
      this.abort()
      this.busyNote = 'The service is busy, so the generated code no longer updates by itself. Press Compile.'
      this.showNotice([this.busyNote])
    }
  }

  async compile(manual: boolean) {
    const target = this.target
    if (target === null) return
    this.abort()
    const code = this.host.code()
    const ctl = new AbortController()
    this.ctl = ctl
    this.root.classList.add('dp-busy')
    this.meta.textContent = 'Compiling…'
    let outcome: Outcome | null = null
    try {
      const res = await fetch(this.host.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, target }),
        signal: ctl.signal,
      })
      let body: unknown = null
      try {
        body = await res.json()
      } catch {
        body = null
      }
      outcome = classify(res.status, body, target)
    } catch (e) {
      if (ctl.signal.aborted) return
      this.settle(ctl)
      this.fail(NETWORK_MESSAGE)
      return
    }
    if (ctl.signal.aborted || this.target !== target) return
    this.settle(ctl)
    if (outcome.kind === 'busy') {
      this.policy.busy()
      this.fail(messageOf(outcome))
      return
    }
    this.policy.accepted(manual)
    this.busyNote = ''
    if (outcome.kind === 'ok') {
      this.stale = false
      this.root.classList.remove('dp-stale')
      this.errBox.hidden = true
      const model = new Model(outcome.view)
      const a: Answer = { code, model, meta: this.metaOf(outcome) }
      this.answers[target] = a
      this.draw(a)
      this.host.calls(outcome.view.calls)
      this.reapply()
      this.say(this.picked !== null ? this.pickText() : `Compiled. ${HINT}`)
    } else if (outcome.kind === 'diagnostics') {
      this.errText.textContent = outcome.text || '(no message)'
      this.errBox.hidden = false
      this.showNotice([])
      this.mark(true)
      this.meta.textContent = 'Compile error'
      // the alert above says what happened; "Compiled." is no longer true
      this.say('')
    } else {
      this.fail(messageOf(outcome))
    }
  }

  private settle(ctl: AbortController) {
    if (this.ctl === ctl) this.ctl = null
    this.root.classList.remove('dp-busy')
  }

  private metaOf(o: Extract<Outcome, { kind: 'ok' }>): string {
    const v = o.view
    const parts = [`${v.pane.shown} of ${v.pane.total} lines`, `${v.calls.length} calls`]
    parts.push(o.cached ? `${o.ms} ms, cached` : `${o.ms} ms`)
    return parts.join(' · ')
  }

  // A failure that is not a compile error: say it in the notice strip, keep
  // the last listing and call it out of date.
  private fail(message: string) {
    this.errBox.hidden = true
    this.showNotice([message])
    this.mark(true)
    this.meta.textContent = this.answers[this.target as Target] ? 'Out of date' : ''
    this.say(message)
  }

  private mark(stale: boolean) {
    this.stale = stale && Object.keys(this.answers).length > 0
    this.root.classList.toggle('dp-stale', this.stale)
  }

  private say(message: string) {
    this.status.textContent = message
  }

  private showNotice(lines: string[]) {
    this.notice.replaceChildren(...lines.map((l) => el('p', undefined, l)))
    this.notice.hidden = lines.length === 0
  }

  // ---- drawing a listing ----

  private drawNothing() {
    this.codeIn.replaceChildren()
    this.lineEls = new Map()
    this.keyEls = new Map()
    this.touched = []
    this.meta.textContent = 'Compiling…'
    this.showNotice(this.busyNote ? [this.busyNote] : [])
  }

  private draw(a: Answer) {
    const m = a.model
    const pane = m.view.pane
    this.lineEls = new Map()
    this.keyEls = new Map()
    this.touched = []
    const owned = m.ownedLines()
    const frag = document.createDocumentFragment()
    pane.text.forEach((text, i) => {
      const n = i + 1
      const line = el('span', 'xl')
      line.dataset.n = String(n)
      const os = m.ownersOf(n)
      const made = m.madeBy(n)
      if (os.length) {
        line.dataset.o = os.join(' ')
        line.setAttribute('role', 'button')
        line.tabIndex = n === owned[0] ? 0 : -1
        line.setAttribute('aria-pressed', 'false')
      }
      if (made.length) line.dataset.i = made.join(' ')
      line.append(el('i', undefined, String(n)))
      if (pane.kind === 'c') this.cPieces(line, text, n, m)
      else this.jvmPieces(line, text)
      this.lineEls.set(n, line)
      frag.appendChild(line)
    })
    this.codeIn.replaceChildren(frag)
    this.code.scrollTop = 0
    this.showNotice(this.busyNote ? [this.busyNote] : notesOf(m.view, this.label()))
    this.meta.textContent = this.stale ? 'Out of date' : a.meta
  }

  // A C line cut where the picked-call columns begin and end, each piece
  // inside the calls whose columns hold it (gen/explorer.dawn c_html).
  private cPieces(line: HTMLElement, text: string, n: number, m: Model) {
    const marks: [number, number, number][] = []
    for (const o of m.view.pane.outs) for (const [l, a, z] of o.marks) if (l === n) marks.push([o.call, a, z])
    const chars = Array.from(text)
    if (!marks.length) {
      line.append(text)
      return
    }
    const cuts = [...new Set([0, chars.length, ...marks.flatMap(([, a, z]) => [a, z])])].sort((x, y) => x - y)
    for (let k = 0; k + 1 < cuts.length; k++) {
      const a = cuts[k]
      const b = cuts[k + 1]
      const ids = marks.filter(([, x, y]) => x <= a && b <= y).map(([c]) => c)
      const piece = chars.slice(a, b).join('')
      if (!ids.length) {
        line.append(piece)
        continue
      }
      const s = el('span', undefined, piece)
      s.dataset.k = ids.join(' ')
      ids.forEach((id) => this.keyEls.set(id, [...(this.keyEls.get(id) ?? []), s]))
      line.append(s)
    }
  }

  // A javap line with its `// ...` tail (the constant's meaning) faint.
  private jvmPieces(line: HTMLElement, text: string) {
    const at = text.indexOf('//')
    if (at < 0) {
      line.append(text)
      return
    }
    line.append(text.slice(0, at), el('span', 'ty', text.slice(at)))
  }

  // ---- picking ----

  private clearMarks() {
    for (const e of this.touched) {
      e.classList.remove('xp-hit', 'xp-in', 'xp-ipc', 'xp-on')
      if (e.getAttribute('aria-pressed') === 'true') e.setAttribute('aria-pressed', 'false')
    }
    this.touched = []
  }

  // Pick a call (again: let go), from the source or from a listing line.
  pick(id: number | null) {
    const again = this.picked === id
    this.clearMarks()
    this.picked = null
    this.host.picked(null)
    const m = this.model()
    const c = m && id !== null ? m.view.calls[id] : null
    if (again || !m || !c) {
      this.say(m ? HINT : '')
      return
    }
    this.picked = id
    this.host.picked(id)
    const first = this.applyMarks(m, id)
    this.say(statusText(c, this.label(), m.mark(id).hit))
    if (first) this.reveal(first)
  }

  // What the live region says of the call picked now, in the listing shown.
  private pickText(): string {
    const m = this.model()
    const c = m && this.picked !== null ? m.view.calls[this.picked] : null
    return m && c ? statusText(c, this.label(), m.mark(c.id).hit) : HINT
  }

  // Draw a pick again on a listing just drawn (a tab switch, a recompile).
  private reapply() {
    const m = this.model()
    if (this.picked === null || !m || !m.view.calls[this.picked]) {
      this.picked = null
      this.host.picked(null)
      return
    }
    this.host.picked(this.picked)
    const first = this.applyMarks(m, this.picked)
    if (first) this.reveal(first)
  }

  private applyMarks(m: Model, id: number): HTMLElement | null {
    const k = m.mark(id)
    const add = (n: number, cls: string, pressed?: boolean) => {
      const e = this.lineEls.get(n)
      if (!e) return
      e.classList.add(cls)
      if (pressed) e.setAttribute('aria-pressed', 'true')
      this.touched.push(e)
    }
    k.hit.forEach((n) => add(n, 'xp-hit', true))
    k.inner.forEach((n) => add(n, 'xp-in'))
    k.ipc.forEach((n) => add(n, 'xp-ipc'))
    for (const e of this.keyEls.get(id) ?? []) {
      e.classList.add('xp-on')
      this.touched.push(e)
    }
    return k.hit.length ? (this.lineEls.get(k.hit[0]) ?? null) : null
  }

  // A listing's own scroll, never the page's.
  private reveal(line: HTMLElement) {
    const box = this.code
    const top = line.offsetTop
    const h = line.offsetHeight
    if (top < box.scrollTop || top + h > box.scrollTop + box.clientHeight) {
      box.scrollTop = Math.max(0, top - box.clientHeight / 3)
    }
  }

  // ---- the keyboard, inside the pane ----

  private keydown(ev: KeyboardEvent) {
    if (ev.key === 'Escape') {
      if (this.picked !== null) {
        ev.preventDefault()
        this.pick(null)
      }
      return
    }
    const l = (ev.target as HTMLElement).closest<HTMLElement>('.xl[data-o]')
    const m = this.model()
    if (!l || !m) return
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault()
      const id = m.innermostAt(Number(l.dataset.n))
      if (id !== null) this.pick(id)
      return
    }
    const to = moveAmong(m.ownedLines(), Number(l.dataset.n), ev.key)
    if (to === null) return
    ev.preventDefault()
    const dest = this.lineEls.get(to)
    if (!dest) return
    this.codeIn.querySelectorAll<HTMLElement>('.xl[data-o]').forEach((e) => (e.tabIndex = e === dest ? 0 : -1))
    dest.focus()
    this.reveal(dest)
  }
}
