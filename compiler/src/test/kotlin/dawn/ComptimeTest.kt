package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M2: const declarations and comptime blocks (spec §3.2, §7). */
class ComptimeTest {

    private fun compileClasses(source: String, fuel: Long = 100_000_000L): Map<String, ByteArray> {
        val analysis = analyze(source, fuel)
        check(!analysis.hasErrors) {
            "unexpected compile errors:\n" + analysis.diagnostics.joinToString("\n") { it.message }
        }
        return CodeGen(analysis.module, "testmod").generate()
    }

    private fun errorsOf(source: String, fuel: Long = 100_000_000L): List<Diagnostic> {
        val analysis = analyze(source, fuel)
        assertTrue(analysis.hasErrors, "expected compile errors, got none")
        return analysis.diagnostics
    }

    private fun assertHasError(diags: List<Diagnostic>, substring: String) {
        assertTrue(
            diags.any { it.message.contains(substring) },
            "no diagnostic contains \"$substring\"; got:\n" + diags.joinToString("\n") { it.message },
        )
    }

    private fun run(source: String, fuel: Long = 100_000_000L): String {
        val classes = compileClasses(source, fuel)
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
    fun `scalar consts inline and print`() {
        val out = run(
            """
            const MAX_DEPTH: Int = 64
            const GREETING: String = "hi " ++ "there"
            const RATIO: Float = 1.0 / 4.0

            pub fn main() -> Unit !io = println("${'$'}{MAX_DEPTH} ${'$'}{GREETING} ${'$'}{RATIO}")
            """.trimIndent(),
        )
        assertEquals("64 hi there 0.25\n", out)
    }

    @Test
    fun `const may call pure functions and earlier consts`() {
        val out = run(
            """
            fn square(x: Int) -> Int = x * x

            const BASE: Int = 7
            const AREA: Int = square(BASE)

            pub fn main() -> Unit !io = println("${'$'}{AREA}")
            """.trimIndent(),
        )
        assertEquals("49\n", out)
    }

    @Test
    fun `structured const materializes once as a static field`() {
        val out = run(
            """
            const TABLE: List[Int] = comptime {
              range(0, 5) |> map(fn(x) => x * x)
            }

            pub fn main() -> Unit !io = {
              match TABLE.get(4) {
                Some(v) -> println("${'$'}v")
                None -> println("?")
              }
              println("${'$'}{len(TABLE)}")
            }
            """.trimIndent(),
        )
        assertEquals("16\n5\n", out)
    }

    @Test
    fun `comptime block inside a function body`() {
        val out = run(
            """
            fn fib(n: Int) -> Int = {
              var a = 0
              var b = 1
              for _i in 0..n {
                let (x, y) = (b, a + b)
                a = x
                b = y
              }
              a
            }

            pub fn main() -> Unit !io = println("${'$'}{comptime { fib(30) }}")
            """.trimIndent(),
        )
        assertEquals("832040\n", out)
    }

    @Test
    fun `comptime handles ADTs tuples strings and match`() {
        val out = run(
            """
            const BANNER: String = comptime {
              "calc (" ++ join(map(range(0, 3), to_string), ".") ++ ")"
            }
            const PAIR: (Int, String) = comptime { (42, "answer") }
            const FOUND: Option[Int] = comptime {
              [1, 2, 3] |> filter(fn(x) => x % 2 == 0) |> get(0)
            }

            pub fn main() -> Unit !io = {
              println(BANNER)
              let (n, s) = PAIR
              println("${'$'}n ${'$'}s")
              match FOUND {
                Some(v) -> println("even: ${'$'}v")
                None -> println("none")
              }
            }
            """.trimIndent(),
        )
        assertEquals("calc (0.1.2)\n42 answer\neven: 2\n", out)
    }

    @Test
    fun `io in a const initializer is rejected`() {
        val diags = errorsOf(
            """
            const OOPS: String = { println("side effect")
              "x" }
            """.trimIndent(),
        )
        assertHasError(diags, "must be pure")
    }

    @Test
    fun `comptime result must be serializable`() {
        val diags = errorsOf(
            """
            fn f() -> Int = {
              let g = comptime { fn(x: Int) => x }
              g(1)
            }
            """.trimIndent(),
        )
        assertHasError(diags, "constant-serializable")
    }

    @Test
    fun `enclosing locals are not visible inside comptime`() {
        val diags = errorsOf(
            """
            fn f(n: Int) -> Int = comptime { n * 2 }
            """.trimIndent(),
        )
        assertHasError(diags, "undefined variable: n")
    }

    @Test
    fun `const referencing a later const is an error with a hint`() {
        val diags = errorsOf(
            """
            const A: Int = B + 1
            const B: Int = 2
            """.trimIndent(),
        )
        assertTrue(diags.any { it.hint?.contains("top to bottom") == true },
            "expected the evaluation-order hint; got:\n" + diags.joinToString("\n") { "${it.message} | ${it.hint}" })
    }

    @Test
    fun `comptime panic becomes a compile error`() {
        val diags = errorsOf(
            """
            const BAD: Int = comptime { 1 / 0 }
            """.trimIndent(),
        )
        assertHasError(diags, "division by zero")
    }

    @Test
    fun `fuel exhaustion is reported, not looped forever`() {
        val diags = errorsOf(
            """
            fn spin() -> Int = {
              var i = 0
              while true { i = i + 1 }
              i
            }
            const HOT: Int = comptime { spin() }
            """.trimIndent(),
            fuel = 10_000,
        )
        assertHasError(diags, "fuel exhausted")
    }

    @Test
    fun `lowercase const name is rejected`() {
        val diags = errorsOf(
            """
            const MaxDepth: Int = 3
            """.trimIndent(),
        )
        assertHasError(diags, "SCREAMING_SNAKE_CASE")
    }
}
