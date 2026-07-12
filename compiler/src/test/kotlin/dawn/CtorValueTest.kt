package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M3: constructors used as first-class function values, e.g. `map(xs, Some)`. */
class CtorValueTest {

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
        val diags: List<Diagnostic> = analysis.diagnostics
        assertTrue(
            diags.any { it.message.contains(substring) },
            "no diagnostic contains \"$substring\"; got:\n" + diags.joinToString("\n") { it.message },
        )
    }

    @Test
    fun `mapped Some values carry their payloads`() {
        // sum the wrapped values back out via fold to prove the payloads survived
        val out = run(
            """
            fn addOpt(acc: Int, o: Option[Int]) -> Int =
              match o { Some(v) -> acc + v  None -> acc }

            pub fn main() -> Unit !io = {
              let ys = map([10, 20, 30], Some)
              println(to_string(fold(ys, 0, addOpt)))
            }
            """.trimIndent(),
        )
        assertEquals("60\n", out)
    }

    @Test
    fun `nullary constructor rejected where a function is expected`() {
        assertHasError(
            """
            pub fn main() -> Unit !io = {
              let ys = map([1, 2], None)
              println("unreachable")
            }
            """.trimIndent(),
            "is a value, not a function",
        )
    }

    @Test
    fun `constructor arity mismatch against expected function type`() {
        assertHasError(
            """
            type Pair = | Pair(a: Int, b: Int)

            pub fn main() -> Unit !io = {
              let ys = map([1, 2], Pair)
              println("unreachable")
            }
            """.trimIndent(),
            "takes 2 field(s)",
        )
    }

}
