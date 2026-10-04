import type {
  Completion,
  CompletionContext,
  CompletionResult,
  CompletionSource,
} from '@codemirror/autocomplete'
import type { Diagnostic } from '@codemirror/lint'
import type { Extension, Range } from '@codemirror/state'
import {
  Decoration,
  type DecorationSet,
  EditorView,
  hoverTooltip,
  ViewPlugin,
  type ViewUpdate,
  WidgetType,
} from '@codemirror/view'

export const DAWN_LSP_URI = 'untitled:dawn-playground/prog.dawn'
export const DAWN_LSP_PROTOCOL = 'dawn-lsp-v1'

export type LspStatus = 'connecting' | 'ready' | 'fallback'

export interface LspPosition {
  line: number
  character: number
}

export interface LspRange {
  start: LspPosition
  end: LspPosition
}

export interface LspDiagnostic {
  range: LspRange
  severity?: number
  message: string
  source?: string
  code?: string | number
}

export interface LspDiagnosticsEvent {
  generation: number
  text: string
  diagnostics: LspDiagnostic[]
}

interface LspCompletionItem {
  label: string
  kind?: number
  detail?: string
  sortText?: string
  insertText?: string
  /** What the server put on the item for `completionItem/resolve`, sent back as is. */
  data?: Record<string, unknown>
}

interface LspHover {
  contents: unknown
  range?: LspRange
}

/** One inlay hint as the server sends it (LSP 3.17 `InlayHint`, string labels only). */
export interface LspInlayHint {
  position: LspPosition
  label: string
  kind?: number
  paddingLeft?: boolean
  paddingRight?: boolean
}

/**
 * The names a semantic token's integers index into (LSP `SemanticTokensLegend`),
 * as the server sent them in `initialize`. Tokens are decoded against these
 * names, never against a list kept here: the server owns the order.
 */
export interface SemanticLegend {
  types: string[]
  modifiers: string[]
}

/** One decoded semantic token: a span of the text and its legend names. */
export interface SemanticToken {
  from: number
  to: number
  type: string
  modifiers: string[]
}

interface LspLocation {
  uri: string
  range: LspRange
}

interface LspLocationLink {
  targetUri: string
  targetSelectionRange?: LspRange
  targetRange: LspRange
}

interface RpcPending {
  resolve: (value: unknown) => void
  reject: (reason: Error) => void
  timer: ReturnType<typeof setTimeout>
}

interface SyncWaiter {
  generation: number
  resolve: () => void
  reject: (reason: Error) => void
  timer: ReturnType<typeof setTimeout>
}

interface SyncFlight {
  generation: number
  text: string
  version: number
}

export interface LspSocket {
  readonly readyState: number
  readonly protocol: string
  onopen: (() => void) | null
  onmessage: ((event: { data: unknown }) => void) | null
  onerror: (() => void) | null
  onclose: (() => void) | null
  send(data: string): void
  close(code?: number, reason?: string): void
}

export type LspSocketFactory = (url: string, protocol: string) => LspSocket

const SOCKET_OPEN = 1
const CONNECT_TIMEOUT_MS = 3000
const INITIALIZE_TIMEOUT_MS = 3000
const DIAGNOSTICS_TIMEOUT_MS = 3000
// How long a connection must stay ready before it earns the reconnect budget
// back. The budget is one jittered reconnect (docs/playground-lsp-design.md);
// what it may not be is one reconnect per round-trip, which is what refilling
// it on every published diagnostic gave: a gateway that dropped every session
// right after its first diagnostics turned into an unbounded connect loop.
// The gateway retires sessions on its own lifetime ceiling, so the budget has
// to come back eventually, and this is the earliest that is still bounded.
const RECONNECT_BUDGET_MS = 60000

function asRecord(value: unknown): Record<string, any> | null {
  return value != null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, any>
    : null
}

function errorOf(reason: unknown): Error {
  return reason instanceof Error ? reason : new Error(String(reason))
}

function positionOf(value: unknown): LspPosition | null {
  const position = asRecord(value)
  return Number.isInteger(position?.line) && position!.line >= 0
    && Number.isInteger(position?.character) && position!.character >= 0
    ? { line: position!.line, character: position!.character }
    : null
}

function rangeOf(value: unknown): LspRange | null {
  const range = asRecord(value)
  const start = positionOf(range?.start)
  const end = positionOf(range?.end)
  return start != null && end != null ? { start, end } : null
}

function diagnosticOf(value: unknown): LspDiagnostic | null {
  const diagnostic = asRecord(value)
  const range = rangeOf(diagnostic?.range)
  if (range == null || typeof diagnostic?.message !== 'string') return null
  return {
    range,
    message: diagnostic.message,
    ...(typeof diagnostic.severity === 'number' ? { severity: diagnostic.severity } : {}),
    ...(typeof diagnostic.source === 'string' ? { source: diagnostic.source } : {}),
    ...(typeof diagnostic.code === 'string' || typeof diagnostic.code === 'number'
      ? { code: diagnostic.code }
      : {}),
  }
}

export function inlayHintOf(value: unknown): LspInlayHint | null {
  const hint = asRecord(value)
  const position = positionOf(hint?.position)
  if (hint == null || position == null || typeof hint.label !== 'string' || !hint.label) return null
  return {
    position,
    label: hint.label,
    ...(typeof hint.kind === 'number' ? { kind: hint.kind } : {}),
    ...(hint.paddingLeft === true ? { paddingLeft: true } : {}),
    ...(hint.paddingRight === true ? { paddingRight: true } : {}),
  }
}

/**
 * The legend of an `initialize` result's capabilities, or null when the
 * server offers no semantic tokens for a range (docs/lsp-references-design.md
 * §T2). A name becomes a CSS class, so only plain letters are taken.
 */
export function semanticLegendOf(capabilities: unknown): SemanticLegend | null {
  const provider = asRecord(asRecord(capabilities)?.semanticTokensProvider)
  const legend = asRecord(provider?.legend)
  if (provider?.range !== true || legend == null) return null
  const names = (value: unknown): string[] | null =>
    Array.isArray(value) && value.every((name) => typeof name === 'string' && /^[A-Za-z]+$/.test(name))
      ? value as string[]
      : null
  const types = names(legend.tokenTypes)
  const modifiers = names(legend.tokenModifiers)
  return types != null && types.length > 0 && modifiers != null ? { types, modifiers } : null
}

/**
 * LSP's relative encoding (five integers per token: line delta, start delta,
 * length, type index, modifier bits) decoded over `text`. Columns are UTF-16
 * code units, which are JavaScript string offsets, so only lines need
 * walking. A token whose type is not in the legend, that runs past its line,
 * or that lies past the text is dropped rather than drawn somewhere else.
 */
export function decodeSemanticTokens(
  data: readonly number[],
  legend: SemanticLegend,
  text: string,
): SemanticToken[] {
  const tokens: SemanticToken[] = []
  let line = 0
  let lineStart = 0
  let character = 0
  for (let i = 0; i + 4 < data.length; i += 5) {
    const [deltaLine, deltaStart, length, type, bits] = data.slice(i, i + 5)
    if (deltaLine > 0) {
      for (let n = 0; n < deltaLine; n++) {
        const newline = text.indexOf('\n', lineStart)
        if (newline < 0) return tokens
        lineStart = newline + 1
      }
      line += deltaLine
      character = deltaStart
    } else {
      character += deltaStart
    }
    const lineEnd = text.indexOf('\n', lineStart)
    const end = lineEnd < 0 ? text.length : lineEnd
    const from = lineStart + character
    const to = from + length
    const name = legend.types[type]
    if (name == null || length <= 0 || to > end) continue
    tokens.push({
      from,
      to,
      type: name,
      modifiers: legend.modifiers.filter((_, bit) => (bits & (1 << bit)) !== 0),
    })
  }
  return tokens
}

function completionItemOf(value: unknown): LspCompletionItem | null {
  const item = asRecord(value)
  if (typeof item?.label !== 'string') return null
  return {
    label: item.label,
    ...(typeof item.kind === 'number' ? { kind: item.kind } : {}),
    ...(typeof item.detail === 'string' ? { detail: item.detail } : {}),
    ...(typeof item.sortText === 'string' ? { sortText: item.sortText } : {}),
    ...(typeof item.insertText === 'string' ? { insertText: item.insertText } : {}),
    ...(asRecord(item.data) != null ? { data: item.data } : {}),
  }
}

/** A `MarkupContent` or bare string's text; '' for anything else. */
function markupValue(value: unknown): string {
  if (typeof value === 'string') return value
  const record = asRecord(value)
  return typeof record?.value === 'string' ? record.value : ''
}

export function lspWebSocketUrl(endpoint: string, baseHref: string): string {
  const url = new URL(endpoint, baseHref)
  if (url.protocol === 'https:') url.protocol = 'wss:'
  else if (url.protocol === 'http:') url.protocol = 'ws:'
  else if (url.protocol !== 'ws:' && url.protocol !== 'wss:') {
    throw new Error(`unsupported LSP endpoint protocol: ${url.protocol}`)
  }
  return url.toString()
}

// JavaScript string offsets and LSP UTF-16 character offsets use the same
// code units. Only line boundaries need translating.
export function offsetToLspPosition(text: string, offset: number): LspPosition {
  const end = Math.max(0, Math.min(offset, text.length))
  let line = 0
  let lineStart = 0
  for (let i = 0; i < end; i++) {
    if (text.charCodeAt(i) === 10) {
      line++
      lineStart = i + 1
    }
  }
  return { line, character: end - lineStart }
}

export function lspPositionToOffset(text: string, position: LspPosition): number {
  const wantedLine = Number.isFinite(position.line) ? Math.max(0, Math.trunc(position.line)) : 0
  const wantedCharacter = Number.isFinite(position.character)
    ? Math.max(0, Math.trunc(position.character))
    : 0
  let line = 0
  let start = 0
  while (line < wantedLine) {
    const newline = text.indexOf('\n', start)
    if (newline < 0) return text.length
    start = newline + 1
    line++
  }
  const newline = text.indexOf('\n', start)
  const end = newline < 0 ? text.length : newline
  return Math.min(start + wantedCharacter, end)
}

function diagnosticSeverity(value: number | undefined): Diagnostic['severity'] {
  if (value === 2) return 'warning'
  if (value === 3) return 'info'
  if (value === 4) return 'hint'
  return 'error'
}

export function lspDiagnostics(
  diagnostics: readonly LspDiagnostic[],
  text: string,
): Diagnostic[] {
  return diagnostics.flatMap((diagnostic) => {
    const safe = diagnosticOf(diagnostic)
    if (safe == null) return []
    const from = lspPositionToOffset(text, safe.range.start)
    const end = lspPositionToOffset(text, safe.range.end)
    return [{
      from,
      to: Math.max(from, end),
      severity: diagnosticSeverity(safe.severity),
      message: safe.message,
      ...(safe.source != null ? { source: safe.source } : {}),
    }]
  })
}

export class DawnLspClient {
  private readonly socketFactory: LspSocketFactory
  private readonly reconnectDelay: () => number
  private socket: LspSocket | null = null
  private connection = 0
  private stopped = false
  private retryCount = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private connectTimer: ReturnType<typeof setTimeout> | null = null
  private nextId = 1
  private pending = new Map<number, RpcPending>()
  private queryEpoch = new Map<string, number>()
  private syncWaiters: SyncWaiter[] = []
  private diagnosticTimer: ReturnType<typeof setTimeout> | null = null
  private readyAt = 0
  private opened = false
  private version = 0
  private generation = 0
  private diagnosedGeneration = -1
  private text = ''
  private legend: SemanticLegend | null = null
  private inFlight: SyncFlight | null = null
  private statusValue: LspStatus = 'fallback'
  private readonly statusListeners = new Set<(status: LspStatus) => void>()
  private readonly diagnosticsListeners = new Set<(event: LspDiagnosticsEvent) => void>()

  constructor(
    readonly url: string,
    socketFactory: LspSocketFactory = (target, protocol) => (
      new WebSocket(target, protocol) as unknown as LspSocket
    ),
    reconnectDelay: () => number = () => 250 + Math.floor(Math.random() * 500),
    private readonly connectTimeoutMs: number = CONNECT_TIMEOUT_MS,
    private readonly reconnectBudgetMs: number = RECONNECT_BUDGET_MS,
  ) {
    this.socketFactory = socketFactory
    this.reconnectDelay = reconnectDelay
  }

  get status(): LspStatus {
    return this.statusValue
  }

  isReady(): boolean {
    return this.statusValue === 'ready'
  }

  /** The semantic tokens legend this connection's server offered, if any. */
  get semanticLegend(): SemanticLegend | null {
    return this.legend
  }

  onStatus(listener: (status: LspStatus) => void): () => void {
    this.statusListeners.add(listener)
    listener(this.statusValue)
    return () => this.statusListeners.delete(listener)
  }

  onDiagnostics(listener: (event: LspDiagnosticsEvent) => void): () => void {
    this.diagnosticsListeners.add(listener)
    return () => this.diagnosticsListeners.delete(listener)
  }

  start(initialText: string): void {
    if (this.stopped || this.connection !== 0) return
    this.text = initialText
    this.generation = 1
    this.connect()
  }

  update(text: string): void {
    if (text === this.text) return
    this.text = text
    this.generation++
    this.rejectStaleSyncWaiters()
    if (this.isReady() && this.inFlight == null) this.sendLatestText()
  }

  stop(): void {
    this.stopped = true
    if (this.reconnectTimer != null) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.abandon(this.connection, new Error('LSP client stopped'), false)
  }

  async completion(offset: number, timeoutMs = 750): Promise<LspCompletionItem[]> {
    const value = await this.query('textDocument/completion', offset, timeoutMs)
    if (Array.isArray(value)) {
      return value.map(completionItemOf).filter((item): item is LspCompletionItem => item != null)
    }
    const record = asRecord(value)
    if (!Array.isArray(record?.items)) return []
    // LSP 3.17 list defaults: the server names the document once
    // (docs/lsp-hover-design.md §D7.2), and an item without data of its own
    // takes it
    const data = asRecord(asRecord(record.itemDefaults)?.data)
    return record.items.map(completionItemOf)
      .filter((item: LspCompletionItem | null): item is LspCompletionItem => item != null)
      .map((item: LspCompletionItem) => item.data == null && data != null ? { ...item, data } : item)
  }

  /**
   * A completion item's doc, as the server's Markdown, or '' when it has none
   * (docs/lsp-hover-design.md §D7). Asked for when the list shows the item,
   * never with the list: the server reads a doc only for the item a reader
   * stops on. The item goes back with only what the server reads.
   */
  async completionDoc(item: LspCompletionItem, timeoutMs = 1000): Promise<string> {
    const value = await this.queryWith('completionItem/resolve', () => ({
      label: item.label,
      ...(item.kind != null ? { kind: item.kind } : {}),
      ...(item.data != null ? { data: item.data } : {}),
    }), timeoutMs)
    return markupValue(asRecord(value)?.documentation)
  }

  async hover(offset: number, timeoutMs = 1000): Promise<LspHover | null> {
    const value = await this.query('textDocument/hover', offset, timeoutMs)
    const hover = asRecord(value)
    if (hover == null) return null
    const range = rangeOf(hover.range)
    return { contents: hover.contents, ...(range != null ? { range } : {}) }
  }

  async definition(
    offset: number,
    timeoutMs = 1000,
  ): Promise<(LspLocation | LspLocationLink)[]> {
    const value = await this.query('textDocument/definition', offset, timeoutMs)
    if (Array.isArray(value)) {
      return value.filter((item) => asRecord(item)) as (LspLocation | LspLocationLink)[]
    }
    return asRecord(value) ? [value as LspLocation | LspLocationLink] : []
  }

  /** The hints between two offsets of the current text, both ends included. */
  async inlayHints(from: number, to: number, timeoutMs = 1500): Promise<LspInlayHint[]> {
    const value = await this.queryWith('textDocument/inlayHint', (text) => ({
      textDocument: { uri: DAWN_LSP_URI },
      range: { start: offsetToLspPosition(text, from), end: offsetToLspPosition(text, to) },
    }), timeoutMs)
    return Array.isArray(value)
      ? value.map(inlayHintOf).filter((hint): hint is LspInlayHint => hint != null)
      : []
  }

  /**
   * The semantic tokens whose names start between two offsets of the current
   * text, or none when the server offers no legend. A name that starts in the
   * range and ends past it is included whole.
   */
  async semanticTokens(from: number, to: number, timeoutMs = 1500): Promise<SemanticToken[]> {
    const legend = this.legend
    if (legend == null) return []
    let text = ''
    const value = await this.queryWith('textDocument/semanticTokens/range', (current) => {
      text = current
      return {
        textDocument: { uri: DAWN_LSP_URI },
        range: { start: offsetToLspPosition(current, from), end: offsetToLspPosition(current, to) },
      }
    }, timeoutMs)
    const data = asRecord(value)?.data
    if (!Array.isArray(data) || !data.every((n) => Number.isInteger(n) && n >= 0)) return []
    return decodeSemanticTokens(data, legend, text)
  }

  private setStatus(status: LspStatus): void {
    if (status === this.statusValue) return
    this.statusValue = status
    for (const listener of this.statusListeners) listener(status)
  }

  private connect(): void {
    if (this.stopped) return
    if (this.reconnectTimer != null) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.setStatus('connecting')
    const connection = ++this.connection
    let socket: LspSocket
    try {
      socket = this.socketFactory(this.url, DAWN_LSP_PROTOCOL)
    } catch (reason) {
      this.abandon(connection, errorOf(reason), true)
      return
    }
    this.socket = socket
    this.clearConnectTimer()
    this.connectTimer = setTimeout(() => {
      this.abandon(connection, new Error('LSP WebSocket handshake timed out'), true)
    }, this.connectTimeoutMs)
    socket.onopen = () => {
      if (!this.isCurrent(connection, socket)) return
      this.clearConnectTimer()
      if (socket.protocol !== DAWN_LSP_PROTOCOL) {
        this.abandon(connection, new Error('LSP subprotocol was not negotiated'), true)
        return
      }
      this.requestRaw('initialize', {
        processId: null,
        clientInfo: { name: 'dawn-playground' },
        rootUri: null,
        workspaceFolders: null,
        capabilities: {
          textDocument: {
            hover: { contentFormat: ['markdown', 'plaintext'] },
            inlayHint: { dynamicRegistration: false },
            semanticTokens: {
              dynamicRegistration: false,
              requests: { range: true, full: false },
              tokenTypes: [],
              tokenModifiers: [],
              formats: ['relative'],
            },
            completion: {
              completionItem: {
                snippetSupport: false,
                documentationFormat: ['markdown', 'plaintext'],
                resolveSupport: { properties: ['documentation'] },
              },
              completionList: { itemDefaults: ['data'] },
            },
          },
        },
      }, INITIALIZE_TIMEOUT_MS).then((result) => {
        if (!this.isCurrent(connection, socket)) return
        this.legend = semanticLegendOf(asRecord(result)?.capabilities)
        this.notify('initialized', {})
        this.opened = false
        this.version = 0
        this.inFlight = null
        this.diagnosedGeneration = -1
        this.readyAt = Date.now()
        this.setStatus('ready')
        this.sendLatestText()
      }).catch((reason) => {
        this.abandon(connection, errorOf(reason), true)
      })
    }
    socket.onmessage = (event) => {
      if (this.isCurrent(connection, socket)) this.receive(connection, event.data)
    }
    socket.onerror = () => {
      this.abandon(connection, new Error('LSP WebSocket failed'), true)
    }
    socket.onclose = () => {
      this.abandon(connection, new Error('LSP WebSocket closed'), true)
    }
  }

  private isCurrent(connection: number, socket: LspSocket): boolean {
    return !this.stopped && connection === this.connection && socket === this.socket
  }

  private abandon(connection: number, reason: Error, retry: boolean): void {
    if (connection !== this.connection) return
    const socket = this.socket
    this.socket = null
    this.connection++
    this.clearConnectTimer()
    if (socket != null && socket.readyState <= SOCKET_OPEN) {
      try { socket.close(1000, 'fallback') } catch { /* already closed */ }
    }
    this.clearDiagnosticTimer()
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer)
      pending.reject(reason)
    }
    this.pending.clear()
    for (const waiter of this.syncWaiters) {
      clearTimeout(waiter.timer)
      waiter.reject(reason)
    }
    this.syncWaiters = []
    this.inFlight = null
    this.opened = false
    this.legend = null
    // -1, not 0: a connection that never reached ready earns nothing back
    // even where the threshold itself is zero.
    const readyFor = this.readyAt === 0 ? -1 : Date.now() - this.readyAt
    this.readyAt = 0
    this.setStatus('fallback')
    if (!retry || this.stopped) return
    // A connection that carried a whole session before dropping earns the
    // budget back; one that dropped sooner spends what is left of it.
    if (readyFor >= this.reconnectBudgetMs) this.retryCount = 0
    if (this.retryCount < 1) {
      this.retryCount++
      this.reconnectTimer = setTimeout(() => this.connect(), this.reconnectDelay())
    }
  }

  private send(message: Record<string, unknown>): void {
    if (this.socket == null || this.socket.readyState !== SOCKET_OPEN) {
      throw new Error('LSP WebSocket is not open')
    }
    this.socket.send(JSON.stringify({ jsonrpc: '2.0', ...message }))
  }

  private notify(method: string, params: unknown): void {
    this.send({ method, params })
  }

  private requestRaw(method: string, params: unknown, timeoutMs: number): Promise<unknown> {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`${method} timed out`))
      }, timeoutMs)
      this.pending.set(id, { resolve, reject, timer })
      try {
        this.send({ id, method, params })
      } catch (reason) {
        clearTimeout(timer)
        this.pending.delete(id)
        reject(errorOf(reason))
      }
    })
  }

  private receive(connection: number, data: unknown): void {
    if (typeof data !== 'string') {
      this.abandon(connection, new Error('LSP gateway sent a non-text message'), false)
      return
    }
    let value: unknown
    try {
      value = JSON.parse(data)
    } catch {
      this.abandon(connection, new Error('LSP gateway sent malformed JSON'), false)
      return
    }
    const message = asRecord(value)
    if (message == null || message.jsonrpc !== '2.0') {
      this.abandon(connection, new Error('LSP gateway sent an invalid JSON-RPC message'), false)
      return
    }
    if (message.method === 'textDocument/publishDiagnostics') {
      this.receiveDiagnostics(message.params)
      return
    }
    if (typeof message.id !== 'number') return
    const pending = this.pending.get(message.id)
    if (pending == null) return
    this.pending.delete(message.id)
    clearTimeout(pending.timer)
    if (message.error != null) {
      const rpcError = asRecord(message.error)
      pending.reject(new Error(String(rpcError?.message ?? 'LSP request failed')))
    } else {
      pending.resolve(message.result)
    }
  }

  private sendLatestText(): void {
    if (!this.isReady() || this.inFlight != null) return
    this.version++
    const flight = { generation: this.generation, text: this.text, version: this.version }
    this.inFlight = flight
    try {
      if (!this.opened) {
        this.opened = true
        this.notify('textDocument/didOpen', {
          textDocument: {
            uri: DAWN_LSP_URI,
            languageId: 'dawn',
            version: this.version,
            text: flight.text,
          },
        })
      } else {
        this.notify('textDocument/didChange', {
          textDocument: { uri: DAWN_LSP_URI, version: this.version },
          contentChanges: [{ text: flight.text }],
        })
      }
      this.clearDiagnosticTimer()
      const connection = this.connection
      this.diagnosticTimer = setTimeout(() => {
        this.abandon(connection, new Error('LSP diagnostics timed out'), false)
      }, DIAGNOSTICS_TIMEOUT_MS)
    } catch (reason) {
      this.abandon(this.connection, errorOf(reason), true)
    }
  }

  private receiveDiagnostics(paramsValue: unknown): void {
    const params = asRecord(paramsValue)
    if (params?.uri !== DAWN_LSP_URI || this.inFlight == null) return
    const flight = this.inFlight
    // Diagnostics are paired to the in-flight sync by arrival order, so a
    // second publish for an already-answered version would be read as the
    // answer to the next one and show the previous buffer's errors against
    // the current text. When the notification carries a version, that is
    // decidable: anything but the in-flight version is stale, and dropping it
    // leaves the sync outstanding for its own timeout rather than closing it
    // with the wrong answer. Servers that omit the version keep the old
    // positional pairing; there is nothing better to do with it.
    if (typeof params.version === 'number' && params.version !== flight.version) return
    this.inFlight = null
    this.clearDiagnosticTimer()
    this.diagnosedGeneration = flight.generation
    const diagnostics = Array.isArray(params.diagnostics)
      ? params.diagnostics.map(diagnosticOf)
        .filter((item: LspDiagnostic | null): item is LspDiagnostic => item != null)
      : []
    if (flight.generation === this.generation && flight.text === this.text) {
      const event = { ...flight, diagnostics }
      for (const listener of this.diagnosticsListeners) listener(event)
      this.resolveSyncWaiters(flight.generation)
    } else {
      this.rejectStaleSyncWaiters()
    }
    if (this.generation !== flight.generation) this.sendLatestText()
  }

  private clearDiagnosticTimer(): void {
    if (this.diagnosticTimer != null) clearTimeout(this.diagnosticTimer)
    this.diagnosticTimer = null
  }

  private clearConnectTimer(): void {
    if (this.connectTimer != null) clearTimeout(this.connectTimer)
    this.connectTimer = null
  }

  private waitForSync(generation: number, timeoutMs: number): Promise<void> {
    if (!this.isReady()) return Promise.reject(new Error('LSP is unavailable'))
    if (generation === this.diagnosedGeneration && generation === this.generation) {
      return Promise.resolve()
    }
    return new Promise((resolve, reject) => {
      const waiter: SyncWaiter = {
        generation,
        resolve,
        reject,
        timer: setTimeout(() => {
          this.syncWaiters = this.syncWaiters.filter((entry) => entry !== waiter)
          reject(new Error('LSP sync timed out'))
        }, timeoutMs),
      }
      this.syncWaiters.push(waiter)
    })
  }

  private resolveSyncWaiters(generation: number): void {
    const keep: SyncWaiter[] = []
    for (const waiter of this.syncWaiters) {
      if (waiter.generation === generation) {
        clearTimeout(waiter.timer)
        waiter.resolve()
      } else {
        keep.push(waiter)
      }
    }
    this.syncWaiters = keep
  }

  private rejectStaleSyncWaiters(): void {
    const keep: SyncWaiter[] = []
    for (const waiter of this.syncWaiters) {
      if (waiter.generation !== this.generation) {
        clearTimeout(waiter.timer)
        waiter.reject(new Error('stale LSP request'))
      } else {
        keep.push(waiter)
      }
    }
    this.syncWaiters = keep
  }

  private query(method: string, offset: number, timeoutMs: number): Promise<unknown> {
    return this.queryWith(method, (text) => ({
      textDocument: { uri: DAWN_LSP_URI },
      position: offsetToLspPosition(text, offset),
    }), timeoutMs)
  }

  /**
   * A request about the text as it is now: sent once the server has analysed
   * that text, and dropped (rejected as stale) when the text changed or a newer
   * request of the same method was made before the answer came.
   */
  private async queryWith(
    method: string,
    params: (text: string) => unknown,
    timeoutMs: number,
  ): Promise<unknown> {
    if (!this.isReady()) throw new Error('LSP is unavailable')
    const epoch = (this.queryEpoch.get(method) ?? 0) + 1
    this.queryEpoch.set(method, epoch)
    const generation = this.generation
    const text = this.text
    const started = Date.now()
    await this.waitForSync(generation, timeoutMs)
    if (generation !== this.generation || text !== this.text
      || epoch !== this.queryEpoch.get(method)) throw new Error('stale LSP request')
    const remaining = timeoutMs - (Date.now() - started)
    if (remaining <= 0) throw new Error(`${method} timed out`)
    const result = await this.requestRaw(method, params(text), remaining)
    if (generation !== this.generation || text !== this.text
      || epoch !== this.queryEpoch.get(method)) throw new Error('stale LSP response')
    return result
  }
}

function completionType(kind: number | undefined): string {
  const types: Record<number, string> = {
    2: 'method', 3: 'function', 4: 'function', 5: 'property', 6: 'variable',
    7: 'class', 8: 'interface', 9: 'namespace', 10: 'property', 13: 'enum',
    14: 'keyword', 20: 'variable', 21: 'constant', 22: 'type', 25: 'type',
  }
  return kind == null ? 'text' : types[kind] ?? 'text'
}

/**
 * An item with `data` may have a doc, and its `info` fetches it when the list
 * selects it; an item without has none to fetch and shows no info pane.
 */
export function completionOf(item: LspCompletionItem, client?: DawnLspClient): Completion | null {
  if (typeof item.label !== 'string' || item.label.length === 0) return null
  return {
    label: item.label,
    type: completionType(item.kind),
    boost: 3,
    ...(typeof item.sortText === 'string' ? { sortText: item.sortText } : {}),
    ...(typeof item.insertText === 'string' ? { apply: item.insertText } : {}),
    ...(typeof item.detail === 'string' ? { detail: item.detail } : {}),
    ...(client != null && item.data != null ? { info: () => completionInfo(client, item) } : {}),
  }
}

/** The text the info pane shows for a resolved doc: hover's (`docText`). */
export function completionInfoText(markdown: string): string {
  return docText(markdown)
}

/**
 * The info pane beside the completion list: the item's doc, as hover shows
 * one (`docText`, then `docNode`), or nothing when it has none or the
 * question went stale.
 */
export async function completionInfo(
  client: DawnLspClient,
  item: LspCompletionItem,
): Promise<HTMLElement | null> {
  try {
    const doc = completionInfoText(await client.completionDoc(item, 1000))
    return doc ? docNode(doc, 'dp-completion-doc') : null
  } catch {
    return null
  }
}

export function mergeCompletionResults(
  server: readonly Completion[],
  fallback: CompletionResult,
): CompletionResult {
  const seen = new Set<string>()
  const options: Completion[] = []
  for (const option of [...server, ...fallback.options]) {
    if (seen.has(option.label)) continue
    seen.add(option.label)
    options.push(option)
  }
  return { ...fallback, options }
}

export function lspCompletionSource(
  client: DawnLspClient,
  fallback: CompletionSource,
): CompletionSource {
  return async (context: CompletionContext): Promise<CompletionResult | null> => {
    const staticResult = await fallback(context)
    const word = context.matchBefore(/[A-Za-z_][A-Za-z0-9_]*/)
    const line = context.state.doc.lineAt(context.pos)
    const before = context.state.sliceDoc(line.from, context.pos)
    const shouldAsk = staticResult != null || context.explicit || word != null || /\S$/.test(before)
    if (!shouldAsk || !client.isReady()) return staticResult
    try {
      const items = await client.completion(context.pos, 750)
      const server = items.map((item) => completionOf(item, client))
        .filter((item): item is Completion => item != null)
      if (server.length === 0) return staticResult
      const base = staticResult ?? {
        from: word?.from ?? context.pos,
        options: [],
        validFor: /^[A-Za-z0-9_]*$/,
      }
      return mergeCompletionResults(server, base)
    } catch {
      return staticResult
    }
  }
}

/**
 * A hover reply split into what the tooltip shows: the code of its first
 * ```dawn fence, and the `##` doc the server puts after a `---` rule
 * (docs/lsp-hover-design.md §A3). A reply without a fence is all code, as a
 * plain-text server sends it. The doc is the comment's own markdown; the
 * tooltip shows it as text, so its fence lines are dropped (their contents
 * kept) and nothing of the markup but inline `code` survives as written.
 */
export interface HoverParts {
  code: string
  doc: string
}

export function hoverParts(contents: unknown): HoverParts {
  const values = Array.isArray(contents) ? contents : [contents]
  const text = values.flatMap((value) => {
    if (typeof value === 'string') return [value]
    const record = asRecord(value)
    return typeof record?.value === 'string' ? [record.value] : []
  }).join('\n\n').trim()
  const fenced = /^```(?:dawn)?[ \t]*\n([\s\S]*?)\n```[ \t]*(?:\n([\s\S]*))?$/.exec(text)
  if (!fenced) return { code: text, doc: '' }
  const rest = (fenced[2] ?? '').trim().replace(/^-{3,}[ \t]*(?:\n|$)/, '')
  return { code: fenced[1], doc: docText(rest) }
}

/**
 * The doc as plain text: fence lines and horizontal rules go, and a Markdown
 * link keeps its label and loses its target. The server turns a doc's
 * [`name`] links into `file://` links to the declaration
 * (docs/lsp-hover-design.md §A5), which name paths on the Playground's
 * server: nothing a browser tab can open, and not something to show.
 *
 * A link the server left as written loses its brackets too. That is every
 * link in a std doc on the Playground: the std there is the copy compiled
 * into the toolchain, which has no file to point at, so the server keeps the
 * `` [`name`] `` it was given and the tooltip showed the brackets.
 */
function docText(markdown: string): string {
  return markdown
    .split('\n')
    .filter((line) => !/^\s*```/.test(line) && !/^\s*-{3,}\s*$/.test(line))
    .join('\n')
    .replace(/\[(`[^`\n]+`)\]\([^)\s]*\)/g, '$1')
    .replace(/\[(`[^`\n]+`)\](?!\()/g, '$1')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/** The tooltip's text: the code, then the doc after a blank line. */
export function hoverText(contents: unknown): string {
  const { code, doc } = hoverParts(contents)
  return doc ? `${code}\n\n${doc}` : code
}

/** The doc's text with each inline `code` span as a <code> element. */
function docNode(doc: string, className = 'dp-hover-doc'): HTMLElement {
  const node = document.createElement('div')
  node.className = className
  doc.split(/(`[^`\n]+`)/).forEach((piece) => {
    if (/^`[^`\n]+`$/.test(piece)) {
      const code = document.createElement('code')
      code.textContent = piece.slice(1, -1)
      node.appendChild(code)
    } else if (piece) {
      node.appendChild(document.createTextNode(piece))
    }
  })
  return node
}

export function lspHover(client: DawnLspClient): Extension {
  return hoverTooltip(async (view, offset) => {
    if (!client.isReady()) return null
    const snapshot = view.state.doc.toString()
    try {
      const hover = await client.hover(offset, 1000)
      if (hover == null || view.state.doc.toString() !== snapshot) return null
      const parts = hoverParts(hover.contents)
      if (!hoverText(hover.contents).trim()) return null
      const from = hover.range ? lspPositionToOffset(snapshot, hover.range.start) : offset
      const to = hover.range ? lspPositionToOffset(snapshot, hover.range.end) : offset
      return {
        pos: from,
        end: Math.max(from, to),
        above: true,
        create: () => {
          const dom = document.createElement('div')
          dom.className = 'dp-hover'
          const code = document.createElement('div')
          code.className = 'dp-hover-code'
          code.textContent = parts.code.trim()
          dom.appendChild(code)
          if (parts.doc) dom.appendChild(docNode(parts.doc))
          return { dom }
        },
      }
    } catch {
      return null
    }
  }, { hoverTime: 350 })
}

function localLocation(
  value: LspLocation | LspLocationLink,
): { uri: string; range: LspRange } | null {
  const record = asRecord(value)
  if (record == null) return null
  const targetRange = rangeOf(record.targetSelectionRange) ?? rangeOf(record.targetRange)
  if (typeof record.targetUri === 'string' && targetRange != null) {
    return { uri: record.targetUri, range: targetRange }
  }
  const range = rangeOf(record.range)
  return typeof record.uri === 'string' && range != null
    ? { uri: record.uri, range }
    : null
}

async function moveToDefinition(
  client: DawnLspClient,
  view: EditorView,
  offset: number,
): Promise<void> {
  const snapshot = view.state.doc.toString()
  try {
    const definitions = await client.definition(offset, 1000)
    if (view.state.doc.toString() !== snapshot) return
    const location = definitions.map(localLocation)
      .find((item) => item?.uri === DAWN_LSP_URI)
    if (location == null) return
    const from = lspPositionToOffset(snapshot, location.range.start)
    const to = lspPositionToOffset(snapshot, location.range.end)
    view.dispatch({
      selection: { anchor: from, head: Math.max(from, to) },
      scrollIntoView: true,
    })
    view.focus()
  } catch {
    // Definition is optional; unavailable LSP leaves ordinary cursor behavior.
  }
}

export function goToLspDefinition(client: DawnLspClient, view: EditorView): boolean {
  if (client.isReady()) {
    void moveToDefinition(client, view, view.state.selection.main.head)
  }
  return true
}

export function lspDefinition(client: DawnLspClient): Extension {
  return EditorView.domEventHandlers({
    mousedown(event, view) {
      if (event.button !== 0 || (!event.metaKey && !event.ctrlKey) || !client.isReady()) {
        return false
      }
      const offset = view.posAtCoords({ x: event.clientX, y: event.clientY })
      if (offset == null) return false
      event.preventDefault()
      void moveToDefinition(client, view, offset)
      return true
    },
  })
}

/**
 * Inlay hints (docs/lsp-hover-design.md §A4): the server's `: Int` after an
 * unannotated binding and `!Fs` after an effectful call, drawn as widgets in
 * the line. Only the visible part of the document is asked for, after edits
 * and scrolling have been quiet for INLAY_DEBOUNCE_MS; while a request is out,
 * the hints already shown move with the edits rather than vanishing, so a line
 * does not shift twice for one keystroke.
 */
const INLAY_DEBOUNCE_MS = 300

class InlayWidget extends WidgetType {
  constructor(readonly hint: LspInlayHint) { super() }

  eq(other: InlayWidget): boolean {
    return other.hint.label === this.hint.label
      && other.hint.kind === this.hint.kind
      && other.hint.paddingLeft === this.hint.paddingLeft
      && other.hint.paddingRight === this.hint.paddingRight
  }

  toDOM(): HTMLElement {
    const node = document.createElement('span')
    node.className = inlayClass(this.hint)
    node.textContent = this.hint.label
    return node
  }

  ignoreEvent(): boolean { return true }
}

/** The widget's class list: the kind (type 1, parameter 2) and the padding. */
export function inlayClass(hint: LspInlayHint): string {
  return [
    'dp-inlay',
    hint.kind === 2 ? 'dp-inlay-param' : 'dp-inlay-type',
    ...(hint.paddingLeft ? ['dp-inlay-pl'] : []),
    ...(hint.paddingRight ? ['dp-inlay-pr'] : []),
  ].join(' ')
}

/** Hints as decorations over `text`, in document order; out-of-range ones are dropped. */
export function inlayDecorations(hints: readonly LspInlayHint[], text: string): DecorationSet {
  const ranges: Range<Decoration>[] = []
  for (const hint of hints) {
    const at = lspPositionToOffset(text, hint.position)
    if (at < 0 || at > text.length) continue
    // side 1: the hint sits after whatever ends at its position, so a cursor
    // at the end of `xs` stays before the `: List[Int]` drawn there
    ranges.push(Decoration.widget({ widget: new InlayWidget(hint), side: 1 }).range(at))
  }
  return Decoration.set(ranges, true)
}

export function lspInlayHints(client: DawnLspClient): Extension {
  return ViewPlugin.fromClass(class {
    decorations: DecorationSet = Decoration.none
    private timer: ReturnType<typeof setTimeout> | null = null
    private unsubscribe: () => void

    constructor(readonly view: EditorView) {
      this.unsubscribe = client.onStatus((status) => {
        if (status === 'ready') this.schedule()
        else if (status === 'fallback' && this.decorations.size > 0) {
          this.decorations = Decoration.none
          this.view.dispatch({})
        }
      })
    }

    update(update: ViewUpdate): void {
      if (update.docChanged) this.decorations = this.decorations.map(update.changes)
      if (update.docChanged || update.viewportChanged) this.schedule()
    }

    schedule(): void {
      if (this.timer != null) clearTimeout(this.timer)
      this.timer = setTimeout(() => {
        this.timer = null
        void this.refresh()
      }, INLAY_DEBOUNCE_MS)
    }

    async refresh(): Promise<void> {
      if (!client.isReady()) return
      const view = this.view
      const snapshot = view.state.doc.toString()
      const { from, to } = view.viewport
      try {
        const hints = await client.inlayHints(from, to)
        if (view.state.doc.toString() !== snapshot) return
        this.decorations = inlayDecorations(hints, snapshot)
        view.dispatch({})
      } catch {
        // stale or unavailable: the next edit or scroll asks again
      }
    }

    destroy(): void {
      if (this.timer != null) clearTimeout(this.timer)
      this.unsubscribe()
    }
  }, { decorations: (plugin) => plugin.decorations })
}

/**
 * Semantic tokens (docs/lsp-references-design.md §T2): the server's kind for
 * each name on screen, drawn as a class over the grammar's colour. Only names
 * come back; keywords, literals and comments keep the stream tokenizer's
 * classes, and with no tokens (no legend, no analysis yet, the gateway
 * unreachable) the grammar's colours are all there is. Asked for the visible
 * part of the document once edits and scrolling are quiet; while a request
 * is out, the marks already drawn move with the edits.
 */
const SEMANTIC_DEBOUNCE_MS = 300

/** A token's classes: `dp-sem-<type>`, then `dp-sem-<modifier>` for each bit set. */
export function semanticClass(token: SemanticToken): string {
  return ['dp-sem', `dp-sem-${token.type}`, ...token.modifiers.map((m) => `dp-sem-${m}`)].join(' ')
}

export function semanticDecorations(tokens: readonly SemanticToken[]): DecorationSet {
  return Decoration.set(
    tokens.map((token) => Decoration.mark({ class: semanticClass(token) }).range(token.from, token.to)),
    true,
  )
}

export function lspSemanticTokens(client: DawnLspClient): Extension {
  return ViewPlugin.fromClass(class {
    decorations: DecorationSet = Decoration.none
    private timer: ReturnType<typeof setTimeout> | null = null
    private unsubscribe: () => void

    constructor(readonly view: EditorView) {
      this.unsubscribe = client.onStatus((status) => {
        if (status === 'ready') this.schedule()
        else if (status === 'fallback' && this.decorations.size > 0) {
          this.decorations = Decoration.none
          this.view.dispatch({})
        }
      })
    }

    update(update: ViewUpdate): void {
      if (update.docChanged) this.decorations = this.decorations.map(update.changes)
      if (update.docChanged || update.viewportChanged) this.schedule()
    }

    schedule(): void {
      if (this.timer != null) clearTimeout(this.timer)
      this.timer = setTimeout(() => {
        this.timer = null
        void this.refresh()
      }, SEMANTIC_DEBOUNCE_MS)
    }

    async refresh(): Promise<void> {
      if (!client.isReady() || client.semanticLegend == null) return
      const view = this.view
      const snapshot = view.state.doc.toString()
      const { from, to } = view.viewport
      try {
        const tokens = await client.semanticTokens(from, to)
        if (view.state.doc.toString() !== snapshot) return
        this.decorations = semanticDecorations(tokens)
        view.dispatch({})
      } catch {
        // stale or unavailable: the next edit or scroll asks again
      }
    }

    destroy(): void {
      if (this.timer != null) clearTimeout(this.timer)
      this.unsubscribe()
    }
  }, { decorations: (plugin) => plugin.decorations })
}
