package dawn.check

import dawn.ast.FnDecl
import dawn.ast.Module
import dawn.diag.DiagnosticSink
import dawn.diag.Severity
import dawn.diag.SourceFile
import dawn.lex.Lexer
import dawn.parse.Parser

/**
 * The bundled standard library (docs/builtins-to-stdlib.md, "杠杆 2").
 *
 * The `std` sources ship inside the compiler jar as resources. Each is parsed and
 * checked once per process, then its `pub` surface is handed to every user
 * module as an *implicit* import — visible without a `use`, exactly like the
 * builtin table it is meant to absorb (spec §10.6). Its generated classes ride
 * along in [dawn.codegen.CodeGen]'s shared emission, so a call into std links in
 * single-file and multi-module builds alike.
 *
 * std is checked with no std of its own in scope: it may only use the prelude,
 * the builtins, and explicit `use` edges between std modules. That keeps the
 * bootstrap acyclic.
 */
object StdLib {

    /** One bundled module: the checked AST plus the JVM class it compiles to. */
    class StdModule(
        val modPath: String,
        val className: String,
        val source: SourceFile,
        val module: Module,
        val exports: ModuleExports,
    )

    private const val INDEX = "/std/modules.txt"

    /** module names from the index resource, in dependency order */
    private val names: List<String> by lazy {
        val text = StdLib::class.java.getResourceAsStream(INDEX)?.use { it.readBytes().decodeToString() }
            ?: error("bundled std index missing from the compiler jar ($INDEX)")
        text.lineSequence()
            .map { it.substringBefore('#').trim() }
            .filter { it.isNotEmpty() }
            .toList()
    }

    /** the checked std modules, in dependency order; parsed and checked once */
    val modules: List<StdModule> by lazy { loadAndCheck() }

    /** bundled module names, for `use std/x` validation (reads only the index resource) */
    val moduleNames: Set<String> by lazy { names.toSet() }

    /**
     * modPath → exports, seeded into every program's import environment so
     * `use std/x` resolves like any module import (spec §10.6).
     */
    val exportsByPath: Map<String, ModuleExports> by lazy { modules.associate { it.modPath to it.exports } }

    /**
     * className → (name → decl), for the comptime interpreter. Module-qualified
     * std calls must resolve by owner: short names repeat across std modules
     * (map.insert / set.insert), so the flat [fnDecls] view cannot tell them apart.
     */
    val declsByOwner: Map<String, Map<String, FnDecl>> by lazy {
        modules.associate { m -> m.className to m.module.fns.associateBy { it.name } }
    }

    /**
     * The std names that stay implicitly visible without a `use` — the prelude's
     * std half (docs/stdlib-naming.md). Every other std name is deprecated as an
     * implicit global in v0.4.0 and needs its module from v0.5.0 on.
     */
    val PRELUDE: Set<String> = setOf("println", "print", "map", "filter", "fold")

    /**
     * The builtin table's deprecated flat spellings (v0.4.0 warns, v0.5.0 hides
     * them from user code): the container and cursor families, whose public
     * spelling is now module-qualified.
     */
    val DEPRECATED_BUILTINS: Set<String> = buildSet {
        for (op in listOf("empty", "from", "insert", "remove", "get", "has", "size", "keys", "values", "entries"))
            add("map_$op")
        for (op in listOf("empty", "from", "insert", "remove", "has", "size", "to_list")) add("set_$op")
        for (op in listOf("start", "end", "done", "char", "next", "prev", "slice", "skip")) add("cursor_$op")
        add("index_of_from")
    }

    /**
     * Deprecated flat spelling → how to write it now. Fed to the v0.4.0
     * deprecation warnings and, from v0.5.0, to unknown-name error hints.
     */
    val MOVED: Map<String, String> by lazy {
        val out = HashMap<String, String>()
        for (m in modules) {
            if (m.modPath == "std/legacy") continue
            val alias = m.modPath.substringAfterLast('/')
            for (n in m.exports.fns.keys) {
                if (n !in PRELUDE) out[n] = "use ${m.modPath}, then $alias.$n(...)"
            }
        }
        fun ren(old: String, mod: String, new: String) {
            out[old] = "use std/$mod, then $mod.$new(...)"
        }
        ren("str_len", "str", "len"); ren("char_to_string", "str", "from_char"); ren("reverse_str", "str", "reverse")
        ren("byte_len", "bytes", "len"); ren("byte_at", "bytes", "at")
        ren("byte_slice", "bytes", "slice"); ren("byte_index_of", "bytes", "index_of")
        for (op in listOf("empty", "from", "insert", "remove", "get", "has", "size", "keys", "values", "entries"))
            ren("map_$op", "map", op)
        for (op in listOf("empty", "from", "insert", "remove", "has", "size", "to_list")) ren("set_$op", "set", op)
        for (op in listOf("start", "end", "done", "char", "next", "prev", "slice", "skip")) ren("cursor_$op", "cursor", op)
        ren("index_of_from", "cursor", "find")
        out
    }

    /**
     * The std function *declarations*, for the compile-time interpreter: a const
     * initializer may call std, so [dawn.check.ComptimeInterp] needs the bodies,
     * not just the signatures [fns] carries.
     *
     * Private helpers are included, unlike [fns]: visibility is a checking
     * concern and has already been enforced by the time anything runs here, but
     * a `pub` function whose body calls a private helper still needs that helper
     * to be callable. A user module's own definitions shadow these.
     */
    val fnDecls: Map<String, FnDecl> by lazy {
        val out = LinkedHashMap<String, FnDecl>()
        for (m in modules) {
            for (d in m.module.fns) out[d.name] = d
        }
        out
    }

    /**
     * The implicitly-visible function surface — pinned to the v0.3 *flat* names
     * (docs/stdlib-naming.md). The short module-qualified spellings born in the
     * P0.7 reorganization (str.len, bytes.at, map.insert, ...) are reachable only
     * through `use std/x`: letting them into this flat view would shadow builtins
     * (`len`, `get`) and each other. The whole non-prelude half of this surface
     * is deprecated in v0.4.0 and gone in v0.5.0.
     */
    val fns: Map<String, FnSig> by lazy {
        val out = LinkedHashMap<String, FnSig>()
        for (m in modules) {
            val hidden = when (m.modPath) {
                "std/map", "std/set", "std/cursor" -> null // qualified-only, born after the flat era
                "std/str" -> setOf("len", "from_char", "reverse") // renamed; legacy carries the old spellings
                "std/bytes" -> setOf("len", "at", "slice", "index_of")
                else -> emptySet()
            }
            if (hidden != null) for ((n, s) in m.exports.fns) if (n !in hidden) out[n] = s
        }
        out
    }

    private fun loadAndCheck(): List<StdModule> {
        val out = ArrayList<StdModule>()
        val exportsByPath = HashMap<String, ModuleExports>()
        for (n in names) {
            val res = "/std/$n.dawn"
            val text = StdLib::class.java.getResourceAsStream(res)?.use { it.readBytes().decodeToString() }
                ?: error("bundled std module missing from the compiler jar ($res)")
            val modPath = "std/$n"
            val className = "std/$n"
            val source = SourceFile("<std>/$n.dawn", text)
            val sink = DiagnosticSink()
            val module = Parser(Lexer(text, 0, sink).lex(), sink, text).module()
            // no stdFns here: std cannot implicitly import itself (bootstrap stays acyclic)
            val checker = Checker(module, sink, ImportEnv(exportsByPath.toMap()), className,
                srcPath = null, javaLoader = null, srcText = text)
            checker.check()
            if (sink.all.none { it.severity == Severity.ERROR }) evalComptime(module, sink, 100_000_000L)
            // A broken bundled std is a compiler bug, not a user error: fail loudly
            // rather than let every downstream program report mystery diagnostics.
            val errs = sink.all.filter { it.severity == Severity.ERROR }
            if (errs.isNotEmpty()) {
                error("bundled std module `$modPath` does not check:\n" +
                    errs.joinToString("\n") { it.render(source) })
            }
            val cm = CheckedModule(modPath, className, source, module, checker.functions,
                checker.types, checker.aliases, null, checker.declaredTraits, checker.declaredImpls)
            exportsByPath[modPath] = exportsOf(cm)
            out.add(StdModule(modPath, className, source, module, exportsByPath.getValue(modPath)))
        }
        return out
    }
}
