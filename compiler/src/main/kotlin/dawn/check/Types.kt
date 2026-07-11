package dawn.check

import dawn.diag.Span

/** The complete set of M0 types. */
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

    /** A user-defined sum type. One instance per declaration, so == is identity. */
    class TAdt(val info: AdtInfo) : Type(info.name)

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

/**
 * A user-defined ADT. Built by the checker in two passes: the shell (name) first,
 * then constructor field types — so recursive types (Expr = Add(l: Expr, ...))
 * resolve naturally.
 */
class AdtInfo(val name: String, val nameSpan: Span?, val isRecord: Boolean = false) {
    val ctors = ArrayList<CtorInfo>()
    val type: Type.TAdt = Type.TAdt(this)

    /** JVM internal name: abstract base class (sum type) or the single final class (record) */
    val jvmName: String get() = name
}

class CtorInfo(val adt: AdtInfo, val name: String, val nameSpan: Span?) {
    val fields = ArrayList<FieldInfo>()

    /** JVM internal name: a final subclass, or the record class itself */
    val jvmName: String get() = if (adt.isRecord) adt.name else "${adt.name}$$name"

    fun render(): String = when {
        adt.isRecord -> "$name { ${fields.joinToString(", ") { "${it.name}: ${it.type}" }} }"
        fields.isEmpty() -> "$name: ${adt.name}"
        else -> "$name(${fields.joinToString(", ") { "${it.name}: ${it.type}" }}): ${adt.name}"
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
    /** span of the name in the declaration (go-to-definition); null for builtins */
    val nameSpan: Span? = null,
) {
    fun render(): String {
        val params = paramNames.zip(paramTypes).joinToString(", ") { "${it.first}: ${it.second}" }
        val eff = if (io) " !io" else ""
        return "fn $name($params) -> $ret$eff"
    }
}

/** M0 builtin functions. A tiny subset of spec §11. */
val BUILTINS: Map<String, FnSig> = listOf(
    FnSig("println", listOf(Type.TString), listOf("s"), Type.TUnit, io = true, isBuiltin = true),
    FnSig("print", listOf(Type.TString), listOf("s"), Type.TUnit, io = true, isBuiltin = true),
    FnSig("panic", listOf(Type.TString), listOf("msg"), Type.TNever, io = false, isBuiltin = true),
    FnSig("todo", listOf(), listOf(), Type.TNever, io = false, isBuiltin = true),
).associateBy { it.name }
