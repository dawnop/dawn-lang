package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import dawn.diag.Diagnostic
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** M2 knife 3: dot-call sugar (UFCS), core/string + io builtins, functions as values. */
class StdlibTest {

    private fun compileClasses(source: String): Map<String, ByteArray> {
        val analysis = analyze(source)
        check(!analysis.hasErrors) {
            "unexpected compile errors:\n" + analysis.diagnostics.joinToString("\n") { it.message }
        }
        return CodeGen(analysis.module, "testmod").generate()
    }

    private fun errorsOf(source: String): List<Diagnostic> {
        val analysis = analyze(source)
        assertTrue(analysis.hasErrors, "expected compile errors, got none")
        return analysis.diagnostics
    }

    private fun assertHasError(diags: List<Diagnostic>, substring: String) {
        assertTrue(
            diags.any { it.message.contains(substring) },
            "no diagnostic contains \"$substring\"; got:\n" + diags.joinToString("\n") { it.message },
        )
    }

    private fun run(source: String): String {
        val classes = compileClasses(source)
        val loader = object : ClassLoader(ClassLoader.getSystemClassLoader()) {
            override fun findClass(name: String): Class<*> {
                val bytes = classes[name.replace('.', '/')] ?: throw ClassNotFoundException(name)
                return defineClass(name, bytes, 0, bytes.size)
            }
        }
        val cls = Class.forName("testmod", false, loader)
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

    // ---- dot calls ----

    @Test
    fun `dot call is UFCS sugar`() {
        val out = run(
            """
            type Parser = { tokens: List[Int], pos: Int }

            fn peek(p: Parser) -> Option[Int] = p.tokens.get(p.pos)

            pub fn main() -> Unit !io = {
              let p = Parser { tokens: [10, 20], pos: 1 }
              match p.peek() {
                Some(v) -> println("${'$'}v")
                None -> println("eof")
              }
            }
            """.trimIndent(),
        )
        assertEquals("20\n", out)
    }

    @Test
    fun `dot call chains and takes extra arguments`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              let s = "  a-b-c  "
              println(s.trim().split("-").join("+"))
              println("${'$'}{[1, 2, 3].len()}")
            }
            """.trimIndent(),
        )
        assertEquals("a+b+c\n3\n", out)
    }

    // ---- strings ----

    @Test
    fun `chars splits by code point`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              println(chars("héllo").join("."))
              println("${'$'}{len(chars("\u{1F600}x"))}")
            }
            """.trimIndent(),
        )
        assertEquals("h.é.l.l.o\n2\n", out)
    }

    @Test
    fun `split is literal, not regex`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              println(split("a.b.c", ".").join("/"))
              println(split("no-sep", ",").join("|"))
            }
            """.trimIndent(),
        )
        assertEquals("a/b/c\nno-sep\n", out)
    }

    @Test
    fun `string predicates and to_string`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              println("${'$'}{contains("hello", "ell")} ${'$'}{starts_with("hello", "he")} ${'$'}{ends_with("hello", "lo")}")
              println(to_string(42) ++ to_string(true) ++ to_string(1.5))
            }
            """.trimIndent(),
        )
        assertEquals("true true true\n42true1.5\n", out)
    }

    @Test
    fun `parse_int and parse_float return Options`() {
        val out = run(
            """
            fn show(o: Option[Int]) -> String = match o { Some(n) -> "${'$'}n", None -> "none" }

            pub fn main() -> Unit !io = {
              println(show(parse_int("42")))
              println(show(parse_int("4x")))
              match parse_float("2.5") {
                Some(f) -> println("${'$'}f")
                None -> println("none")
              }
            }
            """.trimIndent(),
        )
        assertEquals("42\nnone\n2.5\n", out)
    }

    // ---- io ----

    @Test
    fun `write_file then read_file round-trips`() {
        val path = java.io.File.createTempFile("dawn-io-", ".txt").absolutePath
        val out = run(
            """
            pub fn main() -> Unit !io = {
              match write_file("$path", "hello\nfile") {
                Ok(n) -> println("wrote ${'$'}n")
                Err(e) -> println("err ${'$'}e")
              }
              match read_file("$path") {
                Ok(text) -> println(text)
                Err(e) -> println("err ${'$'}e")
              }
            }
            """.trimIndent(),
        )
        assertEquals("wrote 10\nhello\nfile\n", out)
        java.io.File(path).delete()
    }

    @Test
    fun `read_file on a missing path is an Err value`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              match read_file("/definitely/not/here.txt") {
                Ok(_) -> println("ok?!")
                Err(e) -> println("failed: ${'$'}{contains(e, "here.txt")}")
              }
            }
            """.trimIndent(),
        )
        assertEquals("failed: true\n", out)
    }

    @Test
    fun `args is empty without the JVM wrapper`() {
        val out = run(
            """
            pub fn main() -> Unit !io = println("${'$'}{len(args())}")
            """.trimIndent(),
        )
        assertEquals("0\n", out)
    }

    // ---- functions as values ----

    @Test
    fun `generic builtin as a value instantiated from context`() {
        val out = run(
            """
            pub fn main() -> Unit !io =
              println(join(map(range(0, 3), to_string), "."))
            """.trimIndent(),
        )
        assertEquals("0.1.2\n", out)
    }

    @Test
    fun `generic user function as a value`() {
        val out = run(
            """
            fn first[T](p: (T, T)) -> T = { let (a, _) = p
              a }

            fn nth(xs: List[Int], i: Int) -> Int =
              match xs.get(i) { Some(v) -> v, None -> -1 }

            pub fn main() -> Unit !io = {
              let firsts = map([(1, 2), (3, 4)], first)
              println("${'$'}{nth(firsts, 0)} ${'$'}{nth(firsts, 1)}")
            }
            """.trimIndent(),
        )
        assertEquals("1 3\n", out)
    }

    @Test
    fun `to_string of a non-printable type is rejected`() {
        val diags = errorsOf(
            """
            type P = { x: Int }
            fn f() -> String = to_string(P { x: 1 })
            """.trimIndent(),
        )
        assertHasError(diags, "cannot print a value of type P")
    }

    @Test
    fun `generic value without context is rejected with a hint`() {
        val diags = errorsOf(
            """
            fn f() -> Int = {
              let g = len
              1
            }
            """.trimIndent(),
        )
        assertHasError(diags, "cannot infer the type parameter(s) of `len`")
    }
}
