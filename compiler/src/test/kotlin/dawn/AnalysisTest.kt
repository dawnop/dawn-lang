package dawn

import dawn.check.analyze
import dawn.diag.SourceFile
import dawn.lsp.findTarget
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Error recovery, cascade suppression, and the AST query used by the language server. */
class AnalysisTest {

    @Test
    fun multipleErrorsReportedAtOnce() {
        val a = analyze("""
            fn f() -> Unit = println("one")
            fn g() -> Unit = println("two")
            pub fn main() -> Unit !io = { f() }
        """.trimIndent())
        val ioErrors = a.diagnostics.filter { it.message.contains("not declared !io") }
        assertEquals(2, ioErrors.size, a.diagnostics.joinToString("\n") { it.message })
    }

    @Test
    fun parserRecoversAcrossDeclarations() {
        // first fn is syntactically broken; the second must still be fully checked
        val a = analyze("""
            fn broken( -> Int = 1

            fn also_bad() -> Unit = println("io leak")
        """.trimIndent())
        assertTrue(a.diagnostics.any { it.message.contains("expected") },
            "missing parse error: " + a.diagnostics.joinToString { it.message })
        assertTrue(a.diagnostics.any { it.message.contains("not declared !io") },
            "second decl was not checked: " + a.diagnostics.joinToString { it.message })
    }

    @Test
    fun statementRecoveryKeepsRestOfBlock() {
        val a = analyze("""
            pub fn main() -> Unit !io = {
              let x = )
              println("still checked {undefined_one}")
            }
        """.trimIndent())
        assertTrue(a.diagnostics.any { it.message.contains("expected") })
        assertTrue(a.diagnostics.any { it.message.contains("undefined_one") },
            "statements after the broken one were skipped: " + a.diagnostics.joinToString { it.message })
    }

    @Test
    fun undefinedVariableDoesNotCascade() {
        val a = analyze("""
            fn f() -> Int = {
              let x = missing()
              x + 1
            }
            pub fn main() -> Unit !io = println("{f()}")
        """.trimIndent())
        assertEquals(1, a.diagnostics.size, a.diagnostics.joinToString("\n") { it.message })
        assertTrue(a.diagnostics[0].message.contains("undefined function"))
    }

    @Test
    fun lexerRecoversFromBadString() {
        val a = analyze("""
            pub fn main() -> Unit !io = {
              let s = "oops
              println("fine")
            }
        """.trimIndent())
        assertTrue(a.diagnostics.any { it.message.contains("unterminated string") })
        // the println line after the broken string must still parse (no "expected expression" spam on it)
        assertTrue(a.module.decls.isNotEmpty())
    }

    // ---- LSP-facing queries ----

    private val sample = """
        fn double(n: Int) -> Int = n * 2

        pub fn main() -> Unit !io = {
          let count = 21
          println("{double(count)}")
        }
    """.trimIndent()

    private fun offsetOf(text: String, needle: String, occurrence: Int = 1): Int {
        var idx = -1
        repeat(occurrence) { idx = text.indexOf(needle, idx + 1) }
        check(idx >= 0)
        return idx
    }

    @Test
    fun hoverOnVariableShowsBindingAndType() {
        val a = analyze(sample)
        val t = findTarget(a, offsetOf(sample, "count", 2))
        assertNotNull(t)
        assertEquals("let count: Int", t.hover)
        // definition points at the let site
        assertEquals(offsetOf(sample, "let count"), t.defSpan!!.start)
    }

    @Test
    fun hoverOnCallShowsSignatureAndDefinition() {
        val a = analyze(sample)
        val t = findTarget(a, offsetOf(sample, "double", 2))
        assertNotNull(t)
        assertEquals("fn double(n: Int) -> Int", t.hover)
        assertEquals(offsetOf(sample, "double"), t.defSpan!!.start)
    }

    @Test
    fun hoverOnParamShowsType() {
        val a = analyze(sample)
        val t = findTarget(a, offsetOf(sample, "n: Int"))
        assertNotNull(t)
        assertEquals("n: Int", t.hover)
    }

    @Test
    fun hoverOutsideAnythingIsNull() {
        val a = analyze(sample)
        // the blank line between the two declarations belongs to no AST node
        assertNull(findTarget(a, offsetOf(sample, "\n\n") + 1))
    }

    @Test
    fun lspPositionRoundTrip() {
        val text = "fn a() -> Int = 1\nfn b() -> Int = 2\n"
        val f = SourceFile("t", text)
        val off = text.indexOf("b()")
        val (line, col) = f.lspPosition(off)
        assertEquals(1, line)
        assertEquals(3, col)
        assertEquals(off, f.lspOffset(line, col))
    }
}
