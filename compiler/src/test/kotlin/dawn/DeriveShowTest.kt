package dawn

import dawn.check.analyze
import kotlin.test.Test
import kotlin.test.assertTrue

/** M3: `derive Show` — generated to_string / interpolation for user types (spec §4.3). */
class DeriveShowTest {

    private fun assertHasError(source: String, substring: String) {
        val analysis = analyze(source)
        assertTrue(analysis.hasErrors, "expected compile errors, got none")
        assertTrue(
            analysis.diagnostics.any { it.message.contains(substring) || (it.hint ?: "").contains(substring) },
            "no diagnostic mentions \"$substring\"; got:\n" +
                analysis.diagnostics.joinToString("\n") { it.message + " | " + (it.hint ?: "") },
        )
    }

    @Test
    fun `printing a type without derive Show is rejected`() {
        assertHasError(
            """
            type Color = | Red | Green

            pub fn main() -> Unit !io = println(to_string(Red))
            """.trimIndent(),
            "add `derive Show`",
        )
    }

    @Test
    fun `interpolating a type without derive Show is rejected`() {
        assertHasError(
            """
            type Color = | Red | Green

            pub fn main() -> Unit !io = println("c = ${'$'}{Red}")
            """.trimIndent(),
            "add `derive Show`",
        )
    }

    @Test
    fun `deriving Show with a function field is rejected at the declaration`() {
        assertHasError(
            """
            type Bad = | Bad(f: fn(Int) -> Int) derive Show

            pub fn main() -> Unit !io = println("x")
            """.trimIndent(),
            "not printable",
        )
    }

    @Test
    fun `deriving Show requires nested user types to also derive Show`() {
        assertHasError(
            """
            type Inner = | A | B
            type Outer = | Outer(i: Inner) derive Show

            pub fn main() -> Unit !io = println("x")
            """.trimIndent(),
            "add `derive Show` to `type Inner`",
        )
    }

    @Test
    fun `only Show and Ord can be derived`() {
        assertHasError(
            """
            type Color = | Red | Green derive Eq

            pub fn main() -> Unit !io = println("x")
            """.trimIndent(),
            "Show and Ord can be derived",
        )
    }
}
