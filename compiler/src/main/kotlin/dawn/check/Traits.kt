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

    /** JVM class of the declaring module; null = prelude/single-file */
    var owner: String? = null

    val display: String get() = "${trait.name}[${subject.display}]"
}

/** Traits every module sees without imports (Ord arrives with the stdlib knife). */
val PRELUDE_TRAITS: List<TraitInfo> = emptyList()

/** Prelude impls (Ord[Int/Float/String] arrive with the stdlib knife). */
val PRELUDE_IMPLS: List<ImplInfo> = emptyList()
