package dawn

import dawn.check.analyzeProject
import dawn.cli.CliError
import dawn.cli.addDependency
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.assertThrows
import org.junit.jupiter.api.io.TempDir
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * `dawn add` (docs/package-design.md, the format-preserving edit the TOML CST
 * was built for): Maven coordinates, archive urls (fetched + hashed, never a
 * hand-computed hash), and local package paths — each preserving the file's
 * comments and spacing, each updating in place on a repeat add.
 */
class AddCmdTest {

    @TempDir
    lateinit var cache: File

    @BeforeEach
    fun isolateCache() {
        System.setProperty("dawn.pkg.cache", cache.path)
    }

    @AfterEach
    fun restoreCache() {
        System.clearProperty("dawn.pkg.cache")
    }

    private fun tree(dir: File, files: Map<String, String>): File {
        for ((rel, text) in files) {
            val f = File(dir, rel)
            f.parentFile.mkdirs()
            f.writeText(text)
        }
        return dir
    }

    private fun appDir(dir: File): File {
        tree(dir, mapOf(
            "app/dawn.toml" to "schema = 1\nname = \"app\" # the app\n",
            "app/src/main.dawn" to "pub fn main() -> Unit !io = println(\"x\")\n",
        ))
        return File(dir, "app")
    }

    private fun jsonPkg(dir: File, version: String): File = tree(File(dir, "json-src-$version"), mapOf(
        "dawn.toml" to "schema = 1\nname = \"json\"\nversion = \"$version\"\n",
        "src/value.dawn" to "pub fn tag() -> String = \"json $version\"\n",
    ))

    private fun archive(src: File, dir: File, name: String): String {
        val zip = File(dir, "$name.zip")
        ZipOutputStream(zip.outputStream()).use { z ->
            src.walkTopDown().filter { it.isFile }.sortedBy { it.path }.forEach { f ->
                val rel = src.toPath().relativize(f.toPath()).joinToString("/")
                z.putNextEntry(ZipEntry("$name-wrapper/$rel"))
                f.inputStream().use { it.copyTo(z) }
                z.closeEntry()
            }
        }
        return "file://${zip.absolutePath}"
    }

    @Test
    fun `a maven coordinate lands under java-deps, keyed by artifact`(@TempDir dir: File) {
        val app = appDir(dir)
        val msg = addDependency(app, "org.xerial:sqlite-jdbc:3.36.0.3", null, null)
        assertTrue(msg.contains("sqlite-jdbc"))
        val text = File(app, "dawn.toml").readText()
        assertTrue(text.contains("[java-deps]"))
        assertTrue(text.contains("sqlite-jdbc = \"org.xerial:sqlite-jdbc:3.36.0.3\""))
        assertTrue(text.contains("# the app"), "the existing comment must survive")
        // a repeat add with a new version updates the one entry in place
        addDependency(app, "org.xerial:sqlite-jdbc:3.50.1.0", null, null)
        val text2 = File(app, "dawn.toml").readText()
        assertTrue(text2.contains("3.50.1.0"))
        assertTrue(!text2.contains("3.36.0.3"))
    }

    @Test
    fun `a local path lands under deps, keyed by the package name`(@TempDir dir: File) {
        val app = appDir(dir)
        tree(dir, mapOf(
            "packages/web/dawn.toml" to "schema = 1\nname = \"web\"\n",
            "packages/web/src/types.dawn" to "pub fn tag() -> String = \"w\"\n",
        ))
        addDependency(app, "../packages/web", null, null)
        val text = File(app, "dawn.toml").readText()
        assertTrue(text.contains("web = \"../packages/web\""))
        File(app, "src/main.dawn").writeText(
            "use web/types\n\npub fn main() -> Unit !io = println(types.tag())\n")
        val msgs = analyzeProject(app).diagnostics.map { it.diag.message }
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
    }

    @Test
    fun `an archive url is fetched, hashed, and written as a deps table`(@TempDir dir: File) {
        val app = appDir(dir)
        val url = archive(jsonPkg(dir, "1.0.0"), dir, "json-1.0.0")
        val msg = addDependency(app, url, null, null)
        assertTrue(msg.contains("json 1.0.0"), msg)
        val text = File(app, "dawn.toml").readText()
        assertTrue(text.contains("[deps.json]"))
        assertTrue(text.contains("version = \"1.0.0\""))
        assertTrue(Regex("hash = \"d1:[0-9a-f]{64}\"").containsMatchIn(text))
        // the written manifest must resolve for real
        File(app, "src/main.dawn").writeText(
            "use json/value\n\npub fn main() -> Unit !io = println(value.tag())\n")
        val msgs = analyzeProject(app).diagnostics.map { it.diag.message }
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
        // bumping = adding the next archive; the table updates in place
        val url2 = archive(jsonPkg(dir, "1.1.0"), dir, "json-1.1.0")
        addDependency(app, url2, null, null)
        val text2 = File(app, "dawn.toml").readText()
        assertEquals(1, Regex("\\[deps\\.json]").findAll(text2).count())
        assertTrue(text2.contains("version = \"1.1.0\""))
    }

    @Test
    fun `--as picks the alias, the identity stays the package name`(@TempDir dir: File) {
        val app = appDir(dir)
        val url = archive(jsonPkg(dir, "1.0.0"), dir, "json-1.0.0")
        val msg = addDependency(app, url, null, "j")
        assertTrue(msg.contains("as `j`"), msg)
        assertTrue(File(app, "dawn.toml").readText().contains("[deps.j]"))
        File(app, "src/main.dawn").writeText(
            "use j/value\n\npub fn main() -> Unit !io = println(value.tag())\n")
        val msgs = analyzeProject(app).diagnostics.map { it.diag.message }
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
    }

    @Test
    fun `a package without a version cannot be added by url`(@TempDir dir: File) {
        val app = appDir(dir)
        val pkg = tree(File(dir, "nv"), mapOf(
            "dawn.toml" to "schema = 1\nname = \"nv\"\n",
            "src/a.dawn" to "pub fn a() -> Int = 1\n",
        ))
        val url = archive(pkg, dir, "nv-x")
        val e = assertThrows<CliError> { addDependency(app, url, null, null) }
        assertTrue(e.message!!.contains("declares no `version`"))
    }
}
