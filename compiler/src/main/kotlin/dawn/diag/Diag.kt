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
}

/** A compile error: message + location + optional fix hint. Renders with a source snippet. */
class DawnError(
    message: String,
    val span: Span,
    val hint: String? = null,
) : Exception(message) {

    fun render(file: SourceFile): String {
        val line = file.lineOf(span.start)
        val col = file.colOf(span.start)
        val src = file.lineText(line)
        val sb = StringBuilder()
        sb.append("error: ").append(message).append('\n')
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
