package dawn.check

import dawn.ast.Module
import dawn.diag.Diagnostic
import dawn.diag.DiagnosticSink
import dawn.diag.Severity
import dawn.diag.SourceFile
import dawn.lex.Lexer
import dawn.parse.Parser
import java.io.File

/**
 * The result of analyzing one source file. The AST is always present (possibly
 * partial after parse-error recovery) and carries type/symbol annotations, so
 * IDE features keep working even when the file has errors.
 */
class Analyzed(
    val module: Module,
    val diagnostics: List<Diagnostic>,
    /** user-defined functions by name */
    val functions: Map<String, FnSig>,
    /** user-defined types by name */
    val types: Map<String, AdtInfo>,
) {
    val hasErrors: Boolean get() = diagnostics.any { it.severity == dawn.diag.Severity.ERROR }
}

/**
 * Single front-end entry point shared by the CLI and the language server:
 * lex → parse (with recovery) → type/effect check (with recovery).
 * Never throws on bad input; all problems land in [Analyzed.diagnostics].
 */
fun analyze(source: String, comptimeFuel: Long = 100_000_000L): Analyzed {
    val sink = DiagnosticSink()
    val tokens = Lexer(source, 0, sink).lex()
    val module = Parser(tokens, sink, source).module()
    val checker = Checker(module, sink)
    checker.check()
    // comptime evaluation only makes sense on a well-typed module
    if (sink.all.none { it.severity == dawn.diag.Severity.ERROR }) {
        evalComptime(module, sink, comptimeFuel)
    }
    return Analyzed(module, sink.all, checker.functions, checker.types)
}

/** One checked module inside a program (spec §10). */
class CheckedModule(
    val modPath: String,
    val className: String,
    val source: SourceFile,
    val module: Module,
    val functions: Map<String, FnSig>,
    val types: Map<String, AdtInfo>,
)

/**
 * The pub surface of a module, consumed by importers (spec §10.4). Also carries
 * every top-level name so an importer can tell "private" apart from "unknown".
 */
class ModuleExports(
    val modPath: String,
    val className: String,
    val fns: Map<String, FnSig>,
    val types: Map<String, AdtInfo>,
    val ctors: Map<String, CtorInfo>,
    val consts: Map<String, dawn.ast.ConstDecl>,
    val allNames: Set<String>,
)

/**
 * Everything an importer sees: whole-module aliases (spec §10.2) resolve to a
 * module's exports; the raw exports map lets the checker resolve selective imports
 * and report missing modules.
 */
class ImportEnv(
    /** modPath → exports, for every module checked before this one */
    val available: Map<String, ModuleExports>,
) {
    companion object {
        val EMPTY = ImportEnv(emptyMap())
    }
}

private fun exportsOf(cm: CheckedModule): ModuleExports {
    val m = cm.module
    val pubTypes = m.types.filter { it.pub }.mapNotNull { cm.types[it.name] }.associateBy { it.name }
    val pubCtors = pubTypes.values.flatMap { it.ctors }.associateBy { it.name }
    val pubFns = m.fns.filter { it.pub }.mapNotNull { cm.functions[it.name] }.associateBy { it.name }
    val pubConsts = m.consts.filter { it.pub }.associateBy { it.name }
    val allNames = (m.fns.map { it.name } + m.types.map { it.name } + m.consts.map { it.name }).toSet()
    return ModuleExports(cm.modPath, cm.className, pubFns, pubTypes, pubCtors, pubConsts, allNames)
}

/**
 * A whole program: modules in dependency order, each already type/effect checked,
 * plus every diagnostic paired with the file it belongs to.
 */
class AnalyzedProgram(
    val modules: List<CheckedModule>,
    val diagnostics: List<LocatedDiag>,
) {
    val hasErrors: Boolean get() = diagnostics.any { it.diag.severity == Severity.ERROR }

    /** rendered form for the CLI: every diagnostic against its own source file */
    fun render(): String = buildString {
        for (d in diagnostics) append(d.diag.render(d.source))
    }
}

/**
 * Load and check a multi-module program (spec §10). [loaded] comes from
 * [ModuleLoader]; this runs the front-end per module in dependency order.
 *
 * v0.1 note: cross-module name resolution (qualified access, selective imports)
 * is layered on top of this in a later step; here each module is checked in
 * isolation once the graph is known.
 */
fun analyzeProgram(loaded: ModuleLoadResult, comptimeFuel: Long = 100_000_000L): AnalyzedProgram {
    val diags = ArrayList(loaded.loadDiagnostics)
    val checked = ArrayList<CheckedModule>()
    // modules arrive in dependency order, so a module's imports are already checked
    val exportsByPath = HashMap<String, ModuleExports>()
    for (mf in loaded.modules) {
        for (d in mf.diagnostics) diags.add(LocatedDiag(mf.source, d))
        val parseFailed = mf.diagnostics.any { it.severity == Severity.ERROR }
        val sink = DiagnosticSink()
        val checker = Checker(mf.module, sink, ImportEnv(exportsByPath.toMap()), mf.className)
        if (!parseFailed) {
            checker.check()
            if (sink.all.none { it.severity == Severity.ERROR }) {
                evalComptime(mf.module, sink, comptimeFuel)
            }
        }
        for (d in sink.all) diags.add(LocatedDiag(mf.source, d))
        val cm = CheckedModule(mf.modPath, mf.className, mf.source, mf.module,
            checker.functions, checker.types)
        checked.add(cm)
        exportsByPath[mf.modPath] = exportsOf(cm)
    }
    return AnalyzedProgram(checked, diags)
}

/** Convenience: load a project directory (or single file) and check it (spec §10.1). */
fun analyzeProject(path: File, comptimeFuel: Long = 100_000_000L): AnalyzedProgram {
    val loaded = if (path.isDirectory) ModuleLoader.loadDirectory(path) else ModuleLoader.loadFile(path)
    return analyzeProgram(loaded, comptimeFuel)
}
