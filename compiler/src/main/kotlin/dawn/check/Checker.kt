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

    /** whether the current function body uses io */
    private var usesIo = false
    /** location of the first io use (for the error message) */
    private var ioWitness: Span? = null
    private var ioWitnessName: String? = null

    fun check() {
        // 1. type headers first (shells only), so recursive types resolve
        for (d in module.types) {
            if (Type.named(d.name) != null) {
                sink.error("`${d.name}` is a builtin type and cannot be redefined", d.nameSpan)
                continue
            }
            if (adts.containsKey(d.name)) {
                sink.error("type `${d.name}` is defined twice", d.nameSpan)
                continue
            }
            val info = AdtInfo(d.name, d.nameSpan)
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
            for (c in d.ctors) {
                val ci = c.info ?: continue
                for (f in c.fields) {
                    if (ci.fields.any { it.name == f.name }) {
                        sink.error("field `${f.name}` is declared twice in `${c.name}`", f.span)
                        continue
                    }
                    var ft = resolveType(f.typeRef)
                    if (ft == TUnit) {
                        sink.error("constructor fields cannot be Unit", f.span,
                            "a no-payload case is just a bare constructor")
                        ft = TError
                    }
                    ci.fields.add(FieldInfo(f.name, ft))
                }
            }
        }
        // 3. function signatures
        for (d in module.fns) {
            val sig = FnSig(
                d.name,
                d.params.map { resolveType(it.typeName) },
                d.params.map { it.name },
                resolveType(d.retType),
                d.declaredIo,
                isBuiltin = false,
                nameSpan = d.nameSpan,
            )
            d.sig = sig
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
        // 5. check each function body
        for (d in module.fns) checkFn(d)
    }

    private fun resolveType(ref: TypeRef): Type =
        Type.named(ref.name) ?: adts[ref.name]?.type ?: run {
            sink.error("unknown type: ${ref.name}", ref.span,
                "builtin types: Int, Float, Bool, String, Unit — or declare `type ${ref.name} = ...`")
            TError
        }

    private fun checkFn(d: FnDecl) {
        val sig = d.sig!!
        usesIo = false
        ioWitness = null
        ioWitnessName = null
        scopes.clear()
        scopes.addLast(HashMap())
        for ((p, t) in d.params.zip(sig.paramTypes)) {
            p.symbol = declare(p.name, t, mutable = false, p.span)
        }
        val bodyType = checkExpr(d.body, expected = sig.ret)
        if (!assignable(bodyType, sig.ret))
            sink.error("function `${d.name}` declares return type ${sig.ret} but its body is $bodyType", d.body.span)
        if (usesIo && !sig.io) {
            sink.error(
                "function `${d.name}` is not declared !io but calls `${ioWitnessName}` (io)",
                ioWitness ?: d.nameSpan,
                "add !io to the end of the signature, or remove the call",
            )
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

    /** can t be used where target is expected (Never/TError usable as anything) */
    private fun assignable(t: Type, target: Type) =
        t == target || t.isErrorish || target == TError

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
            val sym = lookup(e.name)
            if (sym == null) {
                error("undefined variable: ${e.name}", e.span,
                    if (fns.containsKey(e.name) || BUILTINS.containsKey(e.name))
                        "`${e.name}` is a function; M0 has no function values, call it as ${e.name}(...)" else null)
            } else {
                e.symbol = sym
                sym.type
            }
        }
        is Call -> checkCall(e)
        is CtorCall -> checkCtorCall(e)
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

    private fun checkCall(e: Call): Type {
        val sig = fns[e.callee] ?: BUILTINS[e.callee]
        if (sig == null) {
            // still check the arguments so their subtrees get types/symbols
            for (arg in e.args) checkExpr(arg)
            return error("undefined function: ${e.callee}", e.calleeSpan,
                if (lookup(e.callee) != null) "`${e.callee}` is a variable, not a function (M0 has no function values)" else null)
        }
        e.sig = sig
        if (e.args.size != sig.paramTypes.size) {
            for (arg in e.args) checkExpr(arg)
            sink.error("`${e.callee}` takes ${sig.paramTypes.size} argument(s), got ${e.args.size}",
                e.span, "signature: ${sig.render()}")
            return sig.ret
        }
        for ((arg, pt) in e.args.zip(sig.paramTypes)) {
            val at = checkExpr(arg, expected = pt)
            if (!assignable(at, pt))
                sink.error("argument type mismatch: expected $pt, got $at", arg.span,
                    "signature: ${sig.render()}")
        }
        if (sig.io && !usesIo) {
            usesIo = true
            ioWitness = e.calleeSpan
            ioWitnessName = e.callee
        } else if (sig.io) {
            usesIo = true
        }
        return sig.ret
    }

    private fun checkCtorCall(e: CtorCall): Type {
        val ci = ctors[e.ctorName]
        if (ci == null) {
            for (a in e.args) checkExpr(a.expr)
            return error("undefined constructor: ${e.ctorName}", e.calleeSpan,
                if (adts.containsKey(e.ctorName))
                    "`${e.ctorName}` is a type; build a value with one of its constructors: " +
                        adts[e.ctorName]!!.ctors.joinToString(", ") { it.name }
                else null)
        }
        e.ctor = ci
        val n = ci.fields.size
        if (!e.hasParens && n > 0) {
            return error("constructor `${ci.name}` has $n field(s) and cannot be used bare", e.span,
                "constructor: ${ci.render()}")
        }
        // map arguments (positional prefix, then named) onto fields
        val slots = arrayOfNulls<Expr>(n)
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
            val ft = ci.fields[idx].type
            val at = checkExpr(a.expr, expected = ft)
            if (!assignable(at, ft))
                sink.error("field `${ci.fields[idx].name}` of `${ci.name}` is $ft, got $at", a.expr.span,
                    "constructor: ${ci.render()}")
            slots[idx] = a.expr
        }
        if (!argsBroken) {
            val missing = ci.fields.filterIndexed { i, _ -> slots[i] == null }
            if (e.args.size > n)
                sink.error("`${ci.name}` takes $n field(s), got ${e.args.size}", e.span,
                    "constructor: ${ci.render()}")
            else if (missing.isNotEmpty())
                sink.error("missing field(s) in `${ci.name}`: ${missing.joinToString(", ") { it.name }}",
                    e.span, "constructor: ${ci.render()}")
        }
        if (slots.all { it != null }) e.ordered = slots.map { it!! }
        return ci.adt.type
    }

    private fun checkBinary(e: Binary): Type {
        val lt = checkExpr(e.left)
        val rt = checkExpr(e.right)
        // one side already failed: pick a plausible result type, stay silent
        if (lt.isErrorish || rt.isErrorish) return when (e.op) {
            BinOp.ADD, BinOp.SUB, BinOp.MUL, BinOp.DIV, BinOp.MOD ->
                if (lt.isNumeric) lt else if (rt.isNumeric) rt else TError
            BinOp.CONCAT -> TString
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
            BinOp.CONCAT -> {
                if (lt != TString || rt != TString)
                    error("`++` concatenates Strings (M0), got $lt ++ $rt", e.opSpan,
                        "use + for numbers; interpolation \"{x}{y}\" also builds strings")
                else TString
            }
            BinOp.EQ, BinOp.NEQ -> {
                if (lt != rt) error("== requires both sides to have the same type: $lt vs $rt", e.opSpan)
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
        val scrutOk = st in listOf(TInt, TString, TBool) || st is TAdt
        if (!scrutOk && !st.isErrorish)
            sink.error("match supports Int/String/Bool and user-defined types, got $st", e.scrutinee.span)

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
        else -> false
    }

    private fun checkPattern(p: Pattern, scrutType: Type) {
        when (p) {
            is WildPat -> {}
            is BindPat -> {
                p.symbol = declare(p.name, scrutType, mutable = false, p.span)
            }
            is LitPat -> {
                val lt = checkExpr(p.lit)
                if (lt != scrutType && !scrutType.isErrorish && !lt.isErrorish)
                    sink.error("pattern type $lt does not match scrutinee type $scrutType", p.span)
            }
            is CtorPat -> checkCtorPat(p, scrutType)
        }
    }

    private fun checkCtorPat(p: CtorPat, scrutType: Type) {
        val ci = ctors[p.ctorName]
        if (ci == null) {
            sink.error("undefined constructor in pattern: ${p.ctorName}", p.nameSpan)
            // still check subpatterns so their bindings exist (as TError)
            for (a in p.args) checkPattern(a.pattern, TError)
            return
        }
        p.ctor = ci
        if (scrutType !is TAdt || scrutType.info != ci.adt) {
            if (!scrutType.isErrorish)
                sink.error("`${p.ctorName}` is a ${ci.adt.name} constructor, but the scrutinee is $scrutType",
                    p.nameSpan)
        }
        val n = ci.fields.size
        if (!p.hasParens && n > 0) {
            sink.error("constructor `${ci.name}` has $n field(s); a bare name does not match it", p.span,
                "write ${ci.name}(..) to ignore the fields, or destructure them")
            for (a in p.args) checkPattern(a.pattern, TError)
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
                    checkPattern(a.pattern, TError)
                    continue
                }
            } else {
                if (sawNamed) {
                    sink.error("positional patterns cannot follow named patterns", a.pattern.span)
                    checkPattern(a.pattern, TError)
                    continue
                }
                idx = i
                if (idx >= n) { checkPattern(a.pattern, TError); continue } // counted below
            }
            if (slots[idx] != null) {
                sink.error("field `${ci.fields[idx].name}` is matched twice", a.pattern.span)
                checkPattern(a.pattern, TError)
                continue
            }
            slots[idx] = a.pattern
            checkPattern(a.pattern, ci.fields[idx].type)
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
            is AssignStmt -> {
                val sym = lookup(s.name)
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
                val tt = checkExpr(s.to)
                if ((ft != TInt && !ft.isErrorish) || (tt != TInt && !tt.isErrorish))
                    sink.error("range bounds a..b must be Int (got $ft..$tt)", s.span)
                scoped {
                    s.symbol = declare(s.name, TInt, mutable = false, s.span)
                    val bt = checkExpr(s.body)
                    if (bt != TUnit && !bt.isErrorish)
                        sink.error("the loop body's value is discarded ($bt)", s.body.span)
                }
            }
        }
    }
}
