package dawn

import dawn.check.ModuleLoader
import org.junit.jupiter.api.io.TempDir
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * The module loader (spec §10.5): it resolves the `use` graph rooted at a project
 * directory, parses each file once, orders modules by dependency, and reports
 * missing files, bad segments, duplicate imports, and cycles.
 */
class ModuleLoaderTest {

    private fun write(root: File, rel: String, text: String) {
        val f = File(root, rel)
        f.parentFile.mkdirs()
        f.writeText(text)
    }

    /** A project directory with src/ populated from (relative path → source). */
    private fun project(dir: File, files: Map<String, String>): File {
        for ((rel, text) in files) write(dir, "src/$rel", text)
        return dir
    }

    @Test
    fun `loads modules in topological order`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to "use util/math\npub fn main() -> Unit !io = println(\"hi\")\n",
            "util/math.dawn" to "pub fn double(x: Int) -> Int = x * 2\n",
        ))
        val res = ModuleLoader.loadDirectory(dir)
        assertFalse(res.hasErrors, res.loadDiagnostics.joinToString("\n") { it.diag.message })
        val order = res.modules.map { it.modPath }
        assertEquals(listOf("util/math", "main"), order, "dependency must come before dependent")
        assertEquals(setOf("util/math", "main"), res.modules.map { it.modPath }.toSet())
    }

    @Test
    fun `loads every module under src even if unreferenced`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to "pub fn main() -> Unit !io = println(\"hi\")\n",
            "orphan.dawn" to "pub fn unused() -> Int = 1\n",
        ))
        val res = ModuleLoader.loadDirectory(dir)
        assertTrue(res.modules.any { it.modPath == "orphan" }, "unreferenced modules are still loaded")
    }

    @Test
    fun `parses each file exactly once even with diamond imports`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to "use a\nuse b\npub fn main() -> Unit !io = println(\"hi\")\n",
            "a.dawn" to "use base\npub fn fa() -> Int = 1\n",
            "b.dawn" to "use base\npub fn fb() -> Int = 2\n",
            "base.dawn" to "pub fn base_val() -> Int = 0\n",
        ))
        val res = ModuleLoader.loadDirectory(dir)
        assertFalse(res.hasErrors)
        assertEquals(1, res.modules.count { it.modPath == "base" }, "base loaded once despite two importers")
        // base must precede both a and b, which must precede main
        val idx = res.modules.mapIndexed { i, m -> m.modPath to i }.toMap()
        assertTrue(idx["base"]!! < idx["a"]!!)
        assertTrue(idx["base"]!! < idx["b"]!!)
        assertTrue(idx["a"]!! < idx["main"]!!)
    }

    @Test
    fun `reports a missing module file`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to "use does/not_exist\npub fn main() -> Unit !io = println(\"hi\")\n",
        ))
        val res = ModuleLoader.loadDirectory(dir)
        assertTrue(res.hasErrors)
        assertTrue(res.loadDiagnostics.any { it.diag.message.contains("cannot find module `does/not_exist`") },
            res.loadDiagnostics.joinToString("\n") { it.diag.message })
    }

    @Test
    fun `reports a circular dependency`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to "use a\npub fn main() -> Unit !io = println(\"hi\")\n",
            "a.dawn" to "use b\npub fn fa() -> Int = 1\n",
            "b.dawn" to "use a\npub fn fb() -> Int = 2\n",
        ))
        val res = ModuleLoader.loadDirectory(dir)
        assertTrue(res.hasErrors)
        assertTrue(res.loadDiagnostics.any { it.diag.message.contains("circular module dependency") },
            res.loadDiagnostics.joinToString("\n") { it.diag.message })
    }

    @Test
    fun `reports a duplicate import`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to "use util\nuse util\npub fn main() -> Unit !io = println(\"hi\")\n",
            "util.dawn" to "pub fn helper() -> Int = 1\n",
        ))
        val res = ModuleLoader.loadDirectory(dir)
        assertTrue(res.hasErrors)
        assertTrue(res.loadDiagnostics.any { it.diag.message.contains("imported more than once") })
    }

    @Test
    fun `reports a missing src folder`(@TempDir dir: File) {
        val res = ModuleLoader.loadDirectory(dir)
        assertTrue(res.hasErrors)
        assertTrue(res.loadDiagnostics.any { it.diag.message.contains("no `src/` folder") })
    }

    @Test
    fun `file mode finds the src root above the entry file`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to "use util/math\npub fn main() -> Unit !io = println(\"hi\")\n",
            "util/math.dawn" to "pub fn double(x: Int) -> Int = x * 2\n",
        ))
        // hand the loader the deep file directly; it must still resolve `use util/math`
        val res = ModuleLoader.loadFile(File(dir, "src/main.dawn"))
        assertFalse(res.hasErrors, res.loadDiagnostics.joinToString("\n") { it.diag.message })
        assertTrue(res.modules.any { it.modPath == "util/math" })
    }
}
