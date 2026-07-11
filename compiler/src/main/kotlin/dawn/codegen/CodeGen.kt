package dawn.codegen

import dawn.ast.*
import dawn.check.AdtInfo
import dawn.check.BUILTINS
import dawn.check.CtorInfo
import dawn.check.FnSig
import dawn.check.PRELUDE_ADTS
import dawn.check.Symbol
import dawn.check.Type
import dawn.check.Type.*
import org.objectweb.asm.ClassWriter
import org.objectweb.asm.Handle
import org.objectweb.asm.Label
import org.objectweb.asm.MethodVisitor
import org.objectweb.asm.Opcodes.*
import org.objectweb.asm.Type as AsmType

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
class CodeGen(
    private val module: Module,
    private val className: String,
    /** compile test blocks too (`dawn test`); builds strip them (spec §3.4) */
    private val includeTests: Boolean = false,
) {

    companion object {
        const val PANIC_CLASS = "dawn/rt/PanicError"
        const val LISTS_CLASS = "dawn/rt/Lists"
        private const val SB = "java/lang/StringBuilder"
        private const val OBJ = "java/lang/Object"
        private const val JLIST = "java/util/List"
        private const val ARRAYLIST = "java/util/ArrayList"

        private fun fnIface(arity: Int) = "dawn/rt/Fn$arity"
        private fun erasedApplyDesc(arity: Int) = "(" + "L$OBJ;".repeat(arity) + ")L$OBJ;"

        /** LambdaMetafactory bootstrap (on native-image's supported list, spec §12.3) */
        private val LMF_BSM = Handle(
            H_INVOKESTATIC, "java/lang/invoke/LambdaMetafactory", "metafactory",
            "(Ljava/lang/invoke/MethodHandles\$Lookup;Ljava/lang/String;Ljava/lang/invoke/MethodType;" +
                "Ljava/lang/invoke/MethodType;Ljava/lang/invoke/MethodHandle;Ljava/lang/invoke/MethodType;)" +
                "Ljava/lang/invoke/CallSite;",
            false,
        )
    }

    /** every ADT we emit classes for: prelude (Option/Result) + this module's */
    private val allAdts: List<AdtInfo> =
        PRELUDE_ADTS + module.types.mapNotNull { it.ctors.firstOrNull()?.info?.adt }

    /** super of every class we generate, so frames can be computed without loading them */
    private val adtSupers: Map<String, String> = buildMap {
        for (a in allAdts) {
            put(a.jvmName, OBJ)
            if (!a.isRecord) for (c in a.ctors) put(c.jvmName, a.jvmName)
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

    /** lambdas found while generating a method; their impl methods are emitted after it */
    private class PendingLambda(val lambda: Lambda, val name: String)
    private val pendingLambdas = ArrayList<PendingLambda>()
    private var lambdaCounter = 0
    /** Unit-returning fns used as values; each needs one bridge method */
    private val pendingBridges = LinkedHashSet<FnSig>()

    fun generate(): Map<String, ByteArray> {
        val out = HashMap<String, ByteArray>()
        for (a in allAdts) genAdt(a, out)

        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, className, null, OBJ, null)
        for (d in module.fns) {
            genFn(cw, d)
            drainLambdas(cw)
        }
        if (includeTests) {
            for ((i, t) in module.tests.withIndex()) {
                genTest(cw, t, i)
                drainLambdas(cw)
            }
        }
        if (module.fns.any { it.name == "main" }) genJvmMain(cw)
        cw.visitEnd()

        out[className] = cw.toByteArray()
        out[PANIC_CLASS] = genPanicClass()
        out[LISTS_CLASS] = genListsClass()
        for (n in 0..8) out[fnIface(n)] = genFnInterface(n)
        return out
    }

    private fun genFnInterface(arity: Int): ByteArray {
        val cw = ClassWriter(0)
        cw.visit(V17, ACC_PUBLIC or ACC_ABSTRACT or ACC_INTERFACE, fnIface(arity), null, OBJ, null)
        cw.visitMethod(ACC_PUBLIC or ACC_ABSTRACT, "apply", erasedApplyDesc(arity), null, null).visitEnd()
        cw.visitEnd()
        return cw.toByteArray()
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
        is TVar -> "L$OBJ;" // erasure: type parameters are Object (spec §12.2)
        is TAdt -> "L${t.info.jvmName};"
        is TList -> "L$JLIST;"
        is TFn -> "L${fnIface(t.params.size)};"
    }

    private fun methodDesc(params: List<Type>, ret: Type): String =
        params.joinToString("", "(", ")") { descOf(it) } + descOf(ret)

    private fun slotsOf(t: Type): Int = when (t) {
        TInt, TFloat -> 2
        TBool -> 1
        TUnit, TNever, TError -> 0
        else -> 1 // all references
    }

    private fun isRef(t: Type) = t == TString || t is TAdt || t is TList || t is TVar || t is TFn

    // ---- erasure coercions ----

    /** box a primitive on the stack (it is about to sit in an erased Object position) */
    private fun box(t: Type) {
        when (t) {
            TInt -> mv.visitMethodInsn(INVOKESTATIC, "java/lang/Long", "valueOf", "(J)Ljava/lang/Long;", false)
            TFloat -> mv.visitMethodInsn(INVOKESTATIC, "java/lang/Double", "valueOf", "(D)Ljava/lang/Double;", false)
            TBool -> mv.visitMethodInsn(INVOKESTATIC, "java/lang/Boolean", "valueOf", "(Z)Ljava/lang/Boolean;", false)
            else -> {}
        }
    }

    /** the stack holds an erased Object; recover the concrete type [t] */
    private fun unerase(t: Type) {
        when (t) {
            TInt -> {
                mv.visitTypeInsn(CHECKCAST, "java/lang/Long")
                mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Long", "longValue", "()J", false)
            }
            TFloat -> {
                mv.visitTypeInsn(CHECKCAST, "java/lang/Double")
                mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Double", "doubleValue", "()D", false)
            }
            TBool -> {
                mv.visitTypeInsn(CHECKCAST, "java/lang/Boolean")
                mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Boolean", "booleanValue", "()Z", false)
            }
            TString -> mv.visitTypeInsn(CHECKCAST, "java/lang/String")
            is TAdt -> mv.visitTypeInsn(CHECKCAST, t.info.jvmName)
            is TList -> mv.visitTypeInsn(CHECKCAST, JLIST)
            is TFn -> mv.visitTypeInsn(CHECKCAST, fnIface(t.params.size))
            else -> {} // TVar stays erased; Unit/Never carry no value
        }
    }

    /** stack holds a value of static type [actual]; the target position is declared as [declared] */
    private fun adaptTo(actual: Type, declared: Type) {
        if (declared is TVar) box(actual)
    }

    /** stack holds a value produced from a position declared as [declared]; it is used as [actual] */
    private fun adaptFrom(declared: Type, actual: Type) {
        if (declared is TVar) unerase(actual)
    }

    /**
     * The boxed JVM type of a concrete Dawn type — what LambdaMetafactory's
     * instantiatedMethodType needs (Object→long is not an LMF adaptation, but
     * Object→Long→long is; Unit-returning impls return a null Object).
     */
    private fun boxedDescOf(t: Type): String = when (t) {
        TInt -> "Ljava/lang/Long;"
        TFloat -> "Ljava/lang/Double;"
        TBool -> "Ljava/lang/Boolean;"
        TUnit, TNever, TError -> "L$OBJ;"
        else -> descOf(t)
    }

    private fun instantiatedType(params: List<Type>, ret: Type): AsmType =
        AsmType.getMethodType(params.joinToString("", "(", ")") { boxedDescOf(it) } + boxedDescOf(ret))

    // ---- ADT classes (spec §12.2) ----

    private fun genAdt(a: AdtInfo, out: MutableMap<String, ByteArray>) {
        val base = a.jvmName
        if (a.isRecord) {
            // a record is one final class, no abstract base (spec §12.2)
            out[base] = genCtorClass(OBJ, a.ctors.single())
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

        for (ci in a.ctors) out[ci.jvmName] = genCtorClass(base, ci)
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
            when {
                sig.ret == TInt -> mv.visitInsn(LRETURN)
                sig.ret == TFloat -> mv.visitInsn(DRETURN)
                sig.ret == TBool -> mv.visitInsn(IRETURN)
                isRef(sig.ret) -> mv.visitInsn(ARETURN)
                else -> mv.visitInsn(RETURN)
            }
        }
        mv.visitMaxs(0, 0)
        mv.visitEnd()
    }

    /** one test block → one public static method dawn$test$i()V */
    private fun genTest(cw: ClassWriter, t: TestDecl, idx: Int) {
        mv = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "dawn\$test\$$idx", "()V", null, null)
        mv.visitCode()
        currentFn = null
        fnStart = null
        nextSlot = 0
        if (genExpr(t.body, tail = false)) mv.visitInsn(RETURN)
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

    /**
     * dawn/rt/Lists: runtime helpers for the builtin list type.
     *   get(List, long) -> Option   (bounds-checked; the Dawn `get` builtin)
     *   range(long, long) -> List   (right-open integer range)
     *   concat(List, List) -> List  (the `++` operator)
     */
    private fun genListsClass(): ByteArray {
        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, LISTS_CLASS, null, OBJ, null)

        val get = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "get", "(L$JLIST;J)LOption;", null, null)
        get.visitCode()
        val none = Label()
        get.visitVarInsn(LLOAD, 1)
        get.visitInsn(LCONST_0)
        get.visitInsn(LCMP)
        get.visitJumpInsn(IFLT, none)
        get.visitVarInsn(LLOAD, 1)
        get.visitVarInsn(ALOAD, 0)
        get.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
        get.visitInsn(I2L)
        get.visitInsn(LCMP)
        get.visitJumpInsn(IFGE, none)
        get.visitTypeInsn(NEW, "Option\$Some")
        get.visitInsn(DUP)
        get.visitVarInsn(ALOAD, 0)
        get.visitVarInsn(LLOAD, 1)
        get.visitInsn(L2I)
        get.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
        get.visitMethodInsn(INVOKESPECIAL, "Option\$Some", "<init>", "(L$OBJ;)V", false)
        get.visitInsn(ARETURN)
        get.visitLabel(none)
        get.visitFieldInsn(GETSTATIC, "Option\$None", "INSTANCE", "LOption\$None;")
        get.visitInsn(ARETURN)
        get.visitMaxs(0, 0)
        get.visitEnd()

        val rng = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "range", "(JJ)L$JLIST;", null, null)
        rng.visitCode()
        rng.visitTypeInsn(NEW, ARRAYLIST)
        rng.visitInsn(DUP)
        rng.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "()V", false)
        rng.visitVarInsn(ASTORE, 4)
        rng.visitVarInsn(LLOAD, 0)
        rng.visitVarInsn(LSTORE, 5)
        val loop = Label()
        val done = Label()
        rng.visitLabel(loop)
        rng.visitVarInsn(LLOAD, 5)
        rng.visitVarInsn(LLOAD, 2)
        rng.visitInsn(LCMP)
        rng.visitJumpInsn(IFGE, done)
        rng.visitVarInsn(ALOAD, 4)
        rng.visitVarInsn(LLOAD, 5)
        rng.visitMethodInsn(INVOKESTATIC, "java/lang/Long", "valueOf", "(J)Ljava/lang/Long;", false)
        rng.visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "add", "(L$OBJ;)Z", false)
        rng.visitInsn(POP)
        rng.visitVarInsn(LLOAD, 5)
        rng.visitInsn(LCONST_1)
        rng.visitInsn(LADD)
        rng.visitVarInsn(LSTORE, 5)
        rng.visitJumpInsn(GOTO, loop)
        rng.visitLabel(done)
        rng.visitVarInsn(ALOAD, 4)
        rng.visitInsn(ARETURN)
        rng.visitMaxs(0, 0)
        rng.visitEnd()

        genListHof(cw)

        val cat = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "concat", "(L$JLIST;L$JLIST;)L$JLIST;", null, null)
        cat.visitCode()
        cat.visitTypeInsn(NEW, ARRAYLIST)
        cat.visitInsn(DUP)
        cat.visitVarInsn(ALOAD, 0)
        cat.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "(Ljava/util/Collection;)V", false)
        cat.visitVarInsn(ASTORE, 2)
        cat.visitVarInsn(ALOAD, 2)
        cat.visitVarInsn(ALOAD, 1)
        cat.visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "addAll", "(Ljava/util/Collection;)Z", false)
        cat.visitInsn(POP)
        cat.visitVarInsn(ALOAD, 2)
        cat.visitInsn(ARETURN)
        cat.visitMaxs(0, 0)
        cat.visitEnd()

        cw.visitEnd()
        return cw.toByteArray()
    }

    /** map / filter / fold loops for dawn/rt/Lists */
    private fun genListHof(cw: ClassWriter) {
        // map(List xs, Fn1 f) -> List
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "map", "(L$JLIST;L${fnIface(1)};)L$JLIST;", null, null)
            m.visitCode()
            m.visitTypeInsn(NEW, ARRAYLIST)
            m.visitInsn(DUP)
            m.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "()V", false)
            m.visitVarInsn(ASTORE, 2)
            m.visitInsn(ICONST_0)
            m.visitVarInsn(ISTORE, 3)
            val loop = Label()
            val done = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ILOAD, 3)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
            m.visitJumpInsn(IF_ICMPGE, done)
            m.visitVarInsn(ALOAD, 2)
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ILOAD, 3)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
            m.visitMethodInsn(INVOKEINTERFACE, fnIface(1), "apply", erasedApplyDesc(1), true)
            m.visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "add", "(L$OBJ;)Z", false)
            m.visitInsn(POP)
            m.visitIincInsn(3, 1)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(done)
            m.visitVarInsn(ALOAD, 2)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }
        // filter(List xs, Fn1 f) -> List
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "filter", "(L$JLIST;L${fnIface(1)};)L$JLIST;", null, null)
            m.visitCode()
            m.visitTypeInsn(NEW, ARRAYLIST)
            m.visitInsn(DUP)
            m.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "()V", false)
            m.visitVarInsn(ASTORE, 2)
            m.visitInsn(ICONST_0)
            m.visitVarInsn(ISTORE, 3)
            val loop = Label()
            val done = Label()
            val skip = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ILOAD, 3)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
            m.visitJumpInsn(IF_ICMPGE, done)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ILOAD, 3)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
            m.visitVarInsn(ASTORE, 4)
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ALOAD, 4)
            m.visitMethodInsn(INVOKEINTERFACE, fnIface(1), "apply", erasedApplyDesc(1), true)
            m.visitTypeInsn(CHECKCAST, "java/lang/Boolean")
            m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Boolean", "booleanValue", "()Z", false)
            m.visitJumpInsn(IFEQ, skip)
            m.visitVarInsn(ALOAD, 2)
            m.visitVarInsn(ALOAD, 4)
            m.visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "add", "(L$OBJ;)Z", false)
            m.visitInsn(POP)
            m.visitLabel(skip)
            m.visitIincInsn(3, 1)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(done)
            m.visitVarInsn(ALOAD, 2)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }
        // fold(List xs, Object init, Fn2 f) -> Object
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "fold", "(L$JLIST;L$OBJ;L${fnIface(2)};)L$OBJ;", null, null)
            m.visitCode()
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ASTORE, 3)
            m.visitInsn(ICONST_0)
            m.visitVarInsn(ISTORE, 4)
            val loop = Label()
            val done = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ILOAD, 4)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
            m.visitJumpInsn(IF_ICMPGE, done)
            m.visitVarInsn(ALOAD, 2)
            m.visitVarInsn(ALOAD, 3)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ILOAD, 4)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
            m.visitMethodInsn(INVOKEINTERFACE, fnIface(2), "apply", erasedApplyDesc(2), true)
            m.visitVarInsn(ASTORE, 3)
            m.visitIincInsn(4, 1)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(done)
            m.visitVarInsn(ALOAD, 3)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }
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

    /**
     * assert expr: on failure, panic with the source text. For == over printable
     * types, both sides are kept in temps so the message can show their values.
     */
    private fun genAssert(s: AssertStmt): Boolean {
        val cond = s.cond
        val src = s.sourceText ?: "<assert>"
        val printable = listOf(TInt, TFloat, TBool, TString)
        val deconstruct = cond is Binary && cond.op == BinOp.EQ && cond.left.type in printable
        var leftSlot = -1
        var rightSlot = -1
        var sideType: Type = TUnit
        if (deconstruct) {
            cond as Binary
            sideType = cond.left.type!!
            if (!genExpr(cond.left, tail = false)) return false
            leftSlot = nextSlot
            nextSlot += slotsOf(sideType)
            storeSlot(mv, sideType, leftSlot)
            if (!genExpr(cond.right, tail = false)) return false
            rightSlot = nextSlot
            nextSlot += slotsOf(sideType)
            storeSlot(mv, sideType, rightSlot)
            loadSlot(mv, sideType, leftSlot)
            loadSlot(mv, sideType, rightSlot)
            genEquality(sideType, BinOp.EQ)
        } else {
            if (!genExpr(cond, tail = false)) return false
        }
        val ok = Label()
        mv.visitJumpInsn(IFNE, ok)
        mv.visitTypeInsn(NEW, PANIC_CLASS)
        mv.visitInsn(DUP)
        if (deconstruct) {
            val appendDesc = when (sideType) {
                TInt -> "(J)L$SB;"
                TFloat -> "(D)L$SB;"
                TBool -> "(Z)L$SB;"
                else -> "(Ljava/lang/String;)L$SB;"
            }
            mv.visitTypeInsn(NEW, SB)
            mv.visitInsn(DUP)
            mv.visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
            mv.visitLdcInsn("assertion failed: $src\n  left  = ")
            mv.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
            loadSlot(mv, sideType, leftSlot)
            mv.visitMethodInsn(INVOKEVIRTUAL, SB, "append", appendDesc, false)
            mv.visitLdcInsn("\n  right = ")
            mv.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
            loadSlot(mv, sideType, rightSlot)
            mv.visitMethodInsn(INVOKEVIRTUAL, SB, "append", appendDesc, false)
            mv.visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()Ljava/lang/String;", false)
        } else {
            mv.visitLdcInsn("assertion failed: $src")
        }
        mv.visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
        mv.visitInsn(ATHROW)
        mv.visitLabel(ok)
        return true
    }

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
        is AssertStmt -> genAssert(s)
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
        is ForStmt -> if (s.to == null) genForList(s) else genForRange(s)
    }

    private fun genForRange(s: ForStmt): Boolean {
        genExpr(s.from, tail = false)
        val sym = s.symbol!!
        sym.slot = nextSlot
        nextSlot += 2
        mv.visitVarInsn(LSTORE, sym.slot)
        genExpr(s.to!!, tail = false)
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
        return true
    }

    /** for x in list: an int-indexed loop over the (erased) elements */
    private fun genForList(s: ForStmt): Boolean {
        if (!genExpr(s.from, tail = false)) return false
        val listSlot = nextSlot
        nextSlot += 1
        mv.visitVarInsn(ASTORE, listSlot)
        val idxSlot = nextSlot
        nextSlot += 1
        mv.visitInsn(ICONST_0)
        mv.visitVarInsn(ISTORE, idxSlot)
        val sym = s.symbol!!
        sym.slot = nextSlot
        nextSlot += slotsOf(sym.type)
        val loop = Label()
        val end = Label()
        mv.visitLabel(loop)
        mv.visitVarInsn(ILOAD, idxSlot)
        mv.visitVarInsn(ALOAD, listSlot)
        mv.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
        mv.visitJumpInsn(IF_ICMPGE, end)
        mv.visitVarInsn(ALOAD, listSlot)
        mv.visitVarInsn(ILOAD, idxSlot)
        mv.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
        unerase(sym.type)
        storeVar(sym)
        val bodyFalls = genExpr(s.body, tail = false)
        if (bodyFalls) {
            mv.visitIincInsn(idxSlot, 1)
            mv.visitJumpInsn(GOTO, loop)
        }
        mv.visitLabel(end)
        return true
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
        is VarRef -> {
            val fv = e.fnValue
            if (fv != null) {
                // a top-level function as a value: a zero-capture lambda over it.
                // Unit-returning functions need a bridge (LMF cannot adapt void).
                val n = fv.paramTypes.size
                val needBridge = slotsOf(fv.ret) == 0
                val implName: String
                val implDesc: String
                if (needBridge) {
                    pendingBridges.add(fv)
                    implName = "dawn\$fnval\$${fv.name}"
                    implDesc = fv.paramTypes.joinToString("", "(", ")") { descOf(it) } + "L$OBJ;"
                } else {
                    implName = fv.name
                    implDesc = methodDesc(fv.paramTypes, fv.ret)
                }
                mv.visitInvokeDynamicInsn(
                    "apply", "()L${fnIface(n)};", LMF_BSM,
                    AsmType.getMethodType(erasedApplyDesc(n)),
                    Handle(H_INVOKESTATIC, className, implName, implDesc, false),
                    instantiatedType(fv.paramTypes, fv.ret),
                )
            } else {
                loadVar(e.symbol!!)
            }
            true
        }
        is Lambda -> genLambdaValue(e)
        is Propagate -> genPropagate(e)
        is Apply -> {
            if (!genExpr(e.target, tail = false)) false
            else genDynamicInvoke(e.args, e.target.type as TFn, e.type!!)
        }
        is Call -> genCall(e, tail)
        is CtorCall -> genCtorCall(e)
        is FieldAccess -> {
            if (!genExpr(e.target, tail = false)) false
            else {
                val f = e.field!!
                mv.visitFieldInsn(GETFIELD, e.owner!!.jvmName, f.name, descOf(f.type))
                adaptFrom(f.type, e.type!!)
                true
            }
        }
        is ListLit -> genListLit(e)
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

    /** desc of a lambda/bridge impl method: concrete types, but Unit/Never return Object (for LMF) */
    private fun implDescOf(params: List<Type>, ret: Type): String =
        params.joinToString("", "(", ")") { descOf(it) } +
            (if (slotsOf(ret) == 0) "L$OBJ;" else descOf(ret))

    /** the lambda expression site: load captures + invokedynamic; the impl method is emitted later */
    private fun genLambdaValue(e: Lambda): Boolean {
        val name = "dawn\$lambda\$${lambdaCounter++}"
        pendingLambdas.add(PendingLambda(e, name))
        val caps = e.captures!!
        for (c in caps) loadVar(c)
        val ft = e.fnType!!
        val implDesc = implDescOf(caps.map { it.type } + ft.params, ft.ret)
        val indyDesc = "(" + caps.joinToString("") { descOf(it.type) } + ")L${fnIface(ft.params.size)};"
        mv.visitInvokeDynamicInsn(
            "apply", indyDesc, LMF_BSM,
            AsmType.getMethodType(erasedApplyDesc(ft.params.size)),
            Handle(H_INVOKESTATIC, className, name, implDesc, false),
            instantiatedType(ft.params, ft.ret),
        )
        return true
    }

    private fun drainLambdas(cw: ClassWriter) {
        while (pendingLambdas.isNotEmpty() || pendingBridges.isNotEmpty()) {
            if (pendingLambdas.isNotEmpty()) {
                genLambdaImpl(cw, pendingLambdas.removeFirst())
            } else {
                genFnValueBridge(cw, pendingBridges.first().also { pendingBridges.remove(it) })
            }
        }
    }

    private fun genLambdaImpl(cw: ClassWriter, p: PendingLambda) {
        val l = p.lambda
        val ft = l.fnType!!
        val caps = l.captures!!
        mv = cw.visitMethod(
            ACC_PRIVATE or ACC_STATIC or ACC_SYNTHETIC, p.name,
            implDescOf(caps.map { it.type } + ft.params, ft.ret), null, null,
        )
        mv.visitCode()
        currentFn = null // no self-name inside a lambda, so no tail-call rewrite
        fnStart = null
        nextSlot = 0
        for (sym in caps) {
            sym.slot = nextSlot
            nextSlot += slotsOf(sym.type)
        }
        for (lp in l.params) {
            val sym = lp.symbol!!
            sym.slot = nextSlot
            nextSlot += slotsOf(sym.type)
        }
        val falls = genExpr(l.body, tail = false)
        if (falls) {
            when {
                ft.ret == TInt -> mv.visitInsn(LRETURN)
                ft.ret == TFloat -> mv.visitInsn(DRETURN)
                ft.ret == TBool -> mv.visitInsn(IRETURN)
                isRef(ft.ret) -> mv.visitInsn(ARETURN)
                else -> {
                    // Unit body, Object-returning impl: return null
                    mv.visitInsn(ACONST_NULL)
                    mv.visitInsn(ARETURN)
                }
            }
        }
        mv.visitMaxs(0, 0)
        mv.visitEnd()
    }

    private val emittedBridges = HashSet<String>()

    /** bridge for a Unit-returning top-level function used as a value: call it, return null */
    private fun genFnValueBridge(cw: ClassWriter, sig: FnSig) {
        if (!emittedBridges.add(sig.name)) return
        val m = cw.visitMethod(
            ACC_PRIVATE or ACC_STATIC or ACC_SYNTHETIC, "dawn\$fnval\$${sig.name}",
            implDescOf(sig.paramTypes, sig.ret), null, null,
        )
        m.visitCode()
        var slot = 0
        for (pt in sig.paramTypes) {
            loadSlot(m, pt, slot)
            slot += slotsOf(pt)
        }
        m.visitMethodInsn(INVOKESTATIC, className, sig.name, methodDesc(sig.paramTypes, sig.ret), false)
        m.visitInsn(ACONST_NULL)
        m.visitInsn(ARETURN)
        m.visitMaxs(0, 0)
        m.visitEnd()
    }

    /**
     * expr? (spec §8.1): if the value is Ok/Some, unwrap it; otherwise return it
     * directly from the enclosing function — the Err/None instance is already of
     * the (erased) declared return type.
     */
    private fun genPropagate(e: Propagate): Boolean {
        if (!genExpr(e.operand, tail = false)) return false
        val ot = e.operand.type as TAdt
        val okCtor = ot.info.ctors.first { it.name == "Some" || it.name == "Ok" }
        val okL = Label()
        mv.visitInsn(DUP)
        mv.visitTypeInsn(INSTANCEOF, okCtor.jvmName)
        mv.visitJumpInsn(IFNE, okL)
        mv.visitInsn(ARETURN) // early return of the None/Err value itself
        mv.visitLabel(okL)
        mv.visitTypeInsn(CHECKCAST, okCtor.jvmName)
        val field = okCtor.fields.first()
        mv.visitFieldInsn(GETFIELD, okCtor.jvmName, field.name, descOf(field.type))
        adaptFrom(field.type, e.type!!)
        return true
    }

    /** call a function value already on the stack: box args, apply, recover the result type */
    private fun genDynamicInvoke(args: List<Expr>, ft: TFn, retStatic: Type): Boolean {
        for (a in args) {
            if (!genExpr(a, tail = false)) return false
            box(a.type!!)
        }
        val n = ft.params.size
        mv.visitMethodInsn(INVOKEINTERFACE, fnIface(n), "apply", erasedApplyDesc(n), true)
        if (slotsOf(retStatic) == 0) mv.visitInsn(POP) else unerase(retStatic)
        return true
    }

    private fun genCall(e: Call, tail: Boolean): Boolean {
        val dyn = e.dynamicTarget
        if (dyn != null) {
            loadVar(dyn)
            return genDynamicInvoke(e.args, dyn.type as TFn, e.type!!)
        }
        val builtin = BUILTINS[e.callee]
        if (builtin != null) return genBuiltinCall(e)

        val self = currentFn
        val sig = e.sig!!
        // self-recursive tail call → write args back to param slots + goto entry (spec §12.4)
        if (tail && self != null && e.callee == self.name) {
            for ((a, pt) in e.args.zip(sig.paramTypes)) {
                genExpr(a, tail = false)
                adaptTo(a.type!!, pt)
            }
            for (p in self.params.reversed()) {
                val sym = p.symbol!!
                if (slotsOf(sym.type) > 0) storeVar(sym)
            }
            mv.visitJumpInsn(GOTO, fnStart!!)
            return false
        }
        for ((a, pt) in e.args.zip(sig.paramTypes)) {
            genExpr(a, tail = false)
            adaptTo(a.type!!, pt)
        }
        mv.visitMethodInsn(INVOKESTATIC, className, e.callee, methodDesc(sig.paramTypes, sig.ret), false)
        adaptFrom(sig.ret, e.type!!)
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
                adaptTo(arg.type!!, ci.fields[i].type)
            } else {
                // field not given: take it from the spread base (already erased)
                val f = ci.fields[i]
                mv.visitVarInsn(ALOAD, spreadSlot)
                mv.visitFieldInsn(GETFIELD, sub, f.name, descOf(f.type))
            }
        }
        val desc = "(" + ci.fields.joinToString("") { descOf(it.type) } + ")V"
        mv.visitMethodInsn(INVOKESPECIAL, sub, "<init>", desc, false)
        return true
    }

    private fun genListLit(e: ListLit): Boolean {
        mv.visitTypeInsn(NEW, ARRAYLIST)
        mv.visitInsn(DUP)
        mv.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "()V", false)
        for (el in e.elems) {
            mv.visitInsn(DUP)
            if (!genExpr(el, tail = false)) return false
            box(el.type!!) // list elements are stored erased
            mv.visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "add", "(L$OBJ;)Z", false)
            mv.visitInsn(POP)
        }
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
        "to_float" -> {
            genExpr(e.args[0], tail = false)
            mv.visitInsn(L2D)
            true
        }
        "to_int" -> {
            genExpr(e.args[0], tail = false)
            mv.visitInsn(D2L)
            true
        }
        "len" -> {
            genExpr(e.args[0], tail = false)
            mv.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
            mv.visitInsn(I2L)
            true
        }
        "get" -> {
            genExpr(e.args[0], tail = false)
            genExpr(e.args[1], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "get", "(L$JLIST;J)LOption;", false)
            true
        }
        "range" -> {
            genExpr(e.args[0], tail = false)
            genExpr(e.args[1], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "range", "(JJ)L$JLIST;", false)
            true
        }
        "map", "filter" -> {
            genExpr(e.args[0], tail = false)
            genExpr(e.args[1], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, e.callee,
                "(L$JLIST;L${fnIface(1)};)L$JLIST;", false)
            true
        }
        "fold" -> {
            genExpr(e.args[0], tail = false)
            genExpr(e.args[1], tail = false)
            box(e.args[1].type!!) // the accumulator travels erased
            genExpr(e.args[2], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "fold",
                "(L$JLIST;L$OBJ;L${fnIface(2)};)L$OBJ;", false)
            if (slotsOf(e.type!!) == 0) mv.visitInsn(POP) else unerase(e.type!!)
            true
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
                if (t is TList) {
                    mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "concat", "(L$JLIST;L$JLIST;)L$JLIST;", false)
                } else {
                    mv.visitMethodInsn(
                        INVOKEVIRTUAL, "java/lang/String", "concat",
                        "(Ljava/lang/String;)Ljava/lang/String;", false,
                    )
                }
            BinOp.EQ, BinOp.NEQ -> genEquality(t, e.op)
            BinOp.LT, BinOp.LE, BinOp.GT, BinOp.GE -> genOrdering(t, e.op)
            else -> {}
        }
        return true
    }

    private fun genEquality(t: Type, op: BinOp) {
        when {
            isRef(t) -> {
                // structural equals: String, List, ADT subclasses (generics compare boxed)
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
                    val declared = ci.fields[i].type
                    val concrete = p.fieldTypes!![i]
                    mv.visitVarInsn(ALOAD, slot)
                    mv.visitTypeInsn(CHECKCAST, sub)
                    mv.visitFieldInsn(GETFIELD, sub, ci.fields[i].name, descOf(declared))
                    adaptFrom(declared, concrete)
                    val fSlot = nextSlot
                    nextSlot += slotsOf(concrete)
                    storeSlot(mv, concrete, fSlot)
                    genPatternTest(fp, fSlot, concrete, failTo)
                }
            }
        }
    }
}
