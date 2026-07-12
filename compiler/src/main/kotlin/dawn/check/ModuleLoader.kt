package dawn.check

import dawn.ast.Module
import dawn.ast.UseModuleDecl
import dawn.diag.Diagnostic
import dawn.diag.DiagnosticSink
import dawn.diag.Severity
import dawn.diag.SourceFile
import dawn.diag.Span
import dawn.lex.Lexer
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
)

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
        if (!main.isFile) {
            diags.add(synthetic(dir, "project has no entry module (expected ${main.path})",
                "add src/main.dawn with `pub fn main() -> Unit !io`"))
        }
        // load every module under src/ (spec §10.5: unreferenced modules are still checked)
        val allFiles = root.walkTopDown().filter { it.isFile && it.extension == "dawn" }.sortedBy { it.path }
        return resolve(root, allFiles.toList(), diags)
    }

    /**
     * File mode: root = nearest `src` ancestor of the file, else the file's own
     * directory (spec §10.1). Loads the entry file plus its transitive use-closure.
     * [overrides] (abs path → text) lets an editor supply unsaved buffer content.
     */
    fun loadFile(file: File, overrides: Map<String, String> = emptyMap()): ModuleLoadResult {
        val root = nearestSrcRoot(file)
        return resolve(root, listOf(file), ArrayList(), followUsesOnly = true, overrides = overrides)
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
    ): ModuleLoadResult {
        val byPath = LinkedHashMap<String, ModuleFile>()
        val byFile = HashMap<String, ModuleFile>()

        fun load(file: File): ModuleFile? {
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
            val modPath = modulePathOf(root, file)
            val className = modPath.split('/').joinToString("/") { sanitizeSegment(it) }
            val mf = ModuleFile(modPath, className, file, source, module, sink.all)
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
                val depFile = File(root, u.segments.joinToString("/") + ".dawn")
                val dep = load(depFile)
                if (dep == null) {
                    diags.add(LocatedDiag(mf.source, Diagnostic(
                        "cannot find module `${u.path}`", u.nameSpan,
                        "expected a file at ${depFile.path}")))
                } else {
                    queue.add(dep)
                }
            }
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
