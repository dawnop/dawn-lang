package dawn

import dawn.check.analyze
import dawn.lsp.completionsAt
import org.eclipse.lsp4j.CompletionItem
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** LSP completion: scope collection and context suppression. The cursor is `‸`. */
class CompletionTest {

    private fun completeAt(sourceWithCursor: String): List<CompletionItem> {
        val pos = sourceWithCursor.indexOf('‸')
        check(pos >= 0) { "no cursor marker in source" }
        val source = sourceWithCursor.replace("‸", "")
        return completionsAt(analyze(source), source, pos)
    }

    private fun labels(items: List<CompletionItem>) = items.map { it.label }.toSet()

    private val program = """
        type Shape =
          | Circle(r: Float)
          | Rect(w: Float, h: Float)

        fn area(s: Shape) -> Float =
          match s {
            Circle(r) -> 3.14159 * r * r
            Rect(w, h) -> w * h
          }

        pub fn main() -> Unit !io = {
          let total = area(Circle(2.0))
          println(to_string(‸))
        }
    """.trimIndent()

    @Test
    fun offersLocalsFunctionsCtorsBuiltinsKeywords() {
        val ls = labels(completeAt(program))
        assertTrue("total" in ls, "local let missing")
        assertTrue("area" in ls, "module fn missing")
        assertTrue("Circle" in ls, "ctor missing")
        assertTrue("Shape" in ls, "type missing")
        assertTrue("println" in ls, "builtin missing")
        assertTrue("match" in ls, "keyword missing")
        assertTrue("Some" in ls, "prelude ctor missing")
    }

    @Test
    fun localsRankFirst() {
        val items = completeAt(program)
        val total = items.first { it.label == "total" }
        val println = items.first { it.label == "println" }
        assertTrue(total.sortText < println.sortText, "locals should sort before builtins")
    }

    @Test
    fun parametersOfTheEnclosingFnComplete() {
        val ls = labels(completeAt("""
            fn area(radius: Float) -> Float = 3.14 * ra‸
        """.trimIndent()))
        assertTrue("radius" in ls)
    }

    @Test
    fun suppressedInStringsAndComments() {
        assertEquals(emptyList(), completeAt("""
            pub fn main() -> Unit !io = println("pri‸")
        """.trimIndent()))
        assertEquals(emptyList(), completeAt("""
            # a comment pri‸
            pub fn main() -> Unit !io = println("x")
        """.trimIndent()))
    }

    @Test
    fun interpolationStillCompletes() {
        val ls = labels(completeAt("""
            pub fn main() -> Unit !io = {
              let name = "dawn"
              println("hi ${'$'}na‸")
            }
        """.trimIndent()))
        assertTrue("name" in ls)
    }

    @Test
    fun suppressedAtFreshNamesUseLinesAndDots() {
        assertEquals(emptyList(), completeAt("fn ma‸"))
        assertEquals(emptyList(), completeAt("use pl‸"))
        assertEquals(emptyList(), completeAt("""
            use java "java.lang.System"

            pub fn main() -> Unit !io = {
              System.ex‸
            }
        """.trimIndent()))
    }

    @Test
    fun bangOffersExactlyIo() {
        val items = completeAt("fn f() -> Unit !‸")
        assertEquals(listOf("io"), items.map { it.label })
    }

    @Test
    fun lambdaParamsCompleteInsideTheLambda() {
        val ls = labels(completeAt("""
            pub fn main() -> Unit !io = {
              let xs = map([1, 2], fn(n) => n‸)
              println(to_string(xs))
            }
        """.trimIndent()))
        assertTrue("n" in ls)
    }

    @Test
    fun underscoreNeverCompletes() {
        assertFalse("_" in labels(completeAt(program)))
    }
}
