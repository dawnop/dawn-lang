package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M2 tuples: literals, types, patterns, destructuring lets, exhaustiveness. */
class TupleTest {

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
    fun `tuple literal, return type, destructuring let`() {
        val out = run(
            """
            fn divmod(a: Int, b: Int) -> (Int, Int) = (a / b, a % b)

            pub fn main() -> Unit !io = {
              let (q, r) = divmod(17, 5)
              println("${'$'}q rem ${'$'}r")
            }
            """.trimIndent(),
        )
        assertEquals("3 rem 2\n", out)
    }

    @Test
    fun `var destructuring rebinds mutably`() {
        val out = run(
            """
            fn step(p: (Int, Int)) -> (Int, Int) = {
              let (a, b) = p
              (b, a + b)
            }

            pub fn main() -> Unit !io = {
              var (x, y) = (0, 1)
              while x < 20 {
                let (nx, ny) = step((x, y))
                x = nx
                y = ny
              }
              println("${'$'}x ${'$'}y")
            }
            """.trimIndent(),
        )
        assertEquals("21 34\n", out)
    }

    @Test
    fun `tuple structural equality`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              let a = (1, "x", true)
              let b = (1, "x", true)
              let c = (2, "x", true)
              println("${'$'}{a == b} ${'$'}{a == c}")
            }
            """.trimIndent(),
        )
        assertEquals("true false\n", out)
    }

    @Test
    fun `match on tuple with literal subpatterns and exhaustiveness`() {
        val out = run(
            """
            fn describe(p: (Int, Bool)) -> String =
              match p {
                (0, true)  -> "origin on"
                (0, false) -> "origin off"
                (n, _)     -> "at ${'$'}n"
              }

            pub fn main() -> Unit !io = {
              println(describe((0, true)))
              println(describe((0, false)))
              println(describe((7, true)))
            }
            """.trimIndent(),
        )
        assertEquals("origin on\norigin off\nat 7\n", out)
    }

    @Test
    fun `nested tuple in Option and record destructure`() {
        val out = run(
            """
            type Pair = { fst: Int, snd: String }

            fn find(k: Int) -> Option[(Int, String)] =
              if k == 1 { Some((10, "ten")) } else { None }

            pub fn main() -> Unit !io = {
              match find(1) {
                Some((n, s)) -> println("${'$'}n=${'$'}s")
                None -> println("missing")
              }
              let Pair { fst, snd } = Pair { fst: 5, snd: "five" }
              println("${'$'}fst ${'$'}snd")
            }
            """.trimIndent(),
        )
        assertEquals("10=ten\n5 five\n", out)
    }

    @Test
    fun `tuples flow through generics boxed`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              let pairs = map(range(0, 3), fn(i) => (i, i * i))
              for p in pairs {
                let (a, b) = p
                println("${'$'}a:${'$'}b")
              }
            }
            """.trimIndent(),
        )
        assertEquals("0:0\n1:1\n2:4\n", out)
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
