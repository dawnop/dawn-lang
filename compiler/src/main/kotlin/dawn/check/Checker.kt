package dawn.check

import dawn.ast.*
import dawn.check.Type.*
import dawn.diag.DiagnosticSink
import dawn.diag.SourceFile
import dawn.diag.Span
import dawn.diag.Suggest

/** The builtins that create Map/Set entries — where key-type validity is enforced (spec §2.2). */
private val KEYED_CREATORS = setOf("map_empty", "map_from", "map_insert", "set_empty", "set_from", "set_insert")

/**
 * Type and effect checking (the M0 subset of spec §2/§4/§5/§6).
 * Types and resolved symbols are annotated back onto the AST for codegen and
 * the language server.
 *
 * Error handling: failures are reported to the sink and checking continues;
 * the failing expression gets type TError, which is compatible with everything
 * and never re-reported (no error cascades). Codegen must only run when the
 * sink has no errors.
 *
 * Effect rule: the signature is the promise — callers only look at a callee's
 * declared effect; the effect inferred from a function body must be ⊑ the
 * declared one.
 */
class Checker(
    private val module: Module,
    private val sink: DiagnosticSink,
    /** exports of already-checked modules (spec §10); empty for single-file analysis */
    private val imports: ImportEnv = ImportEnv.EMPTY,
    /** JVM class of this module, tagged onto its fns/types for multi-module codegen */
    private val ownerClass: String? = null,
    /** source file of this module, tagged onto its fns/types/consts for cross-file navigation */
    private val srcPath: String? = null,
    /** resolves `use java` classes; null = the compiler's own class path (JDK only) */
    private val javaLoader: ClassLoader? = null,
    /** source text of this module; only used to put a line number in `!` panic messages */
    private val srcText: String? = null,
    /**
     * The bundled standard library's function surface (spec §10.6), implicitly in
     * scope here without a `use`. Sits between local functions and the builtin
     * table in name resolution, and — like a builtin — cannot be redefined.
     * Empty when checking std itself, so the bootstrap stays acyclic.
     */
    private val stdFns: Map<String, FnSig> = emptyMap(),
) {

    private val fns = HashMap<String, FnSig>()
    private val adts = HashMap<String, AdtInfo>()
    private val typeAliases = HashMap<String, AliasInfo>()
    private val ctors = HashMap<String, CtorInfo>()

    /** traits visible here: prelude + selectively imported + locally declared */
    private val traitsByName = HashMap<String, TraitInfo>()
    /** traits declared in this module (the exportable subset) */
    private val localTraits = LinkedHashMap<String, TraitInfo>()
    /** impls declared in this module */
    private val localImpls = ArrayList<ImplInfo>()
    /** the program-wide impl view: prelude + every previously-checked module + local */
    private val implTable = HashMap<Pair<TraitInfo, Type>, ImplInfo>()

    /** whole-module imports: alias (last path segment) → that module's exports (spec §10.2) */
    private val moduleAliases = HashMap<String, ModuleExports>()
    /** selectively-imported names → the module path they came from (for conflict messages) */
    private val importedNames = HashMap<String, String>()
    /** constants visible so far — filled in declaration order (evaluation order) */
    private val consts = LinkedHashMap<String, ConstDecl>()
    private var allConstNames: Set<String> = emptySet()
    /** imported Java classes by simple name (spec §9) */
    private val javaClasses = HashMap<String, Class<*>>()
    private val scopes = ArrayDeque<HashMap<String, Symbol>>()

    /** user-defined functions by name (first definition wins on duplicates) */
    val functions: Map<String, FnSig> get() = fns
    /** user-defined types by name */
    val types: Map<String, AdtInfo> get() = adts
    val aliases: Map<String, AliasInfo> get() = typeAliases
    /** traits declared in this module */
    val declaredTraits: Map<String, TraitInfo> get() = localTraits
    /** impls declared in this module */
    val declaredImpls: List<ImplInfo> get() = localImpls

    /** effects used by the body currently being checked (Io and/or effect variables) */
    private var usedEffects = HashSet<Eff>()
    /** location of the first use of each effect (for error messages) */
    private var effWitness = HashMap<Eff, Pair<Span, String>>()

    /** effect variables of the signature currently being checked (for annotations in bodies) */
    private var currentEffVars: MutableMap<String, Eff.Var> = HashMap()

    /** an active lambda: locals declared outside its boundary are captures */
    private class LambdaCtx(
        val boundaryDepth: Int,
        /** the lambda's return type when known from context — lets `?` work inside (spec §8.1) */
        val expectedRet: Type?,
    ) {
        val captures = LinkedHashSet<Symbol>()
    }
    private val lambdaStack = ArrayDeque<LambdaCtx>()

    private fun recordEffect(eff: Eff, span: Span, name: String) {
        if (eff == Eff.Pure) return
        if (eff !in usedEffects) effWitness[eff] = span to name
        usedEffects.add(eff)
    }

    /** type parameters of the declaration currently being checked (for annotations in bodies) */
    private var currentTParams: Map<String, TVar> = emptyMap()

    /** the signature of the function being checked (null inside test blocks) */
    private var currentFnSig: FnSig? = null

    /** hidden dictionary bindings of the function being checked: (type param, bound) → symbol */
    private var dictSyms: Map<Pair<TVar, TraitInfo>, Symbol> = emptyMap()

    /** Materialize [sig]'s trait bounds as hidden dictionary symbols (codegen params). */
    private fun bindDicts(sig: FnSig) {
        if (sig.constraints.isEmpty()) {
            dictSyms = emptyMap()
            return
        }
        val m = LinkedHashMap<Pair<TVar, TraitInfo>, Symbol>()
        for ((i, tp) in sig.typeParams.withIndex()) {
            for (tr in sig.boundsOf(i)) {
                // typed as the tvar: erases to Object (one slot), like any generic value
                m[tp to tr] = Symbol("${tr.name}\$${tp.name}", tp, mutable = false,
                    defSpan = sig.nameSpan ?: Span(0, 0), dictOf = tr to tp)
            }
        }
        dictSyms = m
        sig.dictSyms = m.values.toList()
    }

    /** inside a test block (assert is allowed, io is implicit) */
    private var inTest = false

    fun check() {
        // 0. prelude: Option/Result and their constructors; prelude traits/impls
        for (info in PRELUDE_ADTS) {
            adts[info.name] = info
            for (c in info.ctors) ctors[c.name] = c
        }
        for (t in PRELUDE_TRAITS) {
            traitsByName[t.name] = t
            for (m in t.methods.values) fns[m.sig.name] = m.sig
        }
        for (i in PRELUDE_IMPLS) implTable[i.trait to i.subject] = i
        // 0.5. java imports (spec §9): resolved by reflection on the compiler's JVM
        for (d in module.javaUses) {
            val cls = resolveJavaClass(d.fqcn, javaLoader ?: javaClass.classLoader) ?: run {
                sink.error("Java class not found: ${d.fqcn}", d.nameSpan,
                    "the JDK is always visible; third-party jars must be passed with --cp <jars>")
                null
            }
            if (cls == null) continue
            when {
                javaClasses.containsKey(d.name) ->
                    sink.error("`${d.name}` is already imported", d.nameSpan)
                else -> javaClasses[d.name] = cls
            }
        }
        // 0.75. module imports (spec §10): whole-module aliases + selective injections
        processImports()
        // 1. type headers first (shells only), so recursive types resolve
        for (d in module.types) {
            if (javaClasses.containsKey(d.name)) {
                sink.error("`${d.name}` collides with an imported Java class", d.nameSpan)
                continue
            }
            if (aliasShadow(d.name, d.nameSpan) || importClash(d.name, d.nameSpan, "type")) continue
            if (Type.named(d.name) != null || d.name in setOf("List", "Map", "Set")) {
                sink.error("`${d.name}` is a builtin type and cannot be redefined", d.nameSpan)
                continue
            }
            if (adts.containsKey(d.name) || typeAliases.containsKey(d.name)) {
                sink.error(
                    if (PRELUDE_ADTS.any { it.name == d.name })
                        "`${d.name}` is a prelude type and cannot be redefined"
                    else "type `${d.name}` is defined twice",
                    d.nameSpan)
                continue
            }
            if (d.typeParams.toSet().size != d.typeParams.size)
                sink.error("duplicate type parameter names", d.nameSpan)
            if (d.aliasTarget != null) {
                aliasEffVarSpan(d.aliasTarget!!)?.let {
                    sink.error("a type alias cannot carry effect variables", it,
                        "write !io, or leave the function type pure")
                }
                typeAliases[d.name] = AliasInfo(d.name, d.typeParams.map { TVar(it) },
                    d.aliasTarget, d.nameSpan)
                continue
            }
            val info = AdtInfo(d.name, d.nameSpan, d.isRecord, d.typeParams.map { TVar(it) })
            info.owner = ownerClass
            info.srcPath = srcPath
            for ((trait, span) in d.derives) {
                when (trait) {
                    "Show" -> info.derivesShow = true
                    "Ord" -> info.derivesOrd = true
                    else -> sink.error("unknown derivable trait `$trait`", span,
                        "Show and Ord can be derived")
                }
            }
            adts[d.name] = info
            for (c in d.ctors) {
                val ci = CtorInfo(info, c.name, c.nameSpan)
                when {
                    Type.named(c.name) != null ->
                        sink.error("constructor `${c.name}` collides with a builtin type name", c.nameSpan)
                    ctors.containsKey(c.name) ->
                        sink.error("constructor `${c.name}` is already defined (constructors share one module-wide namespace)",
                            c.nameSpan)
                    else -> {
                        c.info = ci
                        ctors[c.name] = ci
                        info.ctors.add(ci)
                    }
                }
            }
        }
        // 2. constructor field types (may reference any type declared above)
        for (d in module.types) {
            val info = d.ctors.firstOrNull()?.info?.adt
            val tp = info?.typeParams?.associateBy { it.name } ?: emptyMap()
            for (c in d.ctors) {
                val ci = c.info ?: continue
                for (f in c.fields) {
                    if (ci.fields.any { it.name == f.name }) {
                        sink.error("field `${f.name}` is declared twice in `${c.name}`", f.span)
                        continue
                    }
                    var ft = resolveType(f.typeRef, tp)
                    if (ft == TUnit) {
                        sink.error("constructor fields cannot be Unit", f.span,
                            "a no-payload case is just a bare constructor")
                        ft = TError
                    }
                    ci.fields.add(FieldInfo(f.name, ft, f.span, srcPath))
                }
            }
        }
        // 2.25 aliases: resolve every target now, so cycles and unknown names are
        // reported at the declaration even if the alias is never used
        for (al in typeAliases.values) resolveAliasTarget(al, al.nameSpan)
        // 2.5 derive Show: every field must be renderable (type parameters allowed, resolved at use)
        for (d in module.types) {
            val info = d.ctors.firstOrNull()?.info?.adt ?: continue
            if (!info.derivesShow) continue
            for (ci in info.ctors) for (f in ci.fields) {
                if (!isShowableField(f.type))
                    sink.error(
                        "cannot derive Show for `${info.name}`: field `${f.name}` of type ${f.type} is not printable",
                        f.defSpan ?: d.nameSpan, showHint(f.type),
                    )
            }
        }
        // 2.75. traits and impls: headers + method signatures + coherence/orphan checks
        registerTraits()
        registerImpls()
        // 3. function signatures
        for (d in module.fns) {
            if (d.typeParams.map { it.name }.toSet().size != d.typeParams.size)
                sink.error("duplicate type parameter names", d.nameSpan)
            val tvars = d.typeParams.map { TVar(it.name) }
            val tp = tvars.associateBy { it.name }
            val ev = HashMap<String, Eff.Var>()
            val eff = resolveEff(d.declaredEff, ev)
            val inferring = d.retType == null
            val sig = FnSig(
                d.name,
                d.params.map { resolveType(it.typeName, tp, ev) },
                d.params.map { it.name },
                d.retType?.let { resolveType(it, tp, ev) } ?: TError,
                // until the body is checked, assume the worst effect for safety
                if (inferring && d.declaredEff.isEmpty()) Eff.Io else eff,
                isBuiltin = false,
                typeParams = tvars,
                nameSpan = d.nameSpan,
                inferring = inferring,
                constraints = resolveBounds(d.typeParams),
            )
            sig.owner = ownerClass
            sig.srcPath = srcPath
            d.sig = sig
            d.effVars = ev
            when {
                moduleAliases.containsKey(d.name) -> aliasShadow(d.name, d.nameSpan)
                importedNames.containsKey(d.name) -> importClash(d.name, d.nameSpan, "function")
                BUILTINS.containsKey(d.name) ->
                    sink.error("`${d.name}` is a builtin function and cannot be redefined", d.nameSpan)
                stdFns.containsKey(d.name) ->
                    sink.error("`${d.name}` is a standard-library function and cannot be redefined", d.nameSpan)
                fns.containsKey(d.name) -> {
                    val prev = fns[d.name]!!.trait
                    if (prev != null)
                        sink.error("`${d.name}` is already a method of trait `${prev.name}` " +
                            "(trait methods share the function namespace)", d.nameSpan)
                    else
                        sink.error("function `${d.name}` is defined twice", d.nameSpan)
                }
                else -> fns[d.name] = sig
            }
        }
        // 3.5. constant declarations — types only. Initializers are checked in
        // pass 5, after signature inference, so they can call inferred functions.
        allConstNames = module.consts.map { it.name }.toSet()
        for (d in module.consts) declareConst(d)
        // 4. entry point check
        val main = module.fns.find { it.name == "main" }
        if (main != null) {
            val sig = main.sig!!
            if (sig.paramTypes.isNotEmpty() || sig.ret != TUnit)
                sink.error("main must have the signature fn main() -> Unit !io", main.nameSpan)
            if (!main.pub)
                sink.error("main must be pub", main.nameSpan, "write pub fn main() -> Unit !io")
        }
        // 5. check each function body, then each test block. Functions whose
        // return type is inferred go first, in call-dependency order — every
        // callee's signature is final before any caller is checked. A cycle
        // (direct or mutual recursion) cannot be inferred and must annotate.
        val inferredDecls = module.fns.filter { it.sig?.inferring == true }.toSet()
        val pending = inferredDecls.toMutableList()
        if (pending.isNotEmpty()) {
            val pendingNames = pending.map { it.name }.toSet()
            val deps = pending.associateWith { d -> nameRefs(d.body).intersect(pendingNames) }
            val done = HashSet<String>()
            var progress = true
            while (progress) {
                progress = false
                val it = pending.iterator()
                while (it.hasNext()) {
                    val d = it.next()
                    if (deps[d]!!.all { n -> n in done }) {
                        checkFnInferred(d)
                        done.add(d.name)
                        it.remove()
                        progress = true
                    }
                }
            }
            for (d in pending) // what remains is a dependency cycle
                sink.error("cannot infer the return type of `${d.name}`: it is recursive (directly or mutually)",
                    d.nameSpan, "declare it: fn ${d.name}(...) -> T = ...")
        }
        // 5.5. constant initializers, in declaration order (a const sees only
        // earlier consts; that order is also the evaluation order)
        val visibleConsts = HashSet<String>()
        for (d in module.consts) {
            checkConstInit(d, visibleConsts)
            visibleConsts.add(d.name)
        }
        for (d in module.fns) if (d !in inferredDecls) checkFn(d)
        // 5.75. impl method bodies and trait default bodies (full signatures, so
        // they check like ordinary annotated functions)
        for (i in module.impls) for (m in i.methods) if (m.sig != null) checkFn(m)
        for (t in module.traits) for (m in t.methods) if (m.body != null && m.sig != null) checkTraitDefault(m)
        for (t in module.tests) checkTest(t)
    }

    /** every lowercase name mentioned in call/value position — the call-graph over-approximation */
    private fun nameRefs(e: Expr, out: MutableSet<String> = HashSet()): Set<String> {
        when (e) {
            is VarRef -> out.add(e.name)
            is Call -> { out.add(e.callee); e.args.forEach { nameRefs(it, out) } }
            is MethodCall -> { out.add(e.name); nameRefs(e.target, out); e.args.forEach { nameRefs(it, out) } }
            is Apply -> { nameRefs(e.target, out); e.args.forEach { nameRefs(it, out) } }
            is Lambda -> nameRefs(e.body, out)
            is Block -> { e.stmts.forEach { nameRefs(it, out) }; e.tail?.let { nameRefs(it, out) } }
            is If -> { nameRefs(e.cond, out); nameRefs(e.thenBranch, out); e.elseBranch?.let { nameRefs(it, out) } }
            is Match -> { nameRefs(e.scrutinee, out); e.arms.forEach { a -> a.guard?.let { nameRefs(it, out) }; nameRefs(a.body, out) } }
            is CtorCall -> { e.spread?.let { nameRefs(it, out) }; e.args.forEach { nameRefs(it.expr, out) } }
            is FieldAccess -> nameRefs(e.target, out)
            is ListLit -> e.elems.forEach { nameRefs(it, out) }
            is TupleLit -> e.elems.forEach { nameRefs(it, out) }
            is Binary -> { nameRefs(e.left, out); nameRefs(e.right, out) }
            is Unary -> nameRefs(e.operand, out)
            is Propagate -> nameRefs(e.operand, out)
            is Unwrap -> nameRefs(e.operand, out)
            is Index -> { nameRefs(e.target, out); nameRefs(e.index, out) }
            is Return -> e.value?.let { nameRefs(it, out) }
            is StrLit -> e.parts.forEach { p -> if (p is StrPart.Interp) nameRefs(p.expr, out) }
            is ComptimeExpr -> nameRefs(e.body, out)
            is UnsafePureExpr -> nameRefs(e.body, out)
            else -> {}
        }
        return out
    }

    private fun nameRefs(s: Stmt, out: MutableSet<String>) {
        when (s) {
            is LetStmt -> nameRefs(s.init, out)
            is LetPatStmt -> nameRefs(s.init, out)
            is LocalFnStmt -> nameRefs(s.lambda.body, out)
            is AssignStmt -> nameRefs(s.value, out)
            is ExprStmt -> nameRefs(s.expr, out)
            is AssertStmt -> nameRefs(s.cond, out)
            is WhileStmt -> { nameRefs(s.cond, out); nameRefs(s.body, out) }
            is ForStmt -> { nameRefs(s.from, out); s.to?.let { nameRefs(it, out) }; nameRefs(s.body, out) }
        }
    }

    /**
     * Check the body of a signature-inferred function and seal its signature:
     * ret = the body's type, eff = the body's effects (or the declared one,
     * which is then enforced as usual).
     */
    private fun checkFnInferred(d: FnDecl) {
        val old = d.sig!!
        currentTParams = old.typeParams.associateBy { it.name }
        currentEffVars = HashMap(d.effVars)
        currentFnSig = old
        bindDicts(old)
        usedEffects = HashSet()
        effWitness = HashMap()
        lambdaStack.clear()
        scopes.clear()
        scopes.addLast(HashMap())
        for ((p, t) in d.params.zip(old.paramTypes)) {
            p.symbol = declare(p.name, t, mutable = false, p.span)
        }
        val bodyType = checkExpr(d.body, expected = null)
        val finalEff: Eff
        if (d.declaredEff.isEmpty()) {
            finalEff = usedEffects.fold(Eff.Pure as Eff) { acc, x -> lubEff(acc, x) }
        } else {
            val declared = old.eff // registration resolved it (declaredEff was non-empty)
            for (used in usedEffects) {
                if (effSubsumes(declared, used)) continue
                val (span, name) = effWitness[used] ?: (d.nameSpan to "?")
                sink.error("function `${d.name}` is not declared !$used but calls `$name` (!$used)",
                    span, "add !$used to the end of the signature, or remove the call")
            }
            finalEff = declared
        }
        val sealed = FnSig(old.name, old.paramTypes, old.paramNames, bodyType, finalEff,
            isBuiltin = false, typeParams = old.typeParams, nameSpan = old.nameSpan,
            constraints = old.constraints)
        sealed.owner = old.owner
        sealed.srcPath = old.srcPath
        sealed.dictSyms = old.dictSyms // witnesses in the body reference these very symbols
        d.sig = sealed
        if (fns[d.name] === old) fns[d.name] = sealed
        scopes.removeLast()
    }

    // ---- traits and impls (docs/trait.md; knife 2: registration + coherence) ----

    /** Register trait headers and method signatures; methods enter the fn namespace. */
    private fun registerTraits() {
        for (d in module.traits) {
            if (aliasShadow(d.name, d.nameSpan) || importClash(d.name, d.nameSpan, "trait")) continue
            if (Type.named(d.name) != null || d.name in setOf("List", "Map", "Set")) {
                sink.error("`${d.name}` is a builtin type and cannot be a trait name", d.nameSpan)
                continue
            }
            if (adts.containsKey(d.name) || typeAliases.containsKey(d.name) || javaClasses.containsKey(d.name)) {
                sink.error("trait `${d.name}` collides with a type of the same name", d.nameSpan,
                    "traits and types share one namespace; rename one")
                continue
            }
            if (traitsByName.containsKey(d.name)) {
                sink.error(
                    if (PRELUDE_TRAITS.any { it.name == d.name })
                        "`${d.name}` is a prelude trait and cannot be redefined"
                    else "trait `${d.name}` is defined twice",
                    d.nameSpan)
                continue
            }
            val info = TraitInfo(d.name, TVar(d.typeParam), d.nameSpan, d.pub)
            info.owner = ownerClass
            info.srcPath = srcPath
            d.info = info
            traitsByName[d.name] = info
            localTraits[d.name] = info
            val tp = mapOf(d.typeParam to info.tvar)
            for (m in d.methods) {
                if (m.declaredEff.any { it != "io" }) {
                    sink.error("trait methods cannot declare effect variables", m.nameSpan,
                        "a trait method is pure or !io")
                    continue
                }
                val ev = HashMap<String, Eff.Var>()
                val paramTypes = m.params.map { resolveType(it.typeName, tp, ev) }
                val ret = resolveType(m.retType, tp, ev)
                if (ev.isNotEmpty()) {
                    sink.error("trait method signatures cannot carry effect variables", m.nameSpan,
                        "write !io on the function type, or leave it pure")
                    continue
                }
                val eff = if (m.declaredEff.isEmpty()) Eff.Pure else Eff.Io
                val sig = FnSig(m.name, paramTypes, m.params.map { it.name }, ret, eff,
                    isBuiltin = false, typeParams = listOf(info.tvar), nameSpan = m.nameSpan,
                    constraints = listOf(listOf(info)))
                sig.trait = info
                sig.owner = ownerClass
                sig.srcPath = srcPath
                m.sig = sig
                when {
                    moduleAliases.containsKey(m.name) -> aliasShadow(m.name, m.nameSpan)
                    importedNames.containsKey(m.name) -> importClash(m.name, m.nameSpan, "trait method")
                    BUILTINS.containsKey(m.name) ->
                        sink.error("`${m.name}` is a builtin function and cannot be a trait method", m.nameSpan)
                    stdFns.containsKey(m.name) ->
                        sink.error("`${m.name}` is a standard-library function and cannot be a trait method",
                            m.nameSpan)
                    fns.containsKey(m.name) -> {
                        val prev = fns[m.name]!!.trait
                        sink.error(
                            if (prev != null)
                                "`${m.name}` is already a method of trait `${prev.name}` " +
                                    "(trait methods share the function namespace)"
                            else "trait method `${m.name}` collides with a function of the same name",
                            m.nameSpan)
                    }
                    else -> {
                        fns[m.name] = sig
                        info.methods[m.name] = TraitMethodSig(sig, m)
                    }
                }
            }
        }
    }

    /** Register impls: subject rules, orphan rule, program-wide coherence, method matching. */
    private fun registerImpls() {
        // the global impl view: every module checked before this one contributes,
        // import edges or not (impls are program-global; coherence makes that safe)
        for (exp in imports.available.values) {
            for (i in exp.impls) implTable.putIfAbsent(i.trait to i.subject, i)
        }
        val localAdts = module.types.mapNotNull { adts[it.name] }.toHashSet()
        // derive Ord first, so an explicit impl of the same pair reports as the duplicate
        for (d in module.types) {
            val info = d.ctors.firstOrNull()?.info?.adt ?: continue
            if (!info.derivesOrd) continue
            val span = d.derives.first { it.first == "Ord" }.second
            if (info.typeParams.isNotEmpty()) {
                sink.error("cannot derive Ord for the generic type `${info.name}`", span,
                    "v1 Ord subjects are non-generic; order concrete values instead")
                continue
            }
            val ii = ImplInfo(ORD_TRAIT, info.type, span, srcPath)
            ii.owner = ownerClass
            ii.derived = true
            implTable[ORD_TRAIT to info.type] = ii
            localImpls.add(ii)
            info.ordImpl = ii
        }
        for (d in module.impls) {
            val tr = traitsByName[d.traitName]
            if (tr == null) {
                sink.error("unknown trait: ${d.traitName}", d.traitSpan,
                    Suggest.hint(d.traitName, traitsByName.keys)
                        ?: "declare `trait ${d.traitName}[T] { ... }` or import it first")
                continue
            }
            currentTParams = emptyMap()
            currentEffVars = HashMap()
            val subject = resolveType(d.subject)
            if (subject == TError) continue
            val subjectOk = when (subject) {
                TInt, TFloat, TBool, TString -> true
                is TAdt -> subject.info.typeParams.isEmpty()
                else -> false
            }
            if (!subjectOk) {
                sink.error("`$subject` cannot be an impl subject", d.subject.span,
                    "v1 impls cover named non-generic types and Int/Float/Bool/String; " +
                        "generic subjects (List, Map, tuples, instantiated generics) need conditional impls (v2)")
                continue
            }
            // orphan rule: the impl lives with the trait or with the subject type
            val traitLocal = localTraits[d.traitName] === tr
            val subjectLocal = subject is TAdt && subject.info in localAdts
            if (!traitLocal && !subjectLocal) {
                sink.error("orphan impl: `${tr.name}[$subject]` may not live here", d.traitSpan,
                    "an impl belongs to the module that declares `${tr.name}` " +
                        "or the one that declares `$subject`")
                continue
            }
            // coherence: at most one impl per (trait, type) in the whole program
            val key = tr to subject
            val prev = implTable[key]
            if (prev != null) {
                val where = prev.srcPath?.takeIf { it != srcPath }?.let { " (previous impl in $it)" } ?: ""
                sink.error("duplicate impl: `${tr.name}[$subject]` is already implemented$where", d.traitSpan,
                    if (prev.derived) "`$subject` already derives ${tr.name}; drop the derive or this impl"
                    else "the program allows one impl per trait and type")
                continue
            }
            val info = ImplInfo(tr, subject, d.span, srcPath)
            info.owner = ownerClass
            d.info = info
            val instMap = mapOf(tr.tvar to subject)
            for (m in d.methods) {
                val ms = tr.methods[m.name]
                if (ms == null) {
                    sink.error("trait `${tr.name}` has no method `${m.name}`", m.nameSpan,
                        Suggest.hint(m.name, tr.methods.keys))
                    continue
                }
                if (info.provided.containsKey(m.name)) {
                    sink.error("method `${m.name}` is implemented twice in this impl", m.nameSpan)
                    continue
                }
                if (m.declaredEff.any { it != "io" }) {
                    sink.error("impl methods cannot declare effect variables", m.nameSpan,
                        "an impl method is pure or !io")
                    continue
                }
                val ev = HashMap<String, Eff.Var>()
                val paramTypes = m.params.map { resolveType(it.typeName, emptyMap(), ev) }
                val ret = m.retType?.let { resolveType(it, emptyMap(), ev) } ?: TError
                val eff = if (m.declaredEff.isEmpty()) Eff.Pure else Eff.Io
                if (ev.isNotEmpty()) {
                    sink.error("impl method signatures cannot carry effect variables", m.nameSpan)
                    continue
                }
                val want = ms.sig.paramTypes.map { subst(it, instMap) }
                val wantRet = subst(ms.sig.ret, instMap)
                val wantRender = "fn ${m.name}(${want.joinToString(", ")}) -> $wantRet${ms.sig.eff.suffix}"
                if (paramTypes != want || ret != wantRet)
                    sink.error("`${m.name}` does not match the trait's signature", m.nameSpan,
                        "trait `${tr.name}` declares it as $wantRender")
                else if (!effSubsumes(ms.sig.eff, eff))
                    sink.error("`${m.name}` is declared !$eff but trait `${tr.name}` declares it pure",
                        m.nameSpan, "drop !$eff here, or declare the trait method !$eff")
                val sig = FnSig(m.name, paramTypes, m.params.map { it.name }, ret, eff,
                    isBuiltin = false, nameSpan = m.nameSpan)
                sig.owner = ownerClass
                sig.srcPath = srcPath
                m.sig = sig
                info.provided[m.name] = m
            }
            val missing = tr.methods.values.filter { !it.hasDefault && it.sig.name !in info.provided }
            if (missing.isNotEmpty())
                sink.error("impl `${tr.name}[$subject]` is missing " +
                    missing.joinToString(", ") { "`${it.sig.name}`" }, d.traitSpan,
                    "provide: " + missing.joinToString("; ") { ms ->
                        val ps = ms.sig.paramNames.zip(ms.sig.paramTypes)
                            .joinToString(", ") { "${it.first}: ${subst(it.second, instMap)}" }
                        "fn ${ms.sig.name}($ps) -> ${subst(ms.sig.ret, instMap)}${ms.sig.eff.suffix}"
                    })
            implTable[key] = info
            localImpls.add(info)
            if (tr === ORD_TRAIT && subject is TAdt) subject.info.ordImpl = info
        }
        // derive Ord field check, after every impl (derived and explicit) is known
        for (d in module.types) {
            val info = d.ctors.firstOrNull()?.info?.adt ?: continue
            if (!info.derivesOrd || info.ordImpl?.derived != true) continue
            val span = d.derives.first { it.first == "Ord" }.second
            for (ci in info.ctors) for (f in ci.fields) {
                val ok = f.type in listOf(TInt, TFloat, TString) ||
                    (f.type is TAdt && implTable.containsKey(ORD_TRAIT to f.type))
                if (!ok)
                    sink.error("cannot derive Ord for `${info.name}`: field `${f.name}` of type " +
                        "${f.type} is not orderable", f.defSpan ?: span,
                        "orderable fields are Int, Float, String, and types with an Ord impl")
            }
        }
    }

    /**
     * Satisfy one trait requirement at a use site. A concrete subject resolves
     * to its unique impl (coherence); the caller's own rigid type parameter
     * forwards the caller's dictionary — which behaves like a hidden fn-scope
     * local, so every enclosing lambda captures it.
     */
    private fun resolveWitness(trait: TraitInfo, t: Type, span: Span, requirer: String): WitnessRef? {
        if (t.isErrorish) return null
        if (t is TVar) {
            val sym = dictSyms[t to trait]
            if (sym == null) {
                sink.error("$requirer requires `${trait.name}[$t]`, but `$t` has no such bound", span,
                    "add the bound: [$t: ${trait.name}]")
                return null
            }
            for (ctx in lambdaStack) ctx.captures.add(sym)
            return WitnessRef.Forward(trait, t, sym)
        }
        implTable[trait to t]?.let { return WitnessRef.Concrete(it) }
        sink.error("no impl of `${trait.name}` for `$t`", span, implHint(trait, t))
        return null
    }

    private fun implHint(trait: TraitInfo, t: Type): String = when {
        trait === ORD_TRAIT && t !is TAdt ->
            "only Int, Float, String and types with an `impl Ord` can be ordered"
        t is TAdt && t.info.typeParams.isEmpty() ->
            "define `impl ${trait.name}[$t] { ... }` in the module declaring `$t` or `${trait.name}`"
        t in listOf(TInt, TFloat, TBool, TString) ->
            "define `impl ${trait.name}[$t] { ... }` in the module declaring `${trait.name}`"
        else -> "v1 impl subjects are named non-generic types and Int/Float/Bool/String"
    }

    /** `< <= > >=` beyond the native scalars order through Ord (docs/trait.md). */
    private fun resolveOrdWitness(t: Type, span: Span): WitnessRef? {
        if (t.isErrorish) return null
        if (t is TVar) {
            val sym = dictSyms[t to ORD_TRAIT]
            if (sym == null) {
                sink.error("values of type $t cannot be ordered", span, "add the bound: [$t: Ord]")
                return null
            }
            for (ctx in lambdaStack) ctx.captures.add(sym)
            return WitnessRef.Forward(ORD_TRAIT, t, sym)
        }
        implTable[ORD_TRAIT to t]?.let { return WitnessRef.Concrete(it) }
        sink.error("values of type $t cannot be ordered", span,
            if (t is TAdt && t.info.typeParams.isEmpty())
                "implement it: impl Ord[$t] { fn cmp(a: $t, b: $t) -> Int = ... }"
            else null)
        return null
    }

    /** Resolve `[T: Ord + Show]` bounds against the visible traits, aligned per parameter. */
    private fun resolveBounds(tparams: List<TypeParamDecl>): List<List<TraitInfo>> {
        if (tparams.all { it.bounds.isEmpty() }) return emptyList()
        return tparams.map { tp ->
            if (tp.bounds.map { it.first }.toSet().size != tp.bounds.size)
                sink.error("duplicate trait bound on `${tp.name}`", tp.span)
            tp.bounds.mapNotNull { (bname, bspan) ->
                val tr = traitsByName[bname]
                if (tr == null) {
                    sink.error("unknown trait: $bname", bspan,
                        Suggest.hint(bname, traitsByName.keys)
                            ?: "declare `trait $bname[T] { ... }` or import it first")
                    null
                } else tr
            }.distinct()
        }
    }

    /** Check a trait's default method body against its own signature (T stays rigid). */
    private fun checkTraitDefault(m: TraitMethod) {
        val sig = m.sig!!
        currentTParams = sig.typeParams.associateBy { it.name }
        currentEffVars = HashMap()
        currentFnSig = sig
        bindDicts(sig)
        usedEffects = HashSet()
        effWitness = HashMap()
        lambdaStack.clear()
        scopes.clear()
        scopes.addLast(HashMap())
        for ((p, t) in m.params.zip(sig.paramTypes)) {
            p.symbol = declare(p.name, t, mutable = false, p.span)
        }
        val bodyType = checkExpr(m.body!!, expected = sig.ret)
        if (!assignable(bodyType, sig.ret))
            sink.error("method `${m.name}` declares return type ${sig.ret} but its default body is $bodyType",
                m.body!!.span)
        for (used in usedEffects) {
            if (effSubsumes(sig.eff, used)) continue
            val (span, name) = effWitness[used] ?: (m.nameSpan to "?")
            sink.error("method `${m.name}` is not declared !$used but calls `$name` (!$used)", span,
                "add !$used to the trait method, or remove the call")
        }
        scopes.removeLast()
    }

    /**
     * Resolve module imports (spec §10): whole-module `use` decls become aliases;
     * selective `use m.{...}` decls inject the named pub members into this module's
     * namespace. Modules the loader could not find are skipped (already reported).
     */
    private fun processImports() {
        for (u in module.moduleUses) {
            val exp = imports.available[u.path] ?: continue
            u.exports = exp
            if (u.selective == null) {
                val prev = moduleAliases.put(u.name, exp)
                if (prev != null && prev.modPath != exp.modPath)
                    sink.error("module alias `${u.name}` is imported from two modules " +
                        "(`${prev.modPath}` and `${exp.modPath}`)", u.nameSpan,
                        "rename with selective imports, or reorganize the modules")
            } else {
                for (imp in u.selective) injectSelective(u.path, exp, imp.name, imp.span)
            }
        }
    }

    private fun injectSelective(fromPath: String, exp: ModuleExports, name: String, span: Span) {
        val fn = exp.fns[name]; val ty = exp.types[name]; val cn = exp.consts[name]; val ct = exp.ctors[name]
        val al = exp.aliases[name]; val tr = exp.traits[name]
        if (fn == null && ty == null && cn == null && ct == null && al == null && tr == null) {
            if (name in exp.allNames)
                sink.error("`$name` is private to module `$fromPath`", span,
                    "add `pub` to its declaration in $fromPath")
            else
                sink.error("module `$fromPath` has no exported name `$name`", span,
                    Suggest.hint(name, exp.fns.keys + exp.types.keys + exp.consts.keys +
                        exp.ctors.keys + exp.traits.keys))
            return
        }
        importedNames[name]?.let { prev ->
            sink.error("`$name` is imported more than once (from `$prev` and `$fromPath`)", span)
            return
        }
        importedNames[name] = fromPath
        if (fn != null) fns[name] = fn
        // a type brings its constructors (spec §10.3); a constructor may also be named directly
        if (ty != null) { adts[name] = ty; for (c in ty.ctors) ctors[c.name] = c }
        if (al != null) typeAliases[name] = al
        if (ct != null) ctors[name] = ct
        if (cn != null) consts[name] = cn
        if (tr != null) traitsByName[name] = tr
    }

    /** A local declaration or binding may not shadow a whole-module alias (spec §10.3). */
    private fun aliasShadow(name: String, span: Span): Boolean {
        val exp = moduleAliases[name] ?: return false
        sink.error("`$name` shadows the imported module `${exp.modPath}`", span,
            "an imported module's alias and your names share one namespace; rename one")
        return true
    }

    /** A local top-level name may not collide with a selectively-imported name. */
    private fun importClash(name: String, span: Span, kind: String): Boolean {
        val from = importedNames[name] ?: return false
        sink.error("$kind `$name` conflicts with a name imported from `$from`", span,
            "drop the import or rename this $kind")
        return true
    }

    /** while checking a const initializer: only constants declared earlier are visible */
    private var constCutoff: Set<String>? = null

    /** const NAME: Type = expr — resolve and register the declared type (initializers come later) */
    private fun declareConst(d: ConstDecl) {
        if (aliasShadow(d.name, d.nameSpan) || importClash(d.name, d.nameSpan, "constant")) return
        currentTParams = emptyMap()
        currentEffVars = HashMap()
        val declared = resolveType(d.typeAnn)
        d.constType = declared
        d.resolvedAnn = declared
        if (!isConstSerializable(declared) && declared != TError) {
            sink.error("`$declared` is not a constant-serializable type", d.typeAnn.span,
                "constants hold Int/Float/Bool/String and List/tuple/record/ADT values built from them (spec §7.2)")
            d.constType = TError
        }
        when {
            ctors.containsKey(d.name) || adts.containsKey(d.name) || traitsByName.containsKey(d.name) ->
                sink.error("`${d.name}` collides with a type, trait, or constructor name", d.nameSpan)
            consts.containsKey(d.name) ->
                sink.error("constant `${d.name}` is defined twice", d.nameSpan)
            else -> {
                d.srcPath = srcPath
                consts[d.name] = d
            }
        }
    }

    /** the initializer must be pure, comptime-evaluable, and match the declared type */
    private fun checkConstInit(d: ConstDecl, visible: Set<String>) {
        val declared = d.resolvedAnn ?: return
        currentTParams = emptyMap()
        currentEffVars = HashMap()
        constCutoff = visible
        checkComptimeBody(d.init, expected = declared, what = "const initializers")?.let { bt ->
            if (!assignable(bt, declared))
                sink.error("`${d.name}` declares type $declared but its initializer is $bt", d.init.span)
        }
        constCutoff = null
    }

    /**
     * Check an implicitly-comptime body: fresh scope (no enclosing locals),
     * no enclosing function (`?` is rejected), and the result must be pure.
     * Returns the body type.
     */
    private fun checkComptimeBody(body: Expr, expected: Type?, what: String): Type? {
        val savedUsed = usedEffects
        val savedWitness = effWitness
        val savedSig = currentFnSig
        val savedDicts = dictSyms
        val savedScopes = ArrayList(scopes)
        val savedLambdas = ArrayList(lambdaStack)
        usedEffects = HashSet()
        effWitness = HashMap()
        currentFnSig = null
        dictSyms = emptyMap()
        scopes.clear()
        scopes.addLast(HashMap())
        lambdaStack.clear()
        val t = try {
            checkExpr(body, expected)
        } finally {
            for (used in usedEffects) {
                val (span, name) = effWitness[used] ?: (body.span to "?")
                sink.error("$what must be pure, but `$name` is !$used", span,
                    "compile-time evaluation cannot perform io (spec §7.2)")
            }
            usedEffects = savedUsed
            effWitness = savedWitness
            currentFnSig = savedSig
            dictSyms = savedDicts
            scopes.clear()
            scopes.addAll(savedScopes)
            lambdaStack.clear()
            lambdaStack.addAll(savedLambdas)
        }
        return t
    }

    /**
     * unsafe_pure { body } (docs/pure-ffi-design.md §3.2). Type-check the body
     * exactly as usual — locals stay in scope, `?` still works — but capture its
     * effects in isolation so we can decide what the stamp is allowed to hide:
     *
     *  - a concrete !io is masked to Pure (the whole point: a Java call can back
     *    a pure function);
     *  - an effect *variable* (!e from an effect-polymorphic callee like a
     *    higher-order `map`) is REJECTED — masking it would be a lie the value
     *    couldn't even honor when e = io, and it's the guard that forces
     *    higher-order code down the pure-Dawn-recursion path (§3.3);
     *  - a body that did no io at all makes the stamp a no-op → flagged, so every
     *    surviving `unsafe_pure` is load-bearing and `grep` yields the real trust
     *    list.
     */
    private fun checkUnsafePure(e: UnsafePureExpr, expected: Type?): Type {
        val savedUsed = usedEffects
        val savedWitness = effWitness
        usedEffects = HashSet()
        effWitness = HashMap()
        var inner: Set<Eff> = emptySet()
        val t = try {
            checkExpr(e.body, expected)
        } finally {
            inner = usedEffects
            usedEffects = savedUsed
            effWitness = savedWitness
        }
        val poly = inner.firstOrNull { it is Eff.Var || it is Eff.Union }
        when {
            poly != null -> error(
                "unsafe_pure cannot mask the effect variable !$poly — it only vouches that a concrete io effect is absent",
                e.span,
                "the block calls an effect-polymorphic function (e.g. a higher-order `map`/`fold`); " +
                    "rewrite it as pure Dawn recursion over first-order pure primitives (docs/pure-ffi-design.md §3.3)")
            Eff.Io !in inner && !t.isErrorish -> error(
                "redundant unsafe_pure: the block is already pure", e.span,
                "drop `unsafe_pure { … }` and keep the inner expression — the stamp is only for vouching " +
                    "a Java interop call the effect checker would otherwise flag !io")
        }
        // masked: the block's own !io is deliberately not folded back into savedUsed,
        // so the enclosing function sees this expression as Pure.
        return t
    }

    /** Int/Float/Bool/String and List/tuple/record/ADT built from them (spec §7.2). */
    private fun isConstSerializable(t: Type, visited: MutableSet<AdtInfo> = HashSet()): Boolean = when (t) {
        TInt, TFloat, TBool, TString -> true
        is TList -> isConstSerializable(t.elem, visited)
        is TTuple -> t.elems.all { isConstSerializable(it, visited) }
        is TAdt -> {
            if (!visited.add(t.info)) true // recursive types terminate here
            else {
                val instMap = t.info.typeParams.zip(t.args).toMap()
                t.args.all { isConstSerializable(it, visited) } &&
                    t.info.ctors.all { c ->
                        c.fields.all { isConstSerializable(subst(it.type, instMap), visited) }
                    }
            }
        }
        is TVar -> false // a comptime result must be a concrete value
        else -> false // functions, Unit, Never
    }

    private fun checkTest(t: TestDecl) {
        currentTParams = emptyMap()
        currentEffVars = HashMap()
        currentFnSig = null
        dictSyms = emptyMap()
        usedEffects = HashSet()
        effWitness = HashMap()
        lambdaStack.clear()
        scopes.clear()
        scopes.addLast(HashMap())
        inTest = true
        val bt = checkExpr(t.body, expected = TUnit)
        if (!assignable(bt, TUnit))
            sink.error("a test block's trailing value is discarded ($bt)", t.body.span,
                "assert on it instead of leaving it as the last expression")
        inTest = false
        scopes.removeLast()
        // test blocks may use io freely (spec §3.4): no effect verification
    }

    /** Resolve parsed effect atoms into a normalized Eff, interning variables per signature. */
    private fun resolveEff(atoms: List<String>, effVars: MutableMap<String, Eff.Var>): Eff =
        Eff.union(atoms.map { if (it == "io") Eff.Io else effVars.getOrPut(it) { Eff.Var(it) } })

    /** Resolve an alias target once, memoized; null (and an error) on a cycle. */
    private fun resolveAliasTarget(al: AliasInfo, useSpan: Span): Type? {
        al.resolved?.let { return if (it == TError) null else it }
        val ref = al.targetRef ?: return TError.also { al.resolved = it } // imported: always resolved
        if (al.resolving) {
            sink.error("type alias `${al.name}` refers to itself", useSpan,
                "aliases are transparent and cannot be recursive")
            al.resolved = TError
            return null
        }
        al.resolving = true
        val t = resolveType(ref, tparams = al.typeParams.associateBy { it.name }, effVars = HashMap())
        al.resolving = false
        al.resolved = t
        return if (t == TError) null else t
    }

    /** The span of the first effect variable inside an alias target, if any. */
    private fun aliasEffVarSpan(ref: TypeRef): Span? = when (ref) {
        is FnTypeRef ->
            if (ref.effAtoms.any { it != "io" }) ref.span
            else (ref.params + ref.ret).firstNotNullOfOrNull { aliasEffVarSpan(it) }
        is TupleTypeRef -> ref.elems.firstNotNullOfOrNull { aliasEffVarSpan(it) }
        is NamedTypeRef -> ref.args.firstNotNullOfOrNull { aliasEffVarSpan(it) }
        else -> null
    }

    private fun resolveType(
        ref: TypeRef,
        tparams: Map<String, TVar> = currentTParams,
        effVars: MutableMap<String, Eff.Var> = currentEffVars,
    ): Type {
        if (ref is TupleTypeRef) {
            val elems = ref.elems.map { resolveType(it, tparams, effVars) }
            for ((i, t) in elems.withIndex()) if (t == TUnit)
                sink.error("tuple elements cannot be Unit", ref.elems[i].span)
            return TTuple(elems.map { if (it == TUnit) TError else it })
        }
        if (ref is FnTypeRef) {
            val eff = resolveEff(ref.effAtoms, effVars)
            return TFn(ref.params.map { resolveType(it, tparams, effVars) },
                resolveType(ref.ret, tparams, effVars), eff)
        }
        ref as NamedTypeRef
        // type parameters shadow everything
        tparams[ref.name]?.let {
            if (ref.args.isNotEmpty()) {
                sink.error("type parameter `${ref.name}` cannot take type arguments", ref.span)
                return TError
            }
            return it
        }
        typeAliases[ref.name]?.let { al ->
            if (ref.args.size != al.typeParams.size) {
                sink.error("`${al.name}` takes ${al.typeParams.size} type parameter(s), got ${ref.args.size}",
                    ref.span)
                return TError
            }
            val target = resolveAliasTarget(al, ref.span) ?: return TError
            if (al.typeParams.isEmpty()) return target
            return subst(target,
                al.typeParams.zip(ref.args.map { resolveType(it, tparams, effVars) }).toMap())
        }
        if (ref.name == "List") {
            if (ref.args.size != 1) {
                sink.error("List takes exactly one type argument: List[T]", ref.span)
                return TError
            }
            return TList(resolveType(ref.args[0], tparams, effVars))
        }
        if (ref.name == "Map") {
            if (ref.args.size != 2) {
                sink.error("Map takes exactly two type arguments: Map[K, V]", ref.span)
                return TError
            }
            val k = resolveType(ref.args[0], tparams, effVars)
            checkKeyType(k, ref.args[0].span)
            return TMap(k, resolveType(ref.args[1], tparams, effVars))
        }
        if (ref.name == "Set") {
            if (ref.args.size != 1) {
                sink.error("Set takes exactly one type argument: Set[T]", ref.span)
                return TError
            }
            val el = resolveType(ref.args[0], tparams, effVars)
            checkKeyType(el, ref.args[0].span)
            return TSet(el)
        }
        Type.named(ref.name)?.let {
            if (ref.args.isNotEmpty()) {
                sink.error("`${ref.name}` is not generic", ref.span)
                return TError
            }
            return it
        }
        javaClasses[ref.name]?.let { cls ->
            if (ref.args.isNotEmpty()) {
                sink.error("Java types take no type arguments (generics are erased)", ref.span)
                return TError
            }
            return TJava(cls.name, cls)
        }
        val info = adts[ref.name] ?: run {
            sink.error("unknown type: ${ref.name}", ref.span,
                Suggest.hint(ref.name, adts.keys + typeAliases.keys + javaClasses.keys + builtinTypeNames)
                    ?: "builtin types: Int, Float, Bool, String, Unit, List — or declare `type ${ref.name} = ...`")
            return TError
        }
        if (ref.args.size != info.typeParams.size) {
            sink.error("`${info.name}` takes ${info.typeParams.size} type parameter(s), got ${ref.args.size}",
                ref.span)
            return TError
        }
        return TAdt(info, ref.args.map { resolveType(it, tparams, effVars) })
    }

    /**
     * Structural unification of a declared type (may contain the callee's type
     * and effect variables) against an actual argument type, accumulating bindings.
     */
    private fun unifyInto(
        declared: Type,
        actual: Type,
        map: HashMap<TVar, Type>,
        effMap: HashMap<Eff.Var, Eff> = HashMap(),
    ): Boolean = when {
        actual.isErrorish -> true
        declared is TVar -> {
            // Unit may instantiate a type parameter: it occupies the erased Object slot as the
            // dawn/rt/Unit singleton (like None), so T = Unit round-trips (box/unerase in codegen).
            val bound = map[declared]
            if (bound == null) { map[declared] = actual; true } else bound == actual
        }
        declared is TAdt && actual is TAdt ->
            declared.info === actual.info &&
                declared.args.zip(actual.args).all { (d, a) -> unifyInto(d, a, map, effMap) }
        declared is TList && actual is TList -> unifyInto(declared.elem, actual.elem, map, effMap)
        declared is TMap && actual is TMap ->
            unifyInto(declared.key, actual.key, map, effMap) && unifyInto(declared.value, actual.value, map, effMap)
        declared is TSet && actual is TSet -> unifyInto(declared.elem, actual.elem, map, effMap)
        declared is TTuple && actual is TTuple ->
            declared.elems.size == actual.elems.size &&
                declared.elems.zip(actual.elems).all { (d, a) -> unifyInto(d, a, map, effMap) }
        declared is TFn && actual is TFn ->
            declared.params.size == actual.params.size &&
                declared.params.zip(actual.params).all { (d, a) -> unifyInto(d, a, map, effMap) } &&
                unifyInto(declared.ret, actual.ret, map, effMap) &&
                unifyEff(declared.eff, actual.eff, effMap)
        else -> declared == actual
    }

    /** effect side of unification: pure ⊑ io; declared variables accumulate a lub */
    private fun unifyEff(declared: Eff, actual: Eff, effMap: HashMap<Eff.Var, Eff>): Boolean = when (declared) {
        Eff.Pure -> actual == Eff.Pure
        Eff.Io -> true
        is Eff.Var -> {
            effMap[declared] = lubEff(effMap[declared] ?: Eff.Pure, actual)
            true
        }
        // a union in a declared parameter position is not inferred into (which variable would bind?);
        // accept when the actual is already subsumed. Unions normally appear only in return position.
        is Eff.Union -> effSubsumes(substEff(declared, effMap), actual)
    }

    /** does this expression need an expected type to check at all? */
    private fun needsExpected(e: Expr): Boolean = when (e) {
        is ListLit -> e.elems.isEmpty() || e.elems.all { needsExpected(it) }
        is TupleLit -> e.elems.any { needsExpected(it) }
        // a generic function used as a value is instantiated from the expected type
        is VarRef -> lookup(e.name) == null &&
            (fns[e.name] ?: stdFns[e.name] ?: BUILTINS[e.name])?.typeParams?.isNotEmpty() == true
        is CtorCall -> {
            val ci = ctors[e.ctorName]
            ci != null && (
                // bare nullary generic constructor (e.g. None): element type comes from expected
                (ci.fields.isEmpty() && ci.adt.typeParams.isNotEmpty()) ||
                // bare constructor-with-fields as a function value (e.g. Some): needs the expected fn type
                (!e.hasParens && ci.fields.isNotEmpty() && !ci.adt.isRecord))
        }
        is Lambda -> e.params.any { it.typeAnn == null }
        // a zero-arg generic call (map_empty(), set_empty()) can only be typed from context
        is Call -> {
            val sig = if (lookup(e.callee) != null) null else (fns[e.callee] ?: stdFns[e.callee] ?: BUILTINS[e.callee])
            sig != null && sig.typeParams.isNotEmpty() && e.args.isEmpty()
        }
        else -> false
    }

    private fun checkFn(d: FnDecl) {
        val sig = d.sig!!
        currentTParams = sig.typeParams.associateBy { it.name }
        currentEffVars = HashMap(d.effVars)
        currentFnSig = sig
        bindDicts(sig)
        usedEffects = HashSet()
        effWitness = HashMap()
        lambdaStack.clear()
        scopes.clear()
        scopes.addLast(HashMap())
        for ((p, t) in d.params.zip(sig.paramTypes)) {
            p.symbol = declare(p.name, t, mutable = false, p.span)
        }
        val bodyType = checkExpr(d.body, expected = sig.ret)
        if (!assignable(bodyType, sig.ret))
            sink.error("function `${d.name}` declares return type ${sig.ret} but its body is $bodyType", d.body.span)
        // the signature is the promise: every used effect must be ⊑ the declared one
        for (used in usedEffects) {
            if (effSubsumes(sig.eff, used)) continue
            val (span, name) = effWitness[used] ?: (d.nameSpan to "?")
            sink.error(
                "function `${d.name}` is not declared !$used but calls `$name` (!$used)",
                span,
                "add !$used to the end of the signature, or remove the call",
            )
        }
        scopes.removeLast()
    }

    // ---- scopes ----

    private fun declare(name: String, type: Type, mutable: Boolean, span: Span): Symbol {
        if (name != "_" && scopes.last().containsKey(name))
            sink.error("`$name` is already bound in this scope", span,
                "let does not shadow; only nested blocks may reuse a name")
        aliasShadow(name, span)
        val sym = Symbol(name, type, mutable, span)
        if (name != "_") scopes.last()[name] = sym
        return sym
    }

    private fun lookup(name: String): Symbol? {
        for (i in scopes.indices.reversed()) scopes[i][name]?.let { return it }
        return null
    }

    /** Every name currently in scope — the candidate pool for "did you mean" on a variable. */
    private fun localNames(): List<String> = scopes.flatMap { it.keys }

    private val builtinTypeNames = listOf("Int", "Float", "Bool", "String", "Bytes", "Unit", "List", "Map", "Set")

    /**
     * Resolve a local name, doing lambda-capture bookkeeping: a symbol declared
     * outside an enclosing lambda's boundary is a capture (by value — vars are
     * rejected, spec §4.5).
     */
    private fun resolveLocal(name: String, span: Span, forAssign: Boolean = false): Symbol? {
        for (i in scopes.indices.reversed()) {
            val sym = scopes[i][name] ?: continue
            for (ctx in lambdaStack) {
                if (i < ctx.boundaryDepth) {
                    when {
                        forAssign -> sink.error("cannot assign to `$name` from inside a lambda", span,
                            "lambdas capture by value; use the result of the lambda instead")
                        sym.mutable -> sink.error("lambdas cannot capture `var` bindings (capture is by value)",
                            span, "bind it to a let before the lambda, or pass it as a parameter")
                        else -> ctx.captures.add(sym)
                    }
                }
            }
            return sym
        }
        return null
    }

    private fun <T> scoped(body: () -> T): T {
        scopes.addLast(HashMap())
        try {
            return body()
        } finally {
            scopes.removeLast()
        }
    }

    // ---- typing rules ----

    private fun error(msg: String, span: Span, hint: String? = null): Type {
        sink.error(msg, span, hint)
        return TError
    }

    /** can t be used where target is expected (Never/TError usable as anything; pure fn ⊑ io fn) */
    private fun assignable(t: Type, target: Type): Boolean =
        t == target || t.isErrorish || target == TError ||
            (t is TFn && target is TFn &&
                t.params == target.params && assignable(t.ret, target.ret) &&
                (target.eff == Eff.Io || t.eff == Eff.Pure || t.eff == target.eff))

    /** unify branch types (Never and TError are absorbed) */
    private fun unify(a: Type, b: Type, span: Span, what: String): Type = when {
        a == TNever || a == TError -> b
        b == TNever || b == TError -> a
        a == b -> a
        else -> error("$what have mismatched types: $a vs $b", span)
    }

    // ---- expressions ----

    private fun checkExpr(e: Expr, expected: Type? = null): Type {
        val t = inferExpr(e, expected)
        e.type = t
        return t
    }

    private fun inferExpr(e: Expr, expected: Type?): Type = when (e) {
        is IntLit -> TInt
        is FloatLit -> TFloat
        is BoolLit -> TBool
        is UnitLit -> TUnit
        is StrLit -> {
            for (p in e.parts) if (p is StrPart.Interp) {
                val t = checkExpr(p.expr)
                if (!isShowable(t) && !t.isErrorish)
                    error("cannot interpolate a value of type $t", p.expr.span, showHint(t))
            }
            TString
        }
        is VarRef -> {
            val sym = resolveLocal(e.name, e.span)
            if (sym != null) {
                e.symbol = sym
                sym.type
            } else {
                val f = fns[e.name] ?: stdFns[e.name] ?: BUILTINS[e.name]
                if (f != null) checkFnValue(e, f, expected)
                else error("undefined variable: ${e.name}", e.span,
                    Suggest.hint(e.name, localNames() + fns.keys + stdFns.keys + BUILTINS.keys))
            }
        }
        is MethodCall -> checkMethodCall(e, expected)
        is Lambda -> checkLambda(e, expected)
        is Apply -> checkApply(e)
        is Propagate -> checkPropagate(e)
        is Unwrap -> checkUnwrap(e)
        is Index -> checkIndex(e)
        is Return -> checkReturn(e)
        is ComptimeExpr -> {
            val t = checkComptimeBody(e.body, expected, what = "comptime blocks") ?: TError
            if (!isConstSerializable(t) && !t.isErrorish)
                error("a comptime result must be constant-serializable, got $t", e.span,
                    "Int/Float/Bool/String and List/tuple/record/ADT values of them (spec §7.2)")
            else t
        }
        is UnsafePureExpr -> checkUnsafePure(e, expected)
        is Call -> checkCall(e, expected)
        is CtorCall -> checkCtorCall(e, expected)
        is FieldAccess -> checkFieldAccess(e)
        is ListLit -> checkListLit(e, expected)
        is TupleLit -> checkTupleLit(e, expected)
        is Binary -> checkBinary(e)
        is Unary -> when (e.op) {
            UnOp.NOT -> {
                val t = checkExpr(e.operand)
                if (t != TBool && !t.isErrorish) error("not expects Bool, got $t", e.operand.span)
                else TBool
            }
            UnOp.NEG -> {
                val t = checkExpr(e.operand)
                if (!t.isNumeric && !t.isErrorish) error("negation expects a number, got $t", e.operand.span)
                else t
            }
            UnOp.BNOT -> {
                val t = checkExpr(e.operand)
                if (t != TInt && !t.isErrorish) error("`~` expects Int, got $t", e.operand.span)
                else TInt
            }
        }
        is If -> checkIf(e, expected)
        is Match -> checkMatch(e, expected)
        is Block -> checkBlock(e, expected)
    }

    private fun isConcrete(t: Type): Boolean = when (t) {
        // a rigid type parameter of the enclosing declaration is a known type;
        // only a callee's still-unbound inference variables are not
        is TVar -> t in currentTParams.values
        is TAdt -> t.args.all { isConcrete(it) }
        is TList -> isConcrete(t.elem)
        is TMap -> isConcrete(t.key) && isConcrete(t.value)
        is TSet -> isConcrete(t.elem)
        is TTuple -> t.elems.all { isConcrete(it) }
        else -> true
    }

    /** does the type contain a function anywhere? (functions cannot be compared, spec §4.3) */
    private fun containsFn(t: Type): Boolean = when (t) {
        is TFn -> true
        is TTuple -> t.elems.any { containsFn(it) }
        is TList -> containsFn(t.elem)
        is TMap -> containsFn(t.key) || containsFn(t.value)
        is TSet -> containsFn(t.elem)
        else -> false
    }

    /** x.f(a): module-qualified (alias.f), Java static (Class.m), Java instance (value.m), or UFCS f(x, a). */
    private fun checkMethodCall(e: MethodCall, expected: Type?): Type {
        val recv = e.target
        // module-qualified call: alias.fn(args), where alias is a whole-module import (spec §10.3)
        if (recv is VarRef && lookup(recv.name) == null && moduleAliases.containsKey(recv.name)) {
            return checkModuleCall(e, recv.name, moduleAliases.getValue(recv.name), expected)
        }
        // static namespace / constructor: System.exit(1), StringBuilder.new()
        if (recv is CtorCall && !recv.hasParens && recv.args.isEmpty() && recv.spread == null &&
            ctors[recv.ctorName] == null && consts[recv.ctorName] == null
        ) {
            javaClasses[recv.ctorName]?.let { cls ->
                recv.type = TUnit // a namespace, not a value; nothing is generated for it
                return checkJavaCall(e, cls, static = true)
            }
        }
        val tt = checkExpr(recv)
        if (tt is TJava) return checkJavaCall(e, tt.cls, static = false)
        if (tt.isErrorish) {
            for (a in e.args) checkExpr(a)
            return TError
        }
        // a record field holding a function: r.f(a) calls the field value. When a
        // function `f` is ALSO in scope the call is ambiguous and errors out (spec
        // §2.4) — silent precedence would let a new top-level fn change what
        // existing field calls mean from a distance, the same hazard §10.3 already
        // rejects for module aliases.
        if (tt is TAdt && tt.info.isRecord) {
            val ci = tt.info.ctors.first()
            val field = ci.fields.find { it.name == e.name }
            if (field != null) {
                val ftype = subst(field.type, tt.info.typeParams.zip(tt.args).toMap())
                val fnInScope = lookup(e.name) != null || fns[e.name] != null ||
                    stdFns.containsKey(e.name) || BUILTINS.containsKey(e.name)
                if (ftype is TFn && fnInScope) {
                    for (a in e.args) checkExpr(a)
                    return error(
                        "`${e.name}` is both a function in scope and a fn-typed field of `${tt.info.name}` — ambiguous call",
                        e.nameSpan,
                        "for the field, bind it first: `let g = <recv>.${e.name}` then `g(...)`; " +
                            "for the function, call it directly: `${e.name}(<recv>, ...)`")
                }
                if (ftype is TFn) {
                    val fa = FieldAccess(e.target, e.name, e.nameSpan,
                        Span(e.target.span.start, e.nameSpan.end))
                    fa.owner = ci
                    fa.field = field
                    fa.type = ftype
                    val ap = Apply(fa, e.args, e.span)
                    e.desugared = ap
                    if (e.args.size != ftype.params.size) {
                        for (a in e.args) checkExpr(a)
                        sink.error("`${e.name}` takes ${ftype.params.size} argument(s), got ${e.args.size}",
                            e.span, "field type: $ftype")
                        ap.type = ftype.ret
                        return ftype.ret
                    }
                    for ((arg, pt) in e.args.zip(ftype.params)) {
                        val at = checkExpr(arg, expected = pt)
                        if (!assignable(at, pt))
                            sink.error("argument type mismatch: expected $pt, got $at", arg.span)
                    }
                    recordEffect(ftype.eff, e.nameSpan, e.name)
                    ap.type = ftype.ret
                    return ftype.ret
                }
            }
        }
        // UFCS: x.f(a) is f(x, a) (spec §4.3); the receiver is already checked
        val call = Call(e.name, listOf(e.target) + e.args, e.nameSpan, e.span)
        e.desugared = call
        val t = checkCall(call, expected, preTyped = recv to tt)
        call.type = t
        return t
    }

    /** alias.fn(args): a call to a pub function of an imported module (spec §10.3). */
    private fun checkModuleCall(e: MethodCall, alias: String, exp: ModuleExports, expected: Type?): Type {
        (e.target as VarRef).type = TUnit // the alias is a namespace, not a value
        val sig = exp.fns[e.name]
        if (sig == null) {
            for (a in e.args) checkExpr(a)
            return if (e.name in exp.allNames)
                error("`${e.name}` is private to module `${exp.modPath}`", e.nameSpan,
                    "add `pub` to its declaration in ${exp.modPath}")
            else if (exp.types.containsKey(e.name) || exp.consts.containsKey(e.name))
                error("`${e.name}` is not a function; import it with `use ${exp.modPath}.{${e.name}}`",
                    e.nameSpan)
            else
                error("module `${exp.modPath}` has no exported function `${e.name}`", e.nameSpan,
                    Suggest.hint(e.name, exp.fns.keys))
        }
        // reuse the ordinary call machinery with the resolved (imported) signature
        val call = Call(e.name, e.args, e.nameSpan, e.span)
        e.desugared = call
        val t = checkCall(call, expected, resolvedSig = sig)
        call.type = t
        return t
    }

    /**
     * How well one Java candidate fits a call site (spec §9.3). Ordered by [phase]
     * first — a candidate that needs no varargs packing always beats one that does,
     * whatever the scores say — then by [score].
     */
    private data class Fit(val phase: Int, val score: Int) : Comparable<Fit> {
        override fun compareTo(other: Fit): Int =
            compareValuesBy(this, other, Fit::phase, Fit::score)
    }

    /** Overload resolution + type mapping for one Java call (spec §9). */
    private fun checkJavaCall(e: MethodCall, cls: Class<*>, static: Boolean): Type {
        recordEffect(Eff.Io, e.nameSpan, "${cls.simpleName}.${e.name}")
        // function-shaped arguments that need the target SAM to be typed (spec §9.4)
        // are deferred: scored by arity now, checked once the winner is known
        fun samDeferred(a: Expr): Boolean = when (a) {
            is Lambda -> a.params.any { it.typeAnn == null }
            is CtorCall -> !a.hasParens && a.spread == null && a.args.isEmpty() &&
                ctors[a.ctorName]?.fields?.isNotEmpty() == true
            else -> false
        }
        fun deferredArity(a: Expr): Int = when (a) {
            is Lambda -> a.params.size
            is CtorCall -> ctors[a.ctorName]!!.fields.size
            else -> 0
        }
        val argTypes: List<Type?> = e.args.map { if (samDeferred(it)) null else checkExpr(it) }
        fun checkDeferredBare() {
            for ((i, a) in e.args.withIndex()) if (argTypes[i] == null) checkExpr(a)
        }
        if (argTypes.any { it != null && it.isErrorish }) {
            checkDeferredBare()
            return TError
        }
        fun showArgs() = e.args.indices.joinToString(", ") { i ->
            argTypes[i]?.toString() ?: "fn/${deferredArity(e.args[i])}"
        }

        fun paramScore(p: Class<*>, i: Int): Int? = when (val a = argTypes[i]) {
            null -> // deferred lambda / bare constructor: match a convertible SAM by arity
                if (samMethodOf(p)?.let { samFnType(it)?.params?.size } == deferredArity(e.args[i])) 2
                else null
            TInt -> when (p) {
                java.lang.Long.TYPE -> 2
                Integer.TYPE -> 1
                else -> null
            }
            TFloat -> when (p) {
                java.lang.Double.TYPE -> 2
                java.lang.Float.TYPE -> 1
                else -> null
            }
            TBool -> if (p == java.lang.Boolean.TYPE) 2 else null
            TString -> when {
                p == String::class.java -> 2
                p.isAssignableFrom(String::class.java) -> 1
                else -> null
            }
            // Bytes is a raw byte[] at runtime, so it passes to Java byte[] params
            // (crypto digests, OutputStream.write, MessageDigest.isEqual) directly.
            Type.TBytes -> when {
                p == ByteArray::class.java -> 2
                !p.isPrimitive && p.isAssignableFrom(ByteArray::class.java) -> 1
                else -> null
            }
            is TJava -> when {
                p == a.cls -> 2
                p.isAssignableFrom(a.cls) -> 1
                // opaque value (erased generic → Object, spec §9.5) down-cast to a
                // specific reference param with a runtime CHECKCAST — the interop
                // escape for e.g. HttpResponse.body() (Object at compile time, byte[]
                // at runtime) flowing to OutputStream.write(byte[]).
                a.cls == Any::class.java && !p.isPrimitive -> 1
                else -> null
            }
            is TFn -> samMethodOf(p)?.let { sam ->
                val exp = samFnType(sam)
                if (exp != null && a.params == exp.params && samRetCompatible(a.ret, sam.returnType)) 2
                else null
            }
            // a Dawn List bridges to the three collection interfaces only (spec §9.6) —
            // never to Object, so the unmodifiable-view wrap is guaranteed
            is TList -> when (p) {
                java.util.List::class.java -> 2
                java.util.Collection::class.java, java.lang.Iterable::class.java -> 1
                else -> null
            }
            else -> null
        }

        // The i-th parameter as the argument at i sees it: inside a packed variadic
        // part that is the array's component type, not the array.
        fun paramAt(params: Array<Class<*>>, packs: Boolean, i: Int): Class<*> =
            if (packs && i >= params.size - 1) params.last().componentType else params[i]

        fun scoreWith(params: Array<Class<*>>, packs: Boolean): Int? {
            if (packs) { if (e.args.size < params.size - 1) return null }
            else if (params.size != e.args.size) return null
            var total = 0
            for (i in e.args.indices) total += paramScore(paramAt(params, packs, i), i) ?: return null
            return total
        }

        // Two-phase resolution (spec §9.3, after JLS): phase 1 tries every candidate
        // without varargs packing; only if that fails does phase 2 pack the trailing
        // arguments into the array. Equal arity does not settle it — `concat(p)` is a
        // phase-1 miss (a BodyPublisher is not a BodyPublisher[]) and a phase-2 hit.
        // The phase, not the score, decides first: scores are per-argument sums that
        // grow with arity, so a packing candidate can outscore an exact-arity one.
        fun score(params: Array<Class<*>>, isVarArgs: Boolean): Fit? {
            scoreWith(params, packs = false)?.let { return Fit(phase = 1, score = it) }
            if (isVarArgs) scoreWith(params, packs = true)?.let { return Fit(phase = 0, score = it) }
            return null
        }

        // the winner is known: type deferred arguments against their SAM's shape,
        // record fn-typed positions for the codegen bridge (spec §9.4), and
        // validate + record List-bridged positions (spec §9.6). Positions in a packed
        // variadic part resolve to the component type, so SAM conversion and the List
        // bridge work there too.
        fun finalizeSams(params: Array<Class<*>>, packs: Boolean) {
            val convs = HashMap<Int, SamConv>()
            val lists = HashSet<Int>()
            if (packs) e.varargsPack = params.size - 1
            for ((i, arg) in e.args.withIndex()) {
                val p = paramAt(params, packs, i)
                when (val at = argTypes[i]) {
                    null -> {
                        val sam = samMethodOf(p)!!
                        val exp = samFnType(sam)!!
                        val t = checkExpr(arg, exp)
                        if (t is TFn && t.params == exp.params && samRetCompatible(t.ret, sam.returnType))
                            convs[i] = SamConv(p, sam)
                        else if (!t.isErrorish)
                            sink.error("this function does not fit `${p.simpleName}`", arg.span,
                                "expected shape: $exp\n  single abstract method: $sam")
                    }
                    is TFn -> convs[i] = SamConv(p, samMethodOf(p)!!)
                    is TList -> {
                        // zero-copy bridge: elements cross as their boxed reps, so only
                        // scalars, String and Java references may cross (spec §9.6)
                        if (bridgeableElem(at.elem)) lists.add(i)
                        else sink.error(
                            "cannot bridge $at to `${p.simpleName}`: element type ${at.elem} does not cross",
                            arg.span,
                            "bridgeable elements: Int, Float, Bool, String, and Java classes; " +
                                "nested containers, ADTs, tuples and functions stay on the Dawn side (spec §9.6)")
                    }
                    else -> {}
                }
            }
            if (convs.isNotEmpty()) e.samConvs = convs
            if (lists.isNotEmpty()) e.listBridges = lists
        }

        if (e.name == "new") {
            if (!static)
                return error("`.new` is called on the class, not on an instance", e.nameSpan)
            val candidates = cls.constructors.filter { !it.isSynthetic }
            val scored = candidates.mapNotNull { c -> score(c.parameterTypes, c.isVarArgs)?.let { c to it } }
            val bestScore = scored.maxOfOrNull { it.second }
            val best = scored.filter { it.second == bestScore }
            return when {
                best.isEmpty() -> {
                    checkDeferredBare()
                    error(
                        "no constructor of `${cls.name}` matches (${showArgs()})",
                        e.span, "candidates:\n" + candidates.joinToString("\n") { "  $it" })
                }
                best.size > 1 -> {
                    checkDeferredBare()
                    error("ambiguous constructor call on `${cls.name}`", e.span,
                        "candidates:\n" + best.joinToString("\n") { "  ${it.first}" })
                }
                else -> {
                    val (c, m) = best.single()
                    e.javaCtorRef = c
                    finalizeSams(c.parameterTypes, packs = m.phase == 0)
                    // .new returns T — a constructor never returns null; a constructed
                    // java.lang.String is an ordinary Dawn String
                    if (cls == String::class.java) TString else TJava(cls.name, cls)
                }
            }
        }

        val sameName = cls.methods.filter {
            it.name == e.name && !it.isBridge && !it.isSynthetic &&
                java.lang.reflect.Modifier.isStatic(it.modifiers) == static
        }.distinctBy { m -> m.parameterTypes.joinToString(",") { it.name } }
        val scored = sameName.mapNotNull { m -> score(m.parameterTypes, m.isVarArgs)?.let { m to it } }
        val bestScore = scored.maxOfOrNull { it.second }
        val best = scored.filter { it.second == bestScore }
        return when {
            sameName.isEmpty() -> {
                checkDeferredBare()
                val shape = if (static) "Class.method(...) for statics" else "value.method(...) for instance methods"
                error(
                    "`${cls.name}` has no ${if (static) "static " else ""}method `${e.name}`", e.nameSpan,
                    "Java calls are $shape; fields are not supported in v0.1")
            }
            best.isEmpty() -> {
                checkDeferredBare()
                error(
                    "no overload of `${cls.simpleName}.${e.name}` matches (${showArgs()})",
                    e.span, "candidates:\n" + sameName.joinToString("\n") { "  $it" })
            }
            best.size > 1 -> {
                checkDeferredBare()
                error("ambiguous call to `${cls.simpleName}.${e.name}`", e.span,
                    "candidates:\n" + best.joinToString("\n") { "  ${it.first}" })
            }
            else -> {
                val (m, match) = best.single()
                e.javaMethod = m
                finalizeSams(m.parameterTypes, packs = match.phase == 0)
                mapJavaReturn(m.returnType, e)
            }
        }
    }

    /** Java return types → Dawn (spec §9.2): references land wrapped in Option. */
    private fun mapJavaReturn(rt: Class<*>, e: MethodCall): Type = when (rt) {
        java.lang.Void.TYPE -> TUnit
        java.lang.Long.TYPE, Integer.TYPE, java.lang.Short.TYPE, java.lang.Byte.TYPE -> TInt
        java.lang.Double.TYPE, java.lang.Float.TYPE -> TFloat
        java.lang.Boolean.TYPE -> TBool
        java.lang.Character.TYPE ->
            error("`char` returns are not supported in v0.1", e.nameSpan,
                "there is no char type; wrap the call in the standard library instead")
        String::class.java -> TAdt(OPTION_ADT, listOf(TString))
        // a Java byte[] return is a first-class Bytes now (spec §9.5): readAllBytes,
        // toByteArray, Base64.decode, etc. land as Option[Bytes], not opaque.
        ByteArray::class.java -> TAdt(OPTION_ADT, listOf(Type.TBytes))
        // other not-imported classes and arrays (spec §9.5) are still usable as
        // opaque values; importing is only needed to write the type name in a signature
        else -> TAdt(OPTION_ADT, listOf(TJava(rt.name, rt)))
    }

    /** The single abstract method of a functional interface, or null (spec §9.4). */
    private fun samMethodOf(p: Class<*>): java.lang.reflect.Method? {
        if (!p.isInterface) return null
        return p.methods
            .filter { java.lang.reflect.Modifier.isAbstract(it.modifiers) && !isObjectMethod(it) }
            .distinctBy { m -> m.name + m.parameterTypes.joinToString(",") { it.name } }
            .singleOrNull()
    }

    /** equals(Object)/hashCode()/toString() redeclared abstract on an interface don't count. */
    private fun isObjectMethod(m: java.lang.reflect.Method): Boolean = try {
        Any::class.java.getMethod(m.name, *m.parameterTypes); true
    } catch (_: NoSuchMethodException) {
        false
    }

    /**
     * SAM signature → the Dawn function type a converted argument must have
     * (spec §9.4). Callback parameters arrive unwrapped (null is a boundary
     * panic, not an Option); null when the SAM is not convertible (char).
     */
    private fun samFnType(sam: java.lang.reflect.Method): TFn? {
        val params = sam.parameterTypes.map { samParamType(it) ?: return null }
        val ret = when (sam.returnType) {
            java.lang.Void.TYPE -> TUnit
            java.lang.Long.TYPE, Integer.TYPE, java.lang.Short.TYPE, java.lang.Byte.TYPE -> TInt
            java.lang.Double.TYPE, java.lang.Float.TYPE -> TFloat
            java.lang.Boolean.TYPE -> TBool
            java.lang.Character.TYPE -> return null
            String::class.java -> TString
            else -> TJava(sam.returnType.name, sam.returnType)
        }
        return TFn(params, ret, Eff.Io)
    }

    private fun samParamType(p: Class<*>): Type? = when (p) {
        java.lang.Long.TYPE, Integer.TYPE, java.lang.Short.TYPE, java.lang.Byte.TYPE -> TInt
        java.lang.Double.TYPE, java.lang.Float.TYPE -> TFloat
        java.lang.Boolean.TYPE -> TBool
        java.lang.Character.TYPE -> null
        String::class.java -> TString
        else -> TJava(p.name, p)
    }

    /** Elements that may cross the List bridge as-is (spec §9.6): boxed scalars, String, Java refs. */
    private fun bridgeableElem(t: Type): Boolean =
        t == TInt || t == TFloat || t == TBool || t == TString || t is TJava

    /** May a Dawn return land where the SAM asks for [j]? (the boxed rep must be assignable) */
    private fun samRetCompatible(r: Type, j: Class<*>): Boolean = when (j) {
        java.lang.Void.TYPE -> r == TUnit || r == TNever
        java.lang.Long.TYPE, Integer.TYPE, java.lang.Short.TYPE, java.lang.Byte.TYPE -> r == TInt
        java.lang.Double.TYPE, java.lang.Float.TYPE -> r == TFloat
        java.lang.Boolean.TYPE -> r == TBool
        java.lang.Character.TYPE -> false
        else -> when (r) {
            TString -> j.isAssignableFrom(String::class.java)
            TInt -> j.isAssignableFrom(java.lang.Long::class.java)
            TFloat -> j.isAssignableFrom(java.lang.Double::class.java)
            TBool -> j.isAssignableFrom(java.lang.Boolean::class.java)
            is TJava -> j.isAssignableFrom(r.cls)
            TNever -> true
            else -> false
        }
    }

    /** A top-level function or builtin used as a value; generics need the expected type. */
    private fun checkFnValue(e: VarRef, f: FnSig, expected: Type?): Type {
        if (f.constraints.isNotEmpty()) {
            val ps = f.paramNames.joinToString(", ")
            return error(
                if (f.trait != null) "trait method `${e.name}` cannot be used as a value"
                else "`${e.name}` has trait bounds and cannot be used as a value",
                e.span, "wrap it in a lambda: fn($ps) => ${e.name}($ps)")
        }
        e.fnValue = f
        val declared = TFn(f.paramTypes, f.ret, f.eff)
        if (f.typeParams.isEmpty() && f.eff !is Eff.Var) return declared
        val exp = expected as? TFn
        if (exp == null || exp.params.size != f.paramTypes.size) {
            return error("cannot infer the type parameter(s) of `${e.name}` used as a value here", e.span,
                "wrap it in a lambda with annotated parameters: fn(x: Int) => ${e.name}(x)")
        }
        val map = HashMap<TVar, Type>()
        val effMap = HashMap<Eff.Var, Eff>()
        for ((d, a) in f.paramTypes.zip(exp.params)) if (isConcrete(a)) unifyInto(d, a, map, effMap)
        if (isConcrete(exp.ret)) unifyInto(f.ret, exp.ret, map, effMap)
        val unbound = f.typeParams.filter { it !in map }
        if (unbound.isNotEmpty()) {
            return error("cannot infer type parameter(s) ${unbound.joinToString(", ")} for `${e.name}` used as a value",
                e.span, "wrap it in a lambda with annotated parameters")
        }
        (f.eff as? Eff.Var)?.let { if (it !in effMap) effMap[it] = exp.eff }
        if (f.isBuiltin && f.name == "to_string")
            checkPrintable(map[f.typeParams[0]] ?: TError, e.span)
        return subst(declared, map, effMap)
    }

    /** A constructor used bare as a function value: `map(xs, Some)`. Generics come from [expected]. */
    private fun checkCtorValue(e: CtorCall, ci: CtorInfo, expected: TFn): Type {
        e.ctorValue = ci
        val adt = ci.adt
        val params = ci.fields.map { it.type }
        val ret = adt.type
        if (expected.params.size != params.size) {
            return error("`${ci.name}` takes ${params.size} field(s), but $expected is expected", e.span,
                "constructor: ${ci.render()}")
        }
        if (adt.typeParams.isEmpty()) return TFn(params, ret, Eff.Pure)
        val map = HashMap<TVar, Type>()
        for ((d, a) in params.zip(expected.params)) if (isConcrete(a)) unifyInto(d, a, map)
        if (isConcrete(expected.ret)) unifyInto(ret, expected.ret, map)
        val unbound = adt.typeParams.filter { it !in map }
        if (unbound.isNotEmpty()) {
            return error("cannot infer type parameter(s) ${unbound.joinToString(", ")} for `${ci.name}` used as a value",
                e.span, "annotate the surrounding context, or wrap it in a lambda")
        }
        return TFn(params.map { subst(it, map) }, subst(ret, map), Eff.Pure)
    }

    /** to_string / interpolation accept printable types: primitives, and `derive Show` values. */
    private fun checkPrintable(t: Type, span: Span) {
        if (!isShowable(t) && !t.isErrorish)
            sink.error("cannot print a value of type $t", span, showHint(t))
    }

    /** A concrete type is printable now: primitives, or containers/ADTs of printable types. */
    private fun isShowable(t: Type): Boolean = when (t) {
        TInt, TFloat, TBool, TString, Type.TBytes -> true
        is TList -> isShowable(t.elem)
        is TMap -> isShowable(t.key) && isShowable(t.value)
        is TSet -> isShowable(t.elem)
        is TTuple -> t.elems.all { isShowable(it) }
        is TAdt -> t.info.derivesShow && t.args.all { isShowable(it) }
        else -> false // TVar (opaque), TFn, TJava, Unit
    }

    /** A field type may derive Show: like [isShowable] but type parameters are allowed (resolved at use). */
    private fun isShowableField(t: Type): Boolean = when (t) {
        TInt, TFloat, TBool, TString, Type.TBytes, is TVar -> true
        is TList -> isShowableField(t.elem)
        is TMap -> isShowableField(t.key) && isShowableField(t.value)
        is TSet -> isShowableField(t.elem)
        is TTuple -> t.elems.all { isShowableField(it) }
        is TAdt -> t.info.derivesShow && t.args.all { isShowableField(it) }
        else -> false
    }

    /**
     * Map/Set keys need a hash that agrees with structural equality (spec §2.2). Two base
     * types can never provide one, anywhere inside the key: Float (NaN and -0.0 make `==`
     * and boxed equals disagree) and Bytes (byte[] hashes by identity, not content).
     * Values are unrestricted; a Map nested *inside a key* is checked on both sides
     * because its values join the outer key's equality. TVar passes — the concrete
     * creation site is where the rule bites.
     */
    private fun invalidKeyPart(t: Type, seen: MutableSet<String> = HashSet()): Type? = when (t) {
        TFloat, Type.TBytes -> t
        is TList -> invalidKeyPart(t.elem, seen)
        is TSet -> invalidKeyPart(t.elem, seen)
        is TMap -> invalidKeyPart(t.key, seen) ?: invalidKeyPart(t.value, seen)
        is TTuple -> t.elems.firstNotNullOfOrNull { invalidKeyPart(it, seen) }
        is TAdt -> if (!seen.add(t.info.name)) null else {
            val m = t.info.typeParams.zip(t.args).toMap()
            t.info.ctors.asSequence()
                .flatMap { it.fields.asSequence() }
                .firstNotNullOfOrNull { invalidKeyPart(subst(it.type, m), seen) }
        }
        else -> null
    }

    /** one report per offending key type per module — the annotation and every seeded call site would otherwise repeat it */
    private val reportedKeyTypes = HashSet<String>()

    private fun checkKeyType(keyT: Type, span: Span) {
        if (keyT.isErrorish) return
        val bad = invalidKeyPart(keyT) ?: return
        if (!reportedKeyTypes.add(keyT.toString())) return
        val inside = if (bad == keyT) "" else " (inside `$keyT`)"
        val why = if (bad == TFloat)
            "NaN and -0.0 give Float two different equalities, so no hash can agree with `==`"
        else "Bytes hashes by identity, not content"
        val hint = if (bad == TFloat)
            "key by an Int encoding (scaled integer, bits) or a String rendering instead"
        else "key by a String instead: decode(b, \"UTF-8\") or a hex rendering"
        sink.error("`$bad` cannot be part of a Map/Set key type$inside: $why", span, hint)
    }

    /** A targeted hint for why [t] is not printable. */
    private fun showHint(t: Type): String = when {
        t is TAdt && !t.info.derivesShow -> "add `derive Show` to `type ${t.info.name}`"
        t is TAdt -> "one of its type arguments is not printable"
        t is TVar -> "a type parameter is not printable; require a concrete printable type"
        t is TFn -> "functions cannot be printed"
        else -> "printable types are Int, Float, Bool, String, and `derive Show` values"
    }

    private fun checkCall(e: Call, expected: Type?, preTyped: Pair<Expr, Type>? = null,
                          resolvedSig: FnSig? = null): Type {
        // UFCS receivers are checked once by checkMethodCall; don't re-check them
        fun typeArg(arg: Expr, exp: Type? = null): Type =
            if (preTyped != null && arg === preTyped.first) preTyped.second
            else checkExpr(arg, expected = exp)
        // a qualified module call (module.fn) resolves to a fixed signature, bypassing locals
        val local = if (resolvedSig != null) null else resolveLocal(e.callee, e.calleeSpan)
        if (local != null) {
            val lt = local.type
            if (lt.isErrorish) {
                for (arg in e.args) typeArg(arg)
                return TError
            }
            if (lt !is TFn) {
                for (arg in e.args) typeArg(arg)
                return error("`${e.callee}` is not a function (it is $lt)", e.calleeSpan)
            }
            e.dynamicTarget = local
            if (e.args.size != lt.params.size) {
                for (arg in e.args) typeArg(arg)
                sink.error("`${e.callee}` takes ${lt.params.size} argument(s), got ${e.args.size}",
                    e.span, "type: $lt")
                return lt.ret
            }
            for ((arg, pt) in e.args.zip(lt.params)) {
                val at = typeArg(arg, pt)
                if (!assignable(at, pt))
                    sink.error("argument type mismatch: expected $pt, got $at", arg.span)
            }
            recordEffect(lt.eff, e.calleeSpan, e.callee)
            return lt.ret
        }
        val sig = resolvedSig ?: fns[e.callee] ?: stdFns[e.callee] ?: BUILTINS[e.callee]
        if (sig == null) {
            // still check the arguments so their subtrees get types/symbols
            for (arg in e.args) typeArg(arg)
            return error("undefined function: ${e.callee}", e.calleeSpan,
                Suggest.hint(e.callee, fns.keys + stdFns.keys + BUILTINS.keys))
        }
        e.sig = sig
        if (e.args.size != sig.paramTypes.size) {
            for (arg in e.args) typeArg(arg)
            sink.error("`${e.callee}` takes ${sig.paramTypes.size} argument(s), got ${e.args.size}",
                e.span, "signature: ${sig.render()}")
            return if (sig.typeParams.isEmpty()) sig.ret else TError
        }
        val map = HashMap<TVar, Type>()
        val effMap = HashMap<Eff.Var, Eff>()
        // seed inference from the expected result type (helps nested cases like Some(None))
        if (sig.typeParams.isNotEmpty() && expected != null && isConcrete(expected))
            unifyInto(sig.ret, expected, map, effMap)
        // two rounds: self-sufficient arguments first (they bind type variables),
        // then inference-needing ones (bare None, []) with what was learned
        val argTypes = arrayOfNulls<Type>(e.args.size)
        for (round in 0..1) {
            for ((i, arg) in e.args.withIndex()) {
                if (argTypes[i] != null) continue
                if (round == 0 && needsExpected(arg)) continue
                val substd = subst(sig.paramTypes[i], map)
                // lambdas only need their parameter types, and function values
                // unify piecewise — a partially concrete expected type still helps
                val exp = substd.takeIf { isConcrete(it) || arg is Lambda || arg is VarRef }
                val at = typeArg(arg, exp)
                argTypes[i] = at
                if (!unifyInto(sig.paramTypes[i], at, map, effMap))
                    sink.error("argument type mismatch: expected ${subst(sig.paramTypes[i], map)}, got $at",
                        arg.span, "signature: ${sig.render()}")
            }
        }
        // return-position inference: let x: Option[Int] = ...
        if (sig.typeParams.any { it !in map } && expected != null) unifyInto(sig.ret, expected, map, effMap)
        val unbound = sig.typeParams.filter { it !in map }
        if (unbound.isNotEmpty()) {
            return error("cannot infer type parameter(s) ${unbound.joinToString(", ")} for `${e.callee}`",
                e.span, "add a type annotation at the use site")
        }
        // trait bounds: each (type parameter, bound) pair needs a dictionary
        if (sig.constraints.isNotEmpty()) {
            val ws = ArrayList<WitnessRef>()
            var ok = true
            for ((i, tp) in sig.typeParams.withIndex()) {
                for (tr in sig.boundsOf(i)) {
                    val w = resolveWitness(tr, subst(tp, map), e.calleeSpan, "`${e.callee}`")
                    if (w == null) ok = false else ws.add(w)
                }
            }
            if (ok) e.witnesses = ws
        }
        if (sig.isBuiltin && sig.name == "to_string")
            checkPrintable(subst(sig.paramTypes[0], map), e.args[0].span)
        if (sig.isBuiltin && sig.name == "cast") {
            // T is bound here (an unbound type param already errored above). It must be a
            // reference type: CHECKCAST cannot target a primitive. See docs/cast-interop.md §三.
            val target = subst(sig.ret, map)
            if (target == TInt || target == TFloat || target == TBool)
                sink.error("`cast` target must be a reference type, not $target", e.span,
                    "cast reclaims an erased Java Object via CHECKCAST; primitive targets aren't supported")
        }
        // entry creators for Map/Set: the instantiated key type must be able to hash
        // consistently with `==` (spec §2.2) — Float/Bytes anywhere inside are rejected
        if (sig.isBuiltin && sig.name in KEYED_CREATORS) {
            when (val ret = subst(sig.ret, map)) {
                is TMap -> checkKeyType(ret.key, e.span)
                is TSet -> checkKeyType(ret.elem, e.span)
                else -> {}
            }
        }
        // instantiate the callee's effect: an unbound effect variable means pure
        val calleeEff = when (val ce = sig.eff) {
            is Eff.Var -> effMap[ce] ?: Eff.Pure
            else -> ce
        }
        recordEffect(calleeEff, e.calleeSpan, e.callee)
        return subst(sig.ret, map, effMap)
    }

    private fun checkCtorCall(e: CtorCall, expected: Type?): Type {
        val ci = ctors[e.ctorName]
        if (ci == null) {
            // a bare SCREAMING_SNAKE name may be a constant reference; inside a
            // const initializer only earlier constants are visible (spec §3.2)
            val cd = consts[e.ctorName]?.takeIf { constCutoff?.contains(e.ctorName) != false }
            if (cd != null) {
                if (e.hasParens || e.args.isNotEmpty() || e.spread != null)
                    return error("`${e.ctorName}` is a constant, not a constructor", e.calleeSpan)
                e.constDecl = cd
                return cd.constType ?: TError
            }
            e.spread?.let { checkExpr(it) }
            for (a in e.args) checkExpr(a.expr)
            return error("undefined constructor: ${e.ctorName}", e.calleeSpan,
                when {
                    adts.containsKey(e.ctorName) ->
                        "`${e.ctorName}` is a type; build a value with one of its constructors: " +
                            adts[e.ctorName]!!.ctors.joinToString(", ") { it.name }
                    e.ctorName in allConstNames ->
                        "const `${e.ctorName}` is declared later in the file; constants are evaluated top to bottom"
                    else -> Suggest.hint(e.ctorName, ctors.keys + consts.keys)
                })
        }
        e.ctor = ci
        val adt = ci.adt
        val n = ci.fields.size
        if (!e.hasParens && n > 0) {
            // a bare constructor with fields, in a function-typed position, is a function value
            if (!adt.isRecord && expected is TFn) return checkCtorValue(e, ci, expected)
            return error(
                if (adt.isRecord)
                    "record `${ci.name}` must be built with braces: ${ci.name} { ... }"
                else "constructor `${ci.name}` has $n field(s) and cannot be used bare",
                e.span, "constructor: ${ci.render()}")
        }
        // a bare nullary constructor where a function is expected: a value, not a function
        if (!e.hasParens && n == 0 && expected is TFn) {
            return error("`${ci.name}` is a value, not a function (it takes no fields)", e.span,
                "use it directly; only constructors with fields can be passed as functions")
        }
        val map = HashMap<TVar, Type>()
        // seed inference from the expected result type (helps nested cases like Some(None))
        if (adt.typeParams.isNotEmpty() && expected != null && isConcrete(expected))
            unifyInto(adt.type, expected, map)
        if (e.spread != null) {
            if (!adt.isRecord)
                sink.error("`..base` functional update only works on records", e.spread!!.span)
            val bt = checkExpr(e.spread!!, expected = adt.type.takeIf { isConcrete(it) })
            if (!unifyInto(adt.type, bt, map))
                sink.error("`..base` must be a ${adt.name}, got $bt", e.spread!!.span)
        }
        // resolve the argument → field mapping (positional prefix, then named)
        val slots = arrayOfNulls<Expr>(n)
        val idxOf = IntArray(e.args.size) { -1 }
        var sawNamed = false
        var argsBroken = false
        for ((i, a) in e.args.withIndex()) {
            val idx: Int
            if (a.name != null) {
                sawNamed = true
                idx = ci.fields.indexOfFirst { it.name == a.name }
                if (idx < 0) {
                    sink.error("`${ci.name}` has no field `${a.name}`", a.span,
                        Suggest.hint(a.name!!, ci.fields.map { it.name }) ?: "constructor: ${ci.render()}")
                    argsBroken = true
                    checkExpr(a.expr)
                    continue
                }
            } else {
                if (sawNamed) {
                    sink.error("positional arguments cannot follow named arguments", a.span)
                    argsBroken = true
                    checkExpr(a.expr)
                    continue
                }
                idx = i
                if (idx >= n) { checkExpr(a.expr); continue } // counted below
            }
            if (slots[idx] != null) {
                sink.error("field `${ci.fields[idx].name}` is given twice", a.span)
                argsBroken = true
                checkExpr(a.expr)
                continue
            }
            slots[idx] = a.expr
            idxOf[i] = idx
        }
        // two rounds of checking (see checkCall)
        val done = BooleanArray(e.args.size)
        for (round in 0..1) {
            for ((i, a) in e.args.withIndex()) {
                val idx = idxOf[i]
                if (idx < 0 || done[i]) continue
                if (round == 0 && needsExpected(a.expr)) continue
                done[i] = true
                val declared = ci.fields[idx].type
                val exp = subst(declared, map).takeIf { isConcrete(it) }
                val at = checkExpr(a.expr, expected = exp)
                if (!unifyInto(declared, at, map))
                    sink.error("field `${ci.fields[idx].name}` of `${ci.name}` is ${subst(declared, map)}, got $at",
                        a.expr.span, "constructor: ${ci.render()}")
            }
        }
        if (!argsBroken) {
            val missing = ci.fields.filterIndexed { i, _ -> slots[i] == null }
            if (e.args.size > n)
                sink.error("`${ci.name}` takes $n field(s), got ${e.args.size}", e.span,
                    "constructor: ${ci.render()}")
            else if (missing.isNotEmpty() && e.spread == null)
                sink.error("missing field(s) in `${ci.name}`: ${missing.joinToString(", ") { it.name }}",
                    e.span, "constructor: ${ci.render()}")
        }
        // with a spread, unspecified fields come from the base
        if (slots.all { it != null } || e.spread != null) e.fieldExprs = slots.toList()
        // instantiate the type arguments; fall back to the expected type (bare None etc.)
        if (adt.typeParams.any { it !in map } && expected != null) unifyInto(adt.type, expected, map)
        val unbound = adt.typeParams.filter { it !in map }
        if (unbound.isNotEmpty()) {
            return error("cannot infer type parameter(s) ${unbound.joinToString(", ")} for `${ci.name}`",
                e.span, "add a type annotation, e.g. let x: ${adt.name}[...] = ${ci.name}")
        }
        return subst(adt.type, map)
    }

    /**
     * fn name(params) -> T [!io] = body, statement form. The name is declared
     * before the body is checked, so the body can call it (recursion); the
     * self-capture is then dropped — codegen calls the impl method directly.
     */
    private fun checkLocalFn(s: LocalFnStmt) {
        val paramTypes = s.lambda.params.map { p ->
            var t = resolveType(p.typeAnn!!)
            if (t == TUnit) {
                sink.error("function parameters cannot be Unit", p.span)
                t = TError
            }
            t
        }
        val ret = resolveType(s.retRef)
        val eff = when {
            s.effNames.isEmpty() -> Eff.Pure
            s.effNames == listOf("io") -> Eff.Io
            else -> {
                sink.error("local functions cannot declare effect variables", s.nameSpan,
                    "a local function is `!io` or pure; lift it to the top level for effect polymorphism")
                Eff.Io
            }
        }
        val ft = TFn(paramTypes, ret, eff)
        val sym = declare(s.name, ft, mutable = false, s.nameSpan)
        s.symbol = sym
        val actual = checkLambda(s.lambda, expected = ft)
        if (actual is TFn) {
            if (!assignable(actual.ret, ret))
                sink.error("the body of `${s.name}` has type ${actual.ret} but the declared return type is $ret",
                    s.lambda.body.span)
            if (actual.eff == Eff.Io && eff == Eff.Pure)
                sink.error("the body of `${s.name}` performs io", s.nameSpan,
                    "declare it: fn ${s.name}(...) -> $ret !io = ...")
        }
        // the declared signature is canonical (the body type may be narrower, e.g. Never)
        s.lambda.fnType = ft
        s.lambda.captures = s.lambda.captures!!.filterNot { it === sym }
    }

    private fun checkLambda(e: Lambda, expected: Type?): Type {
        val exp = expected as? TFn
        if (exp != null && exp.params.size != e.params.size)
            sink.error("this lambda takes ${e.params.size} parameter(s), but $exp is expected", e.span)
        val paramTypes = e.params.mapIndexed { i, p ->
            var t = p.typeAnn?.let { resolveType(it) }
                // take the parameter type from the expected fn type; an enclosing function's
                // type parameter (a TVar) is a legitimate opaque parameter type here
                ?: exp?.params?.getOrNull(i)?.takeIf { isConcrete(it) || it is TVar }
                ?: run {
                    sink.error("cannot infer the type of `${p.name}`", p.span,
                        "annotate it: fn(${p.name}: Int) => ...")
                    TError
                }
            if (t == TUnit) {
                sink.error("lambda parameters cannot be Unit", p.span)
                t = TError
            }
            t
        }
        // the lambda's effects are its own — they happen when it is called
        val savedUsed = usedEffects
        val savedWitness = effWitness
        usedEffects = HashSet()
        effWitness = HashMap()
        val ctx = LambdaCtx(scopes.size, exp?.ret?.takeIf { isConcrete(it) })
        lambdaStack.addLast(ctx)
        val bodyType = scoped {
            e.params.forEachIndexed { i, p -> p.symbol = declare(p.name, paramTypes[i], mutable = false, p.span) }
            checkExpr(e.body, expected = exp?.ret?.takeIf { isConcrete(it) })
        }
        lambdaStack.removeLast()
        val lambdaEff = usedEffects.fold(Eff.Pure as Eff) { acc, x -> lubEff(acc, x) }
        usedEffects = savedUsed
        effWitness = savedWitness
        e.captures = ctx.captures.toList()
        val t = TFn(paramTypes, bodyType, lambdaEff)
        e.fnType = t
        return t
    }

    private fun checkApply(e: Apply): Type {
        val target = e.target
        var preArgTypes: List<Type>? = null
        val ft: Type
        if (target is Lambda && target.params.any { it.typeAnn == null }) {
            // piping into a lambda: the arguments determine its parameter types
            preArgTypes = e.args.map { checkExpr(it) }
            ft = checkExpr(target, expected = TFn(preArgTypes, TNever, Eff.Io))
        } else {
            ft = checkExpr(target)
        }
        if (ft.isErrorish) {
            if (preArgTypes == null) for (arg in e.args) checkExpr(arg)
            return TError
        }
        if (ft !is TFn) {
            if (preArgTypes == null) for (arg in e.args) checkExpr(arg)
            return error("cannot call a value of type $ft", e.target.span)
        }
        if (e.args.size != ft.params.size) {
            if (preArgTypes == null) for (arg in e.args) checkExpr(arg)
            sink.error("this function takes ${ft.params.size} argument(s), got ${e.args.size}", e.span,
                "type: $ft")
            return ft.ret
        }
        if (preArgTypes == null) {
            for ((arg, pt) in e.args.zip(ft.params)) {
                val at = checkExpr(arg, expected = pt)
                if (!assignable(at, pt))
                    sink.error("argument type mismatch: expected $pt, got $at", arg.span)
            }
        } else {
            for ((i, at) in preArgTypes.withIndex()) {
                if (!assignable(at, ft.params[i]))
                    sink.error("argument type mismatch: expected ${ft.params[i]}, got $at", e.args[i].span)
            }
        }
        recordEffect(ft.eff, e.target.span, "the applied function")
        return ft.ret
    }

    /** xs[i] / m[k] — the asserting variants: absence is a bug, so they panic (spec §4.8) */
    private fun checkIndex(e: Index): Type {
        val tt = checkExpr(e.target)
        return when (tt) {
            is Type.TList -> {
                val it = checkExpr(e.index, TInt)
                if (it != TInt && !it.isErrorish)
                    error("a List index must be Int, got $it", e.index.span)
                else tt.elem
            }
            is Type.TMap -> {
                val kt = checkExpr(e.index, tt.key)
                if (kt != tt.key && !kt.isErrorish)
                    error("this Map has keys of type ${tt.key}, got $kt", e.index.span)
                else tt.value
            }
            else -> {
                if (tt.isErrorish) TError
                else error("`[]` indexes a List or Map, got $tt", e.span,
                    "when absence is a normal case, use get(xs, i) / map_get(m, k) instead")
            }
        }
    }

    /** return / return expr — early return from the enclosing fn (or lambda, inside one) */
    private fun checkReturn(e: Return): Type {
        // inside a lambda, return exits the lambda — its return type must be known
        val target = if (lambdaStack.isNotEmpty()) {
            lambdaStack.last().expectedRet
                ?: return error("`return` inside a lambda needs the lambda's return type to be known from context",
                    e.span, "make the expected function type explicit, or drop the return")
        } else {
            val fs = currentFnSig
                ?: return error("`return` can only be used inside a function", e.span)
            if (fs.inferring)
                return error("`return` needs the function's return type to be declared", e.span,
                    "add `-> T` to fn ${fs.name}(...)")
            fs.ret
        }
        val vt = if (e.value != null) checkExpr(e.value, target) else TUnit
        if (!assignable(vt, target))
            error("`return` type mismatch: this function returns $target, got $vt",
                e.value?.span ?: e.span)
        return TNever
    }

    /** expr? — spec §8.1: unwrap Ok/Some, or return the Err/None from the enclosing fn */
    private fun checkPropagate(e: Propagate): Type {
        val ot = checkExpr(e.operand)
        if (ot.isErrorish) return TError
        // inside a lambda, ? returns from the lambda — its return type must be known
        val sigRet = if (lambdaStack.isNotEmpty()) {
            lambdaStack.last().expectedRet
                ?: return error("`?` inside a lambda needs the lambda's return type to be known from context",
                    e.span, "handle the Option/Result with match, or make the expected function type explicit")
        } else {
            val fs = currentFnSig
                ?: return error("`?` can only be used inside a function that returns Option or Result", e.span)
            if (fs.inferring)
                return error("`?` needs the function's return type to be declared", e.span,
                    "add `-> Option[...]` / `-> Result[...]` to fn ${fs.name}(...)")
            fs.ret
        }
        return when {
            ot is TAdt && ot.info === OPTION_ADT -> {
                if (sigRet !is TAdt || sigRet.info !== OPTION_ADT)
                    error("`?` on an Option requires the function to return Option[...], but it returns $sigRet",
                        e.span)
                else ot.args[0]
            }
            ot is TAdt && ot.info === RESULT_ADT -> {
                if (sigRet !is TAdt || sigRet.info !== RESULT_ADT)
                    error("`?` on a Result requires the function to return Result[...], but it returns $sigRet",
                        e.span)
                else if (sigRet.args[1] != ot.args[1])
                    error("`?` error types differ: $ot vs $sigRet", e.span,
                        "v0.1 has no automatic error conversion; match and rewrap the error")
                else ot.args[0]
            }
            else -> error("`?` needs an Option or Result, got $ot", e.span,
                "`?` unwraps an Option or Result and early-returns on None/Err; this value is neither")
        }
    }

    /** expr! — Option[T] -> T, panicking on None (spec §8.2). */
    private fun checkUnwrap(e: Unwrap): Type {
        val ot = checkExpr(e.operand)
        if (ot.isErrorish) return TError
        if (ot !is TAdt || ot.info !== OPTION_ADT) {
            val hint = if (ot is TAdt && ot.info === RESULT_ADT)
                "`!` unwraps an Option; on a Result use `?` to propagate, or match the Ok/Err"
            else
                "`!` unwraps an Option and panics on None; this value is not an Option"
            return error("`!` needs an Option, got $ot", e.span, hint)
        }
        e.panicMsg = unwrapMsg(e)
        return ot.args[0]
    }

    /**
     * The panic message for `expr!`, written here because codegen has neither the source
     * text nor a line-number table. Naming the call that produced the None, and where it
     * sits, is the whole point of `!` over a hand-written `.expect("b-uri")`.
     */
    private fun unwrapMsg(e: Unwrap): String {
        val sb = StringBuilder("unwrapped None")
        describeUnwrapped(e.operand)?.let { sb.append(" from ").append(it) }
        unwrapSite(e.span)?.let { sb.append(" at ").append(it) }
        return sb.toString()
    }

    /** Best-effort "what produced this Option" for the message; null when it is not a call. */
    private fun describeUnwrapped(op: Expr): String? = when (op) {
        is MethodCall -> when (val recv = op.target) {
            is CtorCall -> "${recv.ctorName}.${op.name}()"
            is VarRef -> "${recv.name}.${op.name}()"
            else -> "${op.name}()"
        }
        is Call -> "${op.callee}()"
        else -> null
    }

    /** "path:line" when the source text was handed in, else the path alone, else nothing. */
    private fun unwrapSite(span: Span): String? {
        val f = srcFile ?: return srcPath
        return "${f.path}:${f.lineOf(span.start)}"
    }

    private val srcFile: SourceFile? =
        srcText?.let { SourceFile(srcPath ?: "<input>", it) }

    private fun checkFieldAccess(e: FieldAccess): Type {
        val tt = checkExpr(e.target)
        if (tt.isErrorish) return TError
        if (tt !is TAdt || !tt.info.isRecord)
            return error("`.` field access needs a record value, got $tt", e.fieldSpan,
                if (tt is TAdt) "`${tt.info.name}` is a sum type; destructure it with match" else null)
        val ci = tt.info.ctors.first()
        val field = ci.fields.find { it.name == e.fieldName }
            ?: return error("`${tt.info.name}` has no field `${e.fieldName}`", e.fieldSpan,
                Suggest.hint(e.fieldName, ci.fields.map { it.name })
                    ?: "fields: ${ci.fields.joinToString(", ") { it.name }}")
        e.owner = ci
        e.field = field
        return subst(field.type, tt.info.typeParams.zip(tt.args).toMap())
    }

    private fun checkTupleLit(e: TupleLit, expected: Type?): Type {
        val exp = expected as? TTuple
        val types = e.elems.mapIndexed { i, el ->
            val t = checkExpr(el, expected = exp?.elems?.getOrNull(i)?.takeIf { isConcrete(it) })
            if (t == TUnit) {
                sink.error("tuple elements cannot be Unit", el.span)
                TError
            } else t
        }
        return TTuple(types)
    }

    private fun checkListLit(e: ListLit, expected: Type?): Type {
        val expectedElem = (expected as? TList)?.elem?.takeIf { isConcrete(it) }
        if (e.elems.isEmpty()) {
            return TList(expectedElem
                ?: return error("cannot infer the element type of an empty list", e.span,
                    "add a type annotation: let xs: List[Int] = []"))
        }
        var elemT: Type = expectedElem ?: TNever
        // inference-needing elements (bare None, nested []) go last
        val order = e.elems.sortedBy { needsExpected(it) }
        for (el in order) {
            val t = checkExpr(el, expected = elemT.takeIf { it != TNever && isConcrete(it) })
            elemT = unify(elemT, t, el.span, "the list elements")
        }
        return TList(elemT)
    }

    private fun checkBinary(e: Binary): Type {
        val lt = checkExpr(e.left)
        // == seeds the right side with the left side's type (Ok(14) infers its E
        // from the other operand)
        val eqLike = e.op == BinOp.EQ || e.op == BinOp.NEQ
        val rt = checkExpr(e.right, expected = lt.takeIf { eqLike && isConcrete(it) })
        // one side already failed: pick a plausible result type, stay silent
        if (lt.isErrorish || rt.isErrorish) return when (e.op) {
            BinOp.ADD, BinOp.SUB, BinOp.MUL, BinOp.DIV, BinOp.MOD ->
                if (lt.isNumeric) lt else if (rt.isNumeric) rt else TError
            BinOp.BAND, BinOp.BOR, BinOp.BXOR, BinOp.SHL, BinOp.SHR, BinOp.USHR -> TInt
            BinOp.CONCAT -> if (lt is TList) lt else if (rt is TList) rt else TString
            else -> TBool
        }
        fun bothNumericSame(): Type {
            if (!lt.isNumeric) return error("arithmetic expects numbers, left side is $lt", e.left.span)
            if (lt != rt) return error("both sides must have the same type: $lt vs $rt", e.opSpan,
                if (rt.isNumeric) "there are no implicit conversions; use to_float() (M1) or unify the literal types" else null)
            return lt
        }
        // bitwise operators are Int-only (no Float bit pattern in the surface language)
        fun bothInt(): Type {
            if (lt != TInt) return error("bitwise operators expect Int, left side is $lt", e.left.span)
            if (rt != TInt) return error("bitwise operators expect Int, right side is $rt", e.right.span)
            return TInt
        }
        return when (e.op) {
            BinOp.ADD, BinOp.SUB, BinOp.MUL, BinOp.DIV, BinOp.MOD -> bothNumericSame()
            BinOp.BAND, BinOp.BOR, BinOp.BXOR, BinOp.SHL, BinOp.SHR, BinOp.USHR -> bothInt()
            BinOp.CONCAT -> when {
                lt == TString && rt == TString -> TString
                lt == Type.TBytes && rt == Type.TBytes -> Type.TBytes
                lt is TList && rt is TList ->
                    if (lt != rt) error("`++` needs lists of the same element type: $lt vs $rt", e.opSpan)
                    else lt
                else -> error("`++` concatenates Strings, Bytes or Lists, got $lt ++ $rt", e.opSpan,
                    "use + for numbers; interpolation \"{x}{y}\" also builds strings")
            }
            BinOp.EQ, BinOp.NEQ -> {
                if (containsFn(lt) || containsFn(rt))
                    error("functions cannot be compared", e.opSpan,
                        "compare the values they produce, not the functions themselves")
                else if (lt != rt) error("== requires both sides to have the same type: $lt vs $rt", e.opSpan)
                else TBool
            }
            BinOp.LT, BinOp.LE, BinOp.GT, BinOp.GE -> {
                if (lt != rt) error("comparison requires both sides to have the same type: $lt vs $rt", e.opSpan)
                else if (lt == TInt || lt == TFloat || lt == TString) TBool // native fast path
                else {
                    e.ordWitness = resolveOrdWitness(lt, e.opSpan)
                    TBool
                }
            }
            BinOp.AND, BinOp.OR -> {
                if (lt != TBool) error("logical operators expect Bool, left side is $lt", e.left.span)
                else if (rt != TBool) error("logical operators expect Bool, right side is $rt", e.right.span)
                else TBool
            }
        }
    }

    private fun checkIf(e: If, expected: Type?): Type {
        val ct = checkExpr(e.cond)
        if (ct != TBool && !ct.isErrorish) sink.error("if condition must be Bool, got $ct", e.cond.span)
        val tt = checkExpr(e.thenBranch, expected)
        return if (e.elseBranch == null) {
            // no else: statement position only, branch must be Unit
            if (tt != TUnit && !tt.isErrorish)
                error("an if without else is a statement, so its branch must be Unit (got $tt)", e.thenBranch.span,
                    "add an else branch to produce a value")
            else TUnit
        } else {
            val et = checkExpr(e.elseBranch, expected)
            unify(tt, et, e.span, "the if branches")
        }
    }

    private fun checkMatch(e: Match, expected: Type?): Type {
        val st = checkExpr(e.scrutinee)
        val scrutOk = st in listOf(TInt, TFloat, TString, TBool) || st is TAdt || st is TTuple || st is TList
        if (!scrutOk && !st.isErrorish)
            sink.error("match supports Int/Float/String/Bool, tuples, lists and user-defined types, got $st",
                e.scrutinee.span)

        var result: Type = TNever

        for (arm in e.arms) {
            scoped {
                if (arm.patterns.size > 1) {
                    // or-patterns must not bind: each alternative would need identical bindings
                    for (p in arm.patterns) if (bindsAnything(p))
                        sink.error("or-pattern alternatives cannot introduce bindings", p.span)
                }
                for (p in arm.patterns) checkPattern(p, st)
                if (arm.guard != null) {
                    val gt = checkExpr(arm.guard)
                    if (gt != TBool && !gt.isErrorish) sink.error("guard must be Bool, got $gt", arm.guard.span)
                }
                val bt = checkExpr(arm.body, expected)
                result = unify(result, bt, arm.body.span, "the match arms")
            }
        }

        // exhaustiveness (guarded arms can fail their guard, so they don't count)
        if (scrutOk) {
            val rows = e.arms.filter { it.guard == null }
                .flatMap { arm -> arm.patterns.map { listOf(toSPat(it)) } }
            val tys = listOf(st)
            if (useful(rows, listOf(SWild), tys)) {
                val missing = when {
                    st is TAdt -> st.info.ctors
                        .filter { c -> useful(rows, listOf(SCtor(c, List(c.fields.size) { SWild })), tys) }
                        .joinToString(", ") { it.name }
                    st == TBool -> listOf(true, false)
                        .filter { v -> useful(rows, listOf(SLit(v)), tys) }
                        .joinToString(", ")
                    st is TList -> missingListPatterns(rows, st).joinToString(", ")
                    else -> "_ ($st has too many values to enumerate)"
                }
                sink.error("non-exhaustive match, missing: $missing", e.span,
                    if (st is TAdt) "add arms for the missing constructors, or a catch-all _"
                    else "add an unguarded catch-all arm (a binding or _)")
            }
        }
        return result
    }

    /** does the pattern introduce any binding (recursively)? */
    private fun bindsAnything(p: Pattern): Boolean = when (p) {
        is BindPat -> true
        is CtorPat -> p.args.any { bindsAnything(it.pattern) }
        is TuplePat -> p.elems.any { bindsAnything(it) }
        is ListPat -> p.restName != null || (p.pre + p.post).any { bindsAnything(it) }
        else -> false
    }

    /** first refutable subpattern, or null if [p] always matches (let destructuring, spec §5.2) */
    private fun refutablePart(p: Pattern): Pattern? = when (p) {
        is WildPat, is BindPat -> null
        is LitPat -> p
        is TuplePat -> p.elems.firstNotNullOfOrNull { refutablePart(it) }
        is ListPat ->
            // only [..rest] matches every list; any fixed element constrains the length
            if (p.hasRest && p.pre.isEmpty() && p.post.isEmpty()) null else p
        is CtorPat -> {
            val ci = ctors[p.ctorName]
            if (ci != null && ci.adt.ctors.size > 1) p
            else p.args.firstNotNullOfOrNull { refutablePart(it.pattern) }
        }
    }

    private fun checkPattern(p: Pattern, scrutType: Type, mutable: Boolean = false) {
        when (p) {
            is WildPat -> {}
            is BindPat -> {
                p.symbol = declare(p.name, scrutType, mutable, p.span)
            }
            is LitPat -> {
                val lt = checkExpr(p.lit)
                if (lt != scrutType && !scrutType.isErrorish && !lt.isErrorish)
                    sink.error("pattern type $lt does not match scrutinee type $scrutType", p.span)
            }
            is TuplePat -> {
                if (scrutType is TTuple && scrutType.elems.size == p.elems.size) {
                    p.elemTypes = scrutType.elems
                    for ((sub, t) in p.elems.zip(scrutType.elems)) checkPattern(sub, t, mutable)
                } else {
                    if (!scrutType.isErrorish)
                        sink.error(
                            if (scrutType is TTuple)
                                "this pattern has ${p.elems.size} elements but the scrutinee is $scrutType"
                            else "tuple pattern does not match scrutinee type $scrutType",
                            p.span,
                            if (scrutType is TTuple)
                                "a tuple pattern must bind exactly ${scrutType.elems.size} element(s)"
                            else "match a tuple pattern only against a tuple value")
                    p.elemTypes = List(p.elems.size) { TError }
                    for (sub in p.elems) checkPattern(sub, TError, mutable)
                }
            }
            is ListPat -> {
                val elem: Type = if (scrutType is TList) scrutType.elem else {
                    if (!scrutType.isErrorish)
                        sink.error("list pattern does not match scrutinee type $scrutType", p.span)
                    TError
                }
                p.elemType = elem
                for (sub in p.pre) checkPattern(sub, elem, mutable)
                for (sub in p.post) checkPattern(sub, elem, mutable)
                if (p.restName != null)
                    p.restSymbol = declare(p.restName, TList(elem), mutable, p.restSpan!!)
            }
            is CtorPat -> checkCtorPat(p, scrutType, mutable)
        }
    }

    private fun checkCtorPat(p: CtorPat, scrutType: Type, mutable: Boolean = false) {
        val ci = ctors[p.ctorName]
        if (ci == null) {
            sink.error("undefined constructor in pattern: ${p.ctorName}", p.nameSpan,
                Suggest.hint(p.ctorName, ctors.keys))
            // still check subpatterns so their bindings exist (as TError)
            for (a in p.args) checkPattern(a.pattern, TError, mutable)
            return
        }
        p.ctor = ci
        if (scrutType !is TAdt || scrutType.info !== ci.adt) {
            if (!scrutType.isErrorish)
                sink.error("`${p.ctorName}` is a ${ci.adt.name} constructor, but the scrutinee is $scrutType",
                    p.nameSpan)
        }
        // instantiate field types with the scrutinee's type arguments
        val instMap: Map<TVar, Type> =
            if (scrutType is TAdt && scrutType.info === ci.adt) ci.adt.typeParams.zip(scrutType.args).toMap()
            else emptyMap()
        val fieldTypes = ci.fields.map { subst(it.type, instMap) }
        p.fieldTypes = fieldTypes
        val n = ci.fields.size
        if (!p.hasParens && n > 0) {
            sink.error("constructor `${ci.name}` has $n field(s); a bare name does not match it", p.span,
                "write ${ci.name}(..) to ignore the fields, or destructure them")
            for (a in p.args) checkPattern(a.pattern, TError, mutable)
            return
        }
        val slots = arrayOfNulls<Pattern>(n)
        var sawNamed = false
        for ((i, a) in p.args.withIndex()) {
            val idx: Int
            if (a.name != null) {
                sawNamed = true
                idx = ci.fields.indexOfFirst { it.name == a.name }
                if (idx < 0) {
                    sink.error("`${ci.name}` has no field `${a.name}`", a.pattern.span,
                        Suggest.hint(a.name!!, ci.fields.map { it.name }) ?: "constructor: ${ci.render()}")
                    checkPattern(a.pattern, TError, mutable)
                    continue
                }
            } else {
                if (sawNamed) {
                    sink.error("positional patterns cannot follow named patterns", a.pattern.span)
                    checkPattern(a.pattern, TError, mutable)
                    continue
                }
                idx = i
                if (idx >= n) { checkPattern(a.pattern, TError, mutable); continue } // counted below
            }
            if (slots[idx] != null) {
                sink.error("field `${ci.fields[idx].name}` is matched twice", a.pattern.span)
                checkPattern(a.pattern, TError, mutable)
                continue
            }
            slots[idx] = a.pattern
            checkPattern(a.pattern, fieldTypes[idx], mutable)
        }
        if (p.args.size > n) {
            sink.error("`${ci.name}` has $n field(s), the pattern names ${p.args.size}", p.span,
                "constructor: ${ci.render()}")
        } else if (!p.hasRest) {
            val missing = ci.fields.filterIndexed { i, _ -> slots[i] == null }
            if (missing.isNotEmpty())
                sink.error("pattern for `${ci.name}` does not mention: ${missing.joinToString(", ") { it.name }}",
                    p.span, "add `..` to ignore the remaining fields")
        }
        p.fieldPats = slots.toList()
    }

    private fun checkBlock(e: Block, expected: Type?): Type = scoped {
        for (s in e.stmts) checkStmt(s)
        val t = e.tail?.let { checkExpr(it, expected) } ?: TUnit
        // a Java call in tail position of a Unit block is a discard, like in
        // statement position (spec §9) — codegen pops the leftover value
        if (expected == TUnit && t != TUnit && e.tail is MethodCall && (e.tail as MethodCall).isJava) TUnit
        else t
    }

    private fun checkStmt(s: Stmt) {
        when (s) {
            is LetStmt -> {
                val annType = s.typeAnn?.let { resolveType(it) }
                val it = checkExpr(s.init, expected = annType)
                var t = annType ?: it
                if (annType != null && !assignable(it, annType)) {
                    sink.error("annotated type is $annType but the initializer is $it", s.init.span)
                    t = annType
                }
                if (t == TNever) {
                    sink.error("cannot bind Never (this expression does not return)", s.init.span)
                    t = TError
                }
                s.symbol = declare(s.name, t, s.mutable, s.span)
            }
            is LocalFnStmt -> checkLocalFn(s)
            is LetPatStmt -> {
                var it = checkExpr(s.init)
                if (it == TNever) {
                    sink.error("cannot bind Never (this expression does not return)", s.init.span)
                    it = TError
                }
                refutablePart(s.pattern)?.let { part ->
                    sink.error("this pattern does not always match, so it cannot be used in a let",
                        part.span, "use match to handle the other cases")
                }
                checkPattern(s.pattern, it, mutable = s.mutable)
            }
            is AssignStmt -> {
                val sym = resolveLocal(s.name, s.nameSpan, forAssign = true)
                if (sym == null) {
                    sink.error("undefined variable: ${s.name}", s.nameSpan,
                        Suggest.hint(s.name, localNames() + fns.keys + stdFns.keys + BUILTINS.keys))
                    checkExpr(s.value)
                    return
                }
                if (!sym.mutable)
                    sink.error("`${s.name}` is a let binding and cannot be assigned", s.nameSpan,
                        "declare it as var ${s.name} = ... if it needs to change")
                s.symbol = sym
                val vt = checkExpr(s.value, expected = sym.type)
                if (!assignable(vt, sym.type))
                    sink.error("`${s.name}` is ${sym.type}, cannot assign $vt", s.value.span)
            }
            is ExprStmt -> {
                val t = checkExpr(s.expr)
                // Java results may be dropped freely — Java APIs return `this`
                // and status codes that Dawn code rarely wants (spec §9)
                val javaCall = s.expr is MethodCall && (s.expr as MethodCall).isJava
                if (t != TUnit && !t.isErrorish && !javaCall)
                    sink.error("this $t value is discarded", s.span,
                        "write let _ = ... to discard it, or move it to the block's tail/return position")
            }
            is AssertStmt -> {
                if (!inTest)
                    sink.error("`assert` is only allowed inside test blocks", s.span,
                        "use panic(...) for runtime invariants in regular code")
                val ct = checkExpr(s.cond)
                if (ct != TBool && !ct.isErrorish)
                    sink.error("assert expects Bool, got $ct", s.cond.span)
            }
            is WhileStmt -> {
                val ct = checkExpr(s.cond)
                if (ct != TBool && !ct.isErrorish) sink.error("while condition must be Bool, got $ct", s.cond.span)
                val bt = checkExpr(s.body, expected = TUnit)
                if (bt != TUnit && !bt.isErrorish)
                    sink.error("the loop body's value is discarded ($bt)", s.body.span,
                        "the last statement of a loop body must not be a non-Unit expression")
            }
            is ForStmt -> {
                val ft = checkExpr(s.from)
                val loopVarType: Type
                if (s.to == null) {
                    // for x in list
                    loopVarType = if (ft is TList) ft.elem else {
                        if (!ft.isErrorish)
                            sink.error("for..in iterates a List or an integer range a..b, got $ft", s.from.span)
                        TError
                    }
                } else {
                    val tt = checkExpr(s.to!!)
                    if ((ft != TInt && !ft.isErrorish) || (tt != TInt && !tt.isErrorish))
                        sink.error("range bounds a..b must be Int (got $ft..$tt)", s.span)
                    loopVarType = TInt
                }
                scoped {
                    s.symbol = declare(s.name, loopVarType, mutable = false, s.span)
                    val bt = checkExpr(s.body, expected = TUnit)
                    if (bt != TUnit && !bt.isErrorish)
                        sink.error("the loop body's value is discarded ($bt)", s.body.span)
                }
            }
        }
    }
}

/**
 * Resolve a `use java` name (spec §9.1). Tries the fqcn as written, then walks
 * trailing dots into `$` so nested classes read naturally
 * (`java.net.http.HttpResponse.BodyHandlers`, no `$` in source — `$` would lex
 * as interpolation anyway). Returns null when nothing resolves.
 */
fun resolveJavaClass(fqcn: String, loader: ClassLoader): Class<*>? {
    try {
        return Class.forName(fqcn, false, loader)
    } catch (_: Throwable) {
    }
    var name = fqcn
    while (name.contains('.')) {
        name = name.substringBeforeLast('.') + '$' + name.substringAfterLast('.')
        try {
            return Class.forName(name, false, loader)
        } catch (_: Throwable) {
        }
    }
    return null
}
