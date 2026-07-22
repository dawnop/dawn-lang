package dawn.cli

import dawn.diag.DiagnosticSink
import dawn.diag.SourceFile
import dawn.diag.Span
import dawn.manifest.Manifest
import dawn.manifest.MavenCoord
import dawn.manifest.PkgFetch
import dawn.manifest.PkgFetchError
import dawn.manifest.TomlParser
import dawn.manifest.renderManifestDiagnostics
import java.io.File

/**
 * `dawn add <spec>` — edit dawn.toml in place, preserving comments, spacing and
 * key order (the format-preserving TOML CST exists for exactly this). Three
 * spec shapes, told apart by their syntax:
 *
 *  - `group:artifact:version`  → a `[java-deps]` entry keyed by the artifact
 *  - an archive url            → a `[deps.<name>]` table; the archive is fetched,
 *                                d1-hashed and read for its name and version, so
 *                                the user never computes a hash by hand
 *  - a local directory         → a `[deps]` path entry
 *
 * Adding a spec whose key already exists updates it in place — `dawn add` is
 * also how a dependency is bumped. `--as` picks a different alias (local sugar,
 * package-design.md §4.3); `--subdir` points at a package root inside the
 * archive; `--dir` names the project (default: the current directory).
 */
fun cmdAdd(rest: List<String>) {
    var spec: String? = null
    var subdir: String? = null
    var alias: String? = null
    var dir = "."
    var i = 0
    fun value(flag: String): String {
        if (i + 1 >= rest.size) throw CliError("$flag needs a value")
        i += 2
        return rest[i - 1]
    }
    while (i < rest.size) {
        when (val a = rest[i]) {
            "--subdir" -> subdir = value(a)
            "--as" -> alias = value(a)
            "--dir" -> dir = value(a)
            else -> {
                if (a.startsWith("-") || spec != null)
                    throw CliError("usage: dawn add <spec> [--subdir <p>] [--as <alias>] [--dir <project>]")
                spec = a
                i++
            }
        }
    }
    println(addDependency(File(dir), spec
        ?: throw CliError("usage: dawn add <spec> [--subdir <p>] [--as <alias>] [--dir <project>]"),
        subdir, alias))
}

/** The edit itself, separated from flag parsing so tests can call it directly. */
fun addDependency(projectDir: File, spec: String, subdir: String?, alias: String?): String {
    val mfFile = File(projectDir, Manifest.FILENAME)
    if (!mfFile.isFile)
        throw CliError("no ${Manifest.FILENAME} in ${projectDir.path}; " +
            "start one with `schema = 1` and `name = \"...\"` first")
    val source = SourceFile(mfFile.path, mfFile.readText())
    val sink = DiagnosticSink()
    val doc = TomlParser.parse(source, sink)
    if (Manifest.parse(mfFile, source, sink) == null || sink.hasErrors)
        throw CliError("${mfFile.path} does not validate; fix it first:\n" +
            renderManifestDiagnostics(source, sink.all).trimEnd())

    val summary = when {
        "://" in spec -> {
            if (subdir != null && (subdir.startsWith("/") || subdir.split('/').any { it == ".." || it.isEmpty() }))
                throw CliError("invalid subdir `$subdir`: a relative path inside the archive, no `..`")
            val (entry, hash) = try {
                PkgFetch.fetchAndHash(spec)
            } catch (e: PkgFetchError) {
                throw CliError(e.message!! + (e.hint?.let { "\n  $it" } ?: ""))
            }
            val root = if (subdir == null) entry else File(entry, subdir)
            if (!root.isDirectory) throw CliError("subdir `$subdir` does not exist in the archive")
            val pm = readPackageManifest(root)
            val version = pm.version
                ?: throw CliError("the package's dawn.toml declares no `version`; " +
                    "it needs one before it can be added by url")
            val key = alias ?: pm.name
            doc.remove("deps", key) // a path entry under the same alias gives way
            doc.setString("deps.$key", "url", spec)
            doc.setString("deps.$key", "version", version.toString())
            doc.setString("deps.$key", "hash", hash)
            if (subdir != null) doc.setString("deps.$key", "subdir", subdir)
            else doc.remove("deps.$key", "subdir")
            "added ${pm.name} $version as `$key` ($hash)"
        }
        ":" in spec -> {
            val coordSink = DiagnosticSink()
            val coord = MavenCoord.parse(spec, "cli", Span(0, spec.length), coordSink)
                ?: throw CliError(coordSink.all.joinToString("\n") { it.message })
            val key = alias ?: coord.artifact.replace('.', '-')
            doc.setString("java-deps", key, spec)
            "added $coord as `$key` under [java-deps]"
        }
        else -> {
            val pkgDir = File(spec).let { if (it.isAbsolute) it else File(projectDir, spec) }
            val pm = readPackageManifest(pkgDir)
            val key = alias ?: pm.name
            doc.removeTable("deps.$key") // a url table under the same alias gives way
            doc.setString("deps", key, spec)
            "added ${pm.name} as `$key` (path ${pkgDir.path})"
        }
    }

    // the edited document must itself validate; anything else is a bug here
    val edited = doc.render()
    val checkSink = DiagnosticSink()
    val checkSource = SourceFile(mfFile.path, edited)
    if (Manifest.parse(mfFile, checkSource, checkSink) == null || checkSink.hasErrors)
        throw CliError("internal: the edited manifest does not validate:\n" +
            renderManifestDiagnostics(checkSource, checkSink.all).trimEnd())
    mfFile.writeText(edited)
    return summary
}

private fun readPackageManifest(dir: File): Manifest {
    val file = Manifest.locate(dir)
        ?: throw CliError("no ${Manifest.FILENAME} in ${dir.path}: not a Dawn package")
    val source = SourceFile(file.path, file.readText())
    val sink = DiagnosticSink()
    return Manifest.parse(file, source, sink)
        ?: throw CliError("${file.path} does not validate:\n" +
            renderManifestDiagnostics(source, sink.all).trimEnd())
}
