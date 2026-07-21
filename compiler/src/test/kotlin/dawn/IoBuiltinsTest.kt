package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import org.junit.jupiter.api.io.TempDir
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Filesystem builtins (list_dir / is_dir / write_file's parent creation) need a
 * real directory to poke at, so they live here rather than in golden/run.
 */
class IoBuiltinsTest {

    private fun run(source: String): String {
        val analysis = analyze(source)
        check(!analysis.hasErrors) {
            "unexpected compile errors:\n" + analysis.diagnostics.joinToString("\n") { it.message }
        }
        val classes = CodeGen(analysis.module, "iotest").generate()
        val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }
        val cls = Class.forName("iotest", false, loader)
        val m = cls.getDeclaredMethod("main")
        val buf = ByteArrayOutputStream()
        val old = System.out
        System.setOut(PrintStream(buf, true, "UTF-8"))
        try {
            m.invoke(null)
        } finally {
            System.setOut(old)
        }
        return buf.toString("UTF-8")
    }

    @Test
    fun `list_dir returns sorted names and is_dir distinguishes entries`(@TempDir dir: File) {
        File(dir, "b.txt").writeText("b")
        File(dir, "a.txt").writeText("a")
        File(dir, "sub").mkdir()
        val root = dir.absolutePath.replace("\\", "/")
        val out = run(
            """
            use std/io

            pub fn main() -> Unit !io = {
              match io.list_dir("$root") {
                Ok(names) -> { for n in names { println(n) } }
                Err(e) -> println("err: ${'$'}e")
              }
              println(to_string(io.is_dir("$root/sub")))
              println(to_string(io.is_dir("$root/a.txt")))
              println(to_string(io.is_dir("$root/missing")))
            }
            """.trimIndent(),
        )
        assertEquals("a.txt\nb.txt\nsub\ntrue\nfalse\nfalse\n", out)
    }

    @Test
    fun `list_dir on a file or missing path yields Err`(@TempDir dir: File) {
        File(dir, "plain.txt").writeText("x")
        val root = dir.absolutePath.replace("\\", "/")
        val out = run(
            """
            use std/io

            pub fn main() -> Unit !io = {
              match io.list_dir("$root/plain.txt") {
                Ok(_) -> println("ok")
                Err(e) -> println(e)
              }
              match io.list_dir("$root/nope") {
                Ok(_) -> println("ok")
                Err(e) -> println(e)
              }
            }
            """.trimIndent(),
        )
        assertEquals("not a directory: $root/plain.txt\nnot a directory: $root/nope\n", out)
    }

    @Test
    fun `write_file creates missing parent directories`(@TempDir dir: File) {
        val root = dir.absolutePath.replace("\\", "/")
        val out = run(
            """
            use std/io

            pub fn main() -> Unit !io = {
              match io.write_file("$root/deep/nested/out.txt", "hello") {
                Ok(_) -> println("wrote")
                Err(e) -> println("err: ${'$'}e")
              }
              match io.read_file("$root/deep/nested/out.txt") {
                Ok(s) -> println(s)
                Err(e) -> println("err: ${'$'}e")
              }
            }
            """.trimIndent(),
        )
        assertEquals("wrote\nhello\n", out)
        assertTrue(File(dir, "deep/nested/out.txt").isFile)
    }

    @Test
    fun `list_dir works as a function value`(@TempDir dir: File) {
        File(dir, "only.txt").writeText("x")
        val root = dir.absolutePath.replace("\\", "/")
        val out = run(
            """
            use std/io.{list_dir, is_dir}

            fn apply_fs(f: fn(String) -> Result[List[String], String] !io, p: String) -> Int !io =
              match f(p) {
                Ok(names) -> len(names)
                Err(_) -> -1
              }

            pub fn main() -> Unit !io = {
              println(to_string(apply_fs(list_dir, "$root")))
              println(to_string(is_dir("$root")))
            }
            """.trimIndent(),
        )
        assertEquals("1\ntrue\n", out)
    }
}
