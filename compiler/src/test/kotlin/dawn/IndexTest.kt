package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import java.lang.reflect.InvocationTargetException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * The `[]` operator: xs[i] on List and m[k] on Map. Asserting semantics —
 * out of bounds / absent key panics; `get`/`map_get` stay the asking variants.
 */
class IndexTest {

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

    private fun runExpectPanic(source: String): String {
        return try {
            run(source)
            throw AssertionError("expected a panic, but the program finished normally")
        } catch (e: InvocationTargetException) {
            val cause = e.cause!!
            assertEquals("dawn.rt.PanicError", cause.javaClass.name)
            cause.message ?: ""
        }
    }

    // ---- happy paths ----

    @Test
    fun listIndexReturnsTheElement() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let xs = [10, 20, 30]
              println(to_string(xs[0] + xs[2]))
            }
        """.trimIndent())
        assertEquals("40\n", out)
    }

    @Test
    fun indexComposesWithPostfixAndPipes() {
        val out = run("""
            fn rows() -> List[List[String]] = [["a", "b"], ["c", "d"]]

            pub fn main() -> Unit !io = {
              println(rows()[1][0])
              let n = [3, 1, 2] |> filter(fn(x) => x < 3)
              println(to_string(n[0]))
            }
        """.trimIndent())
        assertEquals("c\n1\n", out)
    }

    @Test
    fun mapIndexReturnsTheValue() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let m = map_from([("a", 1), ("b", 2)])
              println(to_string(m["b"]))
            }
        """.trimIndent())
        assertEquals("2\n", out)
    }

    @Test
    fun structuralKeysIndex() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let m = map_from([((1, "x"), 7)])
              println(to_string(m[(1, "x")]))
            }
        """.trimIndent())
        assertEquals("7\n", out)
    }

    @Test
    fun unitAndFloatElements() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let fs = [1.5, 2.5]
              println(to_string(fs[1]))
            }
        """.trimIndent())
        assertEquals("2.5\n", out)
    }

    @Test
    fun indexInComptime() {
        val out = run("""
            const FIRST: Int = comptime { [7, 8, 9][0] }

            pub fn main() -> Unit !io = println(to_string(FIRST))
        """.trimIndent())
        assertEquals("7\n", out)
    }

    // ---- panics ----

    @Test
    fun outOfBoundsPanicsWithIndexAndLength() {
        val msg = runExpectPanic("""
            pub fn main() -> Unit !io = {
              let xs = [1, 2]
              println(to_string(xs[5]))
            }
        """.trimIndent())
        assertTrue("index 5 out of bounds for length 2" in msg, "got: $msg")
    }

    @Test
    fun negativeIndexPanics() {
        val msg = runExpectPanic("""
            pub fn main() -> Unit !io = {
              let xs = [1, 2]
              println(to_string(xs[0 - 1]))
            }
        """.trimIndent())
        assertTrue("out of bounds" in msg, "got: $msg")
    }

    @Test
    fun absentKeyPanicsShowingTheKey() {
        val msg = runExpectPanic("""
            pub fn main() -> Unit !io = {
              let m = map_from([("a", 1)])
              println(to_string(m["zzz"]))
            }
        """.trimIndent())
        assertTrue("key not found" in msg, "got: $msg")
        assertTrue("zzz" in msg, "the key should be rendered, got: $msg")
    }

    // ---- diagnostics ----

    @Test
    fun indexingANonCollectionIsAnError() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let n = 42
              println(to_string(n[0]))
            }
        """.trimIndent())
        assertHasError(diags, "`[]` indexes a List or Map")
    }

    @Test
    fun listIndexMustBeInt() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let xs = [1, 2]
              println(to_string(xs["0"]))
            }
        """.trimIndent())
        assertHasError(diags, "a List index must be Int")
    }

    @Test
    fun mapKeyTypeIsChecked() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let m = map_from([("a", 1)])
              println(to_string(m[7]))
            }
        """.trimIndent())
        assertHasError(diags, "keys of type String")
    }

    @Test
    fun getStaysOption() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let xs = [1, 2]
              match get(xs, 9) {
                Some(v) -> println(to_string(v))
                None -> println("none")
              }
            }
        """.trimIndent())
        assertEquals("none\n", out)
    }
}
