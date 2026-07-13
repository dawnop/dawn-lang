package dawn.cli

import dawn.ast.ConstDecl
import dawn.ast.Decl
import dawn.ast.FnDecl
import dawn.ast.TraitDecl
import dawn.ast.TypeDecl
import dawn.check.AdtInfo
import dawn.check.AnalyzedProgram
import dawn.check.BUILTINS
import dawn.check.analyzeProject
import dawn.diag.DiagnosticSink
import dawn.diag.Severity
import dawn.diag.SourceFile
import dawn.lex.Lexer
import dawn.lex.Token
import java.io.File
import kotlin.system.exitProcess

/**
 * dawn doc: emit a project's pub API (with `##` doc comments, spec §1) or the
 * builtin function reference as JSON on stdout. The M5 site generator — written
 * in Dawn — consumes this with its own JSON library.
 */
fun cmdDoc(rest: List<String>) {
    if (rest.contains("--builtins")) {
        print(builtinsJson())
        return
    }
    val path = rest.firstOrNull { !it.startsWith("-") }
        ?: throw CliError("usage: dawn doc <file.dawn | project-dir> | dawn doc --builtins")
    val file = File(path)
    if (!file.exists()) throw CliError("no such file or directory: $path")
    val program = analyzeProject(file)
    if (program.hasErrors) {
        System.err.print(program.render())
        exitProcess(1)
    }
    print(projectJson(program))
}

// ---- doc comment extraction ----

/**
 * The `##` lines immediately above a declaration, contiguous, joined by \n
 * (leading `## ` stripped). A blank line between the comment block and the
 * declaration detaches it. Plain `#` comments are never docs.
 */
private fun docOf(source: SourceFile, commentEndLine: Map<Int, Token>, decl: Decl): String? {
    var line = source.lspPosition(decl.span.start).first - 1
    val lines = ArrayList<String>()
    while (true) {
        val tok = commentEndLine[line] ?: break
        if (!tok.text.startsWith("##")) break
        lines.add(tok.text.removePrefix("##").removePrefix(" "))
        line--
    }
    if (lines.isEmpty()) return null
    return lines.reversed().joinToString("\n")
}

/** every comment token of [source], indexed by the line it ends on */
private fun commentsByLine(source: SourceFile): Map<Int, Token> {
    val comments = ArrayList<Token>()
    Lexer(source.text, sink = DiagnosticSink(), commentSink = comments).lex()
    return comments.associateBy { source.lspPosition(it.span.end).first }
}

// ---- project JSON ----

private fun projectJson(program: AnalyzedProgram): String {
    val w = JsonWriter()
    w.obj {
        w.key("modules")
        w.arr(program.modules) { m ->
            val byLine = commentsByLine(m.source)
            fun doc(d: Decl) = docOf(m.source, byLine, d)
            w.obj {
                w.field("path", m.modPath)
                w.key("fns")
                w.arr(m.module.decls.filterIsInstance<FnDecl>().filter { it.pub }) { d ->
                    w.obj {
                        w.field("name", d.name)
                        w.field("sig", m.functions[d.name]?.render() ?: d.name)
                        w.fieldOrNull("doc", doc(d))
                    }
                }
                w.key("types")
                w.arr(m.module.decls.filterIsInstance<TypeDecl>().filter { it.pub }) { d ->
                    typeJson(w, m.types[d.name], d, doc(d))
                }
                w.key("consts")
                w.arr(m.module.decls.filterIsInstance<ConstDecl>().filter { it.pub }) { d ->
                    w.obj {
                        w.field("name", d.name)
                        w.field("type", d.constType?.toString() ?: "")
                        w.fieldOrNull("doc", doc(d))
                    }
                }
                w.key("traits")
                w.arr(m.module.decls.filterIsInstance<TraitDecl>().filter { it.pub }) { d ->
                    w.obj {
                        w.field("name", d.name)
                        w.field("typeParam", d.typeParam)
                        w.key("methods")
                        w.arr(d.info?.methods?.values?.toList() ?: emptyList()) { ms ->
                            w.obj {
                                w.field("name", ms.sig.name)
                                w.field("sig", ms.sig.render())
                                w.field("hasDefault", ms.hasDefault)
                            }
                        }
                        w.fieldOrNull("doc", doc(d))
                    }
                }
                w.key("impls")
                w.arr(m.impls) { i -> w.str(i.display) }
            }
        }
    }
    return w.done()
}

private fun typeJson(w: JsonWriter, info: AdtInfo?, d: TypeDecl, doc: String?) {
    w.obj {
        w.field("name", d.name)
        w.field("record", d.isRecord)
        w.key("typeParams")
        w.arr(d.typeParams) { w.str(it) }
        w.key("ctors")
        w.arr(info?.ctors ?: emptyList()) { c ->
            w.obj {
                w.field("name", c.name)
                w.key("fields")
                w.arr(c.fields) { f ->
                    w.obj {
                        w.field("name", f.name)
                        w.field("type", f.type.toString())
                    }
                }
            }
        }
        w.fieldOrNull("doc", doc)
    }
}

// ---- builtin reference ----

/** spec §11 grouping; every BUILTINS entry must appear in exactly one group (see DocCmdTest) */
val BUILTIN_GROUPS: List<Pair<String, List<Pair<String, String>>>> = listOf(
    "io" to listOf(
        "println" to "print a string followed by a newline",
        "print" to "print a string without a newline",
        "read_line" to "read one line from stdin; None at end of input",
        "read_file" to "read a whole file as a UTF-8 string",
        "write_file" to "write a string to a file, creating missing parent directories; Ok carries the character count",
        "list_dir" to "sorted entry names of a directory; Err when the path is not a directory",
        "is_dir" to "whether the path names a directory (false when missing)",
        "args" to "command line arguments",
    ),
    "list" to listOf(
        "len" to "number of elements",
        "get" to "element at an index; None when out of bounds",
        "range" to "the integers from..to (exclusive)",
        "map" to "transform every element",
        "filter" to "keep the elements satisfying a predicate",
        "fold" to "reduce from the left with an accumulator",
        "sort" to "ascending stable sort (elements need Ord)",
        "sort_by" to "stable sort with a two-argument cmp function",
        "max" to "the first greatest element; None when empty (elements need Ord)",
        "min" to "the first least element; None when empty (elements need Ord)",
        "max_by" to "the first element whose key is greatest; None when empty (keys need Ord)",
        "min_by" to "the first element whose key is least; None when empty (keys need Ord)",
    ),
    "string" to listOf(
        "to_string" to "render any printable value (numbers, strings, derive Show data)",
        "chars" to "split into single-character strings (code point aware)",
        "join" to "concatenate with a separator",
        "split" to "split around a literal separator (not a regex)",
        "trim" to "strip leading and trailing whitespace",
        "contains" to "whether a substring occurs",
        "starts_with" to "whether the string starts with a prefix",
        "ends_with" to "whether the string ends with a suffix",
        "parse_int" to "parse a decimal integer; None on malformed input",
        "parse_float" to "parse a floating point number; None on malformed input",
    ),
    "char" to listOf(
        "code_points" to "split into Unicode code points (a character is its code point Int)",
        "from_code_points" to "assemble a string from code points",
        "char_to_string" to "one code point as a string (invalid code points panic)",
        "str_len" to "length in code points",
        "substring" to "slice by code point indices (out of bounds panics)",
    ),
    "map & set" to listOf(
        "map_empty" to "the empty map",
        "map_from" to "a map from a list of key-value pairs (later wins)",
        "map_insert" to "a new map with one entry added or replaced",
        "map_remove" to "a new map without a key",
        "map_get" to "the value for a key; None when absent",
        "map_has" to "whether a key is present",
        "map_size" to "number of entries",
        "map_keys" to "keys in insertion order",
        "map_values" to "values in insertion order",
        "map_entries" to "entries in insertion order",
        "set_empty" to "the empty set",
        "set_from" to "a set from a list (duplicates collapse)",
        "set_insert" to "a new set with one element added",
        "set_remove" to "a new set without an element",
        "set_has" to "whether an element is present",
        "set_size" to "number of elements",
        "set_to_list" to "elements in insertion order",
    ),
    "option" to listOf(
        "expect" to "unwrap a Some or panic with a message",
        "unwrap_or" to "the Some value, or a fallback for None",
    ),
    "conversion" to listOf(
        "to_float" to "Int to Float",
        "to_int" to "Float to Int (truncates)",
    ),
    "control" to listOf(
        "panic" to "abort with a message (diverges, so usable at any type)",
        "todo" to "placeholder that panics when reached",
    ),
)

private fun builtinsJson(): String {
    val w = JsonWriter()
    w.obj {
        w.key("groups")
        w.arr(BUILTIN_GROUPS) { (group, fns) ->
            w.obj {
                w.field("name", group)
                w.key("fns")
                w.arr(fns) { (name, doc) ->
                    val sig = BUILTINS[name] ?: throw CliError("BUILTIN_GROUPS names unknown builtin: $name")
                    w.obj {
                        w.field("name", name)
                        w.field("sig", sig.render())
                        w.field("doc", doc)
                    }
                }
            }
        }
    }
    return w.done()
}

// ---- a tiny JSON writer (pretty, 2-space indent, deterministic) ----

class JsonWriter {
    private val sb = StringBuilder()
    private var indent = 0
    private var needComma = false

    private fun pad() = sb.append("  ".repeat(indent))

    private fun preValue() {
        if (trailingKey) {
            sb.append(" ")
            trailingKey = false
        } else {
            if (needComma) sb.append(",\n") else sb.append("\n")
            pad()
        }
        needComma = false
    }

    fun obj(body: () -> Unit) {
        preValue()
        sb.append("{")
        indent++
        needComma = false
        body()
        indent--
        sb.append("\n")
        pad()
        sb.append("}")
        needComma = true
    }

    fun <T> arr(items: Iterable<T>, each: (T) -> Unit) {
        preValue()
        sb.append("[")
        indent++
        needComma = false
        var any = false
        for (it in items) { any = true; each(it) }
        indent--
        if (any) { sb.append("\n"); pad() }
        sb.append("]")
        needComma = true
    }

    fun key(k: String) {
        if (needComma) sb.append(",\n") else sb.append("\n")
        pad()
        sb.append(quote(k)).append(":")
        needComma = false
        trailingKey = true // the value that follows sits on the same line
    }

    private var trailingKey = false

    fun str(s: String) {
        preValue()
        sb.append(quote(s))
        needComma = true
    }

    fun field(k: String, v: String) { key(k); str(v) }
    fun field(k: String, v: Boolean) { key(k); preValue(); sb.append(v); needComma = true }
    fun fieldOrNull(k: String, v: String?) { key(k); if (v == null) { preValue(); sb.append("null"); needComma = true } else str(v) }

    fun done(): String = sb.toString().trimStart('\n') + "\n"

    private fun quote(s: String): String {
        val out = StringBuilder("\"")
        for (c in s) when {
            c == '"' -> out.append("\\\"")
            c == '\\' -> out.append("\\\\")
            c == '\n' -> out.append("\\n")
            c == '\r' -> out.append("\\r")
            c == '\t' -> out.append("\\t")
            c < ' ' -> out.append("\\u%04x".format(c.code))
            else -> out.append(c)
        }
        return out.append("\"").toString()
    }
}
