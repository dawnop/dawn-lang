package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Local named functions: `fn name(params) -> T [!io] = body` in statement
 * position. Captures like a lambda, recurses like a top-level function
 * (self tail calls become loops).
 */
class LocalFnTest {

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

    // ---- happy paths ----

    @Test
    fun basicLocalFnAndCapture() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let base = 40
              fn add_base(x: Int) -> Int = x + base
              println(to_string(add_base(2)))
            }
        """.trimIndent())
        assertEquals("42\n", out)
    }

    @Test
    fun localRecursionWorks() {
        val out = run("""
            pub fn main() -> Unit !io = {
              fn fact(n: Int) -> Int = if n <= 1 { 1 } else { n * fact(n - 1) }
              println(to_string(fact(5)))
            }
        """.trimIndent())
        assertEquals("120\n", out)
    }

    @Test
    fun tailRecursionBecomesALoop() {
        // 200k frames would overflow the stack if this were a real call
        val out = run("""
            pub fn main() -> Unit !io = {
              fn count(n: Int, acc: Int) -> Int =
                if n == 0 { acc } else { count(n - 1, acc + 1) }
              println(to_string(count(200000, 0)))
            }
        """.trimIndent())
        assertEquals("200000\n", out)
    }

    @Test
    fun recursionWithCaptureAndIo() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let tag = "n="
              fn go(n: Int) -> Unit !io = {
                if n == 0 { return }
                println("${'$'}tag${'$'}n")
                go(n - 1)
              }
              go(2)
            }
        """.trimIndent())
        assertEquals("n=2\nn=1\n", out)
    }

    @Test
    fun localFnAsAValue() {
        val out = run("""
            pub fn main() -> Unit !io = {
              fn double(x: Int) -> Int = x * 2
              let xs = map([1, 2, 3], double)
              println(to_string(xs))
            }
        """.trimIndent())
        assertEquals("[2, 4, 6]\n", out)
    }

    @Test
    fun recursiveCallInsideANestedLambda() {
        // tree-walk pattern: the nested lambda captures the local fn itself
        val out = run("""
            pub fn main() -> Unit !io = {
              fn sum_deep(xs: List[List[Int]]) -> Int =
                fold(xs, 0, fn(acc, inner) => acc + fold(inner, 0, fn(a, b) => a + b))

              fn tri(n: Int) -> Int = if n == 0 { 0 } else { n + tri(n - 1) }
              let via_lambda = map([3, 4], fn(n) => tri(n))
              println(to_string(sum_deep([[1, 2], [3]])))
              println(to_string(via_lambda))
            }
        """.trimIndent())
        assertEquals("6\n[6, 10]\n", out)
    }

    @Test
    fun selfAsAValueInsideOwnBody() {
        val out = run("""
            fn twice(f: fn(Int) -> Int, x: Int) -> Int = f(f(x))

            pub fn main() -> Unit !io = {
              fn step(n: Int) -> Int = if n > 100 { n } else { twice(step, n + 1) }
              println(to_string(step(99)))
            }
        """.trimIndent())
        assertEquals("101\n", out)
    }

    @Test
    fun localFnInComptime() {
        val out = run("""
            fn table() -> List[Int] = {
              fn fib(n: Int) -> Int = if n < 2 { n } else { fib(n - 1) + fib(n - 2) }
              map(range(0, 8), fn(i) => fib(i))
            }

            const FIBS: List[Int] = comptime { table() }

            pub fn main() -> Unit !io = println(to_string(FIBS))
        """.trimIndent())
        assertEquals("[0, 1, 1, 2, 3, 5, 8, 13]\n", out)
    }

    @Test
    fun worksWithReturnAndIndex() {
        val out = run("""
            pub fn main() -> Unit !io = {
              fn find_first_even(xs: List[Int]) -> Option[Int] = {
                fn go(i: Int) -> Option[Int] = {
                  if i == len(xs) { return None }
                  if xs[i] % 2 == 0 { return Some(xs[i]) }
                  go(i + 1)
                }
                go(0)
              }
              println(to_string(find_first_even([1, 3, 8, 5])))
              println(to_string(find_first_even([1, 3])))
            }
        """.trimIndent())
        assertEquals("Some(8)\nNone\n", out)
    }

    // ---- diagnostics ----

    @Test
    fun paramTypesAreRequired() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              fn f(x) -> Int = x
              println(to_string(f(1)))
            }
        """.trimIndent())
        assertHasError(diags, "local function parameters must be typed")
    }

    @Test
    fun returnTypeIsRequired() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              fn f(x: Int) = x
              println(to_string(f(1)))
            }
        """.trimIndent())
        assertHasError(diags, "local functions must declare a return type")
    }

    @Test
    fun pureLocalFnCannotDoIo() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              fn shout(s: String) -> Unit = println(s)
              shout("hi")
            }
        """.trimIndent())
        assertHasError(diags, "performs io")
    }

    @Test
    fun duplicateNameInTheSameScopeIsAnError() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let go = 1
              fn go(x: Int) -> Int = x
              println(to_string(go))
            }
        """.trimIndent())
        assertHasError(diags, "go")
    }

    @Test
    fun bodyTypeMustMatchDeclaredReturn() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              fn f(x: Int) -> String = x
              println(f(1))
            }
        """.trimIndent())
        assertHasError(diags, "declared return type is String")
    }
}
