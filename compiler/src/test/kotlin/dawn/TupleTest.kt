package dawn

import dawn.check.analyze
import dawn.diag.Diagnostic
import kotlin.test.Test
import kotlin.test.assertTrue

/** M2 tuples: literals, types, patterns, destructuring lets, exhaustiveness. */
class TupleTest {

    private fun errorsOf(source: String): List<Diagnostic> {
        val analysis = analyze(source)
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
    fun `non-exhaustive tuple match is an error`() {
        val diags = errorsOf(
            """
            fn f(p: (Bool, Bool)) -> Int =
              match p {
                (true, true) -> 1
                (false, _)   -> 2
              }
            """.trimIndent(),
        )
        assertHasError(diags, "non-exhaustive")
    }

    @Test
    fun `refutable pattern in let is an error`() {
        val diags = errorsOf(
            """
            fn f(o: Option[Int]) -> Int = {
              let Some(x) = o
              x
            }
            """.trimIndent(),
        )
        assertHasError(diags, "does not always match")
    }

    @Test
    fun `tuple arity mismatch in pattern is an error`() {
        val diags = errorsOf(
            """
            fn f(p: (Int, Int)) -> Int = {
              let (a, b, c) = p
              a
            }
            """.trimIndent(),
        )
        assertHasError(diags, "3 elements but the scrutinee is (Int, Int)")
    }

    @Test
    fun `tuples of functions cannot be compared`() {
        val diags = errorsOf(
            """
            fn f() -> Bool = {
              let a = (1, fn(x: Int) => x)
              let b = (1, fn(x: Int) => x)
              a == b
            }
            """.trimIndent(),
        )
        assertHasError(diags, "functions cannot be compared")
    }

    @Test
    fun `single element tuple is rejected`() {
        val diags = errorsOf(
            """
            fn f() -> Int = {
              let x = (1,)
              1
            }
            """.trimIndent(),
        )
        assertHasError(diags, "a tuple needs at least 2 elements")
    }
}
