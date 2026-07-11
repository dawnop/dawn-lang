package dawn.lex

import dawn.diag.DawnError
import dawn.diag.DiagnosticSink
import dawn.diag.Span

/**
 * Lexer. spec §1.
 *
 * Newline rule: a newline yields a NEWLINE token acting as the statement separator,
 * except when the line ends with an "unfinished" token (binary operator, comma,
 * opening bracket, ->, =>, =, |>, ...), in which case the newline is swallowed
 * (automatic continuation). Consecutive NEWLINEs collapse into one. The parser
 * additionally skips insignificant NEWLINEs (block start/end etc.) itself.
 *
 * Error recovery: bad tokens are reported to the sink and skipped (a broken
 * string skips to the end of its line), so a lex error never kills the file.
 */
class Lexer(
    private val src: String,
    private val baseOffset: Int = 0,
    private val sink: DiagnosticSink = DiagnosticSink(),
) {

    private var pos = 0
    private val tokens = ArrayList<Token>()

    fun lex(): List<Token> {
        while (pos < src.length) {
            val c = src[pos]
            try {
                when {
                    c == '\n' -> { emitNewline(); pos++ }
                    c == ' ' || c == '\t' || c == '\r' -> pos++
                    c == '#' -> skipComment()
                    c == '"' -> lexString()
                    c.isDigit() -> lexNumber()
                    c == '_' && !isIdentPart(peek(1)) -> { add(TokenType.UNDERSCORE, "_", 1) }
                    c.isLetter() || c == '_' -> lexWord()
                    else -> lexSymbol()
                }
            } catch (e: DawnError) {
                // string-level failures: report, then resynchronize at end of line
                sink.add(e)
                while (pos < src.length && src[pos] != '\n') pos++
            }
        }
        // end of file: guarantee a separator after the last declaration
        if (tokens.isNotEmpty() && tokens.last().type != TokenType.NEWLINE) {
            tokens.add(Token(TokenType.NEWLINE, "\\n", spanAt(pos)))
        }
        tokens.add(Token(TokenType.EOF, "<eof>", spanAt(pos)))
        return tokens
    }

    // ---- basics ----

    private fun peek(ahead: Int = 0): Char =
        if (pos + ahead < src.length) src[pos + ahead] else ' '

    private fun spanAt(p: Int, len: Int = 1) = Span(baseOffset + p, baseOffset + p + len)

    private fun add(type: TokenType, text: String, len: Int) {
        tokens.add(Token(type, text, spanAt(pos, len)))
        pos += len
    }

    private fun isIdentPart(c: Char) = c.isLetterOrDigit() || c == '_'

    /** Lines ending in these tokens continue onto the next line (spec §1.7). */
    private fun continuesLine(t: TokenType): Boolean = when (t) {
        TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH, TokenType.PERCENT,
        TokenType.PLUSPLUS, TokenType.PIPEGT, TokenType.PIPE, TokenType.AMPAMP, TokenType.PIPEPIPE,
        TokenType.EQEQ, TokenType.NEQ, TokenType.LT, TokenType.LE, TokenType.GT, TokenType.GE,
        TokenType.COMMA, TokenType.LPAREN, TokenType.LBRACKET, TokenType.LBRACE,
        TokenType.ARROW, TokenType.FATARROW, TokenType.EQ, TokenType.COLON, TokenType.DOT,
        TokenType.NOT, TokenType.BANG, TokenType.AT, TokenType.NEWLINE,
        -> true
        else -> false
    }

    private fun emitNewline() {
        if (tokens.isEmpty()) return
        if (continuesLine(tokens.last().type)) return
        tokens.add(Token(TokenType.NEWLINE, "\\n", spanAt(pos)))
    }

    private fun skipComment() {
        while (pos < src.length && src[pos] != '\n') pos++
    }

    // ---- words: keywords / identifiers / type identifiers ----

    private fun lexWord() {
        val start = pos
        while (pos < src.length && isIdentPart(src[pos])) pos++
        val text = src.substring(start, pos)
        val span = Span(baseOffset + start, baseOffset + pos)
        val kw = KEYWORDS[text]
        val type = when {
            kw != null -> kw
            text[0].isUpperCase() -> TokenType.TYPEIDENT
            else -> TokenType.IDENT
        }
        tokens.add(Token(type, text, span))
    }

    // ---- numbers ----

    private fun lexNumber() {
        val start = pos
        if (peek() == '0' && (peek(1) == 'x' || peek(1) == 'b')) {
            val radix = if (peek(1) == 'x') 16 else 2
            pos += 2
            val digits = StringBuilder()
            while (pos < src.length && (src[pos].isLetterOrDigit() || src[pos] == '_')) {
                if (src[pos] != '_') digits.append(src[pos])
                pos++
            }
            val span = Span(baseOffset + start, baseOffset + pos)
            val value = try {
                digits.toString().toLong(radix)
            } catch (e: NumberFormatException) {
                sink.error("invalid integer literal: ${src.substring(start, pos)}", span)
                0L
            }
            tokens.add(Token(TokenType.INT, src.substring(start, pos), span, intValue = value))
            return
        }
        val digits = StringBuilder()
        while (pos < src.length && (src[pos].isDigit() || src[pos] == '_')) {
            if (src[pos] != '_') digits.append(src[pos])
            pos++
        }
        var isFloat = false
        // the 1 in `1..3` is an Int; `1.5` is a Float
        if (peek() == '.' && peek(1).isDigit()) {
            isFloat = true
            digits.append('.')
            pos++
            while (pos < src.length && (src[pos].isDigit() || src[pos] == '_')) {
                if (src[pos] != '_') digits.append(src[pos])
                pos++
            }
        }
        if (peek() == 'e' || peek() == 'E') {
            isFloat = true
            digits.append('e')
            pos++
            if (peek() == '+' || peek() == '-') { digits.append(src[pos]); pos++ }
            while (pos < src.length && src[pos].isDigit()) { digits.append(src[pos]); pos++ }
        }
        val text = src.substring(start, pos)
        val span = Span(baseOffset + start, baseOffset + pos)
        if (isFloat) {
            tokens.add(Token(TokenType.FLOAT, text, span, floatValue = digits.toString().toDouble()))
        } else {
            val value = try {
                digits.toString().toLong()
            } catch (e: NumberFormatException) {
                sink.error("integer literal out of 64-bit range: $text", span)
                0L
            }
            tokens.add(Token(TokenType.INT, text, span, intValue = value))
        }
    }

    // ---- strings (with interpolation segmentation) ----

    private fun lexString() {
        val start = pos
        if (peek(1) == '"' && peek(2) == '"') return lexTripleString()
        pos++ // opening quote
        val segments = ArrayList<StrSegment>()
        val text = StringBuilder()
        while (true) {
            if (pos >= src.length || src[pos] == '\n') {
                throw DawnError("unterminated string", Span(baseOffset + start, baseOffset + pos))
            }
            when (val c = src[pos]) {
                '"' -> { pos++; break }
                '\\' -> lexEscapeInto(text)
                '{' -> {
                    if (text.isNotEmpty()) { segments.add(StrSegment.Text(text.toString())); text.clear() }
                    segments.add(lexInterpolation())
                }
                else -> { text.append(c); pos++ }
            }
        }
        if (text.isNotEmpty()) segments.add(StrSegment.Text(text.toString()))
        val span = Span(baseOffset + start, baseOffset + pos)
        tokens.add(Token(TokenType.STRING, src.substring(start, pos), span, segments = segments))
    }

    /** on entry pos points at '\\'; consumes the escape and appends the character(s) */
    private fun lexEscapeInto(text: StringBuilder) {
        pos++
        when (val e = peek()) {
            'n' -> text.append('\n')
            't' -> text.append('\t')
            '\\' -> text.append('\\')
            '"' -> text.append('"')
            '{' -> text.append('{')
            'u' -> text.append(lexUnicodeEscape())
            else -> throw DawnError("unknown escape: \\$e", spanAt(pos - 1, 2))
        }
        pos++
    }

    /**
     * Multiline string: """ ... """ (spec §1.6). The newline right after the
     * opening quotes and the one before the closing quotes are stripped, as is
     * the common indentation of the non-blank lines. Escapes and interpolation
     * work as in single-line strings; a lone " or "" is content.
     */
    private fun lexTripleString() {
        val start = pos
        pos += 3 // opening """
        val segments = ArrayList<StrSegment>()
        val text = StringBuilder()
        while (true) {
            if (pos >= src.length) {
                throw DawnError("unterminated \"\"\" string", spanAt(start, 3))
            }
            if (src[pos] == '"' && peek(1) == '"' && peek(2) == '"') { pos += 3; break }
            when (src[pos]) {
                '\\' -> lexEscapeInto(text)
                '{' -> {
                    if (text.isNotEmpty()) { segments.add(StrSegment.Text(text.toString())); text.clear() }
                    segments.add(lexInterpolation())
                }
                else -> { text.append(src[pos]); pos++ }
            }
        }
        if (text.isNotEmpty()) segments.add(StrSegment.Text(text.toString()))
        val span = Span(baseOffset + start, baseOffset + pos)
        tokens.add(Token(TokenType.STRING, src.substring(start, pos), span,
            segments = stripTripleIndent(segments)))
    }

    /** Strip the leading/trailing newlines and the common indentation (spec §1.6). */
    private fun stripTripleIndent(segsIn: List<StrSegment>): List<StrSegment> {
        if (segsIn.isEmpty()) return segsIn
        val parts = segsIn.toMutableList()
        (parts.first() as? StrSegment.Text)?.let {
            if (it.value.startsWith("\n")) parts[0] = StrSegment.Text(it.value.removePrefix("\n"))
        }
        (parts.last() as? StrSegment.Text)?.let {
            val i = it.value.lastIndexOf('\n')
            if (i >= 0 && it.value.substring(i + 1).isBlank())
                parts[parts.size - 1] = StrSegment.Text(it.value.substring(0, i))
        }
        // measure: whitespace run at each line start (may end at an interpolation);
        // lines that are pure whitespace don't count
        var minIndent = Int.MAX_VALUE
        var atStart = true
        var runWs = 0
        for (p in parts) {
            when (p) {
                is StrSegment.Code -> {
                    if (atStart) { minIndent = minOf(minIndent, runWs); atStart = false; runWs = 0 }
                }
                is StrSegment.Text -> {
                    var j = 0
                    val v = p.value
                    while (j < v.length) {
                        if (atStart) {
                            while (j < v.length && (v[j] == ' ' || v[j] == '\t')) { runWs++; j++ }
                            if (j >= v.length) break // whitespace continues into the next part
                            if (v[j] == '\n') { atStart = true; runWs = 0; j++ } // blank line
                            else { minIndent = minOf(minIndent, runWs); atStart = false; runWs = 0 }
                        } else {
                            if (v[j] == '\n') { atStart = true; runWs = 0 }
                            j++
                        }
                    }
                }
            }
        }
        if (minIndent == Int.MAX_VALUE || minIndent == 0) return parts.filterNot {
            it is StrSegment.Text && it.value.isEmpty()
        }
        // strip: drop up to minIndent whitespace chars after every line start
        val out = ArrayList<StrSegment>()
        var atStart2 = true
        var toDrop = minIndent
        for (p in parts) {
            when (p) {
                is StrSegment.Code -> { atStart2 = false; toDrop = 0; out.add(p) }
                is StrSegment.Text -> {
                    val sb = StringBuilder()
                    for (c in p.value) {
                        when {
                            atStart2 && toDrop > 0 && (c == ' ' || c == '\t') -> toDrop--
                            c == '\n' -> { atStart2 = true; toDrop = minIndent; sb.append(c) }
                            else -> { atStart2 = false; toDrop = 0; sb.append(c) }
                        }
                    }
                    if (sb.isNotEmpty()) out.add(StrSegment.Text(sb.toString()))
                }
            }
        }
        return out
    }

    private fun lexUnicodeEscape(): String {
        // on entry pos points at 'u'; expects u{HEX}
        if (peek(1) != '{') throw DawnError("\\u must be followed by {codepoint}", spanAt(pos, 2))
        pos += 2
        val hex = StringBuilder()
        while (pos < src.length && src[pos] != '}') { hex.append(src[pos]); pos++ }
        if (peek() != '}') throw DawnError("unterminated \\u{...}", spanAt(pos))
        val code = try {
            hex.toString().toInt(16)
        } catch (e: NumberFormatException) {
            throw DawnError("invalid unicode codepoint: $hex", spanAt(pos - hex.length, hex.length))
        }
        // pos rests on '}'; the caller advances past it
        return String(Character.toChars(code))
    }

    /** On entry pos points at '{'; scans to the matching '}'. Nested strings are skipped over. */
    private fun lexInterpolation(): StrSegment.Code {
        val open = pos
        pos++ // '{'
        val codeStart = pos
        var depth = 1
        while (pos < src.length) {
            when (src[pos]) {
                '{' -> depth++
                '}' -> { depth--; if (depth == 0) break }
                '"' -> skipInnerString()
                '\n' -> throw DawnError("interpolation cannot span lines", spanAt(open))
            }
            pos++
        }
        if (depth != 0) throw DawnError("unmatched { in interpolation", spanAt(open))
        val code = src.substring(codeStart, pos)
        if (code.isBlank()) throw DawnError("empty interpolation", Span(baseOffset + open, baseOffset + pos + 1))
        pos++ // '}'
        return StrSegment.Code(code, baseOffset + codeStart)
    }

    private fun skipInnerString() {
        pos++ // opening quote
        while (pos < src.length && src[pos] != '"') {
            if (src[pos] == '\\') pos++
            pos++
        }
        // rests on the closing quote; the outer loop advances past it
    }

    // ---- symbols ----

    private fun lexSymbol() {
        val two = if (pos + 1 < src.length) src.substring(pos, pos + 2) else ""
        when (two) {
            "->" -> return add(TokenType.ARROW, two, 2)
            "=>" -> return add(TokenType.FATARROW, two, 2)
            "==" -> return add(TokenType.EQEQ, two, 2)
            "!=" -> return add(TokenType.NEQ, two, 2)
            "<=" -> return add(TokenType.LE, two, 2)
            ">=" -> return add(TokenType.GE, two, 2)
            "++" -> return add(TokenType.PLUSPLUS, two, 2)
            "|>" -> return add(TokenType.PIPEGT, two, 2)
            "&&" -> return add(TokenType.AMPAMP, two, 2)
            "||" -> return add(TokenType.PIPEPIPE, two, 2)
            ".." -> return add(TokenType.DOTDOT, two, 2)
        }
        when (val c = peek()) {
            '(' -> add(TokenType.LPAREN, "(", 1)
            ')' -> add(TokenType.RPAREN, ")", 1)
            '{' -> add(TokenType.LBRACE, "{", 1)
            '}' -> add(TokenType.RBRACE, "}", 1)
            '[' -> add(TokenType.LBRACKET, "[", 1)
            ']' -> add(TokenType.RBRACKET, "]", 1)
            ',' -> add(TokenType.COMMA, ",", 1)
            ':' -> add(TokenType.COLON, ":", 1)
            '.' -> add(TokenType.DOT, ".", 1)
            '?' -> add(TokenType.QUESTION, "?", 1)
            '=' -> add(TokenType.EQ, "=", 1)
            '<' -> add(TokenType.LT, "<", 1)
            '>' -> add(TokenType.GT, ">", 1)
            '+' -> add(TokenType.PLUS, "+", 1)
            '-' -> add(TokenType.MINUS, "-", 1)
            '*' -> add(TokenType.STAR, "*", 1)
            '/' -> add(TokenType.SLASH, "/", 1)
            '%' -> add(TokenType.PERCENT, "%", 1)
            '|' -> add(TokenType.PIPE, "|", 1)
            '!' -> add(TokenType.BANG, "!", 1)
            '@' -> add(TokenType.AT, "@", 1)
            else -> {
                sink.error("unrecognized character: $c", spanAt(pos))
                pos++
            }
        }
    }
}
