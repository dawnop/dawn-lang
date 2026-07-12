package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.TestFactory
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.PrintStream

/**
 * Every ```dawn code block in docs/tutorial.md must analyze without errors, so the
 * tutorial can never drift from the language. A block tagged ```dawn skip-check is
 * skipped (for deliberate counter-examples). A ```dawn block immediately followed by
 * a ```output block is compiled, run, and its stdout checked against that block.
 */
class TutorialTest {

    private data class Block(val info: String, val code: String, val output: String?)

    private val tutorial: File = run {
        val local = File("../docs/tutorial.md")
        if (local.exists()) local else File("docs/tutorial.md")
    }

    private fun blocks(): List<Block> {
        val lines = tutorial.readText().split("\n")
        val out = ArrayList<Block>()
        var i = 0
        while (i < lines.size) {
            val line = lines[i]
            if (line.startsWith("```dawn")) {
                val info = line.removePrefix("```").trim()
                val code = StringBuilder()
                i++
                while (i < lines.size && !lines[i].startsWith("```")) { code.appendLine(lines[i]); i++ }
                i++ // closing fence
                // an immediately following ```output block, if any
                var output: String? = null
                var j = i
                while (j < lines.size && lines[j].isBlank()) j++
                if (j < lines.size && lines[j].trim() == "```output") {
                    val buf = StringBuilder()
                    j++
                    while (j < lines.size && !lines[j].startsWith("```")) { buf.appendLine(lines[j]); j++ }
                    output = buf.toString()
                    i = j + 1
                }
                out.add(Block(info, code.toString(), output))
            } else i++
        }
        return out
    }

    private fun runMain(code: String): String {
        val analysis = analyze(code)
        check(!analysis.hasErrors) { "compile errors:\n" + analysis.diagnostics.joinToString("\n") { it.message } }
        val classes = CodeGen(analysis.module, "tut").generate()
        val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }
        val cls = Class.forName("tut", false, loader)
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

    @TestFactory
    fun `tutorial code blocks compile and run`(): List<DynamicTest> {
        check(tutorial.exists()) { "missing docs/tutorial.md" }
        val bs = blocks()
        check(bs.isNotEmpty()) { "no dawn code blocks found in tutorial" }
        // module examples span multiple files, so they can't compile as standalone blocks
        check(bs.count { it.info.contains("skip-check") } <= 6) { "too many skip-check blocks" }
        return bs.mapIndexed { idx, b ->
            DynamicTest.dynamicTest("block ${idx + 1}${if (b.info.contains("skip-check")) " (skip-check)" else ""}") {
                if (b.info.contains("skip-check")) return@dynamicTest
                val analysis = analyze(b.code)
                check(!analysis.hasErrors) {
                    "block ${idx + 1} does not compile:\n${b.code}\n--\n" +
                        analysis.diagnostics.joinToString("\n") { it.message }
                }
                if (b.output != null) {
                    val got = runMain(b.code)
                    check(got == b.output) {
                        "block ${idx + 1} output mismatch:\nexpected:\n${b.output}\ngot:\n$got"
                    }
                }
            }
        }
    }
}
