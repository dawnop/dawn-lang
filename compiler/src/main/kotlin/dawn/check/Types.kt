package dawn.check

import dawn.diag.Span

/** The complete set of types. */
sealed class Type(val display: String) {
    object TInt : Type("Int")
    object TFloat : Type("Float")
    object TBool : Type("Bool")
    object TString : Type("String")
    object TUnit : Type("Unit")

    /** Bottom type: the "return type" of panic/todo; usable as any type */
    object TNever : Type("Never")

    /**
     * Error type: produced where checking failed (alongside a diagnostic).
     * Compatible with everything and never reported again — stops one error
     * from cascading into a dozen follow-ups.
     */
    object TError : Type("?")

    /** A type variable, introduced by [T, U] on a declaration. Identity equality. */
    class TVar(val name: String) : Type(name)

    /** A user-defined (or prelude) sum type, possibly instantiated: Option[Int]. */
    class TAdt(val info: AdtInfo, val args: List<Type> = emptyList()) :
        Type(if (args.isEmpty()) info.name else "${info.name}[${args.joinToString(", ")}]") {
        override fun equals(other: Any?): Boolean =
            other is TAdt && other.info === info && other.args == args
        override fun hashCode(): Int = info.hashCode() * 31 + args.hashCode()
    }

    /** The builtin immutable list: List[T]. */
    class TList(val elem: Type) : Type("List[$elem]") {
        override fun equals(other: Any?): Boolean = other is TList && other.elem == elem
        override fun hashCode(): Int = elem.hashCode() + 7
    }

    override fun toString() = display

    val isNumeric get() = this == TInt || this == TFloat
    val isErrorish get() = this == TError || this == TNever

    companion object {
        // Deliberately a function, not a companion Map constant: a map initializer
        // can observe nested objects mid-initialization (as null) — the classic
        // JVM class-initialization-order trap.
        fun named(name: String): Type? = when (name) {
            "Int" -> TInt
            "Float" -> TFloat
            "Bool" -> TBool
            "String" -> TString
            "Unit" -> TUnit
            else -> null
        }
    }
}

/** Replace type variables according to [map] (identity lookups). */
fun subst(t: Type, map: Map<Type.TVar, Type>): Type = when (t) {
    is Type.TVar -> map[t] ?: t
    is Type.TAdt -> if (t.args.isEmpty()) t else Type.TAdt(t.info, t.args.map { subst(it, map) })
    is Type.TList -> Type.TList(subst(t.elem, map))
    else -> t
}

/**
 * A user-defined ADT. Built by the checker in two passes: the shell (name +
 * type parameters) first, then constructor field types — so recursive types
 * (Tree[T] = Node(left: Tree[T], ...)) resolve naturally.
 */
class AdtInfo(
    val name: String,
    val nameSpan: Span?,
    val isRecord: Boolean = false,
    val typeParams: List<Type.TVar> = emptyList(),
) {
    val ctors = ArrayList<CtorInfo>()

    /** the declared "self type": Tree[T] inside its own declaration */
    val type: Type.TAdt = Type.TAdt(this, typeParams)

    /** JVM internal name (erased): abstract base class (sum type) or the single final class (record) */
    val jvmName: String get() = name
}

class CtorInfo(val adt: AdtInfo, val name: String, val nameSpan: Span?) {
    val fields = ArrayList<FieldInfo>()

    /** JVM internal name: a final subclass, or the record class itself */
    val jvmName: String get() = if (adt.isRecord) adt.name else "${adt.name}$$name"

    fun render(): String {
        val ret = adt.type.display
        return when {
            adt.isRecord -> "$name { ${fields.joinToString(", ") { "${it.name}: ${it.type}" }} }"
            fields.isEmpty() -> "$name: $ret"
            else -> "$name(${fields.joinToString(", ") { "${it.name}: ${it.type}" }}): $ret"
        }
    }
}

class FieldInfo(val name: String, val type: Type, val defSpan: Span? = null)

/** Resolved local variable/parameter; the checker fills this into the AST, codegen consumes it. */
class Symbol(val name: String, val type: Type, val mutable: Boolean, val defSpan: Span) {
    /** JVM local slot assigned by codegen */
    var slot: Int = -1
}

/** Function signature (shared by user functions and builtins). */
class FnSig(
    val name: String,
    val paramTypes: List<Type>,
    val paramNames: List<String>,
    val ret: Type,
    val io: Boolean,
    val isBuiltin: Boolean,
    val typeParams: List<Type.TVar> = emptyList(),
    /** span of the name in the declaration (go-to-definition); null for builtins */
    val nameSpan: Span? = null,
) {
    fun render(): String {
        val tp = if (typeParams.isEmpty()) "" else "[${typeParams.joinToString(", ")}]"
        val params = paramNames.zip(paramTypes).joinToString(", ") { "${it.first}: ${it.second}" }
        val eff = if (io) " !io" else ""
        return "fn $name$tp($params) -> $ret$eff"
    }
}

// ---- prelude: Option / Result, generic builtins ----
// Top-level vals initialize in file order; nothing here reads a Type object
// before Kotlin has initialized it (see the class-init-order note above).

private fun preludeAdt(name: String, params: List<String>, build: (AdtInfo, List<Type.TVar>) -> Unit): AdtInfo {
    val tvars = params.map { Type.TVar(it) }
    val info = AdtInfo(name, nameSpan = null, isRecord = false, typeParams = tvars)
    build(info, tvars)
    return info
}

val OPTION_ADT: AdtInfo = preludeAdt("Option", listOf("T")) { info, (t) ->
    info.ctors.add(CtorInfo(info, "Some", null).apply { fields.add(FieldInfo("value", t)) })
    info.ctors.add(CtorInfo(info, "None", null))
}

val RESULT_ADT: AdtInfo = preludeAdt("Result", listOf("T", "E")) { info, tv ->
    info.ctors.add(CtorInfo(info, "Ok", null).apply { fields.add(FieldInfo("value", tv[0])) })
    info.ctors.add(CtorInfo(info, "Err", null).apply { fields.add(FieldInfo("error", tv[1])) })
}

val PRELUDE_ADTS: List<AdtInfo> = listOf(OPTION_ADT, RESULT_ADT)

/** Builtin functions (a growing subset of spec §11). */
val BUILTINS: Map<String, FnSig> = run {
    val t = Type.TVar("T")
    listOf(
        FnSig("println", listOf(Type.TString), listOf("s"), Type.TUnit, io = true, isBuiltin = true),
        FnSig("print", listOf(Type.TString), listOf("s"), Type.TUnit, io = true, isBuiltin = true),
        FnSig("panic", listOf(Type.TString), listOf("msg"), Type.TNever, io = false, isBuiltin = true),
        FnSig("todo", listOf(), listOf(), Type.TNever, io = false, isBuiltin = true),
        FnSig("to_float", listOf(Type.TInt), listOf("n"), Type.TFloat, io = false, isBuiltin = true),
        FnSig("to_int", listOf(Type.TFloat), listOf("x"), Type.TInt, io = false, isBuiltin = true),
        FnSig("len", listOf(Type.TList(t)), listOf("xs"), Type.TInt,
            io = false, isBuiltin = true, typeParams = listOf(t)),
        FnSig("get", listOf(Type.TList(t), Type.TInt), listOf("xs", "i"),
            Type.TAdt(OPTION_ADT, listOf(t)), io = false, isBuiltin = true, typeParams = listOf(t)),
        FnSig("range", listOf(Type.TInt, Type.TInt), listOf("from", "to"),
            Type.TList(Type.TInt), io = false, isBuiltin = true),
    ).associateBy { it.name }
}
