package dawn

import dawn.check.analyzeProject
import dawn.codegen.CodeGen
import org.junit.jupiter.api.io.TempDir
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

/**
 * End-to-end for multi-module programs (spec §10, §12.2): load + check a project
 * tree, generate all classes with shared runtime hoisted once, run the entry
 * module's `main`, and check its stdout. Exercises qualified calls, selective
 * imports (types/ctors/consts), cross-module generics, and a shared ADT.
 */
class MultiModuleCodegenTest {

    private fun project(dir: File, files: Map<String, String>): File {
        for ((rel, text) in files) {
            val f = File(dir, "src/$rel")
            f.parentFile.mkdirs()
            f.writeText(text)
        }
        return dir
    }

    private fun runProject(dir: File): String {
        val program = analyzeProject(dir)
        assertFalse(program.hasErrors, "program did not check:\n" +
            program.diagnostics.joinToString("\n") { it.diag.message })
        val units = program.modules.map { CodeGen.Companion.ModuleUnit(it.module, it.className) }
        val classes = CodeGen.generateProgram(units)
        val entry = program.modules.first { m -> m.module.fns.any { it.name == "main" } }
        val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }
        val cls = Class.forName(entry.className.replace('/', '.'), false, loader)
        val buf = ByteArrayOutputStream()
        val old = System.out
        System.setOut(PrintStream(buf, true, "UTF-8"))
        try {
            cls.getDeclaredMethod("main").invoke(null)
        } finally {
            System.setOut(old)
        }
        return buf.toString("UTF-8")
    }

    @Test
    fun `qualified call, selective import, shared ADT and generic across modules`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use shapes.{Shape, Circle, Rect, area}
                use util/nums

                pub fn main() -> Unit !io = {
                  println(to_string(area(Circle(2.0))))
                  println(to_string(area(Rect(3.0, 4.0))))
                  println(to_string(nums.doubled(21)))
                  match nums.head([5, 6, 7]) {
                    Some(n) -> println(to_string(n))
                    None -> println("empty")
                  }
                  println(to_string(Circle(1.0)))
                }
            """.trimIndent(),
            "shapes.dawn" to """
                pub type Shape =
                  | Circle(r: Float)
                  | Rect(w: Float, h: Float)
                  derive Show

                pub fn area(s: Shape) -> Float =
                  match s {
                    Circle(r) -> 3.14 * r * r
                    Rect(w, h) -> w * h
                  }
            """.trimIndent(),
            "util/nums.dawn" to """
                pub fn doubled(x: Int) -> Int = x * 2
                pub fn head[T](xs: List[T]) -> Option[T] = get(xs, 0)
            """.trimIndent(),
        ))
        assertEquals(
            "12.56\n12.0\n42\n5\nCircle(1.0)\n",
            runProject(dir),
        )
    }

    @Test
    fun `constructor value across a module boundary`(@TempDir dir: File) {
        // Some/None are prelude, but map over an imported list module exercises the
        // shared runtime + a constructor value bridge living in the caller module
        project(dir, mapOf(
            "main.dawn" to """
                use boxes.{Box, wrap}
                pub fn main() -> Unit !io = {
                  let xs = map([1, 2, 3], wrap)
                  println(to_string(xs))
                }
            """.trimIndent(),
            "boxes.dawn" to """
                pub type Box = { value: Int } derive Show
                pub fn wrap(n: Int) -> Box = Box { value: n }
            """.trimIndent(),
        ))
        assertEquals("[Box { value: 1 }, Box { value: 2 }, Box { value: 3 }]\n", runProject(dir))
    }

    @Test
    fun `cross-module const is embedded by value`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use config.{LIMIT}
                pub fn main() -> Unit !io = println(to_string(LIMIT + 1))
            """.trimIndent(),
            "config.dawn" to "pub const LIMIT: Int = 99\n",
        ))
        assertEquals("100\n", runProject(dir))
    }
}
