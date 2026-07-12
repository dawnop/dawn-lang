package dawn

import dawn.check.analyzeProject
import org.junit.jupiter.api.io.TempDir
import java.io.File
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Cross-module name resolution (spec §10.3/§10.4): qualified access `alias.fn`,
 * selective imports `use m.{...}`, visibility, and the shadowing rules. These are
 * inherently multi-file, so they run the whole-program front-end over temp trees
 * rather than the single-file golden harness.
 */
class CrossModuleTest {

    private fun project(dir: File, files: Map<String, String>): File {
        for ((rel, text) in files) {
            val f = File(dir, "src/$rel")
            f.parentFile.mkdirs()
            f.writeText(text)
        }
        return dir
    }

    private fun messages(dir: File): List<String> =
        analyzeProject(dir).diagnostics.map { it.diag.message }

    private fun assertClean(dir: File) {
        val msgs = messages(dir)
        assertTrue(msgs.isEmpty(), "expected a clean program, got:\n" + msgs.joinToString("\n"))
    }

    private fun assertError(dir: File, needle: String) {
        val msgs = messages(dir)
        assertTrue(msgs.any { it.contains(needle) },
            "expected an error containing `$needle`, got:\n" + msgs.joinToString("\n"))
    }

    // ---- positive: checking succeeds ----

    @Test
    fun `whole-module alias is the last path segment`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use util/math
                pub fn main() -> Unit !io = println(to_string(math.double(21)))
            """.trimIndent(),
            "util/math.dawn" to "pub fn double(x: Int) -> Int = x * 2\n",
        ))
        assertClean(dir)
    }

    @Test
    fun `selective import of a function`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use util.{double}
                pub fn main() -> Unit !io = println(to_string(double(21)))
            """.trimIndent(),
            "util.dawn" to "pub fn double(x: Int) -> Int = x * 2\n",
        ))
        assertClean(dir)
    }

    @Test
    fun `selective import of a type and its constructors`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use shapes.{Shape, Circle, Square}
                fn area(s: Shape) -> Float =
                  match s {
                    Circle(r) -> 3.14 * r * r
                    Square(side) -> side * side
                  }
                pub fn main() -> Unit !io = println(to_string(area(Circle(2.0))))
            """.trimIndent(),
            "shapes.dawn" to """
                pub type Shape =
                  | Circle(r: Float)
                  | Square(side: Float)
            """.trimIndent(),
        ))
        assertClean(dir)
    }

    @Test
    fun `cross-module const via selective import`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use config.{MAX_DEPTH}
                pub fn main() -> Unit !io = println(to_string(MAX_DEPTH))
            """.trimIndent(),
            "config.dawn" to "pub const MAX_DEPTH: Int = 512\n",
        ))
        assertClean(dir)
    }

    @Test
    fun `cross-module generic function`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use listx
                pub fn main() -> Unit !io = println(to_string(listx.first([10, 20, 30])))
            """.trimIndent(),
            "listx.dawn" to "pub fn first[T](xs: List[T]) -> Option[T] = get(xs, 0)\n",
        ))
        assertClean(dir)
    }

    @Test
    fun `effect propagates across a module boundary`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use io_util
                pub fn main() -> Unit !io = io_util.shout("hi")
            """.trimIndent(),
            "io_util.dawn" to "pub fn shout(s: String) -> Unit !io = println(s)\n",
        ))
        assertClean(dir)
    }

    // ---- negative: the right diagnostic fires ----

    @Test
    fun `pure caller of an imported io function is rejected`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use io_util
                fn quiet() -> Unit = io_util.shout("x")
                pub fn main() -> Unit !io = quiet()
            """.trimIndent(),
            "io_util.dawn" to "pub fn shout(s: String) -> Unit !io = println(s)\n",
        ))
        assertError(dir, "not declared !io")
    }

    @Test
    fun `accessing a private function is rejected`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use util
                pub fn main() -> Unit !io = println(to_string(util.secret()))
            """.trimIndent(),
            "util.dawn" to "fn secret() -> Int = 42\n",
        ))
        assertError(dir, "is private to module `util`")
    }

    @Test
    fun `unknown module member is rejected`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use util
                pub fn main() -> Unit !io = println(to_string(util.doubel(2)))
            """.trimIndent(),
            "util.dawn" to "pub fn double(x: Int) -> Int = x * 2\n",
        ))
        assertError(dir, "has no exported function `doubel`")
    }

    @Test
    fun `a top-level name shadowing a module alias is rejected`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use util
                fn util() -> Int = 1
                pub fn main() -> Unit !io = println(to_string(util()))
            """.trimIndent(),
            "util.dawn" to "pub fn double(x: Int) -> Int = x * 2\n",
        ))
        assertError(dir, "shadows the imported module `util`")
    }

    @Test
    fun `a local binding shadowing a module alias is rejected`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use util
                pub fn main() -> Unit !io = {
                  let util = 3
                  println(to_string(util))
                }
            """.trimIndent(),
            "util.dawn" to "pub fn double(x: Int) -> Int = x * 2\n",
        ))
        assertError(dir, "shadows the imported module `util`")
    }

    @Test
    fun `selective import colliding with a local declaration is rejected`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use util.{double}
                fn double(x: Int) -> Int = x + x
                pub fn main() -> Unit !io = println(to_string(double(2)))
            """.trimIndent(),
            "util.dawn" to "pub fn double(x: Int) -> Int = x * 2\n",
        ))
        assertError(dir, "conflicts with a name imported from `util`")
    }

    @Test
    fun `selective import of a nonexistent name is rejected`(@TempDir dir: File) {
        project(dir, mapOf(
            "main.dawn" to """
                use util.{triple}
                pub fn main() -> Unit !io = println("hi")
            """.trimIndent(),
            "util.dawn" to "pub fn double(x: Int) -> Int = x * 2\n",
        ))
        assertError(dir, "has no exported name `triple`")
    }
}
