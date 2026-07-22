package dawn.cli

import dawn.check.CValue
import dawn.check.ModuleLoader
import dawn.check.analyzeProgram
import java.io.File

/**
 * `dawn __check <file|dir>...` — the checker golden dump for the self-hosting
 * effort (P3b, docs/selfhost-checker.md). One dump per target, TSV lines the
 * Dawn port reproduces byte for byte:
 *
 *     D  path  lo  hi  msg  hint     every diagnostic, program order
 *     M  modPath                     then per module, dependency order
 *     F  sig-render                  each pub fn's checked signature
 *     C  name  value|!failed         each const's comptime value
 *
 * A file target loads its use-closure; a directory target loads the project.
 */
fun cmdCheckDump(paths: List<String>) {
    if (paths.isEmpty()) throw CliError("usage: dawn __check <file.dawn | project-dir>...")
    val sb = StringBuilder()
    for (p in paths) {
        sb.append("== ").append(p).append(" ==\n")
        val f = File(p)
        val loaded = if (f.isDirectory) ModuleLoader.loadDirectory(f) else ModuleLoader.loadFile(f)
        val program = analyzeProgram(loaded)
        for (d in program.diagnostics) {
            sb.append("D\t").append(d.source.path)
                .append('\t').append(d.diag.span.start)
                .append('\t').append(d.diag.span.end)
                .append('\t').append(escCheck(d.diag.message))
                .append('\t').append(escCheck(d.diag.hint ?: "")).append('\n')
        }
        for (cm in program.modules) {
            sb.append("M\t").append(cm.modPath).append('\n')
            for (fd in cm.module.fns) {
                if (!fd.pub) continue
                val sig = cm.functions[fd.name] ?: continue
                sb.append("F\t").append(escCheck(sig.render())).append('\n')
            }
            for (cd in cm.module.consts) {
                val v = cd.value
                sb.append("C\t").append(cd.name).append('\t')
                    .append(if (v != null) escCheck(cvShow(v)) else "!failed").append('\n')
            }
        }
    }
    print(sb)
}

private fun cvShow(v: CValue): String = when (v) {
    is CValue.VInt -> v.v.toString()
    is CValue.VFloat -> v.v.toString()
    is CValue.VBool -> v.v.toString()
    is CValue.VString -> "\"${escCheck(v.v)}\""
    CValue.VUnit -> "()"
    is CValue.VList -> "[${v.elems.joinToString(", ") { cvShow(it) }}]"
    is CValue.VTuple -> "(${v.elems.joinToString(", ") { cvShow(it) }})"
    is CValue.VAdt ->
        if (v.fields.isEmpty()) v.ctor.name
        else "${v.ctor.name}(${v.fields.joinToString(", ") { cvShow(it) }})"
    else -> "<fn>"
}

private fun escCheck(s: String): String {
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
