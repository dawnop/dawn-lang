package dawn

import dawn.check.StdLib
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
import kotlin.test.assertTrue

/**
 * The bundled standard library (docs/builtins-to-stdlib.md "杠杆 2"): std sources
 * ship in the compiler jar, are checked once, are implicitly visible with no
 * `use`, and their classes link in both single-file and multi-module builds.
 */
class StdLibTest {

    private fun loaderOf(classes: Map<String, ByteArray>) =
        object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }

    private fun capture(cls: Class<*>, vararg args: Any?): String {
        val buf = ByteArrayOutputStream()
        val old = System.out
        System.setOut(PrintStream(buf, true, "UTF-8"))
        try {
            cls.getDeclaredMethod("main").invoke(null)
        } finally {
            System.setOut(old)
        }
        return buf.toString("UTF-8")
    }

    private fun run(source: String): String {
        val analysis = analyze(source)
        check(!analysis.hasErrors) {
            "unexpected compile errors:\n" + analysis.diagnostics.joinToString("\n") { it.message }
        }
        val classes = CodeGen(analysis.module, "testmod").generate()
        return capture(Class.forName("testmod", false, loaderOf(classes)))
    }

    private fun errorsOf(source: String): List<String> {
        val analysis = analyze(source)
        assertTrue(analysis.hasErrors, "expected compile errors, got none")
        return analysis.diagnostics.map { it.message }
    }

    @Test
    fun `the bundled std checks cleanly and exports its functions`() {
        // a broken bundled std throws on first touch; reaching here means it checked
        assertTrue(StdLib.modules.isNotEmpty(), "expected at least one bundled std module")
        assertEquals("std/str", StdLib.modules.first().className)
        // the implicit surface is the prelude and nothing more (docs/stdlib-naming.md)
        assertTrue(StdLib.fns.containsKey("map"), "prelude should stay implicit; got ${StdLib.fns.keys}")
        assertFalse(StdLib.fns.containsKey("is_empty"), "non-prelude std must be module-qualified only")
        assertTrue(StdLib.exportsByPath.getValue("std/str").fns.containsKey("is_empty"))
    }

    @Test
    fun `std functions are visible without a use and link in a single-file build`() {
        val out = run(
            """
            use std/str

            pub fn main() -> Unit !io = {
              println("${'$'}{str.is_empty("")}")
              println("${'$'}{str.is_empty("x")}")
              println(str.repeat("ab", 3))
            }
            """.trimIndent(),
        )
        assertEquals("true\nfalse\nababab\n", out)
    }

    @Test
    fun `a pure function may call std and stay pure`() {
        val analysis = analyze(
            """
            use std/str

            pub fn shout(s: String) -> String = str.repeat(s, 2)
            """.trimIndent(),
        )
        assertFalse(analysis.hasErrors,
            "expected no errors:\n" + analysis.diagnostics.joinToString("\n") { it.message })
    }

    @Test
    fun `std functions link in a multi-module build`(@TempDir dir: File) {
        File(dir, "src").mkdirs()
        File(dir, "src/main.dawn").writeText(
            """
            use util/text
            pub fn main() -> Unit !io = println(text.banner("hi"))
            """.trimIndent(),
        )
        File(dir, "src/util").mkdirs()
        File(dir, "src/util/text.dawn").writeText(
            """
            use std/str

            pub fn banner(s: String) -> String = str.repeat("-", 3) ++ s ++ str.repeat("-", 3)
            """.trimIndent(),
        )
        val program = analyzeProject(dir)
        assertFalse(program.hasErrors,
            "program did not check:\n" + program.diagnostics.joinToString("\n") { it.diag.message })
        val units = program.modules.map { CodeGen.Companion.ModuleUnit(it.module, it.className) }
        val classes = CodeGen.generateProgram(units)
        val entry = program.modules.first { m -> m.module.fns.any { it.name == "main" } }
        val cls = Class.forName(entry.className.replace('/', '.'), false, loaderOf(classes))
        assertEquals("---hi---\n", capture(cls))
    }

    @Test
    fun `std forwards to a source-compiled runtime class through unsafe_pure`() {
        // pad_start/reverse_str are implemented in dawn.rt.StdStrings (real Java,
        // reflectable by the checker) and vouched pure on the Dawn side.
        val out = run(
            """
            use std/str

            pub fn main() -> Unit !io = {
              println(str.pad_start("7", 4, "0"))
              println(str.reverse("abc"))
              println(str.pad_start("héllo", 7, "·"))
            }
            """.trimIndent(),
        )
        assertEquals("0007\ncba\n··héllo\n", out)
    }

    @Test
    fun `a cursor walk visits every code point, astral ones included`() {
        // The property that matters: one cursor step is one Dawn character, so a
        // surrogate pair is never split into two. `str_len` counts code points,
        // so the two must agree — on ASCII and on astral text alike.
        val out = run(
            """
            use std/str
            use std/cursor

            fn walk(s: String, c: Cursor, acc: Int) -> Int =
              if cursor.done(s, c) { acc } else { walk(s, cursor.next(s, c), acc + 1) }

            pub fn main() -> Unit !io = {
              println("${'$'}{walk("abc", cursor.start("abc"), 0)} ${'$'}{str.len("abc")}")
              println("${'$'}{walk("héllo", cursor.start("héllo"), 0)} ${'$'}{str.len("héllo")}")
              println("${'$'}{walk("a🎈b", cursor.start("a🎈b"), 0)} ${'$'}{str.len("a🎈b")}")
              println("${'$'}{walk("", cursor.start(""), 0)} ${'$'}{str.len("")}")
            }
            """.trimIndent(),
        )
        assertEquals("3 3\n5 5\n3 3\n0 0\n", out)
    }

    @Test
    fun `cursor_char reads whole code points and reports the end with -1`() {
        val out = run(
            """
            use std/cursor

            pub fn main() -> Unit !io = {
              let s = "a🎈"
              let c0 = cursor.start(s)
              let c1 = cursor.next(s, c0)
              let c2 = cursor.next(s, c1)
              println("${'$'}{cursor.char(s, c0)}")
              println("${'$'}{cursor.char(s, c1)}")
              println("${'$'}{cursor.char(s, c2)}")
              println("${'$'}{cursor.done(s, c2)}")
            }
            """.trimIndent(),
        )
        // 127880 is U+1F388 itself, not either half of its surrogate pair
        assertEquals("97\n127880\n-1\ntrue\n", out)
    }

    @Test
    fun `cursor_prev undoes cursor_next over variable-width characters`() {
        // The reason this is a function and not `c - 1`: over "a🎈b" the steps
        // are 1, 2, 1 units wide, so arithmetic would land inside the pair.
        val out = run(
            """
            use std/cursor

            fn back(s: String, c: Cursor, n: Int) -> Cursor =
              if n == 0 { c } else { back(s, cursor.prev(s, c), n - 1) }

            pub fn main() -> Unit !io = {
              let s = "a🎈b"
              let e = cursor.end(s)
              println(cursor.slice(s, back(s, e, 1), e))
              println(cursor.slice(s, back(s, e, 2), e))
              println(cursor.slice(s, back(s, e, 3), e))
              println("${'$'}{back(s, e, 9) == cursor.start(s)}")
            }
            """.trimIndent(),
        )
        assertEquals("b\n🎈b\na🎈b\ntrue\n", out)
    }

    @Test
    fun `cursor_slice cuts between cursors and index_of_from resumes from one`() {
        val out = run(
            """
            use std/cursor

            fn all_from(s: String, sub: String, c: Cursor, acc: Int) -> Int =
              match cursor.find(s, sub, c) {
                None -> acc
                Some(i) -> all_from(s, sub, cursor.next(s, i), acc + 1)
              }

            pub fn main() -> Unit !io = {
              let s = "a🎈bc🎈d"
              let c0 = cursor.start(s)
              let c1 = cursor.next(s, c0)
              println(cursor.slice(s, c0, c1))
              println(cursor.slice(s, c1, cursor.end(s)))
              println("${'$'}{all_from(s, "🎈", cursor.start(s), 0)}")
            }
            """.trimIndent(),
        )
        assertEquals("a\n🎈bc🎈d\n2\n", out)
    }

    @Test
    fun `the forwarded runtime class is vendored into every built program`() {
        // Regression guard for the bug this spike hit: the class lives in the
        // compiler jar, so `dawn run` worked while `java -jar` died with
        // NoClassDefFoundError. A built program must carry it itself.
        val analysis = analyze("use std/str\npub fn main() -> Unit !io = println(str.reverse(\"ab\"))")
        assertFalse(analysis.hasErrors)
        val classes = CodeGen(analysis.module, "testmod").generate()
        for (name in CodeGen.Companion.VENDORED_RT_CLASSES) {
            assertTrue(classes.containsKey(name), "built program is missing $name; got ${classes.keys.sorted()}")
        }
    }

    @Test
    fun `a built program carries the map runtime and runs without the compiler`(@TempDir dir: File) {
        // The regression this guards: dawn/rt/DawnMap (and its nested Node
        // family) exist only in the compiler artifact, so an unvendored class is
        // invisible to every in-JVM test and fails only in a standalone run.
        val analysis = analyze(
            """
            use std/map

            pub fn main() -> Unit !io = println("${'$'}{map.size(map.insert(map.empty(), 1, 2))}")
            """.trimIndent(),
        )
        assertFalse(analysis.hasErrors)
        val classes = CodeGen(analysis.module, "prog").generate()
        assertTrue(classes.keys.any { it.startsWith("dawn/rt/DawnMap\$") },
            "nested DawnMap classes must be vendored; got ${classes.keys.filter { it.startsWith("dawn/rt/") }}")
        for ((name, bytes) in classes) {
            val f = File(dir, "$name.class")
            f.parentFile.mkdirs()
            f.writeBytes(bytes)
        }
        val java = File(File(System.getProperty("java.home")), "bin/java")
        val p = ProcessBuilder(java.absolutePath, "-cp", dir.absolutePath, "prog")
            .redirectErrorStream(true).start()
        val out = p.inputStream.readBytes().decodeToString()
        assertEquals(0, p.waitFor(), "standalone run failed:\n$out")
        assertEquals("1\n", out)
    }

    @Test
    fun `std is callable from a const, through pure Dawn and through a forward alike`() {
        // std is implicitly visible, so it must also be visible to the compile-time
        // interpreter — otherwise migrating a builtin would silently cost callers
        // their const folding (pure-ffi-design.md 阶段3).
        val out = run(
            """
            use std/str

            const A: Bool = str.is_empty("")
            const B: String = str.substring("hello", 1, 3)
            const C: String = str.pad_start("7", 4, "0")
            pub fn main() -> Unit !io = println("${'$'}{A} ${'$'}{B} ${'$'}{C}")
            """.trimIndent(),
        )
        assertEquals("true el 0007\n", out)
    }

    @Test
    fun `a std panic during folding is reported at the call site, not inside std`() {
        val analysis = analyze("use std/str\nconst X: String = str.substring(\"abc\", 0, 9)")
        assertTrue(analysis.hasErrors, "expected the out-of-range panic to surface at compile time")
        val d = analysis.diagnostics.first { it.message.contains("index out of range") }
        // same text as the runtime panic, and pointing at the user's call rather
        // than into the std source, whose spans would render against the wrong file
        assertTrue(d.message.contains("substring: index out of range"), d.message)
        assertTrue(d.hint.orEmpty().contains("standard library function `substring`"),
            "the diagnostic should name the std function it came from; hint was: ${d.hint}")
    }

    @Test
    fun `the migrated string group keeps its code-point semantics and its folding`() {
        // The migration must be behaviour-preserving on both axes that are easy to
        // lose: code points (not UTF-16 units) and compile-time folding.
        val out = run(
            """
            use std/str

            const T: String = str.trim("  hi  ")
            const C: Bool = str.contains("hello", "ell")
            const N: Int = str.len("héllo🎈")
            pub fn main() -> Unit !io = {
              println("[${'$'}{T}] ${'$'}{C} ${'$'}{N}")
              println(str.to_upper("héllo"))
              match str.index_of("héllo🎈x", "x") {
                Some(i) -> println("${'$'}{i}")
                None -> println("none")
              }
            }
            """.trimIndent(),
        )
        // index 6, not 7: the astral code point counts once
        assertEquals("[hi] true 6\nHÉLLO\n6\n", out)
    }

    @Test
    fun `a local definition shadows a std function`() {
        // fold is in the prelude's std half; a local decl still wins (spec §10.6)
        val out = run(
            """
            fn fold(s: String) -> Bool = false

            pub fn main() -> Unit !io = println("${'$'}{fold("")}")
            """.trimIndent(),
        )
        assertEquals("false\n", out)
    }

    @Test
    fun `a local definition shadows a builtin`() {
        val out = run(
            """
            fn len(s: String) -> Int = 42

            pub fn main() -> Unit !io = println("${'$'}{len("abc")}")
            """.trimIndent(),
        )
        assertEquals("42\n", out)
    }
}
