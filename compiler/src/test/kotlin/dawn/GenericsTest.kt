package dawn

import dawn.check.analyze
import dawn.diag.Diagnostic
import kotlin.test.Test
import kotlin.test.assertTrue

/** M1 generics: type parameters, erasure+boxing, Option/Result prelude, List. */
class GenericsTest {

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

    // ---- Option / Result prelude ----

    // ---- generic user types ----

    // ---- lists ----

    // ---- diagnostics ----

    @Test
    fun bareNoneNeedsContext() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let x = None
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "cannot infer type parameter(s) T for `None`")
    }

    @Test
    fun emptyListNeedsAnnotation() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let xs = []
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "cannot infer the element type of an empty list")
    }

    @Test
    fun typeArgumentArity() {
        val diags = errorsOf("""
            type Box[T] = | Full(v: T) | Empty

            fn f(a: Box, b: List[Int, Int], c: Int[Float]) -> Int = 0

            pub fn main() -> Unit !io = println("${'$'}{f(Empty, [1], 2)}")
        """.trimIndent())
        assertHasError(diags, "`Box` takes 1 type parameter(s), got 0")
        assertHasError(diags, "List takes exactly one type argument")
        assertHasError(diags, "`Int` is not generic")
    }

    @Test
    fun genericArgumentMismatch() {
        val diags = errorsOf("""
            fn want_str(o: Option[String]) -> Int = 0

            pub fn main() -> Unit !io = println("${'$'}{want_str(Some(1))}")
        """.trimIndent())
        // expected-type seeding pins T = String, so the error lands on Some's field
        assertHasError(diags, "field `value` of `Some` is String, got Int")
    }

    @Test
    fun listConcatElementMismatch() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let a = [1] ++ ["x"]
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "`++` needs lists of the same element type")
    }

    @Test
    fun preludeCannotBeRedefined() {
        val diags = errorsOf("""
            type Option = | Yes | No

            pub fn main() -> Unit !io = println("ok")
        """.trimIndent())
        assertHasError(diags, "`Option` is a prelude type and cannot be redefined")
    }

    @Test
    fun optionExhaustivenessWithArgs() {
        val diags = errorsOf("""
            fn f(o: Option[Int]) -> Int =
              match o {
                Some(v) -> v
              }

            pub fn main() -> Unit !io = println("${'$'}{f(None)}")
        """.trimIndent())
        assertHasError(diags, "non-exhaustive match, missing: None")
    }
}
