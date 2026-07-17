package dawn.lex

import dawn.diag.Span

enum class TokenType {
    // literals and identifiers
    INT, FLOAT, STRING, IDENT, TYPEIDENT,
    // keywords
    FN, LET, VAR, TYPE, CONST, USE, JAVA, PUB,
    TRAIT, IMPL,
    MATCH, IF, ELSE, FOR, IN, WHILE, RETURN,
    COMPTIME, TEST, ASSERT, TRUE, FALSE, NOT,
    // symbols
    LPAREN, RPAREN, LBRACE, RBRACE, LBRACKET, RBRACKET,
    COMMA, COLON, DOT, DOTDOT, QUESTION, UNDERSCORE,
    ARROW,      // ->
    FATARROW,   // =>
    EQ,         // =
    EQEQ, NEQ, LT, LE, GT, GE,
    PLUS, MINUS, STAR, SLASH, PERCENT,
    PLUSPLUS,   // ++
    PIPEGT,     // |>
    PIPE,       // |
    AMPAMP,     // &&
    PIPEPIPE,   // ||
    BANG,       // !
    AT,         // @
    NEWLINE, EOF,
    COMMENT,    // # ... (collected only for `dawn fmt`; never enters the parser's stream)
}

/** A piece of a string literal: literal text, or an interpolation (code + its offset in the file). */
sealed class StrSegment {
    data class Text(val value: String) : StrSegment()
    data class Code(val source: String, val offset: Int) : StrSegment()
}

class Token(
    val type: TokenType,
    val text: String,
    val span: Span,
    /** value of an INT token */
    val intValue: Long = 0,
    /** value of a FLOAT token */
    val floatValue: Double = 0.0,
    /** segments of a STRING token */
    val segments: List<StrSegment> = emptyList(),
) {
    override fun toString() = "$type($text)"
}

val KEYWORDS: Map<String, TokenType> = mapOf(
    "fn" to TokenType.FN, "let" to TokenType.LET, "var" to TokenType.VAR,
    "type" to TokenType.TYPE, "const" to TokenType.CONST, "use" to TokenType.USE,
    "java" to TokenType.JAVA, "pub" to TokenType.PUB,
    "trait" to TokenType.TRAIT, "impl" to TokenType.IMPL,
    "match" to TokenType.MATCH, "if" to TokenType.IF, "else" to TokenType.ELSE,
    "for" to TokenType.FOR, "in" to TokenType.IN, "while" to TokenType.WHILE,
    "return" to TokenType.RETURN,
    "comptime" to TokenType.COMPTIME, "test" to TokenType.TEST, "assert" to TokenType.ASSERT,
    "true" to TokenType.TRUE, "false" to TokenType.FALSE, "not" to TokenType.NOT,
)
