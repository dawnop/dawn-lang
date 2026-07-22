package dawn.check

import dawn.ast.Module
import dawn.ast.UseModuleDecl
import dawn.diag.Diagnostic
import dawn.diag.DiagnosticSink
import dawn.diag.Severity
import dawn.diag.SourceFile
import dawn.diag.Span
import dawn.lex.Lexer
import dawn.manifest.Manifest
import dawn.manifest.PathDep
import dawn.manifest.PkgFetch
import dawn.manifest.PkgFetchError
import dawn.manifest.UrlDep
import dawn.parse.Parser
import java.io.File

/**
 * One loaded module: its dotted path, the JVM class name it will compile to, the
 * source file, and the parsed AST. Parse/lex diagnostics live in [diagnostics].
 */
class ModuleFile(
    val modPath: String,
    val className: String,
    val file: File,
    val source: SourceFile,
    val module: Module,
    val diagnostics: List<Diagnostic>,
    /** the source package this module came from via `[deps]`; null = the project's own tree */
    val pkg: PkgInfo? = null,
)

/**
 * A resolved `[deps]` package: its manifest name, its src/ root, and its own
 * dependencies (alias → package). Packages reached through different consumers
 * but the same directory share one PkgInfo — and one set of loaded modules —
 * so a diamond (app → web → json, app → json) links a single json: exactly the
 * one-version-per-path discipline the coherence rules need (package-design.md §4.5).
 */
class PkgInfo(val name: String, val srcRoot: File, val deps: Map<String, PkgInfo>)

/** A diagnostic paired with the source file it should be rendered against. */
class LocatedDiag(val source: SourceFile, val diag: Diagnostic)

/**
 * Result of resolving a program's module graph (spec §10.5): modules in
 * topological order (dependencies before dependents) plus any loader-level
 * diagnostics (missing files, bad path segments, cycles, duplicate imports).
 */
class ModuleLoadResult(
    val modules: List<ModuleFile>,
    val loadDiagnostics: List<LocatedDiag>,
) {
    val hasErrors: Boolean
        get() = loadDiagnostics.any { it.diag.severity == Severity.ERROR } ||
            modules.any { m -> m.diagnostics.any { it.severity == Severity.ERROR } }
}

/**
 * Resolves the module graph rooted at a project directory or a single file
 * (spec §10.1). Parses each file exactly once, follows `use` edges, detects
 * cycles, and returns modules in dependency order. Never throws on bad input.
 */
object ModuleLoader {

    private val SEGMENT = Regex("^[a-z_][a-z0-9_]*$")

    /** Directory mode: root = <dir>/src, entry = <dir>/src/main.dawn (spec §10.1). */
    fun loadDirectory(dir: File): ModuleLoadResult {
        val root = File(dir, "src")
        val diags = ArrayList<LocatedDiag>()
        if (!root.isDirectory) {
            diags.add(synthetic(dir, "project directory has no `src/` folder (expected ${root.path})",
                "a Dawn project keeps its modules under src/, with entry src/main.dawn"))
            return ModuleLoadResult(emptyList(), diags)
        }
        val main = File(root, "main.dawn")
        // a directory with a manifest may be a library package (no entry module);
        // run/build report the missing `fn main` themselves when it matters
        if (!main.isFile && Manifest.locate(dir) == null) {
            diags.add(synthetic(dir, "project has no entry module (expected ${main.path})",
                "add src/main.dawn with `pub fn main() -> Unit !io`"))
        }
        // load every module under src/ (spec §10.5: unreferenced modules are still checked)
        val allFiles = root.walkTopDown().filter { it.isFile && it.extension == "dawn" }.sortedBy { it.path }
        return resolve(root, allFiles.toList(), diags, pkgs = resolveSrcDeps(dir, diags))
    }

    /**
     * Shared state of one dependency resolution: manifests parsed (and their
     * diagnostics emitted) once, linked packages cached by canonical directory,
     * url packages resolved to one directory per name, and the global
     * one-name-one-directory claim table the coherence rules lean on.
     */
    private class ResolveCtx(val diags: ArrayList<LocatedDiag>) {
        val manifests = HashMap<String, Manifest?>()
        val sources = HashMap<String, SourceFile>()
        val pkgCache = HashMap<String, PkgInfo?>()
        /** package name → chosen root dir; a key mapped to null errored during selection */
        val urlResolved = HashMap<String, File?>()
        /** package name → the canonical dir that owns it (one copy program-wide) */
        val nameDirs = HashMap<String, String>()

        /** hash+subdir keys that already failed to materialize — reported once */
        val fetchFailed = HashSet<String>()

        fun manifest(dir: File): Manifest? {
            val canon = dir.canonicalFile.path
            if (canon in manifests) return manifests[canon]
            val mfFile = Manifest.locate(dir)
            if (mfFile == null) {
                manifests[canon] = null
                return null
            }
            val source = SourceFile(mfFile.path, mfFile.readText())
            sources[canon] = source
            val sink = DiagnosticSink()
            val m = Manifest.parse(mfFile, source, sink)
            for (d in sink.all) diags.add(LocatedDiag(source, d))
            manifests[canon] = m
            return m
        }

        fun source(dir: File): SourceFile =
            sources[dir.canonicalFile.path] ?: SourceFile(File(dir, Manifest.FILENAME).path, "")
    }

    /** `[deps]` → alias → package: select url versions globally, then link. */
    private fun resolveSrcDeps(dir: File, diags: ArrayList<LocatedDiag>): Map<String, PkgInfo> {
        val ctx = ResolveCtx(diags)
        selectUrlDeps(dir, ctx)
        return link(dir, ctx, HashSet())
    }

    /**
     * Minimal Version Selection (package-design.md §4.5, Cox's algorithm R1):
     * walk the whole requirement graph — every (name, version) any reachable
     * manifest mentions, fetching archives as needed to read their manifests —
     * then pick the maximum required version per name. Requirements are minima
     * with no upper bounds or excludes, which is what keeps this a walk instead
     * of a SAT problem. Same version demanded under two different hashes is an
     * integrity error, not a tie to break.
     */
    private fun selectUrlDeps(rootDir: File, ctx: ResolveCtx) {
        val reqs = LinkedHashMap<String, ArrayList<Pair<UrlDep, SourceFile>>>()
        val seen = HashSet<String>()
        val queue = ArrayDeque<File>()
        queue.add(rootDir)
        while (queue.isNotEmpty()) {
            val dir = queue.removeFirst()
            if (!seen.add(dir.canonicalFile.path)) continue
            val mf = ctx.manifest(dir) ?: continue
            for (dep in mf.deps) when (dep) {
                is PathDep -> if (dep.dir.isDirectory) queue.add(dep.dir)
                is UrlDep -> {
                    reqs.getOrPut(dep.alias) { ArrayList() }.add(dep to ctx.source(dir))
                    materialize(dep, ctx.source(dir), ctx)?.let { queue.add(it) }
                }
            }
        }
        for ((name, list) in reqs) {
            val winner = list.maxByOrNull { it.first.version }!!
            val atMax = list.filter { it.first.version == winner.first.version }
            if (atMax.map { it.first.hash }.distinct().size > 1) {
                ctx.diags.add(LocatedDiag(winner.second, Diagnostic(
                    "package `$name` version ${winner.first.version} is required under different hashes",
                    winner.first.span,
                    "the same version must mean the same content everywhere; align the `hash` values")))
                ctx.urlResolved[name] = null
                continue
            }
            val root = materialize(winner.first, winner.second, ctx)
            if (root == null) {
                ctx.urlResolved[name] = null
                continue
            }
            // a fetched manifest that declares its version must agree with the selection
            val mf = ctx.manifest(root)
            if (mf?.version != null && mf.version != winner.first.version) {
                ctx.diags.add(LocatedDiag(winner.second, Diagnostic(
                    "package `$name` declares version ${mf.version} but ${winner.first.version} was selected",
                    winner.first.span,
                    "the archive's dawn.toml disagrees with the requirement; fix the version or the url")))
                ctx.urlResolved[name] = null
                continue
            }
            ctx.urlResolved[name] = root
        }
    }

    /**
     * The package root for a url dep: its cached archive (fetched on miss) +
     * subdir. A hash that failed once fails silently afterwards — a package
     * required from several manifests should report its problem once.
     */
    private fun materialize(dep: UrlDep, source: SourceFile, ctx: ResolveCtx): File? {
        val key = dep.hash + ":" + (dep.subdir ?: "")
        if (key in ctx.fetchFailed) return null
        val archive = try {
            PkgFetch.ensureCached(dep.url, dep.hash)
        } catch (e: PkgFetchError) {
            ctx.fetchFailed.add(key)
            ctx.diags.add(LocatedDiag(source, Diagnostic(e.message!!, dep.span, e.hint)))
            return null
        }
        val root = if (dep.subdir == null) archive else File(archive, dep.subdir)
        if (!root.isDirectory) {
            ctx.fetchFailed.add(key)
            ctx.diags.add(LocatedDiag(source, Diagnostic(
                "subdir `${dep.subdir}` does not exist in the archive for `${dep.alias}`", dep.span, null)))
            return null
        }
        return root
    }

    /**
     * Link `[deps]` recursively (transitive packages resolve their own
     * manifests). Each dependency directory must carry a dawn.toml whose `name`
     * equals the alias; package modules load from its src/ on demand (a library
     * has no entry module and its unused modules are not checked). The
     * canonical-directory cache gives a diamond one PkgInfo; the name-claim
     * table rejects two *different* directories under one package name — the
     * situation MVS exists to prevent, closed off for path deps too.
     * v1 fence: a dependency may not have `[java-deps]` (not merged into the
     * consumer's class path yet).
     */
    private fun link(
        dir: File,
        ctx: ResolveCtx,
        visiting: MutableSet<String>,
    ): Map<String, PkgInfo> {
        val manifest = ctx.manifest(dir) ?: return emptyMap()
        val source = ctx.source(dir)
        val out = LinkedHashMap<String, PkgInfo>()
        for (dep in manifest.deps) {
            val depDir = when (dep) {
                is PathDep -> dep.dir
                is UrlDep -> ctx.urlResolved[dep.alias] ?: continue // selection already errored
            }
            val canon = depDir.canonicalFile.path
            val claimed = ctx.nameDirs[dep.alias]
            if (claimed != null && claimed != canon) {
                ctx.diags.add(LocatedDiag(source, Diagnostic(
                    "package `${dep.alias}` is linked from two different directories", dep.span,
                    "one package name means one copy program-wide (coherence, package-design.md §4.5);\n" +
                        "  here:      $canon\n  elsewhere: $claimed")))
                continue
            }
            if (canon in ctx.pkgCache) {
                val hit = ctx.pkgCache[canon]
                if (hit != null) {
                    if (hit.name != dep.alias) {
                        ctx.diags.add(LocatedDiag(source, Diagnostic(
                            "dependency alias `${dep.alias}` does not match the package's name `${hit.name}`",
                            dep.span, "the alias must equal the package's manifest name; rename one of them")))
                    } else {
                        out[dep.alias] = hit
                    }
                }
                continue
            }
            if (canon in visiting) {
                ctx.diags.add(LocatedDiag(source, Diagnostic(
                    "package dependency cycle through `${dep.alias}`", dep.span,
                    "a package cannot depend on itself, directly or through its dependencies")))
                continue
            }
            val dm = ctx.manifest(depDir)
            if (dm == null) {
                ctx.diags.add(LocatedDiag(source, Diagnostic(
                    "dependency `${dep.alias}` has no dawn.toml (looked in ${depDir.path})", dep.span,
                    "a Dawn source package is a directory with dawn.toml (name = \"${dep.alias}\") and src/")))
                ctx.pkgCache[canon] = null
                continue
            }
            if (dm.name != dep.alias) {
                ctx.diags.add(LocatedDiag(source, Diagnostic(
                    "dependency alias `${dep.alias}` does not match the package's name `${dm.name}`", dep.span,
                    "the alias must equal the package's manifest name; rename one of them")))
                ctx.pkgCache[canon] = null
                continue
            }
            if (dm.javaDeps.isNotEmpty()) {
                ctx.diags.add(LocatedDiag(source, Diagnostic(
                    "package `${dm.name}` has `[java-deps]` — a dependency's jars are not merged yet",
                    dep.span, "declare the jars in the consuming project's [java-deps] for now")))
                ctx.pkgCache[canon] = null
                continue
            }
            val srcRoot = File(depDir, "src")
            if (!srcRoot.isDirectory) {
                ctx.diags.add(LocatedDiag(source, Diagnostic(
                    "package `${dm.name}` has no src/ folder (expected ${srcRoot.path})", dep.span, null)))
                ctx.pkgCache[canon] = null
                continue
            }
            visiting.add(canon)
            val transitive = link(depDir, ctx, visiting)
            visiting.remove(canon)
            val info = PkgInfo(dm.name, srcRoot, transitive)
            ctx.pkgCache[canon] = info
            ctx.nameDirs[dep.alias] = canon
            out[dep.alias] = info
        }
        return out
    }

    /**
     * File mode: root = nearest `src` ancestor of the file, else the file's own
     * directory (spec §10.1). Loads the entry file plus its transitive use-closure.
     * [overrides] (abs path → text) lets an editor supply unsaved buffer content.
     */
    fun loadFile(file: File, overrides: Map<String, String> = emptyMap()): ModuleLoadResult {
        val root = nearestSrcRoot(file)
        val diags = ArrayList<LocatedDiag>()
        val projDir = if (root.name == "src") root.parentFile ?: root else root
        return resolve(root, listOf(file), diags, followUsesOnly = true, overrides = overrides,
            pkgs = resolveSrcDeps(projDir, diags))
    }

    private fun nearestSrcRoot(file: File): File {
        var dir = file.absoluteFile.parentFile
        while (dir != null) {
            if (dir.name == "src") return dir
            dir = dir.parentFile
        }
        return file.absoluteFile.parentFile
    }

    private fun resolve(
        root: File,
        seedFiles: List<File>,
        diags: ArrayList<LocatedDiag>,
        followUsesOnly: Boolean = false,
        overrides: Map<String, String> = emptyMap(),
        pkgs: Map<String, PkgInfo> = emptyMap(),
    ): ModuleLoadResult {
        val byPath = LinkedHashMap<String, ModuleFile>()
        val byFile = HashMap<String, ModuleFile>()

        fun load(file: File, pkg: PkgInfo? = null): ModuleFile? {
            val canon = file.absoluteFile.path
            byFile[canon]?.let { return it }
            val override = overrides[canon]
            if (override == null && !file.isFile) return null
            val text = override ?: file.readText()
            val source = SourceFile(file.path, text)
            val sink = DiagnosticSink()
            val comments = ArrayList<dawn.lex.Token>()
            val tokens = Lexer(text, 0, sink, comments).lex()
            val module = Parser(tokens, sink, text).module()
            val internal = modulePathOf(pkg?.srcRoot ?: root, file)
            val internalCls = internal.split('/').joinToString("/") { sanitizeSegment(it) }
            // A dependency module: modPath gains the package-name prefix (what consumers
            // write), the class name gains dawn$pkg$<name>/ — `$` is illegal in module
            // path segments, so the prefix cannot collide with any user module
            // (docs/package-design.md §4.4). Package-internal `use` paths are written
            // bare and canonicalized here to the qualified spelling, so the checker,
            // duplicate detection and the topological sort all see one spelling.
            val modPath = if (pkg == null) internal else "${pkg.name}/$internal"
            val className = if (pkg == null) internalCls else "dawn\$pkg\$${pkg.name}/$internalCls"
            if (pkg != null) {
                // a sibling import gains the package's own name; an import whose
                // first segment names one of the package's own deps is already
                // canonical (the alias equals that package's name)
                for (u in module.moduleUses) {
                    val first = u.segments.first()
                    if (first != "std" && first !in pkg.deps) u.segments = listOf(pkg.name) + u.segments
                }
            }
            val mf = ModuleFile(modPath, className, file, source, module, sink.all, pkg)
            byFile[canon] = mf
            byPath[modPath] = mf
            return mf
        }

        // 1. load seed files (directory mode gives all of src/; file mode gives the entry)
        val queue = ArrayDeque<ModuleFile>()
        for (f in seedFiles) load(f)?.let { queue.add(it) }
        if (!followUsesOnly) queue.addAll(byPath.values)

        // 2. follow use edges, loading dependencies on demand
        val visited = HashSet<String>()
        while (queue.isNotEmpty()) {
            val mf = queue.removeFirst()
            if (!visited.add(mf.modPath)) continue
            for (u in mf.module.moduleUses) {
                val bad = u.segments.firstOrNull { !SEGMENT.matches(it) }
                if (bad != null) {
                    diags.add(LocatedDiag(mf.source, Diagnostic(
                        "invalid module path segment `$bad`", u.nameSpan,
                        "path segments are lowercase identifiers: [a-z_][a-z0-9_]*")))
                    continue
                }
                // bundled std modules come from the compiler jar, not the module graph
                // (spec §10.6); the checker validates the name, in both build modes
                if (u.segments.first() == "std") continue
                val first = u.segments.first()
                val (depFile, depPkg) = when {
                    // a dependency module importing one of its own deps
                    mf.pkg != null && first in mf.pkg.deps -> {
                        val info = mf.pkg.deps[first]!!
                        File(info.srcRoot, u.segments.drop(1).joinToString("/") + ".dawn") to info
                    }
                    // a dependency module importing a sibling: paths were canonicalized
                    // to `<pkgname>/<internal>` at load time, resolve inside the package
                    mf.pkg != null ->
                        File(mf.pkg.srcRoot, u.segments.drop(1).joinToString("/") + ".dawn") to mf.pkg
                    // `use <alias>/...`: the [deps] package, unless a local directory
                    // claims the same first segment — never shadow silently (§4.3)
                    first in pkgs -> {
                        val local = File(root, u.segments.joinToString("/") + ".dawn")
                        if (local.isFile) {
                            diags.add(LocatedDiag(mf.source, Diagnostic(
                                "`${u.path}` is ambiguous: `$first` is both a [deps] package and a local module path",
                                u.nameSpan, "rename the src/$first/ directory or the dependency alias")))
                            continue
                        }
                        if (u.segments.size == 1) {
                            diags.add(LocatedDiag(mf.source, Diagnostic(
                                "cannot import the package `$first` itself", u.nameSpan,
                                "import one of its modules: `use $first/<module>`")))
                            continue
                        }
                        File(pkgs[first]!!.srcRoot, u.segments.drop(1).joinToString("/") + ".dawn") to pkgs[first]
                    }
                    else -> File(root, u.segments.joinToString("/") + ".dawn") to null
                }
                val dep = load(depFile, depPkg)
                if (dep == null) {
                    diags.add(LocatedDiag(mf.source, Diagnostic(
                        "cannot find module `${u.path}`", u.nameSpan,
                        "expected a file at ${depFile.path}")))
                } else {
                    queue.add(dep)
                }
            }
        }

        // 2.5. the std/ path prefix belongs to the bundled standard library (spec §10.6)
        for (mf in byPath.values) {
            if (mf.modPath == "std" || mf.modPath.startsWith("std/"))
                diags.add(LocatedDiag(mf.source, Diagnostic(
                    "the module path `${mf.modPath}` is reserved for the bundled standard library",
                    Span(0, 0), "move the file out of src/std")))
        }

        // 3. duplicate-import detection (same module used twice in one file, spec §10.2)
        for (mf in byPath.values) {
            val seen = HashMap<String, UseModuleDecl>()
            for (u in mf.module.moduleUses) {
                if (u.segments.any { !SEGMENT.matches(it) }) continue
                val prev = seen.put(u.path, u)
                if (prev != null)
                    diags.add(LocatedDiag(mf.source, Diagnostic(
                        "module `${u.path}` is imported more than once", u.nameSpan)))
            }
        }

        // 4. topological order + cycle detection over the use graph
        val ordered = topoSort(root, byPath, diags)
        return ModuleLoadResult(ordered, diags)
    }

    /** Depth-first topological sort; on a back edge, report the cycle path. */
    private fun topoSort(
        root: File,
        byPath: Map<String, ModuleFile>,
        diags: ArrayList<LocatedDiag>,
    ): List<ModuleFile> {
        val order = ArrayList<ModuleFile>()
        val state = HashMap<String, Int>() // 0 = visiting, 1 = done
        var cycleReported = false

        fun edgesOf(mf: ModuleFile): List<String> =
            mf.module.moduleUses.map { it.path }.filter { byPath.containsKey(it) }

        fun visit(path: String, stack: ArrayList<String>) {
            when (state[path]) {
                1 -> return
                0 -> {
                    if (!cycleReported) {
                        val start = stack.indexOf(path)
                        val loop = stack.subList(start, stack.size) + path
                        val mf = byPath[stack[start]]!!
                        val use = mf.module.moduleUses.first { it.path == loop[1] }
                        diags.add(LocatedDiag(mf.source, Diagnostic(
                            "circular module dependency: ${loop.joinToString(" → ")}", use.nameSpan,
                            "modules must form a directed acyclic graph (spec §10.5)")))
                        cycleReported = true
                    }
                    return
                }
            }
            state[path] = 0
            stack.add(path)
            for (dep in edgesOf(byPath[path]!!)) visit(dep, stack)
            stack.removeAt(stack.size - 1)
            state[path] = 1
            order.add(byPath[path]!!)
        }

        for (path in byPath.keys) visit(path, ArrayList())
        return order
    }

    /** module path = file path relative to root, minus extension, '/'-separated. */
    private fun modulePathOf(root: File, file: File): String {
        val rel = file.absoluteFile.relativeToOrNull(root.absoluteFile)?.path ?: file.name
        return rel.removeSuffix(".dawn").replace(File.separatorChar, '/')
    }

    private fun sanitizeSegment(seg: String): String {
        val cleaned = seg.map { if (it.isLetterOrDigit() || it == '_') it else '_' }.joinToString("")
        return if (cleaned.isEmpty() || cleaned[0].isDigit()) "m_$cleaned" else cleaned
    }

    private fun synthetic(near: File, msg: String, hint: String?): LocatedDiag {
        val src = SourceFile(near.path, "")
        return LocatedDiag(src, Diagnostic(msg, Span(0, 0), hint))
    }
}
