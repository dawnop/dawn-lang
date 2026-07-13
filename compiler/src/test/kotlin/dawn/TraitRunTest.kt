package dawn

import dawn.check.analyze
import dawn.check.analyzeProject
import dawn.codegen.CodeGen
import org.junit.jupiter.api.io.TempDir
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

/**
 * Knife 4 of traits: dictionary passing end to end — source → bytecode →
 * in-process execution. Concrete sites devirtualize to impl statics, rigid
 * type parameters forward the caller's dictionary, lambdas capture it.
 */
class TraitRunTest {

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

    @Test
    fun operatorsUseTheUserOrdImpl() {
        val out = run("""
            type Point = { x: Int, y: Int }

            impl Ord[Point] {
              fn cmp(a: Point, b: Point) -> Int =
                if a.x != b.x { a.x - b.x } else { a.y - b.y }
            }

            pub fn main() -> Unit !io = {
              let p = Point { x: 1, y: 5 }
              let q = Point { x: 2, y: 0 }
              println("${'$'}{p < q} ${'$'}{p >= q} ${'$'}{p < p} ${'$'}{p <= p}")
            }
        """.trimIndent())
        assertEquals("true false false true\n", out)
    }

    @Test
    fun boundedGenericWorksAcrossSubjects() {
        val out = run("""
            type Point = { x: Int, y: Int }

            impl Ord[Point] {
              fn cmp(a: Point, b: Point) -> Int = a.x - b.x
            }

            fn max2[T: Ord](a: T, b: T) -> T = if a < b { b } else { a }

            pub fn main() -> Unit !io = {
              let p = max2(Point { x: 1, y: 0 }, Point { x: 9, y: 0 })
              println("${'$'}{max2(3, 7)} ${'$'}{max2(2.5, 1.5)} ${'$'}{max2("pear", "apple")} ${'$'}{p.x}")
            }
        """.trimIndent())
        assertEquals("7 2.5 pear 9\n", out)
    }

    @Test
    fun preludeCmpDevirtualizesOnScalars() {
        val out = run("""
            pub fn main() -> Unit !io =
              println("${'$'}{cmp(1, 2) < 0} ${'$'}{cmp("b", "a") > 0} ${'$'}{cmp(1.5, 1.5) == 0}")
        """.trimIndent())
        assertEquals("true true true\n", out)
    }

    @Test
    fun traitMethodCallsDevirtualizeAndUfcsWorks() {
        val out = run("""
            trait Area[T] {
              fn area(s: T) -> Int
            }

            type Rect = { w: Int, h: Int }

            impl Area[Rect] {
              fn area(s: Rect) -> Int = s.w * s.h
            }

            pub fn main() -> Unit !io = {
              let r = Rect { w: 3, h: 4 }
              println("${'$'}{area(r)} ${'$'}{r.area()}")
            }
        """.trimIndent())
        assertEquals("12 12\n", out)
    }

    @Test
    fun defaultMethodRunsThroughBothPaths() {
        val out = run("""
            trait Greet[T] {
              fn name_of(x: T) -> String
              fn greet(x: T) -> String = "hi " ++ name_of(x)
            }

            type Cat = { called: String }
            type Dog = { called: String }

            impl Greet[Cat] {
              fn name_of(x: Cat) -> String = x.called
            }

            impl Greet[Dog] {
              fn name_of(x: Dog) -> String = x.called
              fn greet(x: Dog) -> String = "woof " ++ x.called
            }

            fn greet_all[T: Greet](x: T) -> String = greet(x)

            pub fn main() -> Unit !io = {
              let c = Cat { called: "mia" }
              let d = Dog { called: "rex" }
              println("${'$'}{greet(c)} | ${'$'}{greet(d)} | ${'$'}{greet_all(c)} | ${'$'}{greet_all(d)}")
            }
        """.trimIndent())
        assertEquals("hi mia | woof rex | hi mia | woof rex\n", out)
    }

    @Test
    fun lambdaCapturesTheDictionary() {
        val out = run("""
            fn largest[T: Ord](first: T, rest: List[T]) -> T =
              fold(rest, first, fn(acc, x) => if acc < x { x } else { acc })

            pub fn main() -> Unit !io =
              println("${'$'}{largest(3, [9, 4, 7])} ${'$'}{largest("m", ["z", "a"])}")
        """.trimIndent())
        assertEquals("9 z\n", out)
    }

    @Test
    fun dictionariesForwardThroughCallChains() {
        val out = run("""
            trait Score[T] {
              fn score(x: T) -> Int
            }

            type Hand = { v: Int }

            impl Score[Hand] {
              fn score(x: Hand) -> Int = x.v * 10
            }

            fn doubled[T: Score](x: T) -> Int = score(x) * 2
            fn tripled[T: Score](x: T) -> Int = doubled(x) + score(x)

            pub fn main() -> Unit !io = println("${'$'}{tripled(Hand { v: 3 })}")
        """.trimIndent())
        assertEquals("90\n", out)
    }

    @Test
    fun multipleBoundsPassMultipleDictionaries() {
        val out = run("""
            trait A[T] { fn fa(x: T) -> Int }
            trait B[T] { fn fb(x: T) -> Int }

            type P = { v: Int }

            impl A[P] { fn fa(x: P) -> Int = x.v + 1 }
            impl B[P] { fn fb(x: P) -> Int = x.v * 2 }

            fn both[T: A + B](x: T) -> Int = fa(x) + fb(x)

            pub fn main() -> Unit !io = println("${'$'}{both(P { v: 10 })}")
        """.trimIndent())
        assertEquals("31\n", out)
    }

    @Test
    fun constrainedTailRecursionKeepsItsDictionary() {
        val out = run("""
            fn count_below[T: Ord](xs: List[T], cap: T, i: Int, acc: Int) -> Int =
              match get(xs, i) {
                None -> acc
                Some(x) -> count_below(xs, cap, i + 1, if x < cap { acc + 1 } else { acc })
              }

            pub fn main() -> Unit !io =
              println("${'$'}{count_below([1, 8, 3, 9, 2], 5, 0, 0)}")
        """.trimIndent())
        assertEquals("3\n", out)
    }

    @Test
    fun insertionSortUsesForwardedOrd() {
        val out = run("""
            fn insert[T: Ord](xs: List[T], x: T) -> List[T] =
              match xs {
                [] -> [x]
                [h, ..t] -> if x < h { [x] ++ xs } else { [h] ++ insert(t, x) }
              }

            fn sorted[T: Ord](xs: List[T]) -> List[T] =
              match xs {
                [] -> xs
                [h, ..t] -> insert(sorted(t), h)
              }

            pub fn main() -> Unit !io = {
              let xs = sorted([5, 2, 9, 1])
              println("${'$'}xs")
            }
        """.trimIndent())
        assertEquals("[1, 2, 5, 9]\n", out)
    }

    // ---- across modules: interface, impl singleton and default static live apart ----

    @Test
    fun dictionariesCrossModuleBoundaries(@TempDir dir: File) {
        for ((rel, text) in mapOf(
            "fmt.dawn" to """
                pub trait Fmt[T] {
                  fn fmt(x: T) -> String
                  fn banner(x: T) -> String = ">> " ++ fmt(x)
                }

                pub fn describe[T: Fmt](x: T) -> String = banner(x)
            """.trimIndent(),
            "point.dawn" to """
                use fmt.{Fmt}

                pub type Point = { x: Int, y: Int }

                impl Fmt[Point] {
                  fn fmt(p: Point) -> String = "(${'$'}{p.x}, ${'$'}{p.y})"
                }

                impl Ord[Point] {
                  fn cmp(a: Point, b: Point) -> Int = a.x - b.x
                }
            """.trimIndent(),
            "main.dawn" to """
                use fmt.{describe}
                use point.{Point}

                pub fn main() -> Unit !io = {
                  let p = Point { x: 1, y: 2 }
                  let q = Point { x: 5, y: 0 }
                  println("${'$'}{describe(p)} ${'$'}{p < q}")
                }
            """.trimIndent(),
        )) {
            val f = File(dir, "src/$rel")
            f.parentFile.mkdirs()
            f.writeText(text)
        }
        val program = analyzeProject(dir)
        assertFalse(program.hasErrors, "program did not check:\n" +
            program.diagnostics.joinToString("\n") { it.diag.message })
        val units = program.modules.map { CodeGen.Companion.ModuleUnit(it.module, it.className) }
        val classes = CodeGen.generateProgram(units)
        val entry = program.modules.first { m -> m.module.fns.any { it.name == "main" } }
        val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }
        val cls = Class.forName(entry.className.replace('/', '.'), false, loader)
        val buf = ByteArrayOutputStream()
        val old = System.out
        System.setOut(PrintStream(buf, true, "UTF-8"))
        try {
            cls.getDeclaredMethod("main").invoke(null)
        } finally {
            System.setOut(old)
        }
        assertEquals(">> (1, 2) true\n", buf.toString("UTF-8"))
    }
}
