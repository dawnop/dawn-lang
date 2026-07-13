package dawn

import dawn.ast.Binary
import dawn.ast.Call
import dawn.ast.Lambda
import dawn.ast.Module
import dawn.check.WitnessRef
import dawn.check.analyze
import dawn.check.analyzeProject
import org.junit.jupiter.api.io.TempDir
import java.io.File
import kotlin.test.Test
import kotlin.test.assertTrue

/**
 * Knife 3 of traits: constraint resolution at use sites (docs/trait.md §4.2/§5).
 * Concrete subjects resolve to their unique impl; a caller's rigid type
 * parameter forwards the caller's dictionary; `< <= > >=` bridge to Ord.
 */
class TraitResolveTest {

    private fun messages(source: String): List<String> =
        analyze(source).diagnostics.map { it.message }

    private fun assertClean(source: String) {
        val msgs = messages(source)
        assertTrue(msgs.isEmpty(), "expected a clean module, got:\n" + msgs.joinToString("\n"))
    }

    private fun assertError(source: String, needle: String) {
        val msgs = messages(source)
        assertTrue(msgs.any { it.contains(needle) },
            "expected an error containing `$needle`, got:\n" + msgs.joinToString("\n"))
    }

    private fun cleanModule(source: String): Module {
        val a = analyze(source)
        assertTrue(a.diagnostics.isEmpty(),
            "expected a clean module, got:\n" + a.diagnostics.joinToString("\n") { it.message })
        return a.module
    }

    private fun fnBody(m: Module, name: String) = m.fns.first { it.name == name }.body

    private val myOrd = """
        trait MyOrd[T] {
          fn cmp2(a: T, b: T) -> Int
        }

        type Point = { x: Int, y: Int }

    """.trimIndent()

    private val myOrdImpl = myOrd + """
        impl MyOrd[Point] {
          fn cmp2(a: Point, b: Point) -> Int = a.x - b.x
        }

    """.trimIndent()

    // ---- concrete resolution ----

    @Test
    fun genericCallWithConcreteSubjectResolvesToImpl() {
        val m = cleanModule(myOrdImpl + """
            fn smaller[T: MyOrd](a: T, b: T) -> T = if cmp2(a, b) <= 0 { a } else { b }
            fn use_it(p: Point, q: Point) -> Point = smaller(p, q)
        """.trimIndent())
        val call = fnBody(m, "use_it") as Call
        val w = call.witnesses!!.single() as WitnessRef.Concrete
        assertTrue(w.impl.display == "MyOrd[Point]")
    }

    @Test
    fun genericCallWithoutImplIsRejected() {
        assertError(myOrd + """
            fn smaller[T: MyOrd](a: T, b: T) -> T = if cmp2(a, b) <= 0 { a } else { b }
            fn use_it(p: Point, q: Point) -> Point = smaller(p, q)
        """.trimIndent(), "no impl of `MyOrd` for `Point`")
    }

    @Test
    fun traitMethodCallOnConcreteSubject() {
        val m = cleanModule(myOrdImpl + "fn f(p: Point, q: Point) -> Int = cmp2(p, q)")
        val call = fnBody(m, "f") as Call
        assertTrue(call.witnesses!!.single() is WitnessRef.Concrete)
    }

    @Test
    fun traitMethodCallWithoutImplIsRejected() {
        assertError(myOrd + "fn f(p: Point, q: Point) -> Int = cmp2(p, q)",
            "no impl of `MyOrd` for `Point`")
    }

    @Test
    fun ufcsTraitMethodCall() {
        assertClean(myOrdImpl + "fn f(p: Point, q: Point) -> Int = p.cmp2(q)")
    }

    // ---- forwarding the caller's dictionary ----

    @Test
    fun boundedFnForwardsItsOwnDictionary() {
        val m = cleanModule(myOrd + "fn f[T: MyOrd](a: T, b: T) -> Int = cmp2(a, b)")
        val call = fnBody(m, "f") as Call
        val w = call.witnesses!!.single() as WitnessRef.Forward
        assertTrue(w.trait.name == "MyOrd" && w.sym.dictOf != null)
    }

    @Test
    fun unboundedTParamCannotCallTraitMethod() {
        assertError(myOrd + "fn f[T](a: T, b: T) -> Int = cmp2(a, b)",
            "`cmp2` requires `MyOrd[T]`, but `T` has no such bound")
    }

    @Test
    fun boundedFnCallsAnotherBoundedFn() {
        assertClean(myOrd + """
            fn f[T: MyOrd](a: T, b: T) -> Int = cmp2(a, b)
            fn g[T: MyOrd](a: T, b: T) -> Int = f(a, b)
        """.trimIndent())
    }

    @Test
    fun missingSecondBoundIsReported() {
        assertError("""
            trait A[T] { fn fa(x: T) -> Int }
            trait B[T] { fn fb(x: T) -> Int }
            fn g[T: A + B](x: T) -> Int = fa(x) + fb(x)
            fn f[T: A](x: T) -> Int = g(x)
        """.trimIndent(), "`g` requires `B[T]`, but `T` has no such bound")
    }

    @Test
    fun multipleBoundsResolveMultipleWitnesses() {
        val m = cleanModule("""
            trait A[T] { fn fa(x: T) -> Int }
            trait B[T] { fn fb(x: T) -> Int }
            type Point = { x: Int }
            impl A[Point] { fn fa(x: Point) -> Int = x.x }
            impl B[Point] { fn fb(x: Point) -> Int = 0 - x.x }
            fn g[T: A + B](x: T) -> Int = fa(x) + fb(x)
            fn use_it(p: Point) -> Int = g(p)
        """.trimIndent())
        val call = fnBody(m, "use_it") as Call
        assertTrue(call.witnesses!!.size == 2 && call.witnesses!!.all { it is WitnessRef.Concrete })
    }

    @Test
    fun lambdaCapturesTheDictionary() {
        val m = cleanModule(myOrd + """
            fn pick[T: MyOrd](xs: List[Int], a: T, b: T) -> List[Int] =
              map(xs, fn(i) => i + cmp2(a, b))
        """.trimIndent())
        val body = fnBody(m, "pick") as Call
        val lambda = body.args[1] as Lambda
        assertTrue(lambda.captures!!.any { it.dictOf != null },
            "the hidden dictionary must be captured alongside a and b")
    }

    // ---- operator bridging to Ord ----

    @Test
    fun operatorUsesUserOrdImpl() {
        val m = cleanModule("""
            type Point = { x: Int, y: Int }
            impl Ord[Point] {
              fn cmp(a: Point, b: Point) -> Int = a.x - b.x
            }
            fn f(p: Point, q: Point) -> Bool = p < q
        """.trimIndent())
        val bin = fnBody(m, "f") as Binary
        assertTrue(bin.ordWitness is WitnessRef.Concrete)
    }

    @Test
    fun operatorWithoutImplKeepsClassicMessage() {
        assertError("type Point = { x: Int }\nfn f(p: Point, q: Point) -> Bool = p < q",
            "values of type Point cannot be ordered")
    }

    @Test
    fun operatorOnBoundedTParamForwards() {
        val m = cleanModule("fn max2[T: Ord](a: T, b: T) -> T = if a < b { b } else { a }")
        val iff = fnBody(m, "max2") as dawn.ast.If
        val bin = iff.cond as Binary
        assertTrue(bin.ordWitness is WitnessRef.Forward)
    }

    @Test
    fun operatorOnUnboundedTParamIsRejected() {
        assertError("fn f[T](a: T, b: T) -> Bool = a < b", "values of type T cannot be ordered")
    }

    @Test
    fun nativeScalarComparisonsCarryNoWitness() {
        val m = cleanModule("""
            fn f() -> Bool = 1 < 2
            fn g() -> Bool = "a" < "b"
            fn h() -> Bool = 1.0 < 2.0
        """.trimIndent())
        for (n in listOf("f", "g", "h"))
            assertTrue((fnBody(m, n) as Binary).ordWitness == null, "scalars stay native")
    }

    @Test
    fun boolStillCannotBeOrdered() {
        assertError("fn f() -> Bool = true < false", "values of type Bool cannot be ordered")
    }

    @Test
    fun listsStillCannotBeOrdered() {
        assertError("fn f() -> Bool = [1] < [2]", "values of type List[Int] cannot be ordered")
    }

    // ---- the prelude Ord trait ----

    @Test
    fun preludeCmpWorksOnScalars() {
        assertClean("fn f() -> Int = cmp(1, 2)\nfn g() -> Int = cmp(\"a\", \"b\")")
    }

    @Test
    fun ordCannotBeRedefined() {
        assertError("trait Ord[T] { fn c(a: T) -> Int }", "`Ord` is a prelude trait and cannot be redefined")
    }

    @Test
    fun userImplOfOrdForScalarIsRejected() {
        // Ord and Int both live in the prelude, so no user module may host this impl
        assertError("impl Ord[Int] { fn cmp(a: Int, b: Int) -> Int = 0 }\nfn f() -> Int = 1",
            "orphan impl")
    }

    // ---- function values ----

    @Test
    fun traitMethodCannotBeAValue() {
        assertError(myOrdImpl + """
            fn f() -> Int = {
              let g = cmp2
              0
            }
        """.trimIndent(), "trait method `cmp2` cannot be used as a value")
    }

    @Test
    fun boundedFnCannotBeAValue() {
        assertError(myOrdImpl + """
            fn smaller[T: MyOrd](a: T, b: T) -> T = if cmp2(a, b) <= 0 { a } else { b }
            fn f() -> Int = {
              let g = smaller
              0
            }
        """.trimIndent(), "`smaller` has trait bounds and cannot be used as a value")
    }

    // ---- comptime ----

    @Test
    fun comptimeRejectsTraitBoundedCalls() {
        assertError("const X: Int = cmp(1, 2)", "uses trait bounds, which comptime cannot evaluate")
    }

    @Test
    fun comptimeScalarComparisonStillWorks() {
        assertClean("const X: Bool = 1 < 2\nfn f() -> Bool = X")
    }

    // ---- across modules ----

    private fun project(dir: File, files: Map<String, String>) {
        for ((rel, text) in files) {
            val f = File(dir, "src/$rel")
            f.parentFile.mkdirs()
            f.writeText(text)
        }
    }

    @Test
    fun importedBoundedFnResolvesAgainstLocalImpl(@TempDir dir: File) {
        project(dir, mapOf(
            "traits.dawn" to """
                pub trait MyOrd[T] { fn cmp2(a: T, b: T) -> Int }
                pub fn smaller[T: MyOrd](a: T, b: T) -> T = if cmp2(a, b) <= 0 { a } else { b }
            """.trimIndent(),
            "main.dawn" to """
                use traits.{MyOrd, smaller}
                type Point = { x: Int, y: Int }
                impl MyOrd[Point] { fn cmp2(a: Point, b: Point) -> Int = a.x - b.x }
                pub fn main() -> Unit !io = {
                  let p = Point { x: 1, y: 2 }
                  let q = Point { x: 3, y: 4 }
                  println("{smaller(p, q).x}")
                }
            """.trimIndent(),
        ))
        val msgs = analyzeProject(dir).diagnostics.map { it.diag.message }
        assertTrue(msgs.isEmpty(), "expected a clean program, got:\n" + msgs.joinToString("\n"))
    }
}
