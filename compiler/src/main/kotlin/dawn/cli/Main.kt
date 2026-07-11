package dawn.cli

import dawn.check.Checker
import dawn.codegen.CodeGen
import dawn.diag.DawnError
import dawn.diag.SourceFile
import dawn.parse.Parser
import java.io.File
import java.util.jar.Attributes
import java.util.jar.JarEntry
import java.util.jar.JarOutputStream
import java.util.jar.Manifest
import kotlin.system.exitProcess

const val USAGE = """dawn — the Dawn language toolchain (M0)

usage:
  dawn run <file.dawn>                 compile and run (in-process JVM)
  dawn build <file.dawn> [-o out.jar]  produce an executable jar
  dawn build <file.dawn> --native [-o out]
                                       produce a standalone native binary (needs native-image)
"""

fun main(args: Array<String>) {
    if (args.isEmpty()) {
        print(USAGE)
        exitProcess(2)
    }
    try {
        when (args[0]) {
            "run" -> cmdRun(args.drop(1))
            "build" -> cmdBuild(args.drop(1))
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

/** Compile one .dawn file → (class name, bytecode per class). Compile errors are rendered here and exit. */
fun compile(path: String): Pair<String, Map<String, ByteArray>> {
    val file = File(path)
    if (!file.exists()) throw CliError("no such file: $path")
    if (!path.endsWith(".dawn")) throw CliError("source files must end in .dawn: $path")
    val source = SourceFile(path, file.readText())
    val className = sanitizeClassName(file.nameWithoutExtension)
    try {
        val module = Parser.parseModule(source.text)
        Checker(module).check()
        return className to CodeGen(module, className).generate()
    } catch (e: DawnError) {
        System.err.print(e.render(source))
        exitProcess(1)
    }
}

fun sanitizeClassName(stem: String): String {
    val cleaned = stem.map { if (it.isLetterOrDigit() || it == '_') it else '_' }.joinToString("")
    return if (cleaned.isEmpty() || cleaned[0].isDigit()) "dawn_$cleaned" else cleaned
}

// ---- run: execute in-process via a class loader ----

fun cmdRun(rest: List<String>) {
    val path = rest.firstOrNull() ?: throw CliError("usage: dawn run <file.dawn>")
    val (className, classes) = compile(path)
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

// ---- build: write a jar, optionally hand it to native-image ----

fun cmdBuild(rest: List<String>) {
    val path = rest.firstOrNull { !it.startsWith("-") }
        ?: throw CliError("usage: dawn build <file.dawn> [-o out] [--native]")
    val native = rest.contains("--native")
    val oIdx = rest.indexOf("-o")
    val out = if (oIdx >= 0 && oIdx + 1 < rest.size) rest[oIdx + 1] else null

    val (className, classes) = compile(path)
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
