package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M1 lambdas: function types, captures, higher-order builtins, effect variables. */
class LambdaTest {

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

    // ---- happy paths ----

    @Test
    fun lambdaBoundAndCalled() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let double = fn(x: Int) => x * 2
              let add = fn(a: Int, b: Int) => a + b
              println("{double(21)} {add(1, 2)}")
            }
        """.trimIndent())
        assertEquals("42 3\n", out)
    }

    @Test
    fun annotationInfersLambdaParams() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let inc: fn(Int) -> Int = fn(x) => x + 1
              println("{inc(41)}")
            }
        """.trimIndent())
        assertEquals("42\n", out)
    }

    @Test
    fun mapFilterFold() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let xs = range(1, 6)
              let squares = map(xs, fn(x) => x * x)
              println("{squares == [1, 4, 9, 16, 25]}")
              let evens = filter(xs, fn(x) => x % 2 == 0)
              println("{evens == [2, 4]}")
              let sum = fold(xs, 0, fn(acc, x) => acc + x)
              println("{sum}")
            }
        """.trimIndent())
        assertEquals("true\ntrue\n15\n", out)
    }

    @Test
    fun topLevelFunctionAsValue() {
        val out = run("""
            fn double(x: Int) -> Int = x * 2

            pub fn main() -> Unit !io = {
              let xs = map([1, 2, 3], double)
              println("{xs == [2, 4, 6]}")
              let d = double
              println("{d(10)}")
            }
        """.trimIndent())
        assertEquals("true\n20\n", out)
    }

    @Test
    fun capturesAreByValue() {
        val out = run("""
            fn scale(xs: List[Int], k: Int) -> List[Int] = map(xs, fn(x) => x * k)

            pub fn main() -> Unit !io = {
              println("{scale([1, 2, 3], 10) == [10, 20, 30]}")
              let offset = 100
              let f = fn(x: Int) => x + offset
              println("{f(1)}")
            }
        """.trimIndent())
        assertEquals("true\n101\n", out)
    }

    @Test
    fun nestedLambdasAndCaptures() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let a = 1
              let outer = fn(b: Int) => {
                let inner = fn(c: Int) => a + b + c
                inner(10)
              }
              println("{outer(100)}")
            }
        """.trimIndent())
        assertEquals("111\n", out)
    }

    @Test
    fun pipeChainWithLambdas() {
        val out = run("""
            pub fn main() -> Unit !io = {
              range(1, 11)
                |> filter(fn(x) => x % 2 == 1)
                |> map(fn(x) => x * x)
                |> fold(0, fn(a, b) => a + b)
                |> fn(total) => println("sum of odd squares: {total}")
            }
        """.trimIndent())
        assertEquals("sum of odd squares: 165\n", out)
    }

    @Test
    fun userHofWithEffectVariable() {
        val out = run("""
            fn apply_twice(f: fn(Int) -> Int !e, x: Int) -> Int !e = f(f(x))

            fn pure_use(x: Int) -> Int = apply_twice(fn(n) => n + 1, x)

            pub fn main() -> Unit !io = {
              println("{pure_use(40)}")
              let r = apply_twice(fn(n) => {
                println("step")
                n * 2
              }, 3)
              println("{r}")
            }
        """.trimIndent())
        assertEquals("42\nstep\nstep\n12\n", out)
    }

    @Test
    fun ioLambdaInsideIoFunction() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let _ = map([1, 2], fn(x) => {
                println("saw {x}")
                x
              })
              println("done")
            }
        """.trimIndent())
        assertEquals("saw 1\nsaw 2\ndone\n", out)
    }

    @Test
    fun shapesAcceptanceExample() {
        val out = run("""
            type Shape =
              | Circle(r: Float)
              | Rect(w: Float, h: Float)
              | Point

            fn area(s: Shape) -> Float =
              match s {
                Circle(r)  -> 3.14159 * r * r
                Rect(w, h) -> w * h
                Point      -> 0.0
              }

            fn describe(s: Shape) -> String =
              match s {
                Circle(r) if r > 100.0 -> "a huge circle"
                Circle(r)              -> "circle with r = {r}"
                Rect(w, h)             -> "rect {w} x {h}"
                Point                  -> "a point"
              }

            pub fn main() -> Unit !io = {
              let shapes = [Circle(1.0), Rect(2.0, 3.0), Point, Circle(200.0)]

              let _ = map(shapes, fn(s) => {
                println(describe(s))
                s
              })

              shapes
                |> map(area)
                |> fold(0.0, fn(acc, a) => acc + a)
                |> fn(total) => println("total area: {total}")
            }
        """.trimIndent())
        assertTrue(out.startsWith("circle with r = 1.0\nrect 2.0 x 3.0\na point\na huge circle\ntotal area: "))
        assertTrue(out.contains("total area: 125672."), "unexpected total: $out")
    }

    // ---- diagnostics ----

    @Test
    fun pureFunctionCannotUseIoLambdaParam() {
        val diags = errorsOf("""
            fn bad(f: fn(Int) -> Int !io) -> Int = f(1)

            pub fn main() -> Unit !io = println("{bad(fn(x) => x)}")
        """.trimIndent())
        assertHasError(diags, "`bad` is not declared !io but calls `f` (!io)")
    }

    @Test
    fun effectVariableMustBeDeclared() {
        val diags = errorsOf("""
            fn h(f: fn(Int) -> Int !e) -> Int = f(1)

            pub fn main() -> Unit !io = println("{h(fn(x) => x)}")
        """.trimIndent())
        assertHasError(diags, "`h` is not declared !e but calls `f` (!e)")
    }

    @Test
    fun ioLambdaIntoPureCallerIsRejected() {
        val diags = errorsOf("""
            fn twice(f: fn(Int) -> Int !e, x: Int) -> Int !e = f(f(x))

            fn pure_caller(x: Int) -> Int =
              twice(fn(n) => {
                println("{n}")
                n
              }, x)

            pub fn main() -> Unit !io = println("{pure_caller(1)}")
        """.trimIndent())
        assertHasError(diags, "`pure_caller` is not declared !io but calls `twice` (!io)")
    }

    @Test
    fun varsCannotBeCaptured() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              var acc = 0
              let f = fn(x: Int) => x + acc
              println("{f(1)}")
            }
        """.trimIndent())
        assertHasError(diags, "lambdas cannot capture `var` bindings")
    }

    @Test
    fun cannotAssignEnclosingFromLambda() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              var acc = 0
              let f = fn(x: Int) => {
                acc = acc + x
              }
              f(1)
              println("{acc}")
            }
        """.trimIndent())
        assertHasError(diags, "cannot assign to `acc` from inside a lambda")
    }

    @Test
    fun lambdaParamNeedsContext() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let f = fn(x) => x
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "cannot infer the type of `x`")
    }

    @Test
    fun functionsCannotBeCompared() {
        val diags = errorsOf("""
            fn a(x: Int) -> Int = x

            pub fn main() -> Unit !io = {
              let f = a
              let g = a
              println("{f == g}")
            }
        """.trimIndent())
        assertHasError(diags, "functions cannot be compared")
    }

    @Test
    fun builtinAsValueRejected() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let p = println
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "builtin functions cannot be used as values yet")
    }
}
