package dawn.diag

/**
 * "Did you mean ...?" suggestions for a name that failed to resolve. A candidate
 * is offered only when it is within Levenshtein distance min(2, name.length/2) of
 * the typo — so single-character names never trigger a guess, and only genuinely
 * close matches surface. The nearest qualifying candidate wins.
 */
object Suggest {

    /** Closest candidate within threshold, or null if none is close enough. */
    fun closest(name: String, candidates: Iterable<String>): String? {
        val threshold = minOf(2, name.length / 2)
        if (threshold == 0) return null
        var best: String? = null
        var bestDist = threshold + 1
        for (c in candidates) {
            if (c == name) continue
            val d = distance(name, c, bestDist - 1)
            if (d < bestDist) {
                bestDist = d
                best = c
                if (d == 1) break // can't do better than an edit distance of 1
            }
        }
        return best
    }

    /** A ready-to-use hint line, or null when nothing is close. */
    fun hint(name: String, candidates: Iterable<String>): String? =
        closest(name, candidates)?.let { "did you mean `$it`?" }

    /** Levenshtein distance, abandoning early once it provably exceeds [limit]. */
    private fun distance(a: String, b: String, limit: Int): Int {
        if (kotlin.math.abs(a.length - b.length) > limit) return limit + 1
        var prev = IntArray(b.length + 1) { it }
        var curr = IntArray(b.length + 1)
        for (i in 1..a.length) {
            curr[0] = i
            var rowMin = curr[0]
            for (j in 1..b.length) {
                val cost = if (a[i - 1] == b[j - 1]) 0 else 1
                curr[j] = minOf(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
                if (curr[j] < rowMin) rowMin = curr[j]
            }
            if (rowMin > limit) return limit + 1
            val tmp = prev; prev = curr; curr = tmp
        }
        return prev[b.length]
    }
}
