package dawn.fmt

import dawn.diag.DiagnosticSink
import dawn.lex.Lexer
import dawn.lex.Token
import dawn.lex.TokenType
import dawn.lex.TokenType.*

/**
 * `dawn fmt`: a token-stream reformatter. It re-lexes the source (collecting
 * comments), then reprints every token verbatim — from its source span, so
 * strings and interpolations are byte-for-byte untouched — changing only the
 * whitespace between tokens: intra-line spacing, 2-space indentation, and
 * blank-line collapsing. It preserves the author's physical line breaks.
 *
 * Because only whitespace changes, formatting is token-preserving and
 * idempotent by construction; it needs only a successful lex (not a parse), so
 * even syntactically broken files format.
 */
object Formatter {

    fun format(source: String): String {
        val comments = ArrayList<Token>()
        val code = Lexer(source, 0, DiagnosticSink(), comments).lex()
            .filter { it.type != NEWLINE && it.type != EOF }
        val stream = (code + comments).sortedBy { it.span.start }
        if (stream.isEmpty()) return ""
        return reflow(source, stream, unaryMinus(code))
    }

    /** Set of MINUS tokens that are unary (prefix), so they hug the following operand. */
    private fun unaryMinus(code: List<Token>): Set<Token> {
        val out = HashSet<Token>()
        for ((i, t) in code.withIndex()) {
            if (t.type != MINUS) continue
            val before = code.getOrNull(i - 1)
            if (before == null || before.type !in valueEnd) out.add(t)
        }
        return out
    }

    private fun reflow(src: String, toks: List<Token>, unary: Set<Token>): String {
        val sb = StringBuilder()
        val openers = ArrayDeque<Int>() // indent (in levels) of the line each still-open bracket sits on
        var lineIndent = 0              // indent of the line currently being emitted
        var lineFirst: Token = toks[0]  // first token of the current line (for use-path spacing)
        var prev: Token? = null
        for (t in toks) {
            if (prev == null) {
                sb.append(text(src, t))
            } else {
                val nl = countNewlines(src, prev.span.end, t.span.start)
                if (nl == 0) {
                    val onUseLine = lineFirst.type == USE
                    if (t.type == COMMENT || space(prev, t, unary, onUseLine)) sb.append(' ')
                    sb.append(text(src, t))
                } else {
                    lineFirst = t
                    repeat(1 + minOf(nl - 1, 1)) { sb.append('\n') } // collapse ≥2 blank lines to 1
                    lineIndent = indentOf(t, openers, prev)
                    sb.append("  ".repeat(lineIndent.coerceAtLeast(0)))
                    sb.append(text(src, t))
                }
            }
            when (t.type) {
                LPAREN, LBRACKET, LBRACE -> openers.addLast(lineIndent)
                RPAREN, RBRACKET, RBRACE -> if (openers.isNotEmpty()) openers.removeLast()
                else -> {}
            }
            prev = t
        }
        sb.append('\n')
        return sb.toString()
    }

    /** Indent (2-space levels) for a line whose first token is [t]; [prevLineLast] ended the previous line. */
    private fun indentOf(t: Token, openers: ArrayDeque<Int>, prevLineLast: Token): Int {
        val content = (openers.lastOrNull() ?: -1) + 1
        return when {
            t.type in closers -> openers.lastOrNull() ?: 0 // align a leading closer with its opener line
            isContinuation(prevLineLast, t) -> content + 1
            else -> content
        }
    }

    private fun isContinuation(prevLineLast: Token, lineStart: Token): Boolean =
        prevLineLast.type in continuationEnders || lineStart.type in continuationStarters

    // ---- spacing between two tokens already known to be on the same line ----

    private fun space(prev: Token, cur: Token, unary: Set<Token>, onUseLine: Boolean = false): Boolean {
        val p = prev.type
        val c = cur.type
        // a module path prints tight: use greet/words.{Lang, greet} (spec §10.2)
        if (onUseLine && (p == SLASH || c == SLASH || p == LBRACE || c == RBRACE)) return false
        return when {
            // openers hug what follows; closers/commas/colons/? hug what precedes
            p == LPAREN || p == LBRACKET -> false
            c == RPAREN || c == RBRACKET -> false
            c == COMMA || c == COLON -> false
            c == QUESTION -> false
            // member access and effect/attribute markers
            p == DOT || c == DOT -> false
            p == DOTDOT -> false
            p == BANG -> false
            p == AT -> false
            // calls / indexing / generics: name(..), name[..], no space before the bracket
            c == LPAREN && p in callableBeforeParen -> false
            c == LBRACKET && p in valueEnd -> false
            // unary minus hugs its operand
            prev in unary -> false
            else -> true
        }
    }

    // ---- helpers ----

    private fun text(src: String, t: Token): String =
        if (t.type == COMMENT) t.text else src.substring(t.span.start, t.span.end)

    private fun countNewlines(src: String, from: Int, to: Int): Int {
        var n = 0
        var i = from
        while (i < to && i < src.length) { if (src[i] == '\n') n++; i++ }
        return n
    }

    private val closers = setOf(RPAREN, RBRACKET, RBRACE)

    private val valueEnd = setOf(
        IDENT, TYPEIDENT, INT, FLOAT, STRING, RPAREN, RBRACKET, TRUE, FALSE, QUESTION, UNDERSCORE,
    )

    private val callableBeforeParen = setOf(IDENT, TYPEIDENT, RPAREN, RBRACKET, QUESTION, FN)

    private val continuationEnders = setOf(
        PLUS, MINUS, STAR, SLASH, PERCENT, PLUSPLUS, PIPEGT, AMPAMP, PIPEPIPE,
        EQEQ, NEQ, LT, LE, GT, GE, ARROW, FATARROW, EQ, DOT, NOT, BANG,
    )

    private val continuationStarters = setOf(
        PIPEGT, DOT, PIPE, PLUS, MINUS, STAR, SLASH, PERCENT, PLUSPLUS, AMPAMP, PIPEPIPE,
        EQEQ, NEQ, LT, LE, GT, GE,
    )
}
