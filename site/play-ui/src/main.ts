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
import { callMarks, pickCall, rangesOf, setCalls } from './call-marks'
import { ComparePane } from './compile-view'
import { targetOfSearch, withView, type Target } from './compile-state'
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
// Shown in the output header's "?" popover, not on a row of its own.
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
  const viewBtn = el('button', 'dp-share dp-viewtoggle', 'C / JVM')
  viewBtn.type = 'button'
  viewBtn.title = 'Show the C and JVM code this program compiles to; click a call to follow it'
  viewBtn.setAttribute('aria-controls', 'dp-view')
  viewBtn.setAttribute('aria-expanded', 'false')
  const shareBtn = el('button', 'dp-share', 'Share')
  shareBtn.type = 'button'
  const runBtn = el('button', 'dp-run')
  runBtn.type = 'button'
  runBtn.append('Run ', el('kbd', undefined, isMac ? '⌘⏎' : 'Ctrl ⏎'))
  runBtn.title = isMac ? 'Run (⌘ Enter)' : 'Run (Ctrl Enter)'
  bar.append(fname, checking, spacer, version, viewBtn, shareBtn, runBtn)

  // The editor and, when asked for, the generated code beside it (stacked
  // under it on a narrow screen): one row, so the console stays below both.
  const work = el('div', 'dp-work')
  const editorHost = el('div', 'dp-editor')

  const outPanel = el('div', 'dp-outpanel')
  outPanel.hidden = true
  const outHead = el('div', 'dp-outhead')
  const outTitle = el('span', 'dp-outtitle', 'Output')
  const outMeta = el('span', 'dp-outmeta')
  const outClose = el('button', 'dp-outclose', '×')
  outClose.type = 'button'
  outClose.title = 'Close output'
  const helpBtn = el('button', 'dp-help')
  helpBtn.type = 'button'
  helpBtn.setAttribute('aria-label', 'Run limits')
  helpBtn.setAttribute('aria-expanded', 'false')
  helpBtn.setAttribute('aria-controls', 'dp-limits')
  // A circled question mark drawn inline: no icon font, no extra request.
  helpBtn.innerHTML =
    '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">' +
    '<circle cx="8" cy="8" r="6.8" fill="none" stroke="currentColor" stroke-width="1.3"/>' +
    '<path d="M6.1 6.2a1.95 1.95 0 1 1 2.9 1.7c-.7.4-1 .8-1 1.5" fill="none" ' +
    'stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>' +
    '<circle cx="8" cy="11.7" r="0.85" fill="currentColor"/></svg>'
  const limits = el('div', 'dp-limits', LIMITS)
  limits.id = 'dp-limits'
  limits.setAttribute('role', 'note')
  limits.hidden = true
  // Click alone must work (touch has no hover): toggle, and close on Esc or a
  // click anywhere else.
  const setHelp = (open: boolean) => {
    limits.hidden = !open
    helpBtn.setAttribute('aria-expanded', open ? 'true' : 'false')
  }
  helpBtn.addEventListener('click', () => setHelp(limits.hidden))
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !limits.hidden) { setHelp(false); helpBtn.focus() }
  })
  document.addEventListener('click', (e) => {
    const t = e.target as Node
    if (!limits.hidden && !limits.contains(t) && !helpBtn.contains(t)) setHelp(false)
  })
  outHead.append(outTitle, outMeta, helpBtn, outClose)
  const output = el('pre', 'dp-console')
  outPanel.append(outHead, output, limits)

  // The tab last shown, which the toolbar button reopens.
  let lastTarget: Target = 'c'
  const pane = new ComparePane({
    endpoint: endpoints.compile,
    code: () => view.state.doc.toString(),
    opened: (t) => {
      if (t) lastTarget = t
      viewBtn.setAttribute('aria-expanded', t ? 'true' : 'false')
      viewBtn.classList.toggle('active', t !== null)
      // `?view=` is the open tab; the hash (the program) is not touched.
      try {
        window.history.replaceState(window.history.state, '', withView(location.href, t))
      } catch {
        // a sandboxed frame may refuse; the pane works without the URL
      }
    },
    calls: (cs) => view.dispatch({ effects: setCalls.of(rangesOf(view.state.doc, cs)) }),
    picked: (id) => view.dispatch({ effects: pickCall.of(id) }),
  })
  work.append(editorHost, pane.root)

  main.append(bar, work, outPanel)
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
        callMarks({
          pick: (id) => pane.pick(id),
          none: () => pane.announce('No call at the cursor.'),
          release: () => (pane.hasPick() ? (pane.pick(null), true) : false),
        }),
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
            pane.edited()
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
  // A link that names a tab opens it, and opening compiles.
  const asked = targetOfSearch(location.search)
  if (asked) pane.open(asked)

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
        // /run and /compile share two permits: stop recompiling by itself
        pane.serviceBusy()
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
  viewBtn.addEventListener('click', () => (pane.isOpen() ? pane.close() : pane.open(lastTarget)))
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
