package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * `unsafe_pure { expr }` — the pure-FFI escape hatch (docs/pure-ffi-design.md).
 * It masks a concrete !io effect down to Pure so a Java interop call can back a
 * pure function, refuses to mask an effect *variable* (the guard that forces
 * higher-order code onto the pure-Dawn-recursion path), flags a redundant stamp,
 * and is transparent at runtime.
 */
class UnsafePureTest {

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

    private fun errorsOf(source: String): List<String> {
        val analysis = analyze(source)
        assertTrue(analysis.hasErrors, "expected compile errors, got none")
        return analysis.diagnostics.map { it.message }
    }

    private fun okOf(source: String) {
        val analysis = analyze(source)
        assertTrue(!analysis.hasErrors,
            "expected no compile errors, got:\n" + analysis.diagnostics.joinToString("\n") { it.message })
    }

    @Test
    fun `a bare Java call cannot back a pure function`() {
        // baseline: without the stamp the checker flags the interop call !io
        val errs = errorsOf(
            """
            use java "java.lang.Math"
            pub fn maxi(a: Int, b: Int) -> Int = Math.max(a, b)
            """.trimIndent(),
        )
        assertTrue(errs.any { it.contains("!io") && it.contains("maxi") },
            "expected an !io rejection on maxi; got:\n" + errs.joinToString("\n"))
    }

    @Test
    fun `unsafe_pure lets a Java call back a pure function`() {
        okOf(
            """
            use java "java.lang.Math"
            pub fn maxi(a: Int, b: Int) -> Int = unsafe_pure { Math.max(a, b) }
            """.trimIndent(),
        )
    }

    @Test
    fun `a pure caller may use the vouched wrapper and stay pure`() {
        okOf(
            """
            use java "java.lang.Math"
            pub fn maxi(a: Int, b: Int) -> Int = unsafe_pure { Math.max(a, b) }
            pub fn clamp_low(x: Int) -> Int = maxi(x, 0)
            const LIMIT: Int = 0
            """.trimIndent(),
        )
    }

    @Test
    fun `the wrapped call runs transparently at runtime`() {
        val out = run(
            """
            use java "java.lang.Math"
            pub fn maxi(a: Int, b: Int) -> Int = unsafe_pure { Math.max(a, b) }
            pub fn main() -> Unit !io = println("${'$'}{maxi(3, 7)}")
            """.trimIndent(),
        )
        assertEquals("7\n", out)
    }

    @Test
    fun `unsafe_pure refuses to mask an effect variable`() {
        val errs = errorsOf(
            """
            pub fn wrap[T](f: fn() -> T !e) -> T = unsafe_pure { f() }
            """.trimIndent(),
        )
        assertTrue(errs.any { it.contains("effect variable") },
            "expected the effect-variable guard; got:\n" + errs.joinToString("\n"))
    }

    @Test
    fun `an already-pure block is flagged redundant`() {
        val errs = errorsOf(
            """
            pub fn twice(n: Int) -> Int = unsafe_pure { n + n }
            """.trimIndent(),
        )
        assertTrue(errs.any { it.contains("redundant unsafe_pure") },
            "expected the redundant-stamp lint; got:\n" + errs.joinToString("\n"))
    }

    /**
     * Route C (docs/pure-ffi-design.md 阶段3): a vouched Java call folds at
     * compile time by reflective invoke. This is what keeps "pure ⟺
     * comptime-foldable" true as builtins migrate into std — a const does not
     * care which side of that line its callee sits on.
     */
    @Test
    fun `a vouched java call folds at compile time`() {
        val out = run(
            """
            use java "java.lang.Math"
            const BIG: Int = unsafe_pure { Math.max(1, 2) }
            pub fn main() -> Unit !io = println("${'$'}{BIG}")
            """.trimIndent(),
        )
        assertEquals("2\n", out)
    }

    @Test
    fun `route C marshals strings and honours null as None`() {
        val out = run(
            """
            use java "java.lang.String"
            const S: String = unsafe_pure { String.valueOf(true) }.expect("never null")
            pub fn main() -> Unit !io = println(S)
            """.trimIndent(),
        )
        assertEquals("true\n", out)
    }

    @Test
    fun `folding refuses arguments route C cannot marshal`() {
        val errs = errorsOf(
            """
            use java "java.util.List"
            const N: Int = unsafe_pure { List.of(1, 2) }.expect("x") == 0
            """.trimIndent(),
        )
        assertTrue(errs.isNotEmpty(), "expected the marshalling refusal, got none")
    }
}
