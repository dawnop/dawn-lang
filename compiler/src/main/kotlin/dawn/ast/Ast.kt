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

class TypeRef(val name: String, val args: List<TypeRef>, val span: Span)

class FnDecl(
    pub: Boolean,
    name: String,
    /** type parameter names: fn map[T, U](...) */
    val typeParams: List<String>,
    val params: List<Param>,
    val retType: TypeRef,
    /** signature declares !io */
    val declaredIo: Boolean,
    val body: Expr,
    span: Span,
    nameSpan: Span,
) : Decl(pub, name, span, nameSpan) {
    /** resolved signature, filled by the checker (codegen consumes it) */
    var sig: FnSig? = null
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
) : Decl(pub, name, span, nameSpan)

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
}

/** M0: calls are by name only (no function values) */
class Call(val callee: String, val args: List<Expr>, val calleeSpan: Span, span: Span) : Expr(span) {
    /** resolved callee signature, filled by the checker */
    var sig: FnSig? = null
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
}

/** Record field access: p.x (also chains: p.a.b). */
class FieldAccess(val target: Expr, val fieldName: String, val fieldSpan: Span, span: Span) : Expr(span) {
    /** resolved owner constructor + field, filled by the checker */
    var owner: CtorInfo? = null
    var field: FieldInfo? = null
}

/** List literal: [1, 2, 3]. */
class ListLit(val elems: List<Expr>, span: Span) : Expr(span)

class CtorArg(val name: String?, val expr: Expr, val span: Span)

enum class BinOp { ADD, SUB, MUL, DIV, MOD, CONCAT, EQ, NEQ, LT, LE, GT, GE, AND, OR }
class Binary(val op: BinOp, val left: Expr, val right: Expr, val opSpan: Span, span: Span) : Expr(span)

enum class UnOp { NEG, NOT }
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

class PatArg(val name: String?, val pattern: Pattern)

class Block(val stmts: List<Stmt>, val tail: Expr?, span: Span) : Expr(span)

// ---- statements ----

sealed class Stmt(val span: Span)

class LetStmt(val name: String, val mutable: Boolean, val typeAnn: TypeRef?, val init: Expr, span: Span) : Stmt(span) {
    var symbol: Symbol? = null
    val isDiscard get() = name == "_"
}

class AssignStmt(val name: String, val value: Expr, val nameSpan: Span, span: Span) : Stmt(span) {
    var symbol: Symbol? = null
}

class ExprStmt(val expr: Expr, span: Span) : Stmt(span)

class WhileStmt(val cond: Expr, val body: Block, span: Span) : Stmt(span)

/** for name in from..to { body } (M0: integer ranges are the only iterable) */
class ForStmt(val name: String, val from: Expr, val to: Expr, val body: Block, span: Span) : Stmt(span) {
    var symbol: Symbol? = null
}
