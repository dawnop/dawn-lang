package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M4 knife 6: character literals as code points + the code-point string API (spec §1.5, §11). */
class CharTest {

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

    @Test
    fun `a char literal is its Int code point`() {
        assertEquals("97\ntrue\n10\n", run(
            """
            pub fn main() -> Unit !io = {
              println(to_string('a'))
              println(to_string('a' == 97))
              println(to_string('\n'))
            }
            """.trimIndent(),
        ))
    }

    @Test
    fun `char literals work as match patterns`() {
        assertEquals("digit\nother\n", run(
            """
            fn classify(c: Int) -> String =
              match c {
                '0' -> "digit"
                _ -> "other"
              }

            pub fn main() -> Unit !io = {
              println(classify('0'))
              println(classify('x'))
            }
            """.trimIndent(),
        ))
    }

    @Test
    fun `code_points and from_code_points round-trip, including supplementary planes`() {
        assertEquals("5\n1\ntrue\ntrue\n", run(
            """
            pub fn main() -> Unit !io = {
              println(to_string(str_len("hello")))
              println(to_string(str_len("🙂")))
              println(to_string(from_code_points(code_points("héllo 🙂")) == "héllo 🙂"))
              println(to_string(from_code_points([104, 105]) == "hi"))
            }
            """.trimIndent(),
        ))
    }

    @Test
    fun `char_to_string builds a one-character string`() {
        assertEquals("A\n世\n", run(
            """
            pub fn main() -> Unit !io = {
              println(char_to_string('A'))
              println(char_to_string(19990))
            }
            """.trimIndent(),
        ))
    }

    @Test
    fun `substring uses code-point indices across multibyte text`() {
        assertEquals("hél\n界\n", run(
            """
            pub fn main() -> Unit !io = {
              println(substring("héllo", 0, 3))
              println(substring("世界", 1, 2))
            }
            """.trimIndent(),
        ))
    }

    @Test
    fun `substring out of range panics`() {
        val out = try {
            run(
                """
                pub fn main() -> Unit !io = println(substring("hi", 0, 9))
                """.trimIndent(),
            )
            "no panic"
        } catch (e: java.lang.reflect.InvocationTargetException) {
            e.cause?.message ?: ""
        }
        assertTrue(out.contains("out of range"), "expected an out-of-range panic, got: $out")
    }

    @Test
    fun `empty char literal is a lex error`() {
        assertTrue(errorsOf("pub fn main() -> Unit !io = println(to_string(''))")
            .any { it.contains("empty character literal") })
    }

    @Test
    fun `multi code point char literal is a lex error`() {
        assertTrue(errorsOf("pub fn main() -> Unit !io = println(to_string('ab'))")
            .any { it.contains("exactly one code point") })
    }
}
