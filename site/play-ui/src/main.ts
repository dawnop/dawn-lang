// Entry: build the Playground UI inside #dawn-playground — a VS Code-style
// full-viewport IDE: an explorer sidebar listing the sample programs as files,
// and an editor column (toolbar, line-numbered CodeMirror, console panel that
// slides in under the editor after a run).
//
// Edits survive a reload through localStorage, not the URL: the hash is only
// written on Run and Share, so it cannot be the draft store, and a draft is a
// fact about this browser, not something to put in a link. A shared link still
// wins over the draft, since following one is asking for that code.
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { closeBrackets, completionKeymap, acceptCompletion } from '@codemirror/autocomplete'
import { bracketMatching, indentOnInput } from '@codemirror/language'
import { lintGutter } from '@codemirror/lint'
import { dawn, dawnCompletions, loadBuiltins, staticCompletions } from './dawn-lang'
import { dawnDiagnostics, errorLens } from './lint'
import {
  DawnLspClient,
  goToLspDefinition,
  lspCompletionSource,
  lspDefinition,
  lspHover,
  lspInlayHints,
  lspSemanticTokens,
  prefetchWhenOffline,
} from './lsp'
import { playEndpoints } from './endpoints'
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

// The run service's limits, as playground/src/play/config.dawn and main.dawn
// set them (run and compile budgets, MAX_BODY, OUTPUT_LIMIT, MAX_CONCURRENT).
// Copied rather than fetched: they change with a deploy of that service, and a
// stale line here costs a reader less than another request on every load.
const LIMITS =
  'Limits: 10 s to run, 30 s to compile, 64 KiB of source and of output, ' +
  '2 programs at a time. Runs on the JVM; there is no stdin.'

// On anything but a Mac the shortcut is Ctrl. Same test as the site's search
// button (site/assets/search.js), copied so this bundle has no dependency on
// that file.
const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)

const DRAFT_KEY = 'dawn-playground-draft'
interface Draft { file: number; code: string; base: string }

// Storage can be missing or throw (private windows, blocked site data), and a
// draft is a convenience: every failure reads as "no draft".
function loadDraft(): Draft | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (!raw) return null
    const d = JSON.parse(raw) as Partial<Draft>
    if (typeof d.code !== 'string' || typeof d.file !== 'number') return null
    return { file: d.file, code: d.code, base: typeof d.base === 'string' ? d.base : '' }
  } catch {
    return null
  }
}
function saveDraft(d: Draft) {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(d))
  } catch {
    // quota or blocked storage: the editor keeps working without a draft
  }
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
  // The service URL is the page's to say (gen/pages.play_endpoint), relative
  // or on another origin; the bundle has no default of its own to drift.
  const runUrl = root.dataset.endpoint
  if (!runUrl) throw new Error('#dawn-playground has no data-endpoint')
  const endpoints = playEndpoints(runUrl, location.href)
  const endpoint = endpoints.run

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
  const checking = el('span', 'dp-checking', 'Checking…')
  checking.hidden = true
  const spacer = el('div', 'dp-spacer')
  const version = el('span', 'dp-version')
  version.title = 'The compiler release the run service uses'
  const shareBtn = el('button', 'dp-share', 'Share')
  shareBtn.type = 'button'
  const runBtn = el('button', 'dp-run')
  runBtn.type = 'button'
  runBtn.append('Run ', el('kbd', undefined, isMac ? '⌘⏎' : 'Ctrl ⏎'))
  runBtn.title = isMac ? 'Run (⌘ Enter)' : 'Run (Ctrl Enter)'
  bar.append(fname, checking, spacer, version, shareBtn, runBtn)

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
  outPanel.append(outHead, output, el('div', 'dp-limits', LIMITS))

  main.append(bar, editorHost, outPanel)
  ide.append(side, main)
  root.appendChild(ide)

  // ---- current "file" state ----
  // A shared link opens as its own scratch file; otherwise the draft this
  // browser left behind; otherwise the first sample. `scratch` is what an
  // unnamed file (current = -1) counts as clean against.
  const fromHash = location.hash.length > 1 ? decodeShare(location.hash.slice(1)) : null
  const draft = fromHash == null ? loadDraft() : null
  let current = 0
  let scratch = ''
  let initialCode = SAMPLES[0].code
  if (fromHash != null) {
    current = -1
    scratch = fromHash
    initialCode = fromHash
  } else if (draft) {
    current = draft.file >= 0 && draft.file < SAMPLES.length ? draft.file : -1
    scratch = draft.base
    initialCode = draft.code
  }
  const baseline = () => (current >= 0 ? SAMPLES[current].code : scratch)
  const checkEndpoint = endpoints.check
  const healthEndpoint = endpoints.health
  const lsp = new DawnLspClient(endpoints.lsp)

  function refreshChrome() {
    const name = current >= 0 ? SAMPLES[current].file : 'shared.dawn'
    const dirty = view && view.state.doc.toString() !== baseline()
    fname.textContent = dirty ? `${name} •` : name
    fileBtns.forEach((b, i) => b.classList.toggle('active', i === current))
  }

  function isDirty() {
    return view.state.doc.toString() !== baseline()
  }

  // Opening a sample replaces the buffer, so unsaved edits get a chance to
  // stay. Clicking the open sample again is a revert, and asks the same way.
  function openSample(i: number) {
    if (isDirty()) {
      const name = current >= 0 ? SAMPLES[current].file : 'shared.dawn'
      const ask = i === current
        ? `Revert ${name} to the original sample? Your edits will be lost.`
        : `Open ${SAMPLES[i].file}? Your edits to ${name} will be lost.`
      if (!confirm(ask)) return
    }
    current = i
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: SAMPLES[i].code } })
    outPanel.hidden = true
    outPanel.dataset.phase = ''
    refreshChrome()
  }

  // ---- editor ----
  const view = new EditorView({
    state: EditorState.create({
      doc: initialCode,
      extensions: [
        history(),
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightActiveLine(),
        dawn(lspCompletionSource(lsp, staticCompletions, dawnCompletions)),
        dawnDiagnostics(checkEndpoint, lsp, (busy) => (checking.hidden = !busy)),
        lspHover(lsp),
        lspInlayHints(lsp),
        lspSemanticTokens(lsp),
        lspDefinition(lsp),
        errorLens,
        lintGutter(),
        bracketMatching(),
        closeBrackets(),
        indentOnInput(),
        keymap.of([
          { key: 'Mod-Enter', run: () => (run(), true) },
          { key: 'F12', run: () => goToLspDefinition(lsp, view) },
          // Monaco-style: Tab accepts the open completion, else indents.
          { key: 'Tab', run: acceptCompletion },
          ...completionKeymap,
          ...defaultKeymap,
          ...historyKeymap,
          indentWithTab,
        ]),
        EditorView.lineWrapping,
        EditorView.updateListener.of((u) => {
          if (u.docChanged) {
            lsp.update(u.state.doc.toString())
            refreshChrome()
            scheduleDraft()
          }
        }),
      ],
    }),
    parent: editorHost,
  })
  lsp.start(initialCode)
  prefetchWhenOffline(lsp, loadBuiltins)
  refreshChrome()

  // ---- draft: debounced, so typing does not write storage per keystroke ----
  let draftTimer: ReturnType<typeof setTimeout> | null = null
  function scheduleDraft() {
    if (draftTimer != null) clearTimeout(draftTimer)
    draftTimer = setTimeout(() => {
      draftTimer = null
      saveDraft({ file: current, code: view.state.doc.toString(), base: current >= 0 ? '' : scratch })
    }, 500)
  }
  // A pending write must not be lost to closing the tab inside the debounce.
  addEventListener('pagehide', () => {
    if (draftTimer == null) return
    clearTimeout(draftTimer)
    draftTimer = null
    saveDraft({ file: current, code: view.state.doc.toString(), base: current >= 0 ? '' : scratch })
  })

  // ---- compiler version, from the run service's /health ----
  fetch(healthEndpoint)
    .then((res) => (res.ok ? res.json() : null))
    .then((h: { version?: unknown } | null) => {
      if (h && typeof h.version === 'string' && h.version) version.textContent = `Dawn ${h.version}`
    })
    .catch(() => {
      // An older runner answers plain "ok", and an unreachable one says so on Run.
    })

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
