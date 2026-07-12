package dawn

import dawn.ast.FnTypeRef
import dawn.ast.Module
import dawn.ast.NamedTypeRef
import dawn.diag.Diagnostic
import dawn.diag.DiagnosticSink
import dawn.lex.Lexer
import dawn.parse.Parser
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Knife 1 of traits: the trait/impl/constraint surface syntax (parser + AST). */
class TraitParseTest {

    private fun parse(src: String): Pair<Module, List<Diagnostic>> {
        val sink = DiagnosticSink()
        val module = Parser(Lexer(src, 0, sink).lex(), sink, src).module()
        return module to sink.all
    }

    private fun parseOk(src: String): Module {
        val (m, diags) = parse(src)
        check(diags.isEmpty()) { "unexpected parse errors:\n" + diags.joinToString("\n") { it.message } }
        return m
    }

    private fun assertHasError(diags: List<Diagnostic>, substring: String) {
        assertTrue(
            diags.any { it.message.contains(substring) },
            "no diagnostic contains \"$substring\"; got:\n" + diags.joinToString("\n") { it.message },
        )
    }

    // ---- trait declarations ----

    @Test
    fun traitWithRequiredAndDefaultMethods() {
        val m = parseOk(
            """
            pub trait Ord[T] {
              fn cmp(a: T, b: T) -> Int
              fn max_of(a: T, b: T) -> T = if cmp(a, b) >= 0 { a } else { b }
            }
            """.trimIndent(),
        )
        val t = m.traits.single()
        assertTrue(t.pub)
        assertEquals("Ord", t.name)
        assertEquals("T", t.typeParam)
        assertEquals(listOf("cmp", "max_of"), t.methods.map { it.name })
        assertNull(t.methods[0].body, "cmp is a required method")
        assertNotNull(t.methods[1].body, "max_of has a default body")
        assertEquals(listOf("a", "b"), t.methods[0].params.map { it.name })
    }

    @Test
    fun traitMethodWithIoEffect() {
        val m = parseOk(
            """
            trait Logger[T] {
              fn log(x: T) -> Unit !io
            }
            """.trimIndent(),
        )
        assertEquals(listOf("io"), m.traits.single().methods.single().declaredEff)
    }

    @Test
    fun traitMethodWithFnTypedParam() {
        val m = parseOk(
            """
            trait Mapper[T] {
              fn apply(x: T, f: fn(T) -> T) -> T
            }
            """.trimIndent(),
        )
        val p = m.traits.single().methods.single().params[1]
        assertTrue(p.typeName is FnTypeRef)
    }

    @Test
    fun traitNeedsExactlyOneTypeParam() {
        val (_, diags) = parse("trait Conv[A, B] { fn conv(a: A) -> B }")
        assertHasError(diags, "exactly one type parameter")
    }

    @Test
    fun traitTypeParamCannotHaveBounds() {
        val (_, diags) = parse("trait Ord[T: Show] { fn cmp(a: T, b: T) -> Int }")
        assertHasError(diags, "cannot have bounds")
    }

    @Test
    fun traitNeedsAtLeastOneMethod() {
        val (_, diags) = parse("trait Empty[T] {\n}")
        assertHasError(diags, "at least one method")
    }

    @Test
    fun traitMethodParamsMustBeTyped() {
        val (_, diags) = parse("trait Ord[T] { fn cmp(a, b) -> Int }")
        assertHasError(diags, "trait method parameters must be typed")
    }

    @Test
    fun traitMethodNeedsReturnType() {
        val (_, diags) = parse("trait Ord[T] { fn cmp(a: T, b: T) = 0 }")
        assertHasError(diags, "trait methods must declare a return type")
    }

    @Test
    fun traitMethodCannotHaveOwnTypeParams() {
        val (_, diags) = parse("trait Ord[T] { fn cmp[U](a: T, b: U) -> Int }")
        assertHasError(diags, "trait methods cannot declare their own type parameters")
    }

    // ---- impl declarations ----

    @Test
    fun implParses() {
        val m = parseOk(
            """
            type Point = { x: Int, y: Int }

            impl Ord[Point] {
              fn cmp(a: Point, b: Point) -> Int =
                if a.x != b.x { a.x - b.x } else { a.y - b.y }
            }
            """.trimIndent(),
        )
        val i = m.impls.single()
        assertEquals("Ord", i.traitName)
        assertEquals("Point", (i.subject as NamedTypeRef).name)
        assertEquals("cmp", i.methods.single().name)
    }

    @Test
    fun implSubjectMayBeGeneric() {
        // parses today; the checker rejects non-concrete subjects (knife 2)
        val m = parseOk("impl Ord[List[Int]] {\n  fn cmp(a: List[Int], b: List[Int]) -> Int = 0\n}")
        val subject = m.impls.single().subject as NamedTypeRef
        assertEquals("List", subject.name)
        assertEquals(1, subject.args.size)
    }

    @Test
    fun implCannotBePub() {
        val (_, diags) = parse("pub impl Ord[Point] { fn cmp(a: Point, b: Point) -> Int = 0 }")
        assertHasError(diags, "an impl cannot be pub")
    }

    @Test
    fun implMethodsCannotBePub() {
        val (_, diags) = parse("impl Ord[Point] { pub fn cmp(a: Point, b: Point) -> Int = 0 }")
        assertHasError(diags, "impl methods cannot be pub")
    }

    @Test
    fun implMethodNeedsFullSignature() {
        val (_, diags) = parse("impl Ord[Point] { fn cmp(a: Point, b: Point) = 0 }")
        assertHasError(diags, "impl methods must declare their full signature")
    }

    @Test
    fun implMethodCannotHaveTypeParams() {
        val (_, diags) = parse("impl Ord[Point] { fn cmp[U](a: Point, b: Point) -> Int = 0 }")
        assertHasError(diags, "impl methods cannot declare their own type parameters")
    }

    @Test
    fun emptyImplParses() {
        // legal shape (a trait may be all defaults); knife 2 validates coverage
        val m = parseOk("impl Ord[Point] {\n}")
        assertTrue(m.impls.single().methods.isEmpty())
    }

    // ---- constraints on type parameters ----

    @Test
    fun singleBoundParses() {
        val m = parseOk("fn sort[T: Ord](xs: List[T]) -> List[T] = xs")
        val tp = m.fns.single().typeParams.single()
        assertEquals("T", tp.name)
        assertEquals(listOf("Ord"), tp.bounds.map { it.first })
    }

    @Test
    fun multipleBoundsParse() {
        val m = parseOk("fn largest[T: Ord + Show](xs: List[T]) -> String = \"\"")
        val tp = m.fns.single().typeParams.single()
        assertEquals(listOf("Ord", "Show"), tp.bounds.map { it.first })
    }

    @Test
    fun mixedBoundedAndUnboundedParams() {
        val m = parseOk("fn pick[T: Ord, U](xs: List[T], u: U) -> U = u")
        val tps = m.fns.single().typeParams
        assertEquals(listOf("Ord"), tps[0].bounds.map { it.first })
        assertTrue(tps[1].bounds.isEmpty())
    }

    @Test
    fun typeDeclCannotConstrainParams() {
        val (_, diags) = parse("type Sorted[T: Ord] = { items: List[T] }")
        assertHasError(diags, "type declarations cannot constrain their type parameters")
    }

    // ---- derive lists (comma form is the decided syntax) ----

    @Test
    fun deriveCommaListParses() {
        val m = parseOk("type Task = { name: String, priority: Int } derive Show, Ord")
        assertEquals(listOf("Show", "Ord"), m.types.single().derives.map { it.first })
    }
}
