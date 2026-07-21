package dawn.rt;

import java.util.AbstractSet;
import java.util.Iterator;

/**
 * Dawn's {@code Set}: immutable, with O(log32 n) membership and insert.
 *
 * <p>The same copy-on-write quadratic that {@link DawnMap} fixes for maps
 * applied to sets built one element at a time (spec section 2.2 pairs them).
 * A set is just a map from each element to a shared {@code PRESENT} marker, so
 * this delegates to {@link DawnMap} and inherits its HAMT, its insertion-order
 * iteration, and its thread-safe publication; only the {@code java.util.Set}
 * face differs.
 *
 * <p>Extending {@link AbstractSet} gives an order-independent {@code
 * equals}/{@code hashCode} (spec section 2.2: equality ignores order) and lets
 * this drop in wherever the compiler already speaks {@code java.util.Set}.
 */
public final class DawnSet extends AbstractSet<Object> {

    private static final Object PRESENT = new Object();
    public static final DawnSet EMPTY = new DawnSet(DawnMap.EMPTY);

    private final DawnMap m;

    private DawnSet(DawnMap m) {
        this.m = m;
    }

    /** Return a set with {@code elem} added; O(log32 n). */
    public DawnSet conj(Object elem) {
        DawnMap n = m.assoc(elem, PRESENT);
        return n == m ? this : new DawnSet(n);
    }

    /** Return a set without {@code elem}; O(log32 n). */
    public DawnSet disj(Object elem) {
        DawnMap n = m.without(elem);
        return n == m ? this : new DawnSet(n);
    }

    @Override
    public boolean contains(Object o) {
        return m.containsKey(o);
    }

    @Override
    public int size() {
        return m.size();
    }

    @Override
    public Iterator<Object> iterator() {
        return m.keySet().iterator();
    }
}
