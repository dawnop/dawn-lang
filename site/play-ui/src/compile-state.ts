// What the page does with each way /compile can answer, and where the open
// tab lives in the URL. Pure, so every branch is tested without a service.
//
// The tab goes in the query string, `?view=c`, and not in the hash. The hash
// is the program (base64, written by Run and Share), and base64's alphabet has
// no `?` or `&`, so the two never meet; a prefix inside the hash would make
// every link already shared ambiguous (docs/playground-compile-design.md 5.3).
// A link with no `view` opens as it always did, so there is nothing to
// migrate. What is picked is not in the URL, for the reason the static page
// gives: it is a reading position, not a thing to share.
import { readView, type XView } from './explorer-core'

export type Target = 'c' | 'jvm' | 'tile'

export const TARGETS: { target: Target; label: string }[] = [
  { target: 'c', label: 'C' },
  { target: 'jvm', label: 'JVM' },
  { target: 'tile', label: 'Tile IR' },
]

// Whether a program is one the Tile IR tab is for. The server asks the same
// question of the same text again (playground/src/play/contract.dawn,
// wants_tileir), because this page is not trusted; this one only decides
// whether the tab is offered.
export function wantsTileir(code: string): boolean {
  return code.includes('use tileir/')
}

// What the tab says when it is open on a program that does not import tileir.
export const TILE_NEEDS = 'The Tile IR view needs a program that imports tileir. Add a line such as `use tileir/dev.{Dev}`.'

// `?view=` as a target; anything else, a missing key and the name of a tab
// this build does not have (`output`) included, is "closed".
export function targetOfSearch(search: string): Target | null {
  const v = new URLSearchParams(search).get('view')
  return v === 'c' || v === 'jvm' || v === 'tile' ? v : null
}

// `href` with `view` set, or removed for null; the hash and every other
// parameter stay as they were.
export function withView(href: string, target: Target | null): string {
  const u = new URL(href)
  if (target) u.searchParams.set('view', target)
  else u.searchParams.delete('view')
  return u.toString()
}

// The Tile IR tab's answer when the calls of the kernel could not be paired
// with the source: the Tile IR text, a line each, and nothing to point at.
// `unmapped` is the service's reason (absent when it did not try, as when the
// program printed something other than a kernel). When they could be paired
// the answer is an ordinary listing, `kind: 'ok'`, like C and JVM.
export interface TileText {
  text: string[]
  total: number
  truncated: boolean
  unmapped?: string
}

export type Outcome =
  | { kind: 'ok'; view: XView; cached: boolean; ms: number }
  | { kind: 'tile'; tile: TileText; cached: boolean; ms: number }
  | { kind: 'diagnostics'; text: string }
  // the Tile IR program compiled and then failed or ran out of time
  | { kind: 'program'; title: string; text: string }
  | { kind: 'busy' }
  | { kind: 'too-long' }
  | { kind: 'too-large' }
  | { kind: 'unavailable'; tile: boolean }
  | { kind: 'unreadable' }
  | { kind: 'failed'; status: number; detail: string }

function detailOf(body: unknown): string {
  if (typeof body === 'object' && body !== null) {
    const o = (body as Record<string, unknown>).output
    if (typeof o === 'string') return o
  }
  return ''
}

function readTile(o: Record<string, unknown>): TileText | null {
  const p = o.pane
  if (typeof p !== 'object' || p === null) return null
  const pane = p as Record<string, unknown>
  const text = pane.text
  if (pane.kind !== 'tile' || !Array.isArray(text) || !text.every((l) => typeof l === 'string')) return null
  if (pane.shown !== text.length || typeof pane.total !== 'number' || typeof pane.truncated !== 'boolean') return null
  const why = o.unmapped
  return {
    text: text as string[],
    total: pane.total,
    truncated: pane.truncated,
    ...(typeof why === 'string' && why !== '' ? { unmapped: why } : {}),
  }
}

// One answer to a request for `target`: the HTTP status and the parsed body
// (null when the body was not JSON). The statuses are the service's own
// (playground/src/main.dawn): 429 is the gate, 413 the body limit, 422 a
// listing too large to show, 503 a server without `javap`.
export function classify(status: number, body: unknown, target: Target): Outcome {
  if (status === 429) return { kind: 'busy' }
  if (status === 413) return { kind: 'too-long' }
  if (status === 422) return { kind: 'too-large' }
  if (status === 503) return { kind: 'unavailable', tile: target === 'tile' }
  const o = typeof body === 'object' && body !== null ? (body as Record<string, unknown>) : null
  if (status === 200 && o && o.ok === false && o.phase === 'compile') {
    return { kind: 'diagnostics', text: detailOf(o) }
  }
  if (status === 200 && o && o.ok === false && (o.phase === 'run' || o.phase === 'timeout')) {
    return { kind: 'program', title: o.phase === 'run' ? 'Run error' : 'Timed out', text: detailOf(o) }
  }
  if (status === 200 && o && o.ok === true && o.phase === 'compile-view' && target === 'tile' && Array.isArray(o.calls)) {
    // the kernel's calls are paired with the source: a listing like the others
    const view = readView(o)
    if (!view || o.target !== 'tile' || view.pane.kind !== 'tile') return { kind: 'unreadable' }
    return { kind: 'ok', view, cached: o.cached === true, ms: typeof o.ms === 'number' ? o.ms : 0 }
  }
  if (status === 200 && o && o.ok === true && o.phase === 'compile-view' && target === 'tile') {
    const tile = o.target === 'tile' ? readTile(o) : null
    if (!tile) return { kind: 'unreadable' }
    return { kind: 'tile', tile, cached: o.cached === true, ms: typeof o.ms === 'number' ? o.ms : 0 }
  }
  if (status === 200 && o && o.ok === true && o.phase === 'compile-view') {
    const pane = o.pane as Record<string, unknown> | undefined
    const view = readView(o)
    // an answer for the other tab is not this tab's listing
    if (!view || o.target !== target || pane?.kind !== target) return { kind: 'unreadable' }
    return { kind: 'ok', view, cached: o.cached === true, ms: typeof o.ms === 'number' ? o.ms : 0 }
  }
  return { kind: 'failed', status, detail: detailOf(o) }
}

// The one sentence each failure gets. A diagnostics outcome and a success
// have their own surfaces; these are for the notice strip.
export function messageOf(o: Outcome): string {
  switch (o.kind) {
    case 'busy':
      return 'The service is busy. Press Compile to try again in a moment.'
    case 'too-long':
      return 'The source is too long to compile here (64 KiB at most).'
    case 'too-large':
      return 'The generated code is too large to show.'
    case 'unavailable':
      return o.tile
        ? 'The Tile IR view is not available on this server.'
        : 'The compile view is not available on this server (javap is missing).'
    case 'unreadable':
      return 'The service sent an answer this page cannot read.'
    case 'failed':
      // the service's own one-sentence refusal (a 400) is for the reader
      if (o.status === 400 && o.detail) return o.detail
      return `The compile service failed (HTTP ${o.status}).`
    default:
      return ''
  }
}

export const NETWORK_MESSAGE = 'Could not reach the compile service.'

// The Tile IR pane's one note, when the program printed more than is shown.
export function tileNotes(t: TileText): string[] {
  const notes: string[] = []
  if (t.unmapped) notes.push(`Calls are not matched to the Tile IR: ${t.unmapped}.`)
  if (t.truncated) notes.push(`The Tile IR text is cut: showing ${t.text.length} of ${t.total} lines.`)
  return notes
}

// Calls that have no listing line, or a listing cut short, in one line each;
// non-blocking, shown under the tabs and never in place of the listing.
export function notesOf(view: XView, label: string): string[] {
  const notes: string[] = []
  if (view.gaps.count > 0) {
    const n = view.gaps.count
    notes.push(`${n} call${n > 1 ? 's' : ''} could not be matched to the ${label} listing and ${n > 1 ? 'are' : 'is'} not highlighted.`)
  }
  if (view.pane.truncated) {
    notes.push(`The ${label} listing is cut: showing ${view.pane.shown} of ${view.pane.total} lines.`)
  }
  if (view.callsTruncated) {
    notes.push(`Only the first ${view.calls.length} of ${view.callsTotal} calls can be picked.`)
  }
  return notes
}

// Automatic compiling is on until the service says it is busy (429 from
// /compile or from /run: they share two permits), and comes back on the next
// compile the service accepts that the reader asked for (ruling 3, design 8).
export class AutoPolicy {
  private paused = false
  get auto(): boolean {
    return !this.paused
  }
  busy() {
    this.paused = true
  }
  // A compile the reader asked for came back with anything but 429.
  accepted(manual: boolean) {
    if (manual) this.paused = false
  }
}
