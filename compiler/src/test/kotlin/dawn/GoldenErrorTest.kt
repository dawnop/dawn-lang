package dawn

import dawn.check.analyze
import dawn.diag.Severity
import dawn.diag.SourceFile
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.TestFactory
import java.io.File
import kotlin.test.assertEquals

/**
 * Locks the exact text of diagnostics against golden files, so any change to an
 * error message (or its location, caret, or hint) shows up as a reviewable diff.
 *
 * Each case is a pair of files under src/test/resources/golden/errors/:
 *   <case>.dawn  — a program that must produce at least one error
 *   <case>.err   — the expected rendered diagnostics
 *
 * Regenerate the .err files after an intentional message change with
 *   gradle :compiler:test -DupdateGolden=true
 * then review `git diff` before committing — never regenerate blind.
 */
class GoldenErrorTest {

    private val dir: File = run {
        val local = File("src/test/resources/golden/errors")
        if (local.isDirectory) local else File("compiler/src/test/resources/golden/errors")
    }

    private val update: Boolean = System.getProperty("updateGolden") == "true"

    /** Render all diagnostics with a machine-independent path so goldens are portable. */
    private fun render(case: File): Pair<String, Boolean> {
        val text = case.readText()
        // A case exercising fuel exhaustion runs under a tiny budget so it aborts fast.
        val fuel = if (case.name.startsWith("ct_fuel")) 1_000L else 100_000_000L
        val analysis = analyze(text, comptimeFuel = fuel)
        val file = SourceFile(case.name, text)
        val ordered = analysis.diagnostics.sortedWith(
            compareBy({ it.span.start }, { it.span.end }, { it.message })
        )
        val hasError = ordered.any { it.severity == Severity.ERROR }
        return ordered.joinToString("") { it.render(file) } to hasError
    }

    @TestFactory
    fun `golden error cases`(): List<DynamicTest> {
        val cases = dir.listFiles { f -> f.extension == "dawn" }?.sortedBy { it.name } ?: emptyList()
        check(cases.isNotEmpty()) { "no golden error cases found under $dir" }
        return cases.map { case ->
            DynamicTest.dynamicTest(case.name) {
                val (actual, hasError) = render(case)
                check(hasError) {
                    "${case.name}: a golden error case must produce at least one error, but analysis was clean"
                }
                val expected = File(case.parentFile, case.nameWithoutExtension + ".err")
                if (update) {
                    expected.writeText(actual)
                } else {
                    check(expected.exists()) {
                        "missing golden ${expected.name}; regenerate with -DupdateGolden=true"
                    }
                    assertEquals(expected.readText(), actual, "diagnostics changed for ${case.name}")
                }
            }
        }
    }
}
