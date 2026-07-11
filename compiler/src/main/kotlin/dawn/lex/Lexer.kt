package dawn.lex

import dawn.diag.DawnError
import dawn.diag.Span

/**
 * Lexer. spec §1.
 *
 * Newline rule: a newline yields a NEWLINE token acting as the statement separator,
 * except when the line ends with an "unfinished" token (binary operator, comma,
 * opening bracket, ->, =>, =, |>, ...), in which case the newline is swallowed
 * (automatic continuation). Consecutive NEWLINEs collapse into one. The parser
 * additionally skips insignificant NEWLINEs (block start/end etc.) itself.
 */
class Lexer(private val src: String, private val baseOffset: Int = 0) {

    private var pos = 0
    private val tokens = ArrayList<Token>()

    fun lex(): List<Token> {
        while (pos < src.length) {
            val c = src[pos]
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
                throw DawnError("invalid integer literal: ${src.substring(start, pos)}", span)
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
                throw DawnError("integer literal out of 64-bit range: $text", span)
            }
            tokens.add(Token(TokenType.INT, text, span, intValue = value))
        }
    }

    // ---- strings (with interpolation segmentation) ----

    private fun lexString() {
        val start = pos
        if (peek(1) == '"' && peek(2) == '"') {
            throw DawnError("multiline strings (\"\"\") are not implemented in v0.1", spanAt(pos, 3))
        }
        pos++ // opening quote
        val segments = ArrayList<StrSegment>()
        val text = StringBuilder()
        while (true) {
            if (pos >= src.length || src[pos] == '\n') {
                throw DawnError("unterminated string", Span(baseOffset + start, baseOffset + pos))
            }
            when (val c = src[pos]) {
                '"' -> { pos++; break }
                '\\' -> {
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
            else -> throw DawnError("unrecognized character: $c", spanAt(pos))
        }
    }
}
