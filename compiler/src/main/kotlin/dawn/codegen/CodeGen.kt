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
        const val STRINGS_CLASS = "dawn/rt/Strings"
        const val IO_CLASS = "dawn/rt/Io"
        const val SHOW_CLASS = "dawn/rt/Show"
        private const val ARGS_FIELD = "dawn\$args"
        private const val SB = "java/lang/StringBuilder"
        private const val OBJ = "java/lang/Object"
        private const val JLIST = "java/util/List"
        private const val ARRAYLIST = "java/util/ArrayList"

        private fun fnIface(arity: Int) = "dawn/rt/Fn$arity"
        private fun erasedApplyDesc(arity: Int) = "(" + "L$OBJ;".repeat(arity) + ")L$OBJ;"
        private fun tupleClass(arity: Int) = "dawn/rt/Tuple$arity"

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
        for (n in 2..8) put(tupleClass(n), OBJ)
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
    /** builtins used as values without a real static method behind them */
    private val pendingBuiltinBridges = LinkedHashSet<FnSig>()
    private val pendingCtorBridges = LinkedHashSet<CtorInfo>()
    private val emittedCtorBridges = HashSet<String>()

    /** non-scalar comptime results become static fields built in <clinit> */
    private class ConstField(val name: String, val value: dawn.check.CValue, val type: Type)
    private val constFields = ArrayList<ConstField>()
    private val constFieldByKey = HashMap<Any, String>()

    fun generate(): Map<String, ByteArray> {
        val out = HashMap<String, ByteArray>()
        for (a in allAdts) genAdt(a, out)

        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, className, null, OBJ, null)
        // CLI arguments, set by the JVM entry wrapper; null when absent (tests) → args() gives []
        cw.visitField(ACC_PUBLIC or ACC_STATIC, ARGS_FIELD, "[Ljava/lang/String;", null, null).visitEnd()
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
        genConstFields(cw)
        cw.visitEnd()

        out[className] = cw.toByteArray()
        out[PANIC_CLASS] = genPanicClass()
        out[LISTS_CLASS] = genListsClass()
        out[STRINGS_CLASS] = genStringsClass()
        out[IO_CLASS] = genIoClass()
        out[SHOW_CLASS] = genShowClass()
        for (n in 0..8) out[fnIface(n)] = genFnInterface(n)
        for (n in 2..8) out[tupleClass(n)] = genTupleClass(n)
        return out
    }

    /** dawn/rt/TupleN: N public final Object fields _0.._N-1 + structural equals (spec §1.5) */
    private fun genTupleClass(n: Int): ByteArray {
        val cls = tupleClass(n)
        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, cls, null, OBJ, null)
        for (i in 0 until n) {
            cw.visitField(ACC_PUBLIC or ACC_FINAL, "_$i", "L$OBJ;", null, null).visitEnd()
        }
        val ctorDesc = "(" + "L$OBJ;".repeat(n) + ")V"
        val init = cw.visitMethod(ACC_PUBLIC, "<init>", ctorDesc, null, null)
        init.visitCode()
        init.visitVarInsn(ALOAD, 0)
        init.visitMethodInsn(INVOKESPECIAL, OBJ, "<init>", "()V", false)
        for (i in 0 until n) {
            init.visitVarInsn(ALOAD, 0)
            init.visitVarInsn(ALOAD, i + 1)
            init.visitFieldInsn(PUTFIELD, cls, "_$i", "L$OBJ;")
        }
        init.visitInsn(RETURN)
        init.visitMaxs(0, 0)
        init.visitEnd()

        val eq = cw.visitMethod(ACC_PUBLIC, "equals", "(L$OBJ;)Z", null, null)
        eq.visitCode()
        val yes = Label()
        val no = Label()
        eq.visitVarInsn(ALOAD, 0)
        eq.visitVarInsn(ALOAD, 1)
        eq.visitJumpInsn(IF_ACMPEQ, yes)
        eq.visitVarInsn(ALOAD, 1)
        eq.visitTypeInsn(INSTANCEOF, cls)
        eq.visitJumpInsn(IFEQ, no)
        eq.visitVarInsn(ALOAD, 1)
        eq.visitTypeInsn(CHECKCAST, cls)
        eq.visitVarInsn(ASTORE, 2)
        for (i in 0 until n) {
            eq.visitVarInsn(ALOAD, 0)
            eq.visitFieldInsn(GETFIELD, cls, "_$i", "L$OBJ;")
            eq.visitVarInsn(ALOAD, 2)
            eq.visitFieldInsn(GETFIELD, cls, "_$i", "L$OBJ;")
            eq.visitMethodInsn(INVOKEVIRTUAL, OBJ, "equals", "(L$OBJ;)Z", false)
            eq.visitJumpInsn(IFEQ, no)
        }
        eq.visitLabel(yes)
        eq.visitInsn(ICONST_1)
        eq.visitInsn(IRETURN)
        eq.visitLabel(no)
        eq.visitInsn(ICONST_0)
        eq.visitInsn(IRETURN)
        eq.visitMaxs(0, 0)
        eq.visitEnd()

        // toString for `derive Show`: (v0, v1, ...) with elements rendered via dawn/rt/Show
        val ts = cw.visitMethod(ACC_PUBLIC, "toString", "()Ljava/lang/String;", null, null)
        ts.visitCode()
        ts.visitTypeInsn(NEW, SB)
        ts.visitInsn(DUP)
        ts.visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
        appendConst(ts, "(")
        for (i in 0 until n) {
            if (i > 0) appendConst(ts, ", ")
            ts.visitVarInsn(ALOAD, 0)
            ts.visitFieldInsn(GETFIELD, cls, "_$i", "L$OBJ;")
            ts.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "show", "(L$OBJ;)Ljava/lang/String;", false)
            ts.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
        }
        appendConst(ts, ")")
        ts.visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()Ljava/lang/String;", false)
        ts.visitInsn(ARETURN)
        ts.visitMaxs(0, 0)
        ts.visitEnd()

        cw.visitEnd()
        return cw.toByteArray()
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
        is TTuple -> "L${tupleClass(t.elems.size)};"
        is TJava -> "L${t.internalName};"
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

    private fun isRef(t: Type) =
        t == TString || t is TAdt || t is TList || t is TVar || t is TFn || t is TTuple || t is TJava

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
            is TTuple -> mv.visitTypeInsn(CHECKCAST, tupleClass(t.elems.size))
            is TJava -> mv.visitTypeInsn(CHECKCAST, t.internalName)
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
        // toString for `derive Show`: always generated so nested/generic fields render
        // uniformly via dawn/rt/Show; the type checker gates whether it may be called
        genToStringMethod(cw, sub, ci)

        cw.visitEnd()
        return cw.toByteArray()
    }

    /** `derive Show` rendering: Name, Name(v0, v1), or Name { f0: v0, f1: v1 } for records */
    private fun genToStringMethod(cw: ClassWriter, sub: String, ci: CtorInfo) {
        val STR = "java/lang/String"
        val m = cw.visitMethod(ACC_PUBLIC, "toString", "()L$STR;", null, null)
        m.visitCode()
        m.visitTypeInsn(NEW, SB)
        m.visitInsn(DUP)
        m.visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
        appendConst(m, ci.name)
        if (ci.fields.isNotEmpty()) {
            val isRecord = ci.adt.isRecord
            appendConst(m, if (isRecord) " { " else "(")
            for ((i, f) in ci.fields.withIndex()) {
                if (i > 0) appendConst(m, ", ")
                if (isRecord) appendConst(m, "${f.name}: ")
                m.visitVarInsn(ALOAD, 0)
                m.visitFieldInsn(GETFIELD, sub, f.name, descOf(f.type))
                when (f.type) {
                    TInt -> m.visitMethodInsn(INVOKESTATIC, "java/lang/Long", "valueOf", "(J)Ljava/lang/Long;", false)
                    TFloat -> m.visitMethodInsn(INVOKESTATIC, "java/lang/Double", "valueOf", "(D)Ljava/lang/Double;", false)
                    TBool -> m.visitMethodInsn(INVOKESTATIC, "java/lang/Boolean", "valueOf", "(Z)Ljava/lang/Boolean;", false)
                    else -> {}
                }
                m.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "show", "(L$OBJ;)L$STR;", false)
                m.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(L$STR;)L$SB;", false)
            }
            appendConst(m, if (isRecord) " }" else ")")
        }
        m.visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()L$STR;", false)
        m.visitInsn(ARETURN)
        m.visitMaxs(0, 0)
        m.visitEnd()
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
        m.visitVarInsn(ALOAD, 0)
        m.visitFieldInsn(PUTSTATIC, className, ARGS_FIELD, "[Ljava/lang/String;")
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

        // fromArray(String[]) -> List — CLI args; null (no JVM wrapper ran) → []
        val fa = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "fromArray", "([Ljava/lang/String;)L$JLIST;", null, null)
        fa.visitCode()
        val faNull = Label()
        fa.visitVarInsn(ALOAD, 0)
        fa.visitJumpInsn(IFNULL, faNull)
        fa.visitTypeInsn(NEW, ARRAYLIST)
        fa.visitInsn(DUP)
        fa.visitVarInsn(ALOAD, 0)
        fa.visitMethodInsn(INVOKESTATIC, "java/util/Arrays", "asList", "([L$OBJ;)L$JLIST;", false)
        fa.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "(Ljava/util/Collection;)V", false)
        fa.visitInsn(ARETURN)
        fa.visitLabel(faNull)
        fa.visitTypeInsn(NEW, ARRAYLIST)
        fa.visitInsn(DUP)
        fa.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "()V", false)
        fa.visitInsn(ARETURN)
        fa.visitMaxs(0, 0)
        fa.visitEnd()

        // slice(List, int from, int to) -> List — the `..rest` middle of a list pattern
        val sl = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "slice", "(L$JLIST;II)L$JLIST;", null, null)
        sl.visitCode()
        sl.visitTypeInsn(NEW, ARRAYLIST)
        sl.visitInsn(DUP)
        sl.visitVarInsn(ALOAD, 0)
        sl.visitVarInsn(ILOAD, 1)
        sl.visitVarInsn(ILOAD, 2)
        sl.visitMethodInsn(INVOKEINTERFACE, JLIST, "subList", "(II)L$JLIST;", true)
        sl.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "(Ljava/util/Collection;)V", false)
        sl.visitInsn(ARETURN)
        sl.visitMaxs(0, 0)
        sl.visitEnd()

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

    /**
     * dawn/rt/Strings: string builtins that need loops or Option results.
     *   chars(String) -> List        (code points as length-1..2 strings)
     *   join(List, String) -> String
     *   split(String, String) -> List (literal separator; "" splits to chars)
     *   parseInt(String) -> Option / parseFloat(String) -> Option
     */
    private fun genStringsClass(): ByteArray {
        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, STRINGS_CLASS, null, OBJ, null)
        val STR = "java/lang/String"

        // chars: iterate by code point so surrogate pairs stay whole
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "chars", "(L$STR;)L$JLIST;", null, null)
            m.visitCode()
            m.visitTypeInsn(NEW, ARRAYLIST)
            m.visitInsn(DUP)
            m.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "()V", false)
            m.visitVarInsn(ASTORE, 1)
            m.visitInsn(ICONST_0)
            m.visitVarInsn(ISTORE, 2)
            val loop = Label()
            val done = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ILOAD, 2)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "length", "()I", false)
            m.visitJumpInsn(IF_ICMPGE, done)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ILOAD, 2)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "codePointAt", "(I)I", false)
            m.visitMethodInsn(INVOKESTATIC, "java/lang/Character", "charCount", "(I)I", false)
            m.visitVarInsn(ISTORE, 3)
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ILOAD, 2)
            m.visitVarInsn(ILOAD, 2)
            m.visitVarInsn(ILOAD, 3)
            m.visitInsn(IADD)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "substring", "(II)L$STR;", false)
            m.visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "add", "(L$OBJ;)Z", false)
            m.visitInsn(POP)
            m.visitVarInsn(ILOAD, 2)
            m.visitVarInsn(ILOAD, 3)
            m.visitInsn(IADD)
            m.visitVarInsn(ISTORE, 2)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(done)
            m.visitVarInsn(ALOAD, 1)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }

        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "join", "(L$JLIST;L$STR;)L$STR;", null, null)
            m.visitCode()
            m.visitTypeInsn(NEW, SB)
            m.visitInsn(DUP)
            m.visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
            m.visitVarInsn(ASTORE, 2)
            m.visitInsn(ICONST_0)
            m.visitVarInsn(ISTORE, 3)
            val loop = Label()
            val done = Label()
            val noSep = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ILOAD, 3)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
            m.visitJumpInsn(IF_ICMPGE, done)
            m.visitVarInsn(ILOAD, 3)
            m.visitJumpInsn(IFEQ, noSep)
            m.visitVarInsn(ALOAD, 2)
            m.visitVarInsn(ALOAD, 1)
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(L$STR;)L$SB;", false)
            m.visitInsn(POP)
            m.visitLabel(noSep)
            m.visitVarInsn(ALOAD, 2)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ILOAD, 3)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
            m.visitTypeInsn(CHECKCAST, STR)
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(L$STR;)L$SB;", false)
            m.visitInsn(POP)
            m.visitIincInsn(3, 1)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(done)
            m.visitVarInsn(ALOAD, 2)
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }

        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "split", "(L$STR;L$STR;)L$JLIST;", null, null)
            m.visitCode()
            val nonEmpty = Label()
            m.visitVarInsn(ALOAD, 1)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "isEmpty", "()Z", false)
            m.visitJumpInsn(IFEQ, nonEmpty)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKESTATIC, STRINGS_CLASS, "chars", "(L$STR;)L$JLIST;", false)
            m.visitInsn(ARETURN)
            m.visitLabel(nonEmpty)
            m.visitTypeInsn(NEW, ARRAYLIST)
            m.visitInsn(DUP)
            m.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "()V", false)
            m.visitVarInsn(ASTORE, 2)
            m.visitInsn(ICONST_0)
            m.visitVarInsn(ISTORE, 3)
            val loop = Label()
            val tail = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ILOAD, 3)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "indexOf", "(L$STR;I)I", false)
            m.visitVarInsn(ISTORE, 4)
            m.visitVarInsn(ILOAD, 4)
            m.visitJumpInsn(IFLT, tail)
            m.visitVarInsn(ALOAD, 2)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ILOAD, 3)
            m.visitVarInsn(ILOAD, 4)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "substring", "(II)L$STR;", false)
            m.visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "add", "(L$OBJ;)Z", false)
            m.visitInsn(POP)
            m.visitVarInsn(ILOAD, 4)
            m.visitVarInsn(ALOAD, 1)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "length", "()I", false)
            m.visitInsn(IADD)
            m.visitVarInsn(ISTORE, 3)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(tail)
            m.visitVarInsn(ALOAD, 2)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ILOAD, 3)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "substring", "(I)L$STR;", false)
            m.visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "add", "(L$OBJ;)Z", false)
            m.visitInsn(POP)
            m.visitVarInsn(ALOAD, 2)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }

        // parseInt / parseFloat: NumberFormatException → None
        for ((name, box, parse, parseDesc, valueOfDesc) in listOf(
            listOf("parseInt", "java/lang/Long", "parseLong", "(L$STR;)J", "(J)Ljava/lang/Long;"),
            listOf("parseFloat", "java/lang/Double", "parseDouble", "(L$STR;)D", "(D)Ljava/lang/Double;"),
        )) {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, name, "(L$STR;)LOption;", null, null)
            m.visitCode()
            val tryStart = Label()
            val tryEnd = Label()
            val handler = Label()
            m.visitTryCatchBlock(tryStart, tryEnd, handler, "java/lang/NumberFormatException")
            m.visitLabel(tryStart)
            m.visitTypeInsn(NEW, "Option\$Some")
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "strip", "()L$STR;", false)
            m.visitMethodInsn(INVOKESTATIC, box, parse, parseDesc, false)
            m.visitMethodInsn(INVOKESTATIC, box, "valueOf", valueOfDesc, false)
            m.visitMethodInsn(INVOKESPECIAL, "Option\$Some", "<init>", "(L$OBJ;)V", false)
            m.visitLabel(tryEnd)
            m.visitInsn(ARETURN)
            m.visitLabel(handler)
            m.visitInsn(POP)
            m.visitFieldInsn(GETSTATIC, "Option\$None", "INSTANCE", "LOption\$None;")
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }

        cw.visitEnd()
        return cw.toByteArray()
    }

    /**
     * dawn/rt/Io: file and console builtins.
     *   readFile(String) -> Result   (Ok(text) / Err(message))
     *   writeFile(String, String) -> Result   (Ok(chars written) / Err(message))
     *   readLine() -> Option         (None on EOF or console error)
     */
    private fun genIoClass(): ByteArray {
        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, IO_CLASS, null, OBJ, null)
        val STR = "java/lang/String"
        val PATH = "java/nio/file/Path"
        val FILES = "java/nio/file/Files"

        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "readFile", "(L$STR;)LResult;", null, null)
            m.visitCode()
            val tryStart = Label()
            val tryEnd = Label()
            val handler = Label()
            m.visitTryCatchBlock(tryStart, tryEnd, handler, "java/lang/Exception")
            m.visitLabel(tryStart)
            m.visitTypeInsn(NEW, "Result\$Ok")
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 0)
            m.visitInsn(ICONST_0)
            m.visitTypeInsn(ANEWARRAY, STR)
            m.visitMethodInsn(INVOKESTATIC, PATH, "of", "(L$STR;[L$STR;)L$PATH;", true)
            m.visitMethodInsn(INVOKESTATIC, FILES, "readString", "(L$PATH;)L$STR;", false)
            m.visitMethodInsn(INVOKESPECIAL, "Result\$Ok", "<init>", "(L$OBJ;)V", false)
            m.visitLabel(tryEnd)
            m.visitInsn(ARETURN)
            m.visitLabel(handler)
            m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Throwable", "toString", "()L$STR;", false)
            m.visitVarInsn(ASTORE, 1)
            m.visitTypeInsn(NEW, "Result\$Err")
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 1)
            m.visitMethodInsn(INVOKESPECIAL, "Result\$Err", "<init>", "(L$OBJ;)V", false)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }

        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "writeFile", "(L$STR;L$STR;)LResult;", null, null)
            m.visitCode()
            val tryStart = Label()
            val tryEnd = Label()
            val handler = Label()
            m.visitTryCatchBlock(tryStart, tryEnd, handler, "java/lang/Exception")
            m.visitLabel(tryStart)
            m.visitVarInsn(ALOAD, 0)
            m.visitInsn(ICONST_0)
            m.visitTypeInsn(ANEWARRAY, STR)
            m.visitMethodInsn(INVOKESTATIC, PATH, "of", "(L$STR;[L$STR;)L$PATH;", true)
            m.visitVarInsn(ALOAD, 1)
            m.visitInsn(ICONST_0)
            m.visitTypeInsn(ANEWARRAY, "java/nio/file/OpenOption")
            m.visitMethodInsn(INVOKESTATIC, FILES, "writeString",
                "(L$PATH;Ljava/lang/CharSequence;[Ljava/nio/file/OpenOption;)L$PATH;", false)
            m.visitInsn(POP)
            m.visitTypeInsn(NEW, "Result\$Ok")
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 1)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "length", "()I", false)
            m.visitInsn(I2L)
            m.visitMethodInsn(INVOKESTATIC, "java/lang/Long", "valueOf", "(J)Ljava/lang/Long;", false)
            m.visitMethodInsn(INVOKESPECIAL, "Result\$Ok", "<init>", "(L$OBJ;)V", false)
            m.visitLabel(tryEnd)
            m.visitInsn(ARETURN)
            m.visitLabel(handler)
            m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Throwable", "toString", "()L$STR;", false)
            m.visitVarInsn(ASTORE, 2)
            m.visitTypeInsn(NEW, "Result\$Err")
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 2)
            m.visitMethodInsn(INVOKESPECIAL, "Result\$Err", "<init>", "(L$OBJ;)V", false)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }

        // shared stdin reader (line-oriented; UTF-8)
        cw.visitField(ACC_PRIVATE or ACC_STATIC or ACC_FINAL, "IN", "Ljava/io/BufferedReader;", null, null)
            .visitEnd()
        run {
            val m = cw.visitMethod(ACC_STATIC, "<clinit>", "()V", null, null)
            m.visitCode()
            m.visitTypeInsn(NEW, "java/io/BufferedReader")
            m.visitInsn(DUP)
            m.visitTypeInsn(NEW, "java/io/InputStreamReader")
            m.visitInsn(DUP)
            m.visitFieldInsn(GETSTATIC, "java/lang/System", "in", "Ljava/io/InputStream;")
            m.visitFieldInsn(GETSTATIC, "java/nio/charset/StandardCharsets", "UTF_8",
                "Ljava/nio/charset/Charset;")
            m.visitMethodInsn(INVOKESPECIAL, "java/io/InputStreamReader", "<init>",
                "(Ljava/io/InputStream;Ljava/nio/charset/Charset;)V", false)
            m.visitMethodInsn(INVOKESPECIAL, "java/io/BufferedReader", "<init>", "(Ljava/io/Reader;)V", false)
            m.visitFieldInsn(PUTSTATIC, IO_CLASS, "IN", "Ljava/io/BufferedReader;")
            m.visitInsn(RETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "readLine", "()LOption;", null, null)
            m.visitCode()
            val tryStart = Label()
            val tryEnd = Label()
            val handler = Label()
            val decide = Label()
            val none = Label()
            m.visitTryCatchBlock(tryStart, tryEnd, handler, "java/io/IOException")
            m.visitLabel(tryStart)
            m.visitFieldInsn(GETSTATIC, IO_CLASS, "IN", "Ljava/io/BufferedReader;")
            m.visitMethodInsn(INVOKEVIRTUAL, "java/io/BufferedReader", "readLine", "()L$STR;", false)
            m.visitVarInsn(ASTORE, 0)
            m.visitLabel(tryEnd)
            m.visitJumpInsn(GOTO, decide)
            m.visitLabel(handler)
            m.visitInsn(POP)
            m.visitInsn(ACONST_NULL)
            m.visitVarInsn(ASTORE, 0)
            m.visitLabel(decide)
            m.visitVarInsn(ALOAD, 0)
            m.visitJumpInsn(IFNULL, none)
            m.visitTypeInsn(NEW, "Option\$Some")
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKESPECIAL, "Option\$Some", "<init>", "(L$OBJ;)V", false)
            m.visitInsn(ARETURN)
            m.visitLabel(none)
            m.visitFieldInsn(GETSTATIC, "Option\$None", "INSTANCE", "LOption\$None;")
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }

        cw.visitEnd()
        return cw.toByteArray()
    }

    /**
     * dawn/rt/Show: the runtime side of `derive Show`. show(Object) renders any
     * erased Dawn value — Strings are quoted, Lists are bracketed with their
     * elements shown recursively, and everything else (numbers, booleans, and
     * ADT/tuple instances whose generated toString does the work) is delegated
     * to String.valueOf. This references only java.*, so it needs no generated
     * types and is native-image safe.
     */
    private fun genShowClass(): ByteArray {
        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, SHOW_CLASS, null, OBJ, null)
        val STR = "java/lang/String"

        // static String show(Object o)
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "show", "(L$OBJ;)L$STR;", null, null)
            m.visitCode()
            val notString = Label()
            val notList = Label()
            // if (o instanceof String) return quote((String) o);
            m.visitVarInsn(ALOAD, 0)
            m.visitTypeInsn(INSTANCEOF, STR)
            m.visitJumpInsn(IFEQ, notString)
            m.visitVarInsn(ALOAD, 0)
            m.visitTypeInsn(CHECKCAST, STR)
            m.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "quote", "(L$STR;)L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitLabel(notString)
            // if (o instanceof java.util.List) return showList((List) o);
            m.visitVarInsn(ALOAD, 0)
            m.visitTypeInsn(INSTANCEOF, JLIST)
            m.visitJumpInsn(IFEQ, notList)
            m.visitVarInsn(ALOAD, 0)
            m.visitTypeInsn(CHECKCAST, JLIST)
            m.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "showList", "(L$JLIST;)L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitLabel(notList)
            // return String.valueOf(o);
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKESTATIC, STR, "valueOf", "(L$OBJ;)L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }

        // static String quote(String s): "\"" + escaped + "\"" (source-literal style)
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "quote", "(L$STR;)L$STR;", null, null)
            m.visitCode()
            m.visitTypeInsn(NEW, SB)
            m.visitInsn(DUP)
            m.visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
            appendConst(m, "\"")
            // escape in order: backslash first, then quote, newline, tab, carriage return
            m.visitVarInsn(ALOAD, 0)
            val esc = listOf("\\" to "\\\\", "\"" to "\\\"", "\n" to "\\n", "\t" to "\\t", "\r" to "\\r")
            for ((from, to) in esc) {
                m.visitLdcInsn(from)
                m.visitLdcInsn(to)
                m.visitMethodInsn(INVOKEVIRTUAL, STR, "replace",
                    "(Ljava/lang/CharSequence;Ljava/lang/CharSequence;)L$STR;", false)
            }
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(L$STR;)L$SB;", false)
            appendConst(m, "\"")
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }

        // static String showList(List xs): "[" + show(e0) + ", " + ... + "]"
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "showList", "(L$JLIST;)L$STR;", null, null)
            m.visitCode()
            // slot 1 = StringBuilder, slot 2 = i, slot 3 = size
            m.visitTypeInsn(NEW, SB)
            m.visitInsn(DUP)
            m.visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
            m.visitVarInsn(ASTORE, 1)
            m.visitVarInsn(ALOAD, 1)
            appendConst(m, "[")
            m.visitInsn(POP)
            m.visitInsn(ICONST_0)
            m.visitVarInsn(ISTORE, 2)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
            m.visitVarInsn(ISTORE, 3)
            val loop = Label()
            val done = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ILOAD, 2)
            m.visitVarInsn(ILOAD, 3)
            m.visitJumpInsn(IF_ICMPGE, done)
            // if (i > 0) sb.append(", ")
            val noComma = Label()
            m.visitVarInsn(ILOAD, 2)
            m.visitJumpInsn(IFEQ, noComma)
            m.visitVarInsn(ALOAD, 1)
            appendConst(m, ", ")
            m.visitInsn(POP)
            m.visitLabel(noComma)
            // sb.append(show(xs.get(i)))
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ILOAD, 2)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
            m.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "show", "(L$OBJ;)L$STR;", false)
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(L$STR;)L$SB;", false)
            m.visitInsn(POP)
            m.visitIincInsn(2, 1)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(done)
            m.visitVarInsn(ALOAD, 1)
            appendConst(m, "]")
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }

        cw.visitEnd()
        return cw.toByteArray()
    }

    /** append a constant string to the StringBuilder already on the stack, leaving the SB on the stack */
    private fun appendConst(m: org.objectweb.asm.MethodVisitor, s: String) {
        m.visitLdcInsn(s)
        m.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
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
        is LetPatStmt -> {
            val t = s.init.type!!
            val falls = genExpr(s.init, tail = false)
            if (falls) {
                val slot = nextSlot
                nextSlot += slotsOf(t)
                storeSlot(mv, t, slot)
                genBind(s.pattern, slot)
            }
            falls
        }
        is ExprStmt -> {
            // usually Unit/Never; discarded Java results leave a value to pop (spec §9)
            val falls = genExpr(s.expr, tail = false)
            if (falls) popValue(s.expr.type!!)
            falls
        }
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
            if (fv != null) genFnValue(e, fv) else loadVar(e.symbol!!)
            true
        }
        is MethodCall -> when {
            e.javaCtorRef != null -> genJavaNew(e)
            e.javaMethod != null -> genJavaCall(e)
            else -> genCall(e.desugared!!, tail)
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
        is TupleLit -> genTupleLit(e)
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
        is ComptimeExpr -> {
            genLoadConst(e.value!!, e.type!!, key = e)
            true
        }
    }

    // ---- comptime constants (spec §7): scalars inline, structures via static fields ----

    private fun genLoadConst(v: dawn.check.CValue, t: Type, key: Any) {
        when (v) {
            is dawn.check.CValue.VInt -> mv.visitLdcInsn(v.v)
            is dawn.check.CValue.VFloat -> mv.visitLdcInsn(v.v)
            is dawn.check.CValue.VBool -> mv.visitInsn(if (v.v) ICONST_1 else ICONST_0)
            is dawn.check.CValue.VString -> mv.visitLdcInsn(v.v)
            dawn.check.CValue.VUnit -> {}
            else -> {
                val fname = constFieldByKey.getOrPut(key) {
                    val f = "dawn\$const\$${constFields.size}"
                    constFields.add(ConstField(f, v, t))
                    f
                }
                mv.visitFieldInsn(GETSTATIC, className, fname, descOf(t))
            }
        }
    }

    private fun genConstFields(cw: ClassWriter) {
        if (constFields.isEmpty()) return
        for (f in constFields) {
            cw.visitField(ACC_PUBLIC or ACC_STATIC or ACC_FINAL, f.name, descOf(f.type), null, null)
                .visitEnd()
        }
        val cl = cw.visitMethod(ACC_STATIC, "<clinit>", "()V", null, null)
        cl.visitCode()
        for (f in constFields) {
            constructValue(cl, f.value, boxed = false)
            cl.visitFieldInsn(PUTSTATIC, className, f.name, descOf(f.type))
        }
        cl.visitInsn(RETURN)
        cl.visitMaxs(0, 0)
        cl.visitEnd()
    }

    /** emit bytecode that rebuilds a comptime value ([boxed] = target position is erased) */
    private fun constructValue(m: MethodVisitor, v: dawn.check.CValue, boxed: Boolean) {
        when (v) {
            is dawn.check.CValue.VInt -> {
                m.visitLdcInsn(v.v)
                if (boxed) m.visitMethodInsn(INVOKESTATIC, "java/lang/Long", "valueOf",
                    "(J)Ljava/lang/Long;", false)
            }
            is dawn.check.CValue.VFloat -> {
                m.visitLdcInsn(v.v)
                if (boxed) m.visitMethodInsn(INVOKESTATIC, "java/lang/Double", "valueOf",
                    "(D)Ljava/lang/Double;", false)
            }
            is dawn.check.CValue.VBool -> {
                m.visitInsn(if (v.v) ICONST_1 else ICONST_0)
                if (boxed) m.visitMethodInsn(INVOKESTATIC, "java/lang/Boolean", "valueOf",
                    "(Z)Ljava/lang/Boolean;", false)
            }
            is dawn.check.CValue.VString -> m.visitLdcInsn(v.v)
            dawn.check.CValue.VUnit -> if (boxed) m.visitInsn(ACONST_NULL)
            is dawn.check.CValue.VList -> {
                m.visitTypeInsn(NEW, ARRAYLIST)
                m.visitInsn(DUP)
                m.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "()V", false)
                for (el in v.elems) {
                    m.visitInsn(DUP)
                    constructValue(m, el, boxed = true)
                    m.visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "add", "(L$OBJ;)Z", false)
                    m.visitInsn(POP)
                }
            }
            is dawn.check.CValue.VTuple -> {
                val cls = tupleClass(v.elems.size)
                m.visitTypeInsn(NEW, cls)
                m.visitInsn(DUP)
                for (el in v.elems) constructValue(m, el, boxed = true)
                m.visitMethodInsn(INVOKESPECIAL, cls, "<init>",
                    "(" + "L$OBJ;".repeat(v.elems.size) + ")V", false)
            }
            is dawn.check.CValue.VAdt -> {
                val ci = v.ctor
                if (ci.fields.isEmpty()) {
                    m.visitFieldInsn(GETSTATIC, ci.jvmName, "INSTANCE", "L${ci.jvmName};")
                } else {
                    m.visitTypeInsn(NEW, ci.jvmName)
                    m.visitInsn(DUP)
                    for ((i, f) in v.fields.withIndex()) {
                        constructValue(m, f, boxed = ci.fields[i].type is TVar)
                    }
                    val desc = "(" + ci.fields.joinToString("") { descOf(it.type) } + ")V"
                    m.visitMethodInsn(INVOKESPECIAL, ci.jvmName, "<init>", desc, false)
                }
            }
            else -> throw IllegalStateException("a function value cannot be a constant (checker bug)")
        }
    }

    private fun genBlock(e: Block, tail: Boolean): Boolean {
        for (s in e.stmts) {
            if (!genStmt(s)) return false // unreachable from here on; stop emitting
        }
        if (e.tail == null) return true
        val falls = genExpr(e.tail!!, tail)
        // discarded Java tail (spec §9): the block is Unit, the call is not
        if (falls && e.type == TUnit && e.tail!!.type != TUnit) popValue(e.tail!!.type!!)
        return falls
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
                    when (val at = p.expr.type!!) {
                        TInt -> mv.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(J)L$SB;", false)
                        TFloat -> mv.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(D)L$SB;", false)
                        TBool -> mv.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Z)L$SB;", false)
                        TString -> mv.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
                        else -> {
                            // a derive Show value: render via the runtime, then append the string
                            box(at)
                            mv.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "show", "(L$OBJ;)Ljava/lang/String;", false)
                            mv.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
                        }
                    }
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
        while (pendingLambdas.isNotEmpty() || pendingBridges.isNotEmpty() ||
            pendingBuiltinBridges.isNotEmpty() || pendingCtorBridges.isNotEmpty()) {
            when {
                pendingLambdas.isNotEmpty() -> genLambdaImpl(cw, pendingLambdas.removeFirst())
                pendingBridges.isNotEmpty() ->
                    genFnValueBridge(cw, pendingBridges.first().also { pendingBridges.remove(it) })
                pendingBuiltinBridges.isNotEmpty() ->
                    genBuiltinBridge(cw, pendingBuiltinBridges.first().also { pendingBuiltinBridges.remove(it) })
                else ->
                    genCtorValueBridge(cw, pendingCtorBridges.first().also { pendingCtorBridges.remove(it) })
            }
        }
    }

    /**
     * A top-level function or builtin used as a value: a zero-capture lambda
     * over its static method (or a bridge). The instantiated type comes from
     * the checker's annotation, so generic values adapt Object↔boxed correctly.
     */
    private fun genFnValue(e: VarRef, fv: FnSig) {
        val ft = e.type as TFn
        val n = fv.paramTypes.size
        val handle = if (fv.isBuiltin) builtinValueHandle(fv) else {
            if (slotsOf(fv.ret) == 0) {
                // Unit-returning functions need a bridge (LMF cannot adapt void)
                pendingBridges.add(fv)
                Handle(H_INVOKESTATIC, className, "dawn\$fnval\$${fv.name}",
                    implDescOf(fv.paramTypes, fv.ret), false)
            } else {
                Handle(H_INVOKESTATIC, className, fv.name, methodDesc(fv.paramTypes, fv.ret), false)
            }
        }
        mv.visitInvokeDynamicInsn(
            "apply", "()L${fnIface(n)};", LMF_BSM,
            AsmType.getMethodType(erasedApplyDesc(n)),
            handle,
            instantiatedType(ft.params, ft.ret),
        )
    }

    /** builtins with a real runtime method get a direct handle; the rest get a bridge */
    private fun builtinValueHandle(fv: FnSig): Handle = when (fv.name) {
        "get" -> Handle(H_INVOKESTATIC, LISTS_CLASS, "get", "(L$JLIST;J)LOption;", false)
        "range" -> Handle(H_INVOKESTATIC, LISTS_CLASS, "range", "(JJ)L$JLIST;", false)
        "map", "filter" ->
            Handle(H_INVOKESTATIC, LISTS_CLASS, fv.name, "(L$JLIST;L${fnIface(1)};)L$JLIST;", false)
        "fold" -> Handle(H_INVOKESTATIC, LISTS_CLASS, "fold", "(L$JLIST;L$OBJ;L${fnIface(2)};)L$OBJ;", false)
        "chars" -> Handle(H_INVOKESTATIC, STRINGS_CLASS, "chars", "(Ljava/lang/String;)L$JLIST;", false)
        "join" -> Handle(H_INVOKESTATIC, STRINGS_CLASS, "join", "(L$JLIST;Ljava/lang/String;)Ljava/lang/String;", false)
        "split" -> Handle(H_INVOKESTATIC, STRINGS_CLASS, "split",
            "(Ljava/lang/String;Ljava/lang/String;)L$JLIST;", false)
        "parse_int" -> Handle(H_INVOKESTATIC, STRINGS_CLASS, "parseInt", "(Ljava/lang/String;)LOption;", false)
        "parse_float" -> Handle(H_INVOKESTATIC, STRINGS_CLASS, "parseFloat", "(Ljava/lang/String;)LOption;", false)
        "read_file" -> Handle(H_INVOKESTATIC, IO_CLASS, "readFile", "(Ljava/lang/String;)LResult;", false)
        "write_file" -> Handle(H_INVOKESTATIC, IO_CLASS, "writeFile",
            "(Ljava/lang/String;Ljava/lang/String;)LResult;", false)
        "read_line" -> Handle(H_INVOKESTATIC, IO_CLASS, "readLine", "()LOption;", false)
        else -> {
            pendingBuiltinBridges.add(fv)
            Handle(H_INVOKESTATIC, className, "dawn\$bi\$${fv.name}", implDescOf(fv.paramTypes, fv.ret), false)
        }
    }

    private val emittedBuiltinBridges = HashSet<String>()

    /** small static bodies for builtins that are inlined at call sites */
    private fun genBuiltinBridge(cw: ClassWriter, sig: FnSig) {
        if (!emittedBuiltinBridges.add(sig.name)) return
        val m = cw.visitMethod(
            ACC_PRIVATE or ACC_STATIC or ACC_SYNTHETIC, "dawn\$bi\$${sig.name}",
            implDescOf(sig.paramTypes, sig.ret), null, null,
        )
        m.visitCode()
        when (sig.name) {
            "println", "print" -> {
                m.visitFieldInsn(GETSTATIC, "java/lang/System", "out", "Ljava/io/PrintStream;")
                m.visitVarInsn(ALOAD, 0)
                m.visitMethodInsn(INVOKEVIRTUAL, "java/io/PrintStream", sig.name, "(Ljava/lang/String;)V", false)
                m.visitInsn(ACONST_NULL)
                m.visitInsn(ARETURN)
            }
            "panic" -> {
                m.visitTypeInsn(NEW, PANIC_CLASS)
                m.visitInsn(DUP)
                m.visitVarInsn(ALOAD, 0)
                m.visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
                m.visitInsn(ATHROW)
            }
            "todo" -> {
                m.visitTypeInsn(NEW, PANIC_CLASS)
                m.visitInsn(DUP)
                m.visitLdcInsn("not yet implemented")
                m.visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
                m.visitInsn(ATHROW)
            }
            "to_string" -> {
                // a top-level String renders unquoted; everything else goes through Show
                val str = Label()
                m.visitVarInsn(ALOAD, 0)
                m.visitTypeInsn(INSTANCEOF, "java/lang/String")
                m.visitJumpInsn(IFNE, str)
                m.visitVarInsn(ALOAD, 0)
                m.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "show", "(L$OBJ;)Ljava/lang/String;", false)
                m.visitInsn(ARETURN)
                m.visitLabel(str)
                m.visitVarInsn(ALOAD, 0)
                m.visitTypeInsn(CHECKCAST, "java/lang/String")
                m.visitInsn(ARETURN)
            }
            "to_float" -> {
                m.visitVarInsn(LLOAD, 0)
                m.visitInsn(L2D)
                m.visitInsn(DRETURN)
            }
            "to_int" -> {
                m.visitVarInsn(DLOAD, 0)
                m.visitInsn(D2L)
                m.visitInsn(LRETURN)
            }
            "len" -> {
                m.visitVarInsn(ALOAD, 0)
                m.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
                m.visitInsn(I2L)
                m.visitInsn(LRETURN)
            }
            "trim" -> {
                m.visitVarInsn(ALOAD, 0)
                m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/String", "strip", "()Ljava/lang/String;", false)
                m.visitInsn(ARETURN)
            }
            "contains" -> {
                m.visitVarInsn(ALOAD, 0)
                m.visitVarInsn(ALOAD, 1)
                m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/String", "contains",
                    "(Ljava/lang/CharSequence;)Z", false)
                m.visitInsn(IRETURN)
            }
            "starts_with", "ends_with" -> {
                m.visitVarInsn(ALOAD, 0)
                m.visitVarInsn(ALOAD, 1)
                m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/String",
                    if (sig.name == "starts_with") "startsWith" else "endsWith", "(Ljava/lang/String;)Z", false)
                m.visitInsn(IRETURN)
            }
            "args" -> {
                m.visitFieldInsn(GETSTATIC, className, ARGS_FIELD, "[Ljava/lang/String;")
                m.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "fromArray", "([Ljava/lang/String;)L$JLIST;", false)
                m.visitInsn(ARETURN)
            }
            "expect" -> {
                m.visitVarInsn(ALOAD, 0)
                m.visitTypeInsn(INSTANCEOF, "Option\$Some")
                val ok = Label()
                m.visitJumpInsn(IFNE, ok)
                m.visitTypeInsn(NEW, PANIC_CLASS)
                m.visitInsn(DUP)
                m.visitVarInsn(ALOAD, 1)
                m.visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
                m.visitInsn(ATHROW)
                m.visitLabel(ok)
                m.visitVarInsn(ALOAD, 0)
                m.visitTypeInsn(CHECKCAST, "Option\$Some")
                m.visitFieldInsn(GETFIELD, "Option\$Some", "value", "L$OBJ;")
                m.visitInsn(ARETURN)
            }
            "unwrap_or" -> {
                m.visitVarInsn(ALOAD, 0)
                m.visitTypeInsn(INSTANCEOF, "Option\$Some")
                val some = Label()
                m.visitJumpInsn(IFNE, some)
                m.visitVarInsn(ALOAD, 1)
                m.visitInsn(ARETURN)
                m.visitLabel(some)
                m.visitVarInsn(ALOAD, 0)
                m.visitTypeInsn(CHECKCAST, "Option\$Some")
                m.visitFieldInsn(GETFIELD, "Option\$Some", "value", "L$OBJ;")
                m.visitInsn(ARETURN)
            }
            else -> throw IllegalStateException("no value bridge for builtin `${sig.name}`")
        }
        m.visitMaxs(0, 0)
        m.visitEnd()
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

    // ---- Java interop (spec §9) ----

    /** Dawn value on the stack → the Java parameter's type (only Int/Float may narrow) */
    private fun adaptJavaArg(dawnType: Type, javaParam: Class<*>) {
        when {
            dawnType == TInt && javaParam == Integer.TYPE -> mv.visitInsn(L2I)
            dawnType == TFloat && javaParam == java.lang.Float.TYPE -> mv.visitInsn(D2F)
            else -> {}
        }
    }

    /** varargs calls carry no variable part in v0.1: supply the empty array */
    private fun pushEmptyVarargs(component: Class<*>) {
        mv.visitInsn(ICONST_0)
        if (component.isPrimitive) {
            val t = when (component) {
                java.lang.Long.TYPE -> T_LONG
                Integer.TYPE -> T_INT
                java.lang.Double.TYPE -> T_DOUBLE
                java.lang.Float.TYPE -> T_FLOAT
                java.lang.Boolean.TYPE -> T_BOOLEAN
                java.lang.Short.TYPE -> T_SHORT
                java.lang.Byte.TYPE -> T_BYTE
                else -> T_CHAR
            }
            mv.visitIntInsn(NEWARRAY, t)
        } else {
            mv.visitTypeInsn(ANEWARRAY, AsmType.getInternalName(component))
        }
    }

    /** Type.new(args): direct construction — never null, so no Option wrap */
    private fun genJavaNew(e: MethodCall): Boolean {
        val ctor = e.javaCtorRef!!
        val owner = AsmType.getInternalName(ctor.declaringClass)
        mv.visitTypeInsn(NEW, owner)
        mv.visitInsn(DUP)
        for ((arg, p) in e.args.zip(ctor.parameterTypes)) {
            if (!genExpr(arg, tail = false)) return false
            adaptJavaArg(arg.type!!, p)
        }
        if (ctor.isVarArgs && e.args.size == ctor.parameterCount - 1)
            pushEmptyVarargs(ctor.parameterTypes.last().componentType)
        mv.visitMethodInsn(INVOKESPECIAL, owner, "<init>", AsmType.getConstructorDescriptor(ctor), false)
        return true
    }

    private fun genJavaCall(e: MethodCall): Boolean {
        val m = e.javaMethod!!
        val static = java.lang.reflect.Modifier.isStatic(m.modifiers)
        val owner = AsmType.getInternalName(m.declaringClass)
        val itf = m.declaringClass.isInterface
        if (!static) {
            if (!genExpr(e.target, tail = false)) return false
        }
        for ((arg, p) in e.args.zip(m.parameterTypes)) {
            if (!genExpr(arg, tail = false)) return false
            adaptJavaArg(arg.type!!, p)
        }
        if (m.isVarArgs && e.args.size == m.parameterCount - 1)
            pushEmptyVarargs(m.parameterTypes.last().componentType)
        mv.visitMethodInsn(
            if (static) INVOKESTATIC else if (itf) INVOKEINTERFACE else INVOKEVIRTUAL,
            owner, m.name, AsmType.getMethodDescriptor(m), itf,
        )
        // returns (spec §9.2): small ints widen, floats widen, references wrap in Option
        when (m.returnType) {
            Integer.TYPE, java.lang.Short.TYPE, java.lang.Byte.TYPE -> mv.visitInsn(I2L)
            java.lang.Float.TYPE -> mv.visitInsn(F2D)
            java.lang.Void.TYPE, java.lang.Long.TYPE, java.lang.Double.TYPE, java.lang.Boolean.TYPE -> {}
            else -> wrapNullableInOption()
        }
        return true
    }

    /** reference on the stack → Some(ref) / None (null is caught at the boundary, spec §9.2) */
    private fun wrapNullableInOption() {
        val tmp = nextSlot
        nextSlot += 1
        mv.visitVarInsn(ASTORE, tmp)
        val nonNull = Label()
        val end = Label()
        mv.visitVarInsn(ALOAD, tmp)
        mv.visitJumpInsn(IFNONNULL, nonNull)
        mv.visitFieldInsn(GETSTATIC, "Option\$None", "INSTANCE", "LOption\$None;")
        mv.visitTypeInsn(CHECKCAST, "Option")
        mv.visitJumpInsn(GOTO, end)
        mv.visitLabel(nonNull)
        mv.visitTypeInsn(NEW, "Option\$Some")
        mv.visitInsn(DUP)
        mv.visitVarInsn(ALOAD, tmp)
        mv.visitMethodInsn(INVOKESPECIAL, "Option\$Some", "<init>", "(L$OBJ;)V", false)
        mv.visitTypeInsn(CHECKCAST, "Option")
        mv.visitLabel(end)
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
        e.ctorValue?.let { return genCtorValue(e, it) }
        e.constDecl?.let { cd ->
            genLoadConst(cd.value!!, e.type!!, key = cd)
            return true
        }
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

    /** a bare constructor used as a function value: an LMF over a synthetic construction bridge */
    private fun genCtorValue(e: CtorCall, ci: CtorInfo): Boolean {
        val ft = e.type as TFn
        pendingCtorBridges.add(ci)
        val handle = Handle(H_INVOKESTATIC, className, "dawn\$ctor\$${ci.jvmName}",
            implDescOf(ci.fields.map { it.type }, ci.adt.type), false)
        mv.visitInvokeDynamicInsn(
            "apply", "()L${fnIface(ft.params.size)};", LMF_BSM,
            AsmType.getMethodType(erasedApplyDesc(ft.params.size)),
            handle,
            instantiatedType(ft.params, ft.ret),
        )
        return true
    }

    /** static body `dawn$ctor$X(fields...) -> Adt` = new + init, target of a constructor value's LMF */
    private fun genCtorValueBridge(cw: ClassWriter, ci: CtorInfo) {
        val sub = ci.jvmName
        if (!emittedCtorBridges.add(sub)) return
        val fieldTypes = ci.fields.map { it.type }
        val m = cw.visitMethod(
            ACC_PRIVATE or ACC_STATIC or ACC_SYNTHETIC, "dawn\$ctor\$$sub",
            implDescOf(fieldTypes, ci.adt.type), null, null,
        )
        m.visitCode()
        m.visitTypeInsn(NEW, sub)
        m.visitInsn(DUP)
        var slot = 0
        for (ft in fieldTypes) {
            loadSlot(m, ft, slot)
            slot += slotsOf(ft)
        }
        m.visitMethodInsn(INVOKESPECIAL, sub, "<init>",
            "(" + fieldTypes.joinToString("") { descOf(it) } + ")V", false)
        m.visitInsn(ARETURN)
        m.visitMaxs(0, 0)
        m.visitEnd()
    }

    private fun genTupleLit(e: TupleLit): Boolean {
        val cls = tupleClass(e.elems.size)
        mv.visitTypeInsn(NEW, cls)
        mv.visitInsn(DUP)
        for (el in e.elems) {
            if (!genExpr(el, tail = false)) return false
            box(el.type!!) // tuple elements are stored erased
        }
        mv.visitMethodInsn(INVOKESPECIAL, cls, "<init>",
            "(" + "L$OBJ;".repeat(e.elems.size) + ")V", false)
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
        "expect" -> {
            genExpr(e.args[0], tail = false) // Option
            genExpr(e.args[1], tail = false) // message
            val msgSlot = nextSlot
            nextSlot += 1
            mv.visitVarInsn(ASTORE, msgSlot)
            mv.visitInsn(DUP)
            mv.visitTypeInsn(INSTANCEOF, "Option\$Some")
            val ok = Label()
            mv.visitJumpInsn(IFNE, ok)
            mv.visitTypeInsn(NEW, PANIC_CLASS)
            mv.visitInsn(DUP)
            mv.visitVarInsn(ALOAD, msgSlot)
            mv.visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
            mv.visitInsn(ATHROW)
            mv.visitLabel(ok)
            mv.visitTypeInsn(CHECKCAST, "Option\$Some")
            mv.visitFieldInsn(GETFIELD, "Option\$Some", "value", "L$OBJ;")
            if (slotsOf(e.type!!) == 0) mv.visitInsn(POP) else unerase(e.type!!)
            true
        }
        "unwrap_or" -> {
            genExpr(e.args[0], tail = false) // Option
            genExpr(e.args[1], tail = false) // fallback (strict: always evaluated)
            val fbType = e.type!!
            val fbSlot = nextSlot
            nextSlot += slotsOf(fbType)
            storeSlot(mv, fbType, fbSlot)
            mv.visitInsn(DUP)
            mv.visitTypeInsn(INSTANCEOF, "Option\$Some")
            val someL = Label()
            val end = Label()
            mv.visitJumpInsn(IFNE, someL)
            mv.visitInsn(POP)
            loadSlot(mv, fbType, fbSlot)
            mv.visitJumpInsn(GOTO, end)
            mv.visitLabel(someL)
            mv.visitTypeInsn(CHECKCAST, "Option\$Some")
            mv.visitFieldInsn(GETFIELD, "Option\$Some", "value", "L$OBJ;")
            unerase(fbType)
            mv.visitLabel(end)
            true
        }
        "to_string" -> {
            genExpr(e.args[0], tail = false)
            when (val at = e.args[0].type!!) {
                TInt -> mv.visitMethodInsn(INVOKESTATIC, "java/lang/String", "valueOf",
                    "(J)Ljava/lang/String;", false)
                TFloat -> mv.visitMethodInsn(INVOKESTATIC, "java/lang/String", "valueOf",
                    "(D)Ljava/lang/String;", false)
                TBool -> mv.visitMethodInsn(INVOKESTATIC, "java/lang/String", "valueOf",
                    "(Z)Ljava/lang/String;", false)
                TString -> {} // stays as is
                else -> {
                    // derive Show value (ADT / tuple / list / Option): render via the runtime
                    box(at)
                    mv.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "show", "(L$OBJ;)Ljava/lang/String;", false)
                }
            }
            true
        }
        "chars" -> {
            genExpr(e.args[0], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, STRINGS_CLASS, "chars", "(Ljava/lang/String;)L$JLIST;", false)
            true
        }
        "join" -> {
            genExpr(e.args[0], tail = false)
            genExpr(e.args[1], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, STRINGS_CLASS, "join",
                "(L$JLIST;Ljava/lang/String;)Ljava/lang/String;", false)
            true
        }
        "split" -> {
            genExpr(e.args[0], tail = false)
            genExpr(e.args[1], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, STRINGS_CLASS, "split",
                "(Ljava/lang/String;Ljava/lang/String;)L$JLIST;", false)
            true
        }
        "trim" -> {
            genExpr(e.args[0], tail = false)
            mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/String", "strip", "()Ljava/lang/String;", false)
            true
        }
        "contains" -> {
            genExpr(e.args[0], tail = false)
            genExpr(e.args[1], tail = false)
            mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/String", "contains", "(Ljava/lang/CharSequence;)Z", false)
            true
        }
        "starts_with", "ends_with" -> {
            genExpr(e.args[0], tail = false)
            genExpr(e.args[1], tail = false)
            mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/String",
                if (e.callee == "starts_with") "startsWith" else "endsWith", "(Ljava/lang/String;)Z", false)
            true
        }
        "parse_int", "parse_float" -> {
            genExpr(e.args[0], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, STRINGS_CLASS,
                if (e.callee == "parse_int") "parseInt" else "parseFloat", "(Ljava/lang/String;)LOption;", false)
            true
        }
        "read_file" -> {
            genExpr(e.args[0], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, IO_CLASS, "readFile", "(Ljava/lang/String;)LResult;", false)
            true
        }
        "write_file" -> {
            genExpr(e.args[0], tail = false)
            genExpr(e.args[1], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, IO_CLASS, "writeFile",
                "(Ljava/lang/String;Ljava/lang/String;)LResult;", false)
            true
        }
        "read_line" -> {
            mv.visitMethodInsn(INVOKESTATIC, IO_CLASS, "readLine", "()LOption;", false)
            true
        }
        "args" -> {
            mv.visitFieldInsn(GETSTATIC, className, ARGS_FIELD, "[Ljava/lang/String;")
            mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "fromArray", "([Ljava/lang/String;)L$JLIST;", false)
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

    /** [pre.., ..rest, post..]: length check, fixed elements from both ends, slice the middle */
    private fun genListPatternTest(p: ListPat, slot: Int, failTo: Label) {
        val fixed = p.pre.size + p.post.size
        mv.visitVarInsn(ALOAD, slot)
        mv.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
        val sizeSlot = nextSlot
        nextSlot += 1
        mv.visitVarInsn(ISTORE, sizeSlot)
        mv.visitVarInsn(ILOAD, sizeSlot)
        mv.visitLdcInsn(fixed)
        mv.visitJumpInsn(if (p.hasRest) IF_ICMPLT else IF_ICMPNE, failTo)
        val elem = p.elemType!!
        fun testElemAt(sub: Pattern, loadIndex: () -> Unit) {
            mv.visitVarInsn(ALOAD, slot)
            loadIndex()
            mv.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
            unerase(elem)
            val eSlot = nextSlot
            nextSlot += slotsOf(elem)
            storeSlot(mv, elem, eSlot)
            genPatternTest(sub, eSlot, elem, failTo)
        }
        for ((i, sub) in p.pre.withIndex()) {
            if (sub is WildPat) continue
            testElemAt(sub) { mv.visitLdcInsn(i) }
        }
        for ((j, sub) in p.post.withIndex()) {
            if (sub is WildPat) continue
            testElemAt(sub) {
                mv.visitVarInsn(ILOAD, sizeSlot)
                mv.visitLdcInsn(p.post.size - j)
                mv.visitInsn(ISUB)
            }
        }
        val rest = p.restSymbol
        if (rest != null) {
            mv.visitVarInsn(ALOAD, slot)
            mv.visitLdcInsn(p.pre.size)
            mv.visitVarInsn(ILOAD, sizeSlot)
            mv.visitLdcInsn(p.post.size)
            mv.visitInsn(ISUB)
            mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "slice", "(L$JLIST;II)L$JLIST;", false)
            rest.slot = nextSlot
            nextSlot += 1
            mv.visitVarInsn(ASTORE, rest.slot)
        }
    }

    /**
     * Destructuring bind (irrefutable, checker-verified): extract fields into
     * fresh slots, alias bindings. No tests, no fail path.
     */
    private fun genBind(p: Pattern, slot: Int) {
        when (p) {
            is WildPat -> {}
            is BindPat -> { p.symbol!!.slot = slot }
            is TuplePat -> {
                val cls = tupleClass(p.elems.size)
                for ((i, sub) in p.elems.withIndex()) {
                    if (sub is WildPat) continue
                    val et = p.elemTypes!![i]
                    mv.visitVarInsn(ALOAD, slot)
                    mv.visitFieldInsn(GETFIELD, cls, "_$i", "L$OBJ;")
                    unerase(et)
                    val eSlot = nextSlot
                    nextSlot += slotsOf(et)
                    storeSlot(mv, et, eSlot)
                    genBind(sub, eSlot)
                }
            }
            is CtorPat -> {
                val ci = p.ctor!!
                for ((i, fp) in p.fieldPats!!.withIndex()) {
                    if (fp == null || fp is WildPat) continue
                    val declared = ci.fields[i].type
                    val concrete = p.fieldTypes!![i]
                    mv.visitVarInsn(ALOAD, slot)
                    mv.visitTypeInsn(CHECKCAST, ci.jvmName) // static type may be the ADT base
                    mv.visitFieldInsn(GETFIELD, ci.jvmName, ci.fields[i].name, descOf(declared))
                    adaptFrom(declared, concrete)
                    val fSlot = nextSlot
                    nextSlot += slotsOf(concrete)
                    storeSlot(mv, concrete, fSlot)
                    genBind(fp, fSlot)
                }
            }
            is ListPat -> {
                // irrefutable ⟺ [..rest]: the rest is the whole list
                p.restSymbol?.let { it.slot = slot }
            }
            is LitPat -> throw IllegalStateException("refutable pattern in let (checker bug)")
        }
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
            is TuplePat -> {
                val cls = tupleClass(p.elems.size)
                for ((i, sub) in p.elems.withIndex()) {
                    if (sub is WildPat) continue
                    val et = p.elemTypes!![i]
                    mv.visitVarInsn(ALOAD, slot)
                    mv.visitFieldInsn(GETFIELD, cls, "_$i", "L$OBJ;")
                    unerase(et)
                    val eSlot = nextSlot
                    nextSlot += slotsOf(et)
                    storeSlot(mv, et, eSlot)
                    genPatternTest(sub, eSlot, et, failTo)
                }
            }
            is ListPat -> genListPatternTest(p, slot, failTo)
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
