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
import java.util.zip.GZIPInputStream
import java.util.zip.ZipInputStream

/**
 * Fetching and verifying remote source packages (docs/package-design.md, url +
 * hash stage). The moving parts are deliberately few:
 *
 *  - archives are .zip or .tar.gz (JDK ZipInputStream/GZIPInputStream plus a
 *    small ustar reader below — still no new dependency);
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
        val (dir, actual) = fetchAndHash(url)
        if (actual != hash)
            throw PkgFetchError("hash mismatch for $url",
                "declared:  $hash\n  actual:    $actual\n  " +
                    "if you just wrote this dependency, copy the actual value into `hash`")
        return dir
    }

    /**
     * Fetch [url], unpack, hash, and file the tree into the cache under its own
     * (actual) hash — content-addressing makes that correct even when the caller
     * expected something else. Returns the cache entry and the d1 hash; `dawn add`
     * uses this to learn the hash of an archive it has never seen.
     */
    fun fetchAndHash(url: String): Pair<File, String> {
        val work = Files.createTempDirectory(cacheRoot().apply { mkdirs() }.toPath(), "fetch-").toFile()
        try {
            unpack(download(url), work)
            val root = stripSingleTopDir(work)
            val actual = treeHash(root)
            val target = cacheDir(actual)
            // rename into place; a concurrent fetch of the same hash yields the same bytes
            if (!target.isDirectory) {
                try {
                    Files.move(root.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE)
                } catch (e: IOException) {
                    if (!target.isDirectory) throw e
                }
            }
            return target to actual
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

    /** zip or tar.gz, told apart by magic bytes (a gzip stream starts 1f 8b). */
    private fun unpack(bytes: ByteArray, dest: File) {
        if (bytes.size >= 2 && bytes[0] == 0x1f.toByte() && bytes[1] == 0x8b.toByte()) untar(bytes, dest)
        else unzip(bytes, dest)
    }

    /** The extraction target for an archive entry, with the zip-slip guard. */
    private fun entryFile(dest: File, name: String): File {
        val out = File(dest, name)
        if (!out.canonicalPath.startsWith(dest.canonicalPath + File.separator) &&
            out.canonicalPath != dest.canonicalPath)
            throw PkgFetchError("archive entry escapes the extraction root: $name")
        return out
    }

    private fun unzip(bytes: ByteArray, dest: File) {
        var any = false
        ZipInputStream(bytes.inputStream()).use { zin ->
            while (true) {
                val entry = zin.nextEntry ?: break
                any = true
                val out = entryFile(dest, entry.name)
                if (entry.isDirectory) out.mkdirs()
                else {
                    out.parentFile.mkdirs()
                    out.outputStream().use { zin.copyTo(it) }
                }
            }
        }
        if (!any) throw PkgFetchError("not a zip archive (or an empty one)",
            ".zip and .tar.gz archives are supported; for GitHub use .../archive/refs/tags/<tag>.zip")
    }

    /**
     * A gzipped ustar reader covering what release archives actually contain:
     * plain files and directories, GNU `L` long names, and pax `x` path
     * overrides (GitHub tarballs use pax for long paths). Links are refused —
     * the d1 hash would refuse them anyway, and this reports the honest reason.
     */
    private fun untar(bytes: ByteArray, dest: File) {
        var any = false
        GZIPInputStream(bytes.inputStream()).use { ins ->
            val block = ByteArray(512)
            fun readBlock(): Boolean {
                var off = 0
                while (off < 512) {
                    val n = ins.read(block, off, 512 - off)
                    if (n < 0) return if (off == 0) false else throw PkgFetchError("truncated tar archive")
                    off += n
                }
                return true
            }
            fun readData(size: Long): ByteArray {
                if (size > Int.MAX_VALUE) throw PkgFetchError("tar entry too large")
                val out = ByteArray(size.toInt())
                var off = 0
                while (off < out.size) {
                    val n = ins.read(out, off, out.size - off)
                    if (n < 0) throw PkgFetchError("truncated tar archive")
                    off += n
                }
                val pad = ((512 - size % 512) % 512).toInt()
                var skipped = 0L
                while (skipped < pad) {
                    val n = ins.skip(pad - skipped)
                    if (n <= 0) throw PkgFetchError("truncated tar archive")
                    skipped += n
                }
                return out
            }
            fun str(off: Int, len: Int): String {
                var end = off
                while (end < off + len && block[end] != 0.toByte()) end++
                return String(block, off, end - off, Charsets.UTF_8)
            }
            fun octal(off: Int, len: Int): Long {
                if (block[off].toInt() and 0x80 != 0)
                    throw PkgFetchError("GNU base-256 tar sizes are not supported")
                val s = str(off, len).trim()
                if (s.isEmpty()) return 0
                return s.toLongOrNull(8) ?: throw PkgFetchError("bad size field in tar header")
            }

            var pendingName: String? = null
            while (readBlock()) {
                if (block.all { it == 0.toByte() }) break // end-of-archive marker
                val size = octal(124, 12)
                val type = block[156].toInt().toChar()
                val magic = str(257, 6)
                val prefix = if (magic.startsWith("ustar")) str(345, 155) else ""
                val rawName = str(0, 100)
                val name = pendingName ?: (if (prefix.isEmpty()) rawName else "$prefix/$rawName")
                pendingName = null
                when (type) {
                    'L' -> { // GNU long name: the data block is the next entry's name
                        pendingName = String(readData(size), Charsets.UTF_8).substringBefore('\u0000')
                        continue
                    }
                    'x' -> { // pax extended header: records are "<len> key=value\n"
                        val recs = String(readData(size), Charsets.UTF_8)
                        var i = 0
                        while (i < recs.length) {
                            val sp = recs.indexOf(' ', i)
                            if (sp < 0) break
                            val recLen = recs.substring(i, sp).toIntOrNull() ?: break
                            val rec = recs.substring(sp + 1, i + recLen).trimEnd('\n')
                            if (rec.startsWith("path=")) pendingName = rec.removePrefix("path=")
                            i += recLen
                        }
                        continue
                    }
                    'g' -> { readData(size); continue } // pax global: nothing we honor
                    '5' -> entryFile(dest, name).mkdirs()
                    '0', '\u0000', '7' -> {
                        val out = entryFile(dest, name)
                        out.parentFile.mkdirs()
                        out.writeBytes(readData(size))
                    }
                    '1', '2' -> throw PkgFetchError("link in tar archive: $name",
                        "the d1 hash refuses links — they do not survive archives portably")
                    else -> throw PkgFetchError("unsupported tar entry type `$type`: $name")
                }
                any = true
            }
        }
        if (!any) throw PkgFetchError("not a tar.gz archive (or an empty one)",
            ".zip and .tar.gz archives are supported; for GitHub use .../archive/refs/tags/<tag>.tar.gz")
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
