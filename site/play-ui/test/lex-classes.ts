// Print how the Playground editor reads each file named on the command line,
// for scripts/lex-properties/run.py to hold against the compiler's lexer.
//
// Why it exists. The editor has two hand-written copies of the lexer's string,
// comment and interpolation rules: the stream tokenizer that colours the pane
// and matches brackets, and `lexContext`, which re-scans the buffer to decide
// how completion behaves at the cursor. Issue #83 was the first one losing a
// string's state after an interpolation; the selftest pins the shapes that were
// thought of, and this lets every tracked .dawn file be the input instead.
//
// Output, one line per file: the path, a tab, the highlighter's classes as
// runs (`<class><count>` with c comment, s string, i interpolation delimiter,
// k keyword, o anything else, - not judged), a tab, then `lexContext` at sampled cursor
// positions as `<pos>:<context>` separated by commas. Counts and positions are
// code points, which is what the compiler's dump counts, not UTF-16 units.
//
// Sampling. `lexContext` re-scans from the start of the buffer on every call,
// so asking it at every position is quadratic; it is asked at SAMPLES
// positions per file, drawn from a generator seeded by the path, so a finding
// is reproduced from the file alone.
import { readFileSync } from 'node:fs'
import { EditorState } from '@codemirror/state'
import { ensureSyntaxTree } from '@codemirror/language'
import { highlightTree } from '@lezer/highlight'
import { dawn, dawnHighlight, lexContext } from '../src/dawn-lang'

const SAMPLES = 48

// CodeMirror's StreamLanguage leaves a line unstyled past this column
// (`C.MaxLineLength` in @codemirror/language), and gives no line break a
// class at all; both are the editor's design, not its reading of Dawn.
const MAX_LINE = 10000

const CLASS: Record<string, string> = {
  'tok-comment': 'c',
  'tok-string': 's',
  'tok-interp': 'i',
  'tok-keyword': 'k',
}

// FNV-1a of the path, then mulberry32: small, and the same on every node.
function seeded(path: string): () => number {
  let h = 0x811c9dc5
  for (let k = 0; k < path.length; k++) h = Math.imul(h ^ path.charCodeAt(k), 0x01000193)
  let a = h >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function classify(path: string, doc: string): string {
  const units: string[] = new Array(doc.length).fill('o')
  const state = EditorState.create({ doc, extensions: [dawn()] })
  const tree = ensureSyntaxTree(state, doc.length, 600000)
  if (!tree) throw new Error(`${path}: the syntax tree did not finish`)
  highlightTree(tree, dawnHighlight, (from, to, cls) => {
    const c = CLASS[cls] ?? 'o'
    for (let k = from; k < to; k++) units[k] = c
  })
  let col = 0
  for (let k = 0; k < doc.length; k++) {
    if (doc[k] === '\n') {
      units[k] = '-'
      col = 0
    } else {
      if (col >= MAX_LINE) units[k] = '-'
      col++
    }
  }
  // one class per code point: a surrogate pair takes its first unit's class
  let runs = ''
  let cur = ''
  let n = 0
  const cpAt: number[] = [] // UTF-16 index of each code point
  for (let k = 0; k < doc.length; k++) {
    const code = doc.charCodeAt(k)
    if (code >= 0xdc00 && code <= 0xdfff && k > 0) {
      const prev = doc.charCodeAt(k - 1)
      if (prev >= 0xd800 && prev <= 0xdbff) continue
    }
    cpAt.push(k)
    if (units[k] === cur) n++
    else {
      if (n > 0) runs += cur + n
      cur = units[k]
      n = 1
    }
  }
  if (n > 0) runs += cur + n
  cpAt.push(doc.length)

  const rand = seeded(path)
  const picks: number[] = []
  for (let k = 0; k < SAMPLES && cpAt.length > 1; k++) {
    picks.push(1 + Math.floor(rand() * (cpAt.length - 1)))
  }
  picks.sort((x, y) => x - y)
  const ctx = picks.map(cp => `${cp}:${lexContext(doc, cpAt[cp])}`).join(',')
  return `${path}\t${runs}\t${ctx}`
}

for (const path of process.argv.slice(2)) {
  console.log(classify(path, readFileSync(path, 'utf8')))
}
