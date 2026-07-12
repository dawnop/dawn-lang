package dawn

import dawn.check.analyze
import dawn.diag.Diagnostic
import kotlin.test.Test
import kotlin.test.assertTrue

/** M1 ADTs: declarations, construction, matching, exhaustiveness, structural equality. */
class AdtTest {

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

    private val shapePrelude = """
        type Shape =
          | Circle(r: Float)
          | Rect(w: Float, h: Float)
          | Point
    """.trimIndent()

    // ---- happy paths ----

    // ---- diagnostics ----

    @Test
    fun nonExhaustiveListsMissingCtors() {
        val diags = errorsOf("""
            $shapePrelude

            fn f(s: Shape) -> Int =
              match s {
                Circle(r) -> 1
              }

            pub fn main() -> Unit !io = println("${'$'}{f(Point)}")
        """.trimIndent())
        assertHasError(diags, "non-exhaustive match, missing: Rect, Point")
    }

    @Test
    fun guardedArmDoesNotCountAsCoverage() {
        val diags = errorsOf("""
            type Color = | Red | Blue

            fn f(c: Color) -> Int =
              match c {
                Red if true -> 1
                Blue        -> 2
              }

            pub fn main() -> Unit !io = println("${'$'}{f(Red)}")
        """.trimIndent())
        assertHasError(diags, "non-exhaustive match, missing: Red")
    }

    @Test
    fun undefinedConstructor() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let x = Bogus(1)
              println("x")
            }
        """.trimIndent())
        assertHasError(diags, "undefined constructor: Bogus")
    }

    @Test
    fun arityAndFieldErrors() {
        val diags = errorsOf("""
            $shapePrelude

            pub fn main() -> Unit !io = {
              let a = Rect(1.0)
              let b = Rect(1.0, 2.0, 3.0)
              let c = Rect(1.0, x: 2.0)
              let d = Rect(w: 1.0, 2.0)
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "missing field(s) in `Rect`: h")
        assertHasError(diags, "`Rect` takes 2 field(s), got 3")
        assertHasError(diags, "`Rect` has no field `x`")
        assertHasError(diags, "positional arguments cannot follow named arguments")
    }

    @Test
    fun fieldTypeMismatch() {
        val diags = errorsOf("""
            $shapePrelude

            pub fn main() -> Unit !io = {
              let a = Circle(1)
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "field `r` of `Circle` is Float, got Int")
    }

    @Test
    fun bareCtorWithFieldsRejected() {
        val diags = errorsOf("""
            $shapePrelude

            pub fn main() -> Unit !io = {
              let a = Circle
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "has 1 field(s) and cannot be used bare")
    }

    @Test
    fun patternMustMentionAllFieldsOrRest() {
        val diags = errorsOf("""
            $shapePrelude

            fn f(s: Shape) -> Float =
              match s {
                Rect(w) -> w
                _       -> 0.0
              }

            pub fn main() -> Unit !io = println("${'$'}{f(Point)}")
        """.trimIndent())
        assertHasError(diags, "pattern for `Rect` does not mention: h")
    }

    @Test
    fun wrongAdtInPattern() {
        val diags = errorsOf("""
            $shapePrelude
            type Color = | Red | Blue

            fn f(s: Shape) -> Int =
              match s {
                Red -> 1
                _   -> 0
              }

            pub fn main() -> Unit !io = println("${'$'}{f(Point)}")
        """.trimIndent())
        assertHasError(diags, "`Red` is a Color constructor, but the scrutinee is Shape")
    }

    @Test
    fun orPatternBindingsRejectedInsideCtors() {
        val diags = errorsOf("""
            $shapePrelude

            fn f(s: Shape) -> Float =
              match s {
                Circle(r) | Rect(r, ..) -> r
                _ -> 0.0
              }

            pub fn main() -> Unit !io = println("${'$'}{f(Point)}")
        """.trimIndent())
        assertHasError(diags, "or-pattern alternatives cannot introduce bindings")
    }

    @Test
    fun duplicateTypesAndCtors() {
        val diags = errorsOf("""
            type A = | X
            type A = | Y
            type B = | X

            pub fn main() -> Unit !io = println("ok")
        """.trimIndent())
        assertHasError(diags, "type `A` is defined twice")
        assertHasError(diags, "constructor `X` is already defined")
    }

    @Test
    fun adtCannotInterpolate() {
        val diags = errorsOf("""
            $shapePrelude

            pub fn main() -> Unit !io = println("${'$'}{Point}")
        """.trimIndent())
        assertHasError(diags, "cannot interpolate a value of type Shape")
    }
}
