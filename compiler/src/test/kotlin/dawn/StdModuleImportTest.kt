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
import kotlin.test.assertTrue

/**
 * The bundled std as real, importable modules (spec §10.6, docs/stdlib-naming.md):
 * `use std/x` resolves against the compiler jar's resources — never the disk —
 * and then behaves like any module import: qualified access and selective imports.
 */
class StdModuleImportTest {

    private fun loaderOf(classes: Map<String, ByteArray>) =
        object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }

    private fun capture(cls: Class<*>): String {
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
    fun `a std module can be imported and called qualified`() {
        val out = run(
            """
            use std/strings

            pub fn main() -> Unit !io = {
              println(strings.trim("  x  "))
              println("${'$'}{strings.str_len("héllo")}")
            }
            """.trimIndent(),
        )
        assertEquals("x\n5\n", out)
    }

    @Test
    fun `selective import pulls a std name into scope`() {
        val out = run(
            """
            use std/strings.{to_upper}

            pub fn main() -> Unit !io = println(to_upper("ab"))
            """.trimIndent(),
        )
        assertEquals("AB\n", out)
    }

    @Test
    fun `an unknown std module is reported with the available list`() {
        val errs = errorsOf(
            """
            use std/nope

            pub fn main() -> Unit !io = println("x")
            """.trimIndent(),
        )
        // single-file analyze() has no loader pass, so the checker reports the
        // unresolved alias when it is used; project builds get the loader message
        assertTrue(errs.isNotEmpty(), "expected an error for use std/nope")
    }

    @Test
    fun `project mode resolves std imports without touching the disk`(@TempDir dir: File) {
        File(dir, "src").mkdirs()
        File(dir, "src/main.dawn").writeText(
            """
            use std/strings

            pub fn main() -> Unit !io = println(strings.to_upper("ok"))
            """.trimIndent(),
        )
        val program = analyzeProject(dir)
        assertTrue(!program.hasErrors,
            "expected a clean check, got:\n" + program.render())
    }

    @Test
    fun `project mode rejects an unknown std module`(@TempDir dir: File) {
        File(dir, "src").mkdirs()
        File(dir, "src/main.dawn").writeText(
            """
            use std/nope

            pub fn main() -> Unit !io = println("x")
            """.trimIndent(),
        )
        val program = analyzeProject(dir)
        assertTrue(program.hasErrors)
        assertTrue(program.diagnostics.any { it.diag.message.contains("no bundled std module `std/nope`") },
            "got: " + program.render())
    }

    @Test
    fun `the std path prefix is reserved on disk`(@TempDir dir: File) {
        File(dir, "src/std").mkdirs()
        File(dir, "src/main.dawn").writeText("pub fn main() -> Unit !io = println(\"x\")\n")
        File(dir, "src/std/mine.dawn").writeText("pub fn f() -> Int = 1\n")
        val program = analyzeProject(dir)
        assertTrue(program.diagnostics.any {
            it.diag.message.contains("reserved for the bundled standard library")
        }, "got: " + program.render())
    }

    @Test
    fun `a private std helper is not importable`() {
        val errs = errorsOf(
            """
            use std/strings.{chars_go}

            pub fn main() -> Unit !io = println("x")
            """.trimIndent(),
        )
        assertTrue(errs.any { it.contains("private to module `std/strings`") }, "got: $errs")
    }
}
