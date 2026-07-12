package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.TestFactory
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.PrintStream
import kotlin.test.assertEquals

/**
 * Golden run cases: each pair of files under src/test/resources/golden/run/
 *   <case>.dawn  — a program that must compile cleanly
 *   <case>.out   — the exact stdout its main() produces
 *
 * This is the preferred home for "compile, run, compare output" tests: the
 * Dawn source lives in a real .dawn file (LSP, highlighting, no dollar-escaping
 * dances inside Kotlin raw strings), and FmtTest sweeps the directory for
 * formatter fidelity automatically. Tests that assert on diagnostics or need
 * extra harness logic stay in Kotlin (or golden/errors/).
 *
 * Regenerate the .out files after an intentional behavior change with
 *   gradle :compiler:test -DupdateGolden=true
 * then review `git diff` before committing — never regenerate blind.
 */
class GoldenRunTest {

    private val dir: File = run {
        val local = File("src/test/resources/golden/run")
        if (local.isDirectory) local else File("compiler/src/test/resources/golden/run")
    }

    private val update: Boolean = System.getProperty("updateGolden") == "true"

    private fun runCase(case: File): String {
        val analysis = analyze(case.readText())
        check(!analysis.hasErrors) {
            "${case.name} does not compile:\n" + analysis.diagnostics.joinToString("\n") { it.message }
        }
        val classes = CodeGen(analysis.module, "goldenrun").generate()
        val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }
        val cls = Class.forName("goldenrun", false, loader)
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

    @TestFactory
    fun `golden run cases`(): List<DynamicTest> {
        val cases = dir.listFiles { f -> f.extension == "dawn" }?.sortedBy { it.name } ?: emptyList()
        check(cases.isNotEmpty()) { "no golden run cases found under $dir" }
        return cases.map { case ->
            DynamicTest.dynamicTest(case.nameWithoutExtension) {
                val actual = runCase(case)
                val expected = File(case.parentFile, case.nameWithoutExtension + ".out")
                if (update) {
                    expected.writeText(actual)
                } else {
                    check(expected.exists()) {
                        "missing golden ${expected.name}; regenerate with -DupdateGolden=true"
                    }
                    assertEquals(expected.readText(), actual, "output changed for ${case.name}")
                }
            }
        }
    }
}
