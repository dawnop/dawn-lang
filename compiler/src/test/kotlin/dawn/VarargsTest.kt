package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M7: passing variadic arguments to Java varargs methods (spec §9.3). */
class VarargsTest {

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
        val main = loader.loadClass("testmod").getMethod("main")
        val buf = ByteArrayOutputStream()
        val saved = System.out
        try {
            System.setOut(PrintStream(buf, true))
            main.invoke(null)
        } finally {
            System.setOut(saved)
        }
        return buf.toString()
    }

    @Test
    fun `variadic arguments are packed into the trailing array`() {
        val out = run(
            """
            use java "java.nio.file.Path"

            pub fn main() -> Unit !io =
              println(Path.of("a", "b", "c").expect("path").toString().expect("s"))
            """.trimIndent(),
        )
        assertEquals("a/b/c\n", out)
    }

    @Test
    fun `omitting the variable part still supplies an empty array`() {
        val out = run(
            """
            use java "java.nio.file.Path"

            pub fn main() -> Unit !io =
              println(Path.of("solo").expect("path").toString().expect("s"))
            """.trimIndent(),
        )
        assertEquals("solo\n", out)
    }

    /**
     * List.of has fixed-arity overloads up to 10 plus of(E...); 11 arguments leave
     * only the variadic one, so this is packing and nothing else.
     */
    @Test
    fun `packing preserves element order and count past the fixed-arity overloads`() {
        val out = run(
            """
            use java "java.util.List"

            pub fn main() -> Unit !io = {
              let l = List.of("a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k").expect("list")
              println("${'$'}{l.size()}")
              println(l.get(0).expect("e0").toString().expect("s"))
              println(l.get(10).expect("e10").toString().expect("s"))
            }
            """.trimIndent(),
        )
        assertEquals("11\na\nk\n", out)
    }

    /**
     * The phase rule earns its keep here (spec §9.3): `of(E, E)` and `of(E...)` both
     * score 2 for two String arguments — a tie, i.e. "ambiguous call", if the phase
     * did not decide first. Phase 1 (no packing) wins, as in Java.
     */
    @Test
    fun `a fixed-arity overload beats an equally scoring variadic one`() {
        val out = run(
            """
            use java "java.util.List"

            pub fn main() -> Unit !io = {
              let l = List.of("a", "b").expect("list")
              println("${'$'}{l.size()}")
            }
            """.trimIndent(),
        )
        assertEquals("2\n", out)
    }

    /** The knife this was sharpened for: a multipart body whose parts stream (M7). */
    @Test
    fun `BodyPublishers concat takes its publishers variadically`() {
        val out = run(
            """
            use java "java.net.http.HttpRequest.BodyPublishers"

            pub fn main() -> Unit !io = {
              let a = BodyPublishers.ofString("hello").expect("a")
              let b = BodyPublishers.ofString("!").expect("b")
              let both = BodyPublishers.concat(a, b).expect("concat")
              println("${'$'}{both.contentLength()}")
            }
            """.trimIndent(),
        )
        assertEquals("6\n", out)
    }

    @Test
    fun `an argument that does not fit the component type is rejected`() {
        val diags = errorsOf(
            """
            use java "java.nio.file.Path"

            fn f() -> Unit !io = {
              let _ = Path.of("a", 1)
            }
            """.trimIndent(),
        )
        assertHasError(diags, "no overload of `Path.of` matches")
    }

    /**
     * Dawn scalars do not box (spec §9.2), so an `Object...` component takes String
     * and Java references but not Int/Float/Bool. That boundary is orthogonal to
     * varargs; this pins it so the error stays honest rather than silently drifting.
     */
    @Test
    fun `an Object component does not box a Dawn scalar`() {
        val diags = errorsOf(
            """
            use java "java.util.List"

            fn f() -> Unit !io = {
              let _ = List.of(1, 2, 3)
            }
            """.trimIndent(),
        )
        assertHasError(diags, "no overload of `List.of` matches")
    }
}
