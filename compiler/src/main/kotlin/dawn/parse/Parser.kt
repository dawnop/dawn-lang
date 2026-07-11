package dawn.parse

import dawn.ast.*
import dawn.diag.DawnError
import dawn.diag.DiagnosticSink
import dawn.diag.Span
import dawn.lex.Lexer
import dawn.lex.StrSegment
import dawn.lex.Token
import dawn.lex.TokenType
import dawn.lex.TokenType.*

/**
 * Recursive descent. M0 subset: fn declarations + statements + expressions.
 * Top-level declarations beyond M0 (type/const/use/test) get explicit
 * "not implemented" errors.
 *
 * Error recovery: parse failures throw DawnError internally; recovery points
 * (statement and declaration boundaries) catch it, report to the sink, and
 * resynchronize — so one broken statement never hides the rest of the file.
 */
class Parser(tokens: List<Token>, private val sink: DiagnosticSink = DiagnosticSink()) {

    private val toks = tokens
    private var pos = 0

    // ---- token cursor ----

    private fun peek(ahead: Int = 0): Token = toks[(pos + ahead).coerceAtMost(toks.size - 1)]
    private fun at(type: TokenType) = peek().type == type
    private fun advance(): Token = toks[pos].also { if (pos < toks.size - 1) pos++ }

    private fun expect(type: TokenType, what: String): Token {
        if (!at(type)) throw err("expected $what, found `${peek().text}`")
        return advance()
    }

    private fun err(msg: String, hint: String? = null) = DawnError(msg, peek().span, hint)

    private fun skipNewlines() {
        while (at(NEWLINE)) advance()
    }

    /** Separator between statements/declarations: at least one NEWLINE (or block end / EOF). */
    private fun expectSeparator() {
        if (at(NEWLINE)) { skipNewlines(); return }
        if (at(RBRACE) || at(EOF)) return
        throw err("expected a newline after this statement",
            "one statement per line; check whether the previous statement is complete")
    }

    // ---- module ----

    fun module(): Module {
        val decls = ArrayList<FnDecl>()
        skipNewlines()
        while (!at(EOF)) {
            try {
                decls.add(topDecl())
            } catch (e: DawnError) {
                sink.add(e)
                syncToNextDecl()
            }
            skipNewlines()
        }
        return Module(decls)
    }

    /** After a broken declaration: skip forward to the next plausible declaration start. */
    private fun syncToNextDecl() {
        if (!at(EOF)) advance() // always make progress
        while (!at(EOF) && !at(FN) && !at(PUB)) advance()
    }

    private fun topDecl(): FnDecl {
        val pub = if (at(PUB)) { advance(); true } else false
        return when (peek().type) {
            FN -> fnDecl(pub)
            TYPE, CONST, USE, TEST ->
                throw err("`${peek().text}` declarations are not implemented in M0",
                    "M0 supports fn only; see the milestones in docs/design.md")
            else -> throw err("only declarations (fn) are allowed at module top level")
        }
    }

    private fun fnDecl(pub: Boolean): FnDecl {
        val fnTok = expect(FN, "`fn`")
        val nameTok = expect(IDENT, "a function name (lowercase)")
        expect(LPAREN, "`(`")
        val params = ArrayList<Param>()
        skipNewlines()
        while (!at(RPAREN)) {
            val pName = expect(IDENT, "a parameter name")
            expect(COLON, "`:` (top-level function parameters must be typed)")
            val pType = typeRef()
            params.add(Param(pName.text, pType, pName.span))
            skipNewlines()
            if (at(COMMA)) { advance(); skipNewlines() } else break
        }
        expect(RPAREN, "`)`")
        expect(ARROW, "`->` (top-level functions must declare a return type)")
        val ret = typeRef()
        var declaredIo = false
        if (at(BANG)) {
            advance()
            val eff = expect(IDENT, "an effect name")
            if (eff.text != "io") throw DawnError("unknown effect: ${eff.text}", eff.span,
                "io is the only effect in v0.1")
            declaredIo = true
        }
        expect(EQ, "`=` (function body)")
        skipNewlines()
        val body = expression()
        return FnDecl(pub, nameTok.text, params, ret, declaredIo, body,
            Span(fnTok.span.start, body.span.end), nameTok.span)
    }

    private fun typeRef(): TypeRef {
        val t = expect(TYPEIDENT, "a type name (uppercase)")
        if (at(LBRACKET)) throw err("generic types are not implemented in M0")
        return TypeRef(t.text, t.span)
    }

    // ---- statements ----

    private fun statement(): Stmt {
        return when (peek().type) {
            LET -> letStmt(mutable = false)
            VAR -> letStmt(mutable = true)
            WHILE -> whileStmt()
            FOR -> forStmt()
            ASSERT -> throw err("`assert` is only allowed inside test blocks (tests are not implemented in M0)")
            IDENT -> {
                // assignment: IDENT = ... (as opposed to == comparison)
                if (peek(1).type == EQ) assignStmt() else exprStmt()
            }
            else -> exprStmt()
        }
    }

    private fun letStmt(mutable: Boolean): Stmt {
        val kw = advance() // let / var
        val name = when {
            at(IDENT) -> advance()
            at(UNDERSCORE) -> {
                if (mutable) throw err("`var _` is meaningless")
                advance()
            }
            else -> throw err("expected a variable name")
        }
        val ann = if (at(COLON)) { advance(); typeRef() } else null
        expect(EQ, "`=`")
        skipNewlines()
        val init = expression()
        return LetStmt(name.text, mutable, ann, init, Span(kw.span.start, init.span.end))
    }

    private fun assignStmt(): Stmt {
        val name = advance()
        advance() // =
        skipNewlines()
        val value = expression()
        return AssignStmt(name.text, value, name.span, Span(name.span.start, value.span.end))
    }

    private fun whileStmt(): Stmt {
        val kw = advance()
        val cond = expression()
        val body = block()
        return WhileStmt(cond, body, Span(kw.span.start, body.span.end))
    }

    private fun forStmt(): Stmt {
        val kw = advance()
        val name = expect(IDENT, "a loop variable name")
        expect(IN, "`in`")
        val from = expression()
        if (!at(DOTDOT)) throw err("M0 for loops support integer ranges only: for i in a..b",
            "list iteration arrives in M1")
        advance()
        val to = expression()
        val body = block()
        return ForStmt(name.text, from, to, body, Span(kw.span.start, body.span.end))
    }

    private fun exprStmt(): Stmt {
        val e = expression()
        return ExprStmt(e, e.span)
    }

    // ---- expressions (by precedence) ----

    fun expression(): Expr = pipeExpr()

    private fun pipeExpr(): Expr {
        var left = orExpr()
        while (true) {
            // vertical pipes: |> may start the next line
            var look = pos
            while (toks[look].type == NEWLINE) look++
            if (toks[look].type != PIPEGT) break
            pos = look + 1
            skipNewlines()
            val rhs = orExpr()
            left = when (rhs) {
                is Call -> Call(rhs.callee, listOf(left) + rhs.args, rhs.calleeSpan,
                    Span(left.span.start, rhs.span.end))
                is VarRef -> Call(rhs.name, listOf(left), rhs.span,
                    Span(left.span.start, rhs.span.end))
                else -> throw DawnError("the right side of `|>` must be a call or a function name", rhs.span,
                    "x |> f(a) is equivalent to f(x, a)")
            }
        }
        return left
    }

    private fun orExpr(): Expr = leftAssoc({ andExpr() }, mapOf(PIPEPIPE to BinOp.OR))
    private fun andExpr(): Expr = leftAssoc({ cmpExpr() }, mapOf(AMPAMP to BinOp.AND))

    private fun cmpExpr(): Expr {
        val left = concatExpr()
        val op = when (peek().type) {
            EQEQ -> BinOp.EQ; NEQ -> BinOp.NEQ
            LT -> BinOp.LT; LE -> BinOp.LE; GT -> BinOp.GT; GE -> BinOp.GE
            else -> return left
        }
        val opTok = advance()
        skipNewlines()
        val right = concatExpr()
        val result = Binary(op, left, right, opTok.span, Span(left.span.start, right.span.end))
        // comparisons are non-associative: a < b < c is an error
        when (peek().type) {
            EQEQ, NEQ, LT, LE, GT, GE ->
                throw err("comparison operators cannot be chained", "write a < b && b < c")
            else -> {}
        }
        return result
    }

    private fun concatExpr(): Expr {
        // right-associative
        val left = addExpr()
        if (!at(PLUSPLUS)) return left
        val opTok = advance()
        skipNewlines()
        val right = concatExpr()
        return Binary(BinOp.CONCAT, left, right, opTok.span, Span(left.span.start, right.span.end))
    }

    private fun addExpr(): Expr = leftAssoc({ mulExpr() }, mapOf(PLUS to BinOp.ADD, MINUS to BinOp.SUB))
    private fun mulExpr(): Expr =
        leftAssoc({ unaryExpr() }, mapOf(STAR to BinOp.MUL, SLASH to BinOp.DIV, PERCENT to BinOp.MOD))

    private fun leftAssoc(next: () -> Expr, ops: Map<TokenType, BinOp>): Expr {
        var left = next()
        while (ops.containsKey(peek().type)) {
            val opTok = advance()
            skipNewlines()
            val right = next()
            left = Binary(ops[opTok.type]!!, left, right, opTok.span, Span(left.span.start, right.span.end))
        }
        return left
    }

    private fun unaryExpr(): Expr {
        if (at(NOT)) {
            val tok = advance()
            val operand = unaryExpr()
            return Unary(UnOp.NOT, operand, Span(tok.span.start, operand.span.end))
        }
        if (at(MINUS)) {
            val tok = advance()
            val operand = unaryExpr()
            return Unary(UnOp.NEG, operand, Span(tok.span.start, operand.span.end))
        }
        return postfixExpr()
    }

    private fun postfixExpr(): Expr {
        var e = primaryExpr()
        while (true) {
            when (peek().type) {
                QUESTION -> throw err("`?` needs Result/Option, which are not implemented in M0")
                DOT -> throw err("`.` field/method access is not implemented in M0")
                else -> return e
            }
        }
    }

    private fun primaryExpr(): Expr {
        val t = peek()
        return when (t.type) {
            INT -> { advance(); IntLit(t.intValue, t.span) }
            FLOAT -> { advance(); FloatLit(t.floatValue, t.span) }
            TRUE -> { advance(); BoolLit(true, t.span) }
            FALSE -> { advance(); BoolLit(false, t.span) }
            STRING -> { advance(); strLit(t) }
            IDENT -> identOrCall()
            IF -> ifExpr()
            MATCH -> matchExpr()
            LBRACE -> block()
            LPAREN -> parenExpr()
            LBRACKET -> throw err("list literals are not implemented in M0")
            FN -> throw err("lambdas are not implemented in M0",
                "use a top-level function name on the right side of |>")
            COMPTIME -> throw err("comptime is not implemented in M0")
            TYPEIDENT -> throw err("constructor/type expressions are not implemented in M0 (no ADTs yet)")
            else -> throw err("expected an expression, found `${t.text}`")
        }
    }

    private fun identOrCall(): Expr {
        val name = advance()
        if (at(LPAREN)) {
            advance()
            skipNewlines()
            val args = ArrayList<Expr>()
            while (!at(RPAREN)) {
                args.add(expression())
                skipNewlines()
                if (at(COMMA)) { advance(); skipNewlines() } else break
            }
            val close = expect(RPAREN, "`)`")
            return Call(name.text, args, name.span, Span(name.span.start, close.span.end))
        }
        return VarRef(name.text, name.span)
    }

    private fun strLit(t: Token): Expr {
        val parts = ArrayList<StrPart>()
        for (seg in t.segments) {
            when (seg) {
                is StrSegment.Text -> parts.add(StrPart.Text(seg.value))
                is StrSegment.Code -> {
                    val sub = Parser(Lexer(seg.source, seg.offset, sink).lex(), sink)
                    val e = sub.expression()
                    sub.skipNewlines()
                    if (!sub.at(EOF)) throw DawnError("trailing content in interpolation", sub.peek().span)
                    parts.add(StrPart.Interp(e))
                }
            }
        }
        return StrLit(parts, t.span)
    }

    private fun parenExpr(): Expr {
        val open = advance()
        if (at(RPAREN)) {
            val close = advance()
            return UnitLit(Span(open.span.start, close.span.end))
        }
        skipNewlines()
        val e = expression()
        skipNewlines()
        if (at(COMMA)) throw err("tuples are not implemented in M0")
        expect(RPAREN, "`)`")
        return e
    }

    private fun ifExpr(): Expr {
        val kw = advance()
        val cond = expression()
        val thenB = block()
        var elseB: Expr? = null
        // else may sit on the line after }
        val save = pos
        skipNewlines()
        if (at(ELSE)) {
            advance()
            elseB = if (at(IF)) ifExpr() else block()
        } else {
            pos = save
        }
        val end = elseB?.span?.end ?: thenB.span.end
        return If(cond, thenB, elseB, Span(kw.span.start, end))
    }

    private fun block(): Block {
        val open = expect(LBRACE, "`{`")
        skipNewlines()
        val stmts = ArrayList<Stmt>()
        while (!at(RBRACE) && !at(EOF)) {
            try {
                stmts.add(statement())
                expectSeparator()
            } catch (e: DawnError) {
                sink.add(e)
                syncToNextStmt()
            }
        }
        val close = expect(RBRACE, "`}`")
        return finishBlock(open, close, stmts)
    }

    /** After a broken statement: skip to the next line (or block end) and continue. */
    private fun syncToNextStmt() {
        while (!at(NEWLINE) && !at(RBRACE) && !at(EOF)) advance()
        skipNewlines()
    }

    private fun finishBlock(open: Token, close: Token, stmts: ArrayList<Stmt>): Block {
        // trailing expression rule: a final plain expression statement is the block's value
        var tail: Expr? = null
        if (stmts.isNotEmpty() && stmts.last() is ExprStmt) {
            tail = (stmts.removeLast() as ExprStmt).expr
        }
        return Block(stmts, tail, Span(open.span.start, close.span.end))
    }

    private fun matchExpr(): Expr {
        val kw = advance()
        val scrut = expression()
        expect(LBRACE, "`{`")
        skipNewlines()
        val arms = ArrayList<MatchArm>()
        while (!at(RBRACE) && !at(EOF)) {
            arms.add(matchArm())
            // arms are separated by newlines or commas
            if (at(COMMA)) { advance(); skipNewlines() } else skipNewlines()
        }
        val close = expect(RBRACE, "`}`")
        if (arms.isEmpty()) throw DawnError("match needs at least one arm", Span(kw.span.start, close.span.end))
        return Match(scrut, arms, Span(kw.span.start, close.span.end))
    }

    private fun matchArm(): MatchArm {
        val patterns = ArrayList<Pattern>()
        patterns.add(pattern())
        while (at(PIPE)) { advance(); skipNewlines(); patterns.add(pattern()) }
        var guard: Expr? = null
        if (at(IF)) { advance(); guard = expression() }
        expect(ARROW, "`->`")
        skipNewlines()
        val body = expression()
        return MatchArm(patterns, guard, body, Span(patterns.first().span.start, body.span.end))
    }

    private fun pattern(): Pattern {
        val t = peek()
        return when (t.type) {
            UNDERSCORE -> { advance(); WildPat(t.span) }
            INT -> { advance(); LitPat(IntLit(t.intValue, t.span), t.span) }
            MINUS -> {
                advance()
                val n = expect(INT, "a number")
                LitPat(IntLit(-n.intValue, n.span), Span(t.span.start, n.span.end))
            }
            TRUE -> { advance(); LitPat(BoolLit(true, t.span), t.span) }
            FALSE -> { advance(); LitPat(BoolLit(false, t.span), t.span) }
            STRING -> {
                advance()
                val lit = strLit(t)
                if ((lit as StrLit).parts.any { it is StrPart.Interp })
                    throw DawnError("string patterns cannot contain interpolation", t.span)
                LitPat(lit, t.span)
            }
            IDENT -> { advance(); BindPat(t.text, t.span) }
            TYPEIDENT -> throw err("constructor patterns are not implemented in M0 (no ADTs yet)")
            else -> throw err("expected a pattern")
        }
    }
}
