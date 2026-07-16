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
A project directory may carry a dawn.toml declaring [java-deps]; run/test/build fetch
those from Maven and put them on the class path automatically.

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

options (run/test/build):
  --cp <jars>                          third-party jars for `use java`, separated by the
                                       platform path separator; repeatable. `build` records
                                       them in the jar manifest's Class-Path. Merged with
                                       anything dawn.toml's [java-deps] resolves to.

environment:
  DAWN_MAVEN_MIRROR                    Maven repository to fetch [java-deps] from
                                       (default: Maven Central)
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

/** --cp <jars> / --cp=jars; repeatable, path-separator separated; returns (jars, args without the flag) */
fun extractCp(rest: List<String>): Pair<List<File>, List<String>> {
    val jars = ArrayList<File>()
    val out = ArrayList<String>()
    fun add(spec: String) {
        for (p in spec.split(File.pathSeparator)) {
            if (p.isEmpty()) continue
            val f = File(p)
            if (!f.exists()) throw CliError("--cp entry not found: $p")
            jars.add(f)
        }
    }
    var i = 0
    while (i < rest.size) {
        val a = rest[i]
        when {
            a == "--cp" && i + 1 < rest.size -> { add(rest[i + 1]); i += 2 }
            a == "--cp" -> throw CliError("--cp needs a path")
            a.startsWith("--cp=") -> { add(a.removePrefix("--cp=")); i++ }
            else -> { out.add(a); i++ }
        }
    }
    return jars to out
}

/** interop loader over --cp jars; null when the flag is absent (JDK only) */
fun cpLoader(jars: List<File>): ClassLoader? =
    if (jars.isEmpty()) null
    else java.net.URLClassLoader(jars.map { it.toURI().toURL() }.toTypedArray(), ClassLoader.getSystemClassLoader())

/**
 * A target's third-party jars: [fetched] from dawn.toml's [java-deps], [cp] from --cp.
 * They are kept apart because `build` vendors the fetched ones next to the jar it writes
 * but leaves --cp jars where the user put them.
 */
class Deps(val fetched: List<File>, val cp: List<File>) {
    val all: List<File> get() = fetched + cp
}

/**
 * Resolve a target's dependencies: dawn.toml's [java-deps] (when the target is a project
 * directory with a manifest) merged with any --cp jars. Manifest errors are rendered and
 * exit, like compile errors.
 */
fun resolveDeps(path: String, cp: List<File>): Deps {
    val dir = File(path)
    if (!dir.isDirectory) return Deps(emptyList(), cp)
    val file = dawn.manifest.Manifest.locate(dir) ?: return Deps(emptyList(), cp)
    val source = SourceFile(file.path, file.readText())
    val sink = dawn.diag.DiagnosticSink()
    val manifest = dawn.manifest.Manifest.parse(file, source, sink)
    if (manifest == null || sink.hasErrors) {
        System.err.print(dawn.manifest.renderManifestDiagnostics(source, sink.all))
        exitProcess(1)
    }
    if (manifest.javaDeps.isEmpty()) return Deps(emptyList(), cp)
    // a cold fetch downloads and can take a while; say so rather than hang silently
    System.err.println("resolving ${manifest.javaDeps.size} java-deps from ${file.path}...")
    val fetched = try {
        dawn.manifest.Maven.fetch(manifest.javaDeps)
    } catch (e: dawn.manifest.Maven.ResolveError) {
        throw CliError(e.message ?: "dependency resolution failed")
    }
    return Deps(fetched, cp)
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
fun compileProject(
    path: String,
    comptimeFuel: Long,
    includeTests: Boolean = false,
    javaLoader: ClassLoader? = null,
): CompiledProgram {
    val file = File(path)
    if (!file.exists()) throw CliError("no such file or directory: $path")
    if (file.isFile && !path.endsWith(".dawn")) throw CliError("source files must end in .dawn: $path")
    val program = analyzeProject(file, comptimeFuel, javaLoader)
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

/** A class loader backed by an in-memory class table; [parent] carries any --cp jars. */
private fun loaderFor(
    classes: Map<String, ByteArray>,
    parent: ClassLoader = ClassLoader.getSystemClassLoader(),
): ClassLoader =
    object : ClassLoader(parent) {
        override fun findClass(name: String): Class<*> {
            val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
            return defineClass(name, bytes, 0, bytes.size)
        }
    }

// ---- run: execute in-process via a class loader ----

fun cmdRun(restIn: List<String>) {
    val (fuel, rest0) = extractFuel(restIn)
    val (cp, rest) = extractCp(rest0)
    val path = rest.firstOrNull() ?: throw CliError("usage: dawn run [--cp jars] <file.dawn | project-dir>")
    val javaLoader = cpLoader(resolveDeps(path, cp).all)
    val program = compileProject(path, fuel, javaLoader = javaLoader)
    val entry = program.entry ?: throw CliError("$path has no pub fn main() -> Unit !io, nothing to run")
    val parent = javaLoader ?: ClassLoader.getSystemClassLoader()
    val loader = loaderFor(program.classes, parent)
    val cls = Class.forName(entry.className.replace('/', '.'), false, loader)
    val main = cls.getDeclaredMethod("main", Array<String>::class.java)
    // libraries discover services (e.g. JDBC drivers) via the context class loader
    Thread.currentThread().contextClassLoader = loader
    main.invoke(null, rest.drop(1).toTypedArray())
}

// ---- test: compile with test blocks, run each across all modules, report ----

fun cmdTest(restIn: List<String>) {
    val (fuel, rest0) = extractFuel(restIn)
    val (cp, rest) = extractCp(rest0)
    val path = rest.firstOrNull() ?: throw CliError("usage: dawn test [--cp jars] <file.dawn | project-dir>")
    val javaLoader = cpLoader(resolveDeps(path, cp).all)
    val program = compileProject(path, fuel, includeTests = true, javaLoader = javaLoader)
    // recover per-module test blocks (a module class holds dawn$test$i methods)
    val analyzed = analyzeProject(File(path), fuel, javaLoader)
    val loader = loaderFor(program.classes, javaLoader ?: ClassLoader.getSystemClassLoader())
    // libraries discover services (e.g. JDBC drivers) via the context class loader
    Thread.currentThread().contextClassLoader = loader
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
    val (fuel, rest0) = extractFuel(restIn)
    val (cp, rest) = extractCp(rest0)
    val path = rest.firstOrNull { !it.startsWith("-") }
        ?: throw CliError("usage: dawn build [--cp jars] <file.dawn | project-dir> [-o out] [--native]")
    val native = rest.contains("--native")
    val oIdx = rest.indexOf("-o")
    val out = if (oIdx >= 0 && oIdx + 1 < rest.size) rest[oIdx + 1] else null

    val deps = resolveDeps(path, cp)
    val program = compileProject(path, fuel, javaLoader = cpLoader(deps.all))
    val entry = program.entry ?: throw CliError("$path has no pub fn main() -> Unit !io to use as an entry point")
    val stem = File(path).let { if (it.isDirectory) it.name else it.nameWithoutExtension }
    val jarPath = when {
        native -> File.createTempFile("dawn-build-", ".jar").absolutePath
        out != null -> out
        else -> "$stem.jar"
    }

    // native-image inlines everything, so it reads the jars where they already live;
    // a plain jar needs them at a stable path next to itself, since the manifest
    // Class-Path is relative to the jar's own directory
    val classPath = if (native) deps.all else vendorJars(deps.fetched, jarPath) + deps.cp
    writeJar(jarPath, entry.className, program.classes, classPath = classPath)

    if (!native) {
        val libDir = File(jarPath).absoluteFile.parentFile
        when {
            classPath.isEmpty() -> println("wrote $jarPath (run it with: java -jar $jarPath)")
            deps.fetched.isEmpty() ->
                println("wrote $jarPath (run it with: java -jar $jarPath; manifest Class-Path points at the --cp jars, keep them in place)")
            else ->
                println("wrote $jarPath and ${deps.fetched.size} jar(s) into ${File(libDir, LIB_DIR).path} " +
                    "(run it with: java -jar $jarPath; keep lib/ next to the jar)")
        }
        return
    }

    val binOut = out ?: stem
    val nativeImage = findNativeImage() ?: throw CliError(
        "native-image not found. Install GraalVM and add it to PATH, or set GRAALVM_HOME",
    )
    println("invoking native-image (takes a minute or two the first time)...")
    // with --cp jars the -jar form would ignore them; pass an explicit class path + main class
    val cmd = if (cp.isEmpty())
        listOf(nativeImage, "-jar", jarPath, "-o", binOut, "--no-fallback")
    else
        listOf(nativeImage, "-cp",
            (listOf(jarPath) + cp.map { it.absolutePath }).joinToString(File.pathSeparator),
            entry.className.replace('/', '.'), "-o", binOut, "--no-fallback")
    val proc = ProcessBuilder(cmd)
        .redirectErrorStream(true)
        .start()
    proc.inputStream.bufferedReader().forEachLine { println("  $it") }
    val code = proc.waitFor()
    File(jarPath).delete()
    if (code != 0) throw CliError("native-image failed (exit code $code)")
    println("wrote $binOut (standalone binary, run it directly: ./$binOut)")
}

/** Where `build` puts jars fetched from dawn.toml, relative to the jar it writes. */
const val LIB_DIR = "lib"

/**
 * Copy resolved jars next to the output jar, under lib/, and return their new paths.
 *
 * They come out of coursier's cache, which is a content-addressed path in the user's home
 * — fine to compile against, useless to a deployed jar. Copying them to a fixed spot beside
 * the artifact keeps the manifest Class-Path relative, so `jar + lib/` stays movable.
 */
fun vendorJars(jars: List<File>, jarPath: String): List<File> {
    if (jars.isEmpty()) return emptyList()
    val libDir = File(File(jarPath).absoluteFile.parentFile, LIB_DIR)
    if (!libDir.isDirectory && !libDir.mkdirs()) throw CliError("could not create ${libDir.path}")
    return jars.map { src ->
        val dst = File(libDir, src.name)
        // the cache is immutable, so same name + same size means same bytes; skip the copy
        if (!dst.isFile || dst.length() != src.length()) src.copyTo(dst, overwrite = true)
        dst
    }
}

fun writeJar(
    jarPath: String,
    mainClass: String,
    classes: Map<String, ByteArray>,
    classPath: List<File> = emptyList(),
) {
    val manifest = Manifest()
    manifest.mainAttributes[Attributes.Name.MANIFEST_VERSION] = "1.0"
    manifest.mainAttributes[Attributes.Name.MAIN_CLASS] = mainClass
    if (classPath.isNotEmpty()) {
        // manifest Class-Path entries are URLs relative to the jar's own directory;
        // URI.relativize keeps entries under that directory relative, others absolute
        val base = File(jarPath).absoluteFile.parentFile.toURI()
        val entries = classPath.map { base.relativize(it.absoluteFile.toURI()).toString() }
        manifest.mainAttributes[Attributes.Name.CLASS_PATH] = entries.joinToString(" ")
    }
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
