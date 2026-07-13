package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.fail

/** M6 knife 2: java_try — the interop exception barrier (spec §9.8). */
class JavaTryTest {

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
    fun `a throwing java call becomes Err and a clean one becomes Ok`() {
        val out = run(
            """
            use java "java.lang.Long"

            fn show(r: Result[Int, String]) -> String !io =
              match r {
                Ok(n) -> "ok " ++ to_string(n)
                Err(m) -> "err " ++ m
              }

            pub fn main() -> Unit !io = {
              println(show(java_try(fn() => Long.parseLong("42"))))
              println(show(java_try(fn() => Long.parseLong("nope"))))
            }
            """.trimIndent(),
        )
        val lines = out.lines()
        assertEquals("ok 42", lines[0])
        assertTrue(lines[1].startsWith("err ") && lines[1].contains("NumberFormatException"),
            "expected a NumberFormatException Err, got: ${lines[1]}")
    }

    @Test
    fun `a pure closure is accepted and returns Ok`() {
        val out = run(
            """
            pub fn main() -> Unit !io =
              match java_try(fn() => 3 + 4) {
                Ok(n) -> println(to_string(n))
                Err(m) -> println(m)
              }
            """.trimIndent(),
        )
        assertEquals("7\n", out)
    }

    @Test
    fun `panics are not caught`() {
        try {
            run(
                """
                fn boom() -> Int = panic("boom")

                pub fn main() -> Unit !io =
                  match java_try(fn() => boom()) {
                    Ok(n) -> println(to_string(n))
                    Err(m) -> println(m)
                  }
                """.trimIndent(),
            )
            fail("expected the panic to escape java_try")
        } catch (e: java.lang.reflect.InvocationTargetException) {
            val cause = e.cause!!
            assertEquals("dawn.rt.PanicError", cause.javaClass.name)
            assertTrue(cause.message!!.contains("boom"))
        }
    }

    @Test
    fun `java_try itself is io`() {
        val analysis = analyze(
            """
            fn f() -> Result[Int, String] = java_try(fn() => 1)
            """.trimIndent(),
        )
        assertTrue(analysis.hasErrors)
        assertTrue(analysis.diagnostics.any { it.message.contains("io") || it.message.contains("effect") },
            "expected an effect error, got:\n" + analysis.diagnostics.joinToString("\n") { it.message })
    }
}
