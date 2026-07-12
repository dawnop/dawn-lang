// Entry: build the Playground UI inside #dawn-playground — a VS Code-style
// full-viewport IDE: an explorer sidebar listing the sample programs as files,
// and an editor column (toolbar, line-numbered CodeMirror, console panel that
// slides in under the editor after a run).
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { closeBrackets, completionKeymap, acceptCompletion } from '@codemirror/autocomplete'
import { bracketMatching, indentOnInput } from '@codemirror/language'
import { lintGutter } from '@codemirror/lint'
import { dawn } from './dawn-lang'
import { dawnLint, errorLens } from './lint'
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

  const ide = el('div', 'dp-ide')

  // ---- explorer sidebar: the samples as files ----
  const side = el('aside', 'dp-side')
  side.appendChild(el('div', 'dp-sidetitle', 'Samples'))
  const fileBtns: HTMLButtonElement[] = []
  SAMPLES.forEach((s, i) => {
    const b = el('button', 'dp-file', s.file)
    b.type = 'button'
    b.title = s.label
    b.addEventListener('click', () => openSample(i))
    fileBtns.push(b)
    side.appendChild(b)
  })

  // ---- editor column ----
  const main = el('div', 'dp-main')

  const bar = el('div', 'dp-bar')
  const fname = el('span', 'dp-fname')
  const spacer = el('div', 'dp-spacer')
  const shareBtn = el('button', 'dp-share', 'Share')
  shareBtn.type = 'button'
  const runBtn = el('button', 'dp-run')
  runBtn.type = 'button'
  runBtn.innerHTML = 'Run <kbd>⌘⏎</kbd>'
  bar.append(fname, spacer, shareBtn, runBtn)

  const editorHost = el('div', 'dp-editor')

  const outPanel = el('div', 'dp-outpanel')
  outPanel.hidden = true
  const outHead = el('div', 'dp-outhead')
  const outTitle = el('span', 'dp-outtitle', 'Output')
  const outMeta = el('span', 'dp-outmeta')
  const outClose = el('button', 'dp-outclose', '×')
  outClose.type = 'button'
  outClose.title = 'Close output'
  outHead.append(outTitle, outMeta, outClose)
  const output = el('pre', 'dp-console')
  outPanel.append(outHead, output)

  main.append(bar, editorHost, outPanel)
  ide.append(side, main)
  root.appendChild(ide)

  // ---- current "file" state ----
  // A shared link opens as its own scratch file; otherwise the first sample.
  const fromHash = location.hash.length > 1 ? decodeShare(location.hash.slice(1)) : null
  let current = fromHash != null ? -1 : 0
  const baseline = () => (current >= 0 ? SAMPLES[current].code : fromHash ?? '')

  function refreshChrome() {
    const name = current >= 0 ? SAMPLES[current].file : 'shared.dawn'
    const dirty = view && view.state.doc.toString() !== baseline()
    fname.textContent = dirty ? `${name} •` : name
    fileBtns.forEach((b, i) => b.classList.toggle('active', i === current))
  }

  function openSample(i: number) {
    current = i
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: SAMPLES[i].code } })
    outPanel.hidden = true
    outPanel.dataset.phase = ''
    refreshChrome()
  }

  // ---- editor ----
  const view = new EditorView({
    state: EditorState.create({
      doc: fromHash ?? SAMPLES[0].code,
      extensions: [
        history(),
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightActiveLine(),
        dawn(),
        dawnLint(endpoint.replace(/\/run$/, '/check')),
        errorLens,
        lintGutter(),
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
        EditorView.updateListener.of((u) => {
          if (u.docChanged) refreshChrome()
        }),
      ],
    }),
    parent: editorHost,
  })
  refreshChrome()

  const currentCode = () => view.state.doc.toString()

  // ---- run ----
  let running = false
  async function run() {
    if (running) return
    running = true
    runBtn.disabled = true
    outPanel.hidden = false
    outPanel.dataset.phase = 'pending'
    outMeta.textContent = ''
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
    outPanel.dataset.phase = r.phase
    output.textContent = r.output || '(no output)'
    if (r.phase === 'run') {
      const parts = [`exit ${r.exit ?? 0}`]
      if (r.ms != null) parts.push(`${r.ms} ms`)
      if (r.truncated) parts.push('output truncated')
      outMeta.textContent = parts.join(' · ')
    } else if (r.phase === 'compile') {
      outMeta.textContent = 'compile error'
    } else if (r.phase === 'timeout') {
      outMeta.textContent = 'timed out'
    } else {
      outMeta.textContent = 'error'
    }
  }

  runBtn.addEventListener('click', run)
  outClose.addEventListener('click', () => {
    outPanel.hidden = true
  })
  shareBtn.addEventListener('click', async () => {
    location.replace('#' + encodeShare(currentCode()))
    try {
      await navigator.clipboard.writeText(location.href)
      shareBtn.textContent = 'Copied!'
    } catch {
      shareBtn.textContent = 'Copy the URL'
    }
    setTimeout(() => (shareBtn.textContent = 'Share'), 1500)
  })
}

const root = document.getElementById('dawn-playground')
if (root) mount(root)
