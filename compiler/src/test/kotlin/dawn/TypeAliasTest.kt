package dawn

import dawn.check.analyze
import dawn.check.analyzeProject
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Type aliases: `alias Name[T] = TypeRef`, transparent and expanded at
 * resolution. `type` declares nominal types only — an alias-shaped RHS under
 * `type` is an error pointing at the `alias` keyword (spec §2.6).
 */
class TypeAliasTest {

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

    // ---- shapes ----

    @Test
    fun fnTypeAliasInSignaturesAndFields() {
        val out = run("""
            alias Handler = fn(Int) -> Int
            type Ops = { inc: Handler }

            fn apply(h: Handler, n: Int) -> Int = h(n)

            pub fn main() -> Unit !io = {
              let ops = Ops { inc: fn(x) => x + 1 }
              println(to_string(apply(ops.inc, 41)))
            }
        """.trimIndent())
        assertEquals("42\n", out)
    }

    @Test
    fun tupleAndGenericApplicationAliases() {
        val out = run("""
            alias Pair = (Int, String)
            alias Names = List[String]

            fn first(p: Pair) -> Int = {
              let (a, _) = p
              a
            }

            pub fn main() -> Unit !io = {
              println(to_string(first((7, "seven"))))
              let names: Names = ["a", "b"]
              println(join(names, ","))
            }
        """.trimIndent())
        assertEquals("7\na,b\n", out)
    }

    @Test
    fun parameterizedAliasSubstitutes() {
        val out = run("""
            alias Lookup[T] = fn(String) -> Option[T]

            fn find_in(m: Map[String, Int]) -> Lookup[Int] = fn(k) => map_get(m, k)

            pub fn main() -> Unit !io = {
              let lk = find_in(map_from([("k", 9)]))
              match lk("k") {
                Some(v) -> println(to_string(v))
                None -> println("none")
              }
            }
        """.trimIndent())
        assertEquals("9\n", out)
    }

    @Test
    fun aliasOfAliasExpands() {
        val out = run("""
            alias Step = fn(Int) -> Int
            alias Pipeline = List[Step]

            fn run_all(ps: Pipeline, n: Int) -> Int = fold(ps, n, fn(acc, f) => f(acc))

            pub fn main() -> Unit !io =
              println(to_string(run_all([fn(x) => x + 1, fn(x) => x * 2], 3)))
        """.trimIndent())
        assertEquals("8\n", out)
    }

    @Test
    fun bareUppercaseRhsIsStillAnAdt() {
        val out = run("""
            type Color = Red | Green

            pub fn main() -> Unit !io =
              match Green {
                Red -> println("r")
                Green -> println("g")
              }
        """.trimIndent())
        assertEquals("g\n", out)
    }

    @Test
    fun bareBuiltinScalarIsAnAlias() {
        val out = run("""
            alias Meters = Float

            fn walk(d: Meters) -> Meters = d * 2.0

            pub fn main() -> Unit !io = println(to_string(walk(1.5)))
        """.trimIndent())
        assertEquals("3.0\n", out)
    }

    @Test
    fun aliasOfAUserAdtIsTransparent() {
        // impossible before the alias keyword: a bare uppercase RHS under `type`
        // always declared a constructor, so user types could not be aliased
        val out = run("""
            type Color = Red | Green derive Show
            alias Paint = Color

            fn flip(p: Paint) -> Paint = match p { Red -> Green, Green -> Red }

            pub fn main() -> Unit !io = println(to_string(flip(Red)))
        """.trimIndent())
        assertEquals("Green\n", out)
    }

    // ---- diagnostics ----

    @Test
    fun aliasShapedRhsUnderTypeIsAnError() {
        val diags = errorsOf("""
            type Meters = Float

            pub fn main() -> Unit !io = println("x")
        """.trimIndent())
        assertHasError(diags, "this is an alias")
    }

    @Test
    fun aliasCycleIsAnError() {
        val diags = errorsOf("""
            alias A = List[B]
            alias B = List[A]

            pub fn main() -> Unit !io = println("x")
        """.trimIndent())
        assertHasError(diags, "refers to itself")
    }

    @Test
    fun effectVariablesAreRejected() {
        val diags = errorsOf("""
            alias H = fn(Int) -> Int !e

            pub fn main() -> Unit !io = println("x")
        """.trimIndent())
        assertHasError(diags, "cannot carry effect variables")
    }

    @Test
    fun aliasArityIsChecked() {
        val diags = errorsOf("""
            alias Lookup[T] = fn(String) -> Option[T]

            fn f(l: Lookup) -> Unit = ()

            pub fn main() -> Unit !io = println("x")
        """.trimIndent())
        assertHasError(diags, "`Lookup` takes 1 type parameter(s), got 0")
    }

    @Test
    fun duplicateAliasAndAdtNamesCollide() {
        val diags = errorsOf("""
            alias H = fn(Int) -> Int
            type H = { n: Int }

            pub fn main() -> Unit !io = println("x")
        """.trimIndent())
        assertHasError(diags, "defined twice")
    }

    // ---- cross-module ----

    @Test
    fun aliasImportsAcrossModules() {
        val dir = Files.createTempDirectory("dawn-alias").toFile()
        try {
            val src = java.io.File(dir, "src/lib").apply { mkdirs() }
            java.io.File(src, "h.dawn").writeText("""
                pub alias Handler = fn(Int) -> Int
                pub fn twice(h: Handler, n: Int) -> Int = h(h(n))
            """.trimIndent())
            java.io.File(dir, "src/main.dawn").writeText("""
                use lib/h.{Handler, twice}

                fn make() -> Handler = fn(x) => x + 10

                pub fn main() -> Unit !io = println(to_string(twice(make(), 1)))
            """.trimIndent())
            val program = analyzeProject(dir)
            assertFalse(program.hasErrors,
                program.diagnostics.joinToString("\n") { it.diag.message })
        } finally {
            dir.deleteRecursively()
        }
    }
}
