// Live diagnostics: after an idle pause, POST the buffer to the playground's
// compile-only endpoint (/api/check) and turn the compiler's own report into
// editor squiggles. Transient failures — busy server (429), rate limiting,
// network — keep the previous diagnostics instead of flashing them away.
import { linter, forEachDiagnostic, type Diagnostic } from '@codemirror/lint'
import type { Text } from '@codemirror/state'
import {
  Decoration,
  EditorView,
  ViewPlugin,
  WidgetType,
  type DecorationSet,
  type ViewUpdate,
} from '@codemirror/view'

// Parse the compiler's report format:
//   error: <message>
//     --> prog.dawn:LINE:COL
//      |
//    L | <source line>
//      |    ^^^^
//     = hint: <hint>
// The caret run gives the span length; hints are folded into the message.
export function parseDawnDiagnostics(report: string, doc: Text): Diagnostic[] {
  const out: Diagnostic[] = []
  const lines = report.split('\n')
  let i = 0
  while (i < lines.length) {
    const head = /^(error|warning): (.*)$/.exec(lines[i])
    if (!head) {
      i++
      continue
    }
    let message = head[2]
    let line = 0
    let col = 1
    let len = 1
    let j = i + 1
    for (; j < lines.length && !/^(?:error|warning): /.test(lines[j]); j++) {
      const loc = /^\s*-->\s*prog\.dawn:(\d+):(\d+)/.exec(lines[j])
      if (loc) {
        line = +loc[1]
        col = +loc[2]
        continue
      }
      const caret = /^\s*\|\s*(\^+)\s*$/.exec(lines[j])
      if (caret) {
        len = caret[1].length
        continue
      }
      const hint = /^\s*=\s*(hint:.*)$/.exec(lines[j])
      if (hint) message += `\n${hint[1]}`
    }
    if (line >= 1 && line <= doc.lines) {
      const l = doc.line(line)
      const from = Math.min(l.from + col - 1, l.to)
      const to = Math.min(from + len, l.to)
      out.push({ from, to: Math.max(to, from), severity: head[1] as 'error' | 'warning', message })
    } else {
      // no usable location (e.g. a whole-program error) — pin it to the start
      out.push({ from: 0, to: 0, severity: head[1] as 'error' | 'warning', message })
    }
    i = j
  }
  return out
}

// Error-lens style inline messages: each diagnostic's first line, rendered
// after the code on its line (VS Code's Error Lens look). The full message —
// hints included — stays in the hover tooltip.
class LensWidget extends WidgetType {
  constructor(
    readonly message: string,
    readonly severity: string,
  ) {
    super()
  }
  eq(other: LensWidget) {
    return other.message === this.message && other.severity === this.severity
  }
  toDOM() {
    const span = document.createElement('span')
    span.className = `dp-lens dp-lens-${this.severity}`
    span.textContent = this.message
    return span
  }
}

function lensDecorations(view: EditorView): DecorationSet {
  // one lens per line: collect the first message of each diagnostic line
  const byLine = new Map<number, { message: string; severity: string }>()
  forEachDiagnostic(view.state, (d, from) => {
    const line = view.state.doc.lineAt(from)
    if (!byLine.has(line.number)) {
      byLine.set(line.number, { message: d.message.split('\n')[0], severity: d.severity })
    }
  })
  const widgets = [...byLine.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([n, { message, severity }]) =>
      Decoration.widget({ widget: new LensWidget(message, severity), side: 1 }).range(
        view.state.doc.line(n).to,
      ),
    )
  return Decoration.set(widgets)
}

export const errorLens = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet
    constructor(view: EditorView) {
      this.decorations = lensDecorations(view)
    }
    update(u: ViewUpdate) {
      // diagnostics arrive via state effects and shift with edits; recomputing
      // on every update is cheap (a handful of diagnostics at most)
      this.decorations = lensDecorations(u.view)
    }
  },
  { decorations: (v) => v.decorations },
)

export function dawnLint(endpoint: string) {
  let last: Diagnostic[] = []
  return linter(
    async (view) => {
      const code = view.state.doc.toString()
      if (!code.trim()) return (last = [])
      try {
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code }),
        })
        if (!res.ok) return last // 429/413/5xx: stale squiggles beat no squiggles
        const r = await res.json()
        if (r.phase === 'compile') last = parseDawnDiagnostics(r.output ?? '', view.state.doc)
        else if (r.ok) last = []
        return last
      } catch {
        return last
      }
    },
    { delay: 1000 },
  )
}
