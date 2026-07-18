package dawn.rt;

import java.util.AbstractList;
import java.util.List;
import java.util.RandomAccess;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Dawn's {@code List}: immutable, indexable in O(1), and appendable in O(1)
 * amortized when a program builds a list by repeated concatenation.
 *
 * <p><b>Why this exists.</b> Lists used to be plain {@code ArrayList}s copied
 * whole on every {@code ++}, which makes the ordinary accumulation loop
 * ({@code acc = acc ++ [x]}) quadratic — measured at ~44x slower than the
 * builtin for 32k elements, and worse as it grows (docs/pure-ffi-design.md
 * section 13). That cost also blocked rewriting the collection builtins in Dawn,
 * since the natural recursive {@code map} accumulates exactly this way.
 *
 * <p><b>How.</b> A version is a window {@code a[0, size)} over a backing array
 * that neighbouring versions share. {@code used} counts the slots handed out
 * across all versions sharing {@code a}, so a version may extend in place
 * precisely when it ends where the shared region ends — the linear,
 * one-owner-at-a-time case that accumulation produces. Appending to an older
 * version instead copies, which is what preserves immutability: a published list
 * never changes, whatever its successors do.
 *
 * <p><b>Thread safety.</b> Dawn programs are concurrent (backend-dawn serves one
 * virtual thread per request), so two threads may append to the same list.
 * A slot range is therefore <i>claimed by CAS before it is written</i>: at most
 * one thread wins a given range, and the loser copies. Publication is safe
 * because the writes happen before this object's final fields are frozen, so any
 * thread reaching the elements through {@link #a} sees them (JLS 17.5).
 *
 * <p>Implementing {@link List} is deliberate: it is the wire type the whole
 * compiler and every Java interop signature already speak, so this
 * representation drops in without touching them, and a DawnList compares equal
 * to any other List with the same elements.
 */
public final class DawnList extends AbstractList<Object> implements RandomAccess {

    private static final int MIN_CAPACITY = 16;

    /** shared backing store; {@code a[0, size)} is this version and never mutates */
    private final Object[] a;
    /** slots handed out across every version sharing {@code a}; only ever grows */
    private final AtomicInteger used;
    private final int size;

    private DawnList(Object[] a, AtomicInteger used, int size) {
        this.a = a;
        this.used = used;
        this.size = size;
    }

    @Override
    public Object get(int i) {
        if (i < 0 || i >= size) {
            throw new IndexOutOfBoundsException("index " + i + " for length " + size);
        }
        return a[i];
    }

    @Override
    public int size() {
        return size;
    }

    /**
     * {@code xs ++ ys} — the {@code ++} operator on lists.
     *
     * <p>Takes the in-place path when {@code xs} is a DawnList ending exactly at
     * the shared watermark and the backing array has room; otherwise copies both
     * sides into a fresh array with slack, so the <i>next</i> append is cheap.
     * Either way the result is a new value and neither argument is observably
     * changed.
     */
    public static List<Object> concat(List<Object> xs, List<Object> ys) {
        int add = ys.size();
        if (add == 0) {
            return xs;
        }
        if (xs instanceof DawnList) {
            DawnList l = (DawnList) xs;
            if (l.size + add <= l.a.length && l.used.compareAndSet(l.size, l.size + add)) {
                // the range [size, size+add) is ours alone now; fill and freeze
                int i = l.size;
                for (Object y : ys) {
                    l.a[i++] = y;
                }
                return new DawnList(l.a, l.used, l.size + add);
            }
        }
        int n = xs.size();
        Object[] arr = new Object[Math.max(MIN_CAPACITY, (n + add) * 2)];
        int i = 0;
        for (Object x : xs) {
            arr[i++] = x;
        }
        for (Object y : ys) {
            arr[i++] = y;
        }
        return new DawnList(arr, new AtomicInteger(n + add), n + add);
    }
}
