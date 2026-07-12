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
private val BUILTIN_SCALARS = setOf("Int", "Float", "Bool", "String", "Unit")

class Parser(
    tokens: List<Token>,
    private val sink: DiagnosticSink = DiagnosticSink(),
    /** original source text, for slicing assert messages; null in sub-parsers */
    private val source: String? = null,
) {

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
        while (!at(EOF) && !at(FN) && !at(PUB) && !at(TYPE) && !at(CONST) && !at(TRAIT) && !at(IMPL)) advance()
    }

    private fun topDecl(): Decl {
        val pub = if (at(PUB)) { advance(); true } else false
        return when (peek().type) {
            FN -> fnDecl(pub)
            TYPE -> typeDecl(pub)
            CONST -> constDecl(pub)
            TRAIT -> traitDecl(pub)
            IMPL -> {
                if (pub) throw err("an impl cannot be pub (its visibility follows the trait)")
                implDecl()
            }
            TEST -> {
                if (pub) throw err("test blocks cannot be pub")
                testDecl()
            }
            USE -> {
                if (pub) throw err("use declarations cannot be pub")
                useDecl()
            }
            else -> throw err("only declarations (fn, type, const, trait, impl, test) are allowed at module top level")
        }
    }

    /** use java "..." (spec §9) or use path/to/module[.{A, b}] (spec §10) */
    private fun useDecl(): Decl {
        val kw = advance() // use
        if (at(JAVA)) return javaUse(kw)
        return moduleUse(kw)
    }

    private fun javaUse(kw: Token): Decl {
        advance() // java
        val s = expect(STRING, "a quoted fully-qualified class name")
        if (s.segments.any { it is StrSegment.Code })
            throw DawnError("a class name cannot contain interpolation", s.span)
        val fqcn = s.segments.joinToString("") { (it as StrSegment.Text).value }
        if (fqcn.isBlank() || fqcn.substringAfterLast('.').firstOrNull()?.isUpperCase() != true)
            throw DawnError("expected a fully-qualified class name like \"java.lang.StringBuilder\"", s.span)
        return UseJavaDecl(fqcn, Span(kw.span.start, s.span.end), s.span)
    }

    /** use json/lexer  or  use json/value.{Json, render} (spec §10.2) */
    private fun moduleUse(kw: Token): Decl {
        val segs = ArrayList<String>()
        val first = expect(IDENT, "a module path (like json/lexer) or `java`")
        segs.add(first.text)
        var endSpan = first.span
        while (at(SLASH)) {
            advance()
            val seg = expect(IDENT, "a module path segment (lowercase)")
            segs.add(seg.text)
            endSpan = seg.span
        }
        val nameSpan = Span(first.span.start, endSpan.end)
        var selective: List<ImportName>? = null
        if (at(DOT)) {
            advance()
            expect(LBRACE, "`{` to open a selective import list")
            val names = ArrayList<ImportName>()
            skipNewlines()
            while (!at(RBRACE)) {
                val n = when {
                    at(IDENT) -> advance()
                    at(TYPEIDENT) -> advance()
                    else -> throw err("expected an imported name (a function, type, or constant)")
                }
                names.add(ImportName(n.text, n.span))
                skipNewlines()
                if (at(COMMA)) { advance(); skipNewlines() } else break
            }
            val close = expect(RBRACE, "`}`")
            if (names.isEmpty())
                throw DawnError("a selective import needs at least one name", Span(nameSpan.start, close.span.end),
                    "use `use ${segs.joinToString("/")}` to import the whole module")
            selective = names
            endSpan = close.span
        }
        return UseModuleDecl(segs, selective, Span(kw.span.start, endSpan.end), nameSpan)
    }

    /** const NAME: Type = expr — the initializer is implicitly comptime (spec §3.2) */
    private fun constDecl(pub: Boolean): ConstDecl {
        val kw = expect(CONST, "`const`")
        val name = expect(TYPEIDENT, "a constant name (SCREAMING_SNAKE_CASE)")
        if (name.text.any { it.isLowerCase() })
            throw DawnError("constant names are SCREAMING_SNAKE_CASE", name.span,
                "lowercase names are values, UpperCamelCase names are types/constructors (spec §1.3)")
        expect(COLON, "`:` (constants must declare their type)")
        val t = typeRef()
        expect(EQ, "`=`")
        skipNewlines()
        val init = expression()
        return ConstDecl(pub, name.text, t, init, Span(kw.span.start, init.span.end), name.span)
    }

    /** test "name" { ... } */
    private fun testDecl(): TestDecl {
        val kw = advance() // test
        val nameTok = expect(STRING, "a test name string")
        if (nameTok.segments.any { it is StrSegment.Code })
            throw DawnError("test names cannot contain interpolation", nameTok.span)
        val name = nameTok.segments.joinToString("") { (it as StrSegment.Text).value }
        val body = block()
        return TestDecl(name, body, Span(kw.span.start, body.span.end), nameTok.span)
    }

    // ---- type declarations ----

    /** [T, U] on fn/type declarations, with optional bounds on fns: [T: Ord + Show] */
    private fun typeParams(): List<TypeParamDecl> {
        if (!at(LBRACKET)) return emptyList()
        advance()
        val out = ArrayList<TypeParamDecl>()
        while (!at(RBRACKET)) {
            val n = expect(TYPEIDENT, "a type parameter name (uppercase)")
            val bounds = ArrayList<Pair<String, Span>>()
            if (at(COLON)) {
                advance()
                val first = expect(TYPEIDENT, "a trait name after `:`")
                bounds.add(first.text to first.span)
                while (at(PLUS)) {
                    advance()
                    val b = expect(TYPEIDENT, "a trait name after `+`")
                    bounds.add(b.text to b.span)
                }
            }
            val end = bounds.lastOrNull()?.second?.end ?: n.span.end
            out.add(TypeParamDecl(n.text, bounds, Span(n.span.start, end)))
            if (at(COMMA)) advance() else break
        }
        expect(RBRACKET, "`]`")
        if (out.isEmpty()) throw err("type parameter list cannot be empty")
        return out
    }

    private fun typeDecl(pub: Boolean): TypeDecl {
        val kw = expect(TYPE, "`type`")
        val name = expect(TYPEIDENT, "a type name (uppercase)")
        val tparamDecls = typeParams()
        tparamDecls.firstOrNull { it.bounds.isNotEmpty() }?.let {
            throw DawnError("type declarations cannot constrain their type parameters", it.span,
                "trait bounds go on the functions that use the type: fn f[T: Ord](...)")
        }
        val tparams = tparamDecls.map { it.name }
        expect(EQ, "`=`")
        if (at(LBRACE)) return recordDecl(pub, kw, name, tparams)
        // a type alias: an RHS that cannot begin a constructor list — a fn type,
        // a tuple, a generic application Name[...], or a bare builtin scalar
        // (`type Meters = Float`; those names can never be constructors). Any
        // other bare uppercase name stays a single-constructor ADT (back-compat).
        val builtinScalar = at(TYPEIDENT) && toks[pos].text in BUILTIN_SCALARS &&
            toks[pos + 1].type != LPAREN
        if (at(FN) || at(LPAREN) || (at(TYPEIDENT) && toks[pos + 1].type == LBRACKET) || builtinScalar) {
            val target = typeRef()
            return TypeDecl(pub, name.text, tparams, emptyList(), isRecord = false,
                Span(kw.span.start, target.span.end), name.span, aliasTarget = target)
        }
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
        val derives = parseDerives()
        val end = derives.lastOrNull()?.second?.end ?: ctors.last().span.end
        return TypeDecl(pub, name.text, tparams, ctors, isRecord = false,
            Span(kw.span.start, end), name.span, derives)
    }

    /**
     * Optional trailing `derive Name (, Name)*` on a type declaration. `derive` is a
     * soft keyword (a plain identifier), so this peeks without consuming when absent.
     */
    private fun parseDerives(): List<Pair<String, Span>> {
        var look = pos
        while (toks[look].type == NEWLINE) look++
        if (!(toks[look].type == IDENT && toks[look].text == "derive")) return emptyList()
        pos = look + 1
        val out = ArrayList<Pair<String, Span>>()
        val first = expect(TYPEIDENT, "a trait name to derive (only Show in v0.1)")
        out.add(first.text to first.span)
        while (at(COMMA)) {
            advance()
            val n = expect(TYPEIDENT, "a trait name to derive")
            out.add(n.text to n.span)
        }
        return out
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
        val derives = parseDerives()
        val end = derives.lastOrNull()?.second?.end ?: close.span.end
        return TypeDecl(pub, name.text, tparams, listOf(ctor), isRecord = true,
            Span(kw.span.start, end), name.span, derives)
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

    private fun fnDecl(pub: Boolean, inImpl: Boolean = false): FnDecl {
        val fnTok = expect(FN, "`fn`")
        val nameTok = expect(IDENT, "a function name (lowercase)")
        val tparams = typeParams()
        if (inImpl && tparams.isNotEmpty())
            throw DawnError("impl methods cannot declare their own type parameters", tparams.first().span)
        expect(LPAREN, "`(`")
        val params = typedParams("top-level function")
        expect(RPAREN, "`)`")
        // pub functions are API: their full signature is the contract. Private
        // functions may leave the return type (and effect) to inference. Impl
        // methods must repeat the trait's signature in full.
        val ret: TypeRef? = when {
            at(ARROW) -> { advance(); typeRef() }
            inImpl -> { expect(ARROW, "`->` (impl methods must declare their full signature)"); null }
            pub -> { expect(ARROW, "`->` (pub functions must declare a return type)"); null }
            else -> null
        }
        val declaredEff = parseEffect()
        expect(EQ, "`=` (function body)")
        skipNewlines()
        val body = expression()
        return FnDecl(pub, nameTok.text, tparams, params, ret, declaredEff, body,
            Span(fnTok.span.start, body.span.end), nameTok.span)
    }

    /** name: Type, ... — the shared typed parameter list of fn/trait declarations */
    private fun typedParams(what: String): List<Param> {
        val params = ArrayList<Param>()
        skipNewlines()
        while (!at(RPAREN)) {
            val pName = expect(IDENT, "a parameter name")
            expect(COLON, "`:` ($what parameters must be typed)")
            val pType = typeRef()
            params.add(Param(pName.text, pType, pName.span))
            skipNewlines()
            if (at(COMMA)) { advance(); skipNewlines() } else break
        }
        return params
    }

    // ---- trait and impl declarations ----

    /** trait Ord[T] { fn cmp(a: T, b: T) -> Int ... } — exactly one type parameter */
    private fun traitDecl(pub: Boolean): TraitDecl {
        val kw = expect(TRAIT, "`trait`")
        val name = expect(TYPEIDENT, "a trait name (uppercase)")
        expect(LBRACKET, "`[` (a trait declares its subject type parameter: trait ${name.text}[T])")
        val tp = expect(TYPEIDENT, "a type parameter name (uppercase)")
        if (at(COMMA))
            throw err("a trait has exactly one type parameter")
        if (at(COLON))
            throw err("the trait's own type parameter cannot have bounds",
                "supertraits are not supported")
        expect(RBRACKET, "`]`")
        skipNewlines()
        expect(LBRACE, "`{` (the trait body)")
        skipNewlines()
        val methods = ArrayList<TraitMethod>()
        while (!at(RBRACE) && !at(EOF)) {
            methods.add(traitMethod())
            expectSeparator()
        }
        val close = expect(RBRACE, "`}`")
        if (methods.isEmpty())
            throw DawnError("a trait must declare at least one method", Span(kw.span.start, close.span.end))
        return TraitDecl(pub, name.text, tp.text, tp.span, methods,
            Span(kw.span.start, close.span.end), name.span)
    }

    /** fn cmp(a: T, b: T) -> Int [!io] [= default-body] */
    private fun traitMethod(): TraitMethod {
        val fnTok = expect(FN, "`fn` (a trait body only contains method declarations)")
        val nameTok = expect(IDENT, "a method name (lowercase)")
        if (at(LBRACKET))
            throw err("trait methods cannot declare their own type parameters",
                "the trait's subject type parameter is already in scope")
        expect(LPAREN, "`(`")
        val params = typedParams("trait method")
        expect(RPAREN, "`)`")
        expect(ARROW, "`->` (trait methods must declare a return type)")
        val ret = typeRef()
        val declaredEff = parseEffect()
        var body: Expr? = null
        if (at(EQ)) {
            advance()
            skipNewlines()
            body = expression()
        }
        val end = body?.span?.end ?: peek(-1).span.end
        return TraitMethod(nameTok.text, params, ret, declaredEff, body,
            Span(fnTok.span.start, end), nameTok.span)
    }

    /** impl Ord[Point] { fn cmp(a: Point, b: Point) -> Int = ... } */
    private fun implDecl(): ImplDecl {
        val kw = expect(IMPL, "`impl`")
        val trait = expect(TYPEIDENT, "a trait name (uppercase)")
        expect(LBRACKET, "`[` (an impl names its subject type: impl ${trait.text}[Point])")
        val subject = typeRef()
        expect(RBRACKET, "`]`")
        skipNewlines()
        expect(LBRACE, "`{` (the impl body)")
        skipNewlines()
        val methods = ArrayList<FnDecl>()
        while (!at(RBRACE) && !at(EOF)) {
            if (at(PUB))
                throw err("impl methods cannot be pub (their visibility follows the trait)")
            methods.add(fnDecl(pub = false, inImpl = true))
            expectSeparator()
        }
        val close = expect(RBRACE, "`}`")
        return ImplDecl(trait.text, trait.span, subject, methods, Span(kw.span.start, close.span.end))
    }

    private fun typeRef(): TypeRef {
        if (at(FN)) return fnTypeRef()
        if (at(LPAREN)) return tupleTypeRef()
        val t = expect(TYPEIDENT, "a type name (uppercase)")
        if (!at(LBRACKET)) return NamedTypeRef(t.text, emptyList(), t.span)
        advance()
        val args = ArrayList<TypeRef>()
        while (!at(RBRACKET)) {
            args.add(typeRef())
            if (at(COMMA)) advance() else break
        }
        val close = expect(RBRACKET, "`]`")
        if (args.isEmpty()) throw err("type argument list cannot be empty")
        return NamedTypeRef(t.text, args, Span(t.span.start, close.span.end))
    }

    /** (A, B) — tuple type, 2 to 8 elements */
    private fun tupleTypeRef(): TypeRef {
        val open = advance() // (
        val elems = ArrayList<TypeRef>()
        while (!at(RPAREN)) {
            elems.add(typeRef())
            if (at(COMMA)) advance() else break
        }
        val close = expect(RPAREN, "`)`")
        val span = Span(open.span.start, close.span.end)
        if (elems.size < 2)
            throw DawnError("a tuple type needs at least 2 elements", span,
                "for a single type, drop the parentheses")
        if (elems.size > 8) throw DawnError("tuples have at most 8 elements", span)
        return TupleTypeRef(elems, span)
    }

    /** fn(A, B) -> C !e */
    private fun fnTypeRef(): TypeRef {
        val kw = advance() // fn
        expect(LPAREN, "`(`")
        val params = ArrayList<TypeRef>()
        while (!at(RPAREN)) {
            params.add(typeRef())
            if (at(COMMA)) advance() else break
        }
        expect(RPAREN, "`)`")
        expect(ARROW, "`->`")
        val ret = typeRef()
        val effAtoms = parseEffect()
        val end = peek(-1).span.end // last token consumed (the ret type or the effect)
        return FnTypeRef(params, ret, effAtoms, Span(kw.span.start, end))
    }

    /**
     * Parse an optional effect annotation after a return type: nothing (pure),
     * `!io`, `!e`, or a union `!(e1 | e2 | ...)`. Returns the atom names.
     */
    private fun parseEffect(): List<String> {
        if (!at(BANG)) return emptyList()
        advance()
        if (!at(LPAREN)) {
            return listOf(expect(IDENT, "an effect name (io or an effect variable)").text)
        }
        advance() // (
        val atoms = ArrayList<String>()
        atoms.add(expect(IDENT, "an effect name (io or an effect variable)").text)
        while (at(PIPE)) {
            advance()
            atoms.add(expect(IDENT, "an effect name (io or an effect variable)").text)
        }
        expect(RPAREN, "`)` to close the effect union")
        return atoms
    }

    // ---- statements ----

    private fun statement(): Stmt {
        return when (peek().type) {
            LET -> letStmt(mutable = false)
            VAR -> letStmt(mutable = true)
            WHILE -> whileStmt()
            FOR -> forStmt()
            ASSERT -> assertStmt()
            IDENT -> {
                // assignment: IDENT = ... (as opposed to == comparison)
                if (peek(1).type == EQ) assignStmt() else exprStmt()
            }
            // `fn name(...)` is a local function; a bare `fn(...)` stays a lambda expression
            FN -> if (peek(1).type == IDENT) localFnStmt() else exprStmt()
            else -> exprStmt()
        }
    }

    private fun localFnStmt(): Stmt {
        val fnTok = advance() // fn
        val nameTok = expect(IDENT, "a function name (lowercase)")
        if (at(LBRACKET))
            throw err("local functions cannot declare type parameters",
                "the enclosing function's type parameters are in scope; or lift it to the top level")
        expect(LPAREN, "`(`")
        val params = ArrayList<LambdaParam>()
        skipNewlines()
        while (!at(RPAREN)) {
            val pName = expect(IDENT, "a parameter name")
            expect(COLON, "`:` (local function parameters must be typed)")
            val pType = typeRef()
            params.add(LambdaParam(pName.text, pType, pName.span))
            skipNewlines()
            if (at(COMMA)) { advance(); skipNewlines() } else break
        }
        expect(RPAREN, "`)`")
        expect(ARROW, "`->` (local functions must declare a return type)")
        val ret = typeRef()
        val effNames = parseEffect()
        expect(EQ, "`=` (function body)")
        skipNewlines()
        val body = expression()
        val span = Span(fnTok.span.start, body.span.end)
        return LocalFnStmt(nameTok.text, Lambda(params, body, span), ret, effNames, nameTok.span, span)
    }

    private fun letStmt(mutable: Boolean): Stmt {
        val kw = advance() // let / var
        // destructuring: let (a, b) = pair / let Point { x, y } = p / let [..all] = xs
        if (at(LPAREN) || at(TYPEIDENT) || at(LBRACKET)) {
            val pat = pattern()
            if (at(COLON))
                throw err("destructuring lets cannot take a type annotation",
                    "annotate inside the pattern's source instead")
            expect(EQ, "`=`")
            skipNewlines()
            val init = expression()
            return LetPatStmt(pat, mutable, init, Span(kw.span.start, init.span.end))
        }
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
        var to: Expr? = null
        if (at(DOTDOT)) {
            advance()
            to = headerExpr { expression() }
        }
        val body = block()
        return ForStmt(name.text, from, to, body, Span(kw.span.start, body.span.end))
    }

    private fun exprStmt(): Stmt {
        val e = expression()
        return ExprStmt(e, e.span)
    }

    private fun assertStmt(): Stmt {
        val kw = advance() // assert
        val cond = expression()
        val stmt = AssertStmt(cond, Span(kw.span.start, cond.span.end))
        stmt.sourceText = source?.substring(cond.span.start, cond.span.end.coerceAtMost(source.length))
        return stmt
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
                is Lambda -> Apply(rhs, listOf(left), Span(left.span.start, rhs.span.end))
                else -> throw DawnError("the right side of `|>` must be a call, a function name, or a lambda",
                    rhs.span, "x |> f(a) is equivalent to f(x, a)")
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
                QUESTION -> {
                    val q = advance()
                    e = Propagate(e, Span(e.span.start, q.span.end))
                }
                LBRACKET -> {
                    e = bracketed {
                        advance()
                        skipNewlines()
                        val idx = expression()
                        skipNewlines()
                        val close = expect(RBRACKET, "`]`")
                        Index(e, idx, Span(e.span.start, close.span.end))
                    }
                }
                DOT -> {
                    advance()
                    val f = expect(IDENT, "a field or function name after `.`")
                    if (at(LPAREN)) {
                        e = bracketed {
                            advance()
                            skipNewlines()
                            val args = ArrayList<Expr>()
                            while (!at(RPAREN)) {
                                args.add(expression())
                                skipNewlines()
                                if (at(COMMA)) { advance(); skipNewlines() } else break
                            }
                            val close = expect(RPAREN, "`)`")
                            MethodCall(e, f.text, args, f.span, Span(e.span.start, close.span.end))
                        }
                    } else {
                        e = FieldAccess(e, f.text, f.span, Span(e.span.start, f.span.end))
                    }
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
            RETURN -> {
                advance()
                val v = if (at(NEWLINE) || at(RBRACE) || at(RPAREN) || at(COMMA) || at(EOF)) null
                        else expression()
                Return(v, Span(t.span.start, v?.span?.end ?: t.span.end))
            }
            LBRACE -> block()
            LPAREN -> parenExpr()
            LBRACKET -> listLit()
            FN -> lambda()
            COMPTIME -> {
                val kw = advance()
                val body = block()
                ComptimeExpr(body, Span(kw.span.start, body.span.end))
            }
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

    /** fn(x, y: Int) => expr */
    private fun lambda(): Expr {
        val kw = advance() // fn
        expect(LPAREN, "`(`")
        val params = ArrayList<LambdaParam>()
        bracketed {
            skipNewlines()
            while (!at(RPAREN)) {
                val name = expect(IDENT, "a parameter name")
                val ann = if (at(COLON)) { advance(); typeRef() } else null
                params.add(LambdaParam(name.text, ann, name.span))
                skipNewlines()
                if (at(COMMA)) { advance(); skipNewlines() } else break
            }
        }
        expect(RPAREN, "`)`")
        expect(FATARROW, "`=>` (lambda body)")
        skipNewlines()
        val body = expression()
        return Lambda(params, body, Span(kw.span.start, body.span.end))
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
            val first = expression()
            skipNewlines()
            if (!at(COMMA)) {
                expect(RPAREN, "`)`")
                return@bracketed first
            }
            val elems = arrayListOf(first)
            while (at(COMMA)) {
                advance()
                skipNewlines()
                if (at(RPAREN)) break // allow a trailing comma
                elems.add(expression())
                skipNewlines()
            }
            val close = expect(RPAREN, "`)`")
            val span = Span(open.span.start, close.span.end)
            if (elems.size < 2)
                throw DawnError("a tuple needs at least 2 elements", span, "(x,) is not a tuple; write x")
            if (elems.size > 8) throw DawnError("tuples have at most 8 elements", span)
            TupleLit(elems, span)
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
            LPAREN -> tuplePat()
            LBRACKET -> listPat()
            else -> throw err("expected a pattern")
        }
    }

    /** [], [x, ..rest], [..init, last] — at most one `..`/`..name` rest */
    private fun listPat(): Pattern {
        val open = advance() // [
        skipNewlines()
        val pre = ArrayList<Pattern>()
        val post = ArrayList<Pattern>()
        var hasRest = false
        var restName: String? = null
        var restSpan: Span? = null
        while (!at(RBRACKET)) {
            if (at(DOTDOT)) {
                val d = advance()
                if (hasRest)
                    throw DawnError("a list pattern can have at most one `..` rest", d.span)
                hasRest = true
                if (at(IDENT)) {
                    val n = advance()
                    restName = n.text
                    restSpan = Span(d.span.start, n.span.end)
                } else {
                    restSpan = d.span
                }
            } else {
                (if (hasRest) post else pre).add(pattern())
            }
            skipNewlines()
            if (at(COMMA)) { advance(); skipNewlines() } else break
        }
        val close = expect(RBRACKET, "`]`")
        return ListPat(pre, hasRest, restName, restSpan, post, Span(open.span.start, close.span.end))
    }

    /** (a, b) — tuple pattern, 2 to 8 elements */
    private fun tuplePat(): Pattern {
        val open = advance() // (
        skipNewlines()
        val elems = ArrayList<Pattern>()
        while (!at(RPAREN)) {
            elems.add(pattern())
            skipNewlines()
            if (at(COMMA)) { advance(); skipNewlines() } else break
        }
        val close = expect(RPAREN, "`)`")
        val span = Span(open.span.start, close.span.end)
        if (elems.size < 2)
            throw DawnError("a tuple pattern needs at least 2 elements", span)
        if (elems.size > 8) throw DawnError("tuples have at most 8 elements", span)
        return TuplePat(elems, span)
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
