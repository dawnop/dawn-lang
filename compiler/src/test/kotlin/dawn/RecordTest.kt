package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M1 records: literals, shorthand, functional update, field access, record patterns. */
class RecordTest {

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

    private val pointPrelude = """
        type Point = { x: Float, y: Float }
    """.trimIndent()

    // ---- happy paths ----

    @Test
    fun literalAndFieldAccess() {
        val out = run("""
            $pointPrelude

            pub fn main() -> Unit !io = {
              let p = Point { x: 1.0, y: 2.0 }
              println("${'$'}{p.x} ${'$'}{p.y}")
            }
        """.trimIndent())
        assertEquals("1.0 2.0\n", out)
    }

    @Test
    fun functionalUpdate() {
        val out = run("""
            $pointPrelude

            pub fn main() -> Unit !io = {
              let p = Point { x: 1.0, y: 2.0 }
              let q = Point { ..p, x: 3.0 }
              println("${'$'}{q.x} ${'$'}{q.y} ${'$'}{p.x}")
            }
        """.trimIndent())
        assertEquals("3.0 2.0 1.0\n", out)
    }

    @Test
    fun shorthandFields() {
        val out = run("""
            $pointPrelude

            pub fn main() -> Unit !io = {
              let x = 5.0
              let y = 6.0
              let p = Point { x, y }
              println("${'$'}{p.x} ${'$'}{p.y}")
            }
        """.trimIndent())
        assertEquals("5.0 6.0\n", out)
    }

    @Test
    fun recordPatterns() {
        val out = run("""
            $pointPrelude

            fn describe(p: Point) -> String =
              match p {
                Point { x: 0.0, y: 0.0 } -> "origin"
                Point { x, .. }          -> "x = ${'$'}x"
              }

            pub fn main() -> Unit !io = {
              println(describe(Point { x: 0.0, y: 0.0 }))
              println(describe(Point { x: 7.0, y: 1.0 }))
            }
        """.trimIndent())
        assertEquals("origin\nx = 7.0\n", out)
    }

    @Test
    fun nestedRecords() {
        val out = run("""
            type Point = { x: Float, y: Float }
            type Line = { a: Point, b: Point }

            pub fn main() -> Unit !io = {
              let l = Line { a: Point { x: 1.0, y: 2.0 }, b: Point { x: 3.0, y: 4.0 } }
              println("${'$'}{l.a.x} ${'$'}{l.b.y}")
              let moved = Line { ..l, b: Point { ..l.b, x: 9.0 } }
              println("${'$'}{moved.a.x} ${'$'}{moved.b.x} ${'$'}{moved.b.y}")
            }
        """.trimIndent())
        assertEquals("1.0 4.0\n1.0 9.0 4.0\n", out)
    }

    @Test
    fun recordEquality() {
        val out = run("""
            $pointPrelude

            pub fn main() -> Unit !io = {
              let p = Point { x: 1.0, y: 2.0 }
              println("${'$'}{p == Point { x: 1.0, y: 2.0 }}")
              println("${'$'}{p == Point { ..p, x: 0.0 }}")
            }
        """.trimIndent())
        assertEquals("true\nfalse\n", out)
    }

    @Test
    fun recordInsideAdt() {
        val out = run("""
            type Point = { x: Float, y: Float }
            type Shape =
              | Circle(center: Point, r: Float)
              | Dot(at: Point)

            fn cx(s: Shape) -> Float =
              match s {
                Circle(c, ..) -> c.x
                Dot(Point { x, .. }) -> x
              }

            pub fn main() -> Unit !io = {
              println("${'$'}{cx(Circle(Point { x: 1.5, y: 0.0 }, 2.0))}")
              println("${'$'}{cx(Dot(Point { x: 4.5, y: 0.0 }))}")
            }
        """.trimIndent())
        assertEquals("1.5\n4.5\n", out)
    }

    @Test
    fun spreadEvaluationOrder() {
        val out = run("""
            type P = { a: Int, b: Int }

            fn trace(tag: String, v: Int) -> Int !io = {
              println(tag)
              v
            }

            pub fn main() -> Unit !io = {
              let base = P { a: trace("base-a", 1), b: trace("base-b", 2) }
              let q = P { ..base, b: trace("override-b", 9) }
              println("${'$'}{q.a} ${'$'}{q.b}")
            }
        """.trimIndent())
        assertEquals("base-a\nbase-b\noverride-b\n1 9\n", out)
    }

    @Test
    fun headerPositionsRejectRecordLiteralButParensWork() {
        val out = run("""
            $pointPrelude

            pub fn main() -> Unit !io = {
              let p = Point { x: 0.0, y: 0.0 }
              if p == (Point { x: 0.0, y: 0.0 }) {
                println("origin")
              }
            }
        """.trimIndent())
        assertEquals("origin\n", out)
    }

    // ---- diagnostics ----

    @Test
    fun missingFieldWithoutSpread() {
        val diags = errorsOf("""
            $pointPrelude

            pub fn main() -> Unit !io = {
              let p = Point { x: 1.0 }
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "missing field(s) in `Point`: y")
    }

    @Test
    fun unknownFieldInLiteralAndAccess() {
        val diags = errorsOf("""
            $pointPrelude

            pub fn main() -> Unit !io = {
              let p = Point { x: 1.0, y: 2.0, z: 3.0 }
              let q = Point { x: 1.0, y: 2.0 }
              println("${'$'}{q.z}")
            }
        """.trimIndent())
        assertHasError(diags, "`Point` has no field `z`")
    }

    @Test
    fun fieldAccessOnNonRecord() {
        val diags = errorsOf("""
            type Color = | Red | Blue

            fn f(c: Color) -> Int = c.x

            pub fn main() -> Unit !io = println("${'$'}{f(Red)}")
        """.trimIndent())
        assertHasError(diags, "field access needs a record value")
    }

    @Test
    fun spreadOnSumTypeRejected() {
        val diags = errorsOf("""
            type Shape = | Circle(r: Float) | Point

            pub fn main() -> Unit !io = {
              let c = Circle(1.0)
              let d = Circle { ..c, r: 2.0 }
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "`..base` functional update only works on records")
    }

    @Test
    fun spreadTypeMismatch() {
        val diags = errorsOf("""
            type Point = { x: Float, y: Float }
            type Size = { w: Float, h: Float }

            pub fn main() -> Unit !io = {
              let s = Size { w: 1.0, h: 2.0 }
              let p = Point { ..s, x: 3.0 }
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "`..base` must be a Point, got Size")
    }

    @Test
    fun recordNeedsBraces() {
        val diags = errorsOf("""
            $pointPrelude

            pub fn main() -> Unit !io = {
              let p = Point
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "record `Point` must be built with braces")
    }
}
