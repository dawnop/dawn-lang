import { DOMParser, parseHTML } from 'linkedom'
import { EditorState } from '@codemirror/state'
import { ensureSyntaxTree } from '@codemirror/language'
import type { EditorView } from '@codemirror/view'
import { CompletionContext, type Completion } from '@codemirror/autocomplete'
import { LSPPlugin, type LSPClient } from '@codemirror/lsp-client'
import { highlightTree } from '@lezer/highlight'
import { dawn, dawnHighlight, dawnMode } from '../src/dawn-lang'
import { DawnLspClient, completionInfo, completionOf, hoverParts, lspHoverSource, signatureHelpOf } from '../src/lsp'
import { docElement, docValue, documentedCompletionSource, highlightLanguage, renderDawnCode } from '../src/doc-render'

type Expect = (name: string, got: unknown, want: unknown) => void

export async function docRenderTests(expect: Expect): Promise<number> {
  let fails = 0
  const check: Expect = (name, got, want) => {
    if (JSON.stringify(got) !== JSON.stringify(want)) fails++
    expect(name, got, want)
  }
  const previous = { document: globalThis.document, DOMParser: globalThis.DOMParser }
  const { document } = parseHTML('<!doctype html><html><body></body></html>')
  Object.assign(globalThis, { document, DOMParser })
  try {
    const client = new DawnLspClient('ws://example.test/api/lsp')
    const core = (client as unknown as { lsp: LSPClient }).lsp
    const state = EditorState.create({ doc: 'greet(', extensions: [dawn()] })
    const view = { state, plugin: () => plugin } as unknown as EditorView
    const plugin = { view, client: core, docToHTML: LSPPlugin.prototype.docToHTML } as LSPPlugin
    const label = 'fn greet(emoji: String = "😀", value: List[Int]) -> String'
    const start = label.indexOf('value'), end = label.indexOf(')')
    const code = renderDawnCode(label, [start, end])
    check('signature preserves Unicode text', code.textContent, label)
    check('active UTF-16 range spans all its tokens', [...code.querySelectorAll('strong')].map((n) => n.textContent).join(''), label.slice(start, end))
    check('active types retain token classes', code.querySelector('strong .tok-typeName')?.textContent, 'List')
    check('invalid active range is ignored', renderDawnCode(label, [-1, 999]).querySelector('strong'), null)
    const tricky = 'let s = """first\n${"nested # ${42}"}\nlast"""\n# comment\nlet c = \'😀\''
    const ranges: [number, number, string][] = []
    highlightTree(dawnMode.parser.parse(tricky), dawnHighlight, (from, to, cls) => ranges.push([from, to, cls]))
    const rendered = renderDawnCode(tricky)
    check('multiline interpolation and escapes preserve text', rendered.textContent, tricky)
    check('snippet uses exactly editor token classes', [...rendered.querySelectorAll('span')].map((s) => [s.textContent, s.className]), ranges.map(([a, b, cls]) => [tricky.slice(a, b), cls]))
    const imports = 'use std/math.{exp as host_exp}\n\nuse std/narrow.{BF16, F32, f32}\nuse as/b.{as as local, f as as}\nlet as = 1'
    const importState = EditorState.create({ doc: imports, extensions: [dawn()] })
    const importRanges: [string, string][] = []
    highlightTree(ensureSyntaxTree(importState, imports.length, 5000)!, dawnHighlight,
      (a, b, cls) => importRanges.push([imports.slice(a, b), cls]))
    const importCode = renderDawnCode(imports)
    check('import documentation preserves the entire snippet', importCode.textContent, imports)
    check('import documentation matches editor classes without semantic tokens',
      [...importCode.querySelectorAll('span')].map(s => [s.textContent, s.className]), importRanges)
    check('import documentation highlights only rename operators',
      [...importCode.querySelectorAll('.tok-keyword')].map(s => s.textContent), ['use', 'as', 'use', 'use', 'as', 'as', 'let'])
    check('only Dawn and unlabeled code use the Dawn parser', [undefined, '', 'DAWN title', 'text', 'plaintext', 'rust'].map((n) => highlightLanguage(n) === dawnMode), [true, true, true, false, false, false])
    const sample = 'fn greet(value: Int) -> String = {\n  let text = "hello ${value}"\n  text # comment\n}'
    const literal = '---\n\n\n[`name`]\n<img src=x onerror=alert(1)>'
    const docs = [
      'Use `value`; see [`Int`] and [`helper`](file:///srv/main.dawn#L1).\n\n```dawn\n' + sample + '\n```\n\n- Nested example:\n\n    ```dawn\n    let count: Int = 42\n    ```\n\n    Indented example:\n\n        let answer = True\n\n```text\nfn stays_plain() -> String\n```',
      '````dawn\n' + literal + '\n```\n````',
      '~~~dawn\n' + sample + '\n~~~',
      '```\n' + sample + '\n```',
      '> - Quoted example:\n>\n>   ```dawn\n>   let count = 42\n>   ```',
      '```unknown\n' + sample + '\n```',
      '```dawn\n' + sample,
      '<img src=x onerror=alert(1)><script>alert(1)</script>Use `safe`.',
    ]
    for (const [i, doc] of docs.entries()) {
      const direct = docElement(view, doc, 'test')
      const hover = await lspHoverSource({ isReady: () => true, hover: async () => ({ contents: { kind: 'markdown', value: '```dawn\n' + label + '\n```\n\n---\n\n' + doc } }) }, () => null)(view, 0, 1)
      const hoverDOM = (hover as import('@codemirror/view').Tooltip).create(view).dom
      const info = await completionInfo({ view, completionDoc: async () => ({ kind: 'markdown', value: doc }) } as unknown as DawnLspClient, { label: 'greet', detail: label, data: {} })
      const help = signatureHelpOf({ signatures: [{ label, documentation: { kind: 'markdown', value: doc } }] })!
      const signatureDoc = docElement(view, help.doc, 'test')
      const blocks = (node: HTMLElement) => [...node.querySelectorAll('pre')].map((p) => [p.textContent, [...p.querySelectorAll('span')].map((s) => s.className)])
      for (const [route, node] of [['hover', hoverDOM], ['completion', info!], ['signature', signatureDoc]] as const) {
        check(`${route} doc ${i} keeps Markdown code and tokens`, blocks(node), blocks(direct))
        check(`${route} doc ${i} is sanitized`, node.querySelector('img,script,[href],[onerror],[style]'), null)
      }
      if (i === 0) {
        check('nested, indented and explicit text fences survive', direct.querySelectorAll('pre').length, 4)
        check('Dawn code is highlighted', direct.querySelector('pre .tok-keyword')?.textContent, 'fn')
        check('explicit text is not highlighted', direct.querySelectorAll('pre')[3].querySelector('span'), null)
        check('unresolved code link has no prose brackets', direct.querySelector('p')?.textContent, 'Use value; see Int and helper.')
      }
      if (i === 1) check('code literals, blank lines, HTML and nested fences survive', direct.querySelector('pre')?.textContent, literal + '\n```\n')
      if (i === 5) check('unknown language stays plain', direct.querySelector('pre span'), null)
    }
    const plain = { kind: 'plaintext' as const, value: '```dawn\n<img src=x> [`name`]\n```' }
    check('plaintext keeps its literal syntax', docElement(view, plain, 'test').textContent, plain.value)
    check('plaintext creates no HTML children', docElement(view, plain, 'test').children.length, 0)
    check('no plugin falls back safely', docElement(null, plain.value, 'test').textContent, plain.value)
    check('renderer exception falls back safely', docElement({ plugin: () => ({ docToHTML: () => { throw new Error('fixture') } }) } as unknown as EditorView, plain.value, 'test').textContent, plain.value)
    const docOnly = hoverParts({ kind: 'markdown', value: 'Only `documentation`.' })
    check('doc-only hover has no empty signature', docOnly.code, '')
    const unclosed = '```dawn\nlet text = """\n---\n\n\n[`name`]  \n\n'
    check('hover preserves trailing whitespace inside unclosed code', hoverParts('```dawn\nInt\n```\n\n---\n\n' + unclosed).doc, unclosed)
    const failed = await completionInfo({ view, completionDoc: async () => { throw new Error('resolve timeout') } } as unknown as DawnLspClient, { label: 'greet', detail: label, data: {} })
    check('failed or timed-out resolve keeps full detail', failed?.textContent, label)
    check('detail-only completion has an info callback', typeof completionOf({ label: 'greet', detail: label }, client)?.info, 'function')
    const duplicate = await completionInfo({ view, completionDoc: async () => '```dawn\n' + label + '\n```\n\n---\n\nDoc.' } as unknown as DawnLspClient, { label: 'greet', detail: label, data: {} })
    check('completion does not repeat its signature', duplicate?.textContent, label + 'Doc.\n')
    let resolve!: (doc: string) => void
    const pending = completionInfo({ view, completionDoc: () => new Promise<string>((r) => { resolve = r }) } as unknown as DawnLspClient, { label: 'greet', detail: label, data: {} })
    ;(view as { state: EditorState }).state = state.update({ changes: { from: 0, insert: 'x' } }).state
    resolve('stale')
    check('edited document discards resolved info', await pending, null)
    ;(view as { state: EditorState }).state = state
    const apply = () => {}
    const option: Completion = { label: 'greet', detail: label, info: 'Needs `use std/math`.', apply }
    const base = { from: 0, options: [option], validFor: /^\w*$/, filter: false }
    const adapted = await documentedCompletionSource(() => base)(new CompletionContext(state, 2, true, view))
    check('static adaptation preserves result fields', [adapted?.from, adapted?.validFor === base.validFor, adapted?.filter, adapted?.options[0].apply === apply], [0, true, false, true])
    const info = adapted!.options[0].info as (c: Completion) => HTMLElement
    check('static doc uses the captured view and shared renderer', info(option).querySelector('code')?.textContent, 'use std/math')
    check('static detail is complete', info(option).querySelector('.dp-hover-code')?.textContent, label)
    check('signature preserves plaintext kind', docValue(signatureHelpOf({ signatures: [{ label, documentation: plain }] })!.doc), plain.value)
  } finally {
    Object.assign(globalThis, previous)
  }
  return fails
}
