package dawn.check

import dawn.ast.*
import dawn.check.Type.*
import dawn.diag.DiagnosticSink
import dawn.diag.Span

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
class Checker(private val module: Module, private val sink: DiagnosticSink) {

    private val fns = HashMap<String, FnSig>()
    private val adts = HashMap<String, AdtInfo>()
    private val ctors = HashMap<String, CtorInfo>()
    private val scopes = ArrayDeque<HashMap<String, Symbol>>()

    /** user-defined functions by name (first definition wins on duplicates) */
    val functions: Map<String, FnSig> get() = fns
    /** user-defined types by name */
    val types: Map<String, AdtInfo> get() = adts

    /** effects used by the body currently being checked (Io and/or effect variables) */
    private var usedEffects = HashSet<Eff>()
    /** location of the first use of each effect (for error messages) */
    private var effWitness = HashMap<Eff, Pair<Span, String>>()

    /** effect variables of the signature currently being checked (for annotations in bodies) */
    private var currentEffVars: MutableMap<String, Eff.Var> = HashMap()

    /** an active lambda: locals declared outside its boundary are captures */
    private class LambdaCtx(val boundaryDepth: Int) {
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

    /** inside a test block (assert is allowed, io is implicit) */
    private var inTest = false

    fun check() {
        // 0. prelude: Option/Result and their constructors
        for (info in PRELUDE_ADTS) {
            adts[info.name] = info
            for (c in info.ctors) ctors[c.name] = c
        }
        // 1. type headers first (shells only), so recursive types resolve
        for (d in module.types) {
            if (Type.named(d.name) != null || d.name == "List") {
                sink.error("`${d.name}` is a builtin type and cannot be redefined", d.nameSpan)
                continue
            }
            if (adts.containsKey(d.name)) {
                sink.error(
                    if (PRELUDE_ADTS.any { it.name == d.name })
                        "`${d.name}` is a prelude type and cannot be redefined"
                    else "type `${d.name}` is defined twice",
                    d.nameSpan)
                continue
            }
            if (d.typeParams.toSet().size != d.typeParams.size)
                sink.error("duplicate type parameter names", d.nameSpan)
            val info = AdtInfo(d.name, d.nameSpan, d.isRecord, d.typeParams.map { TVar(it) })
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
                    ci.fields.add(FieldInfo(f.name, ft, f.span))
                }
            }
        }
        // 3. function signatures
        for (d in module.fns) {
            if (d.typeParams.toSet().size != d.typeParams.size)
                sink.error("duplicate type parameter names", d.nameSpan)
            val tvars = d.typeParams.map { TVar(it) }
            val tp = tvars.associateBy { it.name }
            val ev = HashMap<String, Eff.Var>()
            val eff = when (d.declaredEff) {
                null -> Eff.Pure
                "io" -> Eff.Io
                else -> ev.getOrPut(d.declaredEff) { Eff.Var(d.declaredEff) }
            }
            val sig = FnSig(
                d.name,
                d.params.map { resolveType(it.typeName, tp, ev) },
                d.params.map { it.name },
                resolveType(d.retType, tp, ev),
                eff,
                isBuiltin = false,
                typeParams = tvars,
                nameSpan = d.nameSpan,
            )
            d.sig = sig
            d.effVars = ev
            when {
                BUILTINS.containsKey(d.name) ->
                    sink.error("`${d.name}` is a builtin function and cannot be redefined", d.nameSpan)
                fns.containsKey(d.name) ->
                    sink.error("function `${d.name}` is defined twice", d.nameSpan)
                else -> fns[d.name] = sig
            }
        }
        // 4. entry point check
        val main = module.fns.find { it.name == "main" }
        if (main != null) {
            val sig = main.sig!!
            if (sig.paramTypes.isNotEmpty() || sig.ret != TUnit)
                sink.error("main must have the signature fn main() -> Unit !io", main.nameSpan)
            if (!main.pub)
                sink.error("main must be pub", main.nameSpan, "write pub fn main() -> Unit !io")
        }
        // 5. check each function body, then each test block
        for (d in module.fns) checkFn(d)
        for (t in module.tests) checkTest(t)
    }

    private fun checkTest(t: TestDecl) {
        currentTParams = emptyMap()
        currentEffVars = HashMap()
        currentFnSig = null
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
            val eff = when (ref.effName) {
                null -> Eff.Pure
                "io" -> Eff.Io
                else -> effVars.getOrPut(ref.effName) { Eff.Var(ref.effName) }
            }
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
        if (ref.name == "List") {
            if (ref.args.size != 1) {
                sink.error("List takes exactly one type argument: List[T]", ref.span)
                return TError
            }
            return TList(resolveType(ref.args[0], tparams, effVars))
        }
        Type.named(ref.name)?.let {
            if (ref.args.isNotEmpty()) {
                sink.error("`${ref.name}` is not generic", ref.span)
                return TError
            }
            return it
        }
        val info = adts[ref.name] ?: run {
            sink.error("unknown type: ${ref.name}", ref.span,
                "builtin types: Int, Float, Bool, String, Unit, List — or declare `type ${ref.name} = ...`")
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
            if (actual == TUnit) false // Unit cannot instantiate a type parameter (erasure carries no value)
            else {
                val bound = map[declared]
                if (bound == null) { map[declared] = actual; true } else bound == actual
            }
        }
        declared is TAdt && actual is TAdt ->
            declared.info === actual.info &&
                declared.args.zip(actual.args).all { (d, a) -> unifyInto(d, a, map, effMap) }
        declared is TList && actual is TList -> unifyInto(declared.elem, actual.elem, map, effMap)
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
    }

    /** does this expression need an expected type to check at all? */
    private fun needsExpected(e: Expr): Boolean = when (e) {
        is ListLit -> e.elems.isEmpty() || e.elems.all { needsExpected(it) }
        is TupleLit -> e.elems.any { needsExpected(it) }
        // a generic function used as a value is instantiated from the expected type
        is VarRef -> lookup(e.name) == null &&
            (fns[e.name] ?: BUILTINS[e.name])?.typeParams?.isNotEmpty() == true
        is CtorCall -> {
            val ci = ctors[e.ctorName]
            ci != null && ci.fields.isEmpty() && ci.adt.typeParams.isNotEmpty()
        }
        is Lambda -> e.params.any { it.typeAnn == null }
        else -> false
    }

    private fun checkFn(d: FnDecl) {
        val sig = d.sig!!
        currentTParams = sig.typeParams.associateBy { it.name }
        currentEffVars = HashMap(d.effVars)
        currentFnSig = sig
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
        if (sig.eff != Eff.Io) {
            for (used in usedEffects) {
                if (used == sig.eff) continue // declared !e, used e
                val (span, name) = effWitness[used] ?: (d.nameSpan to "?")
                sink.error(
                    "function `${d.name}` is not declared !$used but calls `$name` (!$used)",
                    span,
                    "add !$used to the end of the signature, or remove the call",
                )
            }
        }
        scopes.removeLast()
    }

    // ---- scopes ----

    private fun declare(name: String, type: Type, mutable: Boolean, span: Span): Symbol {
        if (name != "_" && scopes.last().containsKey(name))
            sink.error("`$name` is already bound in this scope", span,
                "let does not shadow; only nested blocks may reuse a name")
        val sym = Symbol(name, type, mutable, span)
        if (name != "_") scopes.last()[name] = sym
        return sym
    }

    private fun lookup(name: String): Symbol? {
        for (i in scopes.indices.reversed()) scopes[i][name]?.let { return it }
        return null
    }

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
                if (t !in listOf(TInt, TFloat, TBool, TString) && !t.isErrorish)
                    error("cannot interpolate a value of type $t", p.expr.span,
                        "interpolation supports Int, Float, Bool, String (derive Show is not implemented yet)")
            }
            TString
        }
        is VarRef -> {
            val sym = resolveLocal(e.name, e.span)
            if (sym != null) {
                e.symbol = sym
                sym.type
            } else {
                val f = fns[e.name] ?: BUILTINS[e.name]
                if (f != null) checkFnValue(e, f, expected)
                else error("undefined variable: ${e.name}", e.span)
            }
        }
        is MethodCall -> {
            // UFCS: x.f(a) is f(x, a) (spec §4.3); Java receivers come in §9
            val call = Call(e.name, listOf(e.target) + e.args, e.nameSpan, e.span)
            e.desugared = call
            checkExpr(call, expected)
        }
        is Lambda -> checkLambda(e, expected)
        is Apply -> checkApply(e)
        is Propagate -> checkPropagate(e)
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
        }
        is If -> checkIf(e, expected)
        is Match -> checkMatch(e, expected)
        is Block -> checkBlock(e, expected)
    }

    private fun isConcrete(t: Type): Boolean = when (t) {
        is TVar -> false
        is TAdt -> t.args.all { isConcrete(it) }
        is TList -> isConcrete(t.elem)
        is TTuple -> t.elems.all { isConcrete(it) }
        else -> true
    }

    /** does the type contain a function anywhere? (functions cannot be compared, spec §4.3) */
    private fun containsFn(t: Type): Boolean = when (t) {
        is TFn -> true
        is TTuple -> t.elems.any { containsFn(it) }
        is TList -> containsFn(t.elem)
        else -> false
    }

    /** A top-level function or builtin used as a value; generics need the expected type. */
    private fun checkFnValue(e: VarRef, f: FnSig, expected: Type?): Type {
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

    /** to_string / interpolation accept the printable types only (derive Show is later) */
    private fun checkPrintable(t: Type, span: Span) {
        if (t !in listOf(TInt, TFloat, TBool, TString) && !t.isErrorish)
            sink.error("to_string supports Int, Float, Bool, String, got $t", span,
                "derive Show is not implemented yet")
    }

    private fun checkCall(e: Call, expected: Type?): Type {
        // a local function value shadows top-level functions
        val local = resolveLocal(e.callee, e.calleeSpan)
        if (local != null) {
            val lt = local.type
            if (lt.isErrorish) {
                for (arg in e.args) checkExpr(arg)
                return TError
            }
            if (lt !is TFn) {
                for (arg in e.args) checkExpr(arg)
                return error("`${e.callee}` is not a function (it is $lt)", e.calleeSpan)
            }
            e.dynamicTarget = local
            if (e.args.size != lt.params.size) {
                for (arg in e.args) checkExpr(arg)
                sink.error("`${e.callee}` takes ${lt.params.size} argument(s), got ${e.args.size}",
                    e.span, "type: $lt")
                return lt.ret
            }
            for ((arg, pt) in e.args.zip(lt.params)) {
                val at = checkExpr(arg, expected = pt)
                if (!assignable(at, pt))
                    sink.error("argument type mismatch: expected $pt, got $at", arg.span)
            }
            recordEffect(lt.eff, e.calleeSpan, e.callee)
            return lt.ret
        }
        val sig = fns[e.callee] ?: BUILTINS[e.callee]
        if (sig == null) {
            // still check the arguments so their subtrees get types/symbols
            for (arg in e.args) checkExpr(arg)
            return error("undefined function: ${e.callee}", e.calleeSpan)
        }
        e.sig = sig
        if (e.args.size != sig.paramTypes.size) {
            for (arg in e.args) checkExpr(arg)
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
                val at = checkExpr(arg, expected = exp)
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
        if (sig.isBuiltin && sig.name == "to_string")
            checkPrintable(subst(sig.paramTypes[0], map), e.args[0].span)
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
            e.spread?.let { checkExpr(it) }
            for (a in e.args) checkExpr(a.expr)
            return error("undefined constructor: ${e.ctorName}", e.calleeSpan,
                if (adts.containsKey(e.ctorName))
                    "`${e.ctorName}` is a type; build a value with one of its constructors: " +
                        adts[e.ctorName]!!.ctors.joinToString(", ") { it.name }
                else null)
        }
        e.ctor = ci
        val adt = ci.adt
        val n = ci.fields.size
        if (!e.hasParens && n > 0) {
            return error(
                if (adt.isRecord)
                    "record `${ci.name}` must be built with braces: ${ci.name} { ... }"
                else "constructor `${ci.name}` has $n field(s) and cannot be used bare",
                e.span, "constructor: ${ci.render()}")
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
                    sink.error("`${ci.name}` has no field `${a.name}`", a.span, "constructor: ${ci.render()}")
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

    private fun checkLambda(e: Lambda, expected: Type?): Type {
        val exp = expected as? TFn
        if (exp != null && exp.params.size != e.params.size)
            sink.error("this lambda takes ${e.params.size} parameter(s), but $exp is expected", e.span)
        val paramTypes = e.params.mapIndexed { i, p ->
            var t = p.typeAnn?.let { resolveType(it) }
                ?: exp?.params?.getOrNull(i)?.takeIf { isConcrete(it) }
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
        val ctx = LambdaCtx(scopes.size)
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

    /** expr? — spec §8.1: unwrap Ok/Some, or return the Err/None from the enclosing fn */
    private fun checkPropagate(e: Propagate): Type {
        val ot = checkExpr(e.operand)
        if (ot.isErrorish) return TError
        if (lambdaStack.isNotEmpty())
            return error("`?` cannot be used inside a lambda (it returns from the enclosing function)", e.span,
                "handle the Option/Result with match inside the lambda")
        val sigRet = currentFnSig?.ret
            ?: return error("`?` can only be used inside a function that returns Option or Result", e.span)
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
            else -> error("`?` needs an Option or Result, got $ot", e.span)
        }
    }

    private fun checkFieldAccess(e: FieldAccess): Type {
        val tt = checkExpr(e.target)
        if (tt.isErrorish) return TError
        if (tt !is TAdt || !tt.info.isRecord)
            return error("`.` field access needs a record value, got $tt", e.fieldSpan,
                if (tt is TAdt) "`${tt.info.name}` is a sum type; destructure it with match" else null)
        val ci = tt.info.ctors.first()
        val field = ci.fields.find { it.name == e.fieldName }
            ?: return error("`${tt.info.name}` has no field `${e.fieldName}`", e.fieldSpan,
                "fields: ${ci.fields.joinToString(", ") { it.name }}")
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
        val rt = checkExpr(e.right)
        // one side already failed: pick a plausible result type, stay silent
        if (lt.isErrorish || rt.isErrorish) return when (e.op) {
            BinOp.ADD, BinOp.SUB, BinOp.MUL, BinOp.DIV, BinOp.MOD ->
                if (lt.isNumeric) lt else if (rt.isNumeric) rt else TError
            BinOp.CONCAT -> if (lt is TList) lt else if (rt is TList) rt else TString
            else -> TBool
        }
        fun bothNumericSame(): Type {
            if (!lt.isNumeric) return error("arithmetic expects numbers, left side is $lt", e.left.span)
            if (lt != rt) return error("both sides must have the same type: $lt vs $rt", e.opSpan,
                if (rt.isNumeric) "there are no implicit conversions; use to_float() (M1) or unify the literal types" else null)
            return lt
        }
        return when (e.op) {
            BinOp.ADD, BinOp.SUB, BinOp.MUL, BinOp.DIV, BinOp.MOD -> bothNumericSame()
            BinOp.CONCAT -> when {
                lt == TString && rt == TString -> TString
                lt is TList && rt is TList ->
                    if (lt != rt) error("`++` needs lists of the same element type: $lt vs $rt", e.opSpan)
                    else lt
                else -> error("`++` concatenates Strings or Lists, got $lt ++ $rt", e.opSpan,
                    "use + for numbers; interpolation \"{x}{y}\" also builds strings")
            }
            BinOp.EQ, BinOp.NEQ -> {
                if (containsFn(lt) || containsFn(rt))
                    error("functions cannot be compared", e.opSpan)
                else if (lt != rt) error("== requires both sides to have the same type: $lt vs $rt", e.opSpan)
                else TBool
            }
            BinOp.LT, BinOp.LE, BinOp.GT, BinOp.GE -> {
                if (lt != rt) error("comparison requires both sides to have the same type: $lt vs $rt", e.opSpan)
                else if (lt !in listOf(TInt, TFloat, TString))
                    error("values of type $lt cannot be ordered", e.opSpan)
                else TBool
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
                            p.span)
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
            sink.error("undefined constructor in pattern: ${p.ctorName}", p.nameSpan)
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
                        "constructor: ${ci.render()}")
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
        t
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
                    sink.error("undefined variable: ${s.name}", s.nameSpan)
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
                if (t != TUnit && !t.isErrorish)
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
                val bt = checkExpr(s.body)
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
                    val bt = checkExpr(s.body)
                    if (bt != TUnit && !bt.isErrorish)
                        sink.error("the loop body's value is discarded ($bt)", s.body.span)
                }
            }
        }
    }
}
