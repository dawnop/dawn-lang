package dawn

import dawn.check.analyze
import dawn.diag.Diagnostic
import kotlin.test.Test
import kotlin.test.assertTrue

/** M1 records: literals, shorthand, functional update, field access, record patterns. */
class RecordTest {

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

    private val pointPrelude = """
        type Point = { x: Float, y: Float }
    """.trimIndent()

    // ---- happy paths ----

    // ---- diagnostics ----

    @Test
    fun missingFieldWithoutSpread() {
        val diags = errorsOf("""
            $pointPrelude

            pub fn main() -> Unit !io = {
              let p = Point { x: 1.0 }
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "missing field(s) in `Point`: y")
    }

    @Test
    fun unknownFieldInLiteralAndAccess() {
        val diags = errorsOf("""
            $pointPrelude

            pub fn main() -> Unit !io = {
              let p = Point { x: 1.0, y: 2.0, z: 3.0 }
              let q = Point { x: 1.0, y: 2.0 }
              println("${'$'}{q.z}")
            }
        """.trimIndent())
        assertHasError(diags, "`Point` has no field `z`")
    }

    @Test
    fun fieldAccessOnNonRecord() {
        val diags = errorsOf("""
            type Color = | Red | Blue

            fn f(c: Color) -> Int = c.x

            pub fn main() -> Unit !io = println("${'$'}{f(Red)}")
        """.trimIndent())
        assertHasError(diags, "field access needs a record value")
    }

    @Test
    fun spreadOnSumTypeRejected() {
        val diags = errorsOf("""
            type Shape = | Circle(r: Float) | Point

            pub fn main() -> Unit !io = {
              let c = Circle(1.0)
              let d = Circle { ..c, r: 2.0 }
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "`..base` functional update only works on records")
    }

    @Test
    fun spreadTypeMismatch() {
        val diags = errorsOf("""
            type Point = { x: Float, y: Float }
            type Size = { w: Float, h: Float }

            pub fn main() -> Unit !io = {
              let s = Size { w: 1.0, h: 2.0 }
              let p = Point { ..s, x: 3.0 }
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "`..base` must be a Point, got Size")
    }

    @Test
    fun recordNeedsBraces() {
        val diags = errorsOf("""
            $pointPrelude

            pub fn main() -> Unit !io = {
              let p = Point
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "record `Point` must be built with braces")
    }
}
