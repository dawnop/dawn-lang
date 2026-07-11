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
    fun `head and rest, recursive sum`() {
        val out = run(
            """
            fn sum(xs: List[Int]) -> Int =
              match xs {
                [] -> 0
                [x, ..rest] -> x + sum(rest)
              }

            pub fn main() -> Unit !io = println("{sum([1, 2, 3, 4])}")
            """.trimIndent(),
        )
        assertEquals("10\n", out)
    }

    @Test
    fun `suffix rest binds the init, last element matched`() {
        val out = run(
            """
            fn shape(xs: List[Int]) -> String =
              match xs {
                []              -> "empty"
                [..init, 9]     -> "ends in nine, init len {len(init)}"
                [..init, last]  -> "last {last} after {len(init)}"
              }

            pub fn main() -> Unit !io = {
              println(shape([]))
              println(shape([1, 2, 9]))
              println(shape([1, 2, 3]))
            }
            """.trimIndent(),
        )
        assertEquals("empty\nends in nine, init len 2\nlast 3 after 2\n", out)
    }

    @Test
    fun `fixed length and anonymous rest`() {
        val out = run(
            """
            fn f(xs: List[String]) -> String =
              match xs {
                [a, b]      -> "pair {a}{b}"
                [a, .., z]  -> "{a}..{z}"
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
    fun `nested constructor patterns inside a list pattern`() {
        val out = run(
            """
            type Tok = | Num(v: Int) | Plus

            fn last_num(toks: List[Tok]) -> Int =
              match toks {
                [..init, Num(v)] -> v
                _ -> -1
              }

            pub fn main() -> Unit !io = {
              println("{last_num([Num(1), Plus, Num(7)])}")
              println("{last_num([Num(1), Plus])}")
            }
            """.trimIndent(),
        )
        assertEquals("7\n-1\n", out)
    }

    @Test
    fun `empty plus head-rest is exhaustive without a wildcard`() {
        val out = run(
            """
            fn describe(xs: List[Int]) -> String =
              match xs {
                [] -> "none"
                [_, ..rest] -> "some, {len(rest)} more"
              }

            pub fn main() -> Unit !io = println(describe([5, 6, 7]))
            """.trimIndent(),
        )
        assertEquals("some, 2 more\n", out)
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
