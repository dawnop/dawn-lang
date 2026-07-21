package dawn

import dawn.diag.DiagnosticSink
import dawn.lex.Lexer
import kotlin.test.Test
import kotlin.test.assertTrue

/**
 * Lex-level error recovery: malformed literals must become diagnostics, never
 * uncaught JVM exceptions. Both cases here used to crash the compiler (found
 * while porting the lexer to Dawn for self-hosting).
 */
class LexRecoveryTest {

    private fun lexErrors(src: String): List<String> {
        val sink = DiagnosticSink()
        Lexer(src, sink = sink).lex()
        return sink.all.map { it.message }
    }

    @Test
    fun `an out-of-range unicode escape is an error, not a crash`() {
        val errs = lexErrors(""" "\u{FFFFFF}" """)
        assertTrue(errs.any { it == "invalid unicode codepoint: FFFFFF" }, "got: $errs")
    }

    @Test
    fun `a negative unicode escape is an error, not a crash`() {
        val errs = lexErrors(""" "\u{-5}" """)
        assertTrue(errs.any { it == "invalid unicode codepoint: -5" }, "got: $errs")
    }

    @Test
    fun `a float literal with a bare exponent is an error, not a crash`() {
        val errs = lexErrors("let x = 1e")
        assertTrue(errs.any { it == "invalid float literal: 1e" }, "got: $errs")
    }

    @Test
    fun `a float literal with a signed bare exponent is an error, not a crash`() {
        val errs = lexErrors("let x = 2.5e+")
        assertTrue(errs.any { it == "invalid float literal: 2.5e+" }, "got: $errs")
    }
}
