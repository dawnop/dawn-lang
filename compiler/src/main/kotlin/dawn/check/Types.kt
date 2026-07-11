package dawn.check

/** The complete set of M0 types. */
sealed class Type(val display: String) {
    object TInt : Type("Int")
    object TFloat : Type("Float")
    object TBool : Type("Bool")
    object TString : Type("String")
    object TUnit : Type("Unit")

    /** Bottom type: the "return type" of panic/todo; usable as any type */
    object TNever : Type("Never")

    override fun toString() = display

    val isNumeric get() = this == TInt || this == TFloat

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

/** Resolved local variable/parameter; the checker fills this into the AST, codegen consumes it. */
class Symbol(val name: String, val type: Type, val mutable: Boolean) {
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
)

/** M0 builtin functions. A tiny subset of spec §11. */
val BUILTINS: Map<String, FnSig> = listOf(
    FnSig("println", listOf(Type.TString), listOf("s"), Type.TUnit, io = true, isBuiltin = true),
    FnSig("print", listOf(Type.TString), listOf("s"), Type.TUnit, io = true, isBuiltin = true),
    FnSig("panic", listOf(Type.TString), listOf("msg"), Type.TNever, io = false, isBuiltin = true),
    FnSig("todo", listOf(), listOf(), Type.TNever, io = false, isBuiltin = true),
).associateBy { it.name }
