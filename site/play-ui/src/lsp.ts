import type {
  Completion,
  CompletionContext,
  CompletionResult,
  CompletionSource,
} from '@codemirror/autocomplete'
import type { Diagnostic } from '@codemirror/lint'
import type { Extension } from '@codemirror/state'
import { EditorView, hoverTooltip } from '@codemirror/view'

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
}

interface LspHover {
  contents: unknown
  range?: LspRange
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

function completionItemOf(value: unknown): LspCompletionItem | null {
  const item = asRecord(value)
  if (typeof item?.label !== 'string') return null
  return {
    label: item.label,
    ...(typeof item.kind === 'number' ? { kind: item.kind } : {}),
    ...(typeof item.detail === 'string' ? { detail: item.detail } : {}),
    ...(typeof item.sortText === 'string' ? { sortText: item.sortText } : {}),
    ...(typeof item.insertText === 'string' ? { insertText: item.insertText } : {}),
  }
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
  private opened = false
  private version = 0
  private generation = 0
  private diagnosedGeneration = -1
  private text = ''
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
    return Array.isArray(record?.items)
      ? record.items.map(completionItemOf)
        .filter((item: LspCompletionItem | null): item is LspCompletionItem => item != null)
      : []
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
            completion: { completionItem: { snippetSupport: false } },
          },
        },
      }, INITIALIZE_TIMEOUT_MS).then(() => {
        if (!this.isCurrent(connection, socket)) return
        this.notify('initialized', {})
        this.opened = false
        this.version = 0
        this.inFlight = null
        this.diagnosedGeneration = -1
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
    this.setStatus('fallback')
    if (retry && !this.stopped && this.retryCount < 1) {
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
    const flight = { generation: this.generation, text: this.text }
    this.inFlight = flight
    this.version++
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
    this.inFlight = null
    this.clearDiagnosticTimer()
    this.diagnosedGeneration = flight.generation
    this.retryCount = 0
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

  private async query(method: string, offset: number, timeoutMs: number): Promise<unknown> {
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
    const result = await this.requestRaw(method, {
      textDocument: { uri: DAWN_LSP_URI },
      position: offsetToLspPosition(text, offset),
    }, remaining)
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

function completionOf(item: LspCompletionItem): Completion | null {
  if (typeof item.label !== 'string' || item.label.length === 0) return null
  return {
    label: item.label,
    type: completionType(item.kind),
    boost: 3,
    ...(typeof item.sortText === 'string' ? { sortText: item.sortText } : {}),
    ...(typeof item.insertText === 'string' ? { apply: item.insertText } : {}),
    ...(typeof item.detail === 'string' ? { detail: item.detail } : {}),
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
      const server = items.map(completionOf).filter((item): item is Completion => item != null)
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

export function hoverText(contents: unknown): string {
  const values = Array.isArray(contents) ? contents : [contents]
  const text = values.flatMap((value) => {
    if (typeof value === 'string') return [value]
    const record = asRecord(value)
    return typeof record?.value === 'string' ? [record.value] : []
  }).join('\n\n')
  const fenced = /^```(?:dawn)?\s*\n([\s\S]*?)\n```\s*$/.exec(text.trim())
  return fenced ? fenced[1] : text
}

export function lspHover(client: DawnLspClient): Extension {
  return hoverTooltip(async (view, offset) => {
    if (!client.isReady()) return null
    const snapshot = view.state.doc.toString()
    try {
      const hover = await client.hover(offset, 1000)
      if (hover == null || view.state.doc.toString() !== snapshot) return null
      const text = hoverText(hover.contents).trim()
      if (!text) return null
      const from = hover.range ? lspPositionToOffset(snapshot, hover.range.start) : offset
      const to = hover.range ? lspPositionToOffset(snapshot, hover.range.end) : offset
      return {
        pos: from,
        end: Math.max(from, to),
        above: true,
        create: () => {
          const dom = document.createElement('div')
          dom.className = 'dp-hover'
          dom.textContent = text
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
