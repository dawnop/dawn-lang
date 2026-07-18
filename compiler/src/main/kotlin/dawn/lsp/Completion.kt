package dawn.lsp

import dawn.ast.*
import dawn.check.Analyzed
import dawn.check.BUILTINS
import dawn.check.StdLib
import org.eclipse.lsp4j.CompletionItem
import org.eclipse.lsp4j.CompletionItemKind

/**
 * Completion: everything nameable at the cursor — locals of the enclosing
 * function, module + imported functions, types and constructors, builtins,
 * and keywords. Suppressed where a suggestion can only be noise: inside
 * strings and comments, while naming a fresh binding, on `use` lines, and
 * after `.` (Java members are not resolvable without the receiver's type).
 * `!` completes the one builtin effect, like an IDE trigger character.
 */

/** Lexical spot the cursor sits in — mirrors the tokenizer's string/comment rules. */
private enum class Ctx { CODE, COMMENT, STRING, INTERP }

private fun lexContext(text: String, pos: Int): Ctx {
    var kind = 0 // 0 code, 1 comment, 2 double-quote, 3 triple, 4 raw backtick
    var i = 0
    while (i < pos) {
        val ch = text[i]
        when (kind) {
            0 -> when {
                text.startsWith("\"\"\"", i) -> { kind = 3; i += 3 }
                ch == '#' -> { kind = 1; i++ }
                ch == '"' -> { kind = 2; i++ }
                ch == '`' -> { kind = 4; i++ }
                ch == '\'' -> { // a char literal: 'a' or '\n'
                    i++
                    if (i < text.length && text[i] == '\\') i++
                    i++
                    if (i < text.length && text[i] == '\'') i++
                }
                else -> i++
            }
            1 -> { if (ch == '\n') kind = 0; i++ }
            2 -> when {
                ch == '\\' -> i += 2
                ch == '"' || ch == '\n' -> { kind = 0; i++ }
                else -> i++
            }
            3 -> when {
                ch == '\\' -> i += 2
                text.startsWith("\"\"\"", i) -> { kind = 0; i += 3 }
                else -> i++
            }
            else -> { if (ch == '`') kind = 0; i++ }
        }
    }
    return when (kind) {
        1 -> Ctx.COMMENT
        2, 3 -> {
            // a `$name` or `${expr}` being typed completes like code
            val tail = text.substring(maxOf(0, pos - 200), pos)
            if (Regex("\\$[A-Za-z_]\\w*$|\\$\\{[^}\"]*$").containsMatchIn(tail)) Ctx.INTERP else Ctx.STRING
        }
        4 -> Ctx.STRING
        else -> Ctx.CODE
    }
}

private val FRESH_NAME = Regex("(?:^|[^\\w])(?:fn|let|var|const|type|for|derive|trait)\\s+$")
private val USE_LINE = Regex("^\\s*(?:pub\\s+)?use\\b")

internal fun completionsAt(analysis: Analyzed, text: String, offset: Int): List<CompletionItem> {
    val pos = offset.coerceIn(0, text.length)
    when (lexContext(text, pos)) {
        Ctx.COMMENT, Ctx.STRING -> return emptyList()
        else -> {}
    }
    var wordStart = pos
    while (wordStart > 0 && (text[wordStart - 1].isLetterOrDigit() || text[wordStart - 1] == '_')) wordStart--
    val lineStart = text.lastIndexOf('\n', maxOf(0, wordStart - 1)).let { if (it < 0) 0 else it + 1 }
    val before = if (wordStart > lineStart) text.substring(lineStart, wordStart) else ""
    // the effect row: `!` admits exactly one builtin effect
    if (before.endsWith("!")) {
        val io = CompletionItem("io")
        io.kind = CompletionItemKind.Keyword
        io.detail = "the IO effect — this function may perform input/output"
        return listOf(io)
    }
    if (FRESH_NAME.containsMatchIn(before)) return emptyList()
    if (USE_LINE.containsMatchIn(before)) return emptyList()
    if (before.endsWith(".")) return emptyList()

    val items = LinkedHashMap<String, CompletionItem>()
    fun add(name: String, kind: CompletionItemKind, detail: String?, rank: String) {
        if (name == "_" || items.containsKey(name)) return
        val item = CompletionItem(name)
        item.kind = kind
        item.detail = detail
        item.sortText = rank + name
        items[name] = item
    }

    // locals of the enclosing function (top-level, impl method, or trait default):
    // parameters + binders before the cursor
    val enclosingFns = analysis.module.fns + analysis.module.impls.flatMap { it.methods }
    enclosingFns.firstOrNull { pos >= it.span.start && pos <= it.span.end }?.let { fn ->
        for (p in fn.params) add(p.name, CompletionItemKind.Variable, p.symbol?.type?.toString(), "0")
        collectBinders(fn.body, pos) { name, detail ->
            add(name, CompletionItemKind.Variable, detail, "0")
        }
    }
    for (t in analysis.module.traits) {
        for (m in t.methods) {
            if (m.body == null || pos < m.span.start || pos > m.span.end) continue
            for (p in m.params) add(p.name, CompletionItemKind.Variable, p.symbol?.type?.toString(), "0")
            collectBinders(m.body!!, pos) { name, detail ->
                add(name, CompletionItemKind.Variable, detail, "0")
            }
        }
    }
    for (sig in analysis.functions.values)
        add(sig.name, CompletionItemKind.Function, sig.render(), "1")
    for (info in analysis.types.values) {
        add(info.name, CompletionItemKind.Class, "type ${info.name}", "1")
        for (c in info.ctors) {
            val detail =
                if (c.fields.isEmpty()) c.name
                else "${c.name}(${c.fields.joinToString(", ") { "${it.name}: ${it.type}" }})"
            add(c.name, CompletionItemKind.EnumMember, detail, "1")
        }
    }
    for (d in analysis.module.traits)
        add(d.name, CompletionItemKind.Interface, "trait ${d.name}[${d.typeParam}]", "1")
    for (t in dawn.check.PRELUDE_TRAITS)
        add(t.name, CompletionItemKind.Interface, "trait ${t.name}[${t.tvar.name}]", "2")
    // Both tables: a migrated function (`println`, `split`, ...) is still part of
    // the implicitly-visible surface, and users cannot tell which side it lives
    // on. Reading only BUILTINS would make every migration silently delete
    // completions -- the same trap `dawn doc --builtins` fell into.
    for (sig in BUILTINS.values) add(sig.name, CompletionItemKind.Function, sig.render(), "2")
    for (sig in StdLib.fns.values) add(sig.name, CompletionItemKind.Function, sig.render(), "2")
    for (t in listOf("Int", "Float", "Bool", "String", "Unit", "List", "Map", "Set"))
        add(t, CompletionItemKind.Class, "builtin type", "2")
    for (kw in dawn.lex.KEYWORDS.keys) add(kw, CompletionItemKind.Keyword, null, "3")
    add("derive", CompletionItemKind.Keyword, null, "3")
    return items.values.toList()
}

/** Every binder introduced textually before [before] anywhere in the function body. */
private fun collectBinders(e: Expr, before: Int, add: (String, String?) -> Unit) {
    when (e) {
        is Block -> {
            for (s in e.stmts) collectBinders(s, before, add)
            e.tail?.let { collectBinders(it, before, add) }
        }
        is If -> {
            collectBinders(e.cond, before, add)
            collectBinders(e.thenBranch, before, add)
            e.elseBranch?.let { collectBinders(it, before, add) }
        }
        is Match -> {
            collectBinders(e.scrutinee, before, add)
            for (arm in e.arms) collectBinders(arm.body, before, add)
        }
        is Lambda -> {
            if (e.span.start < before) for (p in e.params) add(p.name, null)
            collectBinders(e.body, before, add)
        }
        // lambdas mostly live inside call arguments — walk through them
        is Call -> for (a in e.args) collectBinders(a, before, add)
        is MethodCall -> {
            collectBinders(e.target, before, add)
            for (a in e.args) collectBinders(a, before, add)
        }
        is Apply -> {
            collectBinders(e.target, before, add)
            for (a in e.args) collectBinders(a, before, add)
        }
        is CtorCall -> {
            e.spread?.let { collectBinders(it, before, add) }
            for (a in e.args) collectBinders(a.expr, before, add)
        }
        is ListLit -> for (el in e.elems) collectBinders(el, before, add)
        is TupleLit -> for (el in e.elems) collectBinders(el, before, add)
        is Binary -> {
            collectBinders(e.left, before, add)
            collectBinders(e.right, before, add)
        }
        is Unary -> collectBinders(e.operand, before, add)
        is Propagate -> collectBinders(e.operand, before, add)
        is Unwrap -> collectBinders(e.operand, before, add)
        is Index -> {
            collectBinders(e.target, before, add)
            collectBinders(e.index, before, add)
        }
        is Return -> e.value?.let { collectBinders(it, before, add) }
        else -> {}
    }
}

private fun collectBinders(s: Stmt, before: Int, add: (String, String?) -> Unit) {
    when (s) {
        is LetStmt -> {
            if (s.span.start < before) add(s.name, s.symbol?.type?.toString())
            collectBinders(s.init, before, add)
        }
        is LocalFnStmt -> {
            if (s.span.start < before) add(s.name, s.symbol?.type?.toString())
            collectBinders(s.lambda, before, add)
        }
        is LetPatStmt -> collectBinders(s.init, before, add)
        is ForStmt -> {
            if (s.span.start < before) add(s.name, s.symbol?.type?.toString())
            collectBinders(s.from, before, add)
            s.to?.let { collectBinders(it, before, add) }
            collectBinders(s.body, before, add)
        }
        is WhileStmt -> {
            collectBinders(s.cond, before, add)
            collectBinders(s.body, before, add)
        }
        is AssignStmt -> collectBinders(s.value, before, add)
        is ExprStmt -> collectBinders(s.expr, before, add)
        else -> {}
    }
}
