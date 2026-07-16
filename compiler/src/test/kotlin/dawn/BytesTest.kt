package dawn

import dawn.check.analyze
import dawn.codegen.CodeGen
import java.io.ByteArrayOutputStream
import java.io.PrintStream
import kotlin.test.Test
import kotlin.test.assertEquals

/** M7 序4: the first-class Bytes type (spec §9.5). */
class BytesTest {

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
    fun `utf8 and decode round-trip, including non-ascii`() {
        // é is two UTF-8 bytes, so byte length exceeds the code-point length.
        val out = run(
            """
            pub fn main() -> Unit !io = {
              let b = utf8("héllo")
              println("${'$'}{byte_len(b)}")
              println(decode(b, "UTF-8"))
              println(utf8("world").decode("UTF-8"))
            }
            """.trimIndent(),
        )
        assertEquals("6\nhéllo\nworld\n", out)
    }

    @Test
    fun `concat, byte_at and structural equality`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              let j = utf8("hi") ++ utf8(" ") ++ utf8("world")
              println(decode(j, "UTF-8"))
              println("${'$'}{byte_len(j)}")
              println("${'$'}{byte_at(utf8("A"), 0)}")
              println("${'$'}{utf8("abc") == utf8("abc")}")
              println("${'$'}{utf8("abc") == utf8("abd")}")
              println("${'$'}{utf8("abc") != utf8("abd")}")
            }
            """.trimIndent(),
        )
        assertEquals("hi world\n8\n65\ntrue\nfalse\ntrue\n", out)
    }

    @Test
    fun `byte_slice clamps out-of-range indices`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              let j = utf8("hi world")
              println(decode(byte_slice(j, 0, 2), "UTF-8"))
              println(decode(byte_slice(j, 3, 999), "UTF-8"))
              println("${'$'}{byte_len(byte_slice(j, 5, 1))}")
              println("${'$'}{byte_len(byte_slice(j, 0-4, 2))}")
            }
            """.trimIndent(),
        )
        // "hi", "world", empty (start>end), and negative start clamps to 0 -> "hi" = 2
        assertEquals("hi\nworld\n0\n2\n", out)
    }

    @Test
    fun `byte_index_of finds, offsets, and reports absence`() {
        val out = run(
            """
            pub fn main() -> Unit !io = {
              let j = utf8("abcabc")
              print_i(byte_index_of(j, utf8("bc"), 0))
              print_i(byte_index_of(j, utf8("bc"), 2))
              print_i(byte_index_of(j, utf8("xyz"), 0))
              print_i(byte_index_of(j, utf8(""), 3))
            }
            fn print_i(o: Option[Int]) -> Unit !io =
              match o {
                Some(i) -> println("${'$'}i")
                None -> println("none")
              }
            """.trimIndent(),
        )
        // first "bc" at 1, next from 2 at 4, absent -> none, empty needle at from=3
        assertEquals("1\n4\nnone\n3\n", out)
    }

    @Test
    fun `high bytes survive byte-exact (0, 127, 128, 255)`() {
        // Base64.decode yields a concrete byte[] -> Option[Bytes]; byte_at reads
        // each byte as an unsigned 0..255 Int, proving no sign-extension leak.
        val out = run(
            """
            use java "java.util.Base64"
            pub fn main() -> Unit !io = {
              let b = Base64.getDecoder().expect("d").decode("AH+A/w==").expect("x")
              println("${'$'}{byte_len(b)}")
              println("${'$'}{byte_at(b, 0)} ${'$'}{byte_at(b, 1)} ${'$'}{byte_at(b, 2)} ${'$'}{byte_at(b, 3)}")
            }
            """.trimIndent(),
        )
        assertEquals("4\n0 127 128 255\n", out)
    }

    @Test
    fun `Bytes passes to a java byte array param and round-trips`() {
        // digest(byte[]) takes a Bytes; toByteArray() returns a Bytes.
        val out = run(
            """
            use java "java.security.MessageDigest"
            use java "java.io.ByteArrayOutputStream"
            pub fn main() -> Unit !io = {
              let md = MessageDigest.getInstance("SHA-256").expect("md")
              println("${'$'}{byte_len(md.digest(utf8("abc")).expect("d"))}")
              let baos = ByteArrayOutputStream.new()
              baos.write(utf8("hello"))
              println(decode(baos.toByteArray().expect("o"), "UTF-8"))
            }
            """.trimIndent(),
        )
        assertEquals("32\nhello\n", out)
    }

    @Test
    fun `as_bytes reinterprets an erased-generic Object as Bytes`() {
        val out = run(
            """
            use java "java.util.Optional"
            pub fn main() -> Unit !io = {
              let o = Optional.of(utf8("hi")).expect("o")
              let b: Bytes = as_bytes(o.get().expect("g"))
              println("${'$'}{byte_len(b)}")
            }
            """.trimIndent(),
        )
        assertEquals("2\n", out)
    }

    @Test
    fun `Show renders Bytes as a byte-count summary`() {
        val out = run(
            """
            type Blob = { name: String, data: Bytes } derive Show
            pub fn main() -> Unit !io = {
              println(to_string(utf8("héllo")))
              println(to_string(Blob { name: "x", data: utf8("hi") }))
            }
            """.trimIndent(),
        )
        assertEquals("<6 bytes>\nBlob { name: \"x\", data: <2 bytes> }\n", out)
    }
}
