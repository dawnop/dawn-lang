package dawn.manifest

import coursierapi.Dependency
import coursierapi.Fetch
import coursierapi.MavenRepository
import java.io.File

/**
 * Fetches `[java-deps]` from Maven and hands back a classpath
 * (docs/package-design.md §A.1).
 *
 * Resolution and caching are coursier's (`~/.cache/coursier`, mirroring the repo URL
 * structure — not `~/.m2`). Cold fetches hit the network; warm ones are a few hundred
 * milliseconds.
 *
 * Version conflicts among transitive dependencies resolve "highest wins", like Gradle
 * and unlike Maven's "nearest wins". That is deliberate: nearest-wins lets the *shape*
 * of the dependency graph pick versions, so an unrelated library declaring an old
 * version can silently downgrade one another component needs at runtime.
 */
object Maven {

    /** Repository override for mirrors, e.g. https://maven.aliyun.com/repository/public */
    const val MIRROR_ENV = "DAWN_MAVEN_MIRROR"

    class ResolveError(message: String) : Exception(message)

    /**
     * Resolve [deps] to jars, newest-wins across the transitive graph. Returns an empty
     * list for empty input without touching the network.
     */
    fun fetch(deps: List<MavenCoord>): List<File> {
        if (deps.isEmpty()) return emptyList()
        val fetch = Fetch.create()
        for (d in deps) fetch.addDependencies(Dependency.of(d.group, d.artifact, d.version))
        // A mirror is a property of where you are, not of what the project is, so it comes
        // from the environment and never from dawn.toml — the same manifest has to work on
        // both sides of a slow link.
        val mirror = System.getenv(MIRROR_ENV)?.trim()?.takeIf { it.isNotEmpty() }
        if (mirror != null) {
            fetch.withRepositories(MavenRepository.of(mirror))
        }
        return try {
            fetch.fetch()
        } catch (e: Exception) {
            throw ResolveError(explain(e, deps, mirror))
        }
    }

    /**
     * coursier reports failures as one long multi-line message; keep it (it names the
     * coordinate and the URLs tried) but lead with what the user should do about it.
     */
    private fun explain(e: Exception, deps: List<MavenCoord>, mirror: String?): String {
        val detail = (e.message ?: e.toString()).trim()
        val what = if (deps.size == 1) "dependency ${deps[0]}" else "${deps.size} dependencies"
        val where = mirror?.let { " from $it (\$$MIRROR_ENV)" } ?: ""
        val hint = when {
            detail.contains("not found", ignoreCase = true) ->
                "\n  check the coordinate in dawn.toml against the artifact on Maven Central"
            mirror != null ->
                "\n  the mirror in \$$MIRROR_ENV may not carry it; unset it to try Maven Central"
            else ->
                "\n  set \$$MIRROR_ENV to a closer mirror if this is a network timeout"
        }
        return "could not resolve $what$where:\n$detail$hint"
    }
}
