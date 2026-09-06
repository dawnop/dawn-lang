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
  type CompletionSource,
} from '@codemirror/autocomplete'
import { BUILTINS } from './builtins.generated'

const KEYWORDS = new Set([
  'fn', 'let', 'var', 'type', 'const', 'use', 'java', 'pub', 'match', 'if',
  'else', 'for', 'in', 'while', 'return', 'comptime', 'test', 'assert', 'not', 'derive',
  'trait', 'impl',
])

// Custom tags for the two classes the standard set doesn't cover cleanly: the
// name in a `fn foo` definition, and `$...` interpolation inside strings.
const defTag = Tag.define()
const interpTag = Tag.define()

type Context = { kind: 'string'; closer: '"' | '"""' | '`' } |
  { kind: 'interp'; depth: number }

interface State {
  // Interpolation returns to its enclosing string, even across nested strings
  // and expressions. Each cached line owns its copy of this stack.
  contexts: Context[]
  // the previous significant token was `fn`, so the next identifier is a def name
  afterFn: boolean
}

function isIdentStart(ch: string) {
  return /[A-Za-z_]/.test(ch)
}
function isIdentChar(ch: string) {
  return /[A-Za-z0-9_]/.test(ch)
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
  startState: () => ({ contexts: [], afterFn: false }),
  copyState: state => ({ contexts: state.contexts.map(frame => ({ ...frame })), afterFn: state.afterFn }),
  blankLine(state) {
    const top = state.contexts[state.contexts.length - 1]
    if (top?.kind === 'string' && top.closer === '"') state.contexts.pop()
  },
  token(stream, state) {
    // An unfinished ordinary string stops at the line boundary. Do not pop
    // an enclosing string while a multi-line interpolation is still code.
    let context = state.contexts[state.contexts.length - 1]
    if (stream.sol() && context?.kind === 'string' && context.closer === '"') {
      state.contexts.pop()
      context = state.contexts[state.contexts.length - 1]
    }
    if (context?.kind === 'string') {
      const raw = context.closer === '`'
      if (!raw && stream.peek() === '$') {
        stream.next()
        if (stream.eat('{')) state.contexts.push({ kind: 'interp', depth: 1 })
        else while (isIdentChar(stream.peek() ?? '')) stream.next()
        return 'interp'
      }
      if (scanStringBody(stream, context.closer, raw)) state.contexts.pop()
      return 'string'
    }

    if (stream.eatSpace()) return null
    const wasAfterFn = state.afterFn
    state.afterFn = false

    const ch = stream.peek() as string

    // Strings and comments below consume their braces themselves. Only code
    // braces count toward the interpolation's return to its outer string.
    if (context?.kind === 'interp') {
      if (ch === '{') context.depth++
      if (ch === '}' && --context.depth === 0) {
        stream.next()
        state.contexts.pop()
        return 'interp'
      }
    }

    // comment
    if (ch === '#') {
      stream.skipToEnd()
      return 'comment'
    }

    // strings: triple, then single double-quote, then raw backtick
    if (stream.match('"""')) {
      if (!scanStringBody(stream, '"""', false)) {
        state.contexts.push({ kind: 'string', closer: '"""' })
      }
      return 'string'
    }
    if (ch === '"') {
      stream.next()
      if (!scanStringBody(stream, '"', false)) {
        state.contexts.push({ kind: 'string', closer: '"' })
      }
      return 'string'
    }
    if (ch === '`') {
      stream.next()
      if (!scanStringBody(stream, '`', true)) state.contexts.push({ kind: 'string', closer: '`' })
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

// Constructors of the prelude ADTs — completable like builtins.
const CTORS = ['Some', 'None', 'Ok', 'Err', 'True', 'False']
// Builtin type names (compiler's Types.named + the builtin containers/ADTs).
const TYPES = ['Int', 'Float', 'Bool', 'String', 'Unit', 'List', 'Map', 'Set', 'Option', 'Result']

// Where the cursor sits lexically. The editor's syntax tree can lag a few
// keystrokes behind fast typing, so this re-scans the buffer up to the cursor
// with the same string/comment rules as the tokenizer — cheap at playground
// sizes and always current.
export function lexContext(text: string, pos: number): 'code' | 'comment' | 'string' | 'interp' {
  let kind: 'code' | 'comment' | 'dq' | 'triple' | 'raw' = 'code'
  let i = 0
  while (i < pos) {
    const ch = text[i]
    if (kind === 'code') {
      if (text.startsWith('"""', i)) {
        kind = 'triple'
        i += 3
      } else if (ch === '#') {
        kind = 'comment'
        i++
      } else if (ch === '"') {
        kind = 'dq'
        i++
      } else if (ch === '`') {
        kind = 'raw'
        i++
      } else if (ch === "'") {
        // char literal: 'a' or '\n'
        i++
        if (text[i] === '\\') i++
        i++
        if (text[i] === "'") i++
      } else {
        i++
      }
    } else if (kind === 'comment') {
      if (ch === '\n') kind = 'code'
      i++
    } else if (kind === 'dq') {
      if (ch === '\\') i += 2
      else {
        if (ch === '"' || ch === '\n') kind = 'code' // double-quote strings don't span lines
        i++
      }
    } else if (kind === 'triple') {
      if (ch === '\\') i += 2
      else if (text.startsWith('"""', i)) {
        kind = 'code'
        i += 3
      } else i++
    } else {
      // raw backtick: no escapes, no interpolation
      if (ch === '`') kind = 'code'
      i++
    }
  }
  if (kind === 'comment') return 'comment'
  if (kind === 'raw') return 'string'
  if (kind === 'dq' || kind === 'triple') {
    // a `$name` or `${expr}` being typed completes like code
    if (/\$[A-Za-z_]\w*$|\$\{[^}"]*$/.test(text.slice(Math.max(0, pos - 200), pos))) return 'interp'
    return 'string'
  }
  return 'code'
}

// Names declared in the buffer itself (the user's own functions, bindings,
// types, and ADT constructors), so completion isn't limited to builtins.
// `skipFrom` is the start of the word being typed, which would otherwise
// offer itself as its own completion.
function docDecls(doc: string, skipFrom: number) {
  const re = /\b(?:fn|let|var|const|type)\s+([A-Za-z_]\w*)|\|\s*([A-Z]\w*)/g
  const seen = new Set<string>()
  const out: { label: string; type: string; boost: number }[] = []
  let m: RegExpExecArray | null
  while ((m = re.exec(doc))) {
    const name = m[1] ?? m[2]
    if (m.index + m[0].lastIndexOf(name) === skipFrom) continue
    if (seen.has(name) || KEYWORDS.has(name)) continue
    seen.add(name)
    const type = m[2] || /^[A-Z]/.test(name) ? 'type' : m[0].startsWith('fn') ? 'function' : 'variable'
    out.push({ label: name, type, boost: 2 })
  }
  return out
}

// Completion: builtins (with signature + doc), keywords, prelude constructors,
// and declarations scanned from the buffer. Suppressed where a suggestion can
// only be noise: inside strings and comments, while naming a fresh binding
// (after fn/let/var/const/type/for/derive), on `use` lines (module paths), and
// right after `.` (Java members) or `!` (effect rows).
export function dawnCompletions(context: CompletionContext): CompletionResult | null {
  const word = context.matchBefore(/[A-Za-z_][A-Za-z0-9_]*/)
  const inside = lexContext(context.state.sliceDoc(0, context.pos), context.pos)
  if (inside === 'string' || inside === 'comment') return null
  const from = word ? word.from : context.pos
  const line = context.state.doc.lineAt(context.pos)
  const before = context.state.sliceDoc(line.from, from)
  // an effect row: `!` admits exactly one builtin effect. Pops as soon as the
  // `!` is typed (no word required), like an IDE trigger character.
  if (before.endsWith('!')) {
    return {
      from,
      options: [{ label: 'io', type: 'keyword', info: 'the IO effect — this function may perform input/output' }],
      validFor: /^\w*$/,
    }
  }
  if (!word && !context.explicit) return null
  if (/(?:^|[^\w])(?:fn|let|var|const|type|for|derive|trait)\s+$/.test(before)) return null
  if (/^\s*(?:pub\s+)?use\b/.test(before)) return null
  if (before.endsWith('.')) return null

  const locals = docDecls(context.state.doc.toString(), from)
  const options = [
    ...locals,
    ...BUILTINS.map((b) => ({
      label: b.name,
      type: 'function',
      detail: b.sig.replace(/^fn\s+/, ''),
      info: b.doc,
      boost: 1,
    })),
    ...TYPES.map((t) => ({ label: t, type: 'type' })),
    ...CTORS.map((c) => ({ label: c, type: 'type' })),
    ...[...KEYWORDS].map((k) => ({ label: k, type: 'keyword' })),
  ]
  // An uppercase prefix means a type or constructor — lowercase suggestions
  // would just bury the real matches.
  const typed = word?.text ?? ''
  const filtered = /^[A-Z]/.test(typed)
    ? options.filter((o) => /^[A-Z]/.test(o.label))
    : options
  return { from, options: filtered, validFor: /^[A-Za-z0-9_]*$/ }
}

export function dawn(completionSource: CompletionSource = dawnCompletions): LanguageSupport {
  return new LanguageSupport(dawnMode, [
    syntaxHighlighting(dawnHighlight),
    autocompletion({ override: [completionSource] }),
  ])
}
