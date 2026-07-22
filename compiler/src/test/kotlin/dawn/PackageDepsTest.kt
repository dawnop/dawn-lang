package dawn

import dawn.check.ModuleLoader
import dawn.check.analyzeProject
import org.junit.jupiter.api.io.TempDir
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * `[deps]` source packages (docs/package-design.md 项目 B, v1: local paths).
 * A consumer imports `use <alias>/<module>`; the package's own modules import
 * each other bare and the loader canonicalizes; dependency classes land under
 * dawn$pkg$<name>/ so they can never collide with user modules.
 */
class PackageDepsTest {

    private fun tree(dir: File, files: Map<String, String>): File {
        for ((rel, text) in files) {
            val f = File(dir, rel)
            f.parentFile.mkdirs()
            f.writeText(text)
        }
        return dir
    }

    /** a minimal two-module package `web` under <dir>/packages/web */
    private fun webPackage(dir: File) = tree(dir, mapOf(
        "packages/web/dawn.toml" to """
            schema = 1
            name = "web"
        """.trimIndent(),
        "packages/web/src/types.dawn" to """
            pub type Req = { path: String }
        """.trimIndent(),
        "packages/web/src/router.dawn" to """
            use types.{Req}

            pub fn describe(r: Req) -> String = "GET " ++ r.path
        """.trimIndent(),
    ))

    private fun app(dir: File, toml: String, main: String): File {
        tree(dir, mapOf("app/dawn.toml" to toml, "app/src/main.dawn" to main))
        return File(dir, "app")
    }

    private fun messages(dir: File): List<String> =
        analyzeProject(dir).diagnostics.map { it.diag.message }

    @Test
    fun `a consumer imports package modules and the package imports its own bare`(@TempDir dir: File) {
        webPackage(dir)
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps]
            web = "../packages/web"
        """.trimIndent(), """
            use web/router
            use web/types.{Req}

            pub fn main() -> Unit !io = println(router.describe(Req { path: "/x" }))
        """.trimIndent())
        val program = analyzeProject(appDir)
        val msgs = program.diagnostics.map { it.diag.message }
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
        val router = program.modules.first { it.modPath == "web/router" }
        assertEquals("dawn\$pkg\$web/router", router.className)
        // the package's bare `use types` was canonicalized to the qualified spelling
        assertTrue(program.modules.any { it.modPath == "web/types" })
    }

    @Test
    fun `an alias different from the package name is local sugar`(@TempDir dir: File) {
        webPackage(dir)
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps]
            w = "../packages/web"
        """.trimIndent(), """
            use w/router
            use w/types.{Req}

            pub fn main() -> Unit !io = println(router.describe(Req { path: "/x" }))
        """.trimIndent())
        val program = analyzeProject(appDir)
        val msgs = program.diagnostics.map { it.diag.message }
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
        // the aliased imports were canonicalized to the real name: one spelling,
        // one namespace, however consumers choose to spell it (§4.3/§4.4)
        assertEquals("dawn\$pkg\$web/router",
            program.modules.first { it.modPath == "web/router" }.className)
    }

    @Test
    fun `a dependency's java-deps link cleanly and surface for merging`(@TempDir dir: File) {
        webPackage(dir)
        File(dir, "packages/web/dawn.toml").appendText(
            "\n[java-deps]\nsqlite = \"org.xerial:sqlite-jdbc:3.36.0.3\"\n")
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps]
            web = "../packages/web"
        """.trimIndent(), """
            use web/router
            use web/types.{Req}

            pub fn main() -> Unit !io = println(router.describe(Req { path: "/x" }))
        """.trimIndent())
        val msgs = messages(appDir)
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
        assertEquals(listOf("org.xerial:sqlite-jdbc:3.36.0.3"),
            ModuleLoader.packageJavaDeps(appDir).map { it.toString() })
    }

    @Test
    fun `a local module path may not shadow a package alias`(@TempDir dir: File) {
        webPackage(dir)
        tree(dir, mapOf("app/src/web/router.dawn" to "pub fn describe() -> String = \"local\""))
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps]
            web = "../packages/web"
        """.trimIndent(), """
            use web/router

            pub fn main() -> Unit !io = println("x")
        """.trimIndent())
        assertTrue(messages(appDir).any { it.contains("ambiguous") })
    }

    @Test
    fun `a diamond links one copy of the shared package`(@TempDir dir: File) {
        webPackage(dir)
        tree(dir, mapOf(
            "packages/json/dawn.toml" to "schema = 1\nname = \"json\"",
            "packages/json/src/value.dawn" to "pub type J = | JStr(s: String)",
            "packages/web/dawn.toml" to """
                schema = 1
                name = "web"

                [deps]
                json = "../json"
            """.trimIndent(),
            "packages/web/src/render.dawn" to """
                use json/value.{J, JStr}

                pub fn hello() -> J = JStr("hi")
            """.trimIndent(),
        ))
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps]
            web = "../packages/web"
            json = "../packages/json"
        """.trimIndent(), """
            use web/render
            use json/value.{J, JStr}

            fn show_j(j: J) -> String = match j { JStr(s) -> s }

            pub fn main() -> Unit !io = println(show_j(render.hello()))
        """.trimIndent())
        val program = analyzeProject(appDir)
        val msgs = program.diagnostics.map { it.diag.message }
        assertTrue(msgs.isEmpty(), "expected clean, got:\n" + msgs.joinToString("\n"))
        // json loaded exactly once, under its own name — web's J and the app's J
        // are the same type, so the value flows across the diamond
        assertEquals(1, program.modules.count { it.modPath == "json/value" })
    }

    @Test
    fun `a package dependency cycle is reported`(@TempDir dir: File) {
        tree(dir, mapOf(
            "packages/a/dawn.toml" to "schema = 1\nname = \"a\"\n\n[deps]\nb = \"../b\"",
            "packages/a/src/x.dawn" to "pub fn one() -> Int = 1",
            "packages/b/dawn.toml" to "schema = 1\nname = \"b\"\n\n[deps]\na = \"../a\"",
            "packages/b/src/y.dawn" to "pub fn two() -> Int = 2",
        ))
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps]
            a = "../packages/a"
        """.trimIndent(), """
            pub fn main() -> Unit !io = println("x")
        """.trimIndent())
        assertTrue(messages(appDir).any { it.contains("cycle") })
    }

    @Test
    fun `a dependency directory without a manifest is an error`(@TempDir dir: File) {
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps]
            web = "../packages/web"
        """.trimIndent(), """
            pub fn main() -> Unit !io = println("x")
        """.trimIndent())
        assertTrue(messages(appDir).any { it.contains("has no dawn.toml") })
    }

    @Test
    fun `importing the package itself is an error`(@TempDir dir: File) {
        webPackage(dir)
        val appDir = app(dir, """
            schema = 1
            name = "app"

            [deps]
            web = "../packages/web"
        """.trimIndent(), """
            use web

            pub fn main() -> Unit !io = println("x")
        """.trimIndent())
        assertTrue(messages(appDir).any { it.contains("cannot import the package") })
    }
}
