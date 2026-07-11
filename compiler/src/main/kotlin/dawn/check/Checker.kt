package dawn.check

import dawn.ast.*
import dawn.check.Type.*
import dawn.diag.DawnError
import dawn.diag.Span

/**
 * Type and effect checking (the M0 subset of spec §2/§4/§5/§6).
 * Types and resolved symbols are annotated back onto the AST for codegen.
 * Effect rule: the signature is the promise — callers only look at a callee's
 * declared effect; the effect inferred from a function body must be ⊑ the
 * declared one.
 */
class Checker(private val module: Module) {

    private val fns = HashMap<String, FnSig>()
    private val scopes = ArrayDeque<HashMap<String, Symbol>>()

    /** whether the current function body uses io */
    private var usesIo = false
    /** location of the first io use (for the error message) */
    private var ioWitness: Span? = null
    private var ioWitnessName: String? = null

    fun check() {
        // 1. collect signatures
        for (d in module.decls) {
            if (BUILTINS.containsKey(d.name))
                throw DawnError("`${d.name}` is a builtin function and cannot be redefined", d.nameSpan)
            if (fns.containsKey(d.name))
                throw DawnError("function `${d.name}` is defined twice", d.nameSpan)
            fns[d.name] = FnSig(
                d.name,
                d.params.map { resolveType(it.typeName) },
                d.params.map { it.name },
                resolveType(d.retType),
                d.declaredIo,
                isBuiltin = false,
            )
        }
        // 2. entry point check
        val main = module.decls.find { it.name == "main" }
        if (main != null) {
            val sig = fns["main"]!!
            if (sig.paramTypes.isNotEmpty() || sig.ret != TUnit)
                throw DawnError("main must have the signature fn main() -> Unit !io", main.nameSpan)
            if (!main.pub)
                throw DawnError("main must be pub", main.nameSpan, "write pub fn main() -> Unit !io")
        }
        // 3. check each function
        for (d in module.decls) checkFn(d)
    }

    private fun resolveType(ref: TypeRef): Type =
        Type.named(ref.name) ?: throw DawnError("unknown type: ${ref.name}", ref.span,
            "M0 types: Int, Float, Bool, String, Unit")

    private fun checkFn(d: FnDecl) {
        val sig = fns[d.name]!!
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
            throw DawnError("function `${d.name}` declares return type ${sig.ret} but its body is $bodyType", d.body.span)
        if (usesIo && !sig.io) {
            throw DawnError(
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
            throw DawnError("`$name` is already bound in this scope", span,
                "let does not shadow; only nested blocks may reuse a name")
        val sym = Symbol(name, type, mutable)
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

    /** can t be used where target is expected (Never usable as anything) */
    private fun assignable(t: Type, target: Type) = t == target || t == TNever

    /** unify branch types (Never is absorbed) */
    private fun unify(a: Type, b: Type, span: Span, what: String): Type = when {
        a == TNever -> b
        b == TNever -> a
        a == b -> a
        else -> throw DawnError("$what have mismatched types: $a vs $b", span)
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
                if (t !in listOf(TInt, TFloat, TBool, TString))
                    throw DawnError("cannot interpolate a value of type $t", p.expr.span,
                        "M0 interpolation supports Int, Float, Bool, String")
            }
            TString
        }
        is VarRef -> {
            val sym = lookup(e.name)
                ?: throw DawnError("undefined variable: ${e.name}", e.span,
                    if (fns.containsKey(e.name) || BUILTINS.containsKey(e.name))
                        "`${e.name}` is a function; M0 has no function values, call it as ${e.name}(...)" else null)
            e.symbol = sym
            sym.type
        }
        is Call -> checkCall(e)
        is Binary -> checkBinary(e)
        is Unary -> when (e.op) {
            UnOp.NOT -> {
                val t = checkExpr(e.operand)
                if (t != TBool) throw DawnError("not expects Bool, got $t", e.operand.span)
                TBool
            }
            UnOp.NEG -> {
                val t = checkExpr(e.operand)
                if (!t.isNumeric) throw DawnError("negation expects a number, got $t", e.operand.span)
                t
            }
        }
        is If -> checkIf(e, expected)
        is Match -> checkMatch(e, expected)
        is Block -> checkBlock(e, expected)
    }

    private fun checkCall(e: Call): Type {
        val sig = fns[e.callee] ?: BUILTINS[e.callee]
        ?: throw DawnError("undefined function: ${e.callee}", e.calleeSpan,
            if (lookup(e.callee) != null) "`${e.callee}` is a variable, not a function (M0 has no function values)" else null)
        if (e.args.size != sig.paramTypes.size)
            throw DawnError("`${e.callee}` takes ${sig.paramTypes.size} argument(s), got ${e.args.size}",
                e.span, "signature: ${renderSig(sig)}")
        for ((arg, pt) in e.args.zip(sig.paramTypes)) {
            val at = checkExpr(arg, expected = pt)
            if (!assignable(at, pt))
                throw DawnError("argument type mismatch: expected $pt, got $at", arg.span,
                    "signature: ${renderSig(sig)}")
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

    private fun renderSig(sig: FnSig): String {
        val params = sig.paramNames.zip(sig.paramTypes).joinToString(", ") { "${it.first}: ${it.second}" }
        val eff = if (sig.io) " !io" else ""
        return "fn ${sig.name}($params) -> ${sig.ret}$eff"
    }

    private fun checkBinary(e: Binary): Type {
        val lt = checkExpr(e.left)
        val rt = checkExpr(e.right)
        fun bothNumericSame(): Type {
            if (!lt.isNumeric) throw DawnError("arithmetic expects numbers, left side is $lt", e.left.span)
            if (lt != rt) throw DawnError("both sides must have the same type: $lt vs $rt", e.opSpan,
                if (lt.isNumeric && rt.isNumeric) "there are no implicit conversions; use to_float() (M1) or unify the literal types" else null)
            return lt
        }
        return when (e.op) {
            BinOp.ADD, BinOp.SUB, BinOp.MUL, BinOp.DIV, BinOp.MOD -> bothNumericSame()
            BinOp.CONCAT -> {
                if (lt != TString || rt != TString)
                    throw DawnError("`++` concatenates Strings (M0), got $lt ++ $rt", e.opSpan,
                        "use + for numbers; interpolation \"{x}{y}\" also builds strings")
                TString
            }
            BinOp.EQ, BinOp.NEQ -> {
                if (lt != rt && lt != TNever && rt != TNever)
                    throw DawnError("== requires both sides to have the same type: $lt vs $rt", e.opSpan)
                TBool
            }
            BinOp.LT, BinOp.LE, BinOp.GT, BinOp.GE -> {
                if (lt != rt) throw DawnError("comparison requires both sides to have the same type: $lt vs $rt", e.opSpan)
                if (lt !in listOf(TInt, TFloat, TString))
                    throw DawnError("values of type $lt cannot be ordered", e.opSpan)
                TBool
            }
            BinOp.AND, BinOp.OR -> {
                if (lt != TBool) throw DawnError("logical operators expect Bool, left side is $lt", e.left.span)
                if (rt != TBool) throw DawnError("logical operators expect Bool, right side is $rt", e.right.span)
                TBool
            }
        }
    }

    private fun checkIf(e: If, expected: Type?): Type {
        val ct = checkExpr(e.cond)
        if (ct != TBool) throw DawnError("if condition must be Bool, got $ct", e.cond.span)
        val tt = checkExpr(e.thenBranch, expected)
        return if (e.elseBranch == null) {
            // no else: statement position only, branch must be Unit
            if (tt != TUnit && tt != TNever)
                throw DawnError("an if without else is a statement, so its branch must be Unit (got $tt)", e.thenBranch.span,
                    "add an else branch to produce a value")
            TUnit
        } else {
            val et = checkExpr(e.elseBranch, expected)
            unify(tt, et, e.span, "the if branches")
        }
    }

    private fun checkMatch(e: Match, expected: Type?): Type {
        val st = checkExpr(e.scrutinee)
        if (st !in listOf(TInt, TString, TBool))
            throw DawnError("M0 match supports Int/String/Bool only (ADTs arrive in M1)", e.scrutinee.span)

        var result: Type = TNever
        var hasFallback = false          // unguarded catch-all arm (binding/wildcard)
        var sawTrue = false
        var sawFalse = false

        for (arm in e.arms) {
            scoped {
                for (p in arm.patterns) checkPattern(p, st, arm)
                if (arm.guard != null) {
                    val gt = checkExpr(arm.guard)
                    if (gt != TBool) throw DawnError("guard must be Bool, got $gt", arm.guard.span)
                }
                val bt = checkExpr(arm.body, expected)
                result = unify(result, bt, arm.body.span, "the match arms")
            }
            if (arm.guard == null) {
                for (p in arm.patterns) {
                    when (p) {
                        is BindPat, is WildPat -> hasFallback = true
                        is LitPat -> {
                            val lit = p.lit
                            if (lit is BoolLit) { if (lit.value) sawTrue = true else sawFalse = true }
                        }
                    }
                }
            }
        }
        val exhaustive = hasFallback || (st == TBool && sawTrue && sawFalse)
        if (!exhaustive) {
            val missing = when (st) {
                TBool -> if (sawTrue) "false" else "true"
                else -> "_ ($st has too many values to enumerate)"
            }
            throw DawnError("non-exhaustive match, missing: $missing", e.span,
                "add an unguarded catch-all arm (a binding or _)")
        }
        return result
    }

    private fun checkPattern(p: Pattern, scrutType: Type, arm: MatchArm) {
        when (p) {
            is WildPat -> {}
            is BindPat -> {
                if (arm.patterns.size > 1)
                    throw DawnError("or-pattern alternatives cannot introduce bindings (M0)", p.span)
                p.symbol = declare(p.name, scrutType, mutable = false, p.span)
            }
            is LitPat -> {
                val lt = checkExpr(p.lit)
                if (lt != scrutType)
                    throw DawnError("pattern type $lt does not match scrutinee type $scrutType", p.span)
            }
        }
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
                val t = annType ?: it
                if (annType != null && !assignable(it, annType))
                    throw DawnError("annotated type is $annType but the initializer is $it", s.init.span)
                if (t == TNever)
                    throw DawnError("cannot bind Never (this expression does not return)", s.init.span)
                s.symbol = declare(s.name, t, s.mutable, s.span)
            }
            is AssignStmt -> {
                val sym = lookup(s.name) ?: throw DawnError("undefined variable: ${s.name}", s.nameSpan)
                if (!sym.mutable)
                    throw DawnError("`${s.name}` is a let binding and cannot be assigned", s.nameSpan,
                        "declare it as var ${s.name} = ... if it needs to change")
                s.symbol = sym
                val vt = checkExpr(s.value, expected = sym.type)
                if (!assignable(vt, sym.type))
                    throw DawnError("`${s.name}` is ${sym.type}, cannot assign $vt", s.value.span)
            }
            is ExprStmt -> {
                val t = checkExpr(s.expr)
                if (t != TUnit && t != TNever)
                    throw DawnError("this $t value is discarded", s.span,
                        "write let _ = ... to discard it, or move it to the block's tail/return position")
            }
            is WhileStmt -> {
                val ct = checkExpr(s.cond)
                if (ct != TBool) throw DawnError("while condition must be Bool, got $ct", s.cond.span)
                val bt = checkExpr(s.body)
                if (bt != TUnit && bt != TNever)
                    throw DawnError("the loop body's value is discarded ($bt)", s.body.span,
                        "the last statement of a loop body must not be a non-Unit expression")
            }
            is ForStmt -> {
                val ft = checkExpr(s.from)
                val tt = checkExpr(s.to)
                if (ft != TInt || tt != TInt)
                    throw DawnError("range bounds a..b must be Int (got $ft..$tt)", s.span)
                scoped {
                    s.symbol = declare(s.name, TInt, mutable = false, s.span)
                    val bt = checkExpr(s.body)
                    if (bt != TUnit && bt != TNever)
                        throw DawnError("the loop body's value is discarded ($bt)", s.body.span)
                }
            }
        }
    }
}
