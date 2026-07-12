package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M3: `derive Show` — generated to_string / interpolation for user types (spec §4.3). */
class DeriveShowTest {

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
        assertTrue(
            analysis.diagnostics.any { it.message.contains(substring) || (it.hint ?: "").contains(substring) },
            "no diagnostic mentions \"$substring\"; got:\n" +
                analysis.diagnostics.joinToString("\n") { it.message + " | " + (it.hint ?: "") },
        )
    }

    @Test
    fun `nullary and positional constructors`() {
        val out = run(
            """
            type Shape = | Dot | Circle(r: Float) | Rect(w: Float, h: Float) derive Show

            pub fn main() -> Unit !io = {
              println(to_string(Dot))
              println(to_string(Circle(1.5)))
              println(to_string(Rect(2.0, 3.0)))
            }
            """.trimIndent(),
        )
        assertEquals("Dot\nCircle(1.5)\nRect(2.0, 3.0)\n", out)
    }

    @Test
    fun `record renders with braces and field names`() {
        val out = run(
            """
            type Point = { x: Float, y: Float } derive Show

            pub fn main() -> Unit !io = println(to_string(Point { x: 0.0, y: 2.5 }))
            """.trimIndent(),
        )
        assertEquals("Point { x: 0.0, y: 2.5 }\n", out)
    }

    @Test
    fun `string fields are quoted and escaped`() {
        val out = run(
            """
            type Tagged = | Tagged(name: String, n: Int) derive Show

            pub fn main() -> Unit !io = println(to_string(Tagged("a\nb\tc", 7)))
            """.trimIndent(),
        )
        assertEquals("Tagged(\"a\\nb\\tc\", 7)\n", out)
    }

    @Test
    fun `nested derive values`() {
        val out = run(
            """
            type Color = | Red | Green | Blue derive Show
            type Pair = | Pair(a: Color, b: Color) derive Show

            pub fn main() -> Unit !io = println(to_string(Pair(Red, Blue)))
            """.trimIndent(),
        )
        assertEquals("Pair(Red, Blue)\n", out)
    }

    @Test
    fun `generic type prints when instantiated with a printable argument`() {
        val out = run(
            """
            type Box[T] = | Box(v: T) derive Show

            pub fn main() -> Unit !io = {
              println(to_string(Box(7)))
              println(to_string(Box("hi")))
            }
            """.trimIndent(),
        )
        assertEquals("Box(7)\nBox(\"hi\")\n", out)
    }

    @Test
    fun `Option of a derive value renders through the prelude`() {
        val out = run(
            """
            type Color = | Red | Green | Blue derive Show

            pub fn main() -> Unit !io = {
              println(to_string(Some(Red)))
              let n: Option[Color] = None
              println(to_string(n))
            }
            """.trimIndent(),
        )
        assertEquals("Some(Red)\nNone\n", out)
    }

    @Test
    fun `interpolation and lists of derive values`() {
        val out = run(
            """
            type Color = | Red | Green | Blue derive Show

            pub fn main() -> Unit !io = {
              println("first is ${'$'}{Red}")
              println(to_string([Red, Green, Blue]))
            }
            """.trimIndent(),
        )
        assertEquals("first is Red\n[Red, Green, Blue]\n", out)
    }

    @Test
    fun `tuple of derive values with a quoted string`() {
        val out = run(
            """
            type Color = | Red | Green | Blue derive Show

            pub fn main() -> Unit !io = println(to_string((Red, 7, "ok")))
            """.trimIndent(),
        )
        assertEquals("(Red, 7, \"ok\")\n", out)
    }

    @Test
    fun `printing a type without derive Show is rejected`() {
        assertHasError(
            """
            type Color = | Red | Green

            pub fn main() -> Unit !io = println(to_string(Red))
            """.trimIndent(),
            "add `derive Show`",
        )
    }

    @Test
    fun `interpolating a type without derive Show is rejected`() {
        assertHasError(
            """
            type Color = | Red | Green

            pub fn main() -> Unit !io = println("c = ${'$'}{Red}")
            """.trimIndent(),
            "add `derive Show`",
        )
    }

    @Test
    fun `deriving Show with a function field is rejected at the declaration`() {
        assertHasError(
            """
            type Bad = | Bad(f: fn(Int) -> Int) derive Show

            pub fn main() -> Unit !io = println("x")
            """.trimIndent(),
            "not printable",
        )
    }

    @Test
    fun `deriving Show requires nested user types to also derive Show`() {
        assertHasError(
            """
            type Inner = | A | B
            type Outer = | Outer(i: Inner) derive Show

            pub fn main() -> Unit !io = println("x")
            """.trimIndent(),
            "add `derive Show` to `type Inner`",
        )
    }

    @Test
    fun `only Show can be derived in v0_1`() {
        assertHasError(
            """
            type Color = | Red | Green derive Eq

            pub fn main() -> Unit !io = println("x")
            """.trimIndent(),
            "can only derive Show",
        )
    }
}
