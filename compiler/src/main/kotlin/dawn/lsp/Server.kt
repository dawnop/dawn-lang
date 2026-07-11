package dawn.lsp

import dawn.check.Analyzed
import dawn.check.analyze
import dawn.diag.Severity
import dawn.diag.SourceFile
import dawn.diag.Span
import org.eclipse.lsp4j.*
import org.eclipse.lsp4j.jsonrpc.messages.Either
import org.eclipse.lsp4j.launch.LSPLauncher
import org.eclipse.lsp4j.services.*
import java.util.concurrent.CompletableFuture
import java.util.concurrent.CompletableFuture.completedFuture
import java.util.concurrent.ConcurrentHashMap
import kotlin.system.exitProcess

/** Entry point for `dawn lsp`: speak LSP over stdio until the client disconnects. */
fun runLspServer() {
    val server = DawnLanguageServer()
    val launcher = LSPLauncher.createServerLauncher(server, System.`in`, System.out)
    server.connect(launcher.remoteProxy)
    launcher.startListening().get()
}

/** One open document: text + line index + fresh analysis. Rebuilt on every change (M0 files are tiny). */
private class DocState(text: String) {
    val source = SourceFile("<lsp>", text)
    val analysis: Analyzed = analyze(text)
}

class DawnLanguageServer : LanguageServer, LanguageClientAware {
    lateinit var client: LanguageClient
    private val documents = DawnTextDocumentService(this)

    override fun initialize(params: InitializeParams): CompletableFuture<InitializeResult> {
        val caps = ServerCapabilities()
        caps.setTextDocumentSync(TextDocumentSyncKind.Full)
        caps.setHoverProvider(true)
        caps.setDefinitionProvider(true)
        caps.setDocumentSymbolProvider(true)
        return completedFuture(InitializeResult(caps))
    }

    override fun shutdown(): CompletableFuture<Any> = completedFuture(null)
    override fun exit() = exitProcess(0)
    override fun getTextDocumentService(): TextDocumentService = documents
    override fun getWorkspaceService(): WorkspaceService = object : WorkspaceService {
        override fun didChangeConfiguration(params: DidChangeConfigurationParams) {}
        override fun didChangeWatchedFiles(params: DidChangeWatchedFilesParams) {}
    }

    override fun connect(client: LanguageClient) {
        this.client = client
    }
}

private class DawnTextDocumentService(private val server: DawnLanguageServer) : TextDocumentService {

    private val docs = ConcurrentHashMap<String, DocState>()

    // ---- document sync ----

    override fun didOpen(params: DidOpenTextDocumentParams) {
        update(params.textDocument.uri, params.textDocument.text)
    }

    override fun didChange(params: DidChangeTextDocumentParams) {
        // sync kind is Full: the single change carries the whole document
        val text = params.contentChanges.firstOrNull()?.text ?: return
        update(params.textDocument.uri, text)
    }

    override fun didClose(params: DidCloseTextDocumentParams) {
        docs.remove(params.textDocument.uri)
        server.client.publishDiagnostics(PublishDiagnosticsParams(params.textDocument.uri, emptyList()))
    }

    override fun didSave(params: DidSaveTextDocumentParams) {}

    private fun update(uri: String, text: String) {
        val st = DocState(text)
        docs[uri] = st
        val diags = st.analysis.diagnostics.map { d ->
            Diagnostic(
                rangeOf(st.source, d.span),
                d.message + (d.hint?.let { "\nhint: $it" } ?: ""),
                if (d.severity == Severity.ERROR) DiagnosticSeverity.Error else DiagnosticSeverity.Warning,
                "dawn",
            )
        }
        server.client.publishDiagnostics(PublishDiagnosticsParams(uri, diags))
    }

    // ---- language features ----

    override fun hover(params: HoverParams): CompletableFuture<Hover> {
        val st = docs[params.textDocument.uri] ?: return completedFuture(null)
        val offset = st.source.lspOffset(params.position.line, params.position.character)
        val target = findTarget(st.analysis, offset) ?: return completedFuture(null)
        val content = MarkupContent(MarkupKind.MARKDOWN, "```dawn\n${target.hover}\n```")
        return completedFuture(Hover(content, rangeOf(st.source, target.span)))
    }

    override fun definition(
        params: DefinitionParams,
    ): CompletableFuture<Either<List<Location>, List<LocationLink>>> {
        val st = docs[params.textDocument.uri] ?: return completedFuture(Either.forLeft(emptyList()))
        val offset = st.source.lspOffset(params.position.line, params.position.character)
        val def = findTarget(st.analysis, offset)?.defSpan
            ?: return completedFuture(Either.forLeft(emptyList()))
        val loc = Location(params.textDocument.uri, rangeOf(st.source, def))
        return completedFuture(Either.forLeft(listOf(loc)))
    }

    override fun documentSymbol(
        params: DocumentSymbolParams,
    ): CompletableFuture<List<Either<SymbolInformation, DocumentSymbol>>> {
        val st = docs[params.textDocument.uri] ?: return completedFuture(emptyList())
        val symbols = st.analysis.module.decls.map { d ->
            val sig = st.analysis.functions[d.name]
            val sym = DocumentSymbol(
                d.name,
                SymbolKind.Function,
                rangeOf(st.source, d.span),
                rangeOf(st.source, d.nameSpan),
                sig?.render(),
            )
            Either.forRight<SymbolInformation, DocumentSymbol>(sym)
        }
        return completedFuture(symbols)
    }

    // ---- position mapping ----

    private fun rangeOf(source: SourceFile, span: Span): Range {
        val (sl, sc) = source.lspPosition(span.start)
        val (el, ec) = source.lspPosition(span.end)
        return Range(Position(sl, sc), Position(el, ec))
    }
}
