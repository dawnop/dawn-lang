package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import java.lang.reflect.InvocationTargetException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M1 `?` propagation (spec §8.1) and test blocks + assert (spec §3.4). */
class PropagateAndTestTest {

    private fun compileClasses(source: String, includeTests: Boolean = false): Map<String, ByteArray> {
        val analysis = analyze(source)
        check(!analysis.hasErrors) {
            "unexpected compile errors:\n" + analysis.diagnostics.joinToString("\n") { it.message }
        }
        return CodeGen(analysis.module, "testmod", includeTests).generate()
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

    private fun loaderOf(classes: Map<String, ByteArray>) =
        object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }

    private fun run(source: String): String {
        val cls = Class.forName("testmod", false, loaderOf(compileClasses(source)))
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

    // ---- ? propagation ----

    @Test
    fun resultPropagation() {
        val out = run("""
            fn parse_digit(s: String) -> Result[Int, String] =
              match s {
                "0" -> Ok(0)
                "1" -> Ok(1)
                "2" -> Ok(2)
                _   -> Err("not a digit: " ++ s)
              }

            fn add_digits(a: String, b: String) -> Result[Int, String] = {
              let x = parse_digit(a)?
              let y = parse_digit(b)?
              Ok(x + y)
            }

            fn show(r: Result[Int, String]) -> String =
              match r {
                Ok(v)  -> "ok {v}"
                Err(m) -> "err: {m}"
              }

            pub fn main() -> Unit !io = {
              println(show(add_digits("1", "2")))
              println(show(add_digits("1", "x")))
            }
        """.trimIndent())
        assertEquals("ok 3\nerr: not a digit: x\n", out)
    }

    @Test
    fun optionPropagation() {
        val out = run("""
            fn both_first(a: List[Int], b: List[Int]) -> Option[Int] = {
              let x = get(a, 0)?
              let y = get(b, 0)?
              Some(x + y)
            }

            fn show(o: Option[Int]) -> String =
              match o {
                Some(v) -> "{v}"
                None    -> "none"
              }

            pub fn main() -> Unit !io = {
              println(show(both_first([1], [2])))
              println(show(both_first([1], [])))
            }
        """.trimIndent())
        assertEquals("3\nnone\n", out)
    }

    @Test
    fun propagateNeedsMatchingReturn() {
        val diags = errorsOf("""
            fn f(o: Option[Int]) -> Int = o? + 1

            pub fn main() -> Unit !io = println("{f(Some(1))}")
        """.trimIndent())
        assertHasError(diags, "`?` on an Option requires the function to return Option")
    }

    @Test
    fun propagateErrorTypesMustMatch() {
        val diags = errorsOf("""
            fn inner() -> Result[Int, Int] = Ok(1)

            fn outer() -> Result[Int, String] = Ok(inner()?)

            pub fn main() -> Unit !io = println("ok")
        """.trimIndent())
        assertHasError(diags, "`?` error types differ")
    }

    @Test
    fun propagateRejectedInLambda() {
        val diags = errorsOf("""
            fn f(xs: List[Option[Int]]) -> Option[Int] = {
              let ys = map(xs, fn(o) => o? + 1)
              get([], 0)
            }

            pub fn main() -> Unit !io = println("ok")
        """.trimIndent())
        assertHasError(diags, "`?` cannot be used inside a lambda")
    }

    @Test
    fun propagateOnNonOptionRejected() {
        val diags = errorsOf("""
            fn f(x: Int) -> Option[Int] = Some(x?)

            pub fn main() -> Unit !io = println("ok")
        """.trimIndent())
        assertHasError(diags, "`?` needs an Option or Result, got Int")
    }

    // ---- test blocks + assert ----

    @Test
    fun testBlocksRunAndReport() {
        val source = """
            fn add(a: Int, b: Int) -> Int = a + b

            pub fn main() -> Unit !io = println("app")

            test "addition works" {
              assert add(2, 2) == 4
            }

            test "this one fails" {
              assert add(2, 2) == 5
            }
        """.trimIndent()
        val cls = Class.forName("testmod", false, loaderOf(compileClasses(source, includeTests = true)))
        // test 0 passes
        cls.getDeclaredMethod("dawn\$test\$0").invoke(null)
        // test 1 fails with a message showing source text and both sides
        try {
            cls.getDeclaredMethod("dawn\$test\$1").invoke(null)
            throw AssertionError("expected the failing test to panic")
        } catch (e: InvocationTargetException) {
            val msg = e.cause!!.message!!
            assertTrue(msg.contains("assertion failed: add(2, 2) == 5"), msg)
            assertTrue(msg.contains("left  = 4"), msg)
            assertTrue(msg.contains("right = 5"), msg)
        }
    }

    @Test
    fun buildStripsTests() {
        val source = """
            pub fn main() -> Unit !io = println("app")

            test "not in builds" {
              assert true
            }
        """.trimIndent()
        val cls = Class.forName("testmod", false, loaderOf(compileClasses(source, includeTests = false)))
        assertTrue(cls.declaredMethods.none { it.name.startsWith("dawn\$test") })
    }

    @Test
    fun testsMayUseIo() {
        val source = """
            fn greet(name: String) -> String = "hi, " ++ name

            test "io is fine in tests" {
              println(greet("dawn"))
              assert greet("x") == "hi, x"
            }
        """.trimIndent()
        val cls = Class.forName("testmod", false, loaderOf(compileClasses(source, includeTests = true)))
        cls.getDeclaredMethod("dawn\$test\$0").invoke(null)
    }

    @Test
    fun assertOutsideTestRejected() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              assert 1 == 1
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "`assert` is only allowed inside test blocks")
    }
}
