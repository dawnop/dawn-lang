package dawn.diag

/** Half-open range [start, end) of character offsets into the source. */
data class Span(val start: Int, val end: Int) {
    companion object {
        fun at(pos: Int) = Span(pos, pos + 1)
    }
}

/** A source file: path + text + line offset index; converts offsets to line/column. */
class SourceFile(val path: String, val text: String) {
    private val lineStarts: IntArray = run {
        val starts = ArrayList<Int>()
        starts.add(0)
        text.forEachIndexed { i, c -> if (c == '\n') starts.add(i + 1) }
        starts.toIntArray()
    }

    /** 1-based line number */
    fun lineOf(offset: Int): Int {
        var lo = 0
        var hi = lineStarts.size - 1
        while (lo < hi) {
            val mid = (lo + hi + 1) / 2
            if (lineStarts[mid] <= offset) lo = mid else hi = mid - 1
        }
        return lo + 1
    }

    /** 1-based column number */
    fun colOf(offset: Int): Int = offset - lineStarts[lineOf(offset) - 1] + 1

    fun lineText(line: Int): String {
        val start = lineStarts[line - 1]
        val end = text.indexOf('\n', start).let { if (it < 0) text.length else it }
        return text.substring(start, end)
    }

    // ---- LSP position mapping ----
    // Our offsets index Kotlin String chars, which are UTF-16 code units — exactly
    // LSP's default position encoding, so the conversion is pure arithmetic.

    /** offset → (0-based line, 0-based UTF-16 column) */
    fun lspPosition(offset: Int): Pair<Int, Int> {
        val clamped = offset.coerceIn(0, text.length)
        val line = lineOf(clamped)
        return Pair(line - 1, clamped - lineStarts[line - 1])
    }

    /** (0-based line, 0-based UTF-16 column) → offset, clamped to valid range */
    fun lspOffset(line0: Int, character: Int): Int {
        if (line0 < 0) return 0
        if (line0 >= lineStarts.size) return text.length
        val lineStart = lineStarts[line0]
        val lineEnd = text.indexOf('\n', lineStart).let { if (it < 0) text.length else it }
        return (lineStart + character).coerceIn(lineStart, lineEnd)
    }
}

// Diagnostic style guide (keep every `sink.error(...)` consistent with this):
//   - message: lowercase start, one clause, no trailing period; wrap code in backticks;
//     show types in Dawn syntax (`List[Int]`, `fn(Int) -> Int`), never internal names.
//   - hint (optional): how to FIX it, not a restatement of what's wrong; imperative mood.
//     Omit it only when there is no concrete action the user can take.
//   - Use dawn.diag.Suggest for "did you mean ...?" on names that failed to resolve.
enum class Severity { ERROR, WARNING }

/** A single diagnostic: message + location + optional fix hint. */
class Diagnostic(
    val message: String,
    val span: Span,
    val hint: String? = null,
    val severity: Severity = Severity.ERROR,
) {
    fun render(file: SourceFile): String {
        val line = file.lineOf(span.start)
        val col = file.colOf(span.start)
        val src = file.lineText(line)
        val sb = StringBuilder()
        val label = if (severity == Severity.ERROR) "error" else "warning"
        sb.append(label).append(": ").append(message).append('\n')
        sb.append("  --> ").append(file.path).append(':').append(line).append(':').append(col).append('\n')
        val lineNo = line.toString()
        sb.append(" ".repeat(lineNo.length + 1)).append("|\n")
        sb.append(lineNo).append(" | ").append(src).append('\n')
        val caretLen = (span.end - span.start).coerceAtLeast(1)
            .coerceAtMost((src.length - (col - 1)).coerceAtLeast(1))
        sb.append(" ".repeat(lineNo.length + 1)).append("| ")
        sb.append(" ".repeat(col - 1)).append("^".repeat(caretLen)).append('\n')
        if (hint != null) sb.append("  = hint: ").append(hint).append('\n')
        return sb.toString()
    }
}

/** Collects diagnostics across all compile phases. */
class DiagnosticSink {
    private val list = ArrayList<Diagnostic>()

    val all: List<Diagnostic> get() = list
    val hasErrors: Boolean get() = list.any { it.severity == Severity.ERROR }

    fun error(message: String, span: Span, hint: String? = null) {
        list.add(Diagnostic(message, span, hint, Severity.ERROR))
    }

    fun add(d: Diagnostic) {
        list.add(d)
    }

    fun add(e: DawnError) {
        list.add(Diagnostic(e.message ?: "syntax error", e.span, e.hint))
    }
}

/**
 * Internal abort exception used by the parser for control flow; recovery points
 * catch it, convert it into a Diagnostic, and resynchronize.
 */
class DawnError(
    message: String,
    val span: Span,
    val hint: String? = null,
) : Exception(message)
