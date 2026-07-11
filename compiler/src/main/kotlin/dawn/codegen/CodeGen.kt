package dawn.codegen

import dawn.ast.*
import dawn.check.BUILTINS
import dawn.check.Symbol
import dawn.check.Type
import dawn.check.Type.*
import org.objectweb.asm.ClassWriter
import org.objectweb.asm.Label
import org.objectweb.asm.MethodVisitor
import org.objectweb.asm.Opcodes.*

/**
 * AST (annotated with types/symbols by the Checker) → JVM bytecode. spec §12.2.
 *
 * Mapping: module → class (static methods); Int → long, Float → double,
 * Bool → boolean, String → java.lang.String, Unit → void. match → comparison
 * chains. Self-recursive tail calls → goto loops. panic → dawn.rt.PanicError
 * (an Error subclass). No invokedynamic (until lambdas), which keeps
 * native-image configuration-free (spec §12.3).
 */
class CodeGen(private val module: Module, private val className: String) {

    companion object {
        const val PANIC_CLASS = "dawn/rt/PanicError"
        private const val SB = "java/lang/StringBuilder"
    }

    /**
     * COMPUTE_FRAMES needs common superclasses; our generated classes are not on
     * the compiler's classpath, so fall back to Object.
     */
    private class DawnClassWriter : ClassWriter(COMPUTE_FRAMES) {
        override fun getCommonSuperClass(type1: String, type2: String): String =
            try {
                super.getCommonSuperClass(type1, type2)
            } catch (e: Throwable) {
                "java/lang/Object"
            }
    }

    // ---- current function context ----
    private lateinit var mv: MethodVisitor
    private var currentFn: FnDecl? = null
    private var fnStart: Label? = null
    private var nextSlot = 0

    fun generate(): Map<String, ByteArray> {
        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, className, null, "java/lang/Object", null)

        for (d in module.decls) genFn(cw, d)
        if (module.decls.any { it.name == "main" }) genJvmMain(cw)

        cw.visitEnd()
        return mapOf(
            className to cw.toByteArray(),
            PANIC_CLASS to genPanicClass(),
        )
    }

    // ---- type mapping ----

    private fun descOf(t: Type): String = when (t) {
        TInt -> "J"
        TFloat -> "D"
        TBool -> "Z"
        TString -> "Ljava/lang/String;"
        TUnit -> "V"
        TNever -> "V" // only in return position in theory; Never expressions end in athrow
        TError -> "V" // unreachable: codegen only runs when there are no errors
    }

    private fun methodDesc(params: List<Type>, ret: Type): String =
        params.joinToString("", "(", ")") { descOf(it) } + descOf(ret)

    private fun slotsOf(t: Type): Int = when (t) {
        TInt, TFloat -> 2
        TBool -> 1
        TString -> 1
        TUnit, TNever, TError -> 0
    }

    // ---- functions ----

    private fun genFn(cw: ClassWriter, d: FnDecl) {
        val paramTypes = d.params.map { it.symbol!!.type }
        val retType = returnTypeOf(d)
        mv = cw.visitMethod(
            ACC_PUBLIC or ACC_STATIC, d.name,
            methodDesc(paramTypes, retType), null, null,
        )
        mv.visitCode()
        currentFn = d
        nextSlot = 0
        for (p in d.params) {
            val sym = p.symbol!!
            sym.slot = nextSlot
            nextSlot += slotsOf(sym.type)
        }
        val start = Label()
        fnStart = start
        mv.visitLabel(start)
        val falls = genExpr(d.body, tail = true)
        if (falls) {
            when (retType) {
                TInt -> mv.visitInsn(LRETURN)
                TFloat -> mv.visitInsn(DRETURN)
                TBool -> mv.visitInsn(IRETURN)
                TString -> mv.visitInsn(ARETURN)
                else -> mv.visitInsn(RETURN)
            }
        }
        mv.visitMaxs(0, 0)
        mv.visitEnd()
    }

    private fun returnTypeOf(d: FnDecl): Type =
        Type.named(d.retType.name) ?: TUnit

    /** JVM entry wrapper: catch PanicError → stderr + exit 1 (spec §8.2) */
    private fun genJvmMain(cw: ClassWriter) {
        val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "main", "([Ljava/lang/String;)V", null, null)
        m.visitCode()
        val tryStart = Label()
        val tryEnd = Label()
        val handler = Label()
        m.visitTryCatchBlock(tryStart, tryEnd, handler, PANIC_CLASS)
        m.visitLabel(tryStart)
        m.visitMethodInsn(INVOKESTATIC, className, "main", "()V", false)
        m.visitLabel(tryEnd)
        m.visitInsn(RETURN)
        m.visitLabel(handler)
        m.visitVarInsn(ASTORE, 1)
        m.visitFieldInsn(GETSTATIC, "java/lang/System", "err", "Ljava/io/PrintStream;")
        m.visitTypeInsn(NEW, SB)
        m.visitInsn(DUP)
        m.visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
        m.visitLdcInsn("panic: ")
        m.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
        m.visitVarInsn(ALOAD, 1)
        m.visitMethodInsn(INVOKEVIRTUAL, PANIC_CLASS, "getMessage", "()Ljava/lang/String;", false)
        m.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
        m.visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()Ljava/lang/String;", false)
        m.visitMethodInsn(INVOKEVIRTUAL, "java/io/PrintStream", "println", "(Ljava/lang/String;)V", false)
        m.visitInsn(ICONST_1)
        m.visitMethodInsn(INVOKESTATIC, "java/lang/System", "exit", "(I)V", false)
        m.visitInsn(RETURN)
        m.visitMaxs(0, 0)
        m.visitEnd()
    }

    /** dawn/rt/PanicError extends Error */
    private fun genPanicClass(): ByteArray {
        val cw = ClassWriter(0)
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, PANIC_CLASS, null, "java/lang/Error", null)
        val ctor = cw.visitMethod(ACC_PUBLIC, "<init>", "(Ljava/lang/String;)V", null, null)
        ctor.visitCode()
        ctor.visitVarInsn(ALOAD, 0)
        ctor.visitVarInsn(ALOAD, 1)
        ctor.visitMethodInsn(INVOKESPECIAL, "java/lang/Error", "<init>", "(Ljava/lang/String;)V", false)
        ctor.visitInsn(RETURN)
        ctor.visitMaxs(2, 2)
        ctor.visitEnd()
        cw.visitEnd()
        return cw.toByteArray()
    }

    // ---- statements ----
    // Return value: whether control falls past the statement
    // (false = the statement always throws/jumps; what follows is unreachable).

    private fun genStmt(s: Stmt): Boolean = when (s) {
        is LetStmt -> {
            val initType = s.init.type!!
            val falls = genExpr(s.init, tail = false)
            if (falls) {
                if (s.isDiscard) {
                    popValue(initType)
                } else {
                    val sym = s.symbol!!
                    if (slotsOf(sym.type) > 0) {
                        sym.slot = nextSlot
                        nextSlot += slotsOf(sym.type)
                        storeVar(sym)
                    }
                }
            }
            falls
        }
        is AssignStmt -> {
            val falls = genExpr(s.value, tail = false)
            if (falls) {
                val sym = s.symbol!!
                if (slotsOf(sym.type) > 0) storeVar(sym)
            }
            falls
        }
        is ExprStmt -> genExpr(s.expr, tail = false) // type is Unit/Never, nothing left on the stack
        is WhileStmt -> {
            val loop = Label()
            val end = Label()
            mv.visitLabel(loop)
            genExpr(s.cond, tail = false)
            mv.visitJumpInsn(IFEQ, end)
            if (genExpr(s.body, tail = false)) mv.visitJumpInsn(GOTO, loop)
            mv.visitLabel(end)
            true
        }
        is ForStmt -> {
            genExpr(s.from, tail = false)
            val sym = s.symbol!!
            sym.slot = nextSlot
            nextSlot += 2
            mv.visitVarInsn(LSTORE, sym.slot)
            genExpr(s.to, tail = false)
            val endSlot = nextSlot
            nextSlot += 2
            mv.visitVarInsn(LSTORE, endSlot)
            val loop = Label()
            val end = Label()
            mv.visitLabel(loop)
            mv.visitVarInsn(LLOAD, sym.slot)
            mv.visitVarInsn(LLOAD, endSlot)
            mv.visitInsn(LCMP)
            mv.visitJumpInsn(IFGE, end)
            val bodyFalls = genExpr(s.body, tail = false)
            if (bodyFalls) {
                mv.visitVarInsn(LLOAD, sym.slot)
                mv.visitInsn(LCONST_1)
                mv.visitInsn(LADD)
                mv.visitVarInsn(LSTORE, sym.slot)
                mv.visitJumpInsn(GOTO, loop)
            }
            mv.visitLabel(end)
            true
        }
    }

    private fun popValue(t: Type) {
        when (slotsOf(t)) {
            2 -> mv.visitInsn(POP2)
            1 -> mv.visitInsn(POP)
            else -> {}
        }
    }

    private fun storeVar(sym: Symbol) {
        when (sym.type) {
            TInt -> mv.visitVarInsn(LSTORE, sym.slot)
            TFloat -> mv.visitVarInsn(DSTORE, sym.slot)
            TBool -> mv.visitVarInsn(ISTORE, sym.slot)
            TString -> mv.visitVarInsn(ASTORE, sym.slot)
            else -> {}
        }
    }

    private fun loadVar(sym: Symbol) {
        when (sym.type) {
            TInt -> mv.visitVarInsn(LLOAD, sym.slot)
            TFloat -> mv.visitVarInsn(DLOAD, sym.slot)
            TBool -> mv.visitVarInsn(ILOAD, sym.slot)
            TString -> mv.visitVarInsn(ALOAD, sym.slot)
            else -> {}
        }
    }

    // ---- expressions ----
    // Return value: whether control falls past the expression, leaving its value
    // on the stack (Unit leaves nothing). false = control was transferred
    // (athrow / tail-call goto) and nothing is on the stack.

    private fun genExpr(e: Expr, tail: Boolean): Boolean = when (e) {
        is IntLit -> { mv.visitLdcInsn(e.value); true }
        is FloatLit -> { mv.visitLdcInsn(e.value); true }
        is BoolLit -> { mv.visitInsn(if (e.value) ICONST_1 else ICONST_0); true }
        is UnitLit -> true
        is StrLit -> genStrLit(e)
        is VarRef -> { loadVar(e.symbol!!); true }
        is Call -> genCall(e, tail)
        is Binary -> genBinary(e)
        is Unary -> {
            genExpr(e.operand, tail = false)
            when (e.op) {
                UnOp.NOT -> { mv.visitInsn(ICONST_1); mv.visitInsn(IXOR) }
                UnOp.NEG -> mv.visitInsn(if (e.operand.type == TInt) LNEG else DNEG)
            }
            true
        }
        is If -> genIf(e, tail)
        is Match -> genMatch(e, tail)
        is Block -> genBlock(e, tail)
    }

    private fun genBlock(e: Block, tail: Boolean): Boolean {
        for (s in e.stmts) {
            if (!genStmt(s)) return false // unreachable from here on; stop emitting
        }
        return if (e.tail != null) genExpr(e.tail!!, tail) else true
    }

    private fun genStrLit(e: StrLit): Boolean {
        // pure text → constant
        if (e.parts.all { it is StrPart.Text }) {
            mv.visitLdcInsn(e.parts.joinToString("") { (it as StrPart.Text).value })
            return true
        }
        mv.visitTypeInsn(NEW, SB)
        mv.visitInsn(DUP)
        mv.visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
        for (p in e.parts) {
            when (p) {
                is StrPart.Text -> {
                    mv.visitLdcInsn(p.value)
                    mv.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
                }
                is StrPart.Interp -> {
                    genExpr(p.expr, tail = false)
                    val d = when (p.expr.type!!) {
                        TInt -> "(J)L$SB;"
                        TFloat -> "(D)L$SB;"
                        TBool -> "(Z)L$SB;"
                        else -> "(Ljava/lang/String;)L$SB;"
                    }
                    mv.visitMethodInsn(INVOKEVIRTUAL, SB, "append", d, false)
                }
            }
        }
        mv.visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()Ljava/lang/String;", false)
        return true
    }

    private fun genCall(e: Call, tail: Boolean): Boolean {
        val builtin = BUILTINS[e.callee]
        if (builtin != null) return genBuiltinCall(e)

        val self = currentFn
        // self-recursive tail call → write args back to param slots + goto entry (spec §12.4)
        if (tail && self != null && e.callee == self.name) {
            for (a in e.args) genExpr(a, tail = false)
            for (p in self.params.reversed()) {
                val sym = p.symbol!!
                if (slotsOf(sym.type) > 0) storeVar(sym)
            }
            mv.visitJumpInsn(GOTO, fnStart!!)
            return false
        }
        for (a in e.args) genExpr(a, tail = false)
        val target = module.decls.first { it.name == e.callee }
        val paramTypes = target.params.map { Type.named(it.typeName.name)!! }
        val ret = returnTypeOf(target)
        mv.visitMethodInsn(INVOKESTATIC, className, e.callee, methodDesc(paramTypes, ret), false)
        return true
    }

    private fun genBuiltinCall(e: Call): Boolean = when (e.callee) {
        "println", "print" -> {
            mv.visitFieldInsn(GETSTATIC, "java/lang/System", "out", "Ljava/io/PrintStream;")
            genExpr(e.args[0], tail = false)
            mv.visitMethodInsn(
                INVOKEVIRTUAL, "java/io/PrintStream", e.callee,
                "(Ljava/lang/String;)V", false,
            )
            true
        }
        "panic" -> {
            mv.visitTypeInsn(NEW, PANIC_CLASS)
            mv.visitInsn(DUP)
            genExpr(e.args[0], tail = false)
            mv.visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
            mv.visitInsn(ATHROW)
            false
        }
        "todo" -> {
            mv.visitTypeInsn(NEW, PANIC_CLASS)
            mv.visitInsn(DUP)
            mv.visitLdcInsn("not yet implemented")
            mv.visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
            mv.visitInsn(ATHROW)
            false
        }
        else -> error("unknown builtin: ${e.callee}")
    }

    private fun genBinary(e: Binary): Boolean {
        // short-circuit logic handled separately
        if (e.op == BinOp.AND || e.op == BinOp.OR) {
            val short = Label()
            val end = Label()
            genExpr(e.left, tail = false)
            mv.visitJumpInsn(if (e.op == BinOp.AND) IFEQ else IFNE, short)
            genExpr(e.right, tail = false)
            mv.visitJumpInsn(GOTO, end)
            mv.visitLabel(short)
            mv.visitInsn(if (e.op == BinOp.AND) ICONST_0 else ICONST_1)
            mv.visitLabel(end)
            return true
        }

        genExpr(e.left, tail = false)
        genExpr(e.right, tail = false)
        val t = e.left.type!!
        when (e.op) {
            BinOp.ADD -> mv.visitInsn(if (t == TInt) LADD else DADD)
            BinOp.SUB -> mv.visitInsn(if (t == TInt) LSUB else DSUB)
            BinOp.MUL -> mv.visitInsn(if (t == TInt) LMUL else DMUL)
            BinOp.DIV -> mv.visitInsn(if (t == TInt) LDIV else DDIV)
            BinOp.MOD -> mv.visitInsn(if (t == TInt) LREM else DREM)
            BinOp.CONCAT ->
                mv.visitMethodInsn(
                    INVOKEVIRTUAL, "java/lang/String", "concat",
                    "(Ljava/lang/String;)Ljava/lang/String;", false,
                )
            BinOp.EQ, BinOp.NEQ -> genEquality(t, e.op)
            BinOp.LT, BinOp.LE, BinOp.GT, BinOp.GE -> genOrdering(t, e.op)
            else -> {}
        }
        return true
    }

    private fun genEquality(t: Type, op: BinOp) {
        when (t) {
            TString -> {
                mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/String", "equals", "(Ljava/lang/Object;)Z", false)
                if (op == BinOp.NEQ) { mv.visitInsn(ICONST_1); mv.visitInsn(IXOR) }
            }
            TBool -> {
                mv.visitInsn(IXOR) // 1 = different
                if (op == BinOp.EQ) { mv.visitInsn(ICONST_1); mv.visitInsn(IXOR) }
            }
            else -> {
                mv.visitInsn(if (t == TInt) LCMP else DCMPL)
                pushCmpResult(if (op == BinOp.EQ) IFEQ else IFNE)
            }
        }
    }

    private fun genOrdering(t: Type, op: BinOp) {
        when (t) {
            TInt -> mv.visitInsn(LCMP)
            TString -> mv.visitMethodInsn(
                INVOKEVIRTUAL, "java/lang/String", "compareTo", "(Ljava/lang/String;)I", false,
            )
            else -> // Float: NaN makes every ordered comparison false
                mv.visitInsn(if (op == BinOp.LT || op == BinOp.LE) DCMPG else DCMPL)
        }
        val jump = when (op) {
            BinOp.LT -> IFLT; BinOp.LE -> IFLE; BinOp.GT -> IFGT; else -> IFGE
        }
        pushCmpResult(jump)
    }

    /** Stack top is an int cmp result; convert to boolean 0/1 by the given jump condition. */
    private fun pushCmpResult(jumpIfTrue: Int) {
        val trueL = Label()
        val end = Label()
        mv.visitJumpInsn(jumpIfTrue, trueL)
        mv.visitInsn(ICONST_0)
        mv.visitJumpInsn(GOTO, end)
        mv.visitLabel(trueL)
        mv.visitInsn(ICONST_1)
        mv.visitLabel(end)
    }

    private fun genIf(e: If, tail: Boolean): Boolean {
        val elseL = Label()
        val end = Label()
        genExpr(e.cond, tail = false)
        mv.visitJumpInsn(IFEQ, elseL)
        val thenFalls = genExpr(e.thenBranch, tail)
        if (e.elseBranch == null) {
            mv.visitLabel(elseL)
            return true // statement if: a false condition falls through to here
        }
        if (thenFalls) mv.visitJumpInsn(GOTO, end)
        mv.visitLabel(elseL)
        val elseFalls = genExpr(e.elseBranch!!, tail)
        mv.visitLabel(end)
        return thenFalls || elseFalls
    }

    private fun genMatch(e: Match, tail: Boolean): Boolean {
        val scrutType = e.scrutinee.type!!
        genExpr(e.scrutinee, tail = false)
        val scrutSlot = nextSlot
        nextSlot += slotsOf(scrutType)
        when (scrutType) {
            TInt -> mv.visitVarInsn(LSTORE, scrutSlot)
            TString -> mv.visitVarInsn(ASTORE, scrutSlot)
            else -> mv.visitVarInsn(ISTORE, scrutSlot)
        }
        val end = Label()
        var anyFalls = false

        for (arm in e.arms) {
            val nextArm = Label()
            val body = Label()
            for ((i, p) in arm.patterns.withIndex()) {
                val isLast = i == arm.patterns.size - 1
                if (isLast) {
                    genPatternTest(p, scrutSlot, scrutType, failTo = nextArm)
                } else {
                    val tryNext = Label()
                    genPatternTest(p, scrutSlot, scrutType, failTo = tryNext)
                    mv.visitJumpInsn(GOTO, body)
                    mv.visitLabel(tryNext)
                }
            }
            mv.visitLabel(body)
            if (arm.guard != null) {
                genExpr(arm.guard!!, tail = false)
                mv.visitJumpInsn(IFEQ, nextArm)
            }
            val falls = genExpr(arm.body, tail)
            if (falls) {
                anyFalls = true
                mv.visitJumpInsn(GOTO, end)
            }
            mv.visitLabel(nextArm)
        }
        // the checker guarantees exhaustiveness; this is a defensive unreachable fallback
        mv.visitTypeInsn(NEW, PANIC_CLASS)
        mv.visitInsn(DUP)
        mv.visitLdcInsn("unreachable match")
        mv.visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
        mv.visitInsn(ATHROW)
        mv.visitLabel(end)
        return anyFalls
    }

    /** Emit a pattern test: fall through on success, jump to failTo on failure. Bind patterns also bind. */
    private fun genPatternTest(p: Pattern, scrutSlot: Int, scrutType: Type, failTo: Label) {
        when (p) {
            is WildPat -> {}
            is BindPat -> {
                p.symbol!!.slot = scrutSlot // a binding is an alias, not a copy
            }
            is LitPat -> when (scrutType) {
                TInt -> {
                    mv.visitVarInsn(LLOAD, scrutSlot)
                    mv.visitLdcInsn((p.lit as IntLit).value)
                    mv.visitInsn(LCMP)
                    mv.visitJumpInsn(IFNE, failTo)
                }
                TString -> {
                    mv.visitVarInsn(ALOAD, scrutSlot)
                    val lit = (p.lit as StrLit).parts.joinToString("") { (it as StrPart.Text).value }
                    mv.visitLdcInsn(lit)
                    mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/String", "equals", "(Ljava/lang/Object;)Z", false)
                    mv.visitJumpInsn(IFEQ, failTo)
                }
                else -> {
                    mv.visitVarInsn(ILOAD, scrutSlot)
                    val want = (p.lit as BoolLit).value
                    mv.visitJumpInsn(if (want) IFEQ else IFNE, failTo)
                }
            }
        }
    }
}
