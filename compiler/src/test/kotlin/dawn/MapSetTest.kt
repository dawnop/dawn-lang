package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M4 knife 5: the builtin persistent Map and Set (spec §2.2). */
class MapSetTest {

    private fun run(source: String): String {
        val analysis = analyze(source)
        check(!analysis.hasErrors) {
            "unexpected compile errors:\n" + analysis.diagnostics.joinToString("\n") { it.message }
        }
        val classes = CodeGen(analysis.module, "testmod").generate()
        val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }
        val cls = Class.forName("testmod", false, loader)
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

    private fun errorsOf(source: String): List<String> {
        val analysis = analyze(source)
        assertTrue(analysis.hasErrors, "expected compile errors, got none")
        return analysis.diagnostics.map { it.message }
    }

    @Test
    fun `insert, get, has, size on a map`() {
        assertEquals(
            "Some(1)\nNone\ntrue\nfalse\n2\n",
            run(
                """
                use std/map

                pub fn main() -> Unit !io = {
                  let m = map.insert(map.insert(map.empty(), "a", 1), "b", 2)
                  println(to_string(map.get(m, "a")))
                  println(to_string(map.get(m, "z")))
                  println(to_string(map.has(m, "b")))
                  println(to_string(map.has(m, "z")))
                  println(to_string(map.size(m)))
                }
                """.trimIndent(),
            ),
        )
    }

    @Test
    fun `insert on an existing key replaces value and keeps insertion order`() {
        assertEquals(
            "[\"a\", \"b\", \"c\"]\n[1, 9, 3]\n",
            run(
                """
                use std/map

                pub fn main() -> Unit !io = {
                  let m0 = map.from([("a", 1), ("b", 2), ("c", 3)])
                  let m = map.insert(m0, "b", 9)
                  println(to_string(map.keys(m)))
                  println(to_string(map.values(m)))
                }
                """.trimIndent(),
            ),
        )
    }

    @Test
    fun `map_from later entries win`() {
        assertEquals(
            "Some(20)\n1\n",
            run(
                """
                use std/map

                pub fn main() -> Unit !io = {
                  let m = map.from([("x", 10), ("x", 20)])
                  println(to_string(map.get(m, "x")))
                  println(to_string(map.size(m)))
                }
                """.trimIndent(),
            ),
        )
    }

    @Test
    fun `remove is persistent - the original is unchanged`() {
        assertEquals(
            "1\n2\n",
            run(
                """
                use std/map

                pub fn main() -> Unit !io = {
                  let m = map.from([("a", 1), ("b", 2)])
                  let m2 = map.remove(m, "a")
                  println(to_string(map.size(m2)))
                  println(to_string(map.size(m)))
                }
                """.trimIndent(),
            ),
        )
    }

    @Test
    fun `map_entries yields insertion-ordered pairs`() {
        assertEquals(
            "[(\"a\", 1), (\"b\", 2)]\n",
            run(
                """
                use std/map

                pub fn main() -> Unit !io =
                  println(to_string(map.entries(map.from([("a", 1), ("b", 2)]))))
                """.trimIndent(),
            ),
        )
    }

    @Test
    fun `set add, membership, dedup and size`() {
        assertEquals(
            "true\nfalse\n3\n[1, 2, 3]\n",
            run(
                """
                use std/set

                pub fn main() -> Unit !io = {
                  let s = set.from([1, 2, 2, 3, 1])
                  println(to_string(set.has(s, 2)))
                  println(to_string(set.has(s, 9)))
                  println(to_string(set.size(s)))
                  println(to_string(set.to_list(s)))
                }
                """.trimIndent(),
            ),
        )
    }

    @Test
    fun `tuple and ADT keys use structural hashing`() {
        assertEquals(
            "Some(\"north\")\ntrue\n",
            run(
                """
                use std/map
                use std/set

                type Dir = North | South derive Show

                pub fn main() -> Unit !io = {
                  let m = map.insert(map.empty(), (1, 2), "north")
                  println(to_string(map.get(m, (1, 2))))
                  let s = set.insert(set.empty(), North)
                  println(to_string(set.has(s, North)))
                }
                """.trimIndent(),
            ),
        )
    }

    @Test
    fun `map equality is order-independent`() {
        assertEquals(
            "true\ntrue\n",
            run(
                """
                use std/map
                use std/set

                pub fn main() -> Unit !io = {
                  let a = map.from([("x", 1), ("y", 2)])
                  let b = map.from([("y", 2), ("x", 1)])
                  println(to_string(a == b))
                  let s1 = set.from([1, 2, 3])
                  let s2 = set.from([3, 2, 1])
                  println(to_string(s1 == s2))
                }
                """.trimIndent(),
            ),
        )
    }

    @Test
    fun `Show renders maps and sets as valid Dawn source`() {
        assertEquals(
            "map_from([(\"a\", 1), (\"b\", 2)])\nset_from([1, 2])\nmap_from([])\n",
            run(
                """
                use std/map
                use std/set

                pub fn main() -> Unit !io = {
                  println(to_string(map.from([("a", 1), ("b", 2)])))
                  println(to_string(set.from([1, 2])))
                  let empty: Map[String, Int] = map.empty()
                  println(to_string(empty))
                }
                """.trimIndent(),
            ),
        )
    }

    @Test
    fun `empty container needs a type annotation to infer, then works`() {
        assertEquals(
            "0\n",
            run(
                """
                use std/map

                pub fn main() -> Unit !io = {
                  let m: Map[String, Int] = map.empty()
                  println(to_string(map.size(m)))
                }
                """.trimIndent(),
            ),
        )
    }

    @Test
    fun `map with an unshowable value is rejected by to_string`() {
        val errs = errorsOf(
            """
            use std/map

            type Opaque = Mk(f: fn(Int) -> Int)

            pub fn main() -> Unit !io = {
              let m = map.insert(map.empty(), "a", Mk(fn(x) => x))
              println(to_string(m))
            }
            """.trimIndent(),
        )
        assertTrue(errs.any { it.contains("not printable") || it.contains("cannot") },
            "expected a printability error, got:\n" + errs.joinToString("\n"))
    }

    @Test
    fun `redefining Map is rejected`() {
        val errs = errorsOf("type Map = Nope\npub fn main() -> Unit !io = println(\"x\")\n")
        assertTrue(errs.any { it.contains("builtin type and cannot be redefined") })
    }
}
