package dawn.codegen

import dawn.ast.*
import dawn.check.AdtInfo
import dawn.check.BUILTINS
import dawn.check.CtorInfo
import dawn.check.FnSig
import dawn.check.ImplInfo
import dawn.check.ORD_TRAIT
import dawn.check.PRELUDE_ADTS
import dawn.check.PRELUDE_IMPLS
import dawn.check.PRELUDE_TRAITS
import dawn.check.Symbol
import dawn.check.TraitInfo
import dawn.check.Type
import dawn.check.Type.*
import dawn.check.WitnessRef
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
    /**
     * Every ADT in the whole program (spec §10), so cross-module frames resolve.
     * Null = single-file: prelude + this module's own types.
     */
    programAdts: List<AdtInfo>? = null,
) {

    companion object {
        /** One module to generate: its checked AST and its JVM class name (spec §10). */
        class ModuleUnit(val module: Module, val className: String)

        /**
         * Compile a whole multi-module program: shared runtime + prelude ADT classes
         * once, then each module's class and its own ADT classes, with a program-wide
         * ADT set so cross-module frames resolve (spec §10, §12.2).
         */
        fun generateProgram(units: List<ModuleUnit>, includeTests: Boolean = false): Map<String, ByteArray> {
            val programAdts = PRELUDE_ADTS +
                units.flatMap { u -> u.module.types.mapNotNull { it.ctors.firstOrNull()?.info?.adt } }
            val out = HashMap<String, ByteArray>()
            CodeGen(Module(emptyList()), "", programAdts = programAdts).emitShared(out)
            for (u in units) CodeGen(u.module, u.className, includeTests, programAdts).emitModule(out)
            return out
        }

        const val PANIC_CLASS = "dawn/rt/PanicError"
        const val LISTS_CLASS = "dawn/rt/Lists"
        const val DICT_CMP_CLASS = "dawn/rt/DictComparator"
        const val FN_CMP_CLASS = "dawn/rt/FnComparator"
        const val STRINGS_CLASS = "dawn/rt/Strings"
        const val IO_CLASS = "dawn/rt/Io"
        const val SHOW_CLASS = "dawn/rt/Show"
        const val MAPS_CLASS = "dawn/rt/Maps"
        private const val ARGS_FIELD = "dawn\$args"
        private const val SB = "java/lang/StringBuilder"
        private const val OBJ = "java/lang/Object"
        private const val JLIST = "java/util/List"
        private const val JMAP = "java/util/Map"
        private const val JSET = "java/util/Set"
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

    /** builtin names backed by dawn/rt/Maps (spec §2.2) */
    private val MAP_BUILTINS = setOf(
        "map_empty", "set_empty", "map_from", "set_from", "map_insert", "set_insert",
        "map_remove", "set_remove", "map_get", "map_has", "set_has", "map_size", "set_size",
        "map_keys", "map_values", "map_entries", "set_to_list",
    )

    /** ADTs defined by this module (its own classes to emit) */
    private val ownAdts: List<AdtInfo> = module.types.mapNotNull { it.ctors.firstOrNull()?.info?.adt }

    /** every ADT known for frame computation: the whole program, or (single-file) prelude + own */
    private val allAdts: List<AdtInfo> = programAdts ?: (PRELUDE_ADTS + ownAdts)

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

    /** return type of the method being generated (for `return` expressions) */
    private var methodRet: Type = TUnit
    /** lambda impls return Object — a Unit return must yield null, not a bare RETURN */
    private var methodRetsNull = false
    /** set while generating a local function's impl: self-calls go straight to the impl */
    private var selfPending: PendingLambda? = null

    /** lambdas found while generating a method; their impl methods are emitted after it */
    private class PendingLambda(val lambda: Lambda, val name: String, val selfSym: Symbol? = null)
    private val pendingLambdas = ArrayList<PendingLambda>()

    /** SAM-conversion bridges to emit (spec §9.4): Dawn fn value → functional interface. */
    private class SamBridge(val name: String, val conv: SamConv)
    private val pendingSamBridges = ArrayList<SamBridge>()
    private var samBridgeCounter = 0
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

    /** Single-file (or single-module) generation: shared runtime + this module. */
    fun generate(): Map<String, ByteArray> {
        val out = HashMap<String, ByteArray>()
        emitShared(out)
        emitModule(out)
        return out
    }

    /** prelude ADT classes + the runtime support classes, emitted once per program */
    private fun emitShared(out: MutableMap<String, ByteArray>) {
        for (a in PRELUDE_ADTS) genAdt(a, out)
        for (t in PRELUDE_TRAITS) out[trIface(t)] = genTraitInterface(t)
        for (i in PRELUDE_IMPLS) out[implClass(i)] = genPreludeOrdImpl(i)
        out[DICT_CMP_CLASS] = genComparatorClass(DICT_CMP_CLASS, "L${trIface(ORD_TRAIT)};") { m ->
            m.visitMethodInsn(INVOKEINTERFACE, trIface(ORD_TRAIT), "cmp", "(L$OBJ;L$OBJ;)J", true)
        }
        out[FN_CMP_CLASS] = genComparatorClass(FN_CMP_CLASS, "L${fnIface(2)};") { m ->
            m.visitMethodInsn(INVOKEINTERFACE, fnIface(2), "apply", erasedApplyDesc(2), true)
            m.visitTypeInsn(CHECKCAST, "java/lang/Long")
            m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Long", "longValue", "()J", false)
        }
        out[PANIC_CLASS] = genPanicClass()
        out[LISTS_CLASS] = genListsClass()
        out[STRINGS_CLASS] = genStringsClass()
        out[IO_CLASS] = genIoClass()
        out[SHOW_CLASS] = genShowClass()
        out[MAPS_CLASS] = genMapsClass()
        for (n in 0..8) out[fnIface(n)] = genFnInterface(n)
        for (n in 2..8) out[tupleClass(n)] = genTupleClass(n)
    }

    /**
     * dawn/rt/Maps: the runtime for the builtin persistent Map/Set (spec §2.2).
     * Backed by LinkedHashMap/LinkedHashSet with copy-on-write, so iteration order
     * is insertion order and identical on JVM and native. Keys/values travel erased.
     */
    private fun genMapsClass(): ByteArray {
        val LHM = "java/util/LinkedHashMap"
        val LHS = "java/util/LinkedHashSet"
        val COLL = "java/util/Collection"
        val ITER = "java/util/Iterator"
        val ENTRY = "java/util/Map\$Entry"
        val T2 = tupleClass(2)
        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, MAPS_CLASS, null, OBJ, null)

        fun method(name: String, desc: String, body: MethodVisitor.() -> kotlin.Unit) {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, name, desc, null, null)
            m.visitCode(); m.body(); m.visitMaxs(0, 0); m.visitEnd()
        }
        fun MethodVisitor.newEmpty(cls: String) {
            visitTypeInsn(NEW, cls); visitInsn(DUP); visitMethodInsn(INVOKESPECIAL, cls, "<init>", "()V", false)
        }
        fun MethodVisitor.copyFrom(cls: String, argDesc: String, arg: Int) {
            visitTypeInsn(NEW, cls); visitInsn(DUP); visitVarInsn(ALOAD, arg)
            visitMethodInsn(INVOKESPECIAL, cls, "<init>", "($argDesc)V", false)
        }

        method("map_empty", "()L$JMAP;") { newEmpty(LHM); visitInsn(ARETURN) }
        method("set_empty", "()L$JSET;") { newEmpty(LHS); visitInsn(ARETURN) }

        method("map_insert", "(L$JMAP;L$OBJ;L$OBJ;)L$JMAP;") {
            copyFrom(LHM, "Ljava/util/Map;", 0); visitVarInsn(ASTORE, 3)
            visitVarInsn(ALOAD, 3); visitVarInsn(ALOAD, 1); visitVarInsn(ALOAD, 2)
            visitMethodInsn(INVOKEVIRTUAL, LHM, "put", "(L$OBJ;L$OBJ;)L$OBJ;", false); visitInsn(POP)
            visitVarInsn(ALOAD, 3); visitInsn(ARETURN)
        }
        method("set_insert", "(L$JSET;L$OBJ;)L$JSET;") {
            copyFrom(LHS, "L$COLL;", 0); visitVarInsn(ASTORE, 2)
            visitVarInsn(ALOAD, 2); visitVarInsn(ALOAD, 1)
            visitMethodInsn(INVOKEVIRTUAL, LHS, "add", "(L$OBJ;)Z", false); visitInsn(POP)
            visitVarInsn(ALOAD, 2); visitInsn(ARETURN)
        }
        method("map_remove", "(L$JMAP;L$OBJ;)L$JMAP;") {
            copyFrom(LHM, "Ljava/util/Map;", 0); visitVarInsn(ASTORE, 2)
            visitVarInsn(ALOAD, 2); visitVarInsn(ALOAD, 1)
            visitMethodInsn(INVOKEVIRTUAL, LHM, "remove", "(L$OBJ;)L$OBJ;", false); visitInsn(POP)
            visitVarInsn(ALOAD, 2); visitInsn(ARETURN)
        }
        method("set_remove", "(L$JSET;L$OBJ;)L$JSET;") {
            copyFrom(LHS, "L$COLL;", 0); visitVarInsn(ASTORE, 2)
            visitVarInsn(ALOAD, 2); visitVarInsn(ALOAD, 1)
            visitMethodInsn(INVOKEVIRTUAL, LHS, "remove", "(L$OBJ;)Z", false); visitInsn(POP)
            visitVarInsn(ALOAD, 2); visitInsn(ARETURN)
        }
        method("map_get", "(L$JMAP;L$OBJ;)LOption;") {
            val none = Label()
            visitVarInsn(ALOAD, 0); visitVarInsn(ALOAD, 1)
            visitMethodInsn(INVOKEINTERFACE, JMAP, "containsKey", "(L$OBJ;)Z", true)
            visitJumpInsn(IFEQ, none)
            visitTypeInsn(NEW, "Option\$Some"); visitInsn(DUP)
            visitVarInsn(ALOAD, 0); visitVarInsn(ALOAD, 1)
            visitMethodInsn(INVOKEINTERFACE, JMAP, "get", "(L$OBJ;)L$OBJ;", true)
            visitMethodInsn(INVOKESPECIAL, "Option\$Some", "<init>", "(L$OBJ;)V", false)
            visitInsn(ARETURN)
            visitLabel(none)
            visitFieldInsn(GETSTATIC, "Option\$None", "INSTANCE", "LOption\$None;")
            visitInsn(ARETURN)
        }
        // index(Map, Object) -> Object: the `m[k]` operator — panics when the key is absent
        method("index", "(L$JMAP;L$OBJ;)L$OBJ;") {
            val absent = Label()
            visitVarInsn(ALOAD, 0); visitVarInsn(ALOAD, 1)
            visitMethodInsn(INVOKEINTERFACE, JMAP, "containsKey", "(L$OBJ;)Z", true)
            visitJumpInsn(IFEQ, absent)
            visitVarInsn(ALOAD, 0); visitVarInsn(ALOAD, 1)
            visitMethodInsn(INVOKEINTERFACE, JMAP, "get", "(L$OBJ;)L$OBJ;", true)
            visitInsn(ARETURN)
            visitLabel(absent)
            visitTypeInsn(NEW, PANIC_CLASS); visitInsn(DUP)
            visitTypeInsn(NEW, SB); visitInsn(DUP)
            visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
            visitLdcInsn("key not found: ")
            visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
            visitVarInsn(ALOAD, 1)
            visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "show", "(L$OBJ;)Ljava/lang/String;", false)
            visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
            visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()Ljava/lang/String;", false)
            visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
            visitInsn(ATHROW)
        }
        method("map_has", "(L$JMAP;L$OBJ;)Z") {
            visitVarInsn(ALOAD, 0); visitVarInsn(ALOAD, 1)
            visitMethodInsn(INVOKEINTERFACE, JMAP, "containsKey", "(L$OBJ;)Z", true); visitInsn(IRETURN)
        }
        method("set_has", "(L$JSET;L$OBJ;)Z") {
            visitVarInsn(ALOAD, 0); visitVarInsn(ALOAD, 1)
            visitMethodInsn(INVOKEINTERFACE, JSET, "contains", "(L$OBJ;)Z", true); visitInsn(IRETURN)
        }
        method("map_size", "(L$JMAP;)J") {
            visitVarInsn(ALOAD, 0); visitMethodInsn(INVOKEINTERFACE, JMAP, "size", "()I", true)
            visitInsn(I2L); visitInsn(LRETURN)
        }
        method("set_size", "(L$JSET;)J") {
            visitVarInsn(ALOAD, 0); visitMethodInsn(INVOKEINTERFACE, JSET, "size", "()I", true)
            visitInsn(I2L); visitInsn(LRETURN)
        }
        method("map_keys", "(L$JMAP;)L$JLIST;") {
            visitTypeInsn(NEW, ARRAYLIST); visitInsn(DUP)
            visitVarInsn(ALOAD, 0); visitMethodInsn(INVOKEINTERFACE, JMAP, "keySet", "()L$JSET;", true)
            visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "(L$COLL;)V", false); visitInsn(ARETURN)
        }
        method("map_values", "(L$JMAP;)L$JLIST;") {
            visitTypeInsn(NEW, ARRAYLIST); visitInsn(DUP)
            visitVarInsn(ALOAD, 0); visitMethodInsn(INVOKEINTERFACE, JMAP, "values", "()L$COLL;", true)
            visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "(L$COLL;)V", false); visitInsn(ARETURN)
        }
        method("set_to_list", "(L$JSET;)L$JLIST;") {
            copyFrom(ARRAYLIST, "L$COLL;", 0); visitInsn(ARETURN)
        }
        method("set_from", "(L$JLIST;)L$JSET;") {
            copyFrom(LHS, "L$COLL;", 0); visitInsn(ARETURN)
        }
        method("map_from", "(L$JLIST;)L$JMAP;") {
            newEmpty(LHM); visitVarInsn(ASTORE, 1)
            visitVarInsn(ALOAD, 0); visitMethodInsn(INVOKEINTERFACE, JLIST, "iterator", "()L$ITER;", true)
            visitVarInsn(ASTORE, 2)
            val loop = Label(); val done = Label()
            visitLabel(loop)
            visitVarInsn(ALOAD, 2); visitMethodInsn(INVOKEINTERFACE, ITER, "hasNext", "()Z", true)
            visitJumpInsn(IFEQ, done)
            visitVarInsn(ALOAD, 2); visitMethodInsn(INVOKEINTERFACE, ITER, "next", "()L$OBJ;", true)
            visitTypeInsn(CHECKCAST, T2); visitVarInsn(ASTORE, 3)
            visitVarInsn(ALOAD, 1)
            visitVarInsn(ALOAD, 3); visitFieldInsn(GETFIELD, T2, "_0", "L$OBJ;")
            visitVarInsn(ALOAD, 3); visitFieldInsn(GETFIELD, T2, "_1", "L$OBJ;")
            visitMethodInsn(INVOKEVIRTUAL, LHM, "put", "(L$OBJ;L$OBJ;)L$OBJ;", false); visitInsn(POP)
            visitJumpInsn(GOTO, loop)
            visitLabel(done)
            visitVarInsn(ALOAD, 1); visitInsn(ARETURN)
        }
        method("map_entries", "(L$JMAP;)L$JLIST;") {
            visitTypeInsn(NEW, ARRAYLIST); visitInsn(DUP)
            visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "()V", false); visitVarInsn(ASTORE, 1)
            visitVarInsn(ALOAD, 0); visitMethodInsn(INVOKEINTERFACE, JMAP, "entrySet", "()L$JSET;", true)
            visitMethodInsn(INVOKEINTERFACE, JSET, "iterator", "()L$ITER;", true); visitVarInsn(ASTORE, 2)
            val loop = Label(); val done = Label()
            visitLabel(loop)
            visitVarInsn(ALOAD, 2); visitMethodInsn(INVOKEINTERFACE, ITER, "hasNext", "()Z", true)
            visitJumpInsn(IFEQ, done)
            visitVarInsn(ALOAD, 2); visitMethodInsn(INVOKEINTERFACE, ITER, "next", "()L$OBJ;", true)
            visitTypeInsn(CHECKCAST, ENTRY); visitVarInsn(ASTORE, 3)
            visitVarInsn(ALOAD, 1)
            visitTypeInsn(NEW, T2); visitInsn(DUP)
            visitVarInsn(ALOAD, 3); visitMethodInsn(INVOKEINTERFACE, ENTRY, "getKey", "()L$OBJ;", true)
            visitVarInsn(ALOAD, 3); visitMethodInsn(INVOKEINTERFACE, ENTRY, "getValue", "()L$OBJ;", true)
            visitMethodInsn(INVOKESPECIAL, T2, "<init>", "(L$OBJ;L$OBJ;)V", false)
            visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "add", "(L$OBJ;)Z", false); visitInsn(POP)
            visitJumpInsn(GOTO, loop)
            visitLabel(done)
            visitVarInsn(ALOAD, 1); visitInsn(ARETURN)
        }
        cw.visitEnd()
        return cw.toByteArray()
    }

    /** this module's ADT classes + its class of static methods */
    private fun emitModule(out: MutableMap<String, ByteArray>) {
        for (a in ownAdts) genAdt(a, out)
        for (t in module.traits) t.info?.let { out[trIface(it)] = genTraitInterface(it) }
        for (d in module.impls) d.info?.let { out[implClass(it)] = genImplClass(it) }
        for (a in ownAdts) { // derive Ord singletons
            val ii = a.ordImpl ?: continue
            if (ii.derived) out[implClass(ii)] = genImplClass(ii)
        }

        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, className, null, OBJ, null)
        // CLI arguments, set by the JVM entry wrapper; null when absent (tests) → args() gives []
        cw.visitField(ACC_PUBLIC or ACC_STATIC, ARGS_FIELD, "[Ljava/lang/String;", null, null).visitEnd()
        for (d in module.fns) {
            genFn(cw, d)
            drainLambdas(cw)
        }
        for (d in module.impls) {
            val info = d.info ?: continue
            for (m in d.methods) {
                if (m.sig == null) continue
                genFn(cw, m, name = implMethodName(info, m.name))
                drainLambdas(cw)
            }
        }
        for (t in module.traits) {
            val info = t.info ?: continue
            for (m in t.methods) {
                if (m.body == null || m.sig == null) continue
                genTraitDefault(cw, info, m)
                drainLambdas(cw)
            }
        }
        for (a in ownAdts) { // derive Ord cmp statics
            val ii = a.ordImpl ?: continue
            if (ii.derived) genDerivedOrdCmp(cw, ii, a)
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

        // hashCode consistent with equals, so tuples work as Map/Set keys (spec §12.2)
        val hc = cw.visitMethod(ACC_PUBLIC, "hashCode", "()I", null, null)
        hc.visitCode()
        hc.visitInsn(ICONST_1)
        for (i in 0 until n) {
            hc.visitIntInsn(BIPUSH, 31)
            hc.visitInsn(IMUL)
            hc.visitVarInsn(ALOAD, 0)
            hc.visitFieldInsn(GETFIELD, cls, "_$i", "L$OBJ;")
            hc.visitMethodInsn(INVOKEVIRTUAL, OBJ, "hashCode", "()I", false)
            hc.visitInsn(IADD)
        }
        hc.visitInsn(IRETURN)
        hc.visitMaxs(0, 0)
        hc.visitEnd()

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
        is TMap -> "L$JMAP;"
        is TSet -> "L$JSET;"
        is TTuple -> "L${tupleClass(t.elems.size)};"
        is TJava -> if (t.cls.isArray) t.internalName else "L${t.internalName};" // "[B" is its own descriptor
        is TFn -> "L${fnIface(t.params.size)};"
    }

    private fun methodDesc(params: List<Type>, ret: Type): String =
        params.joinToString("", "(", ")") { descOf(it) } + descOf(ret)

    // ---- traits: dictionary passing (docs/trait.md §6) ----

    private fun ownerPrefix(owner: String?) = owner?.replace('/', '$')?.plus("$") ?: ""

    /** the per-trait dictionary interface: one erased method per trait method */
    private fun trIface(t: TraitInfo) = "dawn/tr/" + ownerPrefix(t.owner) + t.name

    private fun subjectName(t: Type): String = when (t) {
        TInt -> "Int"; TFloat -> "Float"; TBool -> "Bool"; TString -> "String"
        is TAdt -> t.info.name
        else -> throw IllegalStateException("invalid impl subject: $t")
    }

    /** the impl's singleton dictionary class */
    private fun implClass(i: ImplInfo) =
        "dawn/impl/" + ownerPrefix(i.owner) + "${i.trait.name}\$${subjectName(i.subject)}"

    /** an impl method compiled as a static on its declaring module's class */
    private fun implMethodName(i: ImplInfo, m: String) =
        "dawn\$impl\$${i.trait.name}\$${subjectName(i.subject)}\$$m"

    /** a trait default body compiled as a static (erased params + one dict) on the trait's module */
    private fun defaultMethodName(t: TraitInfo, m: String) = "dawn\$default\$${t.name}\$$m"

    /** the concrete descriptor of a derived Ord cmp static */
    private fun derivedCmpDesc(i: ImplInfo) = "(${descOf(i.subject)}${descOf(i.subject)})J"

    /** a fn descriptor with the hidden dictionary params appended (dicts travel as Object) */
    private fun fnDescWithDicts(sig: FnSig): String {
        val dicts = sig.constraints.sumOf { it.size }
        return "(" + sig.paramTypes.joinToString("") { descOf(it) } + "L$OBJ;".repeat(dicts) + ")" +
            descOf(sig.ret)
    }

    /** the erased interface descriptor of a trait method (its own tvar params erase to Object) */
    private fun traitMethodDesc(sig: FnSig) = methodDesc(sig.paramTypes, sig.ret)

    private fun slotsOf(t: Type): Int = when (t) {
        TInt, TFloat -> 2
        TBool -> 1
        TUnit, TNever, TError -> 0
        else -> 1 // all references
    }

    private fun isRef(t: Type) =
        t == TString || t is TAdt || t is TList || t is TMap || t is TSet ||
            t is TVar || t is TFn || t is TTuple || t is TJava

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
            is TMap -> mv.visitTypeInsn(CHECKCAST, JMAP)
            is TSet -> mv.visitTypeInsn(CHECKCAST, JSET)
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

        // structural equality (== in Dawn, spec §4.3); singletons keep identity equals.
        // A matching hashCode lets these values serve as Map/Set keys (spec §12.2).
        if (!singleton) { genEqualsMethod(cw, sub, ci); genHashCodeMethod(cw, sub, ci) }
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

    /** hashCode consistent with the structural equals: h = 31*h + field.hash, seeded 1. */
    private fun genHashCodeMethod(cw: ClassWriter, sub: String, ci: CtorInfo) {
        val m = cw.visitMethod(ACC_PUBLIC, "hashCode", "()I", null, null)
        m.visitCode()
        m.visitInsn(ICONST_1)
        for (f in ci.fields) {
            m.visitIntInsn(BIPUSH, 31)
            m.visitInsn(IMUL)
            m.visitVarInsn(ALOAD, 0)
            m.visitFieldInsn(GETFIELD, sub, f.name, descOf(f.type))
            hashOf(m, f.type)
            m.visitInsn(IADD)
        }
        m.visitInsn(IRETURN)
        m.visitMaxs(0, 0)
        m.visitEnd()
    }

    /** consume a value of [t] on the stack, leave its int hash (Dawn values are never null) */
    private fun hashOf(m: MethodVisitor, t: Type) {
        when (t) {
            TInt -> m.visitMethodInsn(INVOKESTATIC, "java/lang/Long", "hashCode", "(J)I", false)
            TFloat -> m.visitMethodInsn(INVOKESTATIC, "java/lang/Double", "hashCode", "(D)I", false)
            TBool -> m.visitMethodInsn(INVOKESTATIC, "java/lang/Boolean", "hashCode", "(Z)I", false)
            else -> m.visitMethodInsn(INVOKEVIRTUAL, OBJ, "hashCode", "()I", false)
        }
    }

    // ---- functions ----

    private fun genFn(cw: ClassWriter, d: FnDecl, name: String = d.name) {
        val sig = d.sig!!
        mv = cw.visitMethod(
            ACC_PUBLIC or ACC_STATIC, name,
            fnDescWithDicts(sig), null, null,
        )
        mv.visitCode()
        currentFn = d
        nextSlot = 0
        methodRet = sig.ret
        methodRetsNull = false
        selfPending = null
        for (p in d.params) {
            val sym = p.symbol!!
            sym.slot = nextSlot
            nextSlot += slotsOf(sym.type)
        }
        for (sym in sig.dictSyms) { // hidden dictionaries ride behind the declared params
            sym.slot = nextSlot
            nextSlot += slotsOf(sym.type)
        }
        val start = Label()
        fnStart = start
        mv.visitLabel(start)
        val falls = genExpr(d.body, tail = true)
        if (falls) emitMethodReturn()
        mv.visitMaxs(0, 0)
        mv.visitEnd()
    }

    /** the return instruction for a value of declared type [t] on the stack */
    private fun emitReturnOf(t: Type) {
        when {
            t == TInt -> mv.visitInsn(LRETURN)
            t == TFloat -> mv.visitInsn(DRETURN)
            t == TBool -> mv.visitInsn(IRETURN)
            isRef(t) -> mv.visitInsn(ARETURN)
            else -> mv.visitInsn(RETURN)
        }
    }

    /** the per-trait dictionary interface: erased abstract method per trait method */
    private fun genTraitInterface(t: TraitInfo): ByteArray {
        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_ABSTRACT or ACC_INTERFACE, trIface(t), null, OBJ, null)
        for ((name, ms) in t.methods)
            cw.visitMethod(ACC_PUBLIC or ACC_ABSTRACT, name, traitMethodDesc(ms.sig), null, null).visitEnd()
        cw.visitEnd()
        return cw.toByteArray()
    }

    /** the shared singleton plumbing of a dictionary class: INSTANCE + <init> + <clinit> */
    private fun singletonScaffold(cw: ClassWriter, cls: String, iface: String) {
        cw.visitField(ACC_PUBLIC or ACC_STATIC or ACC_FINAL, "INSTANCE", "L$iface;", null, null).visitEnd()
        var m = cw.visitMethod(ACC_PRIVATE, "<init>", "()V", null, null)
        m.visitCode()
        m.visitVarInsn(ALOAD, 0)
        m.visitMethodInsn(INVOKESPECIAL, OBJ, "<init>", "()V", false)
        m.visitInsn(RETURN)
        m.visitMaxs(0, 0)
        m.visitEnd()
        m = cw.visitMethod(ACC_STATIC, "<clinit>", "()V", null, null)
        m.visitCode()
        m.visitTypeInsn(NEW, cls)
        m.visitInsn(DUP)
        m.visitMethodInsn(INVOKESPECIAL, cls, "<init>", "()V", false)
        m.visitFieldInsn(PUTSTATIC, cls, "INSTANCE", "L$iface;")
        m.visitInsn(RETURN)
        m.visitMaxs(0, 0)
        m.visitEnd()
    }

    /**
     * An impl's dictionary: a singleton implementing the trait interface. Each
     * erased interface method unwraps to the concrete static (provided) or
     * delegates to the trait's default static with itself as the dictionary.
     */
    private fun genImplClass(i: ImplInfo): ByteArray {
        val cls = implClass(i)
        val iface = trIface(i.trait)
        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, cls, null, OBJ, arrayOf(iface))
        singletonScaffold(cw, cls, iface)
        for ((mname, ms) in i.trait.methods) {
            mv = cw.visitMethod(ACC_PUBLIC, mname, traitMethodDesc(ms.sig), null, null)
            mv.visitCode()
            val provided = i.provided[mname]
            if (i.derived) {
                // derive Ord: unwrap and call the generated field-lexicographic cmp
                mv.visitVarInsn(ALOAD, 1)
                unerase(i.subject)
                mv.visitVarInsn(ALOAD, 2)
                unerase(i.subject)
                mv.visitMethodInsn(INVOKESTATIC, i.owner ?: className, implMethodName(i, "cmp"),
                    derivedCmpDesc(i), false)
            } else if (provided != null) {
                val psig = provided.sig!!
                var slot = 1 // 0 = this
                for ((declared, concrete) in ms.sig.paramTypes.zip(psig.paramTypes)) {
                    loadSlot(mv, declared, slot)
                    if (declared is TVar) unerase(concrete)
                    slot += slotsOf(declared)
                }
                mv.visitMethodInsn(INVOKESTATIC, psig.owner ?: className, implMethodName(i, mname),
                    methodDesc(psig.paramTypes, psig.ret), false)
                if (ms.sig.ret is TVar) box(psig.ret)
            } else {
                // the trait's default body, with this very dictionary
                var slot = 1
                for (declared in ms.sig.paramTypes) {
                    loadSlot(mv, declared, slot)
                    slot += slotsOf(declared)
                }
                mv.visitVarInsn(ALOAD, 0)
                mv.visitMethodInsn(INVOKESTATIC, i.trait.owner ?: className,
                    defaultMethodName(i.trait, mname), fnDescWithDicts(ms.sig), false)
            }
            emitReturnOf(ms.sig.ret)
            mv.visitMaxs(0, 0)
            mv.visitEnd()
        }
        cw.visitEnd()
        return cw.toByteArray()
    }

    /** the prelude Ord[Int/Float/String] dictionaries: cmp is the native comparison */
    private fun genPreludeOrdImpl(i: ImplInfo): ByteArray {
        val cls = implClass(i)
        val iface = trIface(ORD_TRAIT)
        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, cls, null, OBJ, arrayOf(iface))
        singletonScaffold(cw, cls, iface)
        mv = cw.visitMethod(ACC_PUBLIC, "cmp", "(L$OBJ;L$OBJ;)J", null, null)
        mv.visitCode()
        mv.visitVarInsn(ALOAD, 1)
        unerase(i.subject)
        mv.visitVarInsn(ALOAD, 2)
        unerase(i.subject)
        emitNativeCmp(i.subject)
        mv.visitInsn(LRETURN)
        mv.visitMaxs(0, 0)
        mv.visitEnd()
        cw.visitEnd()
        return cw.toByteArray()
    }

    /** two scalars on the stack → their long cmp result (NaN compares below everything here) */
    private fun emitNativeCmp(t: Type) {
        when (t) {
            TInt -> mv.visitInsn(LCMP)
            TFloat -> mv.visitInsn(DCMPL)
            else -> mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/String", "compareTo",
                "(Ljava/lang/String;)I", false)
        }
        mv.visitInsn(I2L)
    }

    /** small-int push */
    private fun pushInt(v: Int) {
        when (v) {
            in -1..5 -> mv.visitInsn(ICONST_0 + v)
            in Byte.MIN_VALUE..Byte.MAX_VALUE -> mv.visitIntInsn(BIPUSH, v)
            else -> mv.visitLdcInsn(v)
        }
    }

    /** two same-typed orderable values on the stack → their long cmp result */
    private fun emitFieldCmp(t: Type) {
        when {
            t == TInt || t == TFloat || t == TString -> emitNativeCmp(t)
            t is TAdt -> {
                val fi = t.info.ordImpl!! // derive validation guaranteed it
                val provided = fi.provided["cmp"]
                when {
                    fi.derived -> mv.visitMethodInsn(INVOKESTATIC, fi.owner ?: className,
                        implMethodName(fi, "cmp"), derivedCmpDesc(fi), false)
                    else -> {
                        val psig = provided!!.sig!!
                        mv.visitMethodInsn(INVOKESTATIC, psig.owner ?: className,
                            implMethodName(fi, "cmp"), methodDesc(psig.paramTypes, psig.ret), false)
                    }
                }
            }
            else -> throw IllegalStateException("unorderable derived field: $t")
        }
    }

    /**
     * derive Ord: cmp(a, b) compares constructor order first (sum types), then
     * fields lexicographically. Emitted as a concrete static on the module class.
     */
    private fun genDerivedOrdCmp(cw: ClassWriter, i: ImplInfo, info: AdtInfo) {
        val cls = info.jvmName
        mv = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, implMethodName(i, "cmp"),
            derivedCmpDesc(i), null, null)
        mv.visitCode()

        fun compareFields(sub: String, fields: List<dawn.check.FieldInfo>, aSlot: Int, bSlot: Int) {
            for (f in fields) {
                mv.visitVarInsn(ALOAD, aSlot)
                mv.visitFieldInsn(GETFIELD, sub, f.name, descOf(f.type))
                mv.visitVarInsn(ALOAD, bSlot)
                mv.visitFieldInsn(GETFIELD, sub, f.name, descOf(f.type))
                emitFieldCmp(f.type)
                val next = Label()
                mv.visitInsn(DUP2)
                mv.visitInsn(LCONST_0)
                mv.visitInsn(LCMP)
                mv.visitJumpInsn(IFEQ, next)
                mv.visitInsn(LRETURN)
                mv.visitLabel(next)
                mv.visitInsn(POP2)
            }
            mv.visitInsn(LCONST_0)
            mv.visitInsn(LRETURN)
        }

        if (info.isRecord) {
            compareFields(cls, info.ctors[0].fields, 0, 1)
        } else {
            // constructor tags in declaration order
            fun emitTagOf(argSlot: Int, store: Int) {
                val doneTag = Label()
                for ((idx, c) in info.ctors.withIndex()) {
                    val next = Label()
                    mv.visitVarInsn(ALOAD, argSlot)
                    mv.visitTypeInsn(INSTANCEOF, c.jvmName)
                    mv.visitJumpInsn(IFEQ, next)
                    pushInt(idx)
                    mv.visitVarInsn(ISTORE, store)
                    mv.visitJumpInsn(GOTO, doneTag)
                    mv.visitLabel(next)
                }
                pushInt(-1) // unreachable: every value is one of the ctors
                mv.visitVarInsn(ISTORE, store)
                mv.visitLabel(doneTag)
            }
            emitTagOf(0, 2)
            emitTagOf(1, 3)
            val sameTag = Label()
            mv.visitVarInsn(ILOAD, 2)
            mv.visitVarInsn(ILOAD, 3)
            mv.visitJumpInsn(IF_ICMPEQ, sameTag)
            mv.visitVarInsn(ILOAD, 2)
            mv.visitVarInsn(ILOAD, 3)
            mv.visitInsn(ISUB)
            mv.visitInsn(I2L)
            mv.visitInsn(LRETURN)
            mv.visitLabel(sameTag)
            for (c in info.ctors) {
                if (c.fields.isEmpty()) continue // same no-payload ctor: equal, falls through
                val next = Label()
                mv.visitVarInsn(ALOAD, 0)
                mv.visitTypeInsn(INSTANCEOF, c.jvmName)
                mv.visitJumpInsn(IFEQ, next)
                mv.visitVarInsn(ALOAD, 0)
                mv.visitTypeInsn(CHECKCAST, c.jvmName)
                mv.visitVarInsn(ASTORE, 4)
                mv.visitVarInsn(ALOAD, 1)
                mv.visitTypeInsn(CHECKCAST, c.jvmName)
                mv.visitVarInsn(ASTORE, 5)
                compareFields(c.jvmName, c.fields, 4, 5)
                mv.visitLabel(next)
            }
            mv.visitInsn(LCONST_0)
            mv.visitInsn(LRETURN)
        }
        mv.visitMaxs(0, 0)
        mv.visitEnd()
    }

    /** a trait default body: a static with erased params plus the trailing dictionary */
    private fun genTraitDefault(cw: ClassWriter, t: TraitInfo, m: TraitMethod) {
        val sig = m.sig!!
        mv = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, defaultMethodName(t, m.name),
            fnDescWithDicts(sig), null, null)
        mv.visitCode()
        currentFn = null // self-calls resolve as trait-method calls, never a tail rewrite by name
        nextSlot = 0
        methodRet = sig.ret
        methodRetsNull = false
        selfPending = null
        fnStart = null
        for (p in m.params) {
            val sym = p.symbol!!
            sym.slot = nextSlot
            nextSlot += slotsOf(sym.type)
        }
        for (sym in sig.dictSyms) {
            sym.slot = nextSlot
            nextSlot += slotsOf(sym.type)
        }
        if (genExpr(m.body!!, tail = false)) emitMethodReturn()
        mv.visitMaxs(0, 0)
        mv.visitEnd()
    }

    /** the return instruction matching the method under generation */
    private fun emitMethodReturn() {
        when {
            methodRet == TInt -> mv.visitInsn(LRETURN)
            methodRet == TFloat -> mv.visitInsn(DRETURN)
            methodRet == TBool -> mv.visitInsn(IRETURN)
            isRef(methodRet) -> mv.visitInsn(ARETURN)
            methodRetsNull -> { // Unit body, Object-returning impl: return null
                mv.visitInsn(ACONST_NULL)
                mv.visitInsn(ARETURN)
            }
            else -> mv.visitInsn(RETURN)
        }
    }

    /** one test block → one public static method dawn$test$i()V */
    private fun genTest(cw: ClassWriter, t: TestDecl, idx: Int) {
        mv = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "dawn\$test\$$idx", "()V", null, null)
        mv.visitCode()
        currentFn = null
        fnStart = null
        nextSlot = 0
        methodRet = TUnit
        methodRetsNull = false
        selfPending = null
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

        // index(List, long) -> Object: the `xs[i]` operator — panics when out of bounds
        val idx = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "index", "(L$JLIST;J)L$OBJ;", null, null)
        idx.visitCode()
        val bad = Label()
        idx.visitVarInsn(LLOAD, 1)
        idx.visitInsn(LCONST_0)
        idx.visitInsn(LCMP)
        idx.visitJumpInsn(IFLT, bad)
        idx.visitVarInsn(LLOAD, 1)
        idx.visitVarInsn(ALOAD, 0)
        idx.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
        idx.visitInsn(I2L)
        idx.visitInsn(LCMP)
        idx.visitJumpInsn(IFGE, bad)
        idx.visitVarInsn(ALOAD, 0)
        idx.visitVarInsn(LLOAD, 1)
        idx.visitInsn(L2I)
        idx.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
        idx.visitInsn(ARETURN)
        idx.visitLabel(bad)
        idx.visitTypeInsn(NEW, PANIC_CLASS)
        idx.visitInsn(DUP)
        idx.visitTypeInsn(NEW, SB)
        idx.visitInsn(DUP)
        idx.visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
        idx.visitLdcInsn("index ")
        idx.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
        idx.visitVarInsn(LLOAD, 1)
        idx.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(J)L$SB;", false)
        idx.visitLdcInsn(" out of bounds for length ")
        idx.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(Ljava/lang/String;)L$SB;", false)
        idx.visitVarInsn(ALOAD, 0)
        idx.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
        idx.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(I)L$SB;", false)
        idx.visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()Ljava/lang/String;", false)
        idx.visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
        idx.visitInsn(ATHROW)
        idx.visitMaxs(0, 0)
        idx.visitEnd()

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
        genListOrdering(cw)

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

    /**
     * A java.util.Comparator over a Dawn ordering source: an Ord dictionary or a
     * two-argument cmp function. [emitCmp] receives (source, a, b) on the stack
     * and must leave the long comparison result.
     */
    private fun genComparatorClass(cls: String, srcDesc: String, emitCmp: (MethodVisitor) -> kotlin.Unit): ByteArray {
        val cw = DawnClassWriter()
        cw.visit(V17, ACC_PUBLIC or ACC_FINAL, cls, null, OBJ, arrayOf("java/util/Comparator"))
        cw.visitField(ACC_PRIVATE or ACC_FINAL, "src", srcDesc, null, null).visitEnd()
        var m = cw.visitMethod(ACC_PUBLIC, "<init>", "($srcDesc)V", null, null)
        m.visitCode()
        m.visitVarInsn(ALOAD, 0)
        m.visitMethodInsn(INVOKESPECIAL, OBJ, "<init>", "()V", false)
        m.visitVarInsn(ALOAD, 0)
        m.visitVarInsn(ALOAD, 1)
        m.visitFieldInsn(PUTFIELD, cls, "src", srcDesc)
        m.visitInsn(RETURN)
        m.visitMaxs(0, 0)
        m.visitEnd()
        m = cw.visitMethod(ACC_PUBLIC, "compare", "(L$OBJ;L$OBJ;)I", null, null)
        m.visitCode()
        m.visitVarInsn(ALOAD, 0)
        m.visitFieldInsn(GETFIELD, cls, "src", srcDesc)
        m.visitVarInsn(ALOAD, 1)
        m.visitVarInsn(ALOAD, 2)
        emitCmp(m)
        m.visitMethodInsn(INVOKESTATIC, "java/lang/Long", "signum", "(J)I", false)
        m.visitInsn(IRETURN)
        m.visitMaxs(0, 0)
        m.visitEnd()
        cw.visitEnd()
        return cw.toByteArray()
    }

    /** sort / sort_by / max / min / max_by / min_by for dawn/rt/Lists (docs/trait.md) */
    private fun genListOrdering(cw: ClassWriter) {
        // sort(List xs, Object ordDict) -> List — stable (TimSort under the hood)
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "sort", "(L$JLIST;L$OBJ;)L$JLIST;", null, null)
            m.visitCode()
            m.visitTypeInsn(NEW, ARRAYLIST)
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "(Ljava/util/Collection;)V", false)
            m.visitVarInsn(ASTORE, 2)
            m.visitVarInsn(ALOAD, 2)
            m.visitTypeInsn(NEW, DICT_CMP_CLASS)
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 1)
            m.visitTypeInsn(CHECKCAST, trIface(ORD_TRAIT))
            m.visitMethodInsn(INVOKESPECIAL, DICT_CMP_CLASS, "<init>", "(L${trIface(ORD_TRAIT)};)V", false)
            m.visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "sort", "(Ljava/util/Comparator;)V", false)
            m.visitVarInsn(ALOAD, 2)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }
        // sortBy(List xs, Fn2 cmp) -> List
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "sortBy", "(L$JLIST;L${fnIface(2)};)L$JLIST;", null, null)
            m.visitCode()
            m.visitTypeInsn(NEW, ARRAYLIST)
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "(Ljava/util/Collection;)V", false)
            m.visitVarInsn(ASTORE, 2)
            m.visitVarInsn(ALOAD, 2)
            m.visitTypeInsn(NEW, FN_CMP_CLASS)
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 1)
            m.visitMethodInsn(INVOKESPECIAL, FN_CMP_CLASS, "<init>", "(L${fnIface(2)};)V", false)
            m.visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "sort", "(Ljava/util/Comparator;)V", false)
            m.visitVarInsn(ALOAD, 2)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }
        // best(List xs, Object ordDict, int sign) -> Option — the first extreme element
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "best", "(L$JLIST;L$OBJ;I)LOption;", null, null)
            m.visitCode()
            val none = Label()
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "isEmpty", "()Z", true)
            m.visitJumpInsn(IFNE, none)
            m.visitVarInsn(ALOAD, 0)
            m.visitInsn(ICONST_0)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
            m.visitVarInsn(ASTORE, 3) // best
            m.visitInsn(ICONST_1)
            m.visitVarInsn(ISTORE, 4) // i
            val loop = Label()
            val done = Label()
            val keep = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ILOAD, 4)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
            m.visitJumpInsn(IF_ICMPGE, done)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ILOAD, 4)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
            m.visitVarInsn(ASTORE, 5) // x
            m.visitVarInsn(ALOAD, 1)
            m.visitTypeInsn(CHECKCAST, trIface(ORD_TRAIT))
            m.visitVarInsn(ALOAD, 5)
            m.visitVarInsn(ALOAD, 3)
            m.visitMethodInsn(INVOKEINTERFACE, trIface(ORD_TRAIT), "cmp", "(L$OBJ;L$OBJ;)J", true)
            m.visitMethodInsn(INVOKESTATIC, "java/lang/Long", "signum", "(J)I", false)
            m.visitVarInsn(ILOAD, 2)
            m.visitInsn(IMUL)
            m.visitJumpInsn(IFLE, keep)
            m.visitVarInsn(ALOAD, 5)
            m.visitVarInsn(ASTORE, 3)
            m.visitLabel(keep)
            m.visitIincInsn(4, 1)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(done)
            m.visitTypeInsn(NEW, "Option\$Some")
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 3)
            m.visitMethodInsn(INVOKESPECIAL, "Option\$Some", "<init>", "(L$OBJ;)V", false)
            m.visitInsn(ARETURN)
            m.visitLabel(none)
            m.visitFieldInsn(GETSTATIC, "Option\$None", "INSTANCE", "LOption\$None;")
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }
        // bestBy(List xs, Fn1 key, Object ordDict, int sign) -> Option — keys cached
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "bestBy",
                "(L$JLIST;L${fnIface(1)};L$OBJ;I)LOption;", null, null)
            m.visitCode()
            val none = Label()
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "isEmpty", "()Z", true)
            m.visitJumpInsn(IFNE, none)
            m.visitVarInsn(ALOAD, 0)
            m.visitInsn(ICONST_0)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
            m.visitVarInsn(ASTORE, 4) // best
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ALOAD, 4)
            m.visitMethodInsn(INVOKEINTERFACE, fnIface(1), "apply", erasedApplyDesc(1), true)
            m.visitVarInsn(ASTORE, 5) // bestKey
            m.visitInsn(ICONST_1)
            m.visitVarInsn(ISTORE, 6) // i
            val loop = Label()
            val done = Label()
            val keep = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ILOAD, 6)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
            m.visitJumpInsn(IF_ICMPGE, done)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ILOAD, 6)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
            m.visitVarInsn(ASTORE, 7) // x
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ALOAD, 7)
            m.visitMethodInsn(INVOKEINTERFACE, fnIface(1), "apply", erasedApplyDesc(1), true)
            m.visitVarInsn(ASTORE, 8) // xKey
            m.visitVarInsn(ALOAD, 2)
            m.visitTypeInsn(CHECKCAST, trIface(ORD_TRAIT))
            m.visitVarInsn(ALOAD, 8)
            m.visitVarInsn(ALOAD, 5)
            m.visitMethodInsn(INVOKEINTERFACE, trIface(ORD_TRAIT), "cmp", "(L$OBJ;L$OBJ;)J", true)
            m.visitMethodInsn(INVOKESTATIC, "java/lang/Long", "signum", "(J)I", false)
            m.visitVarInsn(ILOAD, 3)
            m.visitInsn(IMUL)
            m.visitJumpInsn(IFLE, keep)
            m.visitVarInsn(ALOAD, 7)
            m.visitVarInsn(ASTORE, 4)
            m.visitVarInsn(ALOAD, 8)
            m.visitVarInsn(ASTORE, 5)
            m.visitLabel(keep)
            m.visitIincInsn(6, 1)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(done)
            m.visitTypeInsn(NEW, "Option\$Some")
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 4)
            m.visitMethodInsn(INVOKESPECIAL, "Option\$Some", "<init>", "(L$OBJ;)V", false)
            m.visitInsn(ARETURN)
            m.visitLabel(none)
            m.visitFieldInsn(GETSTATIC, "Option\$None", "INSTANCE", "LOption\$None;")
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0)
            m.visitEnd()
        }
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

        // ---- code points / characters (spec §1.5, §11) ----

        // code_points(String) -> List[Int]: one Long-boxed code point per element
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "code_points", "(L$STR;)L$JLIST;", null, null)
            m.visitCode()
            m.visitTypeInsn(NEW, ARRAYLIST); m.visitInsn(DUP)
            m.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "()V", false)
            m.visitVarInsn(ASTORE, 1)
            m.visitInsn(ICONST_0); m.visitVarInsn(ISTORE, 2)
            val loop = Label(); val done = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ILOAD, 2)
            m.visitVarInsn(ALOAD, 0); m.visitMethodInsn(INVOKEVIRTUAL, STR, "length", "()I", false)
            m.visitJumpInsn(IF_ICMPGE, done)
            m.visitVarInsn(ALOAD, 0); m.visitVarInsn(ILOAD, 2)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "codePointAt", "(I)I", false)
            m.visitVarInsn(ISTORE, 3)
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ILOAD, 3); m.visitInsn(I2L)
            m.visitMethodInsn(INVOKESTATIC, "java/lang/Long", "valueOf", "(J)Ljava/lang/Long;", false)
            m.visitMethodInsn(INVOKEVIRTUAL, ARRAYLIST, "add", "(L$OBJ;)Z", false); m.visitInsn(POP)
            m.visitVarInsn(ILOAD, 2)
            m.visitVarInsn(ILOAD, 3); m.visitMethodInsn(INVOKESTATIC, "java/lang/Character", "charCount", "(I)I", false)
            m.visitInsn(IADD); m.visitVarInsn(ISTORE, 2)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(done)
            m.visitVarInsn(ALOAD, 1); m.visitInsn(ARETURN)
            m.visitMaxs(0, 0); m.visitEnd()
        }

        // from_code_points(List[Int]) -> String
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "from_code_points", "(L$JLIST;)L$STR;", null, null)
            m.visitCode()
            m.visitTypeInsn(NEW, SB); m.visitInsn(DUP)
            m.visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
            m.visitVarInsn(ASTORE, 1)
            m.visitInsn(ICONST_0); m.visitVarInsn(ISTORE, 2)
            val loop = Label(); val done = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ILOAD, 2)
            m.visitVarInsn(ALOAD, 0); m.visitMethodInsn(INVOKEINTERFACE, JLIST, "size", "()I", true)
            m.visitJumpInsn(IF_ICMPGE, done)
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ALOAD, 0); m.visitVarInsn(ILOAD, 2)
            m.visitMethodInsn(INVOKEINTERFACE, JLIST, "get", "(I)L$OBJ;", true)
            m.visitTypeInsn(CHECKCAST, "java/lang/Long")
            m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Long", "intValue", "()I", false)
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "appendCodePoint", "(I)L$SB;", false); m.visitInsn(POP)
            m.visitIincInsn(2, 1)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(done)
            m.visitVarInsn(ALOAD, 1); m.visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0); m.visitEnd()
        }

        // char_to_string(Int) -> String: a single code point; invalid ones panic
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "char_to_string", "(J)L$STR;", null, null)
            m.visitCode()
            m.visitVarInsn(LLOAD, 0); m.visitInsn(L2I); m.visitVarInsn(ISTORE, 2)
            val ok = Label()
            m.visitVarInsn(ILOAD, 2)
            m.visitMethodInsn(INVOKESTATIC, "java/lang/Character", "isValidCodePoint", "(I)Z", false)
            m.visitJumpInsn(IFNE, ok)
            m.visitTypeInsn(NEW, PANIC_CLASS); m.visitInsn(DUP)
            m.visitLdcInsn("char_to_string: not a valid code point")
            m.visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
            m.visitInsn(ATHROW)
            m.visitLabel(ok)
            m.visitVarInsn(ILOAD, 2)
            m.visitMethodInsn(INVOKESTATIC, "java/lang/Character", "toChars", "(I)[C", false)
            m.visitMethodInsn(INVOKESTATIC, STR, "valueOf", "([C)L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0); m.visitEnd()
        }

        // str_len(String) -> Int: number of code points
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "str_len", "(L$STR;)J", null, null)
            m.visitCode()
            m.visitVarInsn(ALOAD, 0); m.visitInsn(ICONST_0)
            m.visitVarInsn(ALOAD, 0); m.visitMethodInsn(INVOKEVIRTUAL, STR, "length", "()I", false)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "codePointCount", "(II)I", false)
            m.visitInsn(I2L); m.visitInsn(LRETURN)
            m.visitMaxs(0, 0); m.visitEnd()
        }

        // substring(String, Int from, Int to) -> String: code-point indices; out of range panics
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "substring", "(L$STR;JJ)L$STR;", null, null)
            m.visitCode()
            // n = codePointCount; slot 5 (int)
            m.visitVarInsn(ALOAD, 0); m.visitInsn(ICONST_0)
            m.visitVarInsn(ALOAD, 0); m.visitMethodInsn(INVOKEVIRTUAL, STR, "length", "()I", false)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "codePointCount", "(II)I", false)
            m.visitVarInsn(ISTORE, 5)
            val ok = Label(); val bad = Label()
            // if (from < 0 || from > to || to > n) panic
            m.visitVarInsn(LLOAD, 1); m.visitInsn(LCONST_0); m.visitInsn(LCMP); m.visitJumpInsn(IFLT, bad)
            m.visitVarInsn(LLOAD, 1); m.visitVarInsn(LLOAD, 3); m.visitInsn(LCMP); m.visitJumpInsn(IFGT, bad)
            m.visitVarInsn(LLOAD, 3); m.visitVarInsn(ILOAD, 5); m.visitInsn(I2L); m.visitInsn(LCMP); m.visitJumpInsn(IFGT, bad)
            m.visitJumpInsn(GOTO, ok)
            m.visitLabel(bad)
            m.visitTypeInsn(NEW, PANIC_CLASS); m.visitInsn(DUP)
            m.visitLdcInsn("substring: index out of range")
            m.visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
            m.visitInsn(ATHROW)
            m.visitLabel(ok)
            m.visitVarInsn(ALOAD, 0)
            m.visitVarInsn(ALOAD, 0); m.visitInsn(ICONST_0); m.visitVarInsn(LLOAD, 1); m.visitInsn(L2I)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "offsetByCodePoints", "(II)I", false)
            m.visitVarInsn(ALOAD, 0); m.visitInsn(ICONST_0); m.visitVarInsn(LLOAD, 3); m.visitInsn(L2I)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "offsetByCodePoints", "(II)I", false)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "substring", "(II)L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0); m.visitEnd()
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

        // javaTry(Fn0) -> Result: the interop exception barrier (spec §9.8). Catches
        // java.lang.Exception only — dawn.rt.PanicError extends Error and stays fatal.
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "javaTry", "(L${fnIface(0)};)LResult;", null, null)
            m.visitCode()
            val tryStart = Label()
            val tryEnd = Label()
            val handler = Label()
            m.visitTryCatchBlock(tryStart, tryEnd, handler, "java/lang/Exception")
            m.visitLabel(tryStart)
            m.visitTypeInsn(NEW, "Result\$Ok")
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEINTERFACE, fnIface(0), "apply", erasedApplyDesc(0), true)
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
            // write_file creates missing parent directories (spec §11)
            m.visitVarInsn(ASTORE, 3)
            m.visitVarInsn(ALOAD, 3)
            m.visitMethodInsn(INVOKEINTERFACE, PATH, "getParent", "()L$PATH;", true)
            m.visitVarInsn(ASTORE, 4)
            val noParent = Label()
            m.visitVarInsn(ALOAD, 4)
            m.visitJumpInsn(IFNULL, noParent)
            m.visitVarInsn(ALOAD, 4)
            m.visitInsn(ICONST_0)
            m.visitTypeInsn(ANEWARRAY, "java/nio/file/attribute/FileAttribute")
            m.visitMethodInsn(INVOKESTATIC, FILES, "createDirectories",
                "(L$PATH;[Ljava/nio/file/attribute/FileAttribute;)L$PATH;", false)
            m.visitInsn(POP)
            m.visitLabel(noParent)
            m.visitVarInsn(ALOAD, 3)
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

        // listDir: sorted entry names, Err when the path is not a directory
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "listDir", "(L$STR;)LResult;", null, null)
            m.visitCode()
            val tryStart = Label()
            val tryEnd = Label()
            val handler = Label()
            val haveNames = Label()
            m.visitTryCatchBlock(tryStart, tryEnd, handler, "java/lang/Exception")
            m.visitLabel(tryStart)
            m.visitTypeInsn(NEW, "java/io/File")
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKESPECIAL, "java/io/File", "<init>", "(L$STR;)V", false)
            m.visitMethodInsn(INVOKEVIRTUAL, "java/io/File", "list", "()[L$STR;", false)
            m.visitVarInsn(ASTORE, 1)
            m.visitVarInsn(ALOAD, 1)
            m.visitJumpInsn(IFNONNULL, haveNames)
            m.visitTypeInsn(NEW, "Result\$Err")
            m.visitInsn(DUP)
            m.visitLdcInsn("not a directory: ")
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEVIRTUAL, STR, "concat", "(L$STR;)L$STR;", false)
            m.visitMethodInsn(INVOKESPECIAL, "Result\$Err", "<init>", "(L$OBJ;)V", false)
            m.visitInsn(ARETURN)
            m.visitLabel(haveNames)
            m.visitVarInsn(ALOAD, 1)
            m.visitMethodInsn(INVOKESTATIC, "java/util/Arrays", "sort", "([L$OBJ;)V", false)
            m.visitTypeInsn(NEW, "Result\$Ok")
            m.visitInsn(DUP)
            m.visitTypeInsn(NEW, ARRAYLIST)
            m.visitInsn(DUP)
            m.visitVarInsn(ALOAD, 1)
            m.visitMethodInsn(INVOKESTATIC, "java/util/Arrays", "asList",
                "([L$OBJ;)Ljava/util/List;", false)
            m.visitMethodInsn(INVOKESPECIAL, ARRAYLIST, "<init>", "(Ljava/util/Collection;)V", false)
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

        // isDir: false for missing paths and on any path error
        run {
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "isDir", "(L$STR;)Z", null, null)
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
            m.visitInsn(ICONST_0)
            m.visitTypeInsn(ANEWARRAY, "java/nio/file/LinkOption")
            m.visitMethodInsn(INVOKESTATIC, FILES, "isDirectory",
                "(L$PATH;[Ljava/nio/file/LinkOption;)Z", false)
            m.visitLabel(tryEnd)
            m.visitInsn(IRETURN)
            m.visitLabel(handler)
            m.visitInsn(POP)
            m.visitInsn(ICONST_0)
            m.visitInsn(IRETURN)
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
            // if (o instanceof java.util.Map) return showMap((Map) o);
            val notMap = Label()
            m.visitVarInsn(ALOAD, 0)
            m.visitTypeInsn(INSTANCEOF, JMAP)
            m.visitJumpInsn(IFEQ, notMap)
            m.visitVarInsn(ALOAD, 0)
            m.visitTypeInsn(CHECKCAST, JMAP)
            m.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "showMap", "(L$JMAP;)L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitLabel(notMap)
            // if (o instanceof java.util.Set) return showSet((Set) o);
            val notSet = Label()
            m.visitVarInsn(ALOAD, 0)
            m.visitTypeInsn(INSTANCEOF, JSET)
            m.visitJumpInsn(IFEQ, notSet)
            m.visitVarInsn(ALOAD, 0)
            m.visitTypeInsn(CHECKCAST, JSET)
            m.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "showSet", "(L$JSET;)L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitLabel(notSet)
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

        // static String showMap(Map m): "map_from([(k, v), ...])" (spec §2.2 Show shape)
        run {
            val ITER = "java/util/Iterator"
            val ENTRY = "java/util/Map\$Entry"
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "showMap", "(L$JMAP;)L$STR;", null, null)
            m.visitCode()
            m.visitTypeInsn(NEW, SB); m.visitInsn(DUP)
            m.visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
            m.visitVarInsn(ASTORE, 1)
            m.visitVarInsn(ALOAD, 1); appendConst(m, "map_from(["); m.visitInsn(POP)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEINTERFACE, JMAP, "entrySet", "()L$JSET;", true)
            m.visitMethodInsn(INVOKEINTERFACE, JSET, "iterator", "()L$ITER;", true)
            m.visitVarInsn(ASTORE, 2)
            m.visitInsn(ICONST_0); m.visitVarInsn(ISTORE, 3)
            val loop = Label(); val done = Label(); val noComma = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ALOAD, 2); m.visitMethodInsn(INVOKEINTERFACE, ITER, "hasNext", "()Z", true)
            m.visitJumpInsn(IFEQ, done)
            m.visitVarInsn(ALOAD, 2); m.visitMethodInsn(INVOKEINTERFACE, ITER, "next", "()L$OBJ;", true)
            m.visitTypeInsn(CHECKCAST, ENTRY); m.visitVarInsn(ASTORE, 4)
            m.visitVarInsn(ILOAD, 3); m.visitJumpInsn(IFEQ, noComma)
            m.visitVarInsn(ALOAD, 1); appendConst(m, ", "); m.visitInsn(POP)
            m.visitLabel(noComma)
            m.visitVarInsn(ALOAD, 1); appendConst(m, "("); m.visitInsn(POP)
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ALOAD, 4); m.visitMethodInsn(INVOKEINTERFACE, ENTRY, "getKey", "()L$OBJ;", true)
            m.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "show", "(L$OBJ;)L$STR;", false)
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(L$STR;)L$SB;", false); m.visitInsn(POP)
            m.visitVarInsn(ALOAD, 1); appendConst(m, ", "); m.visitInsn(POP)
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ALOAD, 4); m.visitMethodInsn(INVOKEINTERFACE, ENTRY, "getValue", "()L$OBJ;", true)
            m.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "show", "(L$OBJ;)L$STR;", false)
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(L$STR;)L$SB;", false); m.visitInsn(POP)
            m.visitVarInsn(ALOAD, 1); appendConst(m, ")"); m.visitInsn(POP)
            m.visitIincInsn(3, 1)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(done)
            m.visitVarInsn(ALOAD, 1); appendConst(m, "])")
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0); m.visitEnd()
        }

        // static String showSet(Set s): "set_from([e0, e1, ...])"
        run {
            val ITER = "java/util/Iterator"
            val m = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "showSet", "(L$JSET;)L$STR;", null, null)
            m.visitCode()
            m.visitTypeInsn(NEW, SB); m.visitInsn(DUP)
            m.visitMethodInsn(INVOKESPECIAL, SB, "<init>", "()V", false)
            m.visitVarInsn(ASTORE, 1)
            m.visitVarInsn(ALOAD, 1); appendConst(m, "set_from(["); m.visitInsn(POP)
            m.visitVarInsn(ALOAD, 0)
            m.visitMethodInsn(INVOKEINTERFACE, JSET, "iterator", "()L$ITER;", true)
            m.visitVarInsn(ASTORE, 2)
            m.visitInsn(ICONST_0); m.visitVarInsn(ISTORE, 3)
            val loop = Label(); val done = Label(); val noComma = Label()
            m.visitLabel(loop)
            m.visitVarInsn(ALOAD, 2); m.visitMethodInsn(INVOKEINTERFACE, ITER, "hasNext", "()Z", true)
            m.visitJumpInsn(IFEQ, done)
            m.visitVarInsn(ALOAD, 2); m.visitMethodInsn(INVOKEINTERFACE, ITER, "next", "()L$OBJ;", true)
            m.visitVarInsn(ASTORE, 4)
            m.visitVarInsn(ILOAD, 3); m.visitJumpInsn(IFEQ, noComma)
            m.visitVarInsn(ALOAD, 1); appendConst(m, ", "); m.visitInsn(POP)
            m.visitLabel(noComma)
            m.visitVarInsn(ALOAD, 1)
            m.visitVarInsn(ALOAD, 4)
            m.visitMethodInsn(INVOKESTATIC, SHOW_CLASS, "show", "(L$OBJ;)L$STR;", false)
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "append", "(L$STR;)L$SB;", false); m.visitInsn(POP)
            m.visitIincInsn(3, 1)
            m.visitJumpInsn(GOTO, loop)
            m.visitLabel(done)
            m.visitVarInsn(ALOAD, 1); appendConst(m, "])")
            m.visitMethodInsn(INVOKEVIRTUAL, SB, "toString", "()L$STR;", false)
            m.visitInsn(ARETURN)
            m.visitMaxs(0, 0); m.visitEnd()
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
        is LocalFnStmt -> {
            genLambdaValue(s.lambda, selfSym = s.symbol)
            val sym = s.symbol!!
            sym.slot = nextSlot
            nextSlot += slotsOf(sym.type)
            storeVar(sym)
            true
        }
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
            when {
                fv != null -> genFnValue(e, fv)
                e.symbol === selfPending?.selfSym -> emitSelfClosure()
                else -> loadVar(e.symbol!!)
            }
            true
        }
        is MethodCall -> when {
            e.javaCtorRef != null -> genJavaNew(e)
            e.javaMethod != null -> genJavaCall(e)
            else -> genExpr(e.desugared!!, tail)
        }
        is Lambda -> genLambdaValue(e)
        is Propagate -> genPropagate(e)
        is Return -> {
            val v = e.value
            if (v == null || genExpr(v, tail = false)) {
                if (v != null) adaptTo(v.type!!, methodRet)
                emitMethodReturn()
            }
            false
        }
        is Index -> {
            genExpr(e.target, tail = false)
            genExpr(e.index, tail = false)
            if (e.target.type is TList) {
                mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "index", "(L$JLIST;J)L$OBJ;", false)
            } else {
                box(e.index.type!!) // map keys travel erased
                mv.visitMethodInsn(INVOKESTATIC, MAPS_CLASS, "index", "(L$JMAP;L$OBJ;)L$OBJ;", false)
            }
            if (slotsOf(e.type!!) == 0) mv.visitInsn(POP) else unerase(e.type!!)
            true
        }
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
    private fun genLambdaValue(e: Lambda, selfSym: Symbol? = null): Boolean {
        val name = "dawn\$lambda\$${lambdaCounter++}"
        pendingLambdas.add(PendingLambda(e, name, selfSym))
        emitClosure(e, name)
        return true
    }

    /** the invokedynamic that captures the environment and yields the closure object */
    private fun emitClosure(e: Lambda, name: String) {
        val caps = e.captures!!
        // a capture of the local function being generated cannot be loaded (no slot
        // holds it inside its own impl) — rebuild an identical closure instead
        for (c in caps) if (c === selfPending?.selfSym) emitSelfClosure() else loadVar(c)
        val ft = e.fnType!!
        val implDesc = implDescOf(caps.map { it.type } + ft.params, ft.ret)
        val indyDesc = "(" + caps.joinToString("") { descOf(it.type) } + ")L${fnIface(ft.params.size)};"
        mv.visitInvokeDynamicInsn(
            "apply", indyDesc, LMF_BSM,
            AsmType.getMethodType(erasedApplyDesc(ft.params.size)),
            Handle(H_INVOKESTATIC, className, name, implDesc, false),
            instantiatedType(ft.params, ft.ret),
        )
    }

    /** a local function used as a value inside its own body: rebuild the closure */
    private fun emitSelfClosure() {
        val p = selfPending!!
        emitClosure(p.lambda, p.name)
    }

    private fun drainLambdas(cw: ClassWriter) {
        while (pendingLambdas.isNotEmpty() || pendingBridges.isNotEmpty() ||
            pendingBuiltinBridges.isNotEmpty() || pendingCtorBridges.isNotEmpty() ||
            pendingSamBridges.isNotEmpty()) {
            when {
                pendingLambdas.isNotEmpty() -> genLambdaImpl(cw, pendingLambdas.removeFirst())
                pendingBridges.isNotEmpty() ->
                    genFnValueBridge(cw, pendingBridges.first().also { pendingBridges.remove(it) })
                pendingBuiltinBridges.isNotEmpty() ->
                    genBuiltinBridge(cw, pendingBuiltinBridges.first().also { pendingBuiltinBridges.remove(it) })
                pendingCtorBridges.isNotEmpty() ->
                    genCtorValueBridge(cw, pendingCtorBridges.first().also { pendingCtorBridges.remove(it) })
                else -> genSamBridge(cw, pendingSamBridges.removeFirst())
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
                Handle(H_INVOKESTATIC, className, "dawn\$fnval\$${fnValBridgeName(fv)}",
                    implDescOf(fv.paramTypes, fv.ret), false)
            } else {
                Handle(H_INVOKESTATIC, fv.owner ?: className, fv.name,
                    methodDesc(fv.paramTypes, fv.ret), false)
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
        "sort_by" -> Handle(H_INVOKESTATIC, LISTS_CLASS, "sortBy", "(L$JLIST;L${fnIface(2)};)L$JLIST;", false)
        "fold" -> Handle(H_INVOKESTATIC, LISTS_CLASS, "fold", "(L$JLIST;L$OBJ;L${fnIface(2)};)L$OBJ;", false)
        "chars" -> Handle(H_INVOKESTATIC, STRINGS_CLASS, "chars", "(Ljava/lang/String;)L$JLIST;", false)
        "join" -> Handle(H_INVOKESTATIC, STRINGS_CLASS, "join", "(L$JLIST;Ljava/lang/String;)Ljava/lang/String;", false)
        "split" -> Handle(H_INVOKESTATIC, STRINGS_CLASS, "split",
            "(Ljava/lang/String;Ljava/lang/String;)L$JLIST;", false)
        "parse_int" -> Handle(H_INVOKESTATIC, STRINGS_CLASS, "parseInt", "(Ljava/lang/String;)LOption;", false)
        "parse_float" -> Handle(H_INVOKESTATIC, STRINGS_CLASS, "parseFloat", "(Ljava/lang/String;)LOption;", false)
        "java_try" -> Handle(H_INVOKESTATIC, IO_CLASS, "javaTry", "(L${fnIface(0)};)LResult;", false)
        "read_file" -> Handle(H_INVOKESTATIC, IO_CLASS, "readFile", "(Ljava/lang/String;)LResult;", false)
        "write_file" -> Handle(H_INVOKESTATIC, IO_CLASS, "writeFile",
            "(Ljava/lang/String;Ljava/lang/String;)LResult;", false)
        "read_line" -> Handle(H_INVOKESTATIC, IO_CLASS, "readLine", "()LOption;", false)
        "list_dir" -> Handle(H_INVOKESTATIC, IO_CLASS, "listDir", "(Ljava/lang/String;)LResult;", false)
        "is_dir" -> Handle(H_INVOKESTATIC, IO_CLASS, "isDir", "(Ljava/lang/String;)Z", false)
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
        currentFn = null // no self-name inside a lambda, so no top-level tail-call rewrite
        nextSlot = 0
        methodRet = ft.ret
        methodRetsNull = true
        selfPending = if (p.selfSym != null) p else null
        for (sym in caps) {
            sym.slot = nextSlot
            nextSlot += slotsOf(sym.type)
        }
        for (lp in l.params) {
            val sym = lp.symbol!!
            sym.slot = nextSlot
            nextSlot += slotsOf(sym.type)
        }
        // a local function's impl is a named function: self tail calls become a loop
        fnStart = if (p.selfSym != null) Label().also { mv.visitLabel(it) } else null
        val falls = genExpr(l.body, tail = p.selfSym != null)
        if (falls) emitMethodReturn()
        mv.visitMaxs(0, 0)
        mv.visitEnd()
    }

    private val emittedBridges = HashSet<String>()

    /** bridge for a Unit-returning top-level function used as a value: call it, return null */
    /** bridge name for a Unit-returning fn value; namespaced by owner so imports don't collide */
    private fun fnValBridgeName(sig: FnSig) =
        if (sig.owner == null || sig.owner == className) sig.name else "${sig.owner!!.replace('/', '$')}\$${sig.name}"

    private fun genFnValueBridge(cw: ClassWriter, sig: FnSig) {
        val bridge = fnValBridgeName(sig)
        if (!emittedBridges.add(bridge)) return
        val m = cw.visitMethod(
            ACC_PRIVATE or ACC_STATIC or ACC_SYNTHETIC, "dawn\$fnval\$$bridge",
            implDescOf(sig.paramTypes, sig.ret), null, null,
        )
        m.visitCode()
        var slot = 0
        for (pt in sig.paramTypes) {
            loadSlot(m, pt, slot)
            slot += slotsOf(pt)
        }
        m.visitMethodInsn(INVOKESTATIC, sig.owner ?: className, sig.name, methodDesc(sig.paramTypes, sig.ret), false)
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
        for ((i, arg) in e.args.withIndex()) {
            if (!genExpr(arg, tail = false)) return false
            val conv = e.samConvs?.get(i)
            when {
                conv != null -> emitSamConversion(conv, arg.type as TFn)
                e.listBridges?.contains(i) == true -> emitListBridge()
                else -> adaptJavaArg(arg.type!!, ctor.parameterTypes[i])
            }
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
        for ((i, arg) in e.args.withIndex()) {
            if (!genExpr(arg, tail = false)) return false
            val conv = e.samConvs?.get(i)
            when {
                conv != null -> emitSamConversion(conv, arg.type as TFn)
                e.listBridges?.contains(i) == true -> emitListBridge()
                else -> adaptJavaArg(arg.type!!, m.parameterTypes[i])
            }
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

    /**
     * A Dawn List on the stack (already a java.util.List at runtime) → the
     * zero-copy unmodifiable view handed to Java (spec §9.6): mutators throw,
     * the Dawn value stays a value.
     */
    private fun emitListBridge() {
        mv.visitMethodInsn(INVOKESTATIC, "java/util/Collections", "unmodifiableList",
            "(Ljava/util/List;)Ljava/util/List;", false)
    }

    /** A Dawn fn value on the stack → an instance of the target functional interface (spec §9.4). */
    private fun emitSamConversion(conv: SamConv, ft: TFn) {
        val n = ft.params.size
        val bridge = "dawn\$sam\$${samBridgeCounter++}"
        pendingSamBridges.add(SamBridge(bridge, conv))
        val samType = AsmType.getMethodType(AsmType.getMethodDescriptor(conv.sam))
        val bridgeDesc = "(L${fnIface(n)};" +
            conv.sam.parameterTypes.joinToString("") { AsmType.getDescriptor(it) } +
            ")" + AsmType.getDescriptor(conv.sam.returnType)
        mv.visitInvokeDynamicInsn(
            conv.sam.name, "(L${fnIface(n)};)${AsmType.getDescriptor(conv.iface)}", LMF_BSM,
            samType,
            Handle(H_INVOKESTATIC, className, bridge, bridgeDesc, false),
            samType,
        )
    }

    /**
     * static <samRet> dawn$sam$N(FnN f, <sam params>): the body behind a SAM
     * conversion (spec §9.4). Null-checks reference parameters (Java must not
     * pass null into Dawn), boxes to the erased Fn calling convention, invokes,
     * and adapts the result (checked narrowing when the SAM wants an int).
     */
    private fun genSamBridge(cw: ClassWriter, b: SamBridge) {
        val sam = b.conv.sam
        val params = sam.parameterTypes
        val n = params.size
        val desc = "(L${fnIface(n)};" + params.joinToString("") { AsmType.getDescriptor(it) } +
            ")" + AsmType.getDescriptor(sam.returnType)
        val m = cw.visitMethod(ACC_PRIVATE or ACC_STATIC or ACC_SYNTHETIC, b.name, desc, null, null)
        fun panic(msg: String) {
            m.visitTypeInsn(NEW, PANIC_CLASS)
            m.visitInsn(DUP)
            m.visitLdcInsn(msg)
            m.visitMethodInsn(INVOKESPECIAL, PANIC_CLASS, "<init>", "(Ljava/lang/String;)V", false)
            m.visitInsn(ATHROW)
        }
        m.visitCode()
        m.visitVarInsn(ALOAD, 0)
        var slot = 1
        for ((i, p) in params.withIndex()) {
            when (p) {
                java.lang.Long.TYPE -> {
                    m.visitVarInsn(LLOAD, slot); slot += 2
                    m.visitMethodInsn(INVOKESTATIC, "java/lang/Long", "valueOf", "(J)Ljava/lang/Long;", false)
                }
                Integer.TYPE, java.lang.Short.TYPE, java.lang.Byte.TYPE -> {
                    m.visitVarInsn(ILOAD, slot); slot += 1
                    m.visitInsn(I2L)
                    m.visitMethodInsn(INVOKESTATIC, "java/lang/Long", "valueOf", "(J)Ljava/lang/Long;", false)
                }
                java.lang.Double.TYPE -> {
                    m.visitVarInsn(DLOAD, slot); slot += 2
                    m.visitMethodInsn(INVOKESTATIC, "java/lang/Double", "valueOf", "(D)Ljava/lang/Double;", false)
                }
                java.lang.Float.TYPE -> {
                    m.visitVarInsn(FLOAD, slot); slot += 1
                    m.visitInsn(F2D)
                    m.visitMethodInsn(INVOKESTATIC, "java/lang/Double", "valueOf", "(D)Ljava/lang/Double;", false)
                }
                java.lang.Boolean.TYPE -> {
                    m.visitVarInsn(ILOAD, slot); slot += 1
                    m.visitMethodInsn(INVOKESTATIC, "java/lang/Boolean", "valueOf", "(Z)Ljava/lang/Boolean;", false)
                }
                else -> { // reference: null must not enter Dawn — panic at the boundary
                    m.visitVarInsn(ALOAD, slot); slot += 1
                    val ok = Label()
                    m.visitInsn(DUP)
                    m.visitJumpInsn(IFNONNULL, ok)
                    panic("Java passed null to parameter ${i + 1} of a Dawn callback (${b.conv.iface.name})")
                    m.visitLabel(ok)
                }
            }
        }
        m.visitMethodInsn(INVOKEINTERFACE, fnIface(n), "apply", erasedApplyDesc(n), true)
        when (sam.returnType) {
            java.lang.Void.TYPE -> {
                m.visitInsn(POP)
                m.visitInsn(RETURN)
            }
            java.lang.Long.TYPE -> {
                m.visitTypeInsn(CHECKCAST, "java/lang/Long")
                m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Long", "longValue", "()J", false)
                m.visitInsn(LRETURN)
            }
            Integer.TYPE, java.lang.Short.TYPE, java.lang.Byte.TYPE -> {
                m.visitTypeInsn(CHECKCAST, "java/lang/Long")
                m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Long", "longValue", "()J", false)
                // checked narrowing (spec §9.4): the l2i;i2l roundtrip must be identity
                val tmp = slot
                m.visitVarInsn(LSTORE, tmp)
                val ok = Label()
                m.visitVarInsn(LLOAD, tmp)
                m.visitInsn(L2I)
                m.visitInsn(I2L)
                m.visitVarInsn(LLOAD, tmp)
                m.visitInsn(LCMP)
                m.visitJumpInsn(IFEQ, ok)
                panic("Dawn callback returned an Int outside Java int range")
                m.visitLabel(ok)
                m.visitVarInsn(LLOAD, tmp)
                m.visitInsn(L2I)
                m.visitInsn(IRETURN)
            }
            java.lang.Boolean.TYPE -> {
                m.visitTypeInsn(CHECKCAST, "java/lang/Boolean")
                m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Boolean", "booleanValue", "()Z", false)
                m.visitInsn(IRETURN)
            }
            java.lang.Double.TYPE -> {
                m.visitTypeInsn(CHECKCAST, "java/lang/Double")
                m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Double", "doubleValue", "()D", false)
                m.visitInsn(DRETURN)
            }
            java.lang.Float.TYPE -> {
                m.visitTypeInsn(CHECKCAST, "java/lang/Double")
                m.visitMethodInsn(INVOKEVIRTUAL, "java/lang/Double", "doubleValue", "()D", false)
                m.visitInsn(D2F)
                m.visitInsn(FRETURN)
            }
            else -> {
                m.visitTypeInsn(CHECKCAST, AsmType.getInternalName(sam.returnType))
                m.visitInsn(ARETURN)
            }
        }
        m.visitMaxs(0, 0)
        m.visitEnd()
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
            val p = selfPending
            if (p != null && dyn === p.selfSym) {
                // a local function calling itself: skip the closure object entirely
                val ft = p.lambda.fnType!!
                if (tail) { // spec §12.4: self tail call → write back + goto entry
                    for ((a, pt) in e.args.zip(ft.params)) {
                        genExpr(a, tail = false)
                        adaptTo(a.type!!, pt)
                    }
                    for (lp in p.lambda.params.reversed()) {
                        val sym = lp.symbol!!
                        if (slotsOf(sym.type) > 0) storeVar(sym)
                    }
                    mv.visitJumpInsn(GOTO, fnStart!!)
                    return false
                }
                val caps = p.lambda.captures!!
                for (c in caps) loadVar(c) // impl params, forwarded unchanged
                for ((a, pt) in e.args.zip(ft.params)) {
                    genExpr(a, tail = false)
                    adaptTo(a.type!!, pt)
                }
                mv.visitMethodInsn(INVOKESTATIC, className, p.name,
                    implDescOf(caps.map { it.type } + ft.params, ft.ret), false)
                adaptFrom(ft.ret, e.type!!)
                return true
            }
            loadVar(dyn)
            return genDynamicInvoke(e.args, dyn.type as TFn, e.type!!)
        }
        val builtin = BUILTINS[e.callee]
        if (builtin != null) return genBuiltinCall(e)

        val self = currentFn
        val sig = e.sig!!
        if (sig.trait != null) return genTraitMethodCall(e, sig)
        // self-recursive tail call → write args back to param slots + goto entry (spec §12.4);
        // an imported function of the same name (different owner) is not self-recursion
        val ownerClass = sig.owner ?: className
        if (tail && self != null && e.callee == self.name && ownerClass == className) {
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
        e.witnesses?.forEach { pushWitness(it) }
        mv.visitMethodInsn(INVOKESTATIC, ownerClass, e.callee, fnDescWithDicts(sig), false)
        adaptFrom(sig.ret, e.type!!)
        return true
    }

    /** push one dictionary: the impl singleton, or the caller's own dict local/capture */
    private fun pushWitness(w: WitnessRef) {
        when (w) {
            is WitnessRef.Concrete ->
                mv.visitFieldInsn(GETSTATIC, implClass(w.impl), "INSTANCE", "L${trIface(w.impl.trait)};")
            is WitnessRef.Forward -> loadVar(w.sym)
        }
    }

    /**
     * A trait method call. Concrete witness → devirtualize: the impl's static
     * (or the prelude comparison, or the trait's default static with the impl's
     * dictionary). Forward witness → invokeinterface on the caller's dictionary.
     */
    private fun genTraitMethodCall(e: Call, sig: FnSig): Boolean {
        val trait = sig.trait!!
        when (val w = e.witnesses!!.single()) {
            is WitnessRef.Concrete -> {
                val impl = w.impl
                val provided = impl.provided[e.callee]
                when {
                    impl.derived -> {
                        for (a in e.args) genExpr(a, tail = false) // concrete subject args
                        mv.visitMethodInsn(INVOKESTATIC, impl.owner ?: className,
                            implMethodName(impl, e.callee), derivedCmpDesc(impl), false)
                    }
                    provided != null -> {
                        val psig = provided.sig!!
                        for ((a, pt) in e.args.zip(psig.paramTypes)) {
                            genExpr(a, tail = false)
                            adaptTo(a.type!!, pt)
                        }
                        mv.visitMethodInsn(INVOKESTATIC, psig.owner ?: className,
                            implMethodName(impl, e.callee), methodDesc(psig.paramTypes, psig.ret), false)
                        adaptFrom(psig.ret, e.type!!)
                    }
                    trait === ORD_TRAIT && impl.subject !is TAdt -> {
                        // prelude scalar cmp, inlined
                        for (a in e.args) genExpr(a, tail = false)
                        emitNativeCmp(impl.subject)
                    }
                    else -> {
                        // only a default body exists: its static, with the impl's dictionary
                        for ((a, pt) in e.args.zip(sig.paramTypes)) {
                            genExpr(a, tail = false)
                            adaptTo(a.type!!, pt)
                        }
                        mv.visitFieldInsn(GETSTATIC, implClass(impl), "INSTANCE", "L${trIface(trait)};")
                        mv.visitMethodInsn(INVOKESTATIC, trait.owner ?: className,
                            defaultMethodName(trait, e.callee), fnDescWithDicts(sig), false)
                        adaptFrom(sig.ret, e.type!!)
                    }
                }
            }
            is WitnessRef.Forward -> {
                loadVar(w.sym)
                mv.visitTypeInsn(CHECKCAST, trIface(trait))
                for ((a, pt) in e.args.zip(sig.paramTypes)) {
                    genExpr(a, tail = false)
                    adaptTo(a.type!!, pt)
                }
                mv.visitMethodInsn(INVOKEINTERFACE, trIface(trait), e.callee, traitMethodDesc(sig), true)
                adaptFrom(sig.ret, e.type!!)
            }
        }
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
        val handle = Handle(H_INVOKESTATIC, className, ctorBridgeName(ci),
            implDescOf(ci.fields.map { it.type }, ci.adt.type), false)
        mv.visitInvokeDynamicInsn(
            "apply", "()L${fnIface(ft.params.size)};", LMF_BSM,
            AsmType.getMethodType(erasedApplyDesc(ft.params.size)),
            handle,
            instantiatedType(ft.params, ft.ret),
        )
        return true
    }

    /** the bridge method name for a constructor value; '/' from a module prefix is not legal in method names */
    private fun ctorBridgeName(ci: CtorInfo) = "dawn\$ctor\$" + ci.jvmName.replace('/', '$')

    /** static body `dawn$ctor$X(fields...) -> Adt` = new + init, target of a constructor value's LMF */
    private fun genCtorValueBridge(cw: ClassWriter, ci: CtorInfo) {
        val sub = ci.jvmName
        if (!emittedCtorBridges.add(ctorBridgeName(ci))) return
        val fieldTypes = ci.fields.map { it.type }
        val m = cw.visitMethod(
            ACC_PRIVATE or ACC_STATIC or ACC_SYNTHETIC, ctorBridgeName(ci),
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
        "sort" -> {
            genExpr(e.args[0], tail = false)
            pushWitness(e.witnesses!!.single())
            mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "sort", "(L$JLIST;L$OBJ;)L$JLIST;", false)
            true
        }
        "sort_by" -> {
            genExpr(e.args[0], tail = false)
            genExpr(e.args[1], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "sortBy",
                "(L$JLIST;L${fnIface(2)};)L$JLIST;", false)
            true
        }
        "max", "min" -> {
            genExpr(e.args[0], tail = false)
            pushWitness(e.witnesses!!.single())
            mv.visitInsn(if (e.callee == "max") ICONST_1 else ICONST_M1)
            mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "best", "(L$JLIST;L$OBJ;I)LOption;", false)
            true
        }
        "max_by", "min_by" -> {
            genExpr(e.args[0], tail = false)
            genExpr(e.args[1], tail = false)
            pushWitness(e.witnesses!!.single())
            mv.visitInsn(if (e.callee == "max_by") ICONST_1 else ICONST_M1)
            mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "bestBy",
                "(L$JLIST;L${fnIface(1)};L$OBJ;I)LOption;", false)
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
        "java_try" -> {
            genExpr(e.args[0], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, IO_CLASS, "javaTry", "(L${fnIface(0)};)LResult;", false)
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
        "list_dir" -> {
            genExpr(e.args[0], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, IO_CLASS, "listDir", "(Ljava/lang/String;)LResult;", false)
            true
        }
        "is_dir" -> {
            genExpr(e.args[0], tail = false)
            mv.visitMethodInsn(INVOKESTATIC, IO_CLASS, "isDir", "(Ljava/lang/String;)Z", false)
            true
        }
        "args" -> {
            mv.visitFieldInsn(GETSTATIC, className, ARGS_FIELD, "[Ljava/lang/String;")
            mv.visitMethodInsn(INVOKESTATIC, LISTS_CLASS, "fromArray", "([Ljava/lang/String;)L$JLIST;", false)
            true
        }
        "code_points", "from_code_points", "char_to_string", "str_len", "substring" -> {
            for (a in e.args) genExpr(a, tail = false)
            val sig = BUILTINS.getValue(e.callee)
            mv.visitMethodInsn(INVOKESTATIC, STRINGS_CLASS, e.callee, methodDesc(sig.paramTypes, sig.ret), false)
            true
        }
        in MAP_BUILTINS -> genMapCall(e)
        else -> error("unknown builtin: ${e.callee}")
    }

    /** the Map/Set builtins all live in dawn/rt/Maps; keys/values travel erased (boxed). */
    private fun genMapCall(e: Call): Boolean {
        val sig = BUILTINS.getValue(e.callee)
        for (a in e.args) {
            genExpr(a, tail = false)
            box(a.type!!) // scalars box to Object; containers are already references (no-op)
        }
        mv.visitMethodInsn(INVOKESTATIC, MAPS_CLASS, e.callee, methodDesc(sig.paramTypes, sig.ret), false)
        return true
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
        if (e.ordWitness != null) return genTraitOrdering(e)

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

    /** `< <= > >=` through an Ord impl: cmp(l, r), then compare the long result to 0. */
    private fun genTraitOrdering(e: Binary): Boolean {
        val ordCmp = ORD_TRAIT.methods.getValue("cmp").sig
        when (val w = e.ordWitness!!) {
            is WitnessRef.Concrete -> {
                val provided = w.impl.provided["cmp"]
                if (w.impl.derived) {
                    genExpr(e.left, tail = false)
                    genExpr(e.right, tail = false)
                    mv.visitMethodInsn(INVOKESTATIC, w.impl.owner ?: className,
                        implMethodName(w.impl, "cmp"), derivedCmpDesc(w.impl), false)
                } else if (provided != null) {
                    genExpr(e.left, tail = false)
                    genExpr(e.right, tail = false)
                    val psig = provided.sig!!
                    mv.visitMethodInsn(INVOKESTATIC, psig.owner ?: className,
                        implMethodName(w.impl, "cmp"), methodDesc(psig.paramTypes, psig.ret), false)
                } else {
                    // cmp came from a default body (future-proof: Ord has none today)
                    genExpr(e.left, tail = false)
                    genExpr(e.right, tail = false)
                    mv.visitFieldInsn(GETSTATIC, implClass(w.impl), "INSTANCE", "L${trIface(ORD_TRAIT)};")
                    mv.visitMethodInsn(INVOKESTATIC, ORD_TRAIT.owner ?: className,
                        defaultMethodName(ORD_TRAIT, "cmp"), fnDescWithDicts(ordCmp), false)
                }
            }
            is WitnessRef.Forward -> {
                loadVar(w.sym)
                mv.visitTypeInsn(CHECKCAST, trIface(ORD_TRAIT))
                genExpr(e.left, tail = false) // rigid tvar operands are already erased refs
                genExpr(e.right, tail = false)
                mv.visitMethodInsn(INVOKEINTERFACE, trIface(ORD_TRAIT), "cmp",
                    traitMethodDesc(ordCmp), true)
            }
        }
        mv.visitInsn(LCONST_0)
        mv.visitInsn(LCMP)
        pushCmpResult(when (e.op) {
            BinOp.LT -> IFLT; BinOp.LE -> IFLE; BinOp.GT -> IFGT; else -> IFGE
        })
        return true
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
