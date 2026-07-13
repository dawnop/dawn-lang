package dawn.check

import dawn.ast.FnDecl
import dawn.ast.TraitMethod
import dawn.diag.Span

/**
 * A declared trait: a single-parameter, coherence-controlled typeclass
 * (docs/trait.md). Registered by the checker; the same TraitInfo object flows
 * through ModuleExports to importers, so identity comparison works program-wide
 * (like AdtInfo).
 */
class TraitInfo(
    val name: String,
    /** the subject type parameter: the T in trait Ord[T] */
    val tvar: Type.TVar,
    val nameSpan: Span?,
    val pub: Boolean,
) {
    /** methods by name, in declaration order */
    val methods = LinkedHashMap<String, TraitMethodSig>()

    /** JVM class of the declaring module (multi-module codegen); null = prelude/single-file */
    var owner: String? = null

    /** source file of the declaring module (orphan rule + navigation); null = prelude/single-file */
    var srcPath: String? = null
}

/** One trait method: its signature (typeParams = [trait.tvar]) plus the default body, if any. */
class TraitMethodSig(val sig: FnSig, val decl: TraitMethod?) {
    val hasDefault: Boolean get() = decl?.body != null
}

/**
 * One impl: a trait provided for one concrete subject type. Coherence: the
 * whole program holds at most one impl per (trait, subject) pair.
 */
class ImplInfo(
    val trait: TraitInfo,
    val subject: Type,
    val span: Span,
    /** source file of the declaring module; null = prelude/single-file */
    val srcPath: String?,
) {
    /** provided method decls by name (sigs filled during registration) */
    val provided = LinkedHashMap<String, FnDecl>()

    /** a `derive Ord` impl: no source methods; codegen emits the field-lexicographic cmp */
    var derived: Boolean = false

    /** JVM class of the declaring module; null = prelude/single-file */
    var owner: String? = null

    val display: String get() = "${trait.name}[${subject.display}]"
}

/**
 * How a call site satisfies one trait requirement. Filled by the checker,
 * consumed by codegen (dictionary passing).
 */
sealed class WitnessRef {
    /** the subject is concrete: coherence gives a unique impl (devirtualizable) */
    class Concrete(val impl: ImplInfo) : WitnessRef()

    /** the subject is the caller's own type parameter: forward the caller's dictionary */
    class Forward(val trait: TraitInfo, val tvar: Type.TVar, val sym: Symbol) : WitnessRef()
}

/** The prelude ordering trait: `< <= > >=` bridge to `cmp` beyond the native scalars. */
val ORD_TRAIT: TraitInfo = run {
    val info = TraitInfo("Ord", Type.TVar("T"), nameSpan = null, pub = true)
    val sig = FnSig("cmp", listOf(info.tvar, info.tvar), listOf("a", "b"), Type.TInt, Eff.Pure,
        isBuiltin = false, typeParams = listOf(info.tvar), constraints = listOf(listOf(info)))
    sig.trait = info
    info.methods["cmp"] = TraitMethodSig(sig, decl = null)
    info
}

/** Traits every module sees without imports. */
val PRELUDE_TRAITS: List<TraitInfo> = listOf(ORD_TRAIT)

/** Ord over the natively ordered scalars ships with the language (codegen knows them). */
val PRELUDE_IMPLS: List<ImplInfo> = listOf(Type.TInt, Type.TFloat, Type.TString).map {
    ImplInfo(ORD_TRAIT, it, Span(0, 0), srcPath = null)
}
