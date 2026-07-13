package dawn.check

import dawn.diag.Span

/**
 * A type alias: transparent, expanded during type resolution (never a distinct
 * type). Declared as `type Name[T] = <fn type | tuple | Name[args]>`; a bare
 * uppercase RHS still declares a single-constructor ADT (back-compat).
 */
class AliasInfo(
    val name: String,
    val typeParams: List<Type.TVar>,
    /** the unresolved target in the declaring module; null on imported (pre-resolved) aliases */
    val targetRef: dawn.ast.TypeRef?,
    val nameSpan: Span,
) {
    var resolved: Type? = null
    var resolving = false
}

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

    /** The builtin persistent map: Map[K, V] (spec §2.2). */
    class TMap(val key: Type, val value: Type) : Type("Map[$key, $value]") {
        override fun equals(other: Any?): Boolean = other is TMap && other.key == key && other.value == value
        override fun hashCode(): Int = key.hashCode() * 31 + value.hashCode() + 11
    }

    /** The builtin persistent set: Set[T] (spec §2.2). */
    class TSet(val elem: Type) : Type("Set[$elem]") {
        override fun equals(other: Any?): Boolean = other is TSet && other.elem == elem
        override fun hashCode(): Int = elem.hashCode() + 17
    }

    /** An opaque imported Java class (spec §9). Identity is the fully-qualified name.
     *  Arrays ride along as opaque values (spec §9.5): fqcn is the JVM name ("[B"),
     *  the display is readable ("byte[]", "String[]"). */
    class TJava(val fqcn: String, val cls: Class<*>) : Type(
        if (cls.isArray) (cls.canonicalName ?: fqcn).substringAfterLast('.')
        else fqcn.substringAfterLast('.'),
    ) {
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
    is Type.TMap -> Type.TMap(subst(t.key, map, effMap), subst(t.value, map, effMap))
    is Type.TSet -> Type.TSet(subst(t.elem, map, effMap))
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

    /** `derive Show` requested: the type gets a generated to_string / toString (spec §4.3) */
    var derivesShow: Boolean = false

    /** `derive Ord` requested: the checker registers a field-lexicographic Ord impl */
    var derivesOrd: Boolean = false

    /** the program's unique Ord impl for this type, if any (derived or explicit) */
    var ordImpl: ImplInfo? = null

    /**
     * JVM class of the module that defines this type (spec §12.2), used to prefix
     * its class name in a multi-module program. Null = prelude or single-file
     * (no prefix), so existing single-file bytecode is unchanged.
     */
    var owner: String? = null

    /** source file of the defining module (go-to-definition); null = prelude/current file */
    var srcPath: String? = null

    /** the declared "self type": Tree[T] inside its own declaration */
    val type: Type.TAdt = Type.TAdt(this, typeParams)

    /** JVM internal name (erased): abstract base class (sum type) or the single final class (record) */
    val jvmName: String get() = owner?.let { "$it\$$name" } ?: name
}

class CtorInfo(val adt: AdtInfo, val name: String, val nameSpan: Span?) {
    val fields = ArrayList<FieldInfo>()

    /** JVM internal name: a final subclass, or the record class itself */
    val jvmName: String get() = if (adt.isRecord) adt.jvmName else "${adt.jvmName}$$name"

    fun render(): String {
        val ret = adt.type.display
        return when {
            adt.isRecord -> "$name { ${fields.joinToString(", ") { "${it.name}: ${it.type}" }} }"
            fields.isEmpty() -> "$name: $ret"
            else -> "$name(${fields.joinToString(", ") { "${it.name}: ${it.type}" }}): $ret"
        }
    }
}

class FieldInfo(val name: String, val type: Type, val defSpan: Span? = null, val srcPath: String? = null)

/** Resolved local variable/parameter; the checker fills this into the AST, codegen consumes it. */
class Symbol(
    val name: String,
    val type: Type,
    val mutable: Boolean,
    val defSpan: Span,
    /** non-null for a hidden trait-dictionary binding: the (bound, type parameter) it carries */
    val dictOf: Pair<TraitInfo, Type.TVar>? = null,
) {
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
    /** the return type (and effect) is still being inferred; ret is a placeholder */
    val inferring: Boolean = false,
    /** trait bounds per type parameter, aligned with [typeParams]; empty = unconstrained */
    val constraints: List<List<TraitInfo>> = emptyList(),
) {
    /** JVM class of the defining module (spec §12.2); null = builtin/single-file */
    var owner: String? = null

    /** source file of the defining module (go-to-definition); null = builtin/current file */
    var srcPath: String? = null

    /** non-null when this signature is a trait method (resolved through witnesses) */
    var trait: TraitInfo? = null

    /** hidden dictionary parameters, one per (type parameter, bound) in flattened order */
    var dictSyms: List<Symbol> = emptyList()

    val io: Boolean get() = eff == Eff.Io

    /** the bounds of typeParams[i], or none */
    fun boundsOf(i: Int): List<TraitInfo> = constraints.getOrNull(i).orEmpty()

    fun render(): String {
        val tp = if (typeParams.isEmpty()) "" else "[" + typeParams.mapIndexed { i, v ->
            val bs = boundsOf(i)
            if (bs.isEmpty()) v.name else v.name + ": " + bs.joinToString(" + ") { it.name }
        }.joinToString(", ") + "]"
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
    info.derivesShow = true // Option/Result print when their payloads do (spec §4.3)
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
    val k = Type.TVar("K")
    val v = Type.TVar("V")
    val e = Eff.Var("e")
    fun map(kk: Type, vv: Type) = Type.TMap(kk, vv)
    fun set(tt: Type) = Type.TSet(tt)
    fun list(tt: Type) = Type.TList(tt)
    fun pair(aa: Type, bb: Type) = Type.TTuple(listOf(aa, bb))
    fun opt(tt: Type) = Type.TAdt(OPTION_ADT, listOf(tt))
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
        // core/list ordering (docs/trait.md): Ord-bounded builtins take witnesses like any call
        FnSig("sort", listOf(list(t)), listOf("xs"), list(t), Eff.Pure, isBuiltin = true,
            typeParams = listOf(t), constraints = listOf(listOf(ORD_TRAIT))),
        FnSig("sort_by", listOf(list(t), Type.TFn(listOf(t, t), Type.TInt, e)), listOf("xs", "cmp"),
            list(t), e, isBuiltin = true, typeParams = listOf(t)),
        FnSig("max", listOf(list(t)), listOf("xs"), opt(t), Eff.Pure, isBuiltin = true,
            typeParams = listOf(t), constraints = listOf(listOf(ORD_TRAIT))),
        FnSig("min", listOf(list(t)), listOf("xs"), opt(t), Eff.Pure, isBuiltin = true,
            typeParams = listOf(t), constraints = listOf(listOf(ORD_TRAIT))),
        FnSig("max_by", listOf(list(t), Type.TFn(listOf(t), k, e)), listOf("xs", "key"),
            opt(t), e, isBuiltin = true, typeParams = listOf(t, k),
            constraints = listOf(emptyList(), listOf(ORD_TRAIT))),
        FnSig("min_by", listOf(list(t), Type.TFn(listOf(t), k, e)), listOf("xs", "key"),
            opt(t), e, isBuiltin = true, typeParams = listOf(t, k),
            constraints = listOf(emptyList(), listOf(ORD_TRAIT))),
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
        // code points / characters (spec §1.5, §11): a character is its Int code point
        FnSig("code_points", listOf(Type.TString), listOf("s"), Type.TList(Type.TInt),
            Eff.Pure, isBuiltin = true),
        FnSig("from_code_points", listOf(Type.TList(Type.TInt)), listOf("cs"), Type.TString,
            Eff.Pure, isBuiltin = true),
        FnSig("char_to_string", listOf(Type.TInt), listOf("c"), Type.TString, Eff.Pure, isBuiltin = true),
        FnSig("str_len", listOf(Type.TString), listOf("s"), Type.TInt, Eff.Pure, isBuiltin = true),
        FnSig("substring", listOf(Type.TString, Type.TInt, Type.TInt), listOf("s", "from", "to"),
            Type.TString, Eff.Pure, isBuiltin = true),
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
        // java interop exception barrier (spec §9.8): expected Java failures become Err;
        // panics (dawn.rt.PanicError extends Error) pass through untouched
        FnSig("java_try", listOf(Type.TFn(emptyList(), t, Eff.Io)), listOf("f"),
            Type.TAdt(RESULT_ADT, listOf(t, Type.TString)), Eff.Io, isBuiltin = true,
            typeParams = listOf(t)),
        // io (spec §11)
        FnSig("read_file", listOf(Type.TString), listOf("path"),
            Type.TAdt(RESULT_ADT, listOf(Type.TString, Type.TString)), Eff.Io, isBuiltin = true),
        FnSig("write_file", listOf(Type.TString, Type.TString), listOf("path", "content"),
            Type.TAdt(RESULT_ADT, listOf(Type.TInt, Type.TString)), Eff.Io, isBuiltin = true),
        FnSig("list_dir", listOf(Type.TString), listOf("path"),
            Type.TAdt(RESULT_ADT, listOf(Type.TList(Type.TString), Type.TString)), Eff.Io, isBuiltin = true),
        FnSig("is_dir", listOf(Type.TString), listOf("path"), Type.TBool, Eff.Io, isBuiltin = true),
        FnSig("read_line", listOf(), listOf(),
            Type.TAdt(OPTION_ADT, listOf(Type.TString)), Eff.Io, isBuiltin = true),
        FnSig("args", listOf(), listOf(), Type.TList(Type.TString), Eff.Io, isBuiltin = true),
        // core/map + core/set: builtin persistent containers (spec §2.2, §11)
        FnSig("map_empty", listOf(), listOf(), map(k, v), Eff.Pure, isBuiltin = true, typeParams = listOf(k, v)),
        FnSig("set_empty", listOf(), listOf(), set(t), Eff.Pure, isBuiltin = true, typeParams = listOf(t)),
        FnSig("map_from", listOf(list(pair(k, v))), listOf("entries"), map(k, v),
            Eff.Pure, isBuiltin = true, typeParams = listOf(k, v)),
        FnSig("set_from", listOf(list(t)), listOf("xs"), set(t), Eff.Pure, isBuiltin = true, typeParams = listOf(t)),
        FnSig("map_insert", listOf(map(k, v), k, v), listOf("m", "key", "value"), map(k, v),
            Eff.Pure, isBuiltin = true, typeParams = listOf(k, v)),
        FnSig("set_insert", listOf(set(t), t), listOf("s", "x"), set(t),
            Eff.Pure, isBuiltin = true, typeParams = listOf(t)),
        FnSig("map_remove", listOf(map(k, v), k), listOf("m", "key"), map(k, v),
            Eff.Pure, isBuiltin = true, typeParams = listOf(k, v)),
        FnSig("set_remove", listOf(set(t), t), listOf("s", "x"), set(t),
            Eff.Pure, isBuiltin = true, typeParams = listOf(t)),
        FnSig("map_get", listOf(map(k, v), k), listOf("m", "key"), opt(v),
            Eff.Pure, isBuiltin = true, typeParams = listOf(k, v)),
        FnSig("map_has", listOf(map(k, v), k), listOf("m", "key"), Type.TBool,
            Eff.Pure, isBuiltin = true, typeParams = listOf(k, v)),
        FnSig("set_has", listOf(set(t), t), listOf("s", "x"), Type.TBool,
            Eff.Pure, isBuiltin = true, typeParams = listOf(t)),
        FnSig("map_size", listOf(map(k, v)), listOf("m"), Type.TInt,
            Eff.Pure, isBuiltin = true, typeParams = listOf(k, v)),
        FnSig("set_size", listOf(set(t)), listOf("s"), Type.TInt,
            Eff.Pure, isBuiltin = true, typeParams = listOf(t)),
        FnSig("map_keys", listOf(map(k, v)), listOf("m"), list(k),
            Eff.Pure, isBuiltin = true, typeParams = listOf(k, v)),
        FnSig("map_values", listOf(map(k, v)), listOf("m"), list(v),
            Eff.Pure, isBuiltin = true, typeParams = listOf(k, v)),
        FnSig("map_entries", listOf(map(k, v)), listOf("m"), list(pair(k, v)),
            Eff.Pure, isBuiltin = true, typeParams = listOf(k, v)),
        FnSig("set_to_list", listOf(set(t)), listOf("s"), list(t),
            Eff.Pure, isBuiltin = true, typeParams = listOf(t)),
    ).associateBy { it.name }
}
