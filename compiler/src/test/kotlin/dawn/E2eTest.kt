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

/** End to end: source → bytecode → in-process execution, asserting on stdout. */
class E2eTest {

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

    /** Invokes dawn's main()V directly (not the JVM entry wrapper, whose System.exit would kill the test JVM). */
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

    private fun runExpectPanic(source: String): String {
        return try {
            run(source)
            throw AssertionError("expected a panic, but the program finished normally")
        } catch (e: InvocationTargetException) {
            val cause = e.cause!!
            assertEquals("dawn.rt.PanicError", cause.javaClass.name)
            cause.message ?: ""
        }
    }

    // ---- happy paths ----

    @Test
    fun tailRecursionDoesNotGrowStack() {
        // ten million frames: guaranteed StackOverflow without tail-call elimination
        val out = run("""
            fn countdown(n: Int, acc: Int) -> Int =
              if n == 0 { acc } else { countdown(n - 1, acc + 1) }

            pub fn main() -> Unit !io = println("${'$'}{countdown(10000000, 0)}")
        """.trimIndent())
        assertEquals("10000000\n", out)
    }

    @Test
    fun panicMessage() {
        val msg = runExpectPanic("""
            pub fn main() -> Unit !io = panic("boom: ${'$'}{1 + 1}")
        """.trimIndent())
        assertEquals("boom: 2", msg)
    }

    // ---- compile errors ----

    @Test
    fun missingIoDeclarationIsError() {
        val diags = errorsOf("""
            fn sneaky() -> Unit = println("hi")
            pub fn main() -> Unit !io = sneaky()
        """.trimIndent())
        assertHasError(diags, "not declared !io")
    }

    @Test
    fun ioPropagatesThroughSignatures() {
        // greet declares !io, so a pure function calling it must be an error
        val diags = errorsOf("""
            fn greet(name: String) -> Unit !io = println(name)
            fn caller() -> Unit = greet("x")
            pub fn main() -> Unit !io = caller()
        """.trimIndent())
        assertHasError(diags, "not declared !io")
    }

    @Test
    fun discardingValueIsError() {
        val diags = errorsOf("""
            fn f() -> Int = 1
            pub fn main() -> Unit !io = {
              f()
              println("done")
            }
        """.trimIndent())
        assertHasError(diags, "discarded")
    }

    @Test
    fun assigningToLetIsError() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let x = 1
              x = 2
              println("${'$'}x")
            }
        """.trimIndent())
        assertHasError(diags, "cannot be assigned")
    }

    @Test
    fun nonExhaustiveMatchIsError() {
        val diags = errorsOf("""
            fn f(n: Int) -> String = match n { 0 -> "zero" }
            pub fn main() -> Unit !io = println(f(1))
        """.trimIndent())
        assertHasError(diags, "non-exhaustive")
    }

    @Test
    fun noImplicitConversion() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = println("${'$'}{1 + 2.0}")
        """.trimIndent())
        assertHasError(diags, "same type")
    }

    @Test
    fun mixedGuardsNeedFallback() {
        // arms that all carry guards do not count as exhaustive
        val diags = errorsOf("""
            fn f(n: Int) -> Int = match n { x if x > 0 -> x }
            pub fn main() -> Unit !io = println("${'$'}{f(1)}")
        """.trimIndent())
        assertHasError(diags, "non-exhaustive")
    }
}
