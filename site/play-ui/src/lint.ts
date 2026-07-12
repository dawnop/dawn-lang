// Live diagnostics: after an idle pause, POST the buffer to the playground's
// compile-only endpoint (/api/check) and turn the compiler's own report into
// editor squiggles. Transient failures — busy server (429), rate limiting,
// network — keep the previous diagnostics instead of flashing them away.
import { linter, type Diagnostic } from '@codemirror/lint'
import type { Text } from '@codemirror/state'

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
