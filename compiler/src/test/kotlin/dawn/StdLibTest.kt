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
        assertTrue(StdLib.fns.containsKey("is_empty"), "std should export is_empty; got ${StdLib.fns.keys}")
        assertEquals("std/strings", StdLib.modules.first().className)
    }

    @Test
    fun `std functions are visible without a use and link in a single-file build`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              println("${'$'}{is_empty("")}")
              println("${'$'}{is_empty("x")}")
              println(repeat("ab", 3))
            }
            """.trimIndent(),
        )
        assertEquals("true\nfalse\nababab\n", out)
    }

    @Test
    fun `a pure function may call std and stay pure`() {
        val analysis = analyze(
            """
            pub fn shout(s: String) -> String = repeat(s, 2)
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
            pub fn banner(s: String) -> String = repeat("-", 3) ++ s ++ repeat("-", 3)
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
            pub fn main() -> Unit !io = {
              println(pad_start("7", 4, "0"))
              println(reverse_str("abc"))
              println(pad_start("héllo", 7, "·"))
            }
            """.trimIndent(),
        )
        assertEquals("0007\ncba\n··héllo\n", out)
    }

    @Test
    fun `the forwarded runtime class is vendored into every built program`() {
        // Regression guard for the bug this spike hit: the class lives in the
        // compiler jar, so `dawn run` worked while `java -jar` died with
        // NoClassDefFoundError. A built program must carry it itself.
        val analysis = analyze("pub fn main() -> Unit !io = println(reverse_str(\"ab\"))")
        assertFalse(analysis.hasErrors)
        val classes = CodeGen(analysis.module, "testmod").generate()
        for (name in CodeGen.Companion.VENDORED_RT_CLASSES) {
            assertTrue(classes.containsKey(name), "built program is missing $name; got ${classes.keys.sorted()}")
        }
    }

    @Test
    fun `a std function cannot be redefined`() {
        val errs = errorsOf(
            """
            pub fn is_empty(s: String) -> Bool = false
            """.trimIndent(),
        )
        assertTrue(errs.any { it.contains("standard-library function and cannot be redefined") },
            "expected the std redefinition guard; got:\n" + errs.joinToString("\n"))
    }
}
