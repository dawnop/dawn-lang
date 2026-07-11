package dawn.check

import dawn.ast.Module
import dawn.diag.Diagnostic
import dawn.diag.DiagnosticSink
import dawn.lex.Lexer
import dawn.parse.Parser

/**
 * The result of analyzing one source file. The AST is always present (possibly
 * partial after parse-error recovery) and carries type/symbol annotations, so
 * IDE features keep working even when the file has errors.
 */
class Analyzed(
    val module: Module,
    val diagnostics: List<Diagnostic>,
    /** user-defined functions by name */
    val functions: Map<String, FnSig>,
    /** user-defined types by name */
    val types: Map<String, AdtInfo>,
) {
    val hasErrors: Boolean get() = diagnostics.any { it.severity == dawn.diag.Severity.ERROR }
}

/**
 * Single front-end entry point shared by the CLI and the language server:
 * lex → parse (with recovery) → type/effect check (with recovery).
 * Never throws on bad input; all problems land in [Analyzed.diagnostics].
 */
fun analyze(source: String): Analyzed {
    val sink = DiagnosticSink()
    val tokens = Lexer(source, 0, sink).lex()
    val module = Parser(tokens, sink).module()
    val checker = Checker(module, sink)
    checker.check()
    return Analyzed(module, sink.all, checker.functions, checker.types)
}
