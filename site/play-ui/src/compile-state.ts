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

export type Target = 'c' | 'jvm'

export const TARGETS: { target: Target; label: string }[] = [
  { target: 'c', label: 'C' },
  { target: 'jvm', label: 'JVM' },
]

// `?view=` as a target; anything else, a missing key and the name of a tab
// this build does not have (`tile`, `output`) included, is "closed".
export function targetOfSearch(search: string): Target | null {
  const v = new URLSearchParams(search).get('view')
  return v === 'c' || v === 'jvm' ? v : null
}

// `href` with `view` set, or removed for null; the hash and every other
// parameter stay as they were.
export function withView(href: string, target: Target | null): string {
  const u = new URL(href)
  if (target) u.searchParams.set('view', target)
  else u.searchParams.delete('view')
  return u.toString()
}

export type Outcome =
  | { kind: 'ok'; view: XView; cached: boolean; ms: number }
  | { kind: 'diagnostics'; text: string }
  | { kind: 'busy' }
  | { kind: 'too-long' }
  | { kind: 'too-large' }
  | { kind: 'unavailable' }
  | { kind: 'unreadable' }
  | { kind: 'failed'; status: number; detail: string }

function detailOf(body: unknown): string {
  if (typeof body === 'object' && body !== null) {
    const o = (body as Record<string, unknown>).output
    if (typeof o === 'string') return o
  }
  return ''
}

// One answer to a request for `target`: the HTTP status and the parsed body
// (null when the body was not JSON). The statuses are the service's own
// (playground/src/main.dawn): 429 is the gate, 413 the body limit, 422 a
// listing too large to show, 503 a server without `javap`.
export function classify(status: number, body: unknown, target: Target): Outcome {
  if (status === 429) return { kind: 'busy' }
  if (status === 413) return { kind: 'too-long' }
  if (status === 422) return { kind: 'too-large' }
  if (status === 503) return { kind: 'unavailable' }
  const o = typeof body === 'object' && body !== null ? (body as Record<string, unknown>) : null
  if (status === 200 && o && o.ok === false && o.phase === 'compile') {
    return { kind: 'diagnostics', text: detailOf(o) }
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
      return 'The compile view is not available on this server (javap is missing).'
    case 'unreadable':
      return 'The service sent an answer this page cannot read.'
    case 'failed':
      return `The compile service failed (HTTP ${o.status}).`
    default:
      return ''
  }
}

export const NETWORK_MESSAGE = 'Could not reach the compile service.'

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
