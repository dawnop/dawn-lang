package dawn.codegen

import dawn.ast.*
import dawn.check.BUILTINS
import dawn.check.CtorInfo
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
 * Bool → boolean, String → java.lang.String, Unit → void. ADT → abstract base
 * class + one final subclass per constructor (no-payload constructors are
 * singletons). match → instanceof chains + field reads. Self-recursive tail
 * calls → goto loops. panic → dawn.rt.PanicError (an Error subclass). No
 * invokedynamic (until lambdas), which keeps native-image configuration-free
 * (spec §12.3).
 */
class CodeGen(private val module: Module, private val className: String) {

    companion object {
        const val PANIC_CLASS = "dawn/rt/PanicError"
        private const val SB = "java/lang/StringBuilder"
        private const val OBJ = "java/lang/Object"
    }

    /** super of every class we generate, so frames can be computed without loading them */
    private val adtSupers: Map<String, String> = buildMap {
        for (t in module.types) {
            put(t.name, OBJ)
            if (!t.isRecord) for (c in t.ctors) put("${t.name}$${c.name}", t.name)
        }
    }

    /**
     * COMPUTE_FRAMES needs common superclasses. Generated classes are not on the
     * compiler's classpath, so walk our own synthetic hierarchy (adtSupers); for
     * anything else fall back to Object.
     */
    private inner class DawnClassWriter : ClassWriter(COMPUTE_FRAMES) {
        private fun chain(t: String): List<String> {
            val c = ArrayList<String>()
            var cur: String? = t
            while (cur != null) {
                c.add(cur)
                cur = adtSupers[cur]
            }
            if (c.last() != OBJ) c.add(OBJ)
            return c
        }

        override fun getCommonSuperClass(type1: String, type2: String): String {
            if (type1 == type2) return type1
            if (adtSupers.containsKey(type1) || adtSupers.containsKey(type2)) {
                val above2 = chain(type2).toSet()
                return chain(type1).firstOrNull { it in above2 } ?: OBJ
            }
            return try {
                super.getCommonSuperClass(type1, type2)
            } catch (e: Throwable) {
                OBJ
            }
        }
    }

    // ---- current function context ----
    private lateinit var mv: MethodVisitor
    private var currentFn: FnDecl? = null
    private var fnStart: Label? = null
    private var nextSlot = 0

    fun generate(): Map<String, ByteArray> {
        val out = HashMap<String, ByteArray>()
        for (t in module.types) genAdt(t, out)

        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, className, null, OBJ, null)
        for (d in module.fns) genFn(cw, d)
        if (module.fns.any { it.name == "main" }) genJvmMain(cw)
        cw.visitEnd()

        out[className] = cw.toByteArray()
        out[PANIC_CLASS] = genPanicClass()
        return out
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
        is TAdt -> "L${t.info.jvmName};"
    }

    private fun methodDesc(params: List<Type>, ret: Type): String =
        params.joinToString("", "(", ")") { descOf(it) } + descOf(ret)

    private fun slotsOf(t: Type): Int = when (t) {
        TInt, TFloat -> 2
        TBool -> 1
        TString -> 1
        is TAdt -> 1
        TUnit, TNever, TError -> 0
    }

    private fun isRef(t: Type) = t == TString || t is TAdt

    // ---- ADT classes (spec §12.2) ----

    private fun genAdt(d: TypeDecl, out: MutableMap<String, ByteArray>) {
        val base = d.name
        if (d.isRecord) {
            // a record is one final class, no abstract base (spec §12.2)
            val ci = d.ctors.single().info!!
            out[ci.jvmName] = genCtorClass(OBJ, ci)
            return
        }
        val bw = DawnClassWriter()
        bw.visit(V17, ACC_PUBLIC or ACC_ABSTRACT, base, null, OBJ, null)
        val bc = bw.visitMethod(ACC_PROTECTED, "<init>", "()V", null, null)
        bc.visitCode()
        bc.visitVarInsn(ALOAD, 0)
        bc.visitMethodInsn(INVOKESPECIAL, OBJ, "<init>", "()V", false)
        bc.visitInsn(RETURN)
        bc.visitMaxs(1, 1)
        bc.visitEnd()
        bw.visitEnd()
        out[base] = bw.toByteArray()

        for (c in d.ctors) {
            val ci = c.info!! // codegen only runs on error-free modules
            out[ci.jvmName] = genCtorClass(base, ci)
        }
    }

    private fun genCtorClass(base: String, ci: CtorInfo): ByteArray {
        val sub = ci.jvmName
        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, sub, null, base, null)
        val singleton = ci.fields.isEmpty()

        for (f in ci.fields) {
            cw.visitField(ACC_PUBLIC or ACC_FINAL, f.name, descOf(f.type), null, null).visitEnd()
        }
        if (singleton) {
            cw.visitField(ACC_PUBLIC or ACC_STATIC or ACC_FINAL, "INSTANCE", "L$sub;", null, null).visitEnd()
            val cl = cw.visitMethod(ACC_STATIC, "<clinit>", "()V", null, null)
            cl.visitCode()
            cl.visitTypeInsn(NEW, sub)
            cl.visitInsn(DUP)
            cl.visitMethodInsn(INVOKESPECIAL, sub, "<init>", "()V", false)
            cl.visitFieldInsn(PUTSTATIC, sub, "INSTANCE", "L$sub;")
            cl.visitInsn(RETURN)
            cl.visitMaxs(2, 0)
            cl.visitEnd()
        }

        // constructor: store each field
        val ctorDesc = "(" + ci.fields.joinToString("") { descOf(it.type) } + ")V"
        val init = cw.visitMethod(if (singleton) ACC_PRIVATE else ACC_PUBLIC, "<init>", ctorDesc, null, null)
        init.visitCode()
        init.visitVarInsn(ALOAD, 0)
        init.visitMethodInsn(INVOKESPECIAL, base, "<init>", "()V", false)
        var slot = 1
        for (f in ci.fields) {
            init.visitVarInsn(ALOAD, 0)
            loadSlot(init, f.type, slot)
            init.visitFieldInsn(PUTFIELD, sub, f.name, descOf(f.type))
            slot += slotsOf(f.type)
        }
        init.visitInsn(RETURN)
        init.visitMaxs(0, 0)
        init.visitEnd()

        // structural equality (== in Dawn, spec §4.3); singletons keep identity equals
        if (!singleton) genEqualsMethod(cw, sub, ci)

        cw.visitEnd()
        return cw.toByteArray()
    }

    private fun genEqualsMethod(cw: ClassWriter, sub: String, ci: CtorInfo) {
        val m = cw.visitMethod(ACC_PUBLIC, "equals", "(L$OBJ;)Z", null, null)
        m.visitCode()
        val yes = Label()
        val no = Label()
        m.visitVarInsn(ALOAD, 0)
        m.visitVarInsn(ALOAD, 1)
        m.visitJumpInsn(IF_ACMPEQ, yes)
        m.visitVarInsn(ALOAD, 1)
        m.visitTypeInsn(INSTANCEOF, sub)
        m.visitJumpInsn(IFEQ, no)
        m.visitVarInsn(ALOAD, 1)
        m.visitTypeInsn(CHECKCAST, sub)
        m.visitVarInsn(ASTORE, 2)
        for (f in ci.fields) {
            m.visitVarInsn(ALOAD, 0)
            m.visitFieldInsn(GETFIELD, sub, f.name, descOf(f.type))
            m.visitVarInsn(ALOAD, 2)
            m.visitFieldInsn(GETFIELD, sub, f.name, descOf(f.type))
            when (f.type) {
                TInt -> { m.visitInsn(LCMP); m.visitJumpInsn(IFNE, no) }
                TFloat -> { m.visitInsn(DCMPL); m.visitJumpInsn(IFNE, no) }
                TBool -> m.visitJumpInsn(IF_ICMPNE, no)
                else -> {
                    m.visitMethodInsn(INVOKEVIRTUAL, OBJ, "equals", "(L$OBJ;)Z", false)
                    m.visitJumpInsn(IFEQ, no)
                }
            }
        }
        m.visitLabel(yes)
        m.visitInsn(ICONST_1)
        m.visitInsn(IRETURN)
        m.visitLabel(no)
        m.visitInsn(ICONST_0)
        m.visitInsn(IRETURN)
        m.visitMaxs(0, 0)
        m.visitEnd()
    }

    // ---- functions ----

    private fun genFn(cw: ClassWriter, d: FnDecl) {
        val sig = d.sig!!
        mv = cw.visitMethod(
            ACC_PUBLIC or ACC_STATIC, d.name,
            methodDesc(sig.paramTypes, sig.ret), null, null,
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
            when (sig.ret) {
                TInt -> mv.visitInsn(LRETURN)
                TFloat -> mv.visitInsn(DRETURN)
                TBool -> mv.visitInsn(IRETURN)
                TString, is TAdt -> mv.visitInsn(ARETURN)
                else -> mv.visitInsn(RETURN)
            }
        }
        mv.visitMaxs(0, 0)
        mv.visitEnd()
    }

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

    // ---- slot load/store ----

    private fun loadSlot(m: MethodVisitor, t: Type, slot: Int) {
        when {
            t == TInt -> m.visitVarInsn(LLOAD, slot)
            t == TFloat -> m.visitVarInsn(DLOAD, slot)
            t == TBool -> m.visitVarInsn(ILOAD, slot)
            isRef(t) -> m.visitVarInsn(ALOAD, slot)
            else -> {}
        }
    }

    private fun storeSlot(m: MethodVisitor, t: Type, slot: Int) {
        when {
            t == TInt -> m.visitVarInsn(LSTORE, slot)
            t == TFloat -> m.visitVarInsn(DSTORE, slot)
            t == TBool -> m.visitVarInsn(ISTORE, slot)
            isRef(t) -> m.visitVarInsn(ASTORE, slot)
            else -> {}
        }
    }

    private fun storeVar(sym: Symbol) = storeSlot(mv, sym.type, sym.slot)
    private fun loadVar(sym: Symbol) = loadSlot(mv, sym.type, sym.slot)

    private fun popValue(t: Type) {
        when (slotsOf(t)) {
            2 -> mv.visitInsn(POP2)
            1 -> mv.visitInsn(POP)
            else -> {}
        }
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
        is CtorCall -> genCtorCall(e)
        is FieldAccess -> {
            if (!genExpr(e.target, tail = false)) false
            else {
                val f = e.field!!
                mv.visitFieldInsn(GETFIELD, e.owner!!.jvmName, f.name, descOf(f.type))
                true
            }
        }
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
        val sig = e.sig!!
        mv.visitMethodInsn(INVOKESTATIC, className, e.callee, methodDesc(sig.paramTypes, sig.ret), false)
        return true
    }

    private fun genCtorCall(e: CtorCall): Boolean {
        val ci = e.ctor!!
        val sub = ci.jvmName
        if (ci.fields.isEmpty()) {
            mv.visitFieldInsn(GETSTATIC, sub, "INSTANCE", "L$sub;")
            return true
        }
        // evaluate the spread base and arguments in written order into temps
        // (named arguments may be out of field order, but effects must run as
        // written), then construct
        var spreadSlot = -1
        if (e.spread != null) {
            if (!genExpr(e.spread!!, tail = false)) return false
            spreadSlot = nextSlot
            nextSlot += 1
            mv.visitVarInsn(ASTORE, spreadSlot)
        }
        val tempOf = HashMap<Expr, Int>()
        for (a in e.args) {
            if (!genExpr(a.expr, tail = false)) return false
            val t = a.expr.type!!
            tempOf[a.expr] = nextSlot
            storeSlot(mv, t, nextSlot)
            nextSlot += slotsOf(t)
        }
        mv.visitTypeInsn(NEW, sub)
        mv.visitInsn(DUP)
        for ((i, arg) in e.fieldExprs!!.withIndex()) {
            if (arg != null) {
                loadSlot(mv, arg.type!!, tempOf[arg]!!)
            } else {
                // field not given: take it from the spread base
                val f = ci.fields[i]
                mv.visitVarInsn(ALOAD, spreadSlot)
                mv.visitFieldInsn(GETFIELD, sub, f.name, descOf(f.type))
            }
        }
        val desc = "(" + ci.fields.joinToString("") { descOf(it.type) } + ")V"
        mv.visitMethodInsn(INVOKESPECIAL, sub, "<init>", desc, false)
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
        when {
            t == TString || t is TAdt -> {
                // ADT subclasses override equals structurally; singletons keep identity
                mv.visitMethodInsn(INVOKEVIRTUAL, OBJ, "equals", "(L$OBJ;)Z", false)
                if (op == BinOp.NEQ) { mv.visitInsn(ICONST_1); mv.visitInsn(IXOR) }
            }
            t == TBool -> {
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
        storeSlot(mv, scrutType, scrutSlot)
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

    /**
     * Emit a pattern test against the value in [slot] (of type [type]): fall
     * through on success, jump to failTo on failure. Bind patterns also bind.
     */
    private fun genPatternTest(p: Pattern, slot: Int, type: Type, failTo: Label) {
        when (p) {
            is WildPat -> {}
            is BindPat -> {
                p.symbol!!.slot = slot // a binding is an alias, not a copy
            }
            is LitPat -> when (type) {
                TInt -> {
                    mv.visitVarInsn(LLOAD, slot)
                    mv.visitLdcInsn((p.lit as IntLit).value)
                    mv.visitInsn(LCMP)
                    mv.visitJumpInsn(IFNE, failTo)
                }
                TFloat -> {
                    mv.visitVarInsn(DLOAD, slot)
                    mv.visitLdcInsn((p.lit as FloatLit).value)
                    mv.visitInsn(DCMPL) // NaN never matches, same as ==
                    mv.visitJumpInsn(IFNE, failTo)
                }
                TString -> {
                    mv.visitVarInsn(ALOAD, slot)
                    val lit = (p.lit as StrLit).parts.joinToString("") { (it as StrPart.Text).value }
                    mv.visitLdcInsn(lit)
                    mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/String", "equals", "(L$OBJ;)Z", false)
                    mv.visitJumpInsn(IFEQ, failTo)
                }
                else -> {
                    mv.visitVarInsn(ILOAD, slot)
                    val want = (p.lit as BoolLit).value
                    mv.visitJumpInsn(if (want) IFEQ else IFNE, failTo)
                }
            }
            is CtorPat -> {
                val ci = p.ctor!!
                val sub = ci.jvmName
                if (ci.fields.isEmpty()) {
                    // no-payload constructors are singletons: identity test
                    mv.visitVarInsn(ALOAD, slot)
                    mv.visitFieldInsn(GETSTATIC, sub, "INSTANCE", "L$sub;")
                    mv.visitJumpInsn(IF_ACMPNE, failTo)
                    return
                }
                mv.visitVarInsn(ALOAD, slot)
                mv.visitTypeInsn(INSTANCEOF, sub)
                mv.visitJumpInsn(IFEQ, failTo)
                for ((i, fp) in p.fieldPats!!.withIndex()) {
                    if (fp == null || fp is WildPat) continue
                    val ft = ci.fields[i].type
                    mv.visitVarInsn(ALOAD, slot)
                    mv.visitTypeInsn(CHECKCAST, sub)
                    mv.visitFieldInsn(GETFIELD, sub, ci.fields[i].name, descOf(ft))
                    val fSlot = nextSlot
                    nextSlot += slotsOf(ft)
                    storeSlot(mv, ft, fSlot)
                    genPatternTest(fp, fSlot, ft, failTo)
                }
            }
        }
    }
}
