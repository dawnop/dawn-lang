package dawn

import dawn.check.analyze
import dawn.check.analyzeProject
import org.junit.jupiter.api.io.TempDir
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Knife 2 of traits: registration, namespaces, signature matching, coverage,
 * the orphan rule, and program-wide coherence (docs/trait.md §3.3/§4.1).
 * Resolution at call sites (witnesses, operator bridging) is knife 3.
 */
class TraitCheckTest {

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

    // ---- registration ----

    @Test
    fun validTraitAndImplAreClean() {
        assertClean(
            """
            trait MyOrd[T] {
              fn compare_to(a: T, b: T) -> Int
              fn max_of(a: T, b: T) -> T = if compare_to(a, b) >= 0 { a } else { b }
            }

            type Point = { x: Int, y: Int }

            impl MyOrd[Point] {
              fn compare_to(a: Point, b: Point) -> Int =
                if a.x != b.x { a.x - b.x } else { a.y - b.y }
            }
            """.trimIndent(),
        )
    }

    @Test
    fun traitDefinedTwice() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int }\ntrait A[T] { fn g(x: T) -> Int }",
            "trait `A` is defined twice",
        )
    }

    @Test
    fun traitCollidesWithTypeName() {
        assertError(
            "type A = { x: Int }\ntrait A[T] { fn f(x: T) -> Int }",
            "trait `A` collides with a type of the same name",
        )
    }

    @Test
    fun traitCannotUseBuiltinTypeName() {
        assertError("trait Int[T] { fn f(x: T) -> Int }", "builtin type and cannot be a trait name")
    }

    @Test
    fun methodMayShadowABuiltinFn() {
        // spec §10.6: a trait method, like a top-level fn, shadows a builtin name
        assertClean("trait A[T] { fn len(x: T) -> Int }")
    }

    @Test
    fun fnCollidesWithTraitMethod() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int }\nfn f(x: Int) -> Int = x",
            "already a method of trait `A`",
        )
    }

    @Test
    fun twoTraitsCannotShareAMethodName() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int }\ntrait B[T] { fn f(x: T) -> Int }",
            "already a method of trait `A`",
        )
    }

    @Test
    fun traitMethodRejectsEffectVariables() {
        assertError("trait A[T] { fn f(x: T) -> Int !e }", "trait methods cannot declare effect variables")
    }

    @Test
    fun traitMethodRejectsEffectVariablesInFnTypes() {
        assertError(
            "trait A[T] { fn f(x: T, g: fn(T) -> T !e) -> Int }",
            "trait method signatures cannot carry effect variables",
        )
    }

    // ---- impls: subject, orphan (single-file is always local), coherence ----

    @Test
    fun unknownTraitInImpl() {
        assertError("impl Nope[Int] {\n}", "unknown trait: Nope")
    }

    @Test
    fun subjectCannotBeList() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int }\nimpl A[List[Int]] { fn f(x: List[Int]) -> Int = 0 }",
            "cannot be an impl subject",
        )
    }

    @Test
    fun subjectCannotBeGenericAdt() {
        assertError(
            """
            trait A[T] { fn f(x: T) -> Int }
            type Box[T] = { value: T }
            impl A[Box] { fn f(x: Box) -> Int = 0 }
            """.trimIndent(),
            "takes 1 type parameter",
        )
    }

    @Test
    fun subjectCannotBeInstantiatedGeneric() {
        assertError(
            """
            trait A[T] { fn f(x: T) -> Int }
            type Box[T] = { value: T }
            impl A[Box[Int]] { fn f(x: Box[Int]) -> Int = 0 }
            """.trimIndent(),
            "cannot be an impl subject",
        )
    }

    @Test
    fun scalarSubjectIsAllowedWhenTraitIsLocal() {
        assertClean(
            "trait A[T] { fn f(x: T) -> Int }\nimpl A[Int] {\n  fn f(x: Int) -> Int = x\n}",
        )
    }

    @Test
    fun duplicateImplInOneModule() {
        assertError(
            """
            trait A[T] { fn f(x: T) -> Int }
            impl A[Int] { fn f(x: Int) -> Int = x }
            impl A[Int] { fn f(x: Int) -> Int = 0 - x }
            """.trimIndent(),
            "duplicate impl: `A[Int]`",
        )
    }

    // ---- impls: method matching ----

    @Test
    fun implMethodNotInTrait() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int }\nimpl A[Int] {\n  fn f(x: Int) -> Int = x\n  fn g(x: Int) -> Int = x\n}",
            "trait `A` has no method `g`",
        )
    }

    @Test
    fun implMethodSignatureMismatch() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int }\nimpl A[Int] { fn f(x: Float) -> Int = 0 }",
            "does not match the trait's signature",
        )
    }

    @Test
    fun implMethodReturnMismatch() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int }\nimpl A[Int] { fn f(x: Int) -> Float = 1.0 }",
            "does not match the trait's signature",
        )
    }

    @Test
    fun implMethodCannotAddIo() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int }\nimpl A[Int] { fn f(x: Int) -> Int !io = { println(\"x\")\n 0 } }",
            "trait `A` declares it pure",
        )
    }

    @Test
    fun implMethodMayStayPureWhenTraitIsIo() {
        assertClean(
            "trait A[T] { fn f(x: T) -> Int !io }\nimpl A[Int] { fn f(x: Int) -> Int = x }",
        )
    }

    @Test
    fun missingRequiredMethod() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int\n  fn g(x: T) -> Int }\nimpl A[Int] { fn f(x: Int) -> Int = x }",
            "is missing `g`",
        )
    }

    @Test
    fun defaultMethodMakesImplComplete() {
        assertClean(
            """
            trait A[T] {
              fn f(x: T) -> Int
              fn g(x: T) -> Int = f(x) + 1
            }
            impl A[Int] { fn f(x: Int) -> Int = x }
            """.trimIndent(),
        )
    }

    // ---- bodies ----

    @Test
    fun defaultBodyTypeMismatch() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int = \"nope\" }",
            "declares return type Int but its default body is String",
        )
    }

    @Test
    fun defaultBodyMustRespectPurity() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int = { println(\"hi\")\n 1 } }",
            "is not declared !io but calls `println`",
        )
    }

    @Test
    fun implBodyTypeMismatch() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int }\nimpl A[Int] { fn f(x: Int) -> Int = \"nope\" }",
            "declares return type Int but its body is String",
        )
    }

    // ---- constraints on fn type parameters ----

    @Test
    fun boundResolvesAgainstLocalTrait() {
        assertClean("trait MyOrd[T] { fn cmp2(a: T, b: T) -> Int }\nfn f[T: MyOrd](x: T) -> T = x")
    }

    @Test
    fun unknownTraitInBound() {
        assertError("fn f[T: Nope](x: T) -> T = x", "unknown trait: Nope")
    }

    @Test
    fun duplicateBound() {
        assertError(
            "trait A[T] { fn f(x: T) -> Int }\nfn g[T: A + A](x: T) -> T = x",
            "duplicate trait bound",
        )
    }

    @Test
    fun boundRendersInSignature() {
        val analysis = analyze("trait MyOrd[T] { fn cmp2(a: T, b: T) -> Int }\nfn f[T: MyOrd](x: T) -> T = x")
        assertEquals("fn f[T: MyOrd](x: T) -> T", analysis.functions["f"]!!.render())
    }

    // ---- multi-module: orphan rule, cross-module coherence, imports ----

    private fun project(dir: File, files: Map<String, String>): File {
        for ((rel, text) in files) {
            val f = File(dir, "src/$rel")
            f.parentFile.mkdirs()
            f.writeText(text)
        }
        return dir
    }

    private fun projMessages(dir: File): List<String> =
        analyzeProject(dir).diagnostics.map { it.diag.message }

    private fun assertProjClean(dir: File) {
        val msgs = projMessages(dir)
        assertTrue(msgs.isEmpty(), "expected a clean program, got:\n" + msgs.joinToString("\n"))
    }

    private fun assertProjError(dir: File, needle: String) {
        val msgs = projMessages(dir)
        assertTrue(msgs.any { it.contains(needle) },
            "expected an error containing `$needle`, got:\n" + msgs.joinToString("\n"))
    }

    @Test
    fun implInSubjectsModuleIsLegal(@TempDir dir: File) {
        project(dir, mapOf(
            "traits.dawn" to "pub trait MyOrd[T] { fn cmp2(a: T, b: T) -> Int }\n",
            "point.dawn" to """
                use traits.{MyOrd}
                pub type Point = { x: Int, y: Int }
                impl MyOrd[Point] { fn cmp2(a: Point, b: Point) -> Int = a.x - b.x }
            """.trimIndent(),
            "main.dawn" to """
                use point
                pub fn main() -> Unit !io = println("ok")
            """.trimIndent(),
        ))
        assertProjClean(dir)
    }

    @Test
    fun implInTraitsModuleIsLegal(@TempDir dir: File) {
        project(dir, mapOf(
            "point.dawn" to "pub type Point = { x: Int, y: Int }\n",
            "traits.dawn" to """
                use point.{Point}
                pub trait MyOrd[T] { fn cmp2(a: T, b: T) -> Int }
                impl MyOrd[Point] { fn cmp2(a: Point, b: Point) -> Int = a.x - b.x }
            """.trimIndent(),
            "main.dawn" to """
                use traits
                pub fn main() -> Unit !io = println("ok")
            """.trimIndent(),
        ))
        assertProjClean(dir)
    }

    @Test
    fun orphanImplIsRejected(@TempDir dir: File) {
        project(dir, mapOf(
            "traits.dawn" to "pub trait MyOrd[T] { fn cmp2(a: T, b: T) -> Int }\n",
            "point.dawn" to "pub type Point = { x: Int, y: Int }\n",
            "main.dawn" to """
                use traits.{MyOrd}
                use point.{Point}
                impl MyOrd[Point] { fn cmp2(a: Point, b: Point) -> Int = a.x - b.x }
                pub fn main() -> Unit !io = println("ok")
            """.trimIndent(),
        ))
        assertProjError(dir, "orphan impl")
    }

    /**
     * Cross-module duplicates cannot even form: the only two legal homes for an
     * impl (the trait's module and the subject's module) would each need the
     * other's name, which the module DAG forbids. A third module trying it is
     * an orphan — caught by the orphan rule before the coherence table.
     */
    @Test
    fun crossModuleDuplicateDegeneratesToOrphan(@TempDir dir: File) {
        project(dir, mapOf(
            "traits.dawn" to "pub trait MyOrd[T] { fn cmp2(a: T, b: T) -> Int }\n",
            "point.dawn" to """
                use traits.{MyOrd}
                pub type Point = { x: Int, y: Int }
                impl MyOrd[Point] { fn cmp2(a: Point, b: Point) -> Int = a.x - b.x }
            """.trimIndent(),
            "other.dawn" to """
                use traits.{MyOrd}
                use point.{Point}
                pub type Wrap = { p: Point }
                impl MyOrd[Point] { fn cmp2(a: Point, b: Point) -> Int = b.x - a.x }
            """.trimIndent(),
            "main.dawn" to """
                use point
                use other
                pub fn main() -> Unit !io = println("ok")
            """.trimIndent(),
        ))
        assertProjError(dir, "orphan impl")
    }

    @Test
    fun privateTraitIsNotImportable(@TempDir dir: File) {
        project(dir, mapOf(
            "traits.dawn" to "trait Hidden[T] { fn h(x: T) -> Int }\n",
            "main.dawn" to """
                use traits.{Hidden}
                pub fn main() -> Unit !io = println("ok")
            """.trimIndent(),
        ))
        assertProjError(dir, "`Hidden` is private to module `traits`")
    }

    @Test
    fun pubTraitMethodImportsLikeAFn(@TempDir dir: File) {
        project(dir, mapOf(
            "traits.dawn" to "pub trait MyOrd[T] { fn cmp2(a: T, b: T) -> Int }\n",
            "main.dawn" to """
                use traits.{MyOrd, cmp2}
                fn f[T: MyOrd](a: T, b: T) -> Int = cmp2(a, b)
                pub fn main() -> Unit !io = println("ok")
            """.trimIndent(),
        ))
        assertProjClean(dir)
    }
}
