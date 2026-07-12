package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * `return` — early return from the enclosing function (or lambda). Typed
 * Never: usable in any expression position, guard-clause style.
 */
class ReturnTest {

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

    // ---- happy paths ----

    @Test
    fun guardClauseReturnsEarly() {
        val out = run("""
            fn classify(n: Int) -> String = {
              if n < 0 { return "negative" }
              if n == 0 { return "zero" }
              "positive"
            }

            pub fn main() -> Unit !io = {
              println(classify(0 - 5))
              println(classify(0))
              println(classify(7))
            }
        """.trimIndent())
        assertEquals("negative\nzero\npositive\n", out)
    }

    @Test
    fun bareReturnExitsAUnitFunction() {
        val out = run("""
            fn maybe_print(n: Int) -> Unit !io = {
              if n < 0 { return }
              println(to_string(n))
            }

            pub fn main() -> Unit !io = {
              maybe_print(0 - 1)
              maybe_print(42)
            }
        """.trimIndent())
        assertEquals("42\n", out)
    }

    @Test
    fun returnsPrimitiveAndReferenceTypes() {
        val out = run("""
            fn pick(b: Bool) -> Int = {
              if b { return 1 }
              2
            }

            fn half(x: Float) -> Float = {
              if x < 0.0 { return 0.0 }
              x / 2.0
            }

            fn first(xs: List[Int]) -> Option[Int] = {
              if len(xs) == 0 { return None }
              Some(xs[0])
            }

            pub fn main() -> Unit !io = {
              println(to_string(pick(true)))
              println(to_string(half(5.0)))
              println(to_string(first([9])))
            }
        """.trimIndent())
        assertEquals("1\n2.5\nSome(9)\n", out)
    }

    @Test
    fun returnInsideALambdaExitsTheLambda() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let f: fn(Int) -> Int = fn(x) => {
                if x < 0 { return 0 }
                x * 2
              }
              println(to_string(f(0 - 9)))
              println(to_string(f(21)))
            }
        """.trimIndent())
        assertEquals("0\n42\n", out)
    }

    @Test
    fun returnInMatchArm() {
        val out = run("""
            fn describe(o: Option[Int]) -> String = {
              let n = match o {
                None -> return "nothing"
                Some(v) -> v
              }
              "got ${'$'}n"
            }

            pub fn main() -> Unit !io = {
              println(describe(None))
              println(describe(Some(3)))
            }
        """.trimIndent())
        assertEquals("nothing\ngot 3\n", out)
    }

    @Test
    fun returnInComptime() {
        val out = run("""
            fn pick(n: Int) -> Int = {
              if n > 10 { return 100 }
              n
            }

            const BIG: Int = comptime { pick(50) }

            pub fn main() -> Unit !io = println(to_string(BIG))
        """.trimIndent())
        assertEquals("100\n", out)
    }

    @Test
    fun genericReturnBoxesCorrectly() {
        val out = run("""
            fn first_or[T](xs: List[T], fallback: T) -> T = {
              if len(xs) == 0 { return fallback }
              xs[0]
            }

            pub fn main() -> Unit !io = {
              println(to_string(first_or([7], 0)))
              println(first_or([], "empty"))
            }
        """.trimIndent())
        assertEquals("7\nempty\n", out)
    }

    // ---- diagnostics ----

    @Test
    fun returnTypeMismatchIsAnError() {
        val diags = errorsOf("""
            fn f(n: Int) -> Int = {
              if n < 0 { return "no" }
              n
            }

            pub fn main() -> Unit !io = println(to_string(f(1)))
        """.trimIndent())
        assertHasError(diags, "`return` type mismatch")
    }

    @Test
    fun bareReturnInANonUnitFunctionIsAnError() {
        val diags = errorsOf("""
            fn f(n: Int) -> Int = {
              if n < 0 { return }
              n
            }

            pub fn main() -> Unit !io = println(to_string(f(1)))
        """.trimIndent())
        assertHasError(diags, "`return` type mismatch")
    }

    @Test
    fun returnOutsideAFunctionIsAnError() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = println("x")

            test "no returns here" {
              return
            }
        """.trimIndent())
        assertHasError(diags, "`return` can only be used inside a function")
    }
}
