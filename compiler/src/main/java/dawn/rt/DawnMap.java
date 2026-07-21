package dawn.rt;

import java.util.AbstractMap;
import java.util.ArrayList;
import java.util.Set;

/**
 * Dawn's {@code Map}: immutable, with O(log32 n) lookup and insert.
 *
 * <p><b>Why this exists.</b> Maps used to be a {@code LinkedHashMap} copied
 * whole on every {@code map_insert}, so a map grown one key at a time is
 * quadratic — measured at ~48s for 100k inserts into one growing map, versus
 * milliseconds for the same count spread across small discarded scope maps
 * (docs/selfhost-gaps.md section 2). That single-growing-map shape is exactly
 * what a self-hosted compiler builds (one typed-AST or symbol table per pass),
 * so the copy-on-write map blocked self-hosting.
 *
 * <p><b>How.</b> A hash array mapped trie (HAMT): each node branches 32 ways on
 * a 5-bit slice of the key's hash, so {@code assoc} copies only the path from
 * the root to the changed leaf (about {@code log32 n} small nodes) and shares
 * everything else with the source map. A published map never changes.
 *
 * <p><b>Insertion order.</b> spec section 2.2 requires iteration in insertion
 * order and that re-inserting an existing key keeps its original position. Each
 * live key carries a monotonic sequence number ({@code seq}); iteration sorts by
 * it. {@code assoc} on a present key reuses that key's {@code seq}, so its
 * position is preserved; a genuinely new key gets {@code nextSeq}.
 *
 * <p><b>Thread safety.</b> Every node is immutable and reachable only through
 * final fields, so publication is safe (JLS 17.5) without any synchronisation —
 * unlike {@link DawnList}, this structure never writes into shared storage.
 *
 * <p>Extending {@link AbstractMap} is deliberate: {@code java.util.Map} is the
 * wire type the whole compiler and every interop signature already speak, so
 * this drops in without touching them, and {@code AbstractMap} supplies an
 * order-independent {@code equals}/{@code hashCode} (spec section 2.2: equality
 * ignores order) plus {@code keySet}/{@code values} that follow {@link
 * #entrySet}'s order.
 */
public final class DawnMap extends AbstractMap<Object, Object> {

    public static final DawnMap EMPTY = new DawnMap(null, 0, 0);

    /** trie root; null only for the empty map */
    private final Node root;
    private final int size;
    /** sequence number handed to the next genuinely-new key */
    private final int nextSeq;

    private DawnMap(Node root, int size, int nextSeq) {
        this.root = root;
        this.size = size;
        this.nextSeq = nextSeq;
    }

    // ---- persistent operations (called from the generated Maps class) ----

    /** Return a map with {@code key} bound to {@code value}; O(log32 n). */
    public DawnMap assoc(Object key, Object value) {
        int h = hash(key);
        Leaf existing = root == null ? null : root.find(h, key, 0);
        if (existing != null) {
            if (eq(existing.value, value)) return this; // no change: keep sharing
            return new DawnMap(root.put(h, key, value, existing.seq, 0), size, nextSeq);
        }
        Node r = root == null ? new Leaf(h, key, value, nextSeq)
                              : root.put(h, key, value, nextSeq, 0);
        return new DawnMap(r, size + 1, nextSeq + 1);
    }

    /** Return a map without {@code key}; O(log32 n). */
    public DawnMap without(Object key) {
        if (root == null) return this;
        int h = hash(key);
        if (root.find(h, key, 0) == null) return this;
        Node r = root.remove(h, key, 0);
        return new DawnMap(r, size - 1, nextSeq);
    }

    // ---- read side (java.util.Map) ----

    @Override
    public Object get(Object key) {
        if (root == null) return null;
        Leaf e = root.find(hash(key), key, 0);
        return e == null ? null : e.value;
    }

    @Override
    public boolean containsKey(Object key) {
        return root != null && root.find(hash(key), key, 0) != null;
    }

    @Override
    public int size() {
        return size;
    }

    @Override
    public Set<Entry<Object, Object>> entrySet() {
        ArrayList<Leaf> leaves = new ArrayList<>(size);
        if (root != null) root.collect(leaves);
        // insertion order: seq is monotonic and unique among live keys
        leaves.sort((a, b) -> Integer.compare(a.seq, b.seq));
        return new java.util.AbstractSet<Entry<Object, Object>>() {
            @Override public int size() { return leaves.size(); }
            @Override public java.util.Iterator<Entry<Object, Object>> iterator() {
                java.util.Iterator<Leaf> it = leaves.iterator();
                return new java.util.Iterator<Entry<Object, Object>>() {
                    @Override public boolean hasNext() { return it.hasNext(); }
                    @Override public Entry<Object, Object> next() { return it.next(); }
                };
            }
        };
    }

    // ---- hashing: null-safe, spreads java hashCodes across the 5-bit slices ----

    private static int hash(Object k) {
        int h = k == null ? 0 : k.hashCode();
        // mix high bits down so slices are not dominated by low-entropy hashCodes
        return h ^ (h >>> 16);
    }

    private static boolean eq(Object a, Object b) {
        return a == null ? b == null : a.equals(b);
    }

    // ======================= trie nodes =======================

    private abstract static class Node {
        /** the leaf for {@code key}, or null */
        abstract Leaf find(int h, Object key, int shift);
        /** a node with {@code key -> value} at the given seq set (overwriting any prior) */
        abstract Node put(int h, Object key, Object value, int seq, int shift);
        /** a node without {@code key}; never returns an empty node (caller drops empties) */
        abstract Node remove(int h, Object key, int shift);
        abstract void collect(ArrayList<Leaf> out);
    }

    /** A single key/value with its insertion sequence; also serves as its own Map.Entry. */
    private static final class Leaf extends Node implements Entry<Object, Object> {
        final int hash;
        final Object key;
        final Object value;
        final int seq;

        Leaf(int hash, Object key, Object value, int seq) {
            this.hash = hash;
            this.key = key;
            this.value = value;
            this.seq = seq;
        }

        @Override Leaf find(int h, Object k, int shift) {
            return h == hash && eq(key, k) ? this : null;
        }

        @Override Node put(int h, Object k, Object value, int seq, int shift) {
            if (h == hash && eq(key, k)) return new Leaf(hash, key, value, seq);
            Leaf other = new Leaf(h, k, value, seq);
            return h == hash ? new Collision(h, new Leaf[]{this, other})
                             : merge(this, other, shift);
        }

        @Override Node remove(int h, Object k, int shift) {
            return (h == hash && eq(key, k)) ? null : this;
        }

        @Override void collect(ArrayList<Leaf> out) { out.add(this); }

        @Override public Object getKey() { return key; }
        @Override public Object getValue() { return value; }
        @Override public Object setValue(Object v) { throw new UnsupportedOperationException(); }

        // Map.Entry contract: AbstractMap sums these, so it must be the Entry hash
        // (not identity) for equal maps to share a hashCode regardless of order.
        @Override public int hashCode() {
            return (key == null ? 0 : key.hashCode()) ^ (value == null ? 0 : value.hashCode());
        }

        @Override public boolean equals(Object o) {
            if (!(o instanceof Entry)) return false;
            Entry<?, ?> e = (Entry<?, ?>) o;
            return eq(key, e.getKey()) && eq(value, e.getValue());
        }
    }

    /** Two or more keys with the same 32-bit hash but differing by equals. */
    private static final class Collision extends Node {
        final int hash;
        final Leaf[] leaves;

        Collision(int hash, Leaf[] leaves) {
            this.hash = hash;
            this.leaves = leaves;
        }

        @Override Leaf find(int h, Object k, int shift) {
            if (h != hash) return null;
            for (Leaf l : leaves) if (eq(l.key, k)) return l;
            return null;
        }

        @Override Node put(int h, Object k, Object value, int seq, int shift) {
            if (h != hash) return merge(this, new Leaf(h, k, value, seq), shift);
            for (int i = 0; i < leaves.length; i++) {
                if (eq(leaves[i].key, k)) {
                    Leaf[] copy = leaves.clone();
                    copy[i] = new Leaf(h, k, value, seq);
                    return new Collision(hash, copy);
                }
            }
            Leaf[] grown = new Leaf[leaves.length + 1];
            System.arraycopy(leaves, 0, grown, 0, leaves.length);
            grown[leaves.length] = new Leaf(h, k, value, seq);
            return new Collision(hash, grown);
        }

        @Override Node remove(int h, Object k, int shift) {
            if (h != hash) return this;
            int idx = -1;
            for (int i = 0; i < leaves.length; i++) if (eq(leaves[i].key, k)) { idx = i; break; }
            if (idx < 0) return this;
            if (leaves.length == 2) return leaves[idx == 0 ? 1 : 0]; // collapse back to a Leaf
            Leaf[] shrunk = new Leaf[leaves.length - 1];
            System.arraycopy(leaves, 0, shrunk, 0, idx);
            System.arraycopy(leaves, idx + 1, shrunk, idx, leaves.length - idx - 1);
            return new Collision(hash, shrunk);
        }

        @Override void collect(ArrayList<Leaf> out) {
            for (Leaf l : leaves) out.add(l);
        }
    }

    /** A branching node: {@code bitmap} marks which of 32 slots are present. */
    private static final class Bitmap extends Node {
        final int bitmap;
        final Node[] slots; // one entry per set bit, in ascending bit order

        Bitmap(int bitmap, Node[] slots) {
            this.bitmap = bitmap;
            this.slots = slots;
        }

        private static int index(int bitmap, int bit) {
            return Integer.bitCount(bitmap & (bit - 1));
        }

        @Override Leaf find(int h, Object key, int shift) {
            int bit = 1 << ((h >>> shift) & 31);
            if ((bitmap & bit) == 0) return null;
            return slots[index(bitmap, bit)].find(h, key, shift + 5);
        }

        @Override Node put(int h, Object key, Object value, int seq, int shift) {
            int bit = 1 << ((h >>> shift) & 31);
            int i = index(bitmap, bit);
            if ((bitmap & bit) != 0) {
                Node child = slots[i].put(h, key, value, seq, shift + 5);
                Node[] copy = slots.clone();
                copy[i] = child;
                return new Bitmap(bitmap, copy);
            }
            Node[] grown = new Node[slots.length + 1];
            System.arraycopy(slots, 0, grown, 0, i);
            grown[i] = new Leaf(h, key, value, seq);
            System.arraycopy(slots, i, grown, i + 1, slots.length - i);
            return new Bitmap(bitmap | bit, grown);
        }

        @Override Node remove(int h, Object key, int shift) {
            int bit = 1 << ((h >>> shift) & 31);
            if ((bitmap & bit) == 0) return this;
            int i = index(bitmap, bit);
            Node child = slots[i].remove(h, key, shift + 5);
            if (child != null) {
                Node[] copy = slots.clone();
                copy[i] = child;
                return new Bitmap(bitmap, copy);
            }
            // child emptied out: drop the slot
            if (slots.length == 1) return null;
            Node[] shrunk = new Node[slots.length - 1];
            System.arraycopy(slots, 0, shrunk, 0, i);
            System.arraycopy(slots, i + 1, shrunk, i, slots.length - i - 1);
            Bitmap reduced = new Bitmap(bitmap & ~bit, shrunk);
            // collapse a node that now holds a single Leaf back into that Leaf
            if (shrunk.length == 1 && shrunk[0] instanceof Leaf) return shrunk[0];
            return reduced;
        }

        @Override void collect(ArrayList<Leaf> out) {
            for (Node n : slots) n.collect(out);
        }
    }

    /** Build the smallest node holding two leaves whose hashes differ. */
    private static Node merge(Node a, Leaf b, int shift) {
        int ha = leafHash(a);
        int hb = b.hash;
        int fa = (ha >>> shift) & 31;
        int fb = (hb >>> shift) & 31;
        if (fa == fb) {
            // still colliding at this level: recurse one level deeper
            Node deeper = merge(a, b, shift + 5);
            return new Bitmap(1 << fa, new Node[]{deeper});
        }
        int bitmap = (1 << fa) | (1 << fb);
        Node[] slots = fa < fb ? new Node[]{a, b} : new Node[]{b, a};
        return new Bitmap(bitmap, slots);
    }

    private static int leafHash(Node n) {
        return n instanceof Leaf ? ((Leaf) n).hash : ((Collision) n).hash;
    }
}
