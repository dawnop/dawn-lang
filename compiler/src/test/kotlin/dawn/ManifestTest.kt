package dawn

import dawn.diag.DiagnosticSink
import dawn.diag.SourceFile
import dawn.manifest.Manifest
import dawn.manifest.MavenCoord
import dawn.manifest.TomlArr
import dawn.manifest.TomlBool
import dawn.manifest.TomlInt
import dawn.manifest.TomlParser
import dawn.manifest.TomlStr
import org.junit.jupiter.api.io.TempDir
import java.io.File
import kotlin.test.Test
import kotlin.test.assertContains
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * dawn.toml: the TOML subset parser (docs/package-design.md §4.2) and the manifest
 * schema over it (§4.1, §A.4).
 */
class ManifestTest {

    // ---- TOML subset: values ----

    private fun parse(text: String): Pair<dawn.manifest.TomlDoc, DiagnosticSink> {
        val sink = DiagnosticSink()
        val doc = TomlParser.parse(SourceFile("dawn.toml", text), sink)
        return doc to sink
    }

    private fun errorsOf(text: String): List<String> = parse(text).second.all.map { it.message }

    @Test
    fun `parses the supported value types`() {
        val (doc, sink) = parse(
            """
            schema = 1
            name = "demo"
            flag = true
            off = false
            big = 1_000_000
            neg = -3
            list = ["a", "b"]
            empty = []

            [java-deps]
            sqlite = "org.xerial:sqlite-jdbc:3.36.0.3"
            """.trimIndent(),
        )
        assertTrue(sink.all.isEmpty(), "unexpected: ${sink.all.map { it.message }}")
        assertEquals(1L, (doc.entry(null, "schema")!!.value as TomlInt).value)
        assertEquals("demo", (doc.entry(null, "name")!!.value as TomlStr).value)
        assertEquals(true, (doc.entry(null, "flag")!!.value as TomlBool).value)
        assertEquals(false, (doc.entry(null, "off")!!.value as TomlBool).value)
        assertEquals(1_000_000L, (doc.entry(null, "big")!!.value as TomlInt).value)
        assertEquals(-3L, (doc.entry(null, "neg")!!.value as TomlInt).value)
        assertEquals(listOf("a", "b"), (doc.entry(null, "list")!!.value as TomlArr).value)
        assertEquals(emptyList(), (doc.entry(null, "empty")!!.value as TomlArr).value)
        assertEquals("org.xerial:sqlite-jdbc:3.36.0.3", (doc.entry("java-deps", "sqlite")!!.value as TomlStr).value)
    }

    @Test
    fun `string escapes`() {
        val (doc, sink) = parse("""a = "q\"q\\b\nc\td\reé"""")
        assertTrue(sink.all.isEmpty(), "unexpected: ${sink.all.map { it.message }}")
        assertEquals("q\"q\\b\nc\td\reé", (doc.entry(null, "a")!!.value as TomlStr).value)
    }

    @Test
    fun `table scoping keeps same-named keys apart`() {
        val (doc, _) = parse(
            """
            k = "root"

            [a]
            k = "in a"

            [b]
            k = "in b"
            """.trimIndent(),
        )
        assertEquals("root", (doc.entry(null, "k")!!.value as TomlStr).value)
        assertEquals("in a", (doc.entry("a", "k")!!.value as TomlStr).value)
        assertEquals("in b", (doc.entry("b", "k")!!.value as TomlStr).value)
        assertEquals(listOf("a", "b"), doc.tableNames())
    }

    @Test
    fun `comments and trailing comments are not values`() {
        val (doc, sink) = parse(
            """
            # leading
            a = "x"  # trailing
            [t]  # after header
            b = 1 # here too
            """.trimIndent(),
        )
        assertTrue(sink.all.isEmpty(), "unexpected: ${sink.all.map { it.message }}")
        assertEquals("x", (doc.entry(null, "a")!!.value as TomlStr).value)
        assertEquals(1L, (doc.entry("t", "b")!!.value as TomlInt).value)
    }

    // ---- TOML subset: rejections must be loud, never a silent misread ----

    @Test
    fun `rejects constructs outside the subset`() {
        assertContains(errorsOf("[[deps]]").first(), "arrays of tables are not supported")
        assertContains(errorsOf("a = '''x'''").first(), "literal strings are not supported")
        assertContains(errorsOf("a = \"\"\"x\"\"\"").first(), "multi-line strings are not supported")
        assertContains(errorsOf("a = { b = 1 }").first(), "inline tables are not supported")
        assertContains(errorsOf("a.b = 1").first(), "dotted keys are not supported")
        assertContains(errorsOf("[a.b]").first(), "dotted table names are not supported")
        assertContains(errorsOf("\"a\" = 1").first(), "quoted keys are not supported")
        assertContains(errorsOf("a = 1.5").first(), "floats are not supported")
        assertContains(errorsOf("a = 2026-07-17").first(), "date-time values are not supported")
        assertContains(errorsOf("a = 0xff").first(), "only decimal integers are supported")
        assertContains(errorsOf("a = [1, 2]").first(), "array elements must be strings")
    }

    @Test
    fun `rejects malformed lines`() {
        assertContains(errorsOf("a").first(), "expected `=` after key `a`")
        assertContains(errorsOf("a =").first(), "expected a value")
        assertContains(errorsOf("a = \"x").first(), "unterminated string")
        assertContains(errorsOf("a = [\"x\"").first(), "unterminated array")
        assertContains(errorsOf("[t").first(), "expected `]` to close the table header")
        assertContains(errorsOf("a = \"x\" junk").first(), "unexpected text after the value")
        assertContains(errorsOf("a = \"\\q\"").first(), "unsupported escape")
    }

    @Test
    fun `rejects duplicates`() {
        assertContains(errorsOf("a = 1\na = 2").first(), "key `a` is defined more than once")
        assertContains(errorsOf("[t]\n[t]").first(), "table `t` is defined more than once")
        // same key in different tables is fine
        assertTrue(errorsOf("[a]\nk = 1\n[b]\nk = 2").isEmpty())
    }

    @Test
    fun `diagnostics point at the offending span`() {
        val text = "schema = 1\nname = \"x\"\nbad = 1.5\n"
        val sink = DiagnosticSink()
        val source = SourceFile("dawn.toml", text)
        TomlParser.parse(source, sink)
        val rendered = sink.all.first().render(source)
        assertContains(rendered, "dawn.toml:3:7")
        assertContains(rendered, "floats are not supported")
    }

    // ---- format preservation: the entire reason this parser is hand-written ----

    @Test
    fun `render round-trips byte-for-byte`() {
        val text = """
            # a manifest with character
            schema = 1
            name    =    "demo"     # odd spacing survives

            [java-deps]

            # why we need this one
            sqlite = "org.xerial:sqlite-jdbc:3.36.0.3"
        """.trimIndent() + "\n"
        val (doc, sink) = parse(text)
        assertTrue(sink.all.isEmpty())
        assertEquals(text, doc.render())
    }

    @Test
    fun `round-trips a file with no trailing newline and CRLF endings`() {
        for (text in listOf("schema = 1\nname = \"x\"", "schema = 1\r\nname = \"x\"\r\n", "", "\n")) {
            val (doc, _) = parse(text)
            assertEquals(text, doc.render(), "round-trip failed for ${text.replace("\r", "\\r").replace("\n", "\\n")}")
        }
    }

    @Test
    fun `editing a value preserves comments, spacing and key order`() {
        val text = """
            # keep me
            schema = 1
            name    =    "demo"   # and me

            [java-deps]
            # this comment explains sqlite
            sqlite = "org.xerial:sqlite-jdbc:3.36.0.3"
            bcrypt = "org.mindrot:jbcrypt:0.4"
        """.trimIndent() + "\n"
        val (doc, _) = parse(text)
        doc.setString("java-deps", "sqlite", "org.xerial:sqlite-jdbc:3.50.1.0")

        val expected = """
            # keep me
            schema = 1
            name    =    "demo"   # and me

            [java-deps]
            # this comment explains sqlite
            sqlite = "org.xerial:sqlite-jdbc:3.50.1.0"
            bcrypt = "org.mindrot:jbcrypt:0.4"
        """.trimIndent() + "\n"
        assertEquals(expected, doc.render())
    }

    @Test
    fun `editing preserves a trailing comment on the edited line`() {
        val (doc, _) = parse("schema = 1\nname = \"old\"  # why\n")
        doc.setString(null, "name", "new")
        assertEquals("schema = 1\nname = \"new\"  # why\n", doc.render())
    }

    @Test
    fun `adding a key appends to its table`() {
        val text = "schema = 1\nname = \"demo\"\n\n[java-deps]\nsqlite = \"org.xerial:sqlite-jdbc:3.36.0.3\"\n"
        val (doc, _) = parse(text)
        doc.setString("java-deps", "bcrypt", "org.mindrot:jbcrypt:0.4")
        assertEquals(text + "bcrypt = \"org.mindrot:jbcrypt:0.4\"\n", doc.render())
    }

    @Test
    fun `adding a key to an absent table creates the header`() {
        val (doc, _) = parse("schema = 1\nname = \"demo\"\n")
        doc.setString("java-deps", "sqlite", "org.xerial:sqlite-jdbc:3.36.0.3")
        assertEquals(
            "schema = 1\nname = \"demo\"\n\n[java-deps]\nsqlite = \"org.xerial:sqlite-jdbc:3.36.0.3\"\n",
            doc.render(),
        )
    }

    @Test
    fun `removing a key leaves the rest untouched`() {
        val (doc, _) = parse("schema = 1\nname = \"demo\"\n\n[java-deps]\na = \"g:a:1\"\nb = \"g:b:2\"\n")
        assertTrue(doc.remove("java-deps", "a"))
        assertEquals("schema = 1\nname = \"demo\"\n\n[java-deps]\nb = \"g:b:2\"\n", doc.render())
    }

    @Test
    fun `added values are escaped on the way out`() {
        val (doc, _) = parse("schema = 1\n")
        doc.setString(null, "name", "a\"b\\c")
        assertContains(doc.render(), """name = "a\"b\\c"""")
        // and it parses back to the same string
        val (again, sink) = parse(doc.render())
        assertTrue(sink.all.isEmpty())
        assertEquals("a\"b\\c", (again.entry(null, "name")!!.value as TomlStr).value)
    }

    // ---- manifest schema ----

    private fun manifest(dir: File, text: String): Pair<Manifest?, List<String>> {
        val f = File(dir, "dawn.toml")
        f.writeText(text)
        val sink = DiagnosticSink()
        val m = Manifest.parse(f, SourceFile(f.path, text), sink)
        return m to sink.all.map { it.message }
    }

    @Test
    fun `accepts a well-formed manifest`(@TempDir dir: File) {
        val (m, errs) = manifest(
            dir,
            """
            schema = 1
            name = "backend_dawn"

            [java-deps]
            sqlite = "org.xerial:sqlite-jdbc:3.36.0.3"
            bcrypt = "org.mindrot:jbcrypt:0.4"
            """.trimIndent(),
        )
        assertTrue(errs.isEmpty(), "unexpected: $errs")
        assertNotNull(m)
        assertEquals("backend_dawn", m.name)
        assertEquals(2, m.javaDeps.size)
        assertEquals("org.xerial", m.javaDeps[0].group)
        assertEquals("sqlite-jdbc", m.javaDeps[0].artifact)
        assertEquals("3.36.0.3", m.javaDeps[0].version)
        assertEquals("sqlite", m.javaDeps[0].alias)
    }

    @Test
    fun `a manifest with no java-deps is valid`(@TempDir dir: File) {
        val (m, errs) = manifest(dir, "schema = 1\nname = \"demo\"\n")
        assertTrue(errs.isEmpty(), "unexpected: $errs")
        assertEquals(emptyList(), m!!.javaDeps)
    }

    @Test
    fun `schema must be present, first, and known`(@TempDir dir: File) {
        assertContains(manifest(dir, "name = \"x\"\n").second.first(), "no `schema` key")
        assertContains(manifest(dir, "name = \"x\"\nschema = 1\n").second.first(), "must be the first key")
        assertContains(manifest(dir, "schema = 2\nname = \"x\"\n").second.first(), "unsupported dawn.toml schema version 2")
        assertContains(manifest(dir, "schema = 2\nname = \"x\"\n").second.first(), "")
        assertContains(manifest(dir, "schema = \"1\"\nname = \"x\"\n").second.first(), "`schema` must be an integer")
    }

    @Test
    fun `a future schema tells the user to upgrade`(@TempDir dir: File) {
        val f = File(dir, "dawn.toml")
        val text = "schema = 99\nname = \"x\"\n"
        f.writeText(text)
        val sink = DiagnosticSink()
        Manifest.parse(f, SourceFile(f.path, text), sink)
        assertContains(sink.all.first().hint!!, "upgrade dawn")
    }

    @Test
    fun `name is required and must be an identifier`(@TempDir dir: File) {
        assertContains(manifest(dir, "schema = 1\n").second.first(), "no `name` key")
        assertContains(manifest(dir, "schema = 1\nname = \"Bad-Name\"\n").second.first(), "invalid package name")
        assertContains(manifest(dir, "schema = 1\nname = 3\n").second.first(), "`name` must be a string")
    }

    @Test
    fun `unknown keys and tables are rejected`(@TempDir dir: File) {
        assertContains(manifest(dir, "schema = 1\nname = \"x\"\nnope = 1\n").second.first(), "unknown key `nope`")
        assertContains(manifest(dir, "schema = 1\nname = \"x\"\n[nope]\na = \"b\"\n").second.first(), "unknown table `[nope]`")
        // [deps] is legal since 项目 B v1: a path string per alias
        val (m, errs) = manifest(dir, "schema = 1\nname = \"x\"\n[deps]\nweb = \"../web\"\n")
        assertTrue(errs.isEmpty(), errs.joinToString("\n"))
        assertEquals("web", m!!.deps.single().alias)
    }

    // ---- coordinate validation (§A.4): the reproducibility rules ----

    private fun coord(spec: String): Pair<MavenCoord?, List<String>> {
        val sink = DiagnosticSink()
        val c = MavenCoord.parse(spec, "alias", dawn.diag.Span(0, spec.length), sink)
        return c to sink.all.map { it.message }
    }

    @Test
    fun `accepts an exact coordinate`() {
        val (c, errs) = coord("org.xerial:sqlite-jdbc:3.36.0.3")
        assertTrue(errs.isEmpty())
        assertEquals("org.xerial:sqlite-jdbc:3.36.0.3", c.toString())
    }

    @Test
    fun `rejects SNAPSHOT versions`() {
        val (c, errs) = coord("com.example:lib:1.0-SNAPSHOT")
        assertNull(c)
        assertContains(errs.first(), "SNAPSHOT versions are not allowed")
    }

    @Test
    fun `rejects version ranges`() {
        // every range spelling Maven understands must be refused: an upper bound is the
        // thing that would break MVS's tractability later (docs/package-design.md §4.5)
        for (v in listOf("[1.0,2.0)", "[1.0,]", "(,1.0]", "[1.0]", "1.0+", "1.0,2.0")) {
            val (c, errs) = coord("g:a:$v")
            assertNull(c, "should have rejected `$v`")
            assertContains(errs.first(), "version ranges are not allowed")
        }
    }

    @Test
    fun `rejects malformed coordinates`() {
        assertContains(coord("g:a").second.first(), "invalid Maven coordinate")
        assertContains(coord("g:a:v:x").second.first(), "invalid Maven coordinate")
        assertContains(coord("g::1").second.first(), "empty part")
        assertContains(coord("g a:b:1").second.first(), "invalid group")
    }

    @Test
    fun `rejects one artifact declared twice at different versions`(@TempDir dir: File) {
        val (_, errs) = manifest(
            dir,
            """
            schema = 1
            name = "x"

            [java-deps]
            a = "g:lib:1.0"
            b = "g:lib:2.0"
            """.trimIndent(),
        )
        assertContains(errs.first(), "`g:lib` is declared 2 times with different versions")
    }

    @Test
    fun `locate finds a manifest only when it is there`(@TempDir dir: File) {
        assertNull(Manifest.locate(dir))
        File(dir, "dawn.toml").writeText("schema = 1\nname = \"x\"\n")
        assertNotNull(Manifest.locate(dir))
    }
}
