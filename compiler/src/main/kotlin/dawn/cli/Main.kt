package dawn.cli

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.SourceFile
import java.io.File
import java.util.jar.Attributes
import java.util.jar.JarEntry
import java.util.jar.JarOutputStream
import java.util.jar.Manifest
import kotlin.system.exitProcess

const val USAGE = """dawn — the Dawn language toolchain

usage:
  dawn run <file.dawn>                 compile and run (in-process JVM)
  dawn test <file.dawn>                compile with test blocks and run them
  dawn build <file.dawn> [-o out.jar]  produce an executable jar (tests stripped)
  dawn build <file.dawn> --native [-o out]
                                       produce a standalone native binary (needs native-image)
  dawn fmt <file.dawn>...              format files in place
  dawn fmt --check <file.dawn>...      report files that are not formatted (exit 1 if any)
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

/** Compile one .dawn file → (class name, bytecode per class). Compile errors are rendered here and exit. */
fun compile(path: String, comptimeFuel: Long = 100_000_000L): Pair<String, Map<String, ByteArray>> {
    val file = File(path)
    if (!file.exists()) throw CliError("no such file: $path")
    if (!path.endsWith(".dawn")) throw CliError("source files must end in .dawn: $path")
    val source = SourceFile(path, file.readText())
    val className = sanitizeClassName(file.nameWithoutExtension)
    val analysis = analyze(source.text, comptimeFuel)
    if (analysis.hasErrors) {
        for (d in analysis.diagnostics) System.err.print(d.render(source))
        val n = analysis.diagnostics.size
        System.err.println(if (n == 1) "1 error" else "$n errors")
        exitProcess(1)
    }
    return className to CodeGen(analysis.module, className).generate()
}

fun sanitizeClassName(stem: String): String {
    val cleaned = stem.map { if (it.isLetterOrDigit() || it == '_') it else '_' }.joinToString("")
    return if (cleaned.isEmpty() || cleaned[0].isDigit()) "dawn_$cleaned" else cleaned
}

// ---- run: execute in-process via a class loader ----

fun cmdRun(restIn: List<String>) {
    val (fuel, rest) = extractFuel(restIn)
    val path = rest.firstOrNull() ?: throw CliError("usage: dawn run <file.dawn>")
    val (className, classes) = compile(path, fuel)
    val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
        override fun findClass(name: String): Class<*> {
            val internal = name.replace('.', '/')
            val bytes = classes[internal] ?: throw ClassNotFoundException(name)
            return defineClass(name, bytes, 0, bytes.size)
        }
    }
    val cls = Class.forName(className, false, loader)
    val main = try {
        cls.getDeclaredMethod("main", Array<String>::class.java)
    } catch (e: NoSuchMethodException) {
        throw CliError("$path has no pub fn main() -> Unit !io, nothing to run")
    }
    main.invoke(null, rest.drop(1).toTypedArray())
}

// ---- test: compile with test blocks, run each, report ----

fun cmdTest(restIn: List<String>) {
    val (fuel, rest) = extractFuel(restIn)
    val path = rest.firstOrNull() ?: throw CliError("usage: dawn test <file.dawn>")
    val file = File(path)
    if (!file.exists()) throw CliError("no such file: $path")
    val source = SourceFile(path, file.readText())
    val className = sanitizeClassName(file.nameWithoutExtension)
    val analysis = analyze(source.text, fuel)
    if (analysis.hasErrors) {
        for (d in analysis.diagnostics) System.err.print(d.render(source))
        exitProcess(1)
    }
    val tests = analysis.module.tests
    if (tests.isEmpty()) throw CliError("$path has no test blocks")
    val classes = CodeGen(analysis.module, className, includeTests = true).generate()
    val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
        override fun findClass(name: String): Class<*> {
            val internal = name.replace('.', '/')
            val bytes = classes[internal] ?: throw ClassNotFoundException(name)
            return defineClass(name, bytes, 0, bytes.size)
        }
    }
    val cls = Class.forName(className, false, loader)
    var failed = 0
    for ((i, t) in tests.withIndex()) {
        val m = cls.getDeclaredMethod("dawn\$test\$$i")
        try {
            m.invoke(null)
            println("PASS  ${t.testName}")
        } catch (e: java.lang.reflect.InvocationTargetException) {
            failed++
            println("FAIL  ${t.testName}")
            e.cause?.message?.lines()?.forEach { println("      $it") }
        }
    }
    println(if (failed == 0) "${tests.size} test(s) passed" else "$failed of ${tests.size} test(s) failed")
    if (failed > 0) exitProcess(1)
}

// ---- fmt: reformat sources in place, or --check for CI ----

fun cmdFmt(rest: List<String>) {
    val check = rest.contains("--check")
    val paths = rest.filter { !it.startsWith("-") }
    if (paths.isEmpty()) throw CliError("usage: dawn fmt [--check] <file.dawn>...")
    var unformatted = 0
    for (p in paths) {
        val file = File(p)
        if (!file.exists()) throw CliError("no such file: $p")
        val original = file.readText()
        val formatted = dawn.fmt.Formatter.format(original)
        if (formatted == original) continue
        if (check) {
            println(p)
            unformatted++
        } else {
            file.writeText(formatted)
            println("formatted $p")
        }
    }
    if (check && unformatted > 0) exitProcess(1)
}

// ---- build: write a jar, optionally hand it to native-image ----

fun cmdBuild(restIn: List<String>) {
    val (fuel, rest) = extractFuel(restIn)
    val path = rest.firstOrNull { !it.startsWith("-") }
        ?: throw CliError("usage: dawn build <file.dawn> [-o out] [--native]")
    val native = rest.contains("--native")
    val oIdx = rest.indexOf("-o")
    val out = if (oIdx >= 0 && oIdx + 1 < rest.size) rest[oIdx + 1] else null

    val (className, classes) = compile(path, fuel)
    val jarPath = when {
        native -> File.createTempFile("dawn-build-", ".jar").absolutePath
        out != null -> out
        else -> File(path).nameWithoutExtension + ".jar"
    }
    writeJar(jarPath, className, classes)

    if (!native) {
        println("wrote $jarPath (run it with: java -jar $jarPath)")
        return
    }

    val binOut = out ?: File(path).nameWithoutExtension
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
