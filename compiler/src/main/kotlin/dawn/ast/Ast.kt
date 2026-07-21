package dawn.ast

import dawn.check.CtorInfo
import dawn.check.FieldInfo
import dawn.check.FnSig
import dawn.check.Symbol
import dawn.check.Type
import dawn.diag.Span

// ---- module and declarations ----

class Module(
    val decls: List<Decl>,
) {
    val fns: List<FnDecl> by lazy { decls.filterIsInstance<FnDecl>() }
    val types: List<TypeDecl> by lazy { decls.filterIsInstance<TypeDecl>() }
    val tests: List<TestDecl> by lazy { decls.filterIsInstance<TestDecl>() }
    val consts: List<ConstDecl> by lazy { decls.filterIsInstance<ConstDecl>() }
    val traits: List<TraitDecl> by lazy { decls.filterIsInstance<TraitDecl>() }
    val impls: List<ImplDecl> by lazy { decls.filterIsInstance<ImplDecl>() }
    val javaUses: List<UseJavaDecl> by lazy { decls.filterIsInstance<UseJavaDecl>() }
    val moduleUses: List<UseModuleDecl> by lazy { decls.filterIsInstance<UseModuleDecl>() }
}

sealed class Decl(
    val pub: Boolean,
    val name: String,
    val span: Span,
    val nameSpan: Span,
)

class Param(val name: String, val typeName: TypeRef, val span: Span) {
    var symbol: Symbol? = null
}

sealed class TypeRef(val span: Span)

class NamedTypeRef(val name: String, val args: List<TypeRef>, span: Span) : TypeRef(span)

/** (A, B, ...) — 2 to 8 elements (spec §1.5) */
class TupleTypeRef(val elems: List<TypeRef>, span: Span) : TypeRef(span)

/**
 * fn(A, B) -> C !e — effAtoms is the parsed effect: empty (pure), ["io"], ["e"],
 * or ["e1", "e2"] for a union !(e1|e2). Each atom is "io" or an effect variable name.
 */
class FnTypeRef(
    val params: List<TypeRef>,
    val ret: TypeRef,
    val effAtoms: List<String>,
    span: Span,
) : TypeRef(span)

/**
 * One declared type parameter with optional trait bounds:
 * `T` or `T: Ord` or `T: Ord + Show` (bounds only on fn declarations).
 */
class TypeParamDecl(val name: String, val bounds: List<Pair<String, Span>>, val span: Span)

class FnDecl(
    pub: Boolean,
    name: String,
    /** type parameters: fn map[T, U](...), possibly bounded: fn sort[T: Ord](...) */
    val typeParams: List<TypeParamDecl>,
    val params: List<Param>,
    /** null = inferred from the body (private functions only, spec §3.1) */
    val retType: TypeRef?,
    /** declared effect atoms: empty (pure), ["io"], ["e"], or ["e1","e2"] for !(e1|e2) */
    val declaredEff: List<String>,
    val body: Expr,
    span: Span,
    nameSpan: Span,
) : Decl(pub, name, span, nameSpan) {
    /** resolved signature, filled by the checker (codegen consumes it) */
    var sig: FnSig? = null
    /** effect variables of this signature by name, filled by the checker */
    var effVars: Map<String, dawn.check.Eff.Var> = emptyMap()
}

/**
 * type Name = | Ctor(field: T) | ...
 * A record (type Name = { field: T }) is sugar: a single constructor named
 * after the type, with isRecord set.
 */
class TypeDecl(
    pub: Boolean,
    name: String,
    /** type parameter names: type Tree[T] = ... */
    val typeParams: List<String>,
    val ctors: List<CtorDecl>,
    val isRecord: Boolean,
    span: Span,
    nameSpan: Span,
    /** trait names after `derive` (v0.1: only "Show"); paired with each name's span for diagnostics */
    val derives: List<Pair<String, Span>> = emptyList(),
    /** when non-null this is a type alias: `type H = fn(Int) -> Int`; ctors is empty */
    val aliasTarget: TypeRef? = null,
) : Decl(pub, name, span, nameSpan)

/**
 * const NAME: Type = expr (spec §3.2). The initializer is implicitly comptime:
 * pure, evaluated at compile time, embedded as a constant.
 */
class ConstDecl(
    pub: Boolean,
    name: String,
    val typeAnn: TypeRef,
    val init: Expr,
    span: Span,
    nameSpan: Span,
) : Decl(pub, name, span, nameSpan) {
    /** resolved declared type, filled by the checker */
    var constType: Type? = null
    /** the annotation as resolved (kept even when constType is poisoned to TError) */
    var resolvedAnn: Type? = null
    /** the evaluated constant, filled by comptime evaluation */
    var value: dawn.check.CValue? = null
    /** source file of the declaring module (go-to-definition); null = current file */
    var srcPath: String? = null
}

/**
 * trait Ord[T] { fn cmp(a: T, b: T) -> Int ... } — a single-parameter typeclass.
 * Method names live in the module's function namespace (same conflict rules as
 * top-level fns); a method with a body is a default method.
 */
class TraitDecl(
    pub: Boolean,
    name: String,
    /** the subject type parameter (exactly one): the T in trait Ord[T] */
    val typeParam: String,
    val typeParamSpan: Span,
    val methods: List<TraitMethod>,
    span: Span,
    nameSpan: Span,
) : Decl(pub, name, span, nameSpan) {
    /** resolved trait, filled by the checker (codegen emits its interface + defaults) */
    var info: dawn.check.TraitInfo? = null
}

/** One method of a trait: a full signature, plus an optional default body. */
class TraitMethod(
    val name: String,
    val params: List<Param>,
    val retType: TypeRef,
    /** declared effect atoms: empty (pure) or ["io"] — effect variables are not allowed */
    val declaredEff: List<String>,
    /** non-null = a default method the impl may omit */
    val body: Expr?,
    val span: Span,
    val nameSpan: Span,
) {
    /** resolved signature, filled by the checker */
    var sig: dawn.check.FnSig? = null
}

/**
 * impl Ord[Point] { fn cmp(a: Point, b: Point) -> Int = ... } — provides a
 * trait's methods for one concrete type. Never pub (visibility follows the
 * trait); methods are full FnDecls with mandatory signatures and no own
 * type parameters.
 */
class ImplDecl(
    val traitName: String,
    val traitSpan: Span,
    val subject: TypeRef,
    val methods: List<FnDecl>,
    span: Span,
) : Decl(pub = false, name = traitName, span = span, nameSpan = traitSpan) {
    /** resolved impl, filled by the checker (codegen emits its singleton + statics) */
    var info: dawn.check.ImplInfo? = null
}

/** use java "java.lang.StringBuilder" (spec §9): an opaque type + a static namespace */
class UseJavaDecl(
    val fqcn: String,
    span: Span,
    nameSpan: Span,
) : Decl(pub = false, name = fqcn.substringAfterLast('.'), span = span, nameSpan = nameSpan)

/** one imported name in a selective use: `use m.{Json, render}` (spec §10.2) */
class ImportName(val name: String, val span: Span)

/**
 * use json/lexer  — whole-module import; alias = last path segment (`lexer`).
 * use json/value.{Json, render} — selective import; `selective` non-null.
 * (spec §10) The module path segments are lowercase identifiers.
 */
class UseModuleDecl(
    val segments: List<String>,
    /** null = whole-module import; non-null (possibly empty is a parse error) = selective */
    val selective: List<ImportName>?,
    span: Span,
    nameSpan: Span,
) : Decl(pub = false, name = segments.last(), span = span, nameSpan = nameSpan) {
    /** module path as used in diagnostics and as the resolved key: "json/lexer" */
    val path: String get() = segments.joinToString("/")

    /** the imported module's surface, filled by the checker (LSP navigation) */
    var exports: dawn.check.ModuleExports? = null
}

/** test "name" { ... } — compiled and run only by `dawn test` (spec §3.4) */
class TestDecl(
    val testName: String,
    val body: Block,
    span: Span,
    nameSpan: Span,
) : Decl(pub = false, name = testName, span = span, nameSpan = nameSpan)

class CtorDecl(val name: String, val fields: List<FieldDecl>, val span: Span, val nameSpan: Span) {
    /** resolved constructor, filled by the checker */
    var info: CtorInfo? = null
}

class FieldDecl(val name: String, val typeRef: TypeRef, val span: Span)

// ---- expressions ----

sealed class Expr(val span: Span) {
    /** type annotated by the checker */
    var type: Type? = null
}

class IntLit(val value: Long, span: Span) : Expr(span)
class FloatLit(val value: Double, span: Span) : Expr(span)
class BoolLit(val value: Boolean, span: Span) : Expr(span)
class UnitLit(span: Span) : Expr(span)

/** String literal: alternating text and interpolation parts */
class StrLit(val parts: List<StrPart>, span: Span) : Expr(span)
sealed class StrPart {
    class Text(val value: String) : StrPart()
    class Interp(val expr: Expr) : StrPart()
}

class VarRef(val name: String, span: Span) : Expr(span) {
    var symbol: Symbol? = null
    /** set when the name resolves to a top-level function used as a value */
    var fnValue: FnSig? = null
}

/** A call by name: a top-level fn / builtin, or a local function value. */
class Call(val callee: String, val args: List<Expr>, val calleeSpan: Span, span: Span) : Expr(span) {
    /** resolved callee signature, filled by the checker (null for dynamic calls) */
    var sig: FnSig? = null
    /** when the callee is a local function value, its symbol (filled by the checker) */
    var dynamicTarget: Symbol? = null
    /** dictionaries satisfying the callee's trait bounds, in flattened bound order (checker) */
    var witnesses: List<dawn.check.WitnessRef>? = null
}

/** A call of a non-name callee (currently: piping into a lambda). */
class Apply(val target: Expr, val args: List<Expr>, span: Span) : Expr(span)

/**
 * Dot call: x.f(a, b). For Dawn values this is UFCS sugar for f(x, a, b);
 * the checker fills [desugared]. (Java receivers resolve differently — §9.)
 */
class MethodCall(
    val target: Expr,
    val name: String,
    val args: List<Expr>,
    val nameSpan: Span,
    span: Span,
) : Expr(span) {
    /** the checker's rewrite: a UFCS Call, or an Apply for a fn-typed record field */
    var desugared: Expr? = null
    /** resolved Java target, filled by the checker (spec §9) */
    var javaMethod: java.lang.reflect.Method? = null
    var javaCtorRef: java.lang.reflect.Constructor<*>? = null
    val isJava: Boolean get() = javaMethod != null || javaCtorRef != null
    /** argument positions SAM-converted to functional interfaces (spec §9.4), by the checker */
    var samConvs: Map<Int, SamConv>? = null
    /** argument positions where a Dawn List bridges to a Java collection (spec §9.6) */
    var listBridges: Set<Int>? = null
    /**
     * Set by the checker when the winning candidate is variadic and the call packs
     * (spec §9.3): the index where packing starts, i.e. the fixed parameter count.
     * Arguments from here on go into the trailing array — none of them when the call
     * omits the variable part, which is just the empty-array case.
     */
    var varargsPack: Int? = null
}

/** One SAM conversion: the target functional interface and its single abstract method. */
class SamConv(val iface: Class<*>, val sam: java.lang.reflect.Method)

/** fn(x, y) => body */
class Lambda(val params: List<LambdaParam>, val body: Expr, span: Span) : Expr(span) {
    /** the lambda's own function type, filled by the checker */
    var fnType: Type.TFn? = null
    /** enclosing locals referenced by the body, filled by the checker */
    var captures: List<Symbol>? = null
}

class LambdaParam(val name: String, val typeAnn: TypeRef?, val span: Span) {
    var symbol: Symbol? = null
}

/**
 * Constructor call/reference: Circle(1.0), Rect(2.0, h: 3.0), a bare nullary
 * Point, or a record literal Point { x: 1.0, y: 2.0 } / Point { ..p, x: 3.0 }.
 */
class CtorCall(
    val ctorName: String,
    val args: List<CtorArg>,
    /** functional-update base (record literals only): the expr in { ..base, ... } */
    val spread: Expr?,
    /** false for a bare nullary constructor reference */
    val hasParens: Boolean,
    val calleeSpan: Span,
    span: Span,
) : Expr(span) {
    /** resolved constructor, filled by the checker */
    var ctor: CtorInfo? = null
    /** per-field argument expression (null = take the field from spread), filled by the checker */
    var fieldExprs: List<Expr?>? = null
    /** a bare SCREAMING_SNAKE name may resolve to a constant instead (filled by the checker) */
    var constDecl: ConstDecl? = null
    /** a bare constructor used as a function value: `map(xs, Some)` (filled by the checker) */
    var ctorValue: CtorInfo? = null
}

/** Record field access: p.x (also chains: p.a.b). */
class FieldAccess(val target: Expr, val fieldName: String, val fieldSpan: Span, span: Span) : Expr(span) {
    /** resolved owner constructor + field, filled by the checker */
    var owner: CtorInfo? = null
    var field: FieldInfo? = null
}

/** List literal: [1, 2, 3]. */
class ListLit(val elems: List<Expr>, span: Span) : Expr(span)

/** Tuple literal: (1, "a") — 2 to 8 elements. */
class TupleLit(val elems: List<Expr>, span: Span) : Expr(span)

/** expr? — unwrap Ok/Some, or return the Err/None from the enclosing function (spec §8.1) */
class Propagate(val operand: Expr, span: Span) : Expr(span)

/**
 * expr! — unwrap Some, or panic (spec §8.2). Sugar for `expect` with a message the
 * compiler writes, which is what makes it worth having: Java interop wraps every
 * reference return in Option (spec §9.2), and hand-written placeholders like
 * `.expect("b-uri")` carry no information.
 */
class Unwrap(val operand: Expr, span: Span) : Expr(span) {
    /** panic message, filled by the checker — codegen has no source text to build one from */
    var panicMsg: String? = null
}

/**
 * Index expression: xs[i] on a List (panics when out of bounds) or m[k] on a
 * Map (panics when the key is absent). The asking variants stay `get`/`map_get`.
 */
class Index(val target: Expr, val index: Expr, span: Span) : Expr(span)

/**
 * return / return expr — early return from the enclosing function (or lambda,
 * when inside one). Typed Never, so it can sit anywhere an expression can.
 */
class Return(val value: Expr?, span: Span) : Expr(span)

/** comptime { ... } — evaluated at compile time, embedded as a constant (spec §7) */
class ComptimeExpr(val body: Expr, span: Span) : Expr(span) {
    /** the evaluated constant, filled by comptime evaluation */
    var value: dawn.check.CValue? = null
}

/**
 * unsafe_pure { expr } — the author vouches that the wrapped expression is pure
 * (docs/pure-ffi-design.md). Type-checked as usual, but its effect is masked
 * from !io down to Pure, so a Java interop call the checker would otherwise flag
 * !io can back a pure function. An escape hatch: unsound if the vouch is wrong.
 * The block is transparent at runtime (codegen emits the inner expression); it
 * also licenses that Java call to run at compile time (comptime route C).
 */
class UnsafePureExpr(val body: Expr, span: Span) : Expr(span)

class CtorArg(val name: String?, val expr: Expr, val span: Span)

enum class BinOp { ADD, SUB, MUL, DIV, MOD, CONCAT, EQ, NEQ, LT, LE, GT, GE, AND, OR,
    // bitwise, Int only; SHR is arithmetic (sign-extending), USHR is logical
    BAND, BOR, BXOR, SHL, SHR, USHR }
class Binary(val op: BinOp, val left: Expr, val right: Expr, val opSpan: Span, span: Span) : Expr(span) {
    /** when `< <= > >=` order through an Ord impl (not a native scalar): the dictionary (checker) */
    var ordWitness: dawn.check.WitnessRef? = null
}

enum class UnOp { NEG, NOT, BNOT }
class Unary(val op: UnOp, val operand: Expr, span: Span) : Expr(span)

class If(val cond: Expr, val thenBranch: Block, val elseBranch: Expr?, span: Span) : Expr(span)

class Match(val scrutinee: Expr, val arms: List<MatchArm>, span: Span) : Expr(span)
class MatchArm(val patterns: List<Pattern>, val guard: Expr?, val body: Expr, val span: Span)

sealed class Pattern(val span: Span)
class LitPat(val lit: Expr, span: Span) : Pattern(span) // IntLit / StrLit (no interpolation) / BoolLit
class BindPat(val name: String, span: Span) : Pattern(span) {
    var symbol: Symbol? = null
}
class WildPat(span: Span) : Pattern(span)

/** Constructor pattern: Circle(r), Rect(w: w, ..), or a bare nullary Point. */
class CtorPat(
    val ctorName: String,
    val args: List<PatArg>,
    /** pattern ends with `..` (ignore remaining fields) */
    val hasRest: Boolean,
    val hasParens: Boolean,
    val nameSpan: Span,
    span: Span,
) : Pattern(span) {
    /** resolved constructor, filled by the checker */
    var ctor: CtorInfo? = null
    /** subpatterns by field index (null = not matched, via ..), filled by the checker */
    var fieldPats: List<Pattern?>? = null
    /** field types with the scrutinee's type arguments substituted in, filled by the checker */
    var fieldTypes: List<Type>? = null
}

/** Tuple pattern: (a, b). Element types filled by the checker. */
class TuplePat(val elems: List<Pattern>, span: Span) : Pattern(span) {
    var elemTypes: List<Type>? = null
}

/**
 * List pattern: [], [x, ..rest], [..init, last] — fixed elements around at
 * most one `..`/`..name` rest (spec §5.1).
 */
class ListPat(
    val pre: List<Pattern>,
    val hasRest: Boolean,
    /** `..name` binds the middle as a list; bare `..` ignores it */
    val restName: String?,
    val restSpan: Span?,
    val post: List<Pattern>,
    span: Span,
) : Pattern(span) {
    var elemType: Type? = null
    var restSymbol: Symbol? = null
}

class PatArg(val name: String?, val pattern: Pattern)

class Block(val stmts: List<Stmt>, val tail: Expr?, span: Span) : Expr(span)

// ---- statements ----

sealed class Stmt(val span: Span)

class LetStmt(val name: String, val mutable: Boolean, val typeAnn: TypeRef?, val init: Expr, span: Span) : Stmt(span) {
    var symbol: Symbol? = null
    val isDiscard get() = name == "_"
}

/**
 * let (a, b) = pair / let Point { x, y } = p — destructuring bind (spec §5.2).
 * The pattern must be irrefutable; with var every binding is mutable.
 */
class LetPatStmt(val pattern: Pattern, val mutable: Boolean, val init: Expr, span: Span) : Stmt(span)

/**
 * A local named function: `fn name(params) -> T [!io] = body`. Sugar for a
 * let-bound lambda whose name is visible inside its own body — a recursive
 * call compiles to a direct call of the impl method (a loop in tail position).
 */
class LocalFnStmt(
    val name: String,
    val lambda: Lambda,
    val retRef: TypeRef,
    val effNames: List<String>,
    val nameSpan: Span,
    span: Span,
) : Stmt(span) {
    var symbol: Symbol? = null
}

class AssignStmt(val name: String, val value: Expr, val nameSpan: Span, span: Span) : Stmt(span) {
    var symbol: Symbol? = null
}

class ExprStmt(val expr: Expr, span: Span) : Stmt(span)

/** assert expr — only inside test blocks */
class AssertStmt(val cond: Expr, span: Span) : Stmt(span) {
    /** the asserted expression's source text, for the failure message */
    var sourceText: String? = null
}

class WhileStmt(val cond: Expr, val body: Block, span: Span) : Stmt(span)

/** for name in from..to { body }, or for name in list { body } (to == null) */
class ForStmt(val name: String, val from: Expr, val to: Expr?, val body: Block, span: Span) : Stmt(span) {
    var symbol: Symbol? = null
}
