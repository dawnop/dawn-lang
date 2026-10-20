// The draggable borders between the Playground's panes: the sample list and
// the editor column, the editor and the generated code, the work area and the
// Output console.
//
// Hand-written rather than a split-pane package: none of the bundle's
// dependencies has one (CodeMirror only lays out its own editor), and what is
// needed is one pointer handler and one clamp, smaller than any package's
// options object.
//
// Sizes are remembered as ratios of the container, not pixels, so a split
// made on a laptop still reads as the same split on a wide monitor; and they
// are remembered per layout ("wide" and "narrow", the 44rem breakpoint of
// playground.css), because on a phone the generated code is under the editor
// and a width ratio from the desktop means nothing there. Nothing is stored
// until a border is moved: until then the stylesheet's sizes are the layout,
// and a double click on a border goes back to them by forgetting the ratio.
//
// The pane's size is applied in pixels from the stored ratio and clamped each
// time the container changes size (a ResizeObserver), so a pane can never be
// squeezed out of sight by a window that shrank after the drag.
//
// What a border does is decided by pure functions at the top (tested in
// test/panes-selftest.ts without a browser); the class below only listens.

export type Axis = 'x' | 'y'
export type Mode = 'wide' | 'narrow'

export const STORE_KEY = 'dawn-playground-panes'

// One arrow press moves a border this far; with Shift, four times as far.
export const KEY_STEP = 16

// A pane's size after a drag of `delta` pixels from where it was `start`. A
// pane after its border (the generated code, the console) grows as the border
// moves towards the start of the axis.
export function dragSize(start: number, delta: number, after: boolean): number {
  return after ? start - delta : start + delta
}

// The size a pane may take in a container of `total`: no smaller than its own
// minimum, and leaving the rest of the container at least `restMin`. When the
// container is too small for both, the pane's own minimum wins: the rest has
// a scrollbar or shrinks, the dragged pane stays visible.
export function clampSize(size: number, min: number, total: number, restMin: number): number {
  return Math.max(min, Math.min(size, total - restMin))
}

// What a key on a focused border asks for: a change of the pane's size in
// pixels, or the pane's smallest or largest size, or nothing. The arrows that
// matter are the ones along the border's axis; for a pane after its border
// they point the other way, so Left always moves a vertical border left.
export function keyAction(
  key: string,
  axis: Axis,
  after: boolean,
  shift: boolean,
): { delta: number } | 'min' | 'max' | null {
  const step = shift ? KEY_STEP * 4 : KEY_STEP
  let move = 0
  if (axis === 'x' && key === 'ArrowLeft') move = -step
  else if (axis === 'x' && key === 'ArrowRight') move = step
  else if (axis === 'y' && key === 'ArrowUp') move = -step
  else if (axis === 'y' && key === 'ArrowDown') move = step
  else if (key === 'Home') return 'min'
  else if (key === 'End') return 'max'
  else return null
  return { delta: after ? -move : move }
}

// The share of the container a pane takes, as aria-valuenow says it: a whole
// percentage.
export function percent(size: number, total: number): number {
  return total > 0 ? Math.round((size / total) * 100) : 0
}

type Ratios = Partial<Record<Mode, Record<string, number>>>

// Storage is a convenience: missing, throwing (a private window, blocked site
// data) or holding something else all read as "nothing remembered".
export type Store = Pick<Storage, 'getItem' | 'setItem'> | null

function readAll(store: () => Store): Ratios {
  try {
    const raw = store()?.getItem(STORE_KEY)
    if (!raw) return {}
    const v = JSON.parse(raw)
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as Ratios) : {}
  } catch {
    return {}
  }
}

export function loadRatio(store: () => Store, mode: Mode, name: string): number | null {
  const r = readAll(store)[mode]?.[name]
  return typeof r === 'number' && r > 0 && r < 1 ? r : null
}

// Remember `ratio` for this pane in this layout, or forget it (null). Returns
// whether storage took it, which the page does not need and the tests do.
export function saveRatio(store: () => Store, mode: Mode, name: string, ratio: number | null): boolean {
  const all = readAll(store)
  const mine = { ...(all[mode] ?? {}) }
  if (ratio === null) delete mine[name]
  else mine[name] = Math.round(ratio * 10000) / 10000
  all[mode] = mine
  try {
    const s = store()
    if (!s) return false
    s.setItem(STORE_KEY, JSON.stringify(all))
    return true
  } catch {
    return false
  }
}

export function defaultStore(): Store {
  return typeof localStorage === 'undefined' ? null : localStorage
}

export interface SplitSpec {
  // the key it is remembered under, and what a screen reader calls the border
  name: string
  label: string
  // the pane the border resizes, and the box whose size along the axis is
  // the whole the ratio is of
  pane: HTMLElement
  container: HTMLElement
  // the pane comes after the border (to its right, or under it)
  after: boolean
  // where the border lies in the current layout; null: no border here
  axis(mode: Mode): Axis | null
  // the pane's smallest size, and what it must leave to the rest, in pixels
  min(axis: Axis): number
  restMin(axis: Axis): number
  // write a size onto the pane (null: hand the size back to the stylesheet)
  apply(pane: HTMLElement, axis: Axis, px: number | null): void
}

export interface SplitEnv {
  mode(): Mode
  store(): Store
  // a pane changed size (the editor relayouts on this)
  resized(): void
  // measured size along an axis; a test passes its own
  measure?(el: HTMLElement, axis: Axis): number
}

function measureRect(el: HTMLElement, axis: Axis): number {
  const r = el.getBoundingClientRect()
  return axis === 'x' ? r.width : r.height
}

// One border. It owns its element, which the page puts between the panes.
export class Splitter {
  readonly el: HTMLDivElement
  private ratio: number | null = null
  private axisNow: Axis | null = null
  private drag: { id: number; from: number; start: number } | null = null
  private readonly measure: (el: HTMLElement, axis: Axis) => number

  constructor(
    private readonly spec: SplitSpec,
    private readonly env: SplitEnv,
  ) {
    this.measure = env.measure ?? measureRect
    const el = (this.el = document.createElement('div'))
    el.className = 'dp-split'
    el.setAttribute('tabindex', '0')
    el.setAttribute('role', 'separator')
    el.setAttribute('aria-label', spec.label)
    if (spec.pane.id) el.setAttribute('aria-controls', spec.pane.id)
    el.title = 'Drag to resize; double-click to reset'
    el.addEventListener('pointerdown', (e) => this.down(e))
    el.addEventListener('pointermove', (e) => this.move(e))
    el.addEventListener('pointerup', (e) => this.up(e))
    el.addEventListener('pointercancel', (e) => this.up(e))
    el.addEventListener('lostpointercapture', (e) => this.up(e))
    el.addEventListener('dblclick', () => this.reset())
    el.addEventListener('keydown', (e) => this.key(e))
    this.layout()
  }

  // Re-read the layout (the breakpoint may have been crossed) and re-apply the
  // remembered ratio, clamped to the container as it now is.
  layout() {
    const axis = this.spec.axis(this.env.mode())
    this.axisNow = axis
    this.el.hidden = axis === null
    if (axis === null) {
      // nothing of a size set in another layout may stay behind: the sample
      // list's width would become its height in the narrow one
      this.ratio = null
      this.spec.apply(this.spec.pane, 'x', null)
      this.spec.apply(this.spec.pane, 'y', null)
      return
    }
    this.el.setAttribute('aria-orientation', axis === 'x' ? 'vertical' : 'horizontal')
    this.el.dataset.axis = axis
    this.ratio = loadRatio(() => this.env.store(), this.env.mode(), this.spec.name)
    this.spec.apply(this.spec.pane, otherAxis(axis), null)
    if (this.ratio === null) this.spec.apply(this.spec.pane, axis, null)
    else this.set(this.ratio * this.total(axis), false)
    this.aria()
  }

  private total(axis: Axis): number {
    return this.measure(this.spec.container, axis)
  }

  // the pane's current size, clamped; written to the pane, and remembered
  // when `keep`
  private set(px: number, keep: boolean) {
    const axis = this.axisNow
    if (axis === null) return
    const total = this.total(axis)
    const size = clampSize(px, this.spec.min(axis), total, this.spec.restMin(axis))
    this.spec.apply(this.spec.pane, axis, size)
    if (keep && total > 0) {
      this.ratio = size / total
      saveRatio(() => this.env.store(), this.env.mode(), this.spec.name, this.ratio)
    }
    this.aria(size)
    this.env.resized()
  }

  private aria(size?: number) {
    const axis = this.axisNow
    if (axis === null) return
    const total = this.total(axis)
    const now = size ?? this.measure(this.spec.pane, axis)
    this.el.setAttribute('aria-valuemin', String(percent(this.spec.min(axis), total)))
    this.el.setAttribute('aria-valuemax', String(percent(Math.max(0, total - this.spec.restMin(axis)), total)))
    this.el.setAttribute('aria-valuenow', String(percent(now, total)))
  }

  // Back to the stylesheet's size, and nothing remembered.
  reset() {
    const axis = this.axisNow
    if (axis === null) return
    this.ratio = null
    saveRatio(() => this.env.store(), this.env.mode(), this.spec.name, null)
    this.spec.apply(this.spec.pane, axis, null)
    this.aria()
    this.env.resized()
  }

  private down(e: PointerEvent) {
    const axis = this.axisNow
    if (axis === null || (e.pointerType === 'mouse' && e.button !== 0)) return
    // no text selection, no scrolling the page under a finger
    e.preventDefault()
    // keyboard-ready, without the focus ring a click would not ask for
    this.el.focus?.({ focusVisible: false } as FocusOptions)
    try {
      this.el.setPointerCapture(e.pointerId)
    } catch {
      // a synthetic event has no pointer to capture; moves still reach us
    }
    this.drag = { id: e.pointerId, from: axis === 'x' ? e.clientX : e.clientY, start: this.measure(this.spec.pane, axis) }
    this.el.classList.add('dp-split-on')
    document.documentElement.classList.add('dp-resizing', `dp-resizing-${axis}`)
  }

  private move(e: PointerEvent) {
    const d = this.drag
    const axis = this.axisNow
    if (!d || axis === null || e.pointerId !== d.id) return
    e.preventDefault()
    const at = axis === 'x' ? e.clientX : e.clientY
    this.set(dragSize(d.start, at - d.from, this.spec.after), true)
  }

  private up(e: PointerEvent) {
    if (!this.drag || e.pointerId !== this.drag.id) return
    this.drag = null
    this.el.classList.remove('dp-split-on')
    document.documentElement.classList.remove('dp-resizing', 'dp-resizing-x', 'dp-resizing-y')
  }

  private key(e: KeyboardEvent) {
    const axis = this.axisNow
    if (axis === null) return
    const a = keyAction(e.key, axis, this.spec.after, e.shiftKey)
    if (a === null) return
    e.preventDefault()
    if (a === 'min') this.set(0, true)
    else if (a === 'max') this.set(Infinity, true)
    else this.set(this.measure(this.spec.pane, axis) + a.delta, true)
  }
}

function otherAxis(a: Axis): Axis {
  return a === 'x' ? 'y' : 'x'
}

// Size a pane through its flex basis, which every pane here is laid out by.
// The console is a column item sized by its content up to a cap, so it also
// drops the cap while a size is set.
export function applyBasis(pane: HTMLElement, axis: Axis, px: number | null) {
  pane.style.flexBasis = px === null ? '' : `${px}px`
  pane.style.flexGrow = px === null ? '' : '0'
  pane.style.flexShrink = px === null ? '' : '0'
  if (axis === 'x') pane.style.width = px === null ? '' : 'auto'
  else pane.style.maxHeight = px === null ? '' : 'none'
}
