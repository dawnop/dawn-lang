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
 * Signature inference for private functions: the return type and effect may
 * be omitted and are taken from the body. pub functions, recursive functions,
 * and functions using `?`/`return` must declare theirs.
 */
class SigInferTest {

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
    fun returnTypeIsInferredFromTheBody() {
        val out = run("""
            fn double(x: Int) = x * 2
            fn greet(name: String) = "hi " ++ name

            pub fn main() -> Unit !io = {
              println(to_string(double(21)))
              println(greet("dawn"))
            }
        """.trimIndent())
        assertEquals("42\nhi dawn\n", out)
    }

    @Test
    fun effectIsInferredToo() {
        val out = run("""
            fn shout(s: String) = println(s)

            pub fn main() -> Unit !io = shout("loud")
        """.trimIndent())
        assertEquals("loud\n", out)
    }

    @Test
    fun inferredFnsChainInAnyDeclarationOrder() {
        val out = run("""
            fn outer(n: Int) = inner(n) + 1

            pub fn main() -> Unit !io = println(to_string(outer(40)))

            fn inner(n: Int) = n + 1
        """.trimIndent())
        assertEquals("42\n", out)
    }

    @Test
    fun genericReturnIsInferred() {
        val out = run("""
            fn second[T](xs: List[T]) = xs[1]

            pub fn main() -> Unit !io = {
              println(to_string(second([1, 2, 3])))
              println(second(["a", "b"]))
            }
        """.trimIndent())
        assertEquals("2\nb\n", out)
    }

    @Test
    fun inferredPureFnStaysCallableFromPureCode() {
        val out = run("""
            fn triple(x: Int) = x * 3

            fn pure_user(x: Int) -> Int = triple(x) + 1

            pub fn main() -> Unit !io = println(to_string(pure_user(1)))
        """.trimIndent())
        assertEquals("4\n", out)
    }

    @Test
    fun declaredIoWithInferredReturn() {
        val out = run("""
            fn log_and_add(a: Int, b: Int) !io = {
              println("adding")
              a + b
            }

            pub fn main() -> Unit !io = println(to_string(log_and_add(1, 2)))
        """.trimIndent())
        assertEquals("adding\n3\n", out)
    }

    @Test
    fun inferredFnWorksInComptime() {
        val out = run("""
            fn square(x: Int) = x * x

            const SQ: Int = comptime { square(7) }

            pub fn main() -> Unit !io = println(to_string(SQ))
        """.trimIndent())
        assertEquals("49\n", out)
    }

    // ---- diagnostics ----

    @Test
    fun pubFunctionsMustDeclareTheReturnType() {
        val diags = errorsOf("""
            pub fn double(x: Int) = x * 2

            pub fn main() -> Unit !io = println(to_string(double(1)))
        """.trimIndent())
        assertHasError(diags, "pub functions must declare a return type")
    }

    @Test
    fun recursiveFunctionsMustAnnotate() {
        val diags = errorsOf("""
            fn fact(n: Int) = if n <= 1 { 1 } else { n * fact(n - 1) }

            pub fn main() -> Unit !io = println(to_string(fact(5)))
        """.trimIndent())
        assertHasError(diags, "cannot infer the return type of `fact`")
    }

    @Test
    fun mutualRecursionMustAnnotate() {
        val diags = errorsOf("""
            fn is_even(n: Int) = if n == 0 { true } else { is_odd(n - 1) }
            fn is_odd(n: Int) = if n == 0 { false } else { is_even(n - 1) }

            pub fn main() -> Unit !io = println(to_string(is_even(4)))
        """.trimIndent())
        assertHasError(diags, "cannot infer the return type of `is_even`")
        assertHasError(diags, "cannot infer the return type of `is_odd`")
    }

    @Test
    fun questionMarkNeedsADeclaredReturnType() {
        val diags = errorsOf("""
            fn first(xs: List[Int]) = {
              let x = get(xs, 0)?
              Some(x * 2)
            }

            pub fn main() -> Unit !io = println(to_string(first([1])))
        """.trimIndent())
        assertHasError(diags, "`?` needs the function's return type to be declared")
    }

    @Test
    fun returnNeedsADeclaredReturnType() {
        val diags = errorsOf("""
            fn f(n: Int) = {
              if n < 0 { return 0 }
              n
            }

            pub fn main() -> Unit !io = println(to_string(f(1)))
        """.trimIndent())
        assertHasError(diags, "`return` needs the function's return type to be declared")
    }

    @Test
    fun declaredPureIsStillEnforcedWithInferredReturn() {
        // `fn f(...) = ...` with an explicit (empty) effect cannot happen — but a
        // declared !io with a pure body is fine, and io in an annotated-pure fn
        // (via `-> T`) still errors. Sanity-check the second half:
        val diags = errorsOf("""
            fn f(s: String) -> Unit = println(s)

            pub fn main() -> Unit !io = f("x")
        """.trimIndent())
        assertHasError(diags, "not declared !io")
    }
}
