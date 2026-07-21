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
 * Calling a fn-typed record field directly — `r.f(x)` — plus rigid type
 * parameters counting as known types in local annotations (`let xs: List[T] = []`).
 */
class FnFieldCallTest {

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

    // ---- r.f(x): happy paths ----

    @Test
    fun fieldCallInvokesTheStoredFunction() {
        val out = run("""
            type Ops = { inc: fn(Int) -> Int, name: String }

            pub fn main() -> Unit !io = {
              let ops = Ops { inc: fn(x) => x + 1, name: "ops" }
              println(to_string(ops.inc(41)))
            }
        """.trimIndent())
        assertEquals("42\n", out)
    }

    @Test
    fun fieldCallCarriesTheFieldEffect() {
        val out = run("""
            type Hooks = { log: fn(String) -> Unit !io }

            pub fn main() -> Unit !io = {
              let h = Hooks { log: fn(s) => println("log: ${'$'}s") }
              h.log("hello")
            }
        """.trimIndent())
        assertEquals("log: hello\n", out)
    }

    @Test
    fun fieldCallOnGenericRecordSubstitutes() {
        val out = run("""
            type Box[T] = { unwrap: fn(T) -> T }

            pub fn main() -> Unit !io = {
              let b = Box { unwrap: fn(x: Int) => x * 2 }
              println(to_string(b.unwrap(21)))
            }
        """.trimIndent())
        assertEquals("42\n", out)
    }

    @Test
    fun chainedFieldAccessStillWorksAsValue() {
        val out = run("""
            type R = { f: fn(Int) -> Int }

            pub fn main() -> Unit !io = {
              let r = R { f: fn(x) => x - 1 }
              let g = r.f
              println(to_string(g(borrow(r))))
            }

            fn borrow(r: R) -> Int = r.f(10)
        """.trimIndent())
        assertEquals("8\n", out)
    }

    // ---- precedence and diagnostics ----

    @Test
    fun conflictWithAFunctionOfThatNameIsAmbiguous() {
        // both readings exist: silent precedence would let a distant new fn
        // change what this call means, so it errors instead (spec §2.4)
        val diags = errorsOf("""
            type R = { f: fn(Int) -> Int }

            fn f(r: R, n: Int) -> Int = 100 + n

            pub fn main() -> Unit !io = {
              let r = R { f: fn(x) => x }
              println(to_string(r.f(1)))
            }
        """.trimIndent())
        assertHasError(diags, "ambiguous call")
    }

    @Test
    fun bindingTheFieldFirstDisambiguates() {
        val out = run("""
            type R = { f: fn(Int) -> Int }

            fn f(r: R, n: Int) -> Int = 100 + n

            pub fn main() -> Unit !io = {
              let r = R { f: fn(x) => x }
              let g = r.f
              println(to_string(g(1)))      # the field
              println(to_string(f(r, 1)))   # the function
            }
        """.trimIndent())
        assertEquals("1\n101\n", out)
    }

    @Test
    fun callingANonFnFieldSaysSo() {
        val diags = errorsOf("""
            type R = { n: Int }

            pub fn main() -> Unit !io = {
              let r = R { n: 1 }
              println(to_string(r.n(2)))
            }
        """.trimIndent())
        assertHasError(diags, "undefined function: n")
    }

    @Test
    fun fieldCallArityIsChecked() {
        val diags = errorsOf("""
            type R = { f: fn(Int) -> Int }

            pub fn main() -> Unit !io = {
              let r = R { f: fn(x) => x }
              println(to_string(r.f(1, 2)))
            }
        """.trimIndent())
        assertHasError(diags, "`f` takes 1 argument(s), got 2")
    }

    @Test
    fun pureFnCannotCallAnIoField() {
        val diags = errorsOf("""
            type Hooks = { log: fn(String) -> Unit !io }

            fn quiet(h: Hooks) -> Unit = h.log("nope")

            pub fn main() -> Unit !io = println("x")
        """.trimIndent())
        assertHasError(diags, "io")
    }

    // ---- rigid type parameters in local annotations ----

    @Test
    fun localAnnotationMayNameATypeParameter() {
        val out = run("""
            fn rev[T](xs: List[T]) -> List[T] = {
              let init: List[T] = []
              fold(xs, init, fn(acc, x) => [x] ++ acc)
            }

            pub fn main() -> Unit !io = println(join(rev(["a", "b", "c"]), ""))
        """.trimIndent())
        assertEquals("cba\n", out)
    }

    @Test
    fun emptyListSeedsDirectlyInGenericBody() {
        val out = run("""
            fn firsts[T](pairs: List[(T, Int)]) -> List[T] =
              fold(pairs, empty(), fn(acc: List[T], p: (T, Int)) => {
                let (a, _) = p
                acc ++ [a]
              })

            fn empty[T]() -> List[T] = []

            pub fn main() -> Unit !io = println(join(firsts([("x", 1), ("y", 2)]), ""))
        """.trimIndent())
        assertEquals("xy\n", out)
    }
}
