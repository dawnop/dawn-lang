package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Knife 5 of traits: sort / sort_by / max / min / max_by / min_by builtins and
 * derive Ord (constructor order first, then fields lexicographically).
 */
class TraitStdlibTest {

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

    private fun assertError(source: String, needle: String) {
        val msgs = analyze(source).diagnostics.map { it.message }
        assertTrue(msgs.any { it.contains(needle) },
            "expected an error containing `$needle`, got:\n" + msgs.joinToString("\n"))
    }

    // ---- sorting and extremes over scalars ----

    @Test
    fun sortOnScalars() {
        val out = run("""
            pub fn main() -> Unit !io = {
              println("${'$'}{sort([3, 1, 2])}")
              println("${'$'}{sort(["pear", "apple", "fig"])}")
              println("${'$'}{sort([2.5, 0.5, 1.5])}")
            }
        """.trimIndent())
        assertEquals("[1, 2, 3]\n[\"apple\", \"fig\", \"pear\"]\n[0.5, 1.5, 2.5]\n", out)
    }

    @Test
    fun sortByComparatorFunction() {
        val out = run("""
            pub fn main() -> Unit !io =
              println("${'$'}{sort_by([3, 1, 2], fn(a, b) => b - a)}")
        """.trimIndent())
        assertEquals("[3, 2, 1]\n", out)
    }

    @Test
    fun maxMinIncludingEmpty() {
        val out = run("""
            pub fn main() -> Unit !io = {
              println("${'$'}{max([3, 9, 4])} ${'$'}{min([3, 9, 4])}")
              println("${'$'}{max(["a", "z", "m"])}")
              match max([1]) {
                Some(x) -> println("${'$'}x")
                None -> println("none")
              }
              let empty: List[Int] = []
              match min(empty) {
                Some(x) -> println("${'$'}x")
                None -> println("none")
              }
            }
        """.trimIndent())
        assertEquals("Some(9) Some(3)\nSome(\"z\")\n1\nnone\n", out)
    }

    @Test
    fun maxByMinByWithKeys() {
        val out = run("""
            use std/str

            pub fn main() -> Unit !io = {
              let words = ["fig", "banana", "kiwi"]
              match max_by(words, fn(w) => str.len(w)) {
                Some(w) -> println(w)
                None -> println("none")
              }
              match min_by(words, fn(w) => str.len(w)) {
                Some(w) -> println(w)
                None -> println("none")
              }
              match max_by(words, fn(w) => w) {
                Some(w) -> println(w)
                None -> println("none")
              }
            }
        """.trimIndent())
        assertEquals("banana\nfig\nkiwi\n", out)
    }

    @Test
    fun sortUsesUserImpl() {
        val out = run("""
            type Point = { x: Int, y: Int }

            impl Ord[Point] {
              fn cmp(a: Point, b: Point) -> Int = a.x - b.x
            }

            pub fn main() -> Unit !io = {
              let ps = sort([Point { x: 3, y: 0 }, Point { x: 1, y: 0 }, Point { x: 2, y: 0 }])
              println("${'$'}{map(ps, fn(p) => p.x)}")
            }
        """.trimIndent())
        assertEquals("[1, 2, 3]\n", out)
    }

    @Test
    fun sortInsideBoundedGenericForwardsTheDict() {
        val out = run("""
            fn median[T: Ord](xs: List[T]) -> Option[T] = get(sort(xs), len(xs) / 2)

            pub fn main() -> Unit !io = {
              match median([9, 1, 5]) {
                Some(x) -> println("${'$'}x")
                None -> println("none")
              }
            }
        """.trimIndent())
        assertEquals("5\n", out)
    }

    @Test
    fun sortIsStable() {
        val out = run("""
            type Card = { rank: Int, tag: String }

            pub fn main() -> Unit !io = {
              let cards = [Card { rank: 2, tag: "a" }, Card { rank: 1, tag: "x" },
                           Card { rank: 2, tag: "b" }]
              let sorted = sort_by(cards, fn(a, b) => a.rank - b.rank)
              println("${'$'}{map(sorted, fn(c) => c.tag)}")
            }
        """.trimIndent())
        assertEquals("[\"x\", \"a\", \"b\"]\n", out)
    }

    @Test
    fun comptimeSortBy() {
        val out = run("""
            const XS: List[Int] = sort_by([3, 1, 2], fn(a, b) => a - b)

            pub fn main() -> Unit !io = println("${'$'}XS")
        """.trimIndent())
        assertEquals("[1, 2, 3]\n", out)
    }

    // ---- derive Ord ----

    @Test
    fun deriveOrdOnRecordComparesFieldsLexicographically() {
        val out = run("""
            type Point = { x: Int, y: Int } derive Show, Ord

            pub fn main() -> Unit !io = {
              let a = Point { x: 1, y: 9 }
              let b = Point { x: 1, y: 2 }
              let c = Point { x: 0, y: 99 }
              println("${'$'}{a > b} ${'$'}{c < b} ${'$'}{a <= a}")
              println("${'$'}{sort([a, b, c])}")
            }
        """.trimIndent())
        assertEquals("true true true\n[Point { x: 0, y: 99 }, Point { x: 1, y: 2 }, Point { x: 1, y: 9 }]\n", out)
    }

    @Test
    fun deriveOrdOnSumTypeUsesCtorOrderThenPayload() {
        val out = run("""
            type Size =
              | Small
              | Medium(extra: Int)
              | Large
              derive Ord

            pub fn main() -> Unit !io = {
              println("${'$'}{Small < Medium(0)} ${'$'}{Medium(9) < Large} ${'$'}{Large < Small}")
              println("${'$'}{Medium(1) < Medium(2)} ${'$'}{Medium(2) <= Medium(2)} ${'$'}{Small <= Small}")
            }
        """.trimIndent())
        assertEquals("true true false\ntrue true true\n", out)
    }

    @Test
    fun deriveOrdNestsThroughDerivedAndStringFields() {
        val out = run("""
            type Name = { s: String } derive Ord
            type Person = { name: Name, age: Int } derive Ord

            pub fn main() -> Unit !io = {
              let a = Person { name: Name { s: "ann" }, age: 30 }
              let b = Person { name: Name { s: "bob" }, age: 20 }
              let c = Person { name: Name { s: "ann" }, age: 25 }
              println("${'$'}{a < b} ${'$'}{c < a} ${'$'}{b > c}")
            }
        """.trimIndent())
        assertEquals("true true true\n", out)
    }

    @Test
    fun deriveOrdWorksAsABound() {
        val out = run("""
            type P = { v: Int } derive Ord

            fn max2[T: Ord](a: T, b: T) -> T = if a < b { b } else { a }

            pub fn main() -> Unit !io = println("${'$'}{max2(P { v: 2 }, P { v: 7 }).v}")
        """.trimIndent())
        assertEquals("7\n", out)
    }

    @Test
    fun deriveOrdRejectsUnorderableFields() {
        assertError("type P = { flag: Bool } derive Ord\nfn f() -> Int = 1",
            "cannot derive Ord for `P`: field `flag` of type Bool is not orderable")
        assertError("type P = { xs: List[Int] } derive Ord\nfn f() -> Int = 1",
            "field `xs` of type List[Int] is not orderable")
    }

    @Test
    fun deriveOrdRejectsGenericTypes() {
        assertError("type Box[T] = | Full(v: T) | Empty derive Ord\nfn f() -> Int = 1",
            "cannot derive Ord for the generic type `Box`")
    }

    @Test
    fun deriveAndExplicitImplIsDuplicate() {
        assertError("""
            type P = { v: Int } derive Ord
            impl Ord[P] { fn cmp(a: P, b: P) -> Int = a.v - b.v }
            fn f() -> Int = 1
        """.trimIndent(), "duplicate impl: `Ord[P]` is already implemented")
    }

    @Test
    fun explicitImplFieldSatisfiesDerive() {
        val out = run("""
            type Inner = { v: Int }

            impl Ord[Inner] {
              fn cmp(a: Inner, b: Inner) -> Int = b.v - a.v
            }

            type Outer = { inner: Inner } derive Ord

            pub fn main() -> Unit !io = {
              let a = Outer { inner: Inner { v: 1 } }
              let b = Outer { inner: Inner { v: 2 } }
              println("${'$'}{a < b} ${'$'}{b < a}")
            }
        """.trimIndent())
        assertEquals("false true\n", out)
    }
}
