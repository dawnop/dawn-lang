// Entry: build the Playground UI inside #dawn-playground — a code-window frame
// (reusing the site's .code-window / pre.output styles) with a toolbar, the
// CodeMirror editor, and an output panel wired to the runner's /run endpoint.
import { EditorView, keymap } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { closeBrackets, completionKeymap } from '@codemirror/autocomplete'
import { bracketMatching, indentOnInput } from '@codemirror/language'
import { dawn } from './dawn-lang'
import { SAMPLES } from './samples'
import './playground.css'

// base64 <-> UTF-8, for sharing code in the URL hash.
function encodeShare(code: string): string {
  return btoa(unescape(encodeURIComponent(code)))
}
function decodeShare(hash: string): string | null {
  try {
    return decodeURIComponent(escape(atob(hash)))
  } catch {
    return null
  }
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  if (cls) node.className = cls
  if (text) node.textContent = text
  return node
}

interface RunResponse {
  ok: boolean
  phase: 'run' | 'compile' | 'timeout' | 'error'
  output: string
  exit?: number
  truncated?: boolean
  ms?: number
}

function mount(root: HTMLElement) {
  const endpoint = root.dataset.endpoint || '/api/run'

  // ---- frame + toolbar ----
  const win = el('figure', 'code-window dp-window')
  const bar = el('figcaption', 'code-window__bar')
  bar.appendChild(el('span', 'fname', 'playground.dawn'))

  const tools = el('div', 'dp-tools')
  const picker = el('select', 'dp-samples')
  SAMPLES.forEach((s, i) => {
    const opt = el('option')
    opt.value = String(i)
    opt.textContent = s.label
    picker.appendChild(opt)
  })
  const runBtn = el('button', 'dp-run')
  runBtn.type = 'button'
  runBtn.innerHTML = '运行 <kbd>⌘⏎</kbd>'
  tools.appendChild(picker)
  tools.appendChild(runBtn)
  bar.appendChild(tools)
  win.appendChild(bar)

  const editorHost = el('div', 'dp-editor')
  win.appendChild(editorHost)
  root.appendChild(win)

  const output = el('pre', 'output dp-output')
  output.textContent = '// 点「运行」或按 ⌘⏎ 执行'
  root.appendChild(output)

  // ---- editor ----
  const initial = location.hash.length > 1
    ? decodeShare(location.hash.slice(1)) ?? SAMPLES[0].code
    : SAMPLES[0].code

  const view = new EditorView({
    state: EditorState.create({
      doc: initial,
      extensions: [
        history(),
        dawn(),
        bracketMatching(),
        closeBrackets(),
        indentOnInput(),
        keymap.of([
          { key: 'Mod-Enter', run: () => (run(), true) },
          ...completionKeymap,
          ...defaultKeymap,
          ...historyKeymap,
          indentWithTab,
        ]),
        EditorView.lineWrapping,
      ],
    }),
    parent: editorHost,
  })

  const currentCode = () => view.state.doc.toString()

  // ---- run ----
  let running = false
  async function run() {
    if (running) return
    running = true
    runBtn.disabled = true
    output.dataset.phase = 'pending'
    output.textContent = '// 运行中…'
    location.replace('#' + encodeShare(currentCode()))
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: currentCode() }),
      })
      if (res.status === 429) {
        render({ ok: false, phase: 'error', output: '服务器繁忙，请稍后重试' })
      } else if (res.status === 413) {
        render({ ok: false, phase: 'error', output: '代码过长' })
      } else {
        render((await res.json()) as RunResponse)
      }
    } catch {
      render({ ok: false, phase: 'error', output: '无法连接到运行服务' })
    } finally {
      running = false
      runBtn.disabled = false
    }
  }

  function render(r: RunResponse) {
    output.dataset.phase = r.phase
    const body = r.output || '(无输出)'
    if (r.phase === 'run') {
      const ms = r.ms != null ? ` · ${r.ms}ms` : ''
      const code = r.exit != null ? ` · exit ${r.exit}` : ''
      output.textContent = body + `\n\n— 运行结束${code}${ms}` +
        (r.truncated ? '（输出已截断）' : '')
    } else if (r.phase === 'compile') {
      output.textContent = body
    } else if (r.phase === 'timeout') {
      output.textContent = body + '\n\n— 超时终止'
    } else {
      output.textContent = body
    }
  }

  runBtn.addEventListener('click', run)
  picker.addEventListener('change', () => {
    const s = SAMPLES[Number(picker.value)]
    if (s) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: s.code } })
      output.dataset.phase = ''
      output.textContent = '// 点「运行」或按 ⌘⏎ 执行'
    }
  })
}

const root = document.getElementById('dawn-playground')
if (root) mount(root)
