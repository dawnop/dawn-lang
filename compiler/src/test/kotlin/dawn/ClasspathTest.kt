package dawn

import dawn.check.analyze
import dawn.cli.CliError
import dawn.cli.extractCp
import dawn.cli.writeJar
import dawn.codegen.CodeGen
import org.junit.jupiter.api.io.TempDir
import org.objectweb.asm.ClassWriter
import org.objectweb.asm.Opcodes.ACC_PUBLIC
import org.objectweb.asm.Opcodes.ACC_STATIC
import org.objectweb.asm.Opcodes.ALOAD
import org.objectweb.asm.Opcodes.ARETURN
import org.objectweb.asm.Opcodes.INVOKEVIRTUAL
import org.objectweb.asm.Opcodes.V17
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.PrintStream
import java.net.URLClassLoader
import java.util.jar.JarEntry
import java.util.jar.JarFile
import java.util.jar.JarOutputStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** M6 knife 1: --cp — third-party jars on the compile and run class path. */
class ClasspathTest {

    @TempDir
    lateinit var tmp: File

    /** A minimal third-party jar: `thirdparty.Greeter.greet(name) = "hello, " + name`. */
    private fun greeterJar(): File {
        val cw = ClassWriter(0)
        cw.visit(V17, ACC_PUBLIC, "thirdparty/Greeter", null, "java/lang/Object", null)
        val mv = cw.visitMethod(ACC_PUBLIC or ACC_STATIC, "greet",
            "(Ljava/lang/String;)Ljava/lang/String;", null, null)
        mv.visitCode()
        mv.visitLdcInsn("hello, ")
        mv.visitVarInsn(ALOAD, 0)
        mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/String", "concat",
            "(Ljava/lang/String;)Ljava/lang/String;", false)
        mv.visitInsn(ARETURN)
        mv.visitMaxs(2, 1)
        mv.visitEnd()
        cw.visitEnd()
        val jar = File(tmp, "greeter.jar")
        JarOutputStream(jar.outputStream()).use { j ->
            j.putNextEntry(JarEntry("thirdparty/Greeter.class"))
            j.write(cw.toByteArray())
            j.closeEntry()
        }
        return jar
    }

    private val src = """
        use java "thirdparty.Greeter"

        pub fn main() -> Unit !io = {
          println(Greeter.greet("dawn").expect("greeting"))
        }
    """.trimIndent()

    @Test
    fun `third-party class is unresolved without a classpath and the hint names --cp`() {
        val analysis = analyze(src)
        assertTrue(analysis.hasErrors)
        val diag = analysis.diagnostics.first { it.message.contains("Java class not found") }
        assertTrue(diag.hint!!.contains("--cp"), "hint should point at --cp, got: ${diag.hint}")
    }

    @Test
    fun `a jar loader resolves the class and the program runs against it`() {
        val jar = greeterJar()
        val jarLoader = URLClassLoader(arrayOf(jar.toURI().toURL()), ClassLoader.getSystemClassLoader())
        val analysis = analyze(src, javaLoader = jarLoader)
        check(!analysis.hasErrors) {
            "unexpected compile errors:\n" + analysis.diagnostics.joinToString("\n") { it.message }
        }
        val classes = CodeGen(analysis.module, "cptest").generate()
        val loader = object : ClassLoader(jarLoader) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }
        val cls = Class.forName("cptest", false, loader)
        val m = cls.getDeclaredMethod("main")
        val buf = ByteArrayOutputStream()
        val old = System.out
        System.setOut(PrintStream(buf, true, "UTF-8"))
        try {
            m.invoke(null)
        } finally {
            System.setOut(old)
        }
        assertEquals("hello, dawn\n", buf.toString("UTF-8"))
    }

    @Test
    fun `extractCp accepts both forms and accumulates repeats`() {
        val a = File(tmp, "a.jar").apply { writeText("") }
        val b = File(tmp, "b.jar").apply { writeText("") }
        val (jars, rest) = extractCp(listOf("--cp", a.path, "prog", "--cp=${b.path}", "arg"))
        assertEquals(listOf(a.path, b.path), jars.map { it.path })
        assertEquals(listOf("prog", "arg"), rest)
    }

    @Test
    fun `extractCp splits on the platform path separator`() {
        val a = File(tmp, "a.jar").apply { writeText("") }
        val b = File(tmp, "b.jar").apply { writeText("") }
        val (jars, _) = extractCp(listOf("--cp", a.path + File.pathSeparator + b.path))
        assertEquals(2, jars.size)
    }

    @Test
    fun `extractCp rejects missing entries and a bare flag`() {
        assertFailsWith<CliError> { extractCp(listOf("--cp", File(tmp, "nope.jar").path)) }
        assertFailsWith<CliError> { extractCp(listOf("--cp")) }
    }

    @Test
    fun `built jar records a relative Class-Path and runs under java -jar`() {
        val jar = greeterJar()
        val jarLoader = URLClassLoader(arrayOf(jar.toURI().toURL()), ClassLoader.getSystemClassLoader())
        val analysis = analyze(src, javaLoader = jarLoader)
        check(!analysis.hasErrors)
        val classes = CodeGen(analysis.module, "cptest").generate()
        val appJar = File(tmp, "app.jar")
        writeJar(appJar.path, "cptest", classes, classPath = listOf(jar))

        // the dependency sits next to app.jar, so the manifest entry must be relative
        JarFile(appJar).use { jf ->
            val cpAttr = jf.manifest.mainAttributes.getValue("Class-Path")
            assertEquals("greeter.jar", cpAttr)
        }

        val java = File(System.getProperty("java.home"), "bin/java")
        val proc = ProcessBuilder(java.path, "-jar", appJar.path)
            .redirectErrorStream(true)
            .start()
        val out = proc.inputStream.bufferedReader().readText()
        val code = proc.waitFor()
        assertEquals(0, code, "java -jar failed:\n$out")
        assertEquals("hello, dawn\n", out)
    }
}
