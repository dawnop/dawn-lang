package dawn.cli

import dawn.check.CheckedModule
import dawn.check.analyze
import dawn.check.analyzeProject
import dawn.codegen.CodeGen
import dawn.diag.Severity
import dawn.diag.SourceFile
import java.io.File
import java.util.jar.Attributes
import java.util.jar.JarEntry
import java.util.jar.JarOutputStream
import java.util.jar.Manifest
import kotlin.system.exitProcess

const val USAGE = """dawn — the Dawn language toolchain

A <target> is a single .dawn file or a project directory (src/main.dawn entry).

usage:
  dawn run <target>                    compile and run (in-process JVM)
  dawn test <target>                   compile with test blocks and run them
  dawn build <target> [-o out.jar]     produce an executable jar (tests stripped)
  dawn build <target> --native [-o out]
                                       produce a standalone native binary (needs native-image)
  dawn fmt <file.dawn | dir>...        format files in place (a dir formats all .dawn under it)
  dawn fmt --check <target>...         report files that are not formatted (exit 1 if any)
  dawn doc <target>                    emit the pub API (## doc comments) as JSON on stdout
  dawn doc --builtins                  emit the builtin function reference as JSON
"""

fun main(args: Array<String>) {
    if (args.isEmpty()) {
        print(USAGE)
        exitProcess(2)
    }
    try {
        when (args[0]) {
            "run" -> cmdRun(args.drop(1))
            "test" -> cmdTest(args.drop(1))
            "build" -> cmdBuild(args.drop(1))
            "fmt" -> cmdFmt(args.drop(1))
            "doc" -> cmdDoc(args.drop(1))
            "lsp" -> dawn.lsp.runLspServer()
            "--help", "-h", "help" -> print(USAGE)
            else -> {
                System.err.println("unknown command: ${args[0]}\n")
                print(USAGE)
                exitProcess(2)
            }
        }
    } catch (e: CliError) {
        System.err.println("error: ${e.message}")
        exitProcess(2)
    }
}

class CliError(message: String) : Exception(message)

/** --comptime-fuel N / --comptime-fuel=N; returns (fuel, args without the flag) */
fun extractFuel(rest: List<String>): Pair<Long, List<String>> {
    var fuel = 100_000_000L
    val out = ArrayList<String>()
    var i = 0
    while (i < rest.size) {
        val a = rest[i]
        when {
            a == "--comptime-fuel" && i + 1 < rest.size -> {
                fuel = rest[i + 1].toLongOrNull() ?: throw CliError("--comptime-fuel needs a number")
                i += 2
            }
            a.startsWith("--comptime-fuel=") -> {
                fuel = a.removePrefix("--comptime-fuel=").toLongOrNull()
                    ?: throw CliError("--comptime-fuel needs a number")
                i++
            }
            else -> { out.add(a); i++ }
        }
    }
    return fuel to out
}

fun sanitizeClassName(stem: String): String {
    val cleaned = stem.map { if (it.isLetterOrDigit() || it == '_') it else '_' }.joinToString("")
    return if (cleaned.isEmpty() || cleaned[0].isDigit()) "dawn_$cleaned" else cleaned
}

/** A compiled program: its entry module (the one with `main`) and every class file. */
class CompiledProgram(val entry: CheckedModule?, val classes: Map<String, ByteArray>)

/**
 * Compile a project directory or a single .dawn file (spec §10.1) → all classes.
 * Compile errors are rendered here and exit. `includeTests` keeps test blocks.
 */
fun compileProject(path: String, comptimeFuel: Long, includeTests: Boolean = false): CompiledProgram {
    val file = File(path)
    if (!file.exists()) throw CliError("no such file or directory: $path")
    if (file.isFile && !path.endsWith(".dawn")) throw CliError("source files must end in .dawn: $path")
    val program = analyzeProject(file, comptimeFuel)
    if (program.hasErrors) {
        System.err.print(program.render())
        val n = program.diagnostics.count { it.diag.severity == Severity.ERROR }
        System.err.println(if (n == 1) "1 error" else "$n errors")
        exitProcess(1)
    }
    val units = program.modules.map { CodeGen.Companion.ModuleUnit(it.module, it.className) }
    val classes = CodeGen.generateProgram(units, includeTests)
    val entry = program.modules.firstOrNull { m -> m.module.fns.any { it.name == "main" } }
    return CompiledProgram(entry, classes)
}

/** A class loader backed by an in-memory class table. */
private fun loaderFor(classes: Map<String, ByteArray>): ClassLoader =
    object : ClassLoader(ClassLoader.getSystemClassLoader()) {
        override fun findClass(name: String): Class<*> {
            val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
            return defineClass(name, bytes, 0, bytes.size)
        }
    }

// ---- run: execute in-process via a class loader ----

fun cmdRun(restIn: List<String>) {
    val (fuel, rest) = extractFuel(restIn)
    val path = rest.firstOrNull() ?: throw CliError("usage: dawn run <file.dawn | project-dir>")
    val program = compileProject(path, fuel)
    val entry = program.entry ?: throw CliError("$path has no pub fn main() -> Unit !io, nothing to run")
    val cls = Class.forName(entry.className.replace('/', '.'), false, loaderFor(program.classes))
    val main = cls.getDeclaredMethod("main", Array<String>::class.java)
    main.invoke(null, rest.drop(1).toTypedArray())
}

// ---- test: compile with test blocks, run each across all modules, report ----

fun cmdTest(restIn: List<String>) {
    val (fuel, rest) = extractFuel(restIn)
    val path = rest.firstOrNull() ?: throw CliError("usage: dawn test <file.dawn | project-dir>")
    val program = compileProject(path, fuel, includeTests = true)
    // recover per-module test blocks (a module class holds dawn$test$i methods)
    val analyzed = analyzeProject(File(path), fuel)
    val loader = loaderFor(program.classes)
    var total = 0
    var failed = 0
    for (m in analyzed.modules) {
        val tests = m.module.tests
        if (tests.isEmpty()) continue
        val cls = Class.forName(m.className.replace('/', '.'), false, loader)
        for ((i, t) in tests.withIndex()) {
            total++
            val label = if (analyzed.modules.count { it.module.tests.isNotEmpty() } > 1)
                "${m.modPath} :: ${t.testName}" else t.testName
            try {
                cls.getDeclaredMethod("dawn\$test\$$i").invoke(null)
                println("PASS  $label")
            } catch (e: java.lang.reflect.InvocationTargetException) {
                failed++
                println("FAIL  $label")
                e.cause?.message?.lines()?.forEach { println("      $it") }
            }
        }
    }
    if (total == 0) throw CliError("$path has no test blocks")
    println(if (failed == 0) "$total test(s) passed" else "$failed of $total test(s) failed")
    if (failed > 0) exitProcess(1)
}

// ---- fmt: reformat sources in place, or --check for CI ----

fun cmdFmt(rest: List<String>) {
    val check = rest.contains("--check")
    val paths = rest.filter { !it.startsWith("-") }
    if (paths.isEmpty()) throw CliError("usage: dawn fmt [--check] <file.dawn | dir>...")
    // a directory argument formats every .dawn under it (spec §12.1)
    val files = paths.flatMap { p ->
        val f = File(p)
        when {
            !f.exists() -> throw CliError("no such file or directory: $p")
            f.isDirectory -> f.walkTopDown().filter { it.isFile && it.extension == "dawn" }.sortedBy { it.path }.toList()
            else -> listOf(f)
        }
    }
    var unformatted = 0
    for (file in files) {
        val original = file.readText()
        val formatted = dawn.fmt.Formatter.format(original)
        if (formatted == original) continue
        if (check) {
            println(file.path)
            unformatted++
        } else {
            file.writeText(formatted)
            println("formatted ${file.path}")
        }
    }
    if (check && unformatted > 0) exitProcess(1)
}

// ---- build: write a jar, optionally hand it to native-image ----

fun cmdBuild(restIn: List<String>) {
    val (fuel, rest) = extractFuel(restIn)
    val path = rest.firstOrNull { !it.startsWith("-") }
        ?: throw CliError("usage: dawn build <file.dawn | project-dir> [-o out] [--native]")
    val native = rest.contains("--native")
    val oIdx = rest.indexOf("-o")
    val out = if (oIdx >= 0 && oIdx + 1 < rest.size) rest[oIdx + 1] else null

    val program = compileProject(path, fuel)
    val entry = program.entry ?: throw CliError("$path has no pub fn main() -> Unit !io to use as an entry point")
    val stem = File(path).let { if (it.isDirectory) it.name else it.nameWithoutExtension }
    val jarPath = when {
        native -> File.createTempFile("dawn-build-", ".jar").absolutePath
        out != null -> out
        else -> "$stem.jar"
    }
    writeJar(jarPath, entry.className, program.classes)

    if (!native) {
        println("wrote $jarPath (run it with: java -jar $jarPath)")
        return
    }

    val binOut = out ?: stem
    val nativeImage = findNativeImage() ?: throw CliError(
        "native-image not found. Install GraalVM and add it to PATH, or set GRAALVM_HOME",
    )
    println("invoking native-image (takes a minute or two the first time)...")
    val proc = ProcessBuilder(nativeImage, "-jar", jarPath, "-o", binOut, "--no-fallback")
        .redirectErrorStream(true)
        .start()
    proc.inputStream.bufferedReader().forEachLine { println("  $it") }
    val code = proc.waitFor()
    File(jarPath).delete()
    if (code != 0) throw CliError("native-image failed (exit code $code)")
    println("wrote $binOut (standalone binary, run it directly: ./$binOut)")
}

fun writeJar(jarPath: String, mainClass: String, classes: Map<String, ByteArray>) {
    val manifest = Manifest()
    manifest.mainAttributes[Attributes.Name.MANIFEST_VERSION] = "1.0"
    manifest.mainAttributes[Attributes.Name.MAIN_CLASS] = mainClass
    JarOutputStream(File(jarPath).outputStream(), manifest).use { jar ->
        for ((name, bytes) in classes) {
            jar.putNextEntry(JarEntry("$name.class"))
            jar.write(bytes)
            jar.closeEntry()
        }
    }
}

fun findNativeImage(): String? {
    System.getenv("GRAALVM_HOME")?.let {
        val p = File(it, "bin/native-image")
        if (p.canExecute()) return p.absolutePath
    }
    System.getenv("JAVA_HOME")?.let {
        val p = File(it, "bin/native-image")
        if (p.canExecute()) return p.absolutePath
    }
    // PATH
    System.getenv("PATH")?.split(File.pathSeparator)?.forEach {
        val p = File(it, "native-image")
        if (p.canExecute()) return p.absolutePath
    }
    return null
}
