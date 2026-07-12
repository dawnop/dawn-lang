package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M2: use java interop (spec §9). */
class JavaInteropTest {

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
    fun `static call with int narrowing and long overload ranking`() {
        val out = run(
            """
            use java "java.lang.Math"

            pub fn main() -> Unit !io = {
              println("${'$'}{Math.abs(0 - 7)}")
              println("${'$'}{Math.max(3, 9)}")
              println("${'$'}{Math.floor(2.7)}")
            }
            """.trimIndent(),
        )
        // abs/max pick the long overloads (exact match beats int narrowing)
        assertEquals("7\n9\n2.0\n", out)
    }

    @Test
    fun `java calls are io`() {
        val diags = errorsOf(
            """
            use java "java.lang.Math"

            fn f(x: Float) -> Float = Math.sqrt(x)
            """.trimIndent(),
        )
        assertHasError(diags, "not declared !io")
    }

    @Test
    fun `unknown class and unknown method are reported`() {
        val diags = errorsOf(
            """
            use java "java.lang.NoSuchClassHere"
            """.trimIndent(),
        )
        assertHasError(diags, "Java class not found")

        val diags2 = errorsOf(
            """
            use java "java.lang.Math"
            fn f() -> Int !io = Math.frobnicate(1)
            """.trimIndent(),
        )
        assertHasError(diags2, "has no static method `frobnicate`")
    }

    @Test
    fun `Files round-trip through java interop`() {
        val path = java.io.File.createTempFile("dawn-java-", ".txt").absolutePath
        val out = run(
            """
            use java "java.nio.file.Files"
            use java "java.nio.file.Path"

            pub fn main() -> Unit !io = {
              let p = Path.of("$path").expect("path")
              let _ = Files.writeString(p, "from dawn")
              println(Files.readString(p).expect("read"))
            }
            """.trimIndent(),
        )
        assertEquals("from dawn\n", out)
        java.io.File(path).delete()
    }
}
