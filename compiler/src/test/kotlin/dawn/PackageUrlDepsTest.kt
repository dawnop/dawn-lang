package dawn

import dawn.check.analyzeProject
import dawn.manifest.PkgFetch
import dawn.manifest.SemVer
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.io.TempDir
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * `[deps.<alias>]` url + hash dependencies (docs/package-design.md, versioning
 * stage): the d1 tree hash, the content-addressed cache, and MVS over the
 * requirement graph. All archives are file:// zips — the fetch path is the
 * production one minus the network.
 */
class PackageUrlDepsTest {

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

    /** zip [src] under a GitHub-style single wrapper directory; returns (url, d1 hash) */
    private fun archive(src: File, dir: File, name: String): Pair<String, String> {
        val hash = PkgFetch.treeHash(src)
        val zip = File(dir, "$name.zip")
        ZipOutputStream(zip.outputStream()).use { z ->
            src.walkTopDown().filter { it.isFile }.sortedBy { it.path }.forEach { f ->
                val rel = src.toPath().relativize(f.toPath()).joinToString("/")
                z.putNextEntry(ZipEntry("$name-wrapper/$rel"))
                f.inputStream().use { it.copyTo(z) }
                z.closeEntry()
            }
        }
        return "file://${zip.absolutePath}" to hash
    }

    /** the same fixture as [archive], as a hand-rolled gzipped ustar */
    private fun tarArchive(src: File, dir: File, name: String): Pair<String, String> {
        val hash = PkgFetch.treeHash(src)
        val buf = java.io.ByteArrayOutputStream()
        java.util.zip.GZIPOutputStream(buf).use { gz ->
            fun header(path: String, size: Int, type: Char): ByteArray {
                val b = ByteArray(512)
                path.toByteArray().copyInto(b, 0)
                "0000644 ".toByteArray().copyInto(b, 100) // mode
                "0000000 ".toByteArray().copyInto(b, 108) // uid
                "0000000 ".toByteArray().copyInto(b, 116) // gid
                "%011o ".format(size).toByteArray().copyInto(b, 124)
                "00000000000 ".toByteArray().copyInto(b, 136) // mtime
                for (i in 148 until 156) b[i] = ' '.code.toByte() // checksum-as-spaces
                b[156] = type.code.toByte()
                "ustar".toByteArray().copyInto(b, 257)
                "00".toByteArray().copyInto(b, 263) // version
                val sum = b.sumOf { it.toInt() and 0xff }
                "%06o".format(sum).toByteArray().copyInto(b, 148)
                b[154] = 0
                b[155] = ' '.code.toByte()
                return b
            }
            gz.write(header("$name-wrapper/", 0, '5'))
            src.walkTopDown().filter { it.isFile }.sortedBy { it.path }.forEach { f ->
                val rel = src.toPath().relativize(f.toPath()).joinToString("/")
                val bytes = f.readBytes()
                gz.write(header("$name-wrapper/$rel", bytes.size, '0'))
                gz.write(bytes)
                gz.write(ByteArray((512 - bytes.size % 512) % 512))
            }
            gz.write(ByteArray(1024)) // end-of-archive marker
        }
        val tarGz = File(dir, "$name.tar.gz")
        tarGz.writeBytes(buf.toByteArray())
        return "file://${tarGz.absolutePath}" to hash
    }

    private fun jsonPkg(dir: File, version: String, extra: String = ""): File = tree(File(dir, "json-src-$version"), mapOf(
        "dawn.toml" to "schema = 1\nname = \"json\"\nversion = \"$version\"\n",
        "src/value.dawn" to "pub fn tag() -> String = \"json $version\"\n$extra",
    ))

    private fun app(dir: File, toml: String, main: String): File {
        tree(dir, mapOf("app/dawn.toml" to toml, "app/src/main.dawn" to main))
        return File(dir, "app")
    }

    private fun messages(appDir: File): List<String> =
        analyzeProject(appDir).diagnostics.map { it.diag.message }

    @Test
    fun `semver parses strictly and orders numerically`() {
        assertEquals(0, SemVer.parse("1.2.3")!!.compareTo(SemVer(1, 2, 3)))
        assertTrue(SemVer.parse("1.10.0")!! > SemVer.parse("1.9.9")!!)
        assertNull(SemVer.parse("1.2"))
        assertNull(SemVer.parse("v1.2.3"))
        assertNull(SemVer.parse("1.2.3-beta"))
        assertNull(SemVer.parse("01.2.3"))
    }

    @Test
    fun `the d1 hash is stable and content-sensitive`(@TempDir dir: File) {
        val a = jsonPkg(dir, "1.0.0")
        val h1 = PkgFetch.treeHash(a)
        val h2 = PkgFetch.treeHash(a)
        assertEquals(h1, h2)
        assertTrue(h1.startsWith("d1:") && h1.length == 3 + 64)
        File(a, "src/value.dawn").appendText("# changed\n")
        assertTrue(PkgFetch.treeHash(a) != h1)
    }

    @Test
    fun `a url dependency fetches, verifies and links under the package namespace`(@TempDir dir: File) {
        val (url, hash) = archive(jsonPkg(dir, "1.0.0"), dir, "json-1.0.0")
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps.json]
            url = "$url"
            version = "1.0.0"
            hash = "$hash"
        """.trimIndent(), """
            use json/value

            pub fn main() -> Unit !io = println(value.tag())
        """.trimIndent())
        val program = analyzeProject(appDir)
        val msgs = program.diagnostics.map { it.diag.message }
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
        assertEquals("dawn\$pkg\$json/value",
            program.modules.first { it.modPath == "json/value" }.className)
        // second run resolves from the cache alone: delete the archive file
        assertTrue(File(dir, "json-1.0.0.zip").delete())
        assertTrue(messages(appDir).isEmpty())
    }

    @Test
    fun `a hash mismatch reports the actual hash and links nothing`(@TempDir dir: File) {
        val (url, _) = archive(jsonPkg(dir, "1.0.0"), dir, "json-1.0.0")
        val wrong = "d1:" + "0".repeat(64)
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps.json]
            url = "$url"
            version = "1.0.0"
            hash = "$wrong"
        """.trimIndent(), "pub fn main() -> Unit !io = println(\"x\")\n")
        val diags = analyzeProject(appDir).diagnostics
        assertTrue(diags.any { it.diag.message.contains("hash mismatch") },
            "got:\n" + diags.joinToString("\n") { it.diag.message })
        assertTrue(diags.any { it.diag.hint?.contains("actual:") == true })
    }

    @Test
    fun `minimal version selection picks the maximum required version`(@TempDir dir: File) {
        // json 1.1.0 adds `pretty`; web requires 1.1.0, the app only 1.0.0
        val (jsonOldUrl, jsonOldHash) = archive(jsonPkg(dir, "1.0.0"), dir, "json-1.0.0")
        val (jsonNewUrl, jsonNewHash) = archive(
            jsonPkg(dir, "1.1.0", "pub fn pretty() -> String = \"pretty\"\n"), dir, "json-1.1.0")
        val web = tree(File(dir, "web-src"), mapOf(
            "dawn.toml" to """
                schema = 1
                name = "web"
                version = "1.0.0"

                [deps.json]
                url = "$jsonNewUrl"
                version = "1.1.0"
                hash = "$jsonNewHash"
            """.trimIndent(),
            "src/router.dawn" to "use json/value\n\npub fn info() -> String = value.tag()\n",
        ))
        val (webUrl, webHash) = archive(web, dir, "web-1.0.0")
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps.web]
            url = "$webUrl"
            version = "1.0.0"
            hash = "$webHash"

            [deps.json]
            url = "$jsonOldUrl"
            version = "1.0.0"
            hash = "$jsonOldHash"
        """.trimIndent(), """
            use json/value
            use web/router

            pub fn main() -> Unit !io = println(router.info() ++ value.pretty())
        """.trimIndent())
        // `value.pretty` only exists in 1.1.0: the app compiles iff MVS chose the max
        val msgs = messages(appDir)
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
    }

    @Test
    fun `the same version under two hashes is an integrity error`(@TempDir dir: File) {
        val (urlA, hashA) = archive(jsonPkg(dir, "1.0.0"), dir, "json-a")
        val (urlB, hashB) = archive(jsonPkg(dir, "1.0.0", "# different bytes\n"), dir, "json-b")
        val web = tree(File(dir, "web-src"), mapOf(
            "dawn.toml" to """
                schema = 1
                name = "web"

                [deps.json]
                url = "$urlB"
                version = "1.0.0"
                hash = "$hashB"
            """.trimIndent(),
            "src/router.dawn" to "pub fn ok() -> Bool = true\n",
        ))
        val (webUrl, webHash) = archive(web, dir, "web-1.0.0")
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps.web]
            url = "$webUrl"
            version = "1.0.0"
            hash = "$webHash"

            [deps.json]
            url = "$urlA"
            version = "1.0.0"
            hash = "$hashA"
        """.trimIndent(), "pub fn main() -> Unit !io = println(\"x\")\n")
        assertTrue(messages(appDir).any { it.contains("required under different hashes") })
    }

    @Test
    fun `a package that declares a different version than selected is rejected`(@TempDir dir: File) {
        val (url, hash) = archive(jsonPkg(dir, "1.0.1"), dir, "json-1.0.1")
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps.json]
            url = "$url"
            version = "1.0.0"
            hash = "$hash"
        """.trimIndent(), "pub fn main() -> Unit !io = println(\"x\")\n")
        assertTrue(messages(appDir).any {
            it.contains("declares version 1.0.1 but 1.0.0 was selected")
        })
    }

    @Test
    fun `v2 needs the major in the real package name`(@TempDir dir: File) {
        // the archive's own manifest declares no version, so only the
        // selection-time check can catch the rename rule — on the real name
        val pkg = tree(File(dir, "json-src"), mapOf(
            "dawn.toml" to "schema = 1\nname = \"json\"\n",
            "src/value.dawn" to "pub fn tag() -> String = \"json\"\n"))
        val (url, hash) = archive(pkg, dir, "json-2.0.0")
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps.json]
            url = "$url"
            version = "2.0.0"
            hash = "$hash"
        """.trimIndent(), "pub fn main() -> Unit !io = println(\"x\")\n")
        assertTrue(messages(appDir).any { it.contains("needs the major in the package name") })
    }

    @Test
    fun `an alias keeps the old spelling across a v2 rename`(@TempDir dir: File) {
        val pkg = tree(File(dir, "json2-src"), mapOf(
            "dawn.toml" to "schema = 1\nname = \"json2\"\nversion = \"2.0.0\"\n",
            "src/value.dawn" to "pub fn tag() -> String = \"json two\"\n"))
        val (url, hash) = archive(pkg, dir, "json2-2.0.0")
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps.json]
            url = "$url"
            version = "2.0.0"
            hash = "$hash"
        """.trimIndent(), """
            use json/value

            pub fn main() -> Unit !io = println(value.tag())
        """.trimIndent())
        val program = analyzeProject(appDir)
        val msgs = program.diagnostics.map { it.diag.message }
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
        // the identity is json2; the alias only spells the consumer's imports
        assertEquals("dawn\$pkg\$json2/value",
            program.modules.first { it.modPath == "json2/value" }.className)
    }

    @Test
    fun `two aliases for one package share a single MVS selection`(@TempDir dir: File) {
        // web requires json 1.1.0 under the alias `json`; the app requires
        // 1.0.0 under the alias `j` — one package, one winner: 1.1.0
        val (jsonOldUrl, jsonOldHash) = archive(jsonPkg(dir, "1.0.0"), dir, "json-1.0.0")
        val (jsonNewUrl, jsonNewHash) = archive(
            jsonPkg(dir, "1.1.0", "pub fn pretty() -> String = \"pretty\"\n"), dir, "json-1.1.0")
        val web = tree(File(dir, "web-src"), mapOf(
            "dawn.toml" to """
                schema = 1
                name = "web"
                version = "1.0.0"

                [deps.json]
                url = "$jsonNewUrl"
                version = "1.1.0"
                hash = "$jsonNewHash"
            """.trimIndent(),
            "src/router.dawn" to "use json/value\n\npub fn info() -> String = value.tag()\n",
        ))
        val (webUrl, webHash) = archive(web, dir, "web-1.0.0")
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps.web]
            url = "$webUrl"
            version = "1.0.0"
            hash = "$webHash"

            [deps.j]
            url = "$jsonOldUrl"
            version = "1.0.0"
            hash = "$jsonOldHash"
        """.trimIndent(), """
            use j/value
            use web/router

            pub fn main() -> Unit !io = println(router.info() ++ value.pretty())
        """.trimIndent())
        // `value.pretty` only exists in 1.1.0: the app compiles iff both
        // aliases were grouped under the real name and MVS chose the max
        val msgs = messages(appDir)
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
    }

    @Test
    fun `a tar gz archive fetches like a zip`(@TempDir dir: File) {
        val (url, hash) = tarArchive(jsonPkg(dir, "1.0.0"), dir, "json-1.0.0")
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps.json]
            url = "$url"
            version = "1.0.0"
            hash = "$hash"
        """.trimIndent(), """
            use json/value

            pub fn main() -> Unit !io = println(value.tag())
        """.trimIndent())
        val program = analyzeProject(appDir)
        val msgs = program.diagnostics.map { it.diag.message }
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
        assertEquals("dawn\$pkg\$json/value",
            program.modules.first { it.modPath == "json/value" }.className)
    }

    @Test
    fun `a url table missing a key is rejected`(@TempDir dir: File) {
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps.json]
            url = "file:///x.zip"
            version = "1.0.0"
        """.trimIndent(), "pub fn main() -> Unit !io = println(\"x\")\n")
        assertTrue(messages(appDir).any { it.contains("is missing `hash`") })
    }

    @Test
    fun `one monorepo archive serves a subdir package and its internal path dep`(@TempDir dir: File) {
        // one archive holds packages/web and packages/json; web path-deps ../json
        val mono = tree(File(dir, "mono-src"), mapOf(
            "packages/json/dawn.toml" to "schema = 1\nname = \"json\"\n",
            "packages/json/src/value.dawn" to "pub fn tag() -> String = \"mono json\"\n",
            "packages/web/dawn.toml" to """
                schema = 1
                name = "web"

                [deps]
                json = "../json"
            """.trimIndent(),
            "packages/web/src/router.dawn" to "use json/value\n\npub fn info() -> String = value.tag()\n",
        ))
        val (url, hash) = archive(mono, dir, "mono-1.0.0")
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps.web]
            url = "$url"
            version = "1.0.0"
            hash = "$hash"
            subdir = "packages/web"
        """.trimIndent(), """
            use web/router

            pub fn main() -> Unit !io = println(router.info())
        """.trimIndent())
        val program = analyzeProject(appDir)
        val msgs = program.diagnostics.map { it.diag.message }
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
        assertEquals("dawn\$pkg\$json/value",
            program.modules.first { it.modPath == "json/value" }.className)
    }

    @Test
    fun `one package name may not come from two directories`(@TempDir dir: File) {
        tree(dir, mapOf(
            "wa/web/dawn.toml" to "schema = 1\nname = \"web\"\n",
            "wa/web/src/a.dawn" to "pub fn a() -> Int = 1\n",
            "wb/web/dawn.toml" to "schema = 1\nname = \"web\"\n",
            "wb/web/src/a.dawn" to "pub fn a() -> Int = 2\n",
            "lib/dawn.toml" to """
                schema = 1
                name = "lib"

                [deps]
                web = "../wb/web"
            """.trimIndent(),
            "lib/src/l.dawn" to "use web/a\n\npub fn l() -> Int = a.a()\n",
        ))
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps]
            web = "../wa/web"
            lib = "../lib"
        """.trimIndent(), """
            use lib/l

            pub fn main() -> Unit !io = println(to_string(l.l()))
        """.trimIndent())
        assertTrue(messages(appDir).any { it.contains("linked from two different directories") })
    }
}
