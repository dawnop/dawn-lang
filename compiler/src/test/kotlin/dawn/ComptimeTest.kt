package dawn

import dawn.check.analyze
import dawn.diag.Diagnostic
import kotlin.test.Test
import kotlin.test.assertTrue

/** M2: const declarations and comptime blocks (spec §3.2, §7). */
class ComptimeTest {

    private fun errorsOf(source: String, fuel: Long = 100_000_000L): List<Diagnostic> {
        val analysis = analyze(source, fuel)
        assertTrue(analysis.hasErrors, "expected compile errors, got none")
        return analysis.diagnostics
    }

    private fun assertHasError(diags: List<Diagnostic>, substring: String) {
        assertTrue(
            diags.any { it.message.contains(substring) },
            "no diagnostic contains \"$substring\"; got:\n" + diags.joinToString("\n") { it.message },
        )
    }

    @Test
    fun `io in a const initializer is rejected`() {
        val diags = errorsOf(
            """
            const OOPS: String = { println("side effect")
              "x" }
            """.trimIndent(),
        )
        assertHasError(diags, "must be pure")
    }

    @Test
    fun `comptime result must be serializable`() {
        val diags = errorsOf(
            """
            fn f() -> Int = {
              let g = comptime { fn(x: Int) => x }
              g(1)
            }
            """.trimIndent(),
        )
        assertHasError(diags, "constant-serializable")
    }

    @Test
    fun `enclosing locals are not visible inside comptime`() {
        val diags = errorsOf(
            """
            fn f(n: Int) -> Int = comptime { n * 2 }
            """.trimIndent(),
        )
        assertHasError(diags, "undefined variable: n")
    }

    @Test
    fun `const referencing a later const is an error with a hint`() {
        val diags = errorsOf(
            """
            const A: Int = B + 1
            const B: Int = 2
            """.trimIndent(),
        )
        assertTrue(diags.any { it.hint?.contains("top to bottom") == true },
            "expected the evaluation-order hint; got:\n" + diags.joinToString("\n") { "${it.message} | ${it.hint}" })
    }

    @Test
    fun `comptime panic becomes a compile error`() {
        val diags = errorsOf(
            """
            const BAD: Int = comptime { 1 / 0 }
            """.trimIndent(),
        )
        assertHasError(diags, "division by zero")
    }

    @Test
    fun `fuel exhaustion is reported, not looped forever`() {
        val diags = errorsOf(
            """
            fn spin() -> Int = {
              var i = 0
              while true { i = i + 1 }
              i
            }
            const HOT: Int = comptime { spin() }
            """.trimIndent(),
            fuel = 10_000,
        )
        assertHasError(diags, "fuel exhausted")
    }

    @Test
    fun `lowercase const name is rejected`() {
        val diags = errorsOf(
            """
            const MaxDepth: Int = 3
            """.trimIndent(),
        )
        assertHasError(diags, "SCREAMING_SNAKE_CASE")
    }
}
