package dawn.cli

import dawn.diag.DiagnosticSink
import dawn.lex.Lexer
import dawn.lex.StrSegment
import dawn.lex.TokenType
import java.io.File

/**
 * Hidden command for the self-hosting effort: `dawn __lex <file>...` prints each
 * file's token stream (and lex diagnostics) in a canonical line format. The
 * Dawn-written lexer in selfhost/ must reproduce this output byte for byte —
 * scripts/selfhost-lex-diff.sh runs both over the repo's .dawn corpus and diffs.
 * Changing this format or the lexer's observable behavior means changing both
 * sides in the same commit.
 *
 * Format, one line per token:
 *   TYPE<TAB>start<TAB>end<TAB>escaped-text[<TAB>extra...]
 * where extra is the value for INT, the Double.toString value for FLOAT, and
 * one field per segment for STRING (T:text or C:offset:code). Diagnostics
 * follow the tokens, one line each: !<TAB>start<TAB>end<TAB>message<TAB>hint.
 */
fun cmdLexDump(paths: List<String>) {
    if (paths.isEmpty()) throw CliError("usage: dawn __lex <file.dawn>...")
    val sb = StringBuilder()
    for (p in paths) {
        val f = File(p)
        if (!f.isFile) throw CliError("no such file: $p")
        sb.append("== ").append(p).append(" ==\n")
        val sink = DiagnosticSink()
        for (t in Lexer(f.readText(), sink = sink).lex()) {
            sb.append(t.type.name).append('\t').append(t.span.start).append('\t')
                .append(t.span.end).append('\t').append(esc(t.text))
            when (t.type) {
                TokenType.INT -> sb.append('\t').append(t.intValue)
                TokenType.FLOAT -> sb.append('\t').append(t.floatValue)
                TokenType.STRING -> for (s in t.segments) {
                    when (s) {
                        is StrSegment.Text -> sb.append("\tT:").append(esc(s.value))
                        is StrSegment.Code -> sb.append("\tC:").append(s.offset).append(':').append(esc(s.source))
                    }
                }
                else -> {}
            }
            sb.append('\n')
        }
        for (d in sink.all) {
            sb.append("!\t").append(d.span.start).append('\t').append(d.span.end)
                .append('\t').append(esc(d.message)).append('\t').append(esc(d.hint ?: "")).append('\n')
        }
    }
    print(sb)
}

private fun esc(s: String): String {
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
