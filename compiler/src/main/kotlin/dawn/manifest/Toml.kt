package dawn.manifest

import dawn.diag.DiagnosticSink
import dawn.diag.SourceFile
import dawn.diag.Span

/**
 * A format-preserving parser for the subset of TOML that `dawn.toml` uses
 * (docs/package-design.md §4.2).
 *
 * Why hand-written rather than a library: `dawn add` must eventually edit the
 * manifest in place without mangling the user's comments, spacing, and key order,
 * and no format-preserving TOML editor exists on the JVM (Cargo needs `toml_edit`
 * for exactly this; `tomlj` has no writer at all, `toml4j` is unmaintained, and
 * ktoml is a kotlinx.serialization format with no CST). Files stay valid TOML, so
 * editors and other tools can still read them — only the parser is ours.
 *
 * The subset is deliberately line-oriented: every supported construct fits on one
 * line, which is what makes the CST a plain list of lines. Anything outside the
 * subset is a hard error with a hint, never a silent misread. Widening the subset
 * later is backwards compatible; narrowing would not be.
 *
 * Supported:
 *   # comment
 *   key = "string"            escapes: \" \\ \n \t \r \uXXXX
 *   key = 123                 decimal, optional _ separators, optional sign
 *   key = true | false
 *   key = ["a", "b"]          single-line arrays of strings
 *   [table]
 */

/** A value from the supported subset, with its span in the source. */
sealed class TomlValue {
    abstract val span: Span
}

class TomlStr(val value: String, override val span: Span) : TomlValue()
class TomlInt(val value: Long, override val span: Span) : TomlValue()
class TomlBool(val value: Boolean, override val span: Span) : TomlValue()
class TomlArr(val value: List<String>, override val span: Span) : TomlValue()

/**
 * One source line. [text] is the raw text with the newline stripped (a trailing
 * '\r' is kept, so rendering a CRLF file reproduces CRLF).
 */
sealed class TomlLine {
    abstract val text: String
}

class TomlBlank(override val text: String) : TomlLine()
class TomlComment(override val text: String) : TomlLine()
class TomlHeader(val name: String, val nameSpan: Span, override val text: String) : TomlLine()

/** `key = value`, possibly with a trailing comment. [start] is the line's offset. */
class TomlEntry(
    val key: String,
    val keySpan: Span,
    val value: TomlValue,
    override var text: String,
    val start: Int,
) : TomlLine()

/**
 * A parsed document: the CST (every line, in order) plus the source for
 * diagnostics. Lookups are by table; edits preserve everything they don't touch.
 */
class TomlDoc(val source: SourceFile, val lines: MutableList<TomlLine>, private val endsWithNewline: Boolean) {

    /** Entries under `[name]`, or the entries before any header when [name] is null. */
    fun table(name: String?): List<TomlEntry> {
        val out = ArrayList<TomlEntry>()
        var current: String? = null
        for (l in lines) when (l) {
            is TomlHeader -> current = l.name
            is TomlEntry -> if (current == name) out.add(l)
            else -> {}
        }
        return out
    }

    /** The header line for `[name]`, or null if the table is absent. */
    fun header(name: String): TomlHeader? = lines.filterIsInstance<TomlHeader>().firstOrNull { it.name == name }

    fun entry(table: String?, key: String): TomlEntry? = table(table).firstOrNull { it.key == key }

    /** Every table name, in source order. */
    fun tableNames(): List<String> = lines.filterIsInstance<TomlHeader>().map { it.name }

    /** Reassemble the document. Byte-identical to the input when nothing was edited. */
    fun render(): String = lines.joinToString("\n") { it.text } + if (endsWithNewline) "\n" else ""

    /**
     * Set `key = "value"` in [table], preserving the rest of the file. Replaces just
     * the value text of an existing entry (leading indent, key, spacing around `=`,
     * and any trailing comment survive); otherwise appends an entry to the table,
     * creating the table header if needed.
     */
    fun setString(table: String?, key: String, value: String) {
        val quoted = quote(value)
        val existing = entry(table, key)
        if (existing != null) {
            val rel = existing.value.span.start - existing.start
            val relEnd = existing.value.span.end - existing.start
            existing.text = existing.text.substring(0, rel) + quoted + existing.text.substring(relEnd)
            return
        }
        val line = TomlEntry(key, Span(0, 0), TomlStr(value, Span(0, 0)), "$key = $quoted", 0)
        val idx = lastIndexOfTable(table)
        if (idx >= 0) {
            lines.add(idx + 1, line)
            return
        }
        if (table != null) {
            if (lines.isNotEmpty() && lines.last() !is TomlBlank) lines.add(TomlBlank(""))
            lines.add(TomlHeader(table, Span(0, 0), "[$table]"))
        }
        lines.add(line)
    }

    /** Remove `key` from [table]; true if it was there. */
    fun remove(table: String?, key: String): Boolean {
        val e = entry(table, key) ?: return false
        lines.remove(e)
        return true
    }

    /** Remove `[name]` — the header and every entry under it; true if it was there. */
    fun removeTable(name: String): Boolean {
        val header = header(name) ?: return false
        val start = lines.indexOf(header)
        var end = start + 1
        while (end < lines.size && lines[end] !is TomlHeader) end++
        // a trailing blank separates this table from the next; drop it with the table
        while (end > start + 1 && lines[end - 1] is TomlBlank) end--
        lines.subList(start, end).clear()
        return true
    }

    /** Index of the last line belonging to [table] (its last entry, else its header). */
    private fun lastIndexOfTable(table: String?): Int {
        var current: String? = null
        var last = if (table == null) -1 else Int.MIN_VALUE
        for ((i, l) in lines.withIndex()) when (l) {
            is TomlHeader -> {
                current = l.name
                if (l.name == table) last = i
            }
            is TomlEntry -> if (current == table) last = i
            else -> {}
        }
        return if (last == Int.MIN_VALUE) -1 else last
    }

    private fun quote(s: String): String {
        val sb = StringBuilder("\"")
        for (c in s) when (c) {
            '"' -> sb.append("\\\"")
            '\\' -> sb.append("\\\\")
            '\n' -> sb.append("\\n")
            '\t' -> sb.append("\\t")
            '\r' -> sb.append("\\r")
            else -> sb.append(c)
        }
        return sb.append('"').toString()
    }
}

/** Parses [source] into a [TomlDoc], reporting anything outside the subset to [sink]. */
object TomlParser {

    private val BARE_KEY = Regex("^[A-Za-z0-9_-]+$")

    fun parse(source: SourceFile, sink: DiagnosticSink): TomlDoc {
        val text = source.text
        val endsWithNewline = text.endsWith("\n")
        val body = if (endsWithNewline) text.dropLast(1) else text
        val lines = ArrayList<TomlLine>()
        var offset = 0
        // an empty file has no lines at all; split() would yield one empty line
        val rawLines = if (body.isEmpty() && !endsWithNewline) emptyList() else body.split("\n")
        for (raw in rawLines) {
            lines.add(parseLine(raw, offset, sink))
            offset += raw.length + 1
        }
        val doc = TomlDoc(source, lines, endsWithNewline)
        checkDuplicates(doc, sink)
        return doc
    }

    private fun checkDuplicates(doc: TomlDoc, sink: DiagnosticSink) {
        val names = doc.tableNames()
        val seenTables = HashSet<String>()
        for (h in doc.lines.filterIsInstance<TomlHeader>()) {
            if (!seenTables.add(h.name))
                sink.error("table `${h.name}` is defined more than once", h.nameSpan)
        }
        for (t in listOf<String?>(null) + names.distinct()) {
            val seen = HashSet<String>()
            for (e in doc.table(t)) {
                if (!seen.add(e.key))
                    sink.error("key `${e.key}` is defined more than once", e.keySpan)
            }
        }
    }

    private fun parseLine(raw: String, start: Int, sink: DiagnosticSink): TomlLine {
        val s = Scanner(raw, start, sink)
        s.skipSpace()
        if (s.eol()) return TomlBlank(raw)
        if (s.peek() == '#') return TomlComment(raw)
        if (s.peek() == '[') return parseHeader(raw, s)
        return parseEntry(raw, start, s)
    }

    private fun parseHeader(raw: String, s: Scanner): TomlLine {
        s.next() // [
        if (!s.eol() && s.peek() == '[') {
            s.error("arrays of tables are not supported in dawn.toml", Span(s.pos - 1, s.pos + 1),
                "use `[table]` with one key per entry")
            return TomlComment(raw)
        }
        s.skipSpace()
        val nameStart = s.pos
        while (!s.eol() && s.peek() != ']' && s.peek() != ' ' && s.peek() != '\t') s.next()
        val nameSpan = Span(s.abs(nameStart), s.abs(s.pos))
        val name = raw.substring(nameStart, s.pos)
        if (name.isEmpty()) {
            s.error("table name is empty", nameSpan)
            return TomlComment(raw)
        }
        // one dot level for `[deps.<alias>]` sub-tables; deeper nesting stays out
        val segments = name.split('.')
        if (segments.size > 2) {
            s.error("table names may have at most one dot", nameSpan,
                "use `[table]` or `[table.sub]`")
            return TomlComment(raw)
        }
        if (segments.any { !BARE_KEY.matches(it) }) {
            s.error("invalid table name `$name`", nameSpan,
                "table names are bare keys: letters, digits, `_`, `-`")
            return TomlComment(raw)
        }
        s.skipSpace()
        if (s.eol() || s.peek() != ']') {
            s.error("expected `]` to close the table header", Span(s.abs(s.pos), s.abs(s.pos) + 1))
            return TomlComment(raw)
        }
        s.next() // ]
        s.finishLine()
        return TomlHeader(name, nameSpan, raw)
    }

    private fun parseEntry(raw: String, start: Int, s: Scanner): TomlLine {
        val keyStart = s.pos
        if (s.peek() == '"' || s.peek() == '\'') {
            s.error("quoted keys are not supported in dawn.toml", Span(s.abs(s.pos), s.abs(s.pos) + 1),
                "use a bare key: letters, digits, `_`, `-`")
            return TomlComment(raw)
        }
        while (!s.eol() && s.peek() != '=' && s.peek() != ' ' && s.peek() != '\t') s.next()
        val key = raw.substring(keyStart, s.pos)
        val keySpan = Span(s.abs(keyStart), s.abs(s.pos))
        if (key.isEmpty()) {
            s.error("expected a key", keySpan)
            return TomlComment(raw)
        }
        if (key.contains('.')) {
            s.error("dotted keys are not supported in dawn.toml", keySpan,
                "use a `[table]` header instead of `a.b = ...`")
            return TomlComment(raw)
        }
        if (!BARE_KEY.matches(key)) {
            s.error("invalid key `$key`", keySpan, "keys are bare: letters, digits, `_`, `-`")
            return TomlComment(raw)
        }
        s.skipSpace()
        if (s.eol() || s.peek() != '=') {
            s.error("expected `=` after key `$key`", Span(s.abs(s.pos), s.abs(s.pos) + 1))
            return TomlComment(raw)
        }
        s.next() // =
        s.skipSpace()
        val value = parseValue(s) ?: return TomlComment(raw)
        s.finishLine()
        return TomlEntry(key, keySpan, value, raw, start)
    }

    private fun parseValue(s: Scanner): TomlValue? {
        if (s.eol()) {
            s.error("expected a value", Span(s.abs(s.pos), s.abs(s.pos) + 1))
            return null
        }
        return when {
            s.peek() == '"' -> parseString(s)
            s.peek() == '\'' -> {
                s.error("literal strings are not supported in dawn.toml", Span(s.abs(s.pos), s.abs(s.pos) + 1),
                    "use a basic string with double quotes")
                null
            }
            s.peek() == '[' -> parseArray(s)
            s.peek() == '{' -> {
                s.error("inline tables are not supported in dawn.toml", Span(s.abs(s.pos), s.abs(s.pos) + 1),
                    "use a `[table]` header with one key per line")
                null
            }
            s.rest().startsWith("true") -> {
                val start = s.pos
                repeat(4) { s.next() }
                TomlBool(true, Span(s.abs(start), s.abs(s.pos)))
            }
            s.rest().startsWith("false") -> {
                val start = s.pos
                repeat(5) { s.next() }
                TomlBool(false, Span(s.abs(start), s.abs(s.pos)))
            }
            else -> parseNumber(s)
        }
    }

    private fun parseString(s: Scanner): TomlValue? {
        val start = s.pos
        if (s.rest().startsWith("\"\"\"")) {
            s.error("multi-line strings are not supported in dawn.toml", Span(s.abs(start), s.abs(start) + 3),
                "put the value on one line with a basic string")
            return null
        }
        s.next() // opening quote
        val sb = StringBuilder()
        while (true) {
            if (s.eol()) {
                s.error("unterminated string", Span(s.abs(start), s.abs(s.pos)),
                    "add a closing `\"`; strings may not span lines in dawn.toml")
                return null
            }
            val c = s.next()
            if (c == '"') break
            if (c != '\\') {
                sb.append(c)
                continue
            }
            if (s.eol()) {
                s.error("unterminated escape", Span(s.abs(s.pos - 1), s.abs(s.pos)))
                return null
            }
            when (val e = s.next()) {
                '"' -> sb.append('"')
                '\\' -> sb.append('\\')
                'n' -> sb.append('\n')
                't' -> sb.append('\t')
                'r' -> sb.append('\r')
                'u' -> {
                    if (s.remaining() < 4) {
                        s.error("`\\u` needs four hex digits", Span(s.abs(s.pos - 2), s.abs(s.pos)))
                        return null
                    }
                    val hex = s.take(4)
                    val code = hex.toIntOrNull(16)
                    if (code == null) {
                        s.error("invalid `\\u` escape `\\u$hex`", Span(s.abs(s.pos - 6), s.abs(s.pos)),
                            "use four hex digits, e.g. `\\u00e9`")
                        return null
                    }
                    sb.append(code.toChar())
                }
                else -> {
                    s.error("unsupported escape `\\$e`", Span(s.abs(s.pos - 2), s.abs(s.pos)),
                        "dawn.toml supports \\\" \\\\ \\n \\t \\r and \\uXXXX")
                    return null
                }
            }
        }
        return TomlStr(sb.toString(), Span(s.abs(start), s.abs(s.pos)))
    }

    private fun parseArray(s: Scanner): TomlValue? {
        val start = s.pos
        s.next() // [
        val items = ArrayList<String>()
        s.skipSpace()
        if (!s.eol() && s.peek() == ']') {
            s.next()
            return TomlArr(items, Span(s.abs(start), s.abs(s.pos)))
        }
        while (true) {
            s.skipSpace()
            if (s.eol()) {
                s.error("unterminated array", Span(s.abs(start), s.abs(s.pos)),
                    "close it with `]`; arrays may not span lines in dawn.toml")
                return null
            }
            if (s.peek() != '"') {
                s.error("array elements must be strings in dawn.toml", Span(s.abs(s.pos), s.abs(s.pos) + 1),
                    "write elements as basic strings, e.g. `[\"a\", \"b\"]`")
                return null
            }
            val item = parseString(s) as? TomlStr ?: return null
            items.add(item.value)
            s.skipSpace()
            if (s.eol()) {
                s.error("unterminated array", Span(s.abs(start), s.abs(s.pos)),
                    "close it with `]`; arrays may not span lines in dawn.toml")
                return null
            }
            when (s.next()) {
                ',' -> {
                    s.skipSpace()
                    // allow a trailing comma before the closing bracket
                    if (!s.eol() && s.peek() == ']') {
                        s.next()
                        return TomlArr(items, Span(s.abs(start), s.abs(s.pos)))
                    }
                }
                ']' -> return TomlArr(items, Span(s.abs(start), s.abs(s.pos)))
                else -> {
                    s.error("expected `,` or `]` in array", Span(s.abs(s.pos - 1), s.abs(s.pos)))
                    return null
                }
            }
        }
    }

    private fun parseNumber(s: Scanner): TomlValue? {
        val start = s.pos
        if (s.peek() == '+' || s.peek() == '-') s.next()
        while (!s.eol() && (s.peek().isDigit() || s.peek() == '_')) s.next()
        val raw = s.slice(start, s.pos)
        val span = Span(s.abs(start), s.abs(s.pos))
        // classify what stopped us, so the error names the real construct
        if (!s.eol()) {
            val c = s.peek()
            if (c == '-' || c == ':') {
                while (!s.eol() && s.peek() != ' ' && s.peek() != '\t' && s.peek() != '#') s.next()
                s.error("date-time values are not supported in dawn.toml", Span(s.abs(start), s.abs(s.pos)),
                    "quote it if you meant a string")
                return null
            }
            if (c == '.' || c == 'e' || c == 'E') {
                while (!s.eol() && s.peek() != ' ' && s.peek() != '\t' && s.peek() != '#') s.next()
                s.error("floats are not supported in dawn.toml", Span(s.abs(start), s.abs(s.pos)),
                    "use an integer, or quote it if you meant a string")
                return null
            }
            if (c == 'x' || c == 'o' || c == 'b') {
                while (!s.eol() && s.peek() != ' ' && s.peek() != '\t' && s.peek() != '#') s.next()
                s.error("only decimal integers are supported in dawn.toml", Span(s.abs(start), s.abs(s.pos)))
                return null
            }
        }
        if (raw.isEmpty() || raw == "+" || raw == "-") {
            while (!s.eol() && s.peek() != ' ' && s.peek() != '\t' && s.peek() != '#') s.next()
            s.error("invalid value `${s.slice(start, s.pos)}`", Span(s.abs(start), s.abs(s.pos)),
                "dawn.toml values are strings, integers, booleans, or arrays of strings")
            return null
        }
        val n = raw.replace("_", "").toLongOrNull()
        if (n == null) {
            s.error("invalid integer `$raw`", span)
            return null
        }
        return TomlInt(n, span)
    }

    /** A line-local cursor. [abs] lifts a line offset to a source offset for spans. */
    private class Scanner(val line: String, val start: Int, val sink: DiagnosticSink) {
        var pos = 0
        // a trailing '\r' (CRLF input) is not part of the content
        val end = if (line.endsWith("\r")) line.length - 1 else line.length

        fun eol() = pos >= end
        fun peek() = line[pos]
        fun next() = line[pos++]
        fun rest() = line.substring(pos, end)
        fun remaining() = end - pos
        fun slice(a: Int, b: Int) = line.substring(a, b)
        fun take(n: Int): String {
            val s = line.substring(pos, pos + n)
            pos += n
            return s
        }

        fun abs(p: Int) = start + p
        fun skipSpace() {
            while (!eol() && (peek() == ' ' || peek() == '\t')) pos++
        }

        fun error(msg: String, span: Span, hint: String? = null) = sink.error(msg, span, hint)

        /** After a complete value or header: only spaces and a comment may follow. */
        fun finishLine() {
            skipSpace()
            if (eol() || peek() == '#') return
            val from = pos
            pos = end
            sink.error("unexpected text after the value", Span(abs(from), abs(end)),
                "one key per line; start a comment with `#`")
        }
    }
}
