// Documentation shares the editor's parser and token classes. Snippets have no
// document positions, so they deliberately do not receive LSP semantic tokens.
import { LSPPlugin } from '@codemirror/lsp-client'
import type { EditorView } from '@codemirror/view'
import type { CompletionResult, CompletionSource } from '@codemirror/autocomplete'
import { highlightTree } from '@lezer/highlight'
import { dawnMode, dawnHighlight } from './dawn-lang'

export type DocContent = string | { kind: 'markdown' | 'plaintext'; value: string }

export function docContent(value: unknown): DocContent {
  if (typeof value === 'string') return value
  if (value != null && typeof value === 'object' && 'value' in value && typeof value.value === 'string') {
    return { kind: 'kind' in value && value.kind === 'plaintext' ? 'plaintext' : 'markdown', value: value.value }
  }
  return ''
}

export function docValue(doc: DocContent): string {
  return typeof doc === 'string' ? doc : doc.value
}

export function highlightLanguage(name?: string) {
  const word = (name ?? '').trim().split(/\s+/)[0].toLowerCase()
  return !word || word === 'dawn' ? dawnMode : null
}

/** Parse the whole signature once, then intersect token and UTF-16 ranges. */
export function renderDawnCode(text: string, active?: readonly [number, number]): HTMLElement {
  const node = document.createElement('div')
  node.className = 'dp-hover-code'
  const range = active && Number.isInteger(active[0]) && Number.isInteger(active[1])
    && active[0] >= 0 && active[0] < active[1] && active[1] <= text.length ? active : null
  const append = (from: number, to: number, cls = '') => {
    const cuts = [from, to, ...(range ? range.filter((n) => n > from && n < to) : [])].sort((a, b) => a - b)
    for (let i = 1; i < cuts.length; i++) {
      const start = cuts[i - 1], end = cuts[i]
      if (start === end) continue
      let piece: Node = document.createTextNode(text.slice(start, end))
      if (cls) {
        const token = document.createElement('span')
        token.className = cls
        token.appendChild(piece)
        piece = token
      }
      if (range && start >= range[0] && end <= range[1]) {
        const mark = document.createElement('strong')
        mark.className = 'dp-signature-active'
        mark.appendChild(piece)
        piece = mark
      }
      node.appendChild(piece)
    }
  }
  let pos = 0
  highlightTree(dawnMode.parser.parse(text), dawnHighlight, (from, to, cls) => {
    append(pos, from)
    append(from, to, cls)
    pos = to
  })
  append(pos, text.length)
  return node
}

/** Highlighting precedes the client's sanitizer. Failure keeps literal text. */
export function docElement(view: EditorView | null, doc: DocContent, className: string): HTMLElement {
  const node = document.createElement('div')
  node.className = `${className} dp-doc`
  const text = docValue(doc)
  const plain = typeof doc !== 'string' && doc.kind === 'plaintext'
  try {
    const plugin = view && LSPPlugin.get(view)
    if (!plugin || plain) throw new Error('literal documentation')
    node.innerHTML = plugin.docToHTML(doc, 'markdown')
    // The client's highlighter emits <br> inside pre. Restore real newlines
    // for selection/copy and scrolling, without touching literal code text.
    node.querySelectorAll('pre br').forEach((br) => br.replaceWith(document.createTextNode('\n')))
    // Unresolved [`name`] references are prose compatibility syntax. Work on
    // siblings of inline code only; never rewrite a code block or its text.
    node.querySelectorAll('code').forEach((code) => {
      if (code.closest('pre, a')) return
      const before = code.previousSibling, after = code.nextSibling
      if (before?.nodeType === 3 && after?.nodeType === 3
          && before.nodeValue?.endsWith('[') && after.nodeValue?.startsWith(']')) {
        before.nodeValue = before.nodeValue.slice(0, -1)
        after.nodeValue = after.nodeValue.slice(1)
      }
    })
  } catch {
    node.classList.add('dp-doc-plain')
    node.textContent = text
  }
  return node
}

export function docPreview(view: EditorView | null, detail: string, doc: DocContent, className: string): HTMLElement | null {
  if (!detail && !docValue(doc).trim()) return null
  const node = document.createElement('div')
  node.className = className
  if (detail) node.appendChild(renderDawnCode(detail))
  if (docValue(doc).trim()) node.appendChild(docElement(view, doc, 'dp-hover-doc'))
  return node
}

/** Capture the source's actual view, keeping every other completion field. */
export function documentedCompletionSource(source: CompletionSource): CompletionSource {
  return async (context) => {
    const result = await source(context)
    if (!result) return null
    return { ...result, options: result.options.map((option) => {
      if (typeof option.info !== 'string') return option
      const doc = option.info
      return { ...option, info: () => docPreview(context.view ?? null, option.detail ?? '', doc, 'dp-completion-doc') }
    }) } as CompletionResult
  }
}
