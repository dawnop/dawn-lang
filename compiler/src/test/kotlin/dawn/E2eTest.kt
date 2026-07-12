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
    fun hello() {
        val out = run("""
            pub fn main() -> Unit !io = println("hello, dawn")
        """.trimIndent())
        assertEquals("hello, dawn\n", out)
    }

    @Test
    fun fibRecursionAndInterpolation() {
        val out = run("""
            fn fib(n: Int) -> Int =
              if n < 2 { n } else { fib(n - 1) + fib(n - 2) }

            pub fn main() -> Unit !io = println("fib(20) = ${'$'}{fib(20)}")
        """.trimIndent())
        assertEquals("fib(20) = 6765\n", out)
    }

    @Test
    fun matchGuardsOrPatternsStrings() {
        val out = run("""
            fn judge(n: Int) -> String =
              match n {
                0 | 1      -> "tiny"
                x if x < 0 -> "negative"
                100        -> "century"
                _          -> "normal"
              }

            fn color(name: String) -> String =
              match name {
                "red"  -> "#f00"
                "blue" -> "#00f"
                other  -> "unknown: " ++ other
              }

            pub fn main() -> Unit !io = {
              println(judge(0))
              println(judge(-5))
              println(judge(100))
              println(judge(42))
              println(color("red"))
              println(color("cyan"))
            }
        """.trimIndent())
        assertEquals("tiny\nnegative\ncentury\nnormal\n#f00\nunknown: cyan\n", out)
    }

    @Test
    fun matchOnFloatLiterals() {
        val out = run("""
            fn kind(x: Float) -> String =
              match x {
                0.0  -> "zero"
                -1.5 -> "negative three halves"
                _    -> "other"
              }

            pub fn main() -> Unit !io = {
              println(kind(0.0))
              println(kind(-1.5))
              println(kind(2.0))
            }
        """.trimIndent())
        assertEquals("zero\nnegative three halves\nother\n", out)
    }

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
    fun loopsVarsAndFor() {
        val out = run("""
            pub fn main() -> Unit !io = {
              var sum = 0
              for i in 1..101 {
                sum = sum + i
              }
              var n = 3
              while n > 0 {
                n = n - 1
              }
              println("sum=${'$'}sum n=${'$'}n")
            }
        """.trimIndent())
        assertEquals("sum=5050 n=0\n", out)
    }

    @Test
    fun ifAsValueAndBlockValue() {
        val out = run("""
            fn abs(n: Int) -> Int = if n < 0 { -n } else { n }

            pub fn main() -> Unit !io = {
              let x = {
                let a = abs(-7)
                a * 2
              }
              println("${'$'}x")
            }
        """.trimIndent())
        assertEquals("14\n", out)
    }

    @Test
    fun floatsAndComparisons() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let pi = 3.14
              let tau = pi * 2.0
              println("${'$'}tau")
              println("${'$'}{1.5 < 2.5} ${'$'}{"a" < "b"} ${'$'}{3 >= 3}")
            }
        """.trimIndent())
        assertEquals("6.28\ntrue true true\n", out)
    }

    @Test
    fun stringConcatAndEquality() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let s = "foo" ++ "bar"
              println("${'$'}{s == "foobar"} ${'$'}{s != "x"} ${'$'}{not (s == "x")}")
            }
        """.trimIndent())
        assertEquals("true true true\n", out)
    }

    @Test
    fun pipeOperator() {
        val out = run("""
            fn double(n: Int) -> Int = n * 2
            fn plus(a: Int, b: Int) -> Int = a + b

            pub fn main() -> Unit !io = {
              let r = 5 |> double |> plus(3)
              println("${'$'}r")
            }
        """.trimIndent())
        assertEquals("13\n", out)
    }

    @Test
    fun verticalPipeStyle() {
        val out = run("""
            fn double(n: Int) -> Int = n * 2

            pub fn main() -> Unit !io = {
              let r = 5
                |> double
                |> double
              println("${'$'}r")
            }
        """.trimIndent())
        assertEquals("20\n", out)
    }

    @Test
    fun panicMessage() {
        val msg = runExpectPanic("""
            pub fn main() -> Unit !io = panic("boom: ${'$'}{1 + 1}")
        """.trimIndent())
        assertEquals("boom: 2", msg)
    }

    @Test
    fun panicAsNeverInBranch() {
        val out = run("""
            fn safe_div(a: Int, b: Int) -> Int =
              if b == 0 { panic("div by zero") } else { a / b }

            pub fn main() -> Unit !io = println("${'$'}{safe_div(10, 2)}")
        """.trimIndent())
        assertEquals("5\n", out)
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
    fun boolMatchTrueAndFalseIsExhaustive() {
        val out = run("""
            fn yn(b: Bool) -> String = match b { true -> "y", false -> "n" }
            pub fn main() -> Unit !io = println(yn(true) ++ yn(false))
        """.trimIndent())
        assertEquals("yn\n", out)
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
