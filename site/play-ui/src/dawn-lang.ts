// A CodeMirror 6 language for Dawn: a hand-written stream tokenizer plus a
// completion source over the builtins. The token classes mirror the site's
// build-time highlighter (site/src/hl/dawn.dawn): keyword, type/ctor, the
// definition name after `fn`, strings with `$` interpolation, numbers, chars,
// and `#` comments.
import {
  StreamLanguage,
  LanguageSupport,
  HighlightStyle,
  syntaxHighlighting,
} from '@codemirror/language'
import { Tag, tags } from '@lezer/highlight'
import {
  autocompletion,
  type CompletionContext,
  type CompletionResult,
} from '@codemirror/autocomplete'
import { BUILTINS } from './builtins.generated'

const KEYWORDS = new Set([
  'fn', 'let', 'var', 'type', 'const', 'use', 'java', 'pub', 'match', 'if',
  'else', 'for', 'in', 'while', 'comptime', 'test', 'assert', 'not', 'derive',
])

// Custom tags for the two classes the standard set doesn't cover cleanly: the
// name in a `fn foo` definition, and `$...` interpolation inside strings.
const defTag = Tag.define()
const interpTag = Tag.define()

interface State {
  // depth/kind of a multi-line string we're inside: '"""' or '`', else null
  block: '"""' | '`' | null
  // the previous significant token was `fn`, so the next identifier is a def name
  afterFn: boolean
}

function isIdentStart(ch: string) {
  return /[A-Za-z_]/.test(ch)
}
function isIdentChar(ch: string) {
  return /[A-Za-z0-9_]/.test(ch)
}

// Consume one `$name` or `${...}` interpolation; the opening `$` is already next.
function eatInterp(stream: any): boolean {
  if (!stream.eat('$')) return false
  if (stream.eat('{')) {
    while (!stream.eol() && stream.peek() !== '}') stream.next()
    stream.eat('}')
    return true
  }
  if (isIdentStart(stream.peek() ?? '')) {
    while (isIdentChar(stream.peek() ?? '')) stream.next()
    return true
  }
  return true // a lone `$` — treat as consumed
}

// Scan the body of a string with the given closer, honoring escapes (except raw
// backtick strings) and stopping at `$` so the caller can tag interpolation.
// Returns true if the closing delimiter was consumed.
function scanStringBody(stream: any, closer: string, raw: boolean): boolean {
  while (!stream.eol()) {
    const ch = stream.peek()
    if (!raw && ch === '\\') {
      stream.next()
      stream.next()
      continue
    }
    if (!raw && ch === '$') return false // hand back to interpolation handling
    if (stream.match(closer)) return true
    stream.next()
  }
  return false
}

const dawnMode = StreamLanguage.define<State>({
  startState: () => ({ block: null, afterFn: false }),
  token(stream, state) {
    // continue a multi-line string
    if (state.block) {
      const raw = state.block === '`'
      if (!raw && stream.peek() === '$') {
        eatInterp(stream)
        return 'interp'
      }
      if (scanStringBody(stream, state.block, raw)) state.block = null
      return 'string'
    }

    if (stream.eatSpace()) return null
    const wasAfterFn = state.afterFn
    state.afterFn = false

    const ch = stream.peek() as string

    // comment
    if (ch === '#') {
      stream.skipToEnd()
      return 'comment'
    }

    // strings: triple, then single double-quote, then raw backtick
    if (stream.match('"""')) {
      if (!scanStringBody(stream, '"""', false)) {
        if (stream.peek() === '$') return 'string' // interp handled next call
        state.block = '"""'
      }
      return 'string'
    }
    if (ch === '"') {
      stream.next()
      if (!scanStringBody(stream, '"', false)) {
        // stopped at $ or EOL; single-quote strings don't span lines
        if (stream.peek() === '$') return 'string'
      }
      return 'string'
    }
    if (ch === '`') {
      stream.next()
      if (!scanStringBody(stream, '`', true)) state.block = '`'
      return 'string'
    }

    // char literal: 'a', '\n', '\\'
    if (ch === "'") {
      stream.next()
      if (stream.peek() === '\\') stream.next()
      stream.next()
      stream.eat("'")
      return 'string'
    }

    // number
    if (/[0-9]/.test(ch)) {
      stream.match(/^[0-9][0-9_]*(\.[0-9_]+)?/)
      return 'number'
    }

    // identifier / keyword / type / definition name
    if (isIdentStart(ch)) {
      const start = stream.pos
      stream.next()
      while (isIdentChar(stream.peek() ?? '')) stream.next()
      const word = stream.string.slice(start, stream.pos)
      if (KEYWORDS.has(word)) {
        if (word === 'fn') state.afterFn = true
        return 'keyword'
      }
      if (/^[A-Z]/.test(word)) return 'typeName'
      // an identifier right after `fn` is the definition name
      if (wasAfterFn) return 'def'
      return 'variableName'
    }

    stream.next()
    return null
  },
  tokenTable: {
    keyword: tags.keyword,
    string: tags.string,
    comment: tags.lineComment,
    number: tags.number,
    typeName: tags.typeName,
    variableName: tags.variableName,
    def: defTag,
    interp: interpTag,
  },
})

// Colors lifted verbatim from site/assets/style.css (.k/.t/.f/.s/.i/.n/.c).
const dawnHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: '#cf222e' },
  { tag: tags.typeName, color: '#9333ea' },
  { tag: defTag, color: '#7c3aed' },
  { tag: tags.string, color: '#0a3069' },
  { tag: interpTag, color: '#0550ae' },
  { tag: tags.number, color: '#0550ae' },
  { tag: tags.lineComment, color: '#6e7781', fontStyle: 'italic' },
  { tag: tags.variableName, color: 'inherit' },
])

// Completion: builtins (with signature + doc), keywords, and a few snippets.
function dawnCompletions(context: CompletionContext): CompletionResult | null {
  const word = context.matchBefore(/[A-Za-z_][A-Za-z0-9_]*/)
  if (!word || (word.from === word.to && !context.explicit)) return null
  const options = [
    ...BUILTINS.map((b) => ({
      label: b.name,
      type: 'function',
      detail: b.sig.replace(/^fn\s+/, ''),
      info: b.doc,
      boost: 1,
    })),
    ...[...KEYWORDS].map((k) => ({ label: k, type: 'keyword' })),
  ]
  return { from: word.from, options, validFor: /^[A-Za-z0-9_]*$/ }
}

export function dawn(): LanguageSupport {
  return new LanguageSupport(dawnMode, [
    syntaxHighlighting(dawnHighlight),
    autocompletion({ override: [dawnCompletions] }),
  ])
}
