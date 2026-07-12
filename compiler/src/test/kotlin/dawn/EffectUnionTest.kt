package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M3: effect unions `!(e1|e2)` — a higher-order function forwarding two arguments' effects. */
class EffectUnionTest {

    // a compose whose result effect is the union of its two function arguments' effects
    private val compose =
        """
        fn compose[A, B, C](f: fn(A) -> B !e1, g: fn(B) -> C !e2) -> fn(A) -> C !(e1 | e2) =
          fn(a) => g(f(a))

        fn inc(x: Int) -> Int = x + 1
        fn dbl(x: Int) -> Int = x * 2
        fn tag(x: Int) -> String !io = {
          println("tag ${'$'}x")
          "n${'$'}x"
        }
        """.trimIndent()

    private fun run(source: String): String {
        val analysis = analyze(source)
        check(!analysis.hasErrors) {
            "unexpected compile errors:\n" + analysis.diagnostics.joinToString("\n") { it.message }
        }
        val classes = CodeGen(analysis.module, "testmod").generate()
        val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }
        val cls = Class.forName("testmod", false, loader)
        val buf = ByteArrayOutputStream()
        val old = System.out
        System.setOut(PrintStream(buf, true, "UTF-8"))
        try {
            cls.getDeclaredMethod("main").invoke(null)
        } finally {
            System.setOut(old)
        }
        return buf.toString("UTF-8")
    }

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
    fun `union of two pure functions normalizes to pure and is callable in a pure context`() {
        val out = run(
            """
            $compose

            fn usePure() -> Int = {
              let p = compose(inc, dbl)
              p(5)
            }

            pub fn main() -> Unit !io = println(to_string(usePure()))
            """.trimIndent(),
        )
        assertEquals("12\n", out) // (5 + 1) * 2
    }

    @Test
    fun `a pure function may not call an io-composed result`() {
        assertHasError(
            """
            $compose

            fn bad() -> String = {
              let p = compose(inc, tag)
              p(5)
            }

            pub fn main() -> Unit !io = println(bad())
            """.trimIndent(),
            "not declared !io",
        )
    }

    @Test
    fun `the effect union renders as !(e1|e2) in diagnostics`() {
        assertHasError(
            """
            $compose

            pub fn main() -> Unit !io = {
              let p = compose(inc)
              println("unreachable")
            }
            """.trimIndent(),
            "!(e1|e2)",
        )
    }

    @Test
    fun `same variable unioned with itself collapses to a single variable`() {
        // applyTwice composes a function with itself; the result effect is just !e, not !(e|e)
        val out = run(
            """
            fn twice[A](f: fn(A) -> A !e) -> fn(A) -> A !e =
              fn(a) => f(f(a))

            fn inc(x: Int) -> Int = x + 1

            fn usePure() -> Int = {
              let g = twice(inc)
              g(10)
            }

            pub fn main() -> Unit !io = println(to_string(usePure()))
            """.trimIndent(),
        )
        assertEquals("12\n", out)
    }

    @Test
    fun `three-way effect union`() {
        val out = run(
            """
            fn compose3[A, B, C, D](
              f: fn(A) -> B !e1,
              g: fn(B) -> C !e2,
              h: fn(C) -> D !e3,
            ) -> fn(A) -> D !(e1 | e2 | e3) =
              fn(a) => h(g(f(a)))

            fn inc(x: Int) -> Int = x + 1
            fn dbl(x: Int) -> Int = x * 2
            fn neg(x: Int) -> Int = 0 - x

            fn usePure() -> Int = {
              let p = compose3(inc, dbl, neg)
              p(3)
            }

            pub fn main() -> Unit !io = println(to_string(usePure()))
            """.trimIndent(),
        )
        assertEquals("-8\n", out) // neg(dbl(inc(3))) = neg(dbl(4)) = neg(8) = -8
    }
}
