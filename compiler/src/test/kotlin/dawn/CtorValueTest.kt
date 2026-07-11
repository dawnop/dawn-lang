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
    fun `generic constructor Some as a value in map`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              let ys = map([1, 2, 3], Some)
              println(to_string(len(ys)))
            }
            """.trimIndent(),
        )
        assertEquals("3\n", out)
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
    fun `constructor as a value through a pipeline`() {
        val out = run(
            """
            fn addOpt(acc: Int, o: Option[Int]) -> Int =
              match o { Some(v) -> acc + v  None -> acc }

            pub fn main() -> Unit !io = {
              let total = [5, 7] |> map(Some) |> fold(0, addOpt)
              println(to_string(total))
            }
            """.trimIndent(),
        )
        assertEquals("12\n", out)
    }

    @Test
    fun `monomorphic single-field constructor as a value`() {
        val out = run(
            """
            type Box = | Box(v: Int)

            fn openSum(acc: Int, b: Box) -> Int = match b { Box(v) -> acc + v }

            pub fn main() -> Unit !io = {
              let boxes = map([7, 8], Box)
              println(to_string(fold(boxes, 0, openSum)))
            }
            """.trimIndent(),
        )
        assertEquals("15\n", out)
    }

    @Test
    fun `Ok constructor as a value`() {
        val out = run(
            """
            fn addOk(acc: Int, r: Result[Int, String]) -> Int =
              match r { Ok(v) -> acc + v  Err(e) -> acc }

            pub fn main() -> Unit !io = {
              # Ok's error type E is unconstrained by the field, so pin it via the result annotation
              let rs: List[Result[Int, String]] = map([1, 2, 3], Ok)
              println(to_string(fold(rs, 0, addOk)))
            }
            """.trimIndent(),
        )
        assertEquals("6\n", out)
    }

    @Test
    fun `float-field constructor as a value uses primitive slots`() {
        val out = run(
            """
            type Wrapped = | Wrapped(x: Float)

            fn sum(acc: Float, w: Wrapped) -> Float = match w { Wrapped(x) -> acc + x }

            pub fn main() -> Unit !io = {
              let ws = map([1.5, 2.5], Wrapped)
              println(to_string(fold(ws, 0.0, sum)))
            }
            """.trimIndent(),
        )
        assertEquals("4.0\n", out)
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

    @Test
    fun `constructor bound to an annotated function-typed let`() {
        val out = run(
            """
            fn addOpt(acc: Int, o: Option[Int]) -> Int =
              match o { Some(v) -> acc + v  None -> acc }

            pub fn main() -> Unit !io = {
              let wrap: fn(Int) -> Option[Int] = Some
              let ys = map([3, 4], wrap)
              println(to_string(fold(ys, 0, addOpt)))
            }
            """.trimIndent(),
        )
        assertEquals("7\n", out)
    }
}
