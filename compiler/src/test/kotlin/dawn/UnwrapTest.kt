package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.fmt.Formatter
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import java.lang.reflect.InvocationTargetException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** M7 序5: postfix `!` unwraps an Option (spec §8.2). */
class UnwrapTest {

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

    private fun errors(source: String): List<String> =
        analyze(source).diagnostics.map { it.message }

    @Test
    fun `unwraps Some, and threads the payload type through`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              let n = Some(41)! + 1
              println("${'$'}n")
              println(Some("hi")!)
            }
            """.trimIndent()
        )
        assertEquals("42\nhi\n", out)
    }

    @Test
    fun `None panics with a message naming the source and line, no placeholder needed`() {
        val ex = assertFailsWith<InvocationTargetException> {
            run(
                """
                fn missing() -> Option[Int] = None

                pub fn main() -> Unit !io = {
                  println("${'$'}{missing()!}")
                }
                """.trimIndent()
            )
        }
        val msg = ex.cause!!.message!!
        // the whole point of `!` over .expect("b-uri"): the compiler writes a message
        // that names what produced the None and where it sits
        assertTrue(msg.startsWith("unwrapped None"), msg)
        assertTrue(msg.contains("missing()"), msg)
        assertTrue(msg.contains(":4"), "expected the unwrap's line number, got: $msg")
    }

    @Test
    fun `a non-Option operand is a compile error`() {
        val es = errors(
            """
            pub fn main() -> Unit !io = println("${'$'}{5!}")
            """.trimIndent()
        )
        assertTrue(es.any { it.contains("`!` needs an Option") }, es.toString())
    }

    @Test
    fun `on a Result it points at ? instead`() {
        val src = """
            fn r() -> Result[Int, String] = Ok(1)

            pub fn main() -> Unit !io = println("${'$'}{r()!}")
        """.trimIndent()
        val ds = analyze(src).diagnostics
        assertTrue(ds.any { it.message.contains("`!` needs an Option") }, ds.map { it.message }.toString())
        assertTrue(ds.any { it.hint?.contains("use `?` to propagate") == true },
            "expected a hint steering to `?`, got: " + ds.map { it.hint })
    }

    @Test
    fun `chains, and Java interop reference returns unwrap without placeholder strings`() {
        val out = run(
            """
            use java "java.net.URI"

            pub fn main() -> Unit !io = {
              let u = URI.create("https://dawnop.com/a/b")!
              println(u.getPath()!)
            }
            """.trimIndent()
        )
        assertEquals("/a/b\n", out)
    }

    @Test
    fun `bang binds tighter than a comparison, and != still lexes as one token`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              println("${'$'}{Some(1)! != 2}")
              println("${'$'}{Some(2)! != 2}")
            }
            """.trimIndent()
        )
        assertEquals("true\nfalse\n", out)
    }

    @Test
    fun `fmt hugs postfix bang but keeps the effect marker spaced`() {
        // the two `!`s want opposite spacing; `!(e1 | e2)` is an effect union, not a call
        val src = """
            fn f(o: Option[Int]) -> Int = o !
            fn g() -> Unit !io = println("x")
            fn h[A, B](k: fn(A) -> B !e1) -> Unit !(e1 | e2) = todo()
        """.trimIndent()
        val out = Formatter.format(src)
        assertTrue(out.contains("= o!"), out)
        assertTrue(out.contains("-> Unit !io"), out)
        assertTrue(out.contains("!(e1 | e2)"), out)
    }
}
