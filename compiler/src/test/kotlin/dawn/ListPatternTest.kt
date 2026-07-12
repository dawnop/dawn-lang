package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M2 list patterns: [], [x, ..rest], [..init, last], exhaustiveness over lengths. */
class ListPatternTest {

    private fun compileClasses(source: String): Map<String, ByteArray> {
        val analysis = analyze(source)
        check(!analysis.hasErrors) {
            "unexpected compile errors:\n" + analysis.diagnostics.joinToString("\n") { it.message }
        }
        return CodeGen(analysis.module, "testmod").generate()
    }

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

    private fun run(source: String): String {
        val classes = compileClasses(source)
        val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }
        val cls = Class.forName("testmod", false, loader)
        val m = cls.getDeclaredMethod("main")
        val buf = ByteArrayOutputStream()
        val old = System.out
        System.setOut(PrintStream(buf, true, "UTF-8"))
        try {
            m.invoke(null)
        } finally {
            System.setOut(old)
        }
        return buf.toString("UTF-8")
    }

    @Test
    fun `fixed length and anonymous rest`() {
        val out = run(
            """
            fn f(xs: List[String]) -> String =
              match xs {
                [a, b]      -> "pair ${'$'}a${'$'}b"
                [a, .., z]  -> "${'$'}a..${'$'}z"
                [..]        -> "other"
              }

            pub fn main() -> Unit !io = {
              println(f(["x", "y"]))
              println(f(["a", "m", "n", "z"]))
              println(f(["solo"]))
            }
            """.trimIndent(),
        )
        // [a, .., z] needs at least two elements; a single element falls to [..]
        assertEquals("pair xy\na..z\nother\n", out)
    }

    @Test
    fun `missing lengths are reported`() {
        val diags = errorsOf(
            """
            fn f(xs: List[Int]) -> Int =
              match xs {
                [x] -> x
                [a, b, ..] -> a + b
              }
            """.trimIndent(),
        )
        assertHasError(diags, "non-exhaustive")
        assertHasError(diags, "[]")
    }

    @Test
    fun `list pattern in let must be rest-only`() {
        val diags = errorsOf(
            """
            fn f(xs: List[Int]) -> Int = {
              let [x, ..rest] = xs
              x
            }
            """.trimIndent(),
        )
        assertHasError(diags, "does not always match")
    }

    @Test
    fun `two rests are rejected`() {
        val diags = errorsOf(
            """
            fn f(xs: List[Int]) -> Int =
              match xs {
                [..a, ..b] -> 0
                _ -> 1
              }
            """.trimIndent(),
        )
        assertHasError(diags, "at most one")
    }

    @Test
    fun `list pattern against a non-list is an error`() {
        val diags = errorsOf(
            """
            fn f(x: Int) -> Int =
              match x {
                [a] -> a
                _ -> 0
              }
            """.trimIndent(),
        )
        assertHasError(diags, "list pattern does not match scrutinee type Int")
    }
}
