package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The milestone acceptance samples in examples/ compile and run as checked in. */
class ExamplesTest {

    private fun load(path: String): Pair<Class<*>, Int> {
        val file = File(path)
        assertTrue(file.exists(), "missing example: $path")
        val analysis = analyze(file.readText())
        check(!analysis.hasErrors) {
            "$path does not compile:\n" + analysis.diagnostics.joinToString("\n") { it.message }
        }
        val classes = CodeGen(analysis.module, "example", includeTests = true).generate()
        val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }
        return Class.forName("example", false, loader) to analysis.module.tests.size
    }

    private fun captureOut(body: () -> Unit): String {
        val buf = ByteArrayOutputStream()
        val old = System.out
        System.setOut(PrintStream(buf, true, "UTF-8"))
        try {
            body()
        } finally {
            System.setOut(old)
        }
        return buf.toString("UTF-8")
    }

    private fun examplePath(name: String): String {
        // gradle runs tests with cwd = compiler/
        val local = File("../examples/$name")
        return if (local.exists()) local.path else "examples/$name"
    }

    @Test
    fun `calc dot dawn runs and its test blocks pass`() {
        val (cls, testCount) = load(examplePath("calc.dawn"))
        // inject argv (the JVM wrapper would normally set it) and run main()
        cls.getDeclaredField("dawn\$args").set(null, arrayOf("2+3*4"))
        val out = captureOut { cls.getDeclaredMethod("main").invoke(null) }
        assertEquals("dawn-calc (0.1.2)\n2+3*4 = 14\n", out)

        assertTrue(testCount > 0, "calc.dawn should have test blocks")
        for (i in 0 until testCount) {
            cls.getDeclaredMethod("dawn\$test\$$i").invoke(null) // throws on failure
        }
    }

    @Test
    fun `shapes dot dawn still runs and its test blocks pass`() {
        val (cls, testCount) = load(examplePath("shapes.dawn"))
        captureOut { cls.getDeclaredMethod("main").invoke(null) }
        for (i in 0 until testCount) {
            cls.getDeclaredMethod("dawn\$test\$$i").invoke(null)
        }
    }
}
