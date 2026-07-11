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

    fun visitDecl(d: Decl) {
        when (d) {
            is FnDecl -> {
                sigOf(d.name)?.let { offer(d.nameSpan, it.render(), d.nameSpan) }
                for (p in d.params) {
                    val t = p.symbol?.type ?: continue
                    offer(p.span, "${p.name}: $t", p.span)
                }
                visitExpr(d.body)
            }
            is TestDecl -> visitExpr(d.body)
            is TypeDecl -> {
                val info = analysis.types[d.name]
                val summary = info?.ctors?.joinToString(" | ") { it.name } ?: ""
                offer(d.nameSpan, "type ${d.name} = $summary", d.nameSpan)
                for (c in d.ctors) {
                    c.info?.let { offer(c.nameSpan, it.render(), c.nameSpan) }
                    for ((i, f) in c.fields.withIndex()) {
                        val t = c.info?.fields?.getOrNull(i)?.type ?: continue
                        offer(f.span, "${f.name}: $t", f.span)
                    }
                }
            }
        }
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
                e.fnValue?.let { offer(e.span, it.render(), it.nameSpan) }
            }
            is Lambda -> {
                for (p in e.params) {
                    val sym = p.symbol ?: continue
                    offer(p.span, "${sym.name}: ${sym.type}", p.span)
                }
                visitExpr(e.body)
            }
            is Apply -> {
                visitExpr(e.target)
                e.args.forEach { visitExpr(it) }
            }
            is ListLit -> e.elems.forEach { visitExpr(it) }
            is TupleLit -> e.elems.forEach { visitExpr(it) }
            is Call -> {
                sigOf(e.callee)?.let { offer(e.calleeSpan, it.render(), it.nameSpan) }
                e.args.forEach { visitExpr(it) }
            }
            is CtorCall -> {
                e.ctor?.let { offer(e.calleeSpan, it.render(), it.nameSpan) }
                e.spread?.let { visitExpr(it) }
                e.args.forEach { visitExpr(it.expr) }
            }
            is FieldAccess -> {
                visitExpr(e.target)
                e.field?.let { offer(e.fieldSpan, "${it.name}: ${it.type}", it.defSpan) }
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
        when (p) {
            is BindPat -> {
                val sym = p.symbol ?: return
                offer(p.span, "${sym.name}: ${sym.type}", p.span)
            }
            is CtorPat -> {
                p.ctor?.let { offer(p.nameSpan, it.render(), it.nameSpan) }
                p.args.forEach { visitPattern(it.pattern) }
            }
            is TuplePat -> p.elems.forEach { visitPattern(it) }
            is ListPat -> {
                p.pre.forEach { visitPattern(it) }
                p.post.forEach { visitPattern(it) }
                val rest = p.restSymbol
                if (rest != null && p.restSpan != null)
                    offer(p.restSpan!!, "${rest.name}: ${rest.type}", p.restSpan)
            }
            else -> {}
        }
    }

    fun visitStmt(s: Stmt) {
        when (s) {
            is LetStmt -> visitExpr(s.init)
            is LetPatStmt -> {
                visitPattern(s.pattern)
                visitExpr(s.init)
            }
            is AssignStmt -> {
                s.symbol?.let { sym ->
                    val kw = if (sym.mutable) "var" else "let"
                    offer(s.nameSpan, "$kw ${sym.name}: ${sym.type}", sym.defSpan)
                }
                visitExpr(s.value)
            }
            is ExprStmt -> visitExpr(s.expr)
            is AssertStmt -> visitExpr(s.cond)
            is WhileStmt -> { visitExpr(s.cond); visitExpr(s.body) }
            is ForStmt -> { visitExpr(s.from); s.to?.let { visitExpr(it) }; visitExpr(s.body) }
        }
    }
}
