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

    /**
     * In header positions (match scrutinee, if/while conditions, for bounds) a
     * top-level `Type { ... }` record literal would be ambiguous with the block
     * that follows — so it is banned there (same rule as Rust). Any inner
     * bracket/brace re-allows it.
     */
    private var noStructLit = false

    private fun <T> headerExpr(body: () -> T): T {
        val old = noStructLit
        noStructLit = true
        try { return body() } finally { noStructLit = old }
    }

    private fun <T> bracketed(body: () -> T): T {
        val old = noStructLit
        noStructLit = false
        try { return body() } finally { noStructLit = old }
    }

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
        val decls = ArrayList<Decl>()
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
        while (!at(EOF) && !at(FN) && !at(PUB) && !at(TYPE)) advance()
    }

    private fun topDecl(): Decl {
        val pub = if (at(PUB)) { advance(); true } else false
        return when (peek().type) {
            FN -> fnDecl(pub)
            TYPE -> typeDecl(pub)
            CONST, USE, TEST ->
                throw err("`${peek().text}` declarations are not implemented yet",
                    "see the milestones in docs/design.md")
            else -> throw err("only declarations (fn, type) are allowed at module top level")
        }
    }

    // ---- type declarations ----

    /** [T, U] on fn/type declarations */
    private fun typeParams(): List<String> {
        if (!at(LBRACKET)) return emptyList()
        advance()
        val names = ArrayList<String>()
        while (!at(RBRACKET)) {
            names.add(expect(TYPEIDENT, "a type parameter name (uppercase)").text)
            if (at(COMMA)) advance() else break
        }
        expect(RBRACKET, "`]`")
        if (names.isEmpty()) throw err("type parameter list cannot be empty")
        return names
    }

    private fun typeDecl(pub: Boolean): TypeDecl {
        val kw = expect(TYPE, "`type`")
        val name = expect(TYPEIDENT, "a type name (uppercase)")
        val tparams = typeParams()
        expect(EQ, "`=`")
        if (at(LBRACE)) return recordDecl(pub, kw, name, tparams)
        val ctors = ArrayList<CtorDecl>()
        if (at(PIPE)) advance() // leading | is optional
        skipNewlines()
        ctors.add(ctorDecl())
        while (true) {
            // constructors usually sit one per line, | first (like vertical pipes)
            var look = pos
            while (toks[look].type == NEWLINE) look++
            if (toks[look].type != PIPE) break
            pos = look + 1
            skipNewlines()
            ctors.add(ctorDecl())
        }
        return TypeDecl(pub, name.text, tparams, ctors, isRecord = false,
            Span(kw.span.start, ctors.last().span.end), name.span)
    }

    /** type Point = { x: Float, y: Float } — a single-constructor product type */
    private fun recordDecl(pub: Boolean, kw: Token, name: Token, tparams: List<String>): TypeDecl {
        advance() // {
        skipNewlines()
        val fields = ArrayList<FieldDecl>()
        while (!at(RBRACE)) {
            val f = expect(IDENT, "a field name")
            expect(COLON, "`:` (record fields must be typed)")
            val t = typeRef()
            fields.add(FieldDecl(f.text, t, Span(f.span.start, t.span.end)))
            skipNewlines()
            if (at(COMMA)) { advance(); skipNewlines() } else break
        }
        val close = expect(RBRACE, "`}`")
        if (fields.isEmpty())
            throw DawnError("a record must declare at least one field", Span(kw.span.start, close.span.end))
        val ctor = CtorDecl(name.text, fields, Span(name.span.start, close.span.end), name.span)
        return TypeDecl(pub, name.text, tparams, listOf(ctor), isRecord = true,
            Span(kw.span.start, close.span.end), name.span)
    }

    private fun ctorDecl(): CtorDecl {
        val name = expect(TYPEIDENT, "a constructor name (uppercase)")
        val fields = ArrayList<FieldDecl>()
        var end = name.span.end
        if (at(LPAREN)) {
            advance()
            skipNewlines()
            while (!at(RPAREN)) {
                val f = expect(IDENT, "a field name (constructor fields must be named)")
                expect(COLON, "`:` (constructor fields must be typed)")
                val t = typeRef()
                fields.add(FieldDecl(f.text, t, Span(f.span.start, t.span.end)))
                skipNewlines()
                if (at(COMMA)) { advance(); skipNewlines() } else break
            }
            val close = expect(RPAREN, "`)`")
            end = close.span.end
            if (fields.isEmpty())
                throw DawnError("a constructor with `()` must declare at least one field",
                    Span(name.span.start, end), "drop the parentheses for a no-payload constructor: ${name.text}")
        }
        return CtorDecl(name.text, fields, Span(name.span.start, end), name.span)
    }

    private fun fnDecl(pub: Boolean): FnDecl {
        val fnTok = expect(FN, "`fn`")
        val nameTok = expect(IDENT, "a function name (lowercase)")
        val tparams = typeParams()
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
        return FnDecl(pub, nameTok.text, tparams, params, ret, declaredIo, body,
            Span(fnTok.span.start, body.span.end), nameTok.span)
    }

    private fun typeRef(): TypeRef {
        val t = expect(TYPEIDENT, "a type name (uppercase)")
        if (!at(LBRACKET)) return TypeRef(t.text, emptyList(), t.span)
        advance()
        val args = ArrayList<TypeRef>()
        while (!at(RBRACKET)) {
            args.add(typeRef())
            if (at(COMMA)) advance() else break
        }
        val close = expect(RBRACKET, "`]`")
        if (args.isEmpty()) throw err("type argument list cannot be empty")
        return TypeRef(t.text, args, Span(t.span.start, close.span.end))
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
        val cond = headerExpr { expression() }
        val body = block()
        return WhileStmt(cond, body, Span(kw.span.start, body.span.end))
    }

    private fun forStmt(): Stmt {
        val kw = advance()
        val name = expect(IDENT, "a loop variable name")
        expect(IN, "`in`")
        val from = headerExpr { expression() }
        if (!at(DOTDOT)) throw err("for loops support integer ranges only: for i in a..b",
            "list iteration arrives later in M1")
        advance()
        val to = headerExpr { expression() }
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
                QUESTION -> throw err("`?` needs Result/Option, which are not implemented yet")
                DOT -> {
                    advance()
                    val f = expect(IDENT, "a field name after `.`")
                    e = FieldAccess(e, f.text, f.span, Span(e.span.start, f.span.end))
                }
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
            LBRACKET -> listLit()
            FN -> throw err("lambdas are not implemented in M0",
                "use a top-level function name on the right side of |>")
            COMPTIME -> throw err("comptime is not implemented in M0")
            TYPEIDENT -> ctorExpr()
            else -> throw err("expected an expression, found `${t.text}`")
        }
    }

    /** Circle(1.0) / Rect(2.0, h: 3.0) / bare nullary Point / Point { x: 1.0 } / Point { ..p, x: 3.0 } */
    private fun ctorExpr(): Expr {
        val name = advance()
        if (at(LPAREN)) return bracketed { ctorParenArgs(name) }
        if (at(LBRACE) && !noStructLit) return bracketed { recordLit(name) }
        return CtorCall(name.text, emptyList(), spread = null, hasParens = false, name.span, name.span)
    }

    private fun ctorParenArgs(name: Token): Expr {
        advance() // (
        skipNewlines()
        val args = ArrayList<CtorArg>()
        while (!at(RPAREN)) {
            if (at(IDENT) && peek(1).type == COLON) {
                val argName = advance()
                advance() // :
                skipNewlines()
                val value = expression()
                args.add(CtorArg(argName.text, value, Span(argName.span.start, value.span.end)))
            } else {
                val value = expression()
                args.add(CtorArg(null, value, value.span))
            }
            skipNewlines()
            if (at(COMMA)) { advance(); skipNewlines() } else break
        }
        val close = expect(RPAREN, "`)`")
        return CtorCall(name.text, args, spread = null, hasParens = true, name.span,
            Span(name.span.start, close.span.end))
    }

    private fun recordLit(name: Token): Expr {
        advance() // {
        skipNewlines()
        var spread: Expr? = null
        if (at(DOTDOT)) {
            advance()
            spread = expression()
            skipNewlines()
            if (at(COMMA)) { advance(); skipNewlines() }
            else if (!at(RBRACE)) throw err("expected `,` or `}` after the `..base` spread")
        }
        val args = ArrayList<CtorArg>()
        while (!at(RBRACE)) {
            if (at(DOTDOT)) throw err("`..base` must come first in a record literal")
            val f = expect(IDENT, "a field name")
            val value: Expr
            if (at(COLON)) {
                advance()
                skipNewlines()
                value = expression()
            } else {
                value = VarRef(f.text, f.span) // shorthand { x } means { x: x }
            }
            args.add(CtorArg(f.text, value, Span(f.span.start, value.span.end)))
            skipNewlines()
            if (at(COMMA)) { advance(); skipNewlines() } else break
        }
        val close = expect(RBRACE, "`}`")
        return CtorCall(name.text, args, spread, hasParens = true, name.span,
            Span(name.span.start, close.span.end))
    }

    private fun identOrCall(): Expr {
        val name = advance()
        if (at(LPAREN)) {
            return bracketed {
                advance()
                skipNewlines()
                val args = ArrayList<Expr>()
                while (!at(RPAREN)) {
                    args.add(expression())
                    skipNewlines()
                    if (at(COMMA)) { advance(); skipNewlines() } else break
                }
                val close = expect(RPAREN, "`)`")
                Call(name.text, args, name.span, Span(name.span.start, close.span.end))
            }
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

    private fun listLit(): Expr = bracketed {
        val open = advance() // [
        skipNewlines()
        val elems = ArrayList<Expr>()
        while (!at(RBRACKET)) {
            elems.add(expression())
            skipNewlines()
            if (at(COMMA)) { advance(); skipNewlines() } else break
        }
        val close = expect(RBRACKET, "`]`")
        ListLit(elems, Span(open.span.start, close.span.end))
    }

    private fun parenExpr(): Expr {
        val open = advance()
        if (at(RPAREN)) {
            val close = advance()
            return UnitLit(Span(open.span.start, close.span.end))
        }
        return bracketed {
            skipNewlines()
            val e = expression()
            skipNewlines()
            if (at(COMMA)) throw err("tuples are not implemented yet")
            expect(RPAREN, "`)`")
            e
        }
    }

    private fun ifExpr(): Expr {
        val kw = advance()
        val cond = headerExpr { expression() }
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

    private fun block(): Block = bracketed {
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
        finishBlock(open, close, stmts)
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
        val scrut = headerExpr { expression() }
        expect(LBRACE, "`{`")
        return bracketed {
            skipNewlines()
            val arms = ArrayList<MatchArm>()
            while (!at(RBRACE) && !at(EOF)) {
                arms.add(matchArm())
                // arms are separated by newlines or commas
                if (at(COMMA)) { advance(); skipNewlines() } else skipNewlines()
            }
            val close = expect(RBRACE, "`}`")
            if (arms.isEmpty()) throw DawnError("match needs at least one arm", Span(kw.span.start, close.span.end))
            Match(scrut, arms, Span(kw.span.start, close.span.end))
        }
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
            FLOAT -> { advance(); LitPat(FloatLit(t.floatValue, t.span), t.span) }
            MINUS -> {
                advance()
                val span = Span(t.span.start, peek().span.end)
                when {
                    at(INT) -> LitPat(IntLit(-advance().intValue, span), span)
                    at(FLOAT) -> LitPat(FloatLit(-advance().floatValue, span), span)
                    else -> throw err("expected a number after `-` in a pattern")
                }
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
            TYPEIDENT -> ctorPat()
            else -> throw err("expected a pattern")
        }
    }

    /** Circle(r) / Rect(w: w, ..) / bare nullary Point / record Point { x, y: 0, .. } */
    private fun ctorPat(): Pattern {
        val name = advance()
        if (at(LBRACE)) return recordPat(name)
        if (!at(LPAREN)) {
            return CtorPat(name.text, emptyList(), hasRest = false, hasParens = false, name.span, name.span)
        }
        advance()
        skipNewlines()
        val args = ArrayList<PatArg>()
        var rest = false
        while (!at(RPAREN)) {
            if (at(DOTDOT)) {
                advance()
                rest = true
                skipNewlines()
                if (!at(RPAREN)) throw err("`..` must be the last thing in a constructor pattern")
                break
            }
            if (at(IDENT) && peek(1).type == COLON) {
                val argName = advance()
                advance() // :
                skipNewlines()
                args.add(PatArg(argName.text, pattern()))
            } else {
                args.add(PatArg(null, pattern()))
            }
            skipNewlines()
            if (at(COMMA)) { advance(); skipNewlines() } else break
        }
        val close = expect(RPAREN, "`)`")
        return CtorPat(name.text, args, rest, hasParens = true, name.span, Span(name.span.start, close.span.end))
    }

    /** Point { x, y: 0, .. } — field shorthand `x` binds the field to `x` */
    private fun recordPat(name: Token): Pattern {
        advance() // {
        skipNewlines()
        val args = ArrayList<PatArg>()
        var rest = false
        while (!at(RBRACE)) {
            if (at(DOTDOT)) {
                advance()
                rest = true
                skipNewlines()
                if (!at(RBRACE)) throw err("`..` must be the last thing in a record pattern")
                break
            }
            val f = expect(IDENT, "a field name")
            val sub: Pattern
            if (at(COLON)) {
                advance()
                skipNewlines()
                sub = pattern()
            } else {
                sub = BindPat(f.text, f.span) // shorthand { x } binds field x to x
            }
            args.add(PatArg(f.text, sub))
            skipNewlines()
            if (at(COMMA)) { advance(); skipNewlines() } else break
        }
        val close = expect(RBRACE, "`}`")
        return CtorPat(name.text, args, rest, hasParens = true, name.span, Span(name.span.start, close.span.end))
    }
}
