package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M1 ADTs: declarations, construction, matching, exhaustiveness, structural equality. */
class AdtTest {

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

    private val shapePrelude = """
        type Shape =
          | Circle(r: Float)
          | Rect(w: Float, h: Float)
          | Point
    """.trimIndent()

    // ---- happy paths ----

    @Test
    fun constructMatchAndGuards() {
        val out = run("""
            $shapePrelude

            fn describe(s: Shape) -> String =
              match s {
                Circle(r) if r > 100.0 -> "a huge circle"
                Circle(r)              -> "circle with r = {r}"
                Rect(w, h)             -> "rect {w} x {h}"
                Point                  -> "a point"
              }

            pub fn main() -> Unit !io = {
              println(describe(Circle(1.0)))
              println(describe(Rect(2.0, 3.0)))
              println(describe(Point))
              println(describe(Circle(200.0)))
            }
        """.trimIndent())
        assertEquals("circle with r = 1.0\nrect 2.0 x 3.0\na point\na huge circle\n", out)
    }

    @Test
    fun areaThroughFunctions() {
        val out = run("""
            $shapePrelude

            fn area(s: Shape) -> Float =
              match s {
                Circle(r)  -> 3.14159 * r * r
                Rect(w, h) -> w * h
                Point      -> 0.0
              }

            pub fn main() -> Unit !io = {
              let total = area(Circle(1.0)) + area(Rect(2.0, 3.0)) + area(Point)
              println("{total}")
            }
        """.trimIndent())
        assertEquals("9.14159\n", out)
    }

    @Test
    fun namedArgumentsOutOfOrder() {
        val out = run("""
            $shapePrelude

            pub fn main() -> Unit !io = {
              let r = Rect(h: 3.0, w: 2.0)
              match r {
                Rect(w, h) -> println("w={w} h={h}")
                _ -> println("no")
              }
            }
        """.trimIndent())
        assertEquals("w=2.0 h=3.0\n", out)
    }

    @Test
    fun namedArgumentsEvaluateInWrittenOrder() {
        val out = run("""
            type Pair = | Mk(a: Int, b: Int)

            fn trace(tag: String, v: Int) -> Int !io = {
              println(tag)
              v
            }

            pub fn main() -> Unit !io = {
              let p = Mk(b: trace("first", 2), a: trace("second", 1))
              match p {
                Mk(a, b) -> println("a={a} b={b}")
              }
            }
        """.trimIndent())
        assertEquals("first\nsecond\na=1 b=2\n", out)
    }

    @Test
    fun recursiveTypeTreeEval() {
        val out = run("""
            type Expr =
              | Num(v: Int)
              | Add(l: Expr, r: Expr)
              | Mul(l: Expr, r: Expr)

            fn eval(e: Expr) -> Int =
              match e {
                Num(v)    -> v
                Add(l, r) -> eval(l) + eval(r)
                Mul(l, r) -> eval(l) * eval(r)
              }

            pub fn main() -> Unit !io = {
              # (2 + 3) * 4
              let e = Mul(Add(Num(2), Num(3)), Num(4))
              println("{eval(e)}")
            }
        """.trimIndent())
        assertEquals("20\n", out)
    }

    @Test
    fun nestedPatternsAndRest() {
        val out = run("""
            type Opt = | Got(v: Int) | Nothing
            type Box = | Box(inner: Opt, label: String)

            fn peek(b: Box) -> String =
              match b {
                Box(Got(0), ..)   -> "zero"
                Box(Got(v), ..)   -> "got {v}"
                Box(Nothing, lab) -> "empty {lab}"
              }

            pub fn main() -> Unit !io = {
              println(peek(Box(Got(0), "a")))
              println(peek(Box(Got(7), "b")))
              println(peek(Box(Nothing, "c")))
            }
        """.trimIndent())
        assertEquals("zero\ngot 7\nempty c\n", out)
    }

    @Test
    fun namedFieldPatterns() {
        val out = run("""
            $shapePrelude

            pub fn main() -> Unit !io = {
              let s = Rect(2.0, 3.0)
              match s {
                Rect(h: hh, ..) -> println("h={hh}")
                _ -> println("no")
              }
            }
        """.trimIndent())
        assertEquals("h=3.0\n", out)
    }

    @Test
    fun structuralEquality() {
        val out = run("""
            $shapePrelude

            pub fn main() -> Unit !io = {
              println("{Circle(1.0) == Circle(1.0)}")
              println("{Circle(1.0) == Circle(2.0)}")
              println("{Circle(1.0) != Rect(1.0, 1.0)}")
              println("{Point == Point}")
            }
        """.trimIndent())
        assertEquals("true\nfalse\ntrue\ntrue\n", out)
    }

    @Test
    fun orPatternsOnConstructors() {
        val out = run("""
            type Color = | Red | Green | Blue

            fn warm(c: Color) -> Bool =
              match c {
                Red | Green -> true
                Blue        -> false
              }

            pub fn main() -> Unit !io = {
              println("{warm(Red)} {warm(Green)} {warm(Blue)}")
            }
        """.trimIndent())
        assertEquals("true true false\n", out)
    }

    @Test
    fun singleCtorFullDestructureIsExhaustive() {
        val out = run("""
            type Point2 = | P(x: Int, y: Int)

            fn sum(p: Point2) -> Int =
              match p {
                P(x, y) -> x + y
              }

            pub fn main() -> Unit !io = println("{sum(P(3, 4))}")
        """.trimIndent())
        assertEquals("7\n", out)
    }

    // ---- diagnostics ----

    @Test
    fun nonExhaustiveListsMissingCtors() {
        val diags = errorsOf("""
            $shapePrelude

            fn f(s: Shape) -> Int =
              match s {
                Circle(r) -> 1
              }

            pub fn main() -> Unit !io = println("{f(Point)}")
        """.trimIndent())
        assertHasError(diags, "non-exhaustive match, missing: Rect, Point")
    }

    @Test
    fun guardedArmDoesNotCountAsCoverage() {
        val diags = errorsOf("""
            type Color = | Red | Blue

            fn f(c: Color) -> Int =
              match c {
                Red if true -> 1
                Blue        -> 2
              }

            pub fn main() -> Unit !io = println("{f(Red)}")
        """.trimIndent())
        assertHasError(diags, "non-exhaustive match, missing: Red")
    }

    @Test
    fun undefinedConstructor() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let x = Bogus(1)
              println("x")
            }
        """.trimIndent())
        assertHasError(diags, "undefined constructor: Bogus")
    }

    @Test
    fun arityAndFieldErrors() {
        val diags = errorsOf("""
            $shapePrelude

            pub fn main() -> Unit !io = {
              let a = Rect(1.0)
              let b = Rect(1.0, 2.0, 3.0)
              let c = Rect(1.0, x: 2.0)
              let d = Rect(w: 1.0, 2.0)
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "missing field(s) in `Rect`: h")
        assertHasError(diags, "`Rect` takes 2 field(s), got 3")
        assertHasError(diags, "`Rect` has no field `x`")
        assertHasError(diags, "positional arguments cannot follow named arguments")
    }

    @Test
    fun fieldTypeMismatch() {
        val diags = errorsOf("""
            $shapePrelude

            pub fn main() -> Unit !io = {
              let a = Circle(1)
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "field `r` of `Circle` is Float, got Int")
    }

    @Test
    fun bareCtorWithFieldsRejected() {
        val diags = errorsOf("""
            $shapePrelude

            pub fn main() -> Unit !io = {
              let a = Circle
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "has 1 field(s) and cannot be used bare")
    }

    @Test
    fun patternMustMentionAllFieldsOrRest() {
        val diags = errorsOf("""
            $shapePrelude

            fn f(s: Shape) -> Float =
              match s {
                Rect(w) -> w
                _       -> 0.0
              }

            pub fn main() -> Unit !io = println("{f(Point)}")
        """.trimIndent())
        assertHasError(diags, "pattern for `Rect` does not mention: h")
    }

    @Test
    fun wrongAdtInPattern() {
        val diags = errorsOf("""
            $shapePrelude
            type Color = | Red | Blue

            fn f(s: Shape) -> Int =
              match s {
                Red -> 1
                _   -> 0
              }

            pub fn main() -> Unit !io = println("{f(Point)}")
        """.trimIndent())
        assertHasError(diags, "`Red` is a Color constructor, but the scrutinee is Shape")
    }

    @Test
    fun orPatternBindingsRejectedInsideCtors() {
        val diags = errorsOf("""
            $shapePrelude

            fn f(s: Shape) -> Float =
              match s {
                Circle(r) | Rect(r, ..) -> r
                _ -> 0.0
              }

            pub fn main() -> Unit !io = println("{f(Point)}")
        """.trimIndent())
        assertHasError(diags, "or-pattern alternatives cannot introduce bindings")
    }

    @Test
    fun duplicateTypesAndCtors() {
        val diags = errorsOf("""
            type A = | X
            type A = | Y
            type B = | X

            pub fn main() -> Unit !io = println("ok")
        """.trimIndent())
        assertHasError(diags, "type `A` is defined twice")
        assertHasError(diags, "constructor `X` is already defined")
    }

    @Test
    fun adtCannotInterpolate() {
        val diags = errorsOf("""
            $shapePrelude

            pub fn main() -> Unit !io = println("{Point}")
        """.trimIndent())
        assertHasError(diags, "cannot interpolate a value of type Shape")
    }
}
