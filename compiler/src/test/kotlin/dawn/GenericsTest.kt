package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M1 generics: type parameters, erasure+boxing, Option/Result prelude, List. */
class GenericsTest {

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

    // ---- Option / Result prelude ----

    @Test
    fun optionMatchAndBoxing() {
        val out = run("""
            fn or_zero(o: Option[Int]) -> Int =
              match o {
                Some(v) -> v
                None    -> 0
              }

            pub fn main() -> Unit !io = {
              println("{or_zero(Some(41)) + 1}")
              let n: Option[Int] = None
              println("{or_zero(n)}")
            }
        """.trimIndent())
        assertEquals("42\n0\n", out)
    }

    @Test
    fun noneInfersFromSiblingArgument() {
        val out = run("""
            fn or_default[T](o: Option[T], d: T) -> T =
              match o {
                Some(v) -> v
                None    -> d
              }

            pub fn main() -> Unit !io = {
              println("{or_default(None, 5)}")
              println(or_default(Some("hi"), "bye"))
            }
        """.trimIndent())
        assertEquals("5\nhi\n", out)
    }

    @Test
    fun resultOkErr() {
        val out = run("""
            fn div(a: Int, b: Int) -> Result[Int, String] =
              if b == 0 { Err("division by zero") } else { Ok(a / b) }

            fn show(r: Result[Int, String]) -> String =
              match r {
                Ok(v)  -> "ok {v}"
                Err(m) -> "err: {m}"
              }

            pub fn main() -> Unit !io = {
              println(show(div(10, 3)))
              println(show(div(1, 0)))
            }
        """.trimIndent())
        assertEquals("ok 3\nerr: division by zero\n", out)
    }

    @Test
    fun nestedOptionExhaustiveness() {
        val out = run("""
            fn f(o: Option[Option[Int]]) -> Int =
              match o {
                Some(Some(v)) -> v
                Some(None)    -> -1
                None          -> -2
              }

            pub fn main() -> Unit !io = {
              println("{f(Some(Some(7)))} {f(Some(None))} {f(None)}")
            }
        """.trimIndent())
        assertEquals("7 -1 -2\n", out)
    }

    // ---- generic user types ----

    @Test
    fun genericTree() {
        val out = run("""
            type Tree[T] =
              | Leaf
              | Node(left: Tree[T], value: T, right: Tree[T])

            fn insert(t: Tree[Int], v: Int) -> Tree[Int] =
              match t {
                Leaf -> Node(Leaf, v, Leaf)
                Node(l, x, r) ->
                  if v < x { Node(insert(l, v), x, r) }
                  else { Node(l, x, insert(r, v)) }
              }

            fn total(t: Tree[Int]) -> Int =
              match t {
                Leaf -> 0
                Node(l, v, r) -> total(l) + v + total(r)
              }

            pub fn main() -> Unit !io = {
              let e: Tree[Int] = Leaf
              let t = insert(insert(insert(e, 5), 2), 8)
              println("{total(t)}")
            }
        """.trimIndent())
        assertEquals("15\n", out)
    }

    @Test
    fun genericRecordPair() {
        val out = run("""
            type Pair[A, B] = { first: A, second: B }

            fn swap[A, B](p: Pair[A, B]) -> Pair[B, A] =
              Pair { first: p.second, second: p.first }

            pub fn main() -> Unit !io = {
              let p = Pair { first: 1, second: "one" }
              let q = swap(p)
              println("{p.first} {p.second}")
              println("{q.first} {q.second}")
            }
        """.trimIndent())
        assertEquals("1 one\none 1\n", out)
    }

    @Test
    fun genericIdentityFunction() {
        val out = run("""
            fn id[T](x: T) -> T = x

            pub fn main() -> Unit !io = {
              println("{id(42)}")
              println(id("str"))
              println("{id(true)}")
            }
        """.trimIndent())
        assertEquals("42\nstr\ntrue\n", out)
    }

    // ---- lists ----

    @Test
    fun listBasics() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let xs = [10, 20, 30]
              println("{len(xs)}")
              match get(xs, 1) {
                Some(v) -> println("{v}")
                None    -> println("missing")
              }
              match get(xs, 99) {
                Some(v) -> println("{v}")
                None    -> println("missing")
              }
            }
        """.trimIndent())
        assertEquals("3\n20\nmissing\n", out)
    }

    @Test
    fun listConcatRangeEquality() {
        val out = run("""
            pub fn main() -> Unit !io = {
              let a = [1, 2] ++ [3]
              println("{a == [1, 2, 3]}")
              println("{range(1, 4) == a}")
              let empty: List[Int] = []
              println("{len(empty ++ a)}")
            }
        """.trimIndent())
        assertEquals("true\ntrue\n3\n", out)
    }

    @Test
    fun listOfAdtsAndStrings() {
        val out = run("""
            type Color = | Red | Green | Blue

            fn name(c: Color) -> String =
              match c { Red -> "r", Green -> "g", Blue -> "b" }

            pub fn main() -> Unit !io = {
              let cs = [Red, Blue]
              match get(cs, 1) {
                Some(c) -> println(name(c))
                None    -> println("?")
              }
              println("{[Red] == [Red]}")
              let words = ["a", "b"] ++ ["c"]
              println("{len(words)}")
            }
        """.trimIndent())
        assertEquals("b\ntrue\n3\n", out)
    }

    @Test
    fun forOverLists() {
        val out = run("""
            type Color = | Red | Green | Blue

            fn name(c: Color) -> String =
              match c { Red -> "r", Green -> "g", Blue -> "b" }

            pub fn main() -> Unit !io = {
              var sum = 0
              for x in [10, 20, 30] {
                sum = sum + x
              }
              println("{sum}")
              for c in [Red, Blue] {
                print(name(c))
              }
              println("")
            }
        """.trimIndent())
        assertEquals("60\nrb\n", out)
    }

    @Test
    fun sumViaRangeAndGet() {
        val out = run("""
            fn sum_to(n: Int) -> Int = {
              let xs = range(0, n)
              var acc = 0
              for i in 0..len(xs) {
                acc = acc + match get(xs, i) { Some(v) -> v, None -> 0 }
              }
              acc
            }

            pub fn main() -> Unit !io = println("{sum_to(101)}")
        """.trimIndent())
        assertEquals("5050\n", out)
    }

    // ---- diagnostics ----

    @Test
    fun bareNoneNeedsContext() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let x = None
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "cannot infer type parameter(s) T for `None`")
    }

    @Test
    fun emptyListNeedsAnnotation() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let xs = []
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "cannot infer the element type of an empty list")
    }

    @Test
    fun typeArgumentArity() {
        val diags = errorsOf("""
            type Box[T] = | Full(v: T) | Empty

            fn f(a: Box, b: List[Int, Int], c: Int[Float]) -> Int = 0

            pub fn main() -> Unit !io = println("{f(Empty, [1], 2)}")
        """.trimIndent())
        assertHasError(diags, "`Box` takes 1 type parameter(s), got 0")
        assertHasError(diags, "List takes exactly one type argument")
        assertHasError(diags, "`Int` is not generic")
    }

    @Test
    fun genericArgumentMismatch() {
        val diags = errorsOf("""
            fn want_str(o: Option[String]) -> Int = 0

            pub fn main() -> Unit !io = println("{want_str(Some(1))}")
        """.trimIndent())
        // expected-type seeding pins T = String, so the error lands on Some's field
        assertHasError(diags, "field `value` of `Some` is String, got Int")
    }

    @Test
    fun listConcatElementMismatch() {
        val diags = errorsOf("""
            pub fn main() -> Unit !io = {
              let a = [1] ++ ["x"]
              println("ok")
            }
        """.trimIndent())
        assertHasError(diags, "`++` needs lists of the same element type")
    }

    @Test
    fun preludeCannotBeRedefined() {
        val diags = errorsOf("""
            type Option = | Yes | No

            pub fn main() -> Unit !io = println("ok")
        """.trimIndent())
        assertHasError(diags, "`Option` is a prelude type and cannot be redefined")
    }

    @Test
    fun optionExhaustivenessWithArgs() {
        val diags = errorsOf("""
            fn f(o: Option[Int]) -> Int =
              match o {
                Some(v) -> v
              }

            pub fn main() -> Unit !io = println("{f(None)}")
        """.trimIndent())
        assertHasError(diags, "non-exhaustive match, missing: None")
    }
}
