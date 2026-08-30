import { dawn, dawnCompletions } from '../src/dawn-lang'
import { parseDawnDiagnostics } from '../src/lint'
import { EditorState, Text } from '@codemirror/state'
import { ensureSyntaxTree } from '@codemirror/language'
import { CompletionContext } from '@codemirror/autocomplete'
import {
  DAWN_LSP_PROTOCOL,
  DAWN_LSP_URI,
  DawnLspClient,
  hoverText,
  lspCompletionSource,
  lspDiagnostics,
  lspPositionToOffset,
  lspWebSocketUrl,
  mergeCompletionResults,
  offsetToLspPosition,
  type LspSocket,
} from '../src/lsp'

let fails = 0
function expect(name: string, got: unknown, want: unknown) {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) { fails++; console.log(`FAIL  ${name}: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`) }
  else console.log(`  ok  ${name}`)
}

// ---- diagnostics parser, fed real compiler output (strip_dir applied) ----
const report = `error: main must be pub
  --> prog.dawn:1:4
  |
1 | fn main() -> Unit !io = {
  |    ^^^^
  = hint: write pub fn main() -> Unit !io
error: annotated type is Int but the initializer is String
  --> prog.dawn:2:16
  |
2 |   let x: Int = "oops"
  |                ^^^^^^
error: undefined variable: y
  --> prog.dawn:3:11
  |
3 |   println(y)
  |           ^
3 errors`
const docText = Text.of(`fn main() -> Unit !io = {
  let x: Int = "oops"
  println(y)
}`.split('\n'))
const diags = parseDawnDiagnostics(report, docText)
expect('three diagnostics', diags.length, 3)
expect('d1 span = main', [diags[0].from, diags[0].to], [3, 7])
expect('d1 hint folded in', diags[0].message.includes('hint: write pub'), true)
expect('d2 span = "oops"', [diags[1].from, diags[1].to], [docText.line(2).from + 15, docText.line(2).from + 21])
expect('d3 severity', diags[2].severity, 'error')

// ---- completion context awareness ----
function completeAt(doc: string, marker = '‸') {
  const pos = doc.indexOf(marker)
  const text = doc.replace(marker, '')
  const state = EditorState.create({ doc: text, extensions: [dawn()] })
  ensureSyntaxTree(state, text.length, 5000)
  return dawnCompletions(new CompletionContext(state, pos, false))
}
expect('inside string: none', completeAt('fn f() -> Unit = println("pri‸")'), null)
expect('unterminated string: none', completeAt('fn f() -> Unit = println("pri‸'), null)
expect('triple string: none', completeAt('fn f() -> String = \"\"\"\n  multi li‸'), null)
expect('raw string: none', completeAt('fn f() -> String = `raw te‸'), null)
expect('after closed string: completes', completeAt('pub fn main() -> Unit !io = { println("x") ++ pri‸ }') !== null, true)
expect('inside comment: none', completeAt('# comment pri‸'), null)
expect('after fn: none', completeAt('fn ma‸'), null)
expect('after let: none', completeAt('fn f() -> Unit = { let co‸'), null)
expect('use line: none', completeAt('use pl‸'), null)
expect('after dot: none', completeAt('fn f() -> Unit = x.le‸'), null)
const eff = completeAt('fn f() -> Unit !i‸')
expect('effect row offers io only', eff!.options.map((o) => o.label), ['io'])
const effBare = completeAt('fn g() -> Unit !‸')
expect('bare ! pops io', effBare!.options.map((o) => o.label), ['io'])
const expr = completeAt('pub fn main() -> Unit !io = pri‸')
expect('expression: has println', expr!.options.some((o) => o.label === 'println'), true)
const local = completeAt('fn my_helper(n: Int) -> Int = n\npub fn main() -> Unit !io = my‸')
expect('own fn completes', local!.options.some((o) => o.label === 'my_helper' && o.type === 'function'), true)
const ctor = completeAt('type Shape =\n  | Circle(r: Float)\n  | Square(s: Float)\npub fn main() -> Unit !io = { let x = Ci‸ }')
expect('ADT ctor completes', ctor!.options.some((o) => o.label === 'Circle'), true)
expect('uppercase filters lowercase', ctor!.options.every((o) => /^[A-Z]/.test(o.label)), true)
const interp = completeAt('pub fn main() -> Unit !io = { let name = "x"\n  println("hi $na‸") }')
expect('interp still completes', interp !== null, true)
const interpBrace = completeAt('pub fn main() -> Unit !io = println("v=${to_st‸")')
expect('brace interp completes', interpBrace!.options.some((o) => o.label === 'to_string'), true)
const ty = completeAt('fn f(s: Str‸')
expect('builtin type String completes', ty!.options.some((o) => o.label === 'String' && o.type === 'type'), true)
const un = completeAt('pub fn main() -> Uni‸')
expect('builtin type Unit completes', un!.options.some((o) => o.label === 'Unit'), true)
const self = completeAt('fn solo() -> Int = so‸')
expect('recursive self-reference completes', self!.options.some((o) => o.label === 'solo'), true)

// ---- browser/LSP adapter: UTF-16 ranges and safe result shaping ----
const unicode = 'α😀z\nnext'
expect('offset -> LSP UTF-16', offsetToLspPosition(unicode, 3), { line: 0, character: 3 })
expect('offset -> LSP second line', offsetToLspPosition(unicode, 7), { line: 1, character: 2 })
expect('LSP UTF-16 -> offset', lspPositionToOffset(unicode, { line: 0, character: 3 }), 3)
const unicodeDiagnostic = lspDiagnostics([{
  range: { start: { line: 0, character: 1 }, end: { line: 0, character: 3 } },
  severity: 2,
  message: 'emoji warning',
}], unicode)[0]
expect(
  'LSP diagnostic UTF-16 span',
  [unicodeDiagnostic.from, unicodeDiagnostic.to, unicodeDiagnostic.severity],
  [1, 3, 'warning'],
)
expect('HTTPS endpoint becomes WSS', lspWebSocketUrl('/api/lsp', 'https://example.test/play'), 'wss://example.test/api/lsp')
expect('markdown hover fence is plain text', hoverText('```dawn\nfn f() -> Int\n```'), 'fn f() -> Int')
const merged = mergeCompletionResults(
  [{ label: 'same', detail: 'server' }, { label: 'semantic' }],
  { from: 4, options: [{ label: 'same', detail: 'static' }, { label: 'builtin' }] },
)
expect('completion is server-first and deduplicated', merged.options.map((o) => [o.label, o.detail]), [
  ['same', 'server'], ['semantic', undefined], ['builtin', undefined],
])
let semanticCalls = 0
const semanticSource = lspCompletionSource({
  isReady: () => true,
  completion: async () => {
    semanticCalls++
    return [{ label: 'playground', kind: 9, sortText: '0playground' }]
  },
} as unknown as DawnLspClient, dawnCompletions)
const useState = EditorState.create({ doc: 'use pl' })
const useResult = await semanticSource(new CompletionContext(useState, useState.doc.length, false))
expect('LSP handles and orders use completion absent from static source', [
  semanticCalls, useResult?.options[0].label, useResult?.options[0].sortText,
], [1, 'playground', '0playground'])
const rejectedSemanticSource = lspCompletionSource({
  isReady: () => true,
  completion: async () => { throw new Error('timed out') },
} as unknown as DawnLspClient, dawnCompletions)
const staticFallbackState = EditorState.create({ doc: 'fn solo() -> Int = so' })
const staticFallback = await rejectedSemanticSource(new CompletionContext(
  staticFallbackState,
  staticFallbackState.doc.length,
  false,
))
expect('semantic completion failure returns static completion',
  staticFallback?.options.some((item) => item.label === 'solo'), true)

// ---- fake gateway: handshake, serialized Full sync and stale suppression ----
class FakeSocket implements LspSocket {
  readyState = 0
  protocol = ''
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  readonly sent: Record<string, any>[] = []

  constructor(readonly requestedProtocol: string) {}

  open() {
    this.readyState = 1
    this.protocol = this.requestedProtocol
    this.onopen?.()
  }

  receive(message: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify({ jsonrpc: '2.0', ...message }) })
  }

  send(data: string) {
    this.sent.push(JSON.parse(data))
  }

  close() {
    this.readyState = 3
  }
}

const tick = async () => { await Promise.resolve() }
let socket!: FakeSocket
const client = new DawnLspClient(
  'ws://example.test/api/lsp',
  (_url, protocol) => (socket = new FakeSocket(protocol)),
  () => 0,
)
const published: string[] = []
client.onDiagnostics((event) => published.push(event.text))
client.start('first')
socket.open()
expect('requested fixed subprotocol', socket.requestedProtocol, DAWN_LSP_PROTOCOL)
expect('initialize is first', socket.sent[0].method, 'initialize')
socket.receive({ id: socket.sent[0].id, result: { capabilities: {} } })
await tick()
expect('fixed initialize/open sequence', socket.sent.slice(1).map((m) => m.method), [
  'initialized', 'textDocument/didOpen',
])
expect('didOpen fixed URI', socket.sent[2].params.textDocument.uri, DAWN_LSP_URI)

client.update('second')
expect('change waits for prior diagnostics', socket.sent.filter((m) => m.method === 'textDocument/didChange').length, 0)
socket.receive({
  method: 'textDocument/publishDiagnostics',
  params: { uri: DAWN_LSP_URI, diagnostics: [] },
})
expect('stale diagnostics discarded', published, [])
expect('latest Full sync follows stale diagnostics', socket.sent.at(-1)?.params.contentChanges, [{ text: 'second' }])
socket.receive({
  method: 'textDocument/publishDiagnostics',
  params: { uri: DAWN_LSP_URI, diagnostics: [] },
})
expect('current diagnostics published once', published, ['second'])

const completion = client.completion(3)
await tick()
const completionRequest = socket.sent.at(-1)!
expect('completion sees diagnosed snapshot', [completionRequest.method, completionRequest.params.position], [
  'textDocument/completion', { line: 0, character: 3 },
])
socket.receive({ id: completionRequest.id, result: [{ label: 'semantic', kind: 3 }] })
expect('completion response', (await completion).map((item) => item.label), ['semantic'])

const oldDefinition = client.definition(0).then(() => 'resolved', () => 'rejected')
await tick()
const oldDefinitionRequest = socket.sent.at(-1)!
const currentDefinition = client.definition(1)
await tick()
const currentDefinitionRequest = socket.sent.at(-1)!
socket.receive({ id: currentDefinitionRequest.id, result: [] })
expect('latest same-buffer definition resolves', await currentDefinition, [])
socket.receive({ id: oldDefinitionRequest.id, result: [] })
expect('out-of-order older definition is rejected', await oldDefinition, 'rejected')

const staleHover = client.hover(0).then(() => 'resolved', () => 'rejected')
await tick()
const hoverRequest = socket.sent.at(-1)!
client.update('third')
socket.receive({ id: hoverRequest.id, result: { contents: 'old' } })
expect('edited buffer rejects stale query response', await staleHover, 'rejected')
client.stop()

const retrySockets: FakeSocket[] = []
const retryClient = new DawnLspClient(
  'ws://example.test/api/lsp',
  (_url, protocol) => {
    const retrySocket = new FakeSocket(protocol)
    retrySockets.push(retrySocket)
    return retrySocket
  },
  () => 0,
)
retryClient.start('retry')
retrySockets[0].onerror?.()
await new Promise((resolve) => setTimeout(resolve, 0))
expect('disconnect gets one reconnect', retrySockets.length, 2)
retrySockets[1].onerror?.()
await new Promise((resolve) => setTimeout(resolve, 0))
expect('second disconnect stays fallback', [retrySockets.length, retryClient.status], [2, 'fallback'])
retryClient.stop()

// ---- versioned diagnostics: a stale publish is discarded, not adopted ----
let versionSocket!: FakeSocket
const versionClient = new DawnLspClient(
  'ws://example.test/api/lsp',
  (_url, protocol) => (versionSocket = new FakeSocket(protocol)),
  () => 0,
)
const versionEvents: [string, string[]][] = []
versionClient.onDiagnostics((event) => versionEvents.push([
  event.text, event.diagnostics.map((item) => item.message),
]))
versionClient.start('AAA')
versionSocket.open()
versionSocket.receive({ id: versionSocket.sent[0].id, result: { capabilities: {} } })
await tick()
const openVersion = versionSocket.sent.at(-1)!.params.textDocument.version
versionSocket.receive({
  method: 'textDocument/publishDiagnostics',
  params: { uri: DAWN_LSP_URI, version: openVersion, diagnostics: [] },
})
versionClient.update('BBB')
const changeVersion = versionSocket.sent.at(-1)!.params.textDocument.version
expect('each sync carries its own document version', changeVersion > openVersion, true)
// The buffer is BBB and its sync is in flight, but the notification answers
// AAA's version: pairing by arrival order alone would show AAA's error on BBB.
versionSocket.receive({
  method: 'textDocument/publishDiagnostics',
  params: {
    uri: DAWN_LSP_URI,
    version: openVersion,
    diagnostics: [{
      range: { start: { line: 0, character: 0 }, end: { line: 0, character: 3 } },
      message: 'belongs to AAA',
    }],
  },
})
versionSocket.receive({
  method: 'textDocument/publishDiagnostics',
  params: { uri: DAWN_LSP_URI, version: changeVersion, diagnostics: [] },
})
expect('a stale version is discarded and the matching one is published', versionEvents, [
  ['AAA', []], ['BBB', []],
])
versionClient.stop()

// ---- the reconnect budget is per healthy connection, not per round-trip ----
const settle = async () => { await new Promise((resolve) => setTimeout(resolve, 0)) }
async function reachReady(target: FakeSocket) {
  target.open()
  target.receive({ id: target.sent[0].id, result: { capabilities: {} } })
  await tick()
}
async function reachDiagnostics(target: FakeSocket) {
  await reachReady(target)
  target.receive({
    method: 'textDocument/publishDiagnostics',
    params: { uri: DAWN_LSP_URI, diagnostics: [] },
  })
}
const budgetSockets: FakeSocket[] = []
const budgetClient = new DawnLspClient(
  'ws://example.test/api/lsp',
  (_url, protocol) => {
    const budgetSocket = new FakeSocket(protocol)
    budgetSockets.push(budgetSocket)
    return budgetSocket
  },
  () => 0,
  3000,
  60000,
)
budgetClient.start('budget')
await reachDiagnostics(budgetSockets[0])
budgetSockets[0].onerror?.()
await settle()
expect('the first drop spends the one reconnect', budgetSockets.length, 2)
await reachDiagnostics(budgetSockets[1])
budgetSockets[1].onerror?.()
await settle()
expect('a diagnostics round-trip does not refill the reconnect budget', [
  budgetSockets.length, budgetClient.status,
], [2, 'fallback'])
budgetClient.stop()

const refillSockets: FakeSocket[] = []
const refillClient = new DawnLspClient(
  'ws://example.test/api/lsp',
  (_url, protocol) => {
    const refillSocket = new FakeSocket(protocol)
    refillSockets.push(refillSocket)
    return refillSocket
  },
  () => 0,
  3000,
  0,
)
refillClient.start('refill')
await reachReady(refillSockets[0])
refillSockets[0].onerror?.()
await settle()
await reachReady(refillSockets[1])
refillSockets[1].onerror?.()
await settle()
expect('a connection held past the threshold earns the budget back', refillSockets.length, 3)
refillSockets[2].onerror?.()
await settle()
expect('a connection that never became ready earns nothing back', [
  refillSockets.length, refillClient.status,
], [3, 'fallback'])
refillClient.stop()

const blackholeSockets: FakeSocket[] = []
const blackholeClient = new DawnLspClient(
  'ws://example.test/api/lsp',
  (_url, protocol) => {
    const blackholeSocket = new FakeSocket(protocol)
    blackholeSockets.push(blackholeSocket)
    return blackholeSocket
  },
  () => 0,
  1,
)
blackholeClient.start('blackhole')
const blackholeDeadline = Date.now() + 1000
while ((blackholeSockets.length !== 2 || blackholeClient.status !== 'fallback')
  && Date.now() < blackholeDeadline) {
  await new Promise((resolve) => setTimeout(resolve, 1))
}
expect('CONNECTING blackhole retries once then falls back', [
  blackholeSockets.length, blackholeClient.status,
], [2, 'fallback'])
blackholeClient.stop()

console.log(fails === 0 ? 'ALL PASS' : `${fails} FAILURES`)
process.exit(fails === 0 ? 0 : 1)
