// Entry: build the Playground UI inside #dawn-playground — a code-window frame
// (reusing the site's .code-window / pre.output styles) with a toolbar, the
// CodeMirror editor, and an output panel wired to the runner's /run endpoint.
import { EditorView, keymap } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { closeBrackets, completionKeymap, acceptCompletion } from '@codemirror/autocomplete'
import { bracketMatching, indentOnInput } from '@codemirror/language'
import { dawn } from './dawn-lang'
import { dawnLint } from './lint'
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
  runBtn.innerHTML = 'Run <kbd>⌘⏎</kbd>'
  tools.appendChild(picker)
  tools.appendChild(runBtn)
  bar.appendChild(tools)
  win.appendChild(bar)

  const editorHost = el('div', 'dp-editor')
  win.appendChild(editorHost)
  root.appendChild(win)

  // Output panel stays hidden until the first run — no empty placeholder box.
  const output = el('pre', 'output dp-output')
  output.hidden = true
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
        dawnLint(endpoint.replace(/\/run$/, '/check')),
        bracketMatching(),
        closeBrackets(),
        indentOnInput(),
        keymap.of([
          { key: 'Mod-Enter', run: () => (run(), true) },
          // Monaco-style: Tab accepts the open completion, else indents.
          { key: 'Tab', run: acceptCompletion },
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
    output.hidden = false
    output.dataset.phase = 'pending'
    output.textContent = 'Running…'
    location.replace('#' + encodeShare(currentCode()))
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: currentCode() }),
      })
      if (res.status === 429) {
        render({ ok: false, phase: 'error', output: 'Server busy — try again shortly' })
      } else if (res.status === 413) {
        render({ ok: false, phase: 'error', output: 'Source too long' })
      } else {
        render((await res.json()) as RunResponse)
      }
    } catch {
      render({ ok: false, phase: 'error', output: 'Could not reach the run service' })
    } finally {
      running = false
      runBtn.disabled = false
    }
  }

  function render(r: RunResponse) {
    output.dataset.phase = r.phase
    const body = r.output || '(no output)'
    if (r.phase === 'run') {
      const ms = r.ms != null ? ` · ${r.ms}ms` : ''
      const code = r.exit != null ? ` · exit ${r.exit}` : ''
      output.textContent = body + `\n\n— done${code}${ms}` +
        (r.truncated ? ' (output truncated)' : '')
    } else if (r.phase === 'compile') {
      output.textContent = body
    } else if (r.phase === 'timeout') {
      output.textContent = body + '\n\n— timed out'
    } else {
      output.textContent = body
    }
  }

  runBtn.addEventListener('click', run)
  picker.addEventListener('change', () => {
    const s = SAMPLES[Number(picker.value)]
    if (s) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: s.code } })
      output.hidden = true
      output.dataset.phase = ''
    }
  })
}

const root = document.getElementById('dawn-playground')
if (root) mount(root)
