package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M2: triple-quoted multiline strings (spec §1.6). */
class MultilineStringTest {

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
    fun `edge newlines and common indent are stripped`() {
        val out = run(
            "pub fn main() -> Unit !io = {\n" +
                "  let s = \"\"\"\n" +
                "    line one\n" +
                "      indented\n" +
                "    line three\n" +
                "    \"\"\"\n" +
                "  println(s)\n" +
                "}\n",
        )
        assertEquals("line one\n  indented\nline three\n", out)
    }

    @Test
    fun `blank lines survive and do not affect the indent`() {
        val out = run(
            "pub fn main() -> Unit !io = {\n" +
                "  let s = \"\"\"\n" +
                "    a\n" +
                "\n" +
                "    b\n" +
                "    \"\"\"\n" +
                "  println(s)\n" +
                "}\n",
        )
        assertEquals("a\n\nb\n", out)
    }

    @Test
    fun `interpolation and inner quotes work in multiline strings`() {
        val out = run(
            "pub fn main() -> Unit !io = {\n" +
                "  let n = 7\n" +
                "  let s = \"\"\"\n" +
                "    value: ${'$'}{n * 2}\n" +
                "    quote: \"quoted\"\n" +
                "    \"\"\"\n" +
                "  println(s)\n" +
                "}\n",
        )
        assertEquals("value: 14\nquote: \"quoted\"\n", out)
    }

    @Test
    fun `a line starting with interpolation sets the indent floor`() {
        val out = run(
            "pub fn main() -> Unit !io = {\n" +
                "  let x = 1\n" +
                "  let s = \"\"\"\n" +
                "      deep\n" +
                "    ${'$'}{x} shallow\n" +
                "    \"\"\"\n" +
                "  println(s)\n" +
                "}\n",
        )
        assertEquals("  deep\n1 shallow\n", out)
    }

    @Test
    fun `unterminated triple string is an error`() {
        val diags = errorsOf(
            "pub fn main() -> Unit !io = {\n" +
                "  let s = \"\"\"\n" +
                "    never closed\n",
        )
        assertTrue(diags.any { it.message.contains("unterminated") },
            "got: " + diags.joinToString("\n") { it.message })
    }
}
