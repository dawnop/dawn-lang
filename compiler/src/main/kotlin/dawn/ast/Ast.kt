package dawn.ast

import dawn.check.Symbol
import dawn.check.Type
import dawn.diag.Span

// ---- module and declarations ----

class Module(
    val decls: List<FnDecl>,
)

class Param(val name: String, val typeName: TypeRef, val span: Span) {
    var symbol: Symbol? = null
}

class TypeRef(val name: String, val span: Span)

class FnDecl(
    val pub: Boolean,
    val name: String,
    val params: List<Param>,
    val retType: TypeRef,
    /** signature declares !io */
    val declaredIo: Boolean,
    val body: Expr,
    val span: Span,
    val nameSpan: Span,
)

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
class Call(val callee: String, val args: List<Expr>, val calleeSpan: Span, span: Span) : Expr(span)

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
