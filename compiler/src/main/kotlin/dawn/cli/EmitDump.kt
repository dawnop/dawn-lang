package dawn.cli

import java.io.File

/**
 * `dawn __emit <target> -o <dir>` — the codegen golden dump for the
 * self-hosting effort (P4, docs/selfhost-codegen.md): compile the target and
 * write every generated class to <dir>/<internal-name>.class. Plain files,
 * not a jar, so the comparison is byte-exact and timestamp-free.
 */
fun cmdEmitDump(rest: List<String>) {
    var out: String? = null
    val targets = ArrayList<String>()
    var i = 0
    while (i < rest.size) {
        if (rest[i] == "-o" && i + 1 < rest.size) {
            out = rest[i + 1]
            i += 2
        } else {
            targets.add(rest[i])
            i += 1
        }
    }
    val dir = out ?: throw CliError("usage: dawn __emit <file.dawn | project-dir> -o <dir>")
    val target = targets.firstOrNull() ?: throw CliError("usage: dawn __emit <target> -o <dir>")
    val program = compileProject(target, 100_000_000L, includeTests = true)
    val root = File(dir)
    root.mkdirs()
    for ((name, bytes) in program.classes.toSortedMap()) {
        val f = File(root, "$name.class")
        f.parentFile.mkdirs()
        f.writeBytes(bytes)
    }
    println("${program.classes.size} classes -> $dir")
}
