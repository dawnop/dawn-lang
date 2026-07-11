package dawn.check

import dawn.diag.Span

/**
 * An effect (spec §6): the two-point lattice pure < io, plus effect variables
 * (introduced by appearing in a signature; identity equality, one instance per
 * name per signature).
 */
sealed class Eff {
    object Pure : Eff() {
        override fun toString() = ""
    }
    object Io : Eff() {
        override fun toString() = "io"
    }
    class Var(val name: String) : Eff() {
        override fun toString() = name
    }

    /**
     * A union of two or more distinct effect variables: `!(e1|e2)`. Built only
     * through [union], which normalizes (io absorbs, pure is dropped, a single
     * variable collapses), so a Union always holds ≥2 variables and no io.
     * Equality is by the set of variables (each Var by identity).
     */
    class Union(val vars: Set<Var>) : Eff() {
        override fun toString() = vars.map { it.name }.sorted().joinToString("|", "(", ")")
        override fun equals(other: Any?) = other is Union && other.vars == vars
        override fun hashCode() = vars.hashCode()
    }

    /** render as a signature suffix: "", " !io", " !e", " !(e1|e2)" */
    val suffix: String get() = if (this == Pure) "" else " !$this"

    companion object {
        /** Combine effects into their normalized least upper bound. */
        fun union(effs: List<Eff>): Eff {
            if (effs.any { it == Io }) return Io
            val vars = LinkedHashSet<Var>()
            for (e in effs) when (e) {
                is Var -> vars.add(e)
                is Union -> vars.addAll(e.vars)
                else -> {} // Pure contributes nothing; Io handled above
            }
            return when (vars.size) {
                0 -> Pure
                1 -> vars.first()
                else -> Union(vars)
            }
        }
    }
}

/** least upper bound in the effect lattice (distinct variables join into a union) */
fun lubEff(a: Eff, b: Eff): Eff = Eff.union(listOf(a, b))

/** does [outer] permit every effect in [inner]? io covers all; pure is bottom. */
fun effSubsumes(outer: Eff, inner: Eff): Boolean = when {
    outer == Eff.Io -> true
    inner == Eff.Pure -> true
    outer == inner -> true
    outer is Eff.Union -> when (inner) {
        is Eff.Var -> inner in outer.vars
        is Eff.Union -> outer.vars.containsAll(inner.vars)
        else -> false // inner == Io is not covered by a variable union
    }
    else -> false
}

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

    /** An opaque imported Java class (spec §9). Identity is the fully-qualified name. */
    class TJava(val fqcn: String, val cls: Class<*>) : Type(fqcn.substringAfterLast('.')) {
        override fun equals(other: Any?): Boolean = other is TJava && other.fqcn == fqcn
        override fun hashCode(): Int = fqcn.hashCode()
        val internalName: String get() = fqcn.replace('.', '/')
    }

    /** A tuple: (A, B) — 2 to 8 elements, invariant, elements stored boxed. */
    class TTuple(val elems: List<Type>) :
        Type("(${elems.joinToString(", ")})") {
        override fun equals(other: Any?): Boolean = other is TTuple && other.elems == elems
        override fun hashCode(): Int = elems.hashCode() + 13
    }

    /** A function type: fn(A, B) -> C !e. */
    class TFn(val params: List<Type>, val ret: Type, val eff: Eff) :
        Type("fn(${params.joinToString(", ")}) -> $ret${eff.suffix}") {
        override fun equals(other: Any?): Boolean =
            other is TFn && other.params == params && other.ret == ret && other.eff == eff
        override fun hashCode(): Int = params.hashCode() * 31 + ret.hashCode()
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

/** Replace type variables (and effect variables) according to the maps (identity lookups). */
fun subst(t: Type, map: Map<Type.TVar, Type>, effMap: Map<Eff.Var, Eff> = emptyMap()): Type = when (t) {
    is Type.TVar -> map[t] ?: t
    is Type.TAdt -> if (t.args.isEmpty()) t else Type.TAdt(t.info, t.args.map { subst(it, map, effMap) })
    is Type.TList -> Type.TList(subst(t.elem, map, effMap))
    is Type.TTuple -> Type.TTuple(t.elems.map { subst(it, map, effMap) })
    is Type.TFn -> Type.TFn(t.params.map { subst(it, map, effMap) }, subst(t.ret, map, effMap),
        substEff(t.eff, effMap))
    else -> t
}

fun substEff(e: Eff, effMap: Map<Eff.Var, Eff>): Eff = when (e) {
    is Eff.Var -> effMap[e] ?: e
    is Eff.Union -> Eff.union(e.vars.map { effMap[it] ?: it })
    else -> e
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
    val eff: Eff,
    val isBuiltin: Boolean,
    val typeParams: List<Type.TVar> = emptyList(),
    /** span of the name in the declaration (go-to-definition); null for builtins */
    val nameSpan: Span? = null,
) {
    val io: Boolean get() = eff == Eff.Io

    fun render(): String {
        val tp = if (typeParams.isEmpty()) "" else "[${typeParams.joinToString(", ")}]"
        val params = paramNames.zip(paramTypes).joinToString(", ") { "${it.first}: ${it.second}" }
        return "fn $name$tp($params) -> $ret${eff.suffix}"
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
    val u = Type.TVar("U")
    val a = Type.TVar("A")
    val e = Eff.Var("e")
    listOf(
        FnSig("println", listOf(Type.TString), listOf("s"), Type.TUnit, Eff.Io, isBuiltin = true),
        FnSig("print", listOf(Type.TString), listOf("s"), Type.TUnit, Eff.Io, isBuiltin = true),
        FnSig("panic", listOf(Type.TString), listOf("msg"), Type.TNever, Eff.Pure, isBuiltin = true),
        FnSig("todo", listOf(), listOf(), Type.TNever, Eff.Pure, isBuiltin = true),
        FnSig("to_float", listOf(Type.TInt), listOf("n"), Type.TFloat, Eff.Pure, isBuiltin = true),
        FnSig("to_int", listOf(Type.TFloat), listOf("x"), Type.TInt, Eff.Pure, isBuiltin = true),
        FnSig("len", listOf(Type.TList(t)), listOf("xs"), Type.TInt,
            Eff.Pure, isBuiltin = true, typeParams = listOf(t)),
        FnSig("get", listOf(Type.TList(t), Type.TInt), listOf("xs", "i"),
            Type.TAdt(OPTION_ADT, listOf(t)), Eff.Pure, isBuiltin = true, typeParams = listOf(t)),
        FnSig("range", listOf(Type.TInt, Type.TInt), listOf("from", "to"),
            Type.TList(Type.TInt), Eff.Pure, isBuiltin = true),
        FnSig("map", listOf(Type.TList(t), Type.TFn(listOf(t), u, e)), listOf("xs", "f"),
            Type.TList(u), e, isBuiltin = true, typeParams = listOf(t, u)),
        FnSig("filter", listOf(Type.TList(t), Type.TFn(listOf(t), Type.TBool, e)), listOf("xs", "f"),
            Type.TList(t), e, isBuiltin = true, typeParams = listOf(t)),
        FnSig("fold", listOf(Type.TList(t), a, Type.TFn(listOf(a, t), a, e)), listOf("xs", "init", "f"),
            a, e, isBuiltin = true, typeParams = listOf(t, a)),
        // core/option (spec §11)
        FnSig("expect", listOf(Type.TAdt(OPTION_ADT, listOf(t)), Type.TString), listOf("o", "msg"),
            t, Eff.Pure, isBuiltin = true, typeParams = listOf(t)),
        FnSig("unwrap_or", listOf(Type.TAdt(OPTION_ADT, listOf(t)), t), listOf("o", "fallback"),
            t, Eff.Pure, isBuiltin = true, typeParams = listOf(t)),
        // core/string (spec §11); to_string's T is checked printable at the use site
        FnSig("to_string", listOf(t), listOf("x"), Type.TString,
            Eff.Pure, isBuiltin = true, typeParams = listOf(t)),
        FnSig("chars", listOf(Type.TString), listOf("s"),
            Type.TList(Type.TString), Eff.Pure, isBuiltin = true),
        FnSig("join", listOf(Type.TList(Type.TString), Type.TString), listOf("xs", "sep"),
            Type.TString, Eff.Pure, isBuiltin = true),
        FnSig("split", listOf(Type.TString, Type.TString), listOf("s", "sep"),
            Type.TList(Type.TString), Eff.Pure, isBuiltin = true),
        FnSig("trim", listOf(Type.TString), listOf("s"), Type.TString, Eff.Pure, isBuiltin = true),
        FnSig("contains", listOf(Type.TString, Type.TString), listOf("s", "sub"),
            Type.TBool, Eff.Pure, isBuiltin = true),
        FnSig("starts_with", listOf(Type.TString, Type.TString), listOf("s", "prefix"),
            Type.TBool, Eff.Pure, isBuiltin = true),
        FnSig("ends_with", listOf(Type.TString, Type.TString), listOf("s", "suffix"),
            Type.TBool, Eff.Pure, isBuiltin = true),
        FnSig("parse_int", listOf(Type.TString), listOf("s"),
            Type.TAdt(OPTION_ADT, listOf(Type.TInt)), Eff.Pure, isBuiltin = true),
        FnSig("parse_float", listOf(Type.TString), listOf("s"),
            Type.TAdt(OPTION_ADT, listOf(Type.TFloat)), Eff.Pure, isBuiltin = true),
        // io (spec §11)
        FnSig("read_file", listOf(Type.TString), listOf("path"),
            Type.TAdt(RESULT_ADT, listOf(Type.TString, Type.TString)), Eff.Io, isBuiltin = true),
        FnSig("write_file", listOf(Type.TString, Type.TString), listOf("path", "content"),
            Type.TAdt(RESULT_ADT, listOf(Type.TInt, Type.TString)), Eff.Io, isBuiltin = true),
        FnSig("read_line", listOf(), listOf(),
            Type.TAdt(OPTION_ADT, listOf(Type.TString)), Eff.Io, isBuiltin = true),
        FnSig("args", listOf(), listOf(), Type.TList(Type.TString), Eff.Io, isBuiltin = true),
    ).associateBy { it.name }
}
