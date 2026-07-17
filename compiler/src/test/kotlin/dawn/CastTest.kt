package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * The generic interop cast `cast(x) -> T` (spec §9.5, docs/cast-interop.md): reclaim an erased
 * Java Object as a concrete reference type T, taken from the expected type at the call site.
 * Replaces the old monomorphic `as_bytes`. Bytes reclaim itself is covered in BytesTest.
 */
class CastTest {

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
    fun `cast reclaims an erased Object as String, T from the annotation`() {
        val out = run(
            """
            use java "java.util.Optional"
            pub fn main() -> Unit !io = {
              let o = Optional.of("hi").expect("o")
              let s: String = cast(o.get().expect("g"))
              println(s)
            }
            """.trimIndent(),
        )
        assertEquals("hi\n", out)
    }

    @Test
    fun `cast takes T from a record field type, not just a let annotation`() {
        // the streaming StreamResp { stream: cast(...) } and the http BytesResp { bytes: cast(...) }
        // both rely on field-position expected-type propagation.
        val out = run(
            """
            use java "java.util.Optional"
            type Wrap = { b: Bytes }
            pub fn main() -> Unit !io = {
              let o = Optional.of(utf8("hi")).expect("o")
              let w = Wrap { b: cast(o.get().expect("g")) }
              println("${'$'}{byte_len(w.b)}")
            }
            """.trimIndent(),
        )
        assertEquals("2\n", out)
    }

    @Test
    fun `cast target must be a reference type, not a primitive`() {
        val errs = errorsOf(
            """
            use java "java.util.Optional"
            pub fn main() -> Unit !io = {
              let o = Optional.of(utf8("hi")).expect("o")
              let n: Int = cast(o.get().expect("g"))
              println("${'$'}{n}")
            }
            """.trimIndent(),
        )
        assertTrue(errs.any { "reference type" in it }, "got: $errs")
    }

    @Test
    fun `cast with no expected type is rejected — annotate the use site`() {
        val errs = errorsOf(
            """
            use java "java.util.Optional"
            pub fn main() -> Unit !io = {
              let o = Optional.of(utf8("hi")).expect("o")
              let b = cast(o.get().expect("g"))
              println("${'$'}{byte_len(b)}")
            }
            """.trimIndent(),
        )
        assertTrue(errs.any { "infer type parameter" in it || "annotation" in it }, "got: $errs")
    }

    @Test
    fun `a wrong cast fails loud at runtime and java_try catches it`() {
        val out = run(
            """
            use java "java.util.Optional"
            fn go() -> Result[Int, String] !io =
              java_try(fn() => {
                let o = Optional.of(utf8("hi")).expect("o")
                let s: String = cast(o.get().expect("g"))   # value is a byte[], not a String
                str_len(s)
              })
            pub fn main() -> Unit !io =
              match go() {
                Ok(n) -> println("ok ${'$'}{n}")
                Err(_) -> println("caught")
              }
            """.trimIndent(),
        )
        assertEquals("caught\n", out)
    }
}
