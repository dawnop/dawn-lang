package dawn

import dawn.check.BUILTINS
import dawn.check.StdLib
import dawn.cli.cmdDoc
import org.junit.jupiter.api.io.TempDir
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DocCmdTest {

    private fun doc(vararg args: String): String {
        val buf = ByteArrayOutputStream()
        val old = System.out
        System.setOut(PrintStream(buf, true, "UTF-8"))
        try {
            cmdDoc(args.toList())
        } finally {
            System.setOut(old)
        }
        return buf.toString("UTF-8")
    }

    @Test
    fun `pub decls carry their doc comments, private decls are excluded`(@TempDir dir: File) {
        File(dir, "src").mkdirs()
        File(dir, "src/main.dawn").writeText(
            """
            ## Doubles an integer.
            ## Second line.
            pub fn double(x: Int) -> Int = x * 2

            fn hidden(x: Int) -> Int = x

            ## A 2D point.
            pub type Point = { x: Float, y: Float }

            ## Answer to everything.
            pub const ANSWER: Int = 42

            pub fn main() -> Unit !io = println(to_string(double(ANSWER)))
            """.trimIndent() + "\n",
        )
        val out = doc(dir.absolutePath)
        assertTrue(out.contains("\"name\": \"double\""), out)
        assertTrue(out.contains("\"sig\": \"fn double(x: Int) -> Int\""), out)
        assertTrue(out.contains("\"doc\": \"Doubles an integer.\\nSecond line.\""), out)
        assertFalse(out.contains("hidden"), out)
        assertTrue(out.contains("\"name\": \"Point\""), out)
        assertTrue(out.contains("\"record\": true"), out)
        assertTrue(out.contains("\"doc\": \"A 2D point.\""), out)
        assertTrue(out.contains("\"name\": \"ANSWER\""), out)
        assertTrue(out.contains("\"doc\": \"Answer to everything.\""), out)
    }

    @Test
    fun `a blank line detaches docs and plain comments are not docs`(@TempDir dir: File) {
        File(dir, "src").mkdirs()
        File(dir, "src/main.dawn").writeText(
            """
            ## Orphaned paragraph.

            pub fn detached(x: Int) -> Int = x

            # implementation note, not a doc
            pub fn plain(x: Int) -> Int = x

            pub fn main() -> Unit !io = println(to_string(detached(plain(1))))
            """.trimIndent() + "\n",
        )
        val out = doc(dir.absolutePath)
        assertFalse(out.contains("Orphaned"), out)
        assertFalse(out.contains("implementation note"), out)
        assertTrue(out.contains("\"name\": \"detached\""), out)
    }

    @Test
    fun `sum types list their constructors and fields`(@TempDir dir: File) {
        File(dir, "src").mkdirs()
        File(dir, "src/main.dawn").writeText(
            """
            ## A shape.
            pub type Shape =
              | Circle(r: Float)
              | Point

            pub fn main() -> Unit !io = {
              let s = Circle(1.0)
              match s {
                Circle(r) -> println(to_string(r))
                Point -> println("point")
              }
            }
            """.trimIndent() + "\n",
        )
        val out = doc(dir.absolutePath)
        assertTrue(out.contains("\"name\": \"Circle\""), out)
        assertTrue(out.contains("\"name\": \"r\""), out)
        assertTrue(out.contains("\"type\": \"Float\""), out)
        assertTrue(out.contains("\"name\": \"Point\""), out)
    }

    @Test
    fun `builtins reference covers every builtin exactly`() {
        val out = doc("--builtins")
        for (name in BUILTINS.keys) {
            assertTrue(out.contains("\"name\": \"$name\""), "builtin $name missing from dawn doc --builtins")
        }
        // and each carries a rendered signature and a description
        assertTrue(out.contains("\"sig\": \"fn list_dir(path: String) -> Result[List[String], String] !io\""), out)
        assertTrue(Regex("\"doc\": \"[^\"]+\"").containsMatchIn(out), out)
    }

    @Test
    fun `the reference also covers the bundled std, so migrating a builtin does not drop it`() {
        val out = doc("--builtins")
        for (name in StdLib.fns.keys) {
            assertTrue(out.contains("\"name\": \"$name\""), "std function $name missing from dawn doc --builtins")
        }
        // substring migrated out of the builtin table into std (pure-ffi-design.md §十);
        // it must still read as an ordinary reference entry, signature and all.
        assertFalse(BUILTINS.containsKey("substring"), "substring should no longer be a builtin")
        assertTrue(out.contains("\"sig\": \"fn substring(s: String, from: Int, to: Int) -> String\""), out)
        assertTrue(out.contains("\"name\": \"std/str\""), out)
    }
}
