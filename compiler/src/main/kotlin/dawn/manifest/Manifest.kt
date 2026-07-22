package dawn.manifest

import dawn.diag.Diagnostic
import dawn.diag.DiagnosticSink
import dawn.diag.Severity
import dawn.diag.SourceFile
import dawn.diag.Span
import java.io.File

/**
 * `dawn.toml` — a project's identity and its dependencies (docs/package-design.md §4.1).
 *
 * The manifest is optional: a project without one keeps working exactly as before
 * (directory convention alone defines it, spec §10.1). It only carries what the
 * directory layout cannot express.
 *
 * The manifest is data, never code. See docs/package-design.md §6.1 — PEP 518's
 * deadlock ("you can't execute setup.py without knowing its dependencies, and you
 * can't know its dependencies without executing setup.py") is the thing this rule
 * exists to avoid, and Python has not escaped it in ten years.
 */
class Manifest(
    val name: String,
    val javaDeps: List<MavenCoord>,
    val deps: List<SrcDep>,
    val file: File,
) {
    companion object {
        const val FILENAME = "dawn.toml"

        /** The only schema this compiler understands. Bump when the format changes. */
        const val SCHEMA = 1L

        private val NAME = Regex("^[a-z_][a-z0-9_]*$")

        /** The manifest for a project directory, or null when there is none. */
        fun locate(dir: File): File? = File(dir, FILENAME).takeIf { it.isFile }

        /**
         * Parse and validate. Returns null if anything was wrong; diagnostics land in
         * [sink] and the caller renders them against [source].
         */
        fun parse(file: File, source: SourceFile, sink: DiagnosticSink): Manifest? {
            val doc = TomlParser.parse(source, sink)
            val before = sink.all.size
            val m = validate(doc, file, sink)
            return if (sink.all.size > before || sink.hasErrors) null else m
        }

        private fun validate(doc: TomlDoc, file: File, sink: DiagnosticSink): Manifest? {
            val root = doc.table(null)

            // `schema` first: a tool must be able to tell the format version by reading
            // line 1, before it understands anything else. This is the one lever that
            // makes an otherwise irreversible format decision reversible (§6.2), so the
            // position is enforced, not merely conventional.
            val schema = root.firstOrNull { it.key == "schema" }
            if (schema == null) {
                sink.error("dawn.toml has no `schema` key", Span(0, 1),
                    "start the file with `schema = $SCHEMA`")
                return null
            }
            if (root.first() !== schema) {
                sink.error("`schema` must be the first key in dawn.toml", schema.keySpan,
                    "move `schema = $SCHEMA` to the top so tools can read the format version first")
                return null
            }
            val schemaVal = schema.value
            if (schemaVal !is TomlInt) {
                sink.error("`schema` must be an integer", schemaVal.span, "write `schema = $SCHEMA`")
                return null
            }
            if (schemaVal.value != SCHEMA) {
                sink.error("unsupported dawn.toml schema version ${schemaVal.value}", schemaVal.span,
                    if (schemaVal.value > SCHEMA) "this dawn only understands schema $SCHEMA; upgrade dawn"
                    else "this dawn only understands schema $SCHEMA")
                return null
            }

            var name: String? = null
            for (e in root) {
                when (e.key) {
                    "schema" -> {}
                    "name" -> {
                        val v = e.value
                        if (v !is TomlStr) {
                            sink.error("`name` must be a string", v.span, "write `name = \"my_project\"`")
                            continue
                        }
                        if (!NAME.matches(v.value)) {
                            sink.error("invalid package name `${v.value}`", v.span,
                                "names are lowercase identifiers: [a-z_][a-z0-9_]*")
                            continue
                        }
                        name = v.value
                    }
                    else -> sink.error("unknown key `${e.key}` in dawn.toml", e.keySpan,
                        "dawn.toml schema $SCHEMA has `schema`, `name`, and the `[java-deps]`/`[deps]` tables")
                }
            }
            if (name == null) {
                sink.error("dawn.toml has no `name` key", Span(0, 1),
                    "add `name = \"${file.parentFile?.name?.replace('-', '_') ?: "my_project"}\"`")
                return null
            }

            for (t in doc.tableNames().distinct()) {
                if (t != "java-deps" && t != "deps")
                    sink.error("unknown table `[$t]` in dawn.toml", doc.header(t)!!.nameSpan,
                        "dawn.toml schema $SCHEMA has `[java-deps]` and `[deps]`")
            }

            // [deps]: Dawn source packages (docs/package-design.md 项目 B). v1 takes a
            // local path string per alias; the url+hash form arrives with versioning.
            val srcDeps = ArrayList<SrcDep>()
            for (e in doc.table("deps")) {
                val v = e.value
                if (v !is TomlStr) {
                    sink.error("`${e.key}` must be a path string", v.span,
                        "write `${e.key} = \"../packages/${e.key}\"` (a directory containing dawn.toml + src/)")
                    continue
                }
                if (!NAME.matches(e.key)) {
                    sink.error("invalid dependency alias `${e.key}`", e.keySpan,
                        "aliases are lowercase identifiers: [a-z_][a-z0-9_]*")
                    continue
                }
                if (srcDeps.any { it.alias == e.key }) {
                    sink.error("dependency `${e.key}` is declared twice", e.keySpan, null)
                    continue
                }
                val dir = File(v.value).let { if (it.isAbsolute) it else File(file.parentFile, v.value) }
                srcDeps.add(SrcDep(e.key, dir, v.span))
            }

            val deps = ArrayList<MavenCoord>()
            for (e in doc.table("java-deps")) {
                val v = e.value
                if (v !is TomlStr) {
                    sink.error("`${e.key}` must be a Maven coordinate string", v.span,
                        "write `${e.key} = \"group:artifact:version\"`")
                    continue
                }
                MavenCoord.parse(v.value, e.key, v.span, sink)?.let { deps.add(it) }
            }

            val byCoord = deps.groupBy { "${it.group}:${it.artifact}" }
            for ((ga, group) in byCoord) {
                if (group.size > 1)
                    sink.error("`$ga` is declared ${group.size} times with different versions",
                        doc.entry("java-deps", group[1].alias)!!.value.span,
                        "one version per artifact; drop all but one")
            }

            return Manifest(name, deps, srcDeps, file)
        }
    }
}

/**
 * A `[deps]` entry: a Dawn source package at a local directory (its dawn.toml +
 * src/ tree). The alias must equal the package's own manifest name — the alias
 * IS the namespace consumers write (`use <alias>/<module>`), and letting it
 * drift from the package identity would make one package compile under two
 * names (docs/package-design.md §4.3 keeps aliasing as future local sugar).
 */
class SrcDep(val alias: String, val dir: File, val span: Span)

/**
 * An exact Maven coordinate. Ranges and SNAPSHOTs are rejected: with exact versions
 * and Maven Central's immutable releases, resolution is reproducible without a
 * lockfile (docs/package-design.md §4.6). Banning upper bounds is the same discipline
 * MVS needs (§4.5) — the two rules are the same rule.
 */
class MavenCoord(val group: String, val artifact: String, val version: String, val alias: String) {

    override fun toString() = "$group:$artifact:$version"

    companion object {
        private val SEGMENT = Regex("^[A-Za-z0-9_.-]+$")
        private val RANGE_CHARS = charArrayOf('[', ']', '(', ')', ',', '+')

        fun parse(spec: String, alias: String, span: Span, sink: DiagnosticSink): MavenCoord? {
            val parts = spec.split(":")
            if (parts.size != 3) {
                sink.error("invalid Maven coordinate `$spec`", span,
                    "use exactly three parts: `group:artifact:version`, e.g. `org.xerial:sqlite-jdbc:3.36.0.3`")
                return null
            }
            val (g, a, v) = parts
            if (g.isEmpty() || a.isEmpty() || v.isEmpty()) {
                sink.error("invalid Maven coordinate `$spec`: empty part", span,
                    "use `group:artifact:version`, e.g. `org.xerial:sqlite-jdbc:3.36.0.3`")
                return null
            }
            for ((label, part) in listOf("group" to g, "artifact" to a)) {
                if (!SEGMENT.matches(part)) {
                    sink.error("invalid $label `$part` in `$spec`", span,
                        "$label may hold letters, digits, `.`, `-`, `_`")
                    return null
                }
            }
            if (v.endsWith("-SNAPSHOT")) {
                sink.error("SNAPSHOT versions are not allowed: `$spec`", span,
                    "SNAPSHOTs change under the same coordinate, so builds stop being reproducible; " +
                        "pin a release version")
                return null
            }
            val bad = v.firstOrNull { it in RANGE_CHARS }
            if (bad != null) {
                sink.error("version ranges are not allowed: `$spec`", span,
                    "dawn.toml takes one exact version so builds are reproducible without a lockfile; " +
                        "write the version you want, e.g. `3.36.0.3`")
                return null
            }
            if (!SEGMENT.matches(v)) {
                sink.error("invalid version `$v` in `$spec`", span,
                    "versions may hold letters, digits, `.`, `-`, `_`")
                return null
            }
            return MavenCoord(g, a, v, alias)
        }
    }
}

/** Renders manifest diagnostics the same way compile errors are rendered. */
fun renderManifestDiagnostics(source: SourceFile, diags: List<Diagnostic>): String =
    diags.joinToString("") { it.render(source) } +
        diags.count { it.severity == Severity.ERROR }.let { if (it == 1) "1 error\n" else "$it errors\n" }
