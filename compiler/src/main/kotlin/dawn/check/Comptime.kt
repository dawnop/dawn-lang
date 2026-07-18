package dawn.check

import dawn.ast.*
import dawn.diag.DawnError
import dawn.diag.DiagnosticSink
import dawn.diag.Span

/**
 * Compile-time evaluation (spec §7): a plain AST interpreter over the pure
 * subset. Top-level const initializers and comptime blocks run here after
 * checking; the results are embedded as constants by codegen.
 *
 * Guarantees: only pure code reaches this point (the checker rejects io), and
 * a fuel budget plus a call-depth cap make evaluation always terminate.
 */

/** A comptime value. Function values may exist during evaluation but cannot be a result. */
sealed class CValue {
    class VInt(val v: Long) : CValue()
    class VFloat(val v: Double) : CValue()
    class VBool(val v: Boolean) : CValue()
    class VString(val v: String) : CValue()
    object VUnit : CValue()
    class VList(val elems: List<CValue>) : CValue()
    class VTuple(val elems: List<CValue>) : CValue()
    class VAdt(val ctor: CtorInfo, val fields: List<CValue>) : CValue()

    /** a Dawn function value: a lambda closure, a top-level fn, or a builtin */
    class VLambda(val params: List<Symbol>, val body: Expr, val env: Map<Symbol, CValue>) : CValue()
    class VFnRef(val decl: FnDecl) : CValue()
    class VBuiltin(val sig: FnSig) : CValue()
}

/**
 * Evaluate all comptime constructs of a checked module: consts in declaration
 * order, then comptime blocks inside function and test bodies. Failures become
 * ordinary diagnostics on the sink.
 */
fun evalComptime(module: Module, sink: DiagnosticSink, fuel: Long, stdFns: Map<String, FnDecl> = emptyMap()) {
    // The interpreter is a tree walker, so one Dawn call costs a dozen JVM frames.
    // Since std's list functions are now ordinary Dawn recursion, folding a const
    // over a few thousand elements would exhaust the default stack and crash the
    // compiler outright. Give the evaluation a stack of its own; `fuel` remains the
    // real bound on runaway evaluation, and a StackOverflowError past even this
    // becomes a diagnostic rather than a crash.
    var failure: Throwable? = null
    val worker = Thread(null, { runComptime(module, sink, fuel, stdFns) }, "dawn-comptime", COMPTIME_STACK_BYTES)
    worker.setUncaughtExceptionHandler { _, t -> failure = t }
    worker.start()
    worker.join()
    failure?.let { throw it }
}

private fun tooDeep(span: dawn.diag.Span) = DawnError(
    "comptime: evaluation nested too deeply", span,
    "the compile-time interpreter recurses per Dawn call, so a very deep recursion " +
        "runs out of stack; rewrite it as a fold or shrink the input")

/**
 * Deep enough that folding a const over a realistic list still works — std's list
 * functions are Dawn recursion now, so the depth is the input length, where the
 * old Kotlin builtins looped. `fuel` is what actually bounds runaway evaluation;
 * this cap only turns a stack overflow into a decent message. (The principled fix
 * is tail calls in the interpreter, which codegen already does — see the design doc.)
 */
private const val MAX_CALL_DEPTH = 100_000

/** 64 MB: room for deep interpreted recursion without pretending the depth is unbounded. */
private const val COMPTIME_STACK_BYTES = 64L * 1024 * 1024

private fun runComptime(module: Module, sink: DiagnosticSink, fuel: Long, stdFns: Map<String, FnDecl>) {
    // std is implicitly visible to user code, so it must be callable from a const
    // too; a local definition still shadows it, matching the checker's
    // local → std → builtin order. Empty while std itself is being checked, which
    // is what keeps the bootstrap acyclic.
    val fnsByName = stdFns + module.fns.associateBy { it.name }
    for (c in module.consts) {
        try {
            c.value = ComptimeInterp(fnsByName, fuel, stdFns.keys).eval(c.init, HashMap())
        } catch (e: DawnError) {
            sink.add(e)
        } catch (e: StackOverflowError) {
            sink.add(tooDeep(c.init.span))
        }
    }
    val walker = object {
        fun walkExpr(e: Expr) {
            when (e) {
                is ComptimeExpr -> {
                    if (e.value == null) {
                        try {
                            e.value = ComptimeInterp(fnsByName, fuel, stdFns.keys).eval(e.body, HashMap())
                        } catch (err: DawnError) {
                            sink.add(err)
                        } catch (err: StackOverflowError) {
                            sink.add(tooDeep(e.body.span))
                        }
                    }
                }
                is StrLit -> e.parts.forEach { if (it is StrPart.Interp) walkExpr(it.expr) }
                is Lambda -> walkExpr(e.body)
                is Apply -> { walkExpr(e.target); e.args.forEach(::walkExpr) }
                is MethodCall -> { walkExpr(e.target); e.args.forEach(::walkExpr) }
                is Propagate -> walkExpr(e.operand)
                is Unwrap -> walkExpr(e.operand)
                is Return -> e.value?.let(::walkExpr)
                is Index -> { walkExpr(e.target); walkExpr(e.index) }
                is Call -> e.args.forEach(::walkExpr)
                is CtorCall -> { e.spread?.let(::walkExpr); e.args.forEach { walkExpr(it.expr) } }
                is FieldAccess -> walkExpr(e.target)
                is ListLit -> e.elems.forEach(::walkExpr)
                is TupleLit -> e.elems.forEach(::walkExpr)
                is Binary -> { walkExpr(e.left); walkExpr(e.right) }
                is Unary -> walkExpr(e.operand)
                is If -> { walkExpr(e.cond); walkExpr(e.thenBranch); e.elseBranch?.let(::walkExpr) }
                is Match -> {
                    walkExpr(e.scrutinee)
                    e.arms.forEach { arm -> arm.guard?.let(::walkExpr); walkExpr(arm.body) }
                }
                is Block -> { e.stmts.forEach(::walkStmt); e.tail?.let(::walkExpr) }
                else -> {}
            }
        }

        fun walkStmt(s: Stmt) {
            when (s) {
                is LetStmt -> walkExpr(s.init)
                is LetPatStmt -> walkExpr(s.init)
                is LocalFnStmt -> walkExpr(s.lambda.body)
                is AssignStmt -> walkExpr(s.value)
                is ExprStmt -> walkExpr(s.expr)
                is AssertStmt -> walkExpr(s.cond)
                is WhileStmt -> { walkExpr(s.cond); walkExpr(s.body) }
                is ForStmt -> { walkExpr(s.from); s.to?.let(::walkExpr); walkExpr(s.body) }
            }
        }
    }
    for (d in module.fns) walker.walkExpr(d.body)
    for (t in module.tests) walker.walkExpr(t.body)
}

class ComptimeInterp(
    private val fns: Map<String, FnDecl>,
    private var fuel: Long,
    /** which of [fns] came from the bundled std, for diagnostics that must not point into it */
    private val stdFnNames: Set<String> = emptySet(),
) {
    private var depth = 0

    /** inside an `unsafe_pure` block, where route C is allowed to invoke Java */
    private var inUnsafePure = false

    private fun err(msg: String, span: Span, hint: String? = null): Nothing =
        throw DawnError("comptime: $msg", span, hint)

    /** `?` unwinding to the enclosing interpreted function */
    private class EarlyReturn(val value: CValue) : RuntimeException(null, null, false, false)

    private fun burn(span: Span) {
        if (--fuel < 0) {
            err("fuel exhausted — evaluation did not finish within the step budget", span,
                "raise it with --comptime-fuel, or simplify the computation")
        }
    }

    fun eval(e: Expr, env: MutableMap<Symbol, CValue>): CValue {
        burn(e.span)
        return when (e) {
            is IntLit -> CValue.VInt(e.value)
            is FloatLit -> CValue.VFloat(e.value)
            is BoolLit -> CValue.VBool(e.value)
            is UnitLit -> CValue.VUnit
            is StrLit -> CValue.VString(e.parts.joinToString("") { p ->
                when (p) {
                    is StrPart.Text -> p.value
                    is StrPart.Interp -> stringify(eval(p.expr, env))
                }
            })
            is VarRef -> {
                val fv = e.fnValue
                when {
                    fv == null -> env[e.symbol!!] ?: err("`${e.name}` is not bound (interpreter bug)", e.span)
                    fv.isBuiltin -> CValue.VBuiltin(fv)
                    else -> CValue.VFnRef(fns[fv.name] ?: err("missing function `${fv.name}`", e.span))
                }
            }
            is Lambda -> {
                val caps = HashMap<Symbol, CValue>()
                for (c in e.captures.orEmpty()) env[c]?.let { caps[c] = it }
                CValue.VLambda(e.params.map { it.symbol!! }, e.body, caps)
            }
            is ComptimeExpr -> eval(e.body, HashMap<Symbol, CValue>()).also { e.value = it }
            is UnsafePureExpr -> evalUnsafePure(e, env)
            is Propagate -> {
                val v = eval(e.operand, env) as CValue.VAdt
                when (v.ctor.name) {
                    "Some", "Ok" -> v.fields[0]
                    else -> throw EarlyReturn(v)
                }
            }
            // same semantics as the `expect` builtin above, minus the hand-written message
            is Unwrap -> {
                val v = eval(e.operand, env) as CValue.VAdt
                if (v.ctor.name == "Some") v.fields[0]
                else err("panicked: ${e.panicMsg ?: "unwrapped None"}", e.span)
            }
            is MethodCall -> if (e.isJava) evalJavaCall(e, env) else eval(e.desugared!!, env)
            is Return -> throw EarlyReturn(if (e.value != null) eval(e.value, env) else CValue.VUnit)
            is Index -> {
                val target = eval(e.target, env)
                val i = eval(e.index, env)
                if (target is CValue.VList && i is CValue.VInt) {
                    if (i.v < 0 || i.v >= target.elems.size)
                        err("index ${i.v} out of bounds for length ${target.elems.size}", e.span)
                    else target.elems[i.v.toInt()]
                } else err("`[]` in comptime indexes List only", e.span)
            }
            is Call -> evalCall(e, env)
            is Apply -> {
                val f = eval(e.target, env)
                applyFn(f, e.args.map { eval(it, env) }, e.span)
            }
            is CtorCall -> {
                e.constDecl?.let { cd ->
                    return cd.value ?: err("const `${cd.name}` failed to evaluate", e.span)
                }
                val ci = e.ctor!!
                if (ci.fields.isEmpty()) return CValue.VAdt(ci, emptyList())
                val spread = e.spread?.let { eval(it, env) as CValue.VAdt }
                // written order first (effects don't exist here, but keep the semantics)
                val given = HashMap<Expr, CValue>()
                for (a in e.args) given[a.expr] = eval(a.expr, env)
                val fields = e.fieldExprs!!.mapIndexed { i, arg ->
                    if (arg != null) given[arg]!! else spread!!.fields[i]
                }
                CValue.VAdt(ci, fields)
            }
            is FieldAccess -> {
                val v = eval(e.target, env) as CValue.VAdt
                val idx = e.owner!!.fields.indexOfFirst { it.name == e.fieldName }
                v.fields[idx]
            }
            is ListLit -> CValue.VList(e.elems.map { eval(it, env) })
            is TupleLit -> CValue.VTuple(e.elems.map { eval(it, env) })
            is Binary -> evalBinary(e, env)
            is Unary -> when (e.op) {
                UnOp.NOT -> CValue.VBool(!(eval(e.operand, env) as CValue.VBool).v)
                UnOp.NEG -> when (val v = eval(e.operand, env)) {
                    is CValue.VInt -> CValue.VInt(-v.v)
                    is CValue.VFloat -> CValue.VFloat(-v.v)
                    else -> err("negation needs a number", e.span)
                }
            }
            is If -> {
                if ((eval(e.cond, env) as CValue.VBool).v) eval(e.thenBranch, env)
                else e.elseBranch?.let { eval(it, env) } ?: CValue.VUnit
            }
            is Match -> {
                // Symbols are unique per declaration site, so one flat env per
                // function invocation is safe: bindings from a failed pattern
                // are never read (their symbols live only in that arm's body).
                val scrut = eval(e.scrutinee, env)
                for (arm in e.arms) {
                    if (!arm.patterns.any { matchPat(it, scrut, env) }) continue
                    if (arm.guard != null && !(eval(arm.guard!!, env) as CValue.VBool).v) continue
                    return eval(arm.body, env)
                }
                err("no match arm matched (checker bug?)", e.span)
            }
            is Block -> {
                for (s in e.stmts) execStmt(s, env)
                e.tail?.let { eval(it, env) } ?: CValue.VUnit
            }
            is UnsafePureExpr -> evalUnsafePure(e, env)
        }
    }

    /**
     * unsafe_pure at compile time. The block type-checks as Pure, so it may sit
     * in a const/comptime position — but folding it means running the vouched
     * Java call reflectively (docs/pure-ffi-design.md route C), which is not yet
     * implemented. Until then, refuse rather than silently mis-fold.
     */
    private fun evalUnsafePure(e: UnsafePureExpr, env: MutableMap<Symbol, CValue>): CValue {
        val saved = inUnsafePure
        inUnsafePure = true
        try {
            return eval(e.body, env)
        } finally {
            inUnsafePure = saved
        }
    }

    /**
     * Route C (docs/pure-ffi-design.md): fold a vouched Java call by invoking it
     * reflectively. This runs real Java inside the compiler, so it is deliberately
     * narrow — only reachable through [evalUnsafePure], only static methods, and
     * only across the scalar/String boundary the std wrappers actually use. The
     * reward is that "pure ⟺ comptime-foldable" survives the builtin migration:
     * `const` keeps folding after a function moves from the builtin table to std.
     */
    private fun evalJavaCall(e: MethodCall, env: MutableMap<Symbol, CValue>): CValue {
        val m = e.javaMethod
            ?: err("Java constructors are not available at compile time", e.span)
        if (!inUnsafePure) {
            err("a Java call can only be folded inside `unsafe_pure`", e.span,
                "the block is where purity is vouched for; without it the call is !io and " +
                    "cannot reach a const in the first place")
        }
        if (!java.lang.reflect.Modifier.isStatic(m.modifiers)) {
            err("only static Java methods can be folded", e.nameSpan,
                "`${m.declaringClass.simpleName}.${m.name}` needs a receiver, and comptime " +
                    "has no way to build a Java object")
        }
        val args = e.args.map { eval(it, env) }
        val marshalled = m.parameterTypes.zip(args).map { (p, a) -> toJava(p, a, e.span) }
        // a Java call is opaque to the fuel counter, so charge a flat cost: it
        // cannot be interrupted once entered, but it also cannot be free
        burnN(100, e.span)
        val result = try {
            m.invoke(null, *marshalled.toTypedArray())
        } catch (t: java.lang.reflect.InvocationTargetException) {
            err("`${m.declaringClass.simpleName}.${m.name}` threw " +
                "${t.targetException}", e.span,
                "the unsafe_pure around this call vouches that it is pure and total; " +
                    "a throw means that promise does not hold for these arguments")
        } catch (t: IllegalAccessException) {
            err("`${m.declaringClass.simpleName}.${m.name}` is not accessible", e.span)
        }
        return fromJava(m.returnType, result, e.span)
    }

    /** Dawn value → Java argument; mirrors the codegen marshalling (spec §9.2). */
    private fun toJava(p: Class<*>, v: CValue, span: Span): Any? = when {
        p == java.lang.Long.TYPE && v is CValue.VInt -> v.v
        p == Integer.TYPE && v is CValue.VInt -> v.v.toInt()
        p == java.lang.Double.TYPE && v is CValue.VFloat -> v.v
        p == java.lang.Boolean.TYPE && v is CValue.VBool -> v.v
        p == String::class.java && v is CValue.VString -> v.v
        else -> err("cannot pass this argument to Java at compile time", span,
            "route C marshals Int/Float/Bool/String only; got a ${v.javaClass.simpleName} " +
                "for a ${p.simpleName} parameter")
    }

    /** Java result → Dawn value; must agree with `Checker.mapJavaReturn` or folding would lie. */
    private fun fromJava(rt: Class<*>, r: Any?, span: Span): CValue = when (rt) {
        java.lang.Void.TYPE -> CValue.VUnit
        java.lang.Long.TYPE, Integer.TYPE, java.lang.Short.TYPE, java.lang.Byte.TYPE ->
            CValue.VInt((r as Number).toLong())
        java.lang.Double.TYPE, java.lang.Float.TYPE -> CValue.VFloat((r as Number).toDouble())
        java.lang.Boolean.TYPE -> CValue.VBool(r as Boolean)
        // reference returns arrive wrapped in Option, null being None
        String::class.java -> if (r == null) none() else some(CValue.VString(r as String))
        else -> err("cannot bring this Java result back at compile time", span,
            "route C returns Int/Float/Bool/String (and Unit) only; got ${rt.simpleName}")
    }

    private fun execStmt(s: Stmt, env: MutableMap<Symbol, CValue>) {
        burn(s.span)
        when (s) {
            is LetStmt -> {
                val v = eval(s.init, env)
                s.symbol?.let { env[it] = v }
            }
            is LocalFnStmt -> {
                // the captured env holds the lambda itself, so it can recurse
                val capEnv = HashMap(env)
                val v = CValue.VLambda(s.lambda.params.map { it.symbol!! }, s.lambda.body, capEnv)
                capEnv[s.symbol!!] = v
                env[s.symbol!!] = v
            }
            is LetPatStmt -> {
                val v = eval(s.init, env)
                if (!matchPat(s.pattern, v, env))
                    err("irrefutable pattern failed to match (checker bug?)", s.span)
            }
            is AssignStmt -> env[s.symbol!!] = eval(s.value, env)
            is ExprStmt -> { eval(s.expr, env) }
            is AssertStmt -> err("assert cannot appear in comptime code", s.span)
            is WhileStmt -> {
                while ((eval(s.cond, env) as CValue.VBool).v) {
                    burn(s.span)
                    eval(s.body, env)
                }
            }
            is ForStmt -> {
                val sym = s.symbol!!
                if (s.to == null) {
                    for (v in (eval(s.from, env) as CValue.VList).elems) {
                        burn(s.span)
                        env[sym] = v
                        eval(s.body, env)
                    }
                } else {
                    val from = (eval(s.from, env) as CValue.VInt).v
                    val to = (eval(s.to!!, env) as CValue.VInt).v
                    for (i in from until to) {
                        burn(s.span)
                        env[sym] = CValue.VInt(i)
                        eval(s.body, env)
                    }
                }
            }
        }
    }

    // ---- calls ----

    private fun evalCall(e: Call, env: MutableMap<Symbol, CValue>): CValue {
        if (!e.witnesses.isNullOrEmpty())
            err("`${e.callee}` uses trait bounds, which comptime cannot evaluate yet", e.span,
                "trait dictionaries are a runtime construct in v1")
        e.dynamicTarget?.let { sym ->
            val f = env[sym] ?: err("`${e.callee}` is not bound (interpreter bug)", e.span)
            return applyFn(f, e.args.map { eval(it, env) }, e.span)
        }
        val sig = e.sig!!
        val args = e.args.map { eval(it, env) }
        if (sig.isBuiltin) return callBuiltin(sig.name, args, e.span)
        val decl = fns[e.callee] ?: err("missing function `${e.callee}`", e.span)
        // A failure inside std carries a span into the std source, which the caller
        // would render against the *user's* file — garbage carets. Re-point it at
        // the call site, which is the part of the program the user can act on.
        if (stdFnNames.contains(e.callee)) {
            try {
                return callFn(decl, args, e.span)
            } catch (err: DawnError) {
                throw DawnError(err.message ?: "std call failed", e.span,
                    "raised inside the standard library function `${e.callee}`")
            }
        }
        return callFn(decl, args, e.span)
    }

    private fun callFn(decl: FnDecl, args: List<CValue>, span: Span): CValue {
        if (++depth > MAX_CALL_DEPTH) {
            depth--
            err("call depth limit ($MAX_CALL_DEPTH) exceeded", span,
                "deep recursion does not fit comptime; use a loop or fold")
        }
        try {
            val env = HashMap<Symbol, CValue>()
            for ((p, v) in decl.params.zip(args)) env[p.symbol!!] = v
            return try {
                eval(decl.body, env)
            } catch (r: EarlyReturn) {
                r.value
            }
        } finally {
            depth--
        }
    }

    private fun applyFn(f: CValue, args: List<CValue>, span: Span): CValue = when (f) {
        is CValue.VLambda -> {
            if (++depth > MAX_CALL_DEPTH) { depth--; err("call depth limit ($MAX_CALL_DEPTH) exceeded", span) }
            try {
                val env = HashMap(f.env)
                for ((p, v) in f.params.zip(args)) env[p] = v
                eval(f.body, env)
            } finally {
                depth--
            }
        }
        is CValue.VFnRef -> callFn(f.decl, args, span)
        is CValue.VBuiltin -> callBuiltin(f.sig.name, args, span)
        else -> err("cannot call a non-function value", span)
    }

    // ---- builtins (the pure ones; io never reaches the interpreter) ----

    private fun callBuiltin(name: String, args: List<CValue>, span: Span): CValue = when (name) {
        "panic" -> err("panicked: ${(args[0] as CValue.VString).v}", span)
        "todo" -> err("panicked: not yet implemented", span)
        "expect" -> {
            val o = args[0] as CValue.VAdt
            if (o.ctor.name == "Some") o.fields[0]
            else err("panicked: ${(args[1] as CValue.VString).v}", span)
        }
        "unwrap_or" -> {
            val o = args[0] as CValue.VAdt
            if (o.ctor.name == "Some") o.fields[0] else args[1]
        }
        "to_float" -> CValue.VFloat((args[0] as CValue.VInt).v.toDouble())
        "to_int" -> CValue.VInt((args[0] as CValue.VFloat).v.toLong())
        "to_string" -> CValue.VString(stringify(args[0]))
        "len" -> CValue.VInt((args[0] as CValue.VList).elems.size.toLong())
        "get" -> {
            val xs = (args[0] as CValue.VList).elems
            val i = (args[1] as CValue.VInt).v
            if (i in 0 until xs.size.toLong()) some(xs[i.toInt()]) else none()
        }
        "range" -> {
            val from = (args[0] as CValue.VInt).v
            val to = (args[1] as CValue.VInt).v
            burnN(to - from, span)
            CValue.VList((from until to).map { CValue.VInt(it) })
        }
        "sort_by" -> {
            val xs = (args[0] as CValue.VList).elems
            CValue.VList(xs.sortedWith { a, b ->
                (applyFn(args[1], listOf(a, b), span) as CValue.VInt).v.coerceIn(-1L, 1L).toInt()
            })
        }
        "chars" -> {
            val s = (args[0] as CValue.VString).v
            burnN(s.length.toLong(), span)
            val out = ArrayList<CValue>()
            var i = 0
            while (i < s.length) {
                val n = Character.charCount(s.codePointAt(i))
                out.add(CValue.VString(s.substring(i, i + n)))
                i += n
            }
            CValue.VList(out)
        }
        "join" -> CValue.VString(
            (args[0] as CValue.VList).elems.joinToString((args[1] as CValue.VString).v) {
                (it as CValue.VString).v
            })
        "split" -> {
            val s = (args[0] as CValue.VString).v
            val sep = (args[1] as CValue.VString).v
            if (sep.isEmpty()) callBuiltin("chars", listOf(args[0]), span)
            else CValue.VList(s.split(sep).map { CValue.VString(it) })
        }
        "parse_int" -> try {
            some(CValue.VInt((args[0] as CValue.VString).v.trim().toLong()))
        } catch (e: NumberFormatException) {
            none()
        }
        "parse_float" -> try {
            some(CValue.VFloat((args[0] as CValue.VString).v.trim().toDouble()))
        } catch (e: NumberFormatException) {
            none()
        }
        else -> err("builtin `$name` is not available at comptime", span)
    }

    private fun burnN(n: Long, span: Span) {
        fuel -= maxOf(0, n)
        if (fuel < 0) err("fuel exhausted — evaluation did not finish within the step budget", span,
            "raise it with --comptime-fuel, or simplify the computation")
    }

    private fun some(v: CValue) = CValue.VAdt(OPTION_ADT.ctors.first { it.name == "Some" }, listOf(v))
    private fun none() = CValue.VAdt(OPTION_ADT.ctors.first { it.name == "None" }, emptyList())

    // ---- operators ----

    private fun evalBinary(e: Binary, env: MutableMap<Symbol, CValue>): CValue {
        if (e.op == BinOp.AND || e.op == BinOp.OR) {
            val l = (eval(e.left, env) as CValue.VBool).v
            return when {
                e.op == BinOp.AND && !l -> CValue.VBool(false)
                e.op == BinOp.OR && l -> CValue.VBool(true)
                else -> eval(e.right, env)
            }
        }
        val l = eval(e.left, env)
        val r = eval(e.right, env)
        return when (e.op) {
            BinOp.ADD, BinOp.SUB, BinOp.MUL, BinOp.DIV, BinOp.MOD -> arith(e, l, r)
            BinOp.CONCAT -> when {
                l is CValue.VString && r is CValue.VString -> CValue.VString(l.v + r.v)
                l is CValue.VList && r is CValue.VList -> CValue.VList(l.elems + r.elems)
                else -> err("`++` needs two Strings or two Lists", e.opSpan)
            }
            BinOp.EQ -> CValue.VBool(valueEq(l, r))
            BinOp.NEQ -> CValue.VBool(!valueEq(l, r))
            BinOp.LT, BinOp.LE, BinOp.GT, BinOp.GE -> {
                if (e.ordWitness != null)
                    err("ordering through a trait impl is not supported in comptime yet", e.opSpan,
                        "trait dictionaries are a runtime construct in v1")
                val c = when {
                    l is CValue.VInt && r is CValue.VInt -> l.v.compareTo(r.v)
                    l is CValue.VString && r is CValue.VString -> l.v.compareTo(r.v)
                    l is CValue.VFloat && r is CValue.VFloat -> {
                        // NaN: every ordered comparison is false (spec §4.3)
                        if (l.v.isNaN() || r.v.isNaN()) return CValue.VBool(false)
                        l.v.compareTo(r.v)
                    }
                    else -> err("cannot order these values", e.opSpan)
                }
                CValue.VBool(when (e.op) {
                    BinOp.LT -> c < 0; BinOp.LE -> c <= 0; BinOp.GT -> c > 0; else -> c >= 0
                })
            }
            else -> err("unexpected operator", e.opSpan)
        }
    }

    private fun arith(e: Binary, l: CValue, r: CValue): CValue = when {
        l is CValue.VInt && r is CValue.VInt -> {
            val a = l.v
            val b = r.v
            when (e.op) {
                BinOp.ADD -> CValue.VInt(a + b)
                BinOp.SUB -> CValue.VInt(a - b)
                BinOp.MUL -> CValue.VInt(a * b)
                BinOp.DIV ->
                    if (b == 0L) err("panicked: division by zero", e.opSpan) else CValue.VInt(a / b)
                else ->
                    if (b == 0L) err("panicked: division by zero", e.opSpan) else CValue.VInt(a % b)
            }
        }
        l is CValue.VFloat && r is CValue.VFloat -> {
            val a = l.v
            val b = r.v
            CValue.VFloat(when (e.op) {
                BinOp.ADD -> a + b; BinOp.SUB -> a - b; BinOp.MUL -> a * b
                BinOp.DIV -> a / b; else -> a % b
            })
        }
        else -> err("arithmetic needs two numbers of the same type", e.opSpan)
    }

    private fun valueEq(a: CValue, b: CValue): Boolean = when {
        a is CValue.VInt && b is CValue.VInt -> a.v == b.v
        a is CValue.VFloat && b is CValue.VFloat -> a.v == b.v // NaN != NaN, like DCMPL
        a is CValue.VBool && b is CValue.VBool -> a.v == b.v
        a is CValue.VString && b is CValue.VString -> a.v == b.v
        a is CValue.VUnit && b is CValue.VUnit -> true
        a is CValue.VList && b is CValue.VList ->
            a.elems.size == b.elems.size && a.elems.zip(b.elems).all { (x, y) -> valueEq(x, y) }
        a is CValue.VTuple && b is CValue.VTuple ->
            a.elems.size == b.elems.size && a.elems.zip(b.elems).all { (x, y) -> valueEq(x, y) }
        a is CValue.VAdt && b is CValue.VAdt ->
            a.ctor === b.ctor && a.fields.zip(b.fields).all { (x, y) -> valueEq(x, y) }
        else -> false
    }

    private fun stringify(v: CValue): String = when (v) {
        is CValue.VInt -> v.v.toString()
        is CValue.VFloat -> v.v.toString()
        is CValue.VBool -> v.v.toString()
        is CValue.VString -> v.v
        else -> "<value>" // unreachable: the checker restricts printable types
    }

    // ---- patterns ----

    private fun matchPat(p: Pattern, v: CValue, env: MutableMap<Symbol, CValue>): Boolean = when (p) {
        is WildPat -> true
        is BindPat -> {
            p.symbol?.let { env[it] = v }
            true
        }
        is LitPat -> when (val lit = p.lit) {
            is IntLit -> (v as CValue.VInt).v == lit.value
            is FloatLit -> (v as CValue.VFloat).v == lit.value
            is BoolLit -> (v as CValue.VBool).v == lit.value
            is StrLit -> (v as CValue.VString).v ==
                lit.parts.joinToString("") { (it as StrPart.Text).value }
            else -> false
        }
        is TuplePat -> {
            val t = v as CValue.VTuple
            p.elems.zip(t.elems).all { (sub, x) -> matchPat(sub, x, env) }
        }
        is ListPat -> {
            val xs = (v as CValue.VList).elems
            val fixed = p.pre.size + p.post.size
            val lenOk = if (p.hasRest) xs.size >= fixed else xs.size == fixed
            lenOk &&
                p.pre.withIndex().all { (i, sub) -> matchPat(sub, xs[i], env) } &&
                p.post.withIndex().all { (j, sub) ->
                    matchPat(sub, xs[xs.size - p.post.size + j], env)
                } &&
                (p.restSymbol?.let {
                    env[it] = CValue.VList(xs.subList(p.pre.size, xs.size - p.post.size).toList())
                    true
                } ?: true)
        }
        is CtorPat -> {
            val adt = v as CValue.VAdt
            if (adt.ctor !== p.ctor) false
            else p.fieldPats!!.withIndex().all { (i, sub) ->
                sub == null || matchPat(sub, adt.fields[i], env)
            }
        }
    }
}
