package dawn.manifest

import java.io.File
import java.io.IOException
import java.net.InetSocketAddress
import java.net.ProxySelector
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.zip.ZipInputStream

/**
 * Fetching and verifying remote source packages (docs/package-design.md, url +
 * hash stage). The moving parts are deliberately few:
 *
 *  - archives are .zip only (JDK ZipInputStream, no new dependency);
 *  - the single top-level directory GitHub-style archives wrap everything in
 *    is stripped before hashing, so `.../archive/refs/tags/v1.zip` works as-is;
 *  - the d1 hash is computed over the *unpacked file tree*, never the archive
 *    bytes — GitHub regenerates archives and does not promise byte stability;
 *  - the cache is content-addressed (`$DAWN_PKG_CACHE`, default `~/.dawn/pkg`,
 *    one immutable `d1-<hex>/` per archive), so a cache hit never touches the
 *    network and two subdir packages from one monorepo archive share one entry.
 *
 * Failures throw [PkgFetchError]; the caller turns them into diagnostics at the
 * dependency's manifest span.
 */
class PkgFetchError(message: String, val hint: String? = null) : Exception(message)

object PkgFetch {

    /** d1: SHA-256 over the sorted file tree — `relpath \0 size \0 bytes` per regular file. */
    fun treeHash(root: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val files = ArrayList<Pair<String, File>>()
        collect(root, root, files)
        files.sortBy { it.first }
        for ((rel, f) in files) {
            digest.update(rel.toByteArray(Charsets.UTF_8))
            digest.update(0)
            digest.update(f.length().toString().toByteArray(Charsets.UTF_8))
            digest.update(0)
            f.inputStream().use { ins ->
                val buf = ByteArray(64 * 1024)
                while (true) {
                    val n = ins.read(buf)
                    if (n < 0) break
                    digest.update(buf, 0, n)
                }
            }
        }
        return "d1:" + digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun collect(root: File, dir: File, out: MutableList<Pair<String, File>>) {
        for (f in (dir.listFiles() ?: emptyArray()).sortedBy { it.name }) {
            if (Files.isSymbolicLink(f.toPath()))
                throw PkgFetchError("symbolic link in package tree: ${f.relativeTo(root)}",
                    "the d1 hash refuses symlinks — they do not survive archives portably")
            when {
                f.isDirectory -> collect(root, f, out)
                f.isFile -> out.add(root.toPath().relativize(f.toPath()).joinToString("/") to f)
            }
        }
    }

    /** The content-addressed cache root: `$DAWN_PKG_CACHE` or `~/.dawn/pkg` (the
     *  `dawn.pkg.cache` system property wins, so tests can isolate a cache). */
    fun cacheRoot(): File =
        System.getProperty("dawn.pkg.cache")?.let { File(it) }
            ?: System.getenv("DAWN_PKG_CACHE")?.let { File(it) }
            ?: File(System.getProperty("user.home"), ".dawn/pkg")

    fun cacheDir(hash: String): File = File(cacheRoot(), hash.replace(':', '-'))

    /**
     * The unpacked archive for [hash], fetching from [url] on a cache miss.
     * Verification happens exactly once, at fetch time: the cache is immutable
     * afterwards (Go's model — verify on download, trust the local copy).
     */
    fun ensureCached(url: String, hash: String): File {
        val target = cacheDir(hash)
        if (target.isDirectory) return target
        val work = Files.createTempDirectory(cacheRoot().apply { mkdirs() }.toPath(), "fetch-").toFile()
        try {
            unzip(download(url), work)
            val root = stripSingleTopDir(work)
            val actual = treeHash(root)
            if (actual != hash)
                throw PkgFetchError("hash mismatch for $url",
                    "declared:  $hash\n  actual:    $actual\n  " +
                        "if you just wrote this dependency, copy the actual value into `hash`")
            // rename into place; a concurrent fetch of the same hash yields the same bytes
            if (!target.isDirectory) {
                try {
                    Files.move(root.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE)
                } catch (e: IOException) {
                    if (!target.isDirectory) throw e
                }
            }
            return target
        } finally {
            work.deleteRecursively()
        }
    }

    private fun download(url: String): ByteArray {
        if (url.startsWith("file://")) {
            val f = File(URI(url))
            if (!f.isFile) throw PkgFetchError("no such file: $url")
            return f.readBytes()
        }
        val builder = HttpClient.newBuilder().followRedirects(HttpClient.Redirect.NORMAL)
        proxyFromEnv()?.let { builder.proxy(it) }
        val client = builder.build()
        val res: HttpResponse<ByteArray> = try {
            client.send(
                HttpRequest.newBuilder(URI(url)).GET().build(),
                HttpResponse.BodyHandlers.ofByteArray())
        } catch (e: Exception) {
            throw PkgFetchError("cannot fetch $url: ${e.message ?: e.javaClass.simpleName}",
                "check the network (https_proxy is honored) or pre-seed the cache")
        }
        if (res.statusCode() != 200)
            throw PkgFetchError("cannot fetch $url: HTTP ${res.statusCode()}")
        return res.body()
    }

    /** `https_proxy`/`HTTPS_PROXY` as a fixed proxy — the JDK ignores these env vars. */
    private fun proxyFromEnv(): ProxySelector? {
        val raw = System.getenv("https_proxy") ?: System.getenv("HTTPS_PROXY") ?: return null
        val uri = try { URI(if (raw.contains("://")) raw else "http://$raw") } catch (e: Exception) { return null }
        val host = uri.host ?: return null
        val port = if (uri.port > 0) uri.port else 80
        return ProxySelector.of(InetSocketAddress(host, port))
    }

    private fun unzip(bytes: ByteArray, dest: File) {
        var any = false
        ZipInputStream(bytes.inputStream()).use { zin ->
            while (true) {
                val entry = zin.nextEntry ?: break
                any = true
                val out = File(dest, entry.name)
                if (!out.canonicalPath.startsWith(dest.canonicalPath + File.separator) &&
                    out.canonicalPath != dest.canonicalPath)
                    throw PkgFetchError("archive entry escapes the extraction root: ${entry.name}")
                if (entry.isDirectory) out.mkdirs()
                else {
                    out.parentFile.mkdirs()
                    out.outputStream().use { zin.copyTo(it) }
                }
            }
        }
        if (!any) throw PkgFetchError("not a zip archive (or an empty one)",
            "only .zip archives are supported; for GitHub use .../archive/refs/tags/<tag>.zip")
    }

    /**
     * GitHub-style archives wrap everything in `<repo>-<tag>/`. When the
     * unpacked root holds exactly one directory and nothing else, that
     * directory is the tree; otherwise the root is.
     */
    private fun stripSingleTopDir(work: File): File {
        val entries = work.listFiles() ?: emptyArray()
        return if (entries.size == 1 && entries[0].isDirectory) entries[0] else work
    }
}
