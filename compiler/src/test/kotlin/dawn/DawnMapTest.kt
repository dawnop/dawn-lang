package dawn

import dawn.rt.DawnMap
import dawn.rt.DawnSet
import java.util.Random
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Correctness of the persistent HAMT behind Dawn's Map/Set (spec §2.2). The
 * decisive case is [oracle]: thousands of random assoc/without run against a
 * LinkedHashMap, whose semantics Dawn copies exactly (insertion-order
 * iteration, update keeps position, remove-then-readd goes to the end). If the
 * trie mishandles a node split, a collision, or a slot index, the two disagree.
 */
class DawnMapTest {

    private fun <K, V> assoc(m: DawnMap, k: K, v: V): DawnMap = m.assoc(k as Any?, v as Any?)

    @Test fun emptyBasics() {
        val m = DawnMap.EMPTY
        assertEquals(0, m.size)
        assertFalse(m.containsKey("x"))
        assertNull(m.get("x"))
        assertTrue(m.isEmpty())
    }

    @Test fun insertGetUpdatePersist() {
        val a = DawnMap.EMPTY.assoc("k", 1)
        val b = a.assoc("k", 2)
        assertEquals(1, a.get("k")) // a is unchanged by b's update
        assertEquals(2, b.get("k"))
        assertEquals(1, a.size)
        assertEquals(1, b.size)
    }

    @Test fun updateKeepsInsertionPosition() {
        var m = DawnMap.EMPTY
        m = m.assoc("b", 1).assoc("a", 1).assoc("c", 1)
        m = m.assoc("b", 99) // updating b must not move it to the end
        assertEquals(listOf("b", "a", "c"), m.keys.toList())
        assertEquals(listOf(99, 1, 1), m.values.toList())
    }

    @Test fun removeThenReaddGoesToEnd() {
        var m = DawnMap.EMPTY.assoc("a", 1).assoc("b", 1).assoc("c", 1)
        m = m.without("a").assoc("a", 1)
        assertEquals(listOf("b", "c", "a"), m.keys.toList())
    }

    @Test fun equalityIsOrderIndependent() {
        val m = DawnMap.EMPTY.assoc("a", 1).assoc("b", 2).assoc("c", 3)
        val n = DawnMap.EMPTY.assoc("c", 3).assoc("b", 2).assoc("a", 1)
        assertEquals(m, n)
        assertEquals(m.hashCode(), n.hashCode())
        // and equal to a plain java map with the same content
        assertEquals(linkedMapOf<Any, Any>("a" to 1, "b" to 2, "c" to 3) as Map<*, *>, m as Map<*, *>)
    }

    @Test fun nullKeyAndValue() {
        val m = DawnMap.EMPTY.assoc(null, "nv").assoc("nk", null)
        assertTrue(m.containsKey(null))
        assertEquals("nv", m.get(null))
        assertTrue(m.containsKey("nk"))
        assertNull(m.get("nk"))
        assertEquals(2, m.size)
    }

    /** Keys with identical hashCode but distinct equals must all coexist (collision nodes). */
    @Test fun hashCollisions() {
        class Collide(val id: Int) {
            override fun hashCode() = 7 // force every key into one collision chain
            override fun equals(other: Any?) = other is Collide && other.id == id
        }
        var m = DawnMap.EMPTY
        val keys = (0 until 200).map { Collide(it) }
        for (k in keys) m = m.assoc(k, k.id)
        assertEquals(200, m.size)
        for (k in keys) assertEquals(k.id, m.get(k))
        // remove half, the rest must survive
        for (i in 0 until 200 step 2) m = m.without(keys[i])
        assertEquals(100, m.size)
        for (i in 0 until 200) {
            if (i % 2 == 0) assertFalse(m.containsKey(keys[i]))
            else assertEquals(i, m.get(keys[i]))
        }
    }

    @Test fun oracle() {
        val rnd = Random(20260721L)
        val dawn = arrayOf(DawnMap.EMPTY) // boxed so the lambda can rebind
        val ref = LinkedHashMap<Int, Int>()
        val universe = 500 // small key space => many updates and real collisions in the trie
        repeat(60_000) {
            val k = rnd.nextInt(universe)
            if (rnd.nextInt(4) == 0 && ref.containsKey(k)) {
                dawn[0] = dawn[0].without(k)
                ref.remove(k)
            } else {
                val v = rnd.nextInt()
                dawn[0] = assoc(dawn[0], k, v)
                ref[k] = v
            }
        }
        val m = dawn[0]
        assertEquals(ref.size, m.size)
        // membership and values agree across the whole key space
        for (k in 0 until universe) {
            assertEquals(ref.containsKey(k), m.containsKey(k), "containsKey($k)")
            assertEquals(ref[k], m.get(k), "get($k)")
        }
        // iteration order is insertion order, exactly the LinkedHashMap's
        assertEquals(ref.keys.toList(), m.keys.map { it as Int }.toList())
        assertEquals(ref.entries.map { it.key to it.value }, m.entries.map { it.key to it.value })
        // order-independent equality holds against the reference
        assertEquals(ref as Map<*, *>, m as Map<*, *>)
    }

    @Test fun setBasics() {
        var s = DawnSet.EMPTY
        s = s.conj(3).conj(1).conj(3) // duplicate ignored
        assertEquals(2, s.size)
        assertTrue(s.contains(3))
        assertEquals(listOf(3, 1), s.toList()) // insertion order
        val s2 = s.disj(3)
        assertEquals(setOf(1) as Set<*>, s2 as Set<*>)
        assertEquals(2, s.size) // original persists
        // order-independent set equality
        assertEquals(DawnSet.EMPTY.conj(1).conj(3) as Set<*>, DawnSet.EMPTY.conj(3).conj(1) as Set<*>)
    }
}
