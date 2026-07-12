package dawn

import dawn.check.analyzeDocument
import dawn.lsp.findTarget
import org.junit.jupiter.api.io.TempDir
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * Cross-file go-to-definition (LSP): a Target for an imported symbol must carry
 * the defining module's file in [dawn.lsp.Target.defPath] and a defSpan valid in
 * THAT file's text — the server turns this into a Location in the right document.
 */
class CrossFileNavTest {

    private fun project(dir: File, files: Map<String, String>): File {
        for ((rel, text) in files) {
            val f = File(dir, "src/$rel")
            f.parentFile.mkdirs()
            f.writeText(text)
        }
        return dir
    }

    /** findTarget in main.dawn at the character just inside [needle]'s [occurrence]-th match. */
    private fun targetAt(dir: File, main: String, needle: String, occurrence: Int = 0): dawn.lsp.Target? {
        val mainFile = File(dir, "src/main.dawn")
        val analysis = analyzeDocument(mainFile, main)
        assertTrue(analysis.diagnostics.none { it.severity == dawn.diag.Severity.ERROR },
            "expected clean analysis, got:\n" + analysis.diagnostics.joinToString("\n") { it.message })
        var off = -1
        repeat(occurrence + 1) { off = main.indexOf(needle, off + 1) }
        check(off >= 0) { "needle `$needle` (occurrence $occurrence) not found in main.dawn" }
        return findTarget(analysis, off + 1)
    }

    private fun assertDefIn(t: dawn.lsp.Target?, file: String, text: String, defName: String) {
        assertNotNull(t, "no target under the cursor")
        assertTrue(t.defPath?.endsWith(file) == true, "defPath should end with $file, got ${t.defPath}")
        val span = t.defSpan
        assertNotNull(span, "target has no defSpan")
        assertEquals(defName, text.substring(span.start, span.end),
            "defSpan should cover `$defName` in $file")
    }

    private val utilText = """
        pub fn double(x: Int) -> Int = x * 2

        pub type Shape =
          | Circle(r: Float)
          | Square(side: Float)

        pub const LIMIT: Int = 10
    """.trimIndent() + "\n"

    private fun utilProject(dir: File, main: String): File =
        project(dir, mapOf("main.dawn" to main, "util.dawn" to utilText))

    @Test
    fun `selectively imported function jumps into the defining file`(@TempDir dir: File) {
        val main = """
            use util.{double}
            pub fn main() -> Unit !io = println(to_string(double(21)))
        """.trimIndent()
        utilProject(dir, main)
        assertDefIn(targetAt(dir, main, "double(21)"), "util.dawn", utilText, "double")
    }

    @Test
    fun `module-qualified call hovers and jumps into the defining file`(@TempDir dir: File) {
        val main = """
            use util
            pub fn main() -> Unit !io = println(to_string(util.double(21)))
        """.trimIndent()
        utilProject(dir, main)
        val t = targetAt(dir, main, "double(21)")
        assertDefIn(t, "util.dawn", utilText, "double")
        assertTrue(t!!.hover.contains("fn double(x: Int) -> Int"), "hover was: ${t.hover}")
    }

    @Test
    fun `imported constructor in an expression and a pattern jumps cross-file`(@TempDir dir: File) {
        val main = """
            use util.{Shape, Circle, Square}

            fn pick(s: Shape) -> Float =
              match s {
                Circle(r) -> r
                Square(side) -> side
              }

            pub fn main() -> Unit !io = println(to_string(pick(Circle(2.0))))
        """.trimIndent()
        utilProject(dir, main)
        assertDefIn(targetAt(dir, main, "Circle(2.0)"), "util.dawn", utilText, "Circle")
        assertDefIn(targetAt(dir, main, "Square(side) ->"), "util.dawn", utilText, "Square")
    }

    @Test
    fun `imported const reference jumps cross-file`(@TempDir dir: File) {
        val main = """
            use util.{LIMIT}
            pub fn main() -> Unit !io = println(to_string(LIMIT + 1))
        """.trimIndent()
        utilProject(dir, main)
        assertDefIn(targetAt(dir, main, "LIMIT + 1"), "util.dawn", utilText, "LIMIT")
    }

    @Test
    fun `use-line items navigate to their definitions`(@TempDir dir: File) {
        val main = """
            use util.{double, Shape}
            pub fn main() -> Unit !io = println(to_string(double(21)))
        """.trimIndent()
        utilProject(dir, main)
        assertDefIn(targetAt(dir, main, "double, Shape"), "util.dawn", utilText, "double")
        assertDefIn(targetAt(dir, main, "Shape}"), "util.dawn", utilText, "Shape")
    }

    @Test
    fun `use-line module path jumps to the top of the module file`(@TempDir dir: File) {
        val main = """
            use util
            pub fn main() -> Unit !io = println(to_string(util.double(21)))
        """.trimIndent()
        utilProject(dir, main)
        val t = targetAt(dir, main, "util") // the module path on the use line
        assertNotNull(t)
        assertTrue(t.defPath?.endsWith("util.dawn") == true, "defPath was ${t.defPath}")
        assertEquals(0, t.defSpan?.start)
    }

    @Test
    fun `local definitions resolve to the document itself`(@TempDir dir: File) {
        val main = """
            use util.{double}
            fn triple(x: Int) -> Int = x * 3
            pub fn main() -> Unit !io = println(to_string(triple(double(7))))
        """.trimIndent()
        utilProject(dir, main)
        val t = targetAt(dir, main, "triple(double")
        assertNotNull(t)
        assertTrue(t.defPath?.endsWith("main.dawn") == true, "defPath was ${t.defPath}")
        assertEquals("triple", main.substring(t.defSpan!!.start, t.defSpan!!.end))
    }
}
