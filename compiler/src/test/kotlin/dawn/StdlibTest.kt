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

    // ---- strings ----

    @Test
    fun `to_lower and to_upper, inline and as values`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              println(to_lower("HeLLo Wörld"))
              println(to_upper("HeLLo"))
              println(join(map(["Ab", "cD"], to_lower), ","))
            }
            """.trimIndent(),
        )
        assertEquals("hello wörld\nHELLO\nab,cd\n", out)
    }

    // ---- result ----

    /**
     * The reason `map_err` exists: `?` demands identical error types, so without
     * it a handler returning `Result[_, Wrapped]` cannot propagate a repository's
     * `Result[_, String]` and has to hand-write a match whose Ok arm is a no-op.
     */
    @Test
    fun `map_err lets ? cross an error-type boundary`() {
        val out = run(
            """
            type Wrapped = { code: Int, text: String }

            fn repo() -> Result[Int, String] = Err("db is down")

            fn handler() -> Result[Int, Wrapped] = {
              let n = map_err(repo(), fn(m) => Wrapped { code: 500, text: m })?
              Ok(n + 1)
            }

            pub fn main() -> Unit !io =
              match handler() {
                Ok(n) -> println("ok ${'$'}n")
                Err(e) -> println("err ${'$'}{e.code} ${'$'}{e.text}")
              }
            """.trimIndent(),
        )
        assertEquals("err 500 db is down\n", out)
    }

    @Test
    fun `map_err leaves Ok untouched`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              let r: Result[Int, String] = Ok(7)
              match map_err(r, fn(msg) => 500) {
                Ok(n) -> println("ok ${'$'}n")
                Err(_) -> println("err")
              }
            }
            """.trimIndent(),
        )
        assertEquals("ok 7\n", out)
    }

    /** Effect-polymorphic like `list.map`: an `!io` callback is allowed. */
    @Test
    fun `map_err accepts an effectful callback`() {
        val out = run(
            """
            fn bad() -> Result[Int, String] = Err("boom")
            pub fn main() -> Unit !io =
              match map_err(bad(), fn(m) => { println("log: ${'$'}m")
                                              "wrapped: ${'$'}m" }) {
                Ok(_) -> println("unreachable")
                Err(e) -> println(e)
              }
            """.trimIndent(),
        )
        assertEquals("log: boom\nwrapped: boom\n", out)
    }

    // ---- io ----

    @Test
    fun `write_file then read_file round-trips`() {
        val path = java.io.File.createTempFile("dawn-io-", ".txt").absolutePath
        val out = run(
            """
            pub fn main() -> Unit !io = {
              match write_file("$path", "hello\nfile") {
                Ok(_) -> println("wrote")
                Err(e) -> println("err ${'$'}e")
              }
              match read_file("$path") {
                Ok(text) -> println(text)
                Err(e) -> println("err ${'$'}e")
              }
            }
            """.trimIndent(),
        )
        assertEquals("wrote\nhello\nfile\n", out)
        java.io.File(path).delete()
    }

    // ---- functions as values ----

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
