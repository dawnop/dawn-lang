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
    val version: SemVer?,
    val javaDeps: List<MavenCoord>,
    val deps: List<SrcDep>,
    val file: File,
) {
    companion object {
        const val FILENAME = "dawn.toml"

        /** The only schema this compiler understands. Bump when the format changes. */
        const val SCHEMA = 1L

        private val NAME = Regex("^[a-z_][a-z0-9_]*$")

        /** `d1:` marks the hash format version (schema-in-the-string, §6.2). */
        private val HASH = Regex("^d1:[0-9a-f]{64}$")

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
            var version: SemVer? = null
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
                    "version" -> {
                        val v = e.value
                        if (v !is TomlStr) {
                            sink.error("`version` must be a string", v.span, "write `version = \"1.0.0\"`")
                            continue
                        }
                        version = SemVer.parse(v.value)
                        if (version == null)
                            sink.error("invalid version `${v.value}`", v.span,
                                "versions are exactly `major.minor.patch` decimal numbers, e.g. `1.0.0`; " +
                                    "no prerelease or build suffixes (the same discipline that bans SNAPSHOTs)")
                    }
                    else -> sink.error("unknown key `${e.key}` in dawn.toml", e.keySpan,
                        "dawn.toml schema $SCHEMA has `schema`, `name`, `version`, " +
                            "and the `[java-deps]`/`[deps]` tables")
                }
            }
            if (name == null) {
                sink.error("dawn.toml has no `name` key", Span(0, 1),
                    "add `name = \"${file.parentFile?.name?.replace('-', '_') ?: "my_project"}\"`")
                return null
            }
            if (version != null) checkV2Name(name, version, root.first { it.key == "version" }.value.span, sink)

            for (t in doc.tableNames().distinct()) {
                if (t != "java-deps" && t != "deps" && !t.startsWith("deps."))
                    sink.error("unknown table `[$t]` in dawn.toml", doc.header(t)!!.nameSpan,
                        "dawn.toml schema $SCHEMA has `[java-deps]`, `[deps]` and `[deps.<alias>]`")
            }

            // [deps]: Dawn source packages (docs/package-design.md 项目 B). A path string
            // per alias links a local directory; a `[deps.<alias>]` sub-table pins a
            // remote archive by url + version + content hash (§4.5, MVS over versions).
            val srcDeps = ArrayList<SrcDep>()
            for (e in doc.table("deps")) {
                val v = e.value
                if (v !is TomlStr) {
                    sink.error("`${e.key}` must be a path string", v.span,
                        "write `${e.key} = \"../packages/${e.key}\"` (a directory containing dawn.toml + src/), " +
                            "or use a `[deps.${e.key}]` table for a remote package")
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
                srcDeps.add(PathDep(e.key, dir, v.span))
            }
            for (t in doc.tableNames().distinct()) {
                if (!t.startsWith("deps.")) continue
                val alias = t.removePrefix("deps.")
                val span = doc.header(t)!!.nameSpan
                if (!NAME.matches(alias)) {
                    sink.error("invalid dependency alias `$alias`", span,
                        "aliases are lowercase identifiers: [a-z_][a-z0-9_]*")
                    continue
                }
                if (srcDeps.any { it.alias == alias }) {
                    sink.error("dependency `$alias` is declared twice", span,
                        "it already has a path entry under `[deps]`; keep one form")
                    continue
                }
                parseUrlDep(doc, t, alias, span, sink)?.let { srcDeps.add(it) }
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

            return Manifest(name, version, deps, srcDeps, file)
        }

        /** One `[deps.<alias>]` sub-table → a UrlDep, or null with diagnostics. */
        private fun parseUrlDep(
            doc: TomlDoc,
            table: String,
            alias: String,
            span: Span,
            sink: DiagnosticSink,
        ): UrlDep? {
            var url: String? = null
            var version: SemVer? = null
            var hash: String? = null
            var subdir: String? = null
            var bad = false
            for (e in doc.table(table)) {
                val v = e.value
                if (v !is TomlStr) {
                    sink.error("`${e.key}` must be a string", v.span, null)
                    bad = true
                    continue
                }
                when (e.key) {
                    "url" -> {
                        if (listOf("https://", "http://", "file://").none { v.value.startsWith(it) }) {
                            sink.error("unsupported url `${v.value}`", v.span,
                                "https://, http:// and file:// are supported; the archive must be a .zip or .tar.gz")
                            bad = true
                        } else url = v.value
                    }
                    "version" -> {
                        version = SemVer.parse(v.value)
                        if (version == null) {
                            sink.error("invalid version `${v.value}`", v.span,
                                "versions are exactly `major.minor.patch` decimal numbers, e.g. `1.0.0`")
                            bad = true
                        }
                    }
                    "hash" -> {
                        if (!HASH.matches(v.value)) {
                            sink.error("invalid hash `${v.value}`", v.span,
                                "hashes are `d1:` + 64 hex digits — the d1 canonical tree hash; " +
                                    "`dawn __pkghash <dir>` prints one, and a mismatch error shows the actual value")
                            bad = true
                        } else hash = v.value
                    }
                    "subdir" -> {
                        val s = v.value
                        if (s.startsWith("/") || s.split('/').any { it == ".." || it.isEmpty() }) {
                            sink.error("invalid subdir `$s`", v.span,
                                "a relative path inside the archive, no `..`, e.g. `packages/web`")
                            bad = true
                        } else subdir = s
                    }
                    else -> {
                        sink.error("unknown key `${e.key}` in `[deps.$alias]`", e.keySpan,
                            "a remote dependency has `url`, `version`, `hash` and optional `subdir`")
                        bad = true
                    }
                }
            }
            for ((k, present) in listOf("url" to (url != null), "version" to (version != null), "hash" to (hash != null))) {
                if (!present) {
                    sink.error("`[deps.$alias]` is missing `$k`", span,
                        "a remote dependency needs `url`, `version` and `hash`")
                    bad = true
                }
            }
            if (bad) return null
            // no v2-name check against the alias here: the alias is only the
            // consumer's local spelling — the check runs at selection time
            // against the package's real manifest name (ModuleLoader)
            return UrlDep(alias, version!!, url!!, hash!!, subdir, span)
        }

        /**
         * v2 = new name (docs/package-design.md §6.3): a major bump is a new package,
         * spelled into the name so MVS can never hand v2 to a v1 consumer. Enforced
         * from day zero because it is free now and impossible later.
         */
        private fun checkV2Name(name: String, version: SemVer, span: Span, sink: DiagnosticSink) {
            if (version.major >= 2 && !name.endsWith(version.major.toString()))
                sink.error("version $version needs the major in the package name", span,
                    "v2+ is a new package with a new name (`${name}${version.major}`): " +
                        "otherwise version selection would hand incompatible majors to old consumers")
        }
    }
}

/** A strict `major.minor.patch` version. No prerelease, no build metadata, no ranges. */
class SemVer(val major: Int, val minor: Int, val patch: Int) : Comparable<SemVer> {
    override fun compareTo(other: SemVer): Int =
        compareValuesBy(this, other, { it.major }, { it.minor }, { it.patch })

    override fun equals(other: Any?) = other is SemVer && compareTo(other) == 0
    override fun hashCode() = major * 31 * 31 + minor * 31 + patch
    override fun toString() = "$major.$minor.$patch"

    companion object {
        private val RE = Regex("^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$")
        fun parse(s: String): SemVer? {
            val m = RE.matchEntire(s) ?: return null
            val (a, b, c) = m.destructured
            return SemVer(a.toInt(), b.toInt(), c.toInt())
        }
    }
}

/**
 * A `[deps]` entry: a Dawn source package. The alias is the consumer's local
 * spelling (`use <alias>/<module>`); the package's identity — its class-name
 * namespace, the MVS grouping key, the one-copy-program-wide claim — is the
 * `name` its own manifest declares (docs/package-design.md §4.3/§4.4: the name
 * is the identity, the alias is local sugar). The loader canonicalizes aliased
 * imports to the real name, so one package never compiles under two names.
 */
sealed class SrcDep(val alias: String, val span: Span)

/** A local directory (its dawn.toml + src/ tree). */
class PathDep(alias: String, val dir: File, span: Span) : SrcDep(alias, span)

/**
 * A remote archive pinned by url + version + content hash. The hash is the
 * identity, the url is only where to look (Zig's lesson, package-design.md
 * 调研依据): fetched bytes are unpacked, tree-hashed and verified before use,
 * and the cache is addressed by hash, so a moved or re-tarred url cannot
 * change what a build sees. [subdir] points at the package root inside the
 * archive, letting one archive (a monorepo tag) serve several packages.
 */
class UrlDep(
    alias: String,
    val version: SemVer,
    val url: String,
    val hash: String,
    val subdir: String?,
    span: Span,
) : SrcDep(alias, span)

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
