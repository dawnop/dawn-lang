package dawn

import dawn.rt.DawnList
import java.util.ArrayList
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/**
 * The list representation behind `++` (docs/pure-ffi-design.md section 13): it
 * shares a backing array between successive versions so accumulation is linear,
 * which only stays sound if a published list never changes. These tests pin the
 * two ways that could break — aliasing and concurrency.
 */
class DawnListTest {

    /** concat over plain Kotlin lists; the runtime signature speaks java.util.List */
    private fun cat(a: List<Any?>, b: List<Any?>): List<Any?> =
        DawnList.concat(ArrayList(a), ArrayList(b))

    @Test
    fun `extending an older version does not disturb the newer one`() {
        val a = cat(listOf(1, 2), listOf(3))
        val base = cat(listOf<Any>(), listOf(1, 2))
        val b = cat(base, listOf(3))
        val c = cat(base, listOf(4)) // second append off the same base: must copy
        assertEquals(listOf(1, 2, 3), b)
        assertEquals(listOf(1, 2, 4), c)
        assertEquals(listOf(1, 2), base)
        // and the fork keeps growing independently
        assertEquals(listOf(1, 2, 3, 5), cat(b, listOf(5)))
        assertEquals(listOf(1, 2, 4), c)
        assertEquals(listOf(1, 2, 3), a)
    }

    @Test
    fun `repeated appends stay correct for a long run`() {
        var xs: List<Any?> = cat(listOf<Any>(), listOf<Any>())
        for (i in 0 until 5000) xs = cat(xs, listOf(i))
        assertEquals(5000, xs.size)
        assertEquals((0 until 5000).toList(), xs)
    }

    /**
     * Dawn programs are concurrent (backend-dawn runs a virtual thread per
     * request), so two threads can append to the same list at once. Exactly one
     * may take the in-place slot; every other must copy. A lost CAS would show
     * up here as two threads reading each other's element.
     */
    @Test
    fun `concurrent appends to one base each see only their own element`() {
        val threads = 8
        val rounds = 200
        Executors.newFixedThreadPool(threads).use { pool ->
            for (round in 0 until rounds) {
                val base = cat(listOf<Any>(), (0 until 50).toList())
                val tasks = (0 until threads).map { t ->
                    Callable { cat(base, listOf("t$t")) }
                }
                val results = pool.invokeAll(tasks).map { it.get() }
                for ((t, r) in results.withIndex()) {
                    assertEquals(51, r.size, "round $round thread $t got $r")
                    assertEquals("t$t", r[50], "round $round thread $t saw another thread's element")
                    assertEquals((0 until 50).toList(), r.subList(0, 50))
                }
                assertEquals(50, base.size, "the shared base must not grow")
            }
        }
    }

    @Test
    fun `a dawn list equals any other list with the same elements`() {
        val xs = cat(listOf<Any>(), listOf(1, 2, 3))
        assertEquals(listOf(1, 2, 3), xs)
        assertEquals(xs, listOf(1, 2, 3))
        assertEquals(listOf(1, 2, 3).hashCode(), xs.hashCode())
    }

    @Test
    fun `the representation is immutable`() {
        val xs = cat(listOf<Any>(), listOf(1, 2, 3))
        assertFailsWith<UnsupportedOperationException> { (xs as MutableList<Any?>).add(4) }
        assertFailsWith<IndexOutOfBoundsException> { xs[3] }
        assertTrue(xs is DawnList)
    }
}
