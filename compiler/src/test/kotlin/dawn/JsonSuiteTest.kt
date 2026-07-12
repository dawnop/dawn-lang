package dawn

import dawn.check.analyzeProject
import dawn.codegen.CodeGen
import org.junit.jupiter.api.DynamicTest
import org.junit.jupiter.api.TestFactory
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.PrintStream

/**
 * The M4 acceptance (docs/design.md): the pure-Dawn multi-module JSON library in
 * examples/m4/json compiles once, then runs over every file in JSONTestSuite.
 *   y_*  must print "valid"    n_*  must print "invalid"
 *   i_*  may print either, but must never throw
 * A small override list (json-suite-overrides.txt) may flip at most 5 verdicts,
 * each with a stated reason (e.g. lossy UTF-8 decoding on read).
 */
class JsonSuiteTest {

    private val projectDir: File = run {
        val a = File("../examples/m4/json")
        if (a.isDirectory) a else File("examples/m4/json")
    }

    private val overrides: Set<String> = run {
        val f = listOf(
            File("src/test/resources/json-suite-overrides.txt"),
            File("compiler/src/test/resources/json-suite-overrides.txt"),
        ).firstOrNull { it.exists() }
        val names = f?.readLines().orEmpty()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .map { it.substringBefore(' ').trim() }
            .toSet()
        check(names.size <= 5) { "at most 5 suite overrides allowed, found ${names.size}" }
        names
    }

    // compiled once: class table + entry class name + the args field
    private val compiled: Triple<Class<*>, java.lang.reflect.Field, java.lang.reflect.Method> by lazy {
        val program = analyzeProject(projectDir)
        check(!program.hasErrors) {
            "the JSON library did not compile:\n" + program.diagnostics.joinToString("\n") {
                it.diag.render(it.source)
            }
        }
        val units = program.modules.map { CodeGen.Companion.ModuleUnit(it.module, it.className) }
        val classes = CodeGen.generateProgram(units)
        val entry = program.modules.first { m -> m.module.fns.any { it.name == "main" } }
        val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }
        val cls = Class.forName(entry.className.replace('/', '.'), false, loader)
        Triple(cls, cls.getDeclaredField("dawn\$args"), cls.getDeclaredMethod("main"))
    }

    private fun runOn(path: File): String {
        val (cls, argsField, main) = compiled
        argsField.set(null, arrayOf(path.absolutePath))
        val buf = ByteArrayOutputStream()
        val old = System.out
        System.setOut(PrintStream(buf, true, "UTF-8"))
        try {
            main.invoke(null)
        } finally {
            System.setOut(old)
        }
        return buf.toString("UTF-8").trim()
    }

    @TestFactory
    fun `JSONTestSuite parsing`(): List<DynamicTest> {
        val dir = File(projectDir, "suite/test_parsing")
        check(dir.isDirectory) { "missing vendored suite at $dir" }
        val files = dir.listFiles { f -> f.extension == "json" }?.sortedBy { it.name } ?: emptyList()
        check(files.size > 300) { "expected the full JSONTestSuite, found ${files.size} files" }
        return files.map { f ->
            DynamicTest.dynamicTest(f.name) {
                val got = runOn(f)
                check(got == "valid" || got == "invalid") { "${f.name}: unexpected output `$got`" }
                val overridden = f.name in overrides
                when (f.name.first()) {
                    'y' -> if (!overridden) check(got == "valid") { "${f.name}: expected valid, got $got" }
                    'n' -> if (!overridden) check(got == "invalid") { "${f.name}: expected invalid, got $got" }
                    else -> {} // i_: any verdict, as long as it didn't throw
                }
            }
        }
    }
}
