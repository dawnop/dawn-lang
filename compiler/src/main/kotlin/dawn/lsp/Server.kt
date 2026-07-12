package dawn.lsp

import dawn.check.Analyzed
import dawn.check.analyze
import dawn.check.analyzeDocument
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
private class DocState(uri: String, text: String) {
    val source = SourceFile("<lsp>", text)
    // resolve imports from the file's project when the URI is a real path (spec §10)
    val analysis: Analyzed = run {
        val file = uriToFile(uri)
        if (file != null) analyzeDocument(file, text) else analyze(text)
    }
}

/** file:// URI → File, or null if the URI isn't a local path (unsaved/untitled buffers). */
private fun uriToFile(uri: String): java.io.File? = try {
    if (uri.startsWith("file:")) java.io.File(java.net.URI(uri)) else null
} catch (e: Exception) {
    null
}

class DawnLanguageServer : LanguageServer, LanguageClientAware {
    lateinit var client: LanguageClient
    private val documents = DawnTextDocumentService(this)

    override fun initialize(params: InitializeParams): CompletableFuture<InitializeResult> {
        val caps = ServerCapabilities()
        caps.setTextDocumentSync(TextDocumentSyncKind.Full)
        caps.setHoverProvider(true)
        caps.setCompletionProvider(CompletionOptions(false, listOf("!")))
        caps.setDefinitionProvider(true)
        caps.setDocumentSymbolProvider(true)
        caps.setDocumentFormattingProvider(true)
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
        val st = DocState(uri, text)
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

    override fun completion(
        params: CompletionParams,
    ): CompletableFuture<Either<MutableList<CompletionItem>, CompletionList>> {
        val st = docs[params.textDocument.uri]
            ?: return completedFuture(Either.forLeft(mutableListOf()))
        val offset = st.source.lspOffset(params.position.line, params.position.character)
        val items = completionsAt(st.analysis, st.source.text, offset)
        return completedFuture(Either.forLeft(items.toMutableList()))
    }

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
        val target = findTarget(st.analysis, offset)
        val def = target?.defSpan ?: return completedFuture(Either.forLeft(emptyList()))
        val loc = locationOf(params.textDocument.uri, st, target.defPath, def)
            ?: return completedFuture(Either.forLeft(emptyList()))
        return completedFuture(Either.forLeft(listOf(loc)))
    }

    /**
     * Resolve a definition site to a Location. A null [defPath] (or one naming the
     * requesting document) maps through the live buffer; another file maps through
     * its open buffer if the client has it open, else through the text on disk.
     */
    private fun locationOf(uri: String, st: DocState, defPath: String?, def: Span): Location? {
        val cur = uriToFile(uri)
        val defFile = defPath?.let { java.io.File(it) }
        if (defFile == null || (cur != null && defFile.canonicalPath == cur.canonicalPath)) {
            return Location(uri, rangeOf(st.source, def))
        }
        val open = docs.entries.firstOrNull { uriToFile(it.key)?.canonicalPath == defFile.canonicalPath }
        if (open != null) return Location(open.key, rangeOf(open.value.source, def))
        val text = try {
            defFile.readText()
        } catch (e: Exception) {
            return null
        }
        return Location(defFile.toPath().toUri().toString(), rangeOf(SourceFile(defPath, text), def))
    }

    override fun documentSymbol(
        params: DocumentSymbolParams,
    ): CompletableFuture<List<Either<SymbolInformation, DocumentSymbol>>> {
        val st = docs[params.textDocument.uri] ?: return completedFuture(emptyList())
        val symbols = st.analysis.module.decls.map { d ->
            val isFn = d is dawn.ast.FnDecl
            val detail = if (isFn) st.analysis.functions[d.name]?.render() else null
            val sym = DocumentSymbol(
                d.name,
                if (isFn) SymbolKind.Function else SymbolKind.Class,
                rangeOf(st.source, d.span),
                rangeOf(st.source, d.nameSpan),
                detail,
            )
            Either.forRight<SymbolInformation, DocumentSymbol>(sym)
        }
        return completedFuture(symbols)
    }

    override fun formatting(params: DocumentFormattingParams): CompletableFuture<List<TextEdit>> {
        val st = docs[params.textDocument.uri] ?: return completedFuture(emptyList())
        val text = st.source.text
        val formatted = dawn.fmt.Formatter.format(text)
        if (formatted == text) return completedFuture(emptyList())
        // replace the whole document (fmt only needs a successful lex, so this works on broken files too)
        val lines = text.split("\n")
        val end = Position(lines.size - 1, lines.last().length)
        return completedFuture(listOf(TextEdit(Range(Position(0, 0), end), formatted)))
    }

    // ---- position mapping ----

    private fun rangeOf(source: SourceFile, span: Span): Range {
        val (sl, sc) = source.lspPosition(span.start)
        val (el, ec) = source.lspPosition(span.end)
        return Range(Position(sl, sc), Position(el, ec))
    }
}
