package dawn.cli

import dawn.ast.*
import dawn.diag.DiagnosticSink
import dawn.diag.Span
import dawn.lex.Lexer
import dawn.parse.Parser
import java.io.File

/**
 * Hidden command for the self-hosting effort: `dawn __parse <file>...` prints
 * each file's parsed AST (and lex+parse diagnostics) in a canonical line
 * format. The Dawn-written parser in selfhost/ must reproduce this byte for
 * byte — scripts/selfhost-parse-diff.sh runs both over the repo corpus.
 *
 * Format: one node per line, two-space indentation for children,
 *   Kind field=value ... @lo..hi
 * then diagnostics as in the lex dump: !<TAB>start<TAB>end<TAB>message<TAB>hint.
 * The dump covers exactly what the parser produced — no checker-filled slots.
 */
fun cmdParseDump(paths: List<String>) {
    if (paths.isEmpty()) throw CliError("usage: dawn __parse <file.dawn>...")
    val sb = StringBuilder()
    for (p in paths) {
        val f = File(p)
        if (!f.isFile) throw CliError("no such file: $p")
        sb.append("== ").append(p).append(" ==\n")
        val text = f.readText()
        val sink = DiagnosticSink()
        val module = Parser(Lexer(text, sink = sink).lex(), sink, source = text).module()
        AstDumper(sb).module(module)
        for (d in sink.all) {
            sb.append("!\t").append(d.span.start).append('\t').append(d.span.end)
                .append('\t').append(escA(d.message)).append('\t').append(escA(d.hint ?: "")).append('\n')
        }
    }
    print(sb)
}

private fun escA(s: String): String {
    val sb = StringBuilder(s.length)
    for (c in s) {
        when (c) {
            '\\' -> sb.append("\\\\")
            '\n' -> sb.append("\\n")
            '\t' -> sb.append("\\t")
            '\r' -> sb.append("\\r")
            else -> sb.append(c)
        }
    }
    return sb.toString()
}

private class AstDumper(val sb: StringBuilder) {
    var depth = 0

    fun line(s: String) {
        repeat(depth) { sb.append("  ") }
        sb.append(s).append('\n')
    }

    inline fun nest(body: () -> Unit) {
        depth++
        body()
        depth--
    }

    fun sp(s: Span) = "@${s.start}..${s.end}"

    fun module(m: Module) {
        line("Module")
        nest { for (d in m.decls) decl(d) }
    }

    fun decl(d: Decl) {
        when (d) {
            is FnDecl -> fnDecl(d)
            is TypeDecl -> typeDecl(d)
            is ConstDecl -> {
                line("Const ${d.name} pub=${d.pub} name${sp(d.nameSpan)} ${sp(d.span)}")
                nest {
                    typeRef(d.typeAnn)
                    expr(d.init)
                }
            }
            is TraitDecl -> {
                line("Trait ${d.name} tp=${d.typeParam} tp${sp(d.typeParamSpan)} pub=${d.pub} name${sp(d.nameSpan)} ${sp(d.span)}")
                nest { for (m in d.methods) traitMethod(m) }
            }
            is ImplDecl -> {
                line("Impl ${d.traitName} trait${sp(d.traitSpan)} ${sp(d.span)}")
                nest {
                    typeRef(d.subject)
                    for (m in d.methods) fnDecl(m)
                }
            }
            is UseJavaDecl -> line("UseJava ${escA(d.fqcn)} name${sp(d.nameSpan)} ${sp(d.span)}")
            is UseModuleDecl -> {
                line("UseModule ${d.path} name${sp(d.nameSpan)} ${sp(d.span)}")
                nest { d.selective?.forEach { line("ImportName ${it.name} ${sp(it.span)}") } }
            }
            is TestDecl -> {
                line("Test ${escA(d.testName)} name${sp(d.nameSpan)} ${sp(d.span)}")
                nest { expr(d.body) }
            }
        }
    }

    fun fnDecl(d: FnDecl) {
        line("Fn ${d.name} pub=${d.pub} eff=${atoms(d.declaredEff)} name${sp(d.nameSpan)} ${sp(d.span)}")
        nest {
            for (tp in d.typeParams) typeParam(tp)
            for (p in d.params) {
                line("Param ${p.name} ${sp(p.span)}")
                nest { typeRef(p.typeName) }
            }
            d.retType?.let {
                line("Ret")
                nest { typeRef(it) }
            }
            expr(d.body)
        }
    }

    fun typeParam(tp: TypeParamDecl) {
        val bounds = if (tp.bounds.isEmpty()) "_"
        else tp.bounds.joinToString("+") { (n, s) -> "$n${sp(s)}" }
        line("TypeParam ${tp.name} bounds=$bounds ${sp(tp.span)}")
    }

    fun typeDecl(d: TypeDecl) {
        val tparams = if (d.typeParams.isEmpty()) "_" else d.typeParams.joinToString(",")
        val derives = if (d.derives.isEmpty()) "_"
        else d.derives.joinToString("+") { (n, s) -> "$n${sp(s)}" }
        val alias = d.aliasTarget != null
        line(
            "Type ${d.name} tparams=$tparams record=${d.isRecord} alias=$alias derives=$derives " +
                "pub=${d.pub} name${sp(d.nameSpan)} ${sp(d.span)}",
        )
        nest {
            d.aliasTarget?.let { typeRef(it) }
            for (c in d.ctors) {
                line("Ctor ${c.name} name${sp(c.nameSpan)} ${sp(c.span)}")
                nest {
                    for (f in c.fields) {
                        line("Field ${f.name} ${sp(f.span)}")
                        nest { typeRef(f.typeRef) }
                    }
                }
            }
        }
    }

    fun traitMethod(m: TraitMethod) {
        line("TraitMethod ${m.name} eff=${atoms(m.declaredEff)} default=${m.body != null} name${sp(m.nameSpan)} ${sp(m.span)}")
        nest {
            for (p in m.params) {
                line("Param ${p.name} ${sp(p.span)}")
                nest { typeRef(p.typeName) }
            }
            line("Ret")
            nest { typeRef(m.retType) }
            m.body?.let { expr(it) }
        }
    }

    fun atoms(a: List<String>) = if (a.isEmpty()) "_" else a.joinToString(",")

    fun typeRef(t: TypeRef) {
        when (t) {
            is NamedTypeRef -> {
                line("TNamed ${t.name} ${sp(t.span)}")
                nest { for (a in t.args) typeRef(a) }
            }
            is TupleTypeRef -> {
                line("TTuple ${sp(t.span)}")
                nest { for (e in t.elems) typeRef(e) }
            }
            is FnTypeRef -> {
                line("TFn nparams=${t.params.size} eff=${atoms(t.effAtoms)} ${sp(t.span)}")
                nest {
                    for (p in t.params) typeRef(p)
                    typeRef(t.ret)
                }
            }
        }
    }

    fun stmt(s: Stmt) {
        when (s) {
            is LetStmt -> {
                line("Let ${s.name} mut=${s.mutable} ann=${s.typeAnn != null} ${sp(s.span)}")
                nest {
                    s.typeAnn?.let { typeRef(it) }
                    expr(s.init)
                }
            }
            is LetPatStmt -> {
                line("LetPat mut=${s.mutable} ${sp(s.span)}")
                nest {
                    pattern(s.pattern)
                    expr(s.init)
                }
            }
            is LocalFnStmt -> {
                line("LocalFn ${s.name} eff=${atoms(s.effNames)} name${sp(s.nameSpan)} ${sp(s.span)}")
                nest {
                    for (p in s.lambda.params) lambdaParam(p)
                    line("Ret")
                    nest { typeRef(s.retRef) }
                    expr(s.lambda.body)
                }
            }
            is AssignStmt -> {
                line("Assign ${s.name} name${sp(s.nameSpan)} ${sp(s.span)}")
                nest { expr(s.value) }
            }
            is ExprStmt -> {
                line("ExprStmt ${sp(s.span)}")
                nest { expr(s.expr) }
            }
            is AssertStmt -> {
                line("Assert src=${s.sourceText?.let { escA(it) } ?: "_"} ${sp(s.span)}")
                nest { expr(s.cond) }
            }
            is WhileStmt -> {
                line("While ${sp(s.span)}")
                nest {
                    expr(s.cond)
                    expr(s.body)
                }
            }
            is ForStmt -> {
                line("For ${s.name} ranged=${s.to != null} ${sp(s.span)}")
                nest {
                    expr(s.from)
                    s.to?.let { expr(it) }
                    expr(s.body)
                }
            }
        }
    }

    fun lambdaParam(p: LambdaParam) {
        line("LParam ${p.name} ann=${p.typeAnn != null} ${sp(p.span)}")
        nest { p.typeAnn?.let { typeRef(it) } }
    }

    fun expr(e: Expr) {
        when (e) {
            is IntLit -> line("Int ${e.value} ${sp(e.span)}")
            is FloatLit -> line("Float ${e.value} ${sp(e.span)}")
            is BoolLit -> line("Bool ${e.value} ${sp(e.span)}")
            is UnitLit -> line("Unit ${sp(e.span)}")
            is StrLit -> {
                line("Str ${sp(e.span)}")
                nest {
                    for (p in e.parts) {
                        when (p) {
                            is StrPart.Text -> line("SText ${escA(p.value)}")
                            is StrPart.Interp -> {
                                line("SInterp")
                                nest { expr(p.expr) }
                            }
                        }
                    }
                }
            }
            is VarRef -> line("Var ${e.name} ${sp(e.span)}")
            is Call -> {
                line("Call ${e.callee} callee${sp(e.calleeSpan)} ${sp(e.span)}")
                nest { for (a in e.args) expr(a) }
            }
            is Apply -> {
                line("Apply nargs=${e.args.size} ${sp(e.span)}")
                nest {
                    expr(e.target)
                    for (a in e.args) expr(a)
                }
            }
            is MethodCall -> {
                line("MethodCall ${e.name} nargs=${e.args.size} name${sp(e.nameSpan)} ${sp(e.span)}")
                nest {
                    expr(e.target)
                    for (a in e.args) expr(a)
                }
            }
            is Lambda -> {
                line("Lambda ${sp(e.span)}")
                nest {
                    for (p in e.params) lambdaParam(p)
                    expr(e.body)
                }
            }
            is CtorCall -> {
                line("CtorCall ${e.ctorName} parens=${e.hasParens} spread=${e.spread != null} callee${sp(e.calleeSpan)} ${sp(e.span)}")
                nest {
                    e.spread?.let { expr(it) }
                    for (a in e.args) {
                        line("CtorArg name=${a.name ?: "_"} ${sp(a.span)}")
                        nest { expr(a.expr) }
                    }
                }
            }
            is FieldAccess -> {
                line("FieldAccess ${e.fieldName} field${sp(e.fieldSpan)} ${sp(e.span)}")
                nest { expr(e.target) }
            }
            is ListLit -> {
                line("ListLit ${sp(e.span)}")
                nest { for (x in e.elems) expr(x) }
            }
            is TupleLit -> {
                line("TupleLit ${sp(e.span)}")
                nest { for (x in e.elems) expr(x) }
            }
            is Propagate -> {
                line("Propagate ${sp(e.span)}")
                nest { expr(e.operand) }
            }
            is Unwrap -> {
                line("Unwrap ${sp(e.span)}")
                nest { expr(e.operand) }
            }
            is Index -> {
                line("Index ${sp(e.span)}")
                nest {
                    expr(e.target)
                    expr(e.index)
                }
            }
            is Return -> {
                line("Return has=${e.value != null} ${sp(e.span)}")
                nest { e.value?.let { expr(it) } }
            }
            is BreakExpr -> line("Break ${sp(e.span)}")
            is ContinueExpr -> line("Continue ${sp(e.span)}")
            is ComptimeExpr -> {
                line("Comptime ${sp(e.span)}")
                nest { expr(e.body) }
            }
            is UnsafePureExpr -> {
                line("UnsafePure ${sp(e.span)}")
                nest { expr(e.body) }
            }
            is Binary -> {
                line("Binary ${e.op.name} op${sp(e.opSpan)} ${sp(e.span)}")
                nest {
                    expr(e.left)
                    expr(e.right)
                }
            }
            is Unary -> {
                line("Unary ${e.op.name} ${sp(e.span)}")
                nest { expr(e.operand) }
            }
            is If -> {
                line("If else=${e.elseBranch != null} ${sp(e.span)}")
                nest {
                    expr(e.cond)
                    expr(e.thenBranch)
                    e.elseBranch?.let { expr(it) }
                }
            }
            is Match -> {
                line("Match narms=${e.arms.size} ${sp(e.span)}")
                nest {
                    expr(e.scrutinee)
                    for (a in e.arms) {
                        line("Arm npats=${a.patterns.size} guard=${a.guard != null} ${sp(a.span)}")
                        nest {
                            for (p in a.patterns) pattern(p)
                            a.guard?.let { expr(it) }
                            expr(a.body)
                        }
                    }
                }
            }
            is Block -> {
                line("Block tail=${e.tail != null} ${sp(e.span)}")
                nest {
                    for (s in e.stmts) stmt(s)
                    e.tail?.let { expr(it) }
                }
            }
        }
    }

    fun pattern(p: Pattern) {
        when (p) {
            is LitPat -> {
                line("PLit ${sp(p.span)}")
                nest { expr(p.lit) }
            }
            is BindPat -> line("PBind ${p.name} ${sp(p.span)}")
            is WildPat -> line("PWild ${sp(p.span)}")
            is CtorPat -> {
                line("PCtor ${p.ctorName} rest=${p.hasRest} parens=${p.hasParens} name${sp(p.nameSpan)} ${sp(p.span)}")
                nest {
                    for (a in p.args) {
                        line("PArg name=${a.name ?: "_"}")
                        nest { pattern(a.pattern) }
                    }
                }
            }
            is TuplePat -> {
                line("PTuple ${sp(p.span)}")
                nest { for (x in p.elems) pattern(x) }
            }
            is ListPat -> {
                val rs = p.restSpan?.let { sp(it) } ?: "@_"
                line("PList npre=${p.pre.size} rest=${p.hasRest} restname=${p.restName ?: "_"} rest$rs ${sp(p.span)}")
                nest {
                    for (x in p.pre) pattern(x)
                    for (x in p.post) pattern(x)
                }
            }
        }
    }
}
