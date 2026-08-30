// Diagnostic adapters for both live LSP ranges and the compile-only /api/check
// fallback. Transient HTTP failures keep the previous squiggles rather than
// flashing them away.
import {
  linter,
  forEachDiagnostic,
  setDiagnostics,
  type Diagnostic,
} from '@codemirror/lint'
import type { Text } from '@codemirror/state'
import {
  Decoration,
  EditorView,
  ViewPlugin,
  WidgetType,
  type DecorationSet,
  type ViewUpdate,
} from '@codemirror/view'
import { lspDiagnostics, type DawnLspClient } from './lsp'

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

// LSP owns diagnostics while its session is healthy. When the session is not
// available, this switches the same CodeMirror diagnostic state back to the
// existing /api/check endpoint. Only the source that currently owns that state
// may publish, so a late HTTP response cannot overwrite fresh LSP diagnostics.
export function dawnDiagnostics(endpoint: string, lsp: DawnLspClient) {
  return ViewPlugin.fromClass(class {
    private timer: ReturnType<typeof setTimeout> | null = null
    private abort: AbortController | null = null
    private serial = 0
    private destroyed = false
    private readonly removeStatusListener: () => void
    private readonly removeDiagnosticsListener: () => void

    constructor(readonly view: EditorView) {
      this.removeDiagnosticsListener = lsp.onDiagnostics((event) => {
        if (event.text !== this.view.state.doc.toString()) return
        this.cancelHttp()
        this.publish(lspDiagnostics(event.diagnostics, event.text), event.text)
      })
      this.removeStatusListener = lsp.onStatus((status) => {
        if (status === 'fallback') this.scheduleHttp(0)
        else this.cancelHttp()
      })
    }

    update(update: ViewUpdate) {
      if (!update.docChanged) return
      const text = update.state.doc.toString()
      if (!text.trim()) {
        this.cancelHttp()
        this.publish([], text)
      } else if (lsp.status === 'fallback') {
        this.scheduleHttp(1000)
      } else {
        this.cancelHttp()
      }
    }

    destroy() {
      this.destroyed = true
      this.cancelHttp()
      this.removeStatusListener()
      this.removeDiagnosticsListener()
    }

    private scheduleHttp(delay: number) {
      this.cancelHttp()
      if (!this.view.state.doc.toString().trim()) {
        this.publish([], this.view.state.doc.toString())
        return
      }
      this.timer = setTimeout(() => {
        this.timer = null
        void this.checkWithHttp()
      }, delay)
    }

    private cancelHttp() {
      this.serial++
      if (this.timer != null) clearTimeout(this.timer)
      this.timer = null
      this.abort?.abort()
      this.abort = null
    }

    private publish(diagnostics: Diagnostic[], text: string, serial?: number) {
      queueMicrotask(() => {
        if (this.destroyed || this.view.state.doc.toString() !== text) return
        if (serial != null && serial !== this.serial) return
        this.view.dispatch(setDiagnostics(this.view.state, diagnostics))
      })
    }

    private async checkWithHttp() {
      if (lsp.status !== 'fallback') return
      const text = this.view.state.doc.toString()
      if (!text.trim()) {
        this.publish([], text)
        return
      }
      const serial = ++this.serial
      const abort = new AbortController()
      this.abort = abort
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code: text }),
          signal: abort.signal,
        })
        if (!response.ok || serial !== this.serial || lsp.status !== 'fallback') return
        const result = await response.json() as { ok?: boolean; phase?: string; output?: string }
        if (serial !== this.serial || lsp.status !== 'fallback') return
        const diagnostics = result.phase === 'compile'
          ? parseDawnDiagnostics(result.output ?? '', this.view.state.doc)
          : result.ok ? [] : null
        if (diagnostics != null) this.publish(diagnostics, text, serial)
      } catch {
        // Busy, network and abort failures deliberately preserve the last set.
      } finally {
        if (this.abort === abort) this.abort = null
      }
    }
  })
}
