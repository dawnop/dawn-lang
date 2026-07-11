package dawn.lsp

import dawn.ast.*
import dawn.check.Analyzed
import dawn.check.BUILTINS
import dawn.diag.Span

/**
 * What sits under the cursor: hover text (dawn pseudo-syntax) plus an optional
 * definition site. Computed by walking the annotated AST and picking the
 * innermost (smallest) span containing the offset.
 */
class Target(
    val span: Span,
    val hover: String,
    val defSpan: Span? = null,
)

fun findTarget(analysis: Analyzed, offset: Int): Target? {
    val q = TargetQuery(analysis, offset)
    for (d in analysis.module.decls) q.visitDecl(d)
    return q.best
}

private class TargetQuery(private val analysis: Analyzed, private val offset: Int) {
    var best: Target? = null

    private fun offer(span: Span, hover: String, defSpan: Span? = null) {
        if (offset < span.start || offset >= span.end) return
        val cur = best
        if (cur == null || span.end - span.start <= cur.span.end - cur.span.start) {
            best = Target(span, hover, defSpan)
        }
    }

    private fun sigOf(name: String) = analysis.functions[name] ?: BUILTINS[name]

    fun visitDecl(d: FnDecl) {
        sigOf(d.name)?.let { offer(d.nameSpan, it.render(), d.nameSpan) }
        for (p in d.params) {
            val t = p.symbol?.type ?: continue
            offer(p.span, "${p.name}: $t", p.span)
        }
        visitExpr(d.body)
    }

    fun visitExpr(e: Expr) {
        // generic fallback: the expression's own type
        e.type?.let { offer(e.span, it.display) }
        when (e) {
            is VarRef -> {
                val sym = e.symbol
                if (sym != null) {
                    val kw = if (sym.mutable) "var" else "let"
                    offer(e.span, "$kw ${sym.name}: ${sym.type}", sym.defSpan)
                }
            }
            is Call -> {
                sigOf(e.callee)?.let { offer(e.calleeSpan, it.render(), it.nameSpan) }
                e.args.forEach { visitExpr(it) }
            }
            is StrLit -> e.parts.forEach { if (it is StrPart.Interp) visitExpr(it.expr) }
            is Binary -> { visitExpr(e.left); visitExpr(e.right) }
            is Unary -> visitExpr(e.operand)
            is If -> {
                visitExpr(e.cond)
                visitExpr(e.thenBranch)
                e.elseBranch?.let { visitExpr(it) }
            }
            is Match -> {
                visitExpr(e.scrutinee)
                for (arm in e.arms) {
                    arm.patterns.forEach { visitPattern(it) }
                    arm.guard?.let { visitExpr(it) }
                    visitExpr(arm.body)
                }
            }
            is Block -> {
                e.stmts.forEach { visitStmt(it) }
                e.tail?.let { visitExpr(it) }
            }
            else -> {}
        }
    }

    fun visitPattern(p: Pattern) {
        if (p is BindPat) {
            val sym = p.symbol ?: return
            offer(p.span, "${sym.name}: ${sym.type}", p.span)
        }
    }

    fun visitStmt(s: Stmt) {
        when (s) {
            is LetStmt -> visitExpr(s.init)
            is AssignStmt -> {
                s.symbol?.let { sym ->
                    val kw = if (sym.mutable) "var" else "let"
                    offer(s.nameSpan, "$kw ${sym.name}: ${sym.type}", sym.defSpan)
                }
                visitExpr(s.value)
            }
            is ExprStmt -> visitExpr(s.expr)
            is WhileStmt -> { visitExpr(s.cond); visitExpr(s.body) }
            is ForStmt -> { visitExpr(s.from); visitExpr(s.to); visitExpr(s.body) }
        }
    }
}
