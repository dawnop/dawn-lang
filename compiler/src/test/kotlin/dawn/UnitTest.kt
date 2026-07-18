package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * Unit as a first-class value that can instantiate a type parameter (T = Unit). It occupies
 * an erased Object slot as the dawn/rt/Unit singleton — the same representation every other
 * "one valueless value" uses (None, nullary constructors). This unblocks the natural interop
 * pattern of wrapping a void-returning call in java_try, plus Result[Unit], List[Unit], etc.
 */
class UnitTest {

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

    @Test
    fun `java_try wraps a void-returning call as Result of Unit`() {
        val out = run(
            """
            use java "java.io.ByteArrayInputStream"
            pub fn main() -> Unit !io = {
              let s = ByteArrayInputStream.new(utf8("hi"))
              match java_try(fn() => s.close()) {
                Ok(_) -> println("closed")
                Err(_) -> println("err")
              }
            }
            """.trimIndent(),
        )
        assertEquals("closed\n", out)
    }

    @Test
    fun `Result of Unit round-trips through Ok`() {
        val out = run(
            """
            fn noop() -> Result[Unit, String] = Ok(())
            pub fn main() -> Unit !io =
              match noop() {
                Ok(_) -> println("ok")
                Err(_) -> println("err")
              }
            """.trimIndent(),
        )
        assertEquals("ok\n", out)
    }

    @Test
    fun `Unit flows through a generic container — List of Unit`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              let xs = map([1, 2, 3], fn(n) => ())
              println("${'$'}{len(xs)}")
            }
            """.trimIndent(),
        )
        assertEquals("3\n", out)
    }

    @Test
    fun `Option of Unit distinguishes Some from None`() {
        val out = run(
            """
            fn flag(b: Bool) -> Option[Unit] = if b { Some(()) } else { None }
            pub fn main() -> Unit !io = {
              match flag(true) { Some(_) -> println("some") None -> println("none") }
              match flag(false) { Some(_) -> println("some") None -> println("none") }
            }
            """.trimIndent(),
        )
        assertEquals("some\nnone\n", out)
    }

    @Test
    fun `a generic function instantiated at Unit`() {
        val out = run(
            """
            fn dup[T](x: T) -> (T, T) = (x, x)
            pub fn main() -> Unit !io = {
              let (_, _) = dup(())
              println("ok")
            }
            """.trimIndent(),
        )
        assertEquals("ok\n", out)
    }
}
