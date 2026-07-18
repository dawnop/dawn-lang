package dawn

import dawn.diag.DiagnosticSink
import dawn.fmt.Formatter
import dawn.lex.Lexer
import dawn.lex.Token
import dawn.lex.TokenType
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.TestFactory
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * `dawn fmt` fidelity: formatting must preserve the token stream and all comments,
 * and be idempotent. Fixtures under golden/fmt/ lock the exact output, and every
 * example plus every golden-error source is run through the fidelity assertions.
 */
class FmtTest {

    private fun codeTokens(src: String): List<Pair<TokenType, String>> =
        Lexer(src, 0, DiagnosticSink()).lex()
            .filter { it.type != TokenType.NEWLINE && it.type != TokenType.EOF }
            .map { it.type to (if (it.type == TokenType.STRING) src.substring(it.span.start, it.span.end) else it.text) }

    private fun comments(src: String): List<String> {
        val sink = ArrayList<Token>()
        Lexer(src, 0, DiagnosticSink(), sink).lex()
        return sink.map { it.text }
    }

    /** The three invariants every format must satisfy. */
    private fun assertFidelity(src: String) {
        val out = Formatter.format(src)
        assertEquals(codeTokens(src), codeTokens(out), "token stream changed while formatting")
        assertEquals(comments(src), comments(out), "comments changed while formatting")
        assertEquals(out, Formatter.format(out), "formatting is not idempotent")
    }

    // ---- fidelity over real sources ----

    @TestFactory
    fun `examples and golden sources survive formatting unchanged in meaning`(): List<DynamicTest> {
        val roots = listOf("../examples", "examples", "../compiler/src/test/resources/golden", "src/test/resources/golden")
        val files = roots.map { File(it) }.filter { it.isDirectory }
            .flatMap { it.walkTopDown().filter { f -> f.extension == "dawn" } }
            .distinctBy { it.canonicalPath }
        check(files.isNotEmpty()) { "no .dawn sources found for fidelity check" }
        return files.map { f ->
            DynamicTest.dynamicTest(f.name) { assertFidelity(f.readText()) }
        }
    }

    // ---- fixture goldens ----

    private val fmtDir: File = run {
        val local = File("src/test/resources/golden/fmt")
        if (local.isDirectory) local else File("compiler/src/test/resources/golden/fmt")
    }
    private val update = System.getProperty("updateGolden") == "true"

    @TestFactory
    fun `fmt fixtures`(): List<DynamicTest> {
        val cases = fmtDir.listFiles { f -> f.extension == "dawn" }?.sortedBy { it.name } ?: emptyList()
        check(cases.isNotEmpty()) { "no fmt fixtures under $fmtDir" }
        return cases.map { case ->
            DynamicTest.dynamicTest(case.name) {
                val formatted = Formatter.format(case.readText())
                val expected = File(case.parentFile, case.nameWithoutExtension + ".formatted")
                if (update) {
                    expected.writeText(formatted)
                } else {
                    check(expected.exists()) { "missing ${expected.name}; regenerate with -DupdateGolden=true" }
                    assertEquals(expected.readText(), formatted, "fmt output changed for ${case.name}")
                }
                // fixtures must also be idempotent and token-preserving
                assertFidelity(case.readText())
            }
        }
    }

    @Test
    fun `empty input formats to empty`() {
        assertEquals("", Formatter.format(""))
        assertEquals("", Formatter.format("   \n  \n"))
    }

    @Test
    fun `index brackets hug the value`() {
        val src = "pub fn main() -> Unit !io = println(to_string(xs [0] [1] + m [\"k\"]))\n"
        val out = Formatter.format(src)
        assertEquals("pub fn main() -> Unit !io = println(to_string(xs[0][1] + m[\"k\"]))\n", out)
        assertFidelity(src)
    }

    @Test
    fun `unsafe_pure block formats like comptime`() {
        val src = "pub fn maxi(a: Int, b: Int) -> Int = unsafe_pure{Math.max( a,b )}\n"
        val out = Formatter.format(src)
        assertEquals("pub fn maxi(a: Int, b: Int) -> Int = unsafe_pure { Math.max(a, b) }\n", out)
        assertFidelity(src)
    }
}
