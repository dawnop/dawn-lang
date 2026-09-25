package contract;

import java.lang.reflect.Array;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.Arrays;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.IdentityHashMap;

/** Full private trace and independent equality; no generated Show/Eq requirement. */
public final class GenericTrace {
    private static long calls;
    public static void enter() { calls++; }
    public static void reset() { calls = 0; }
    public static long count() { return calls; }

    private static Object field(Object value, String name) throws Exception {
        return value.getClass().getField(name).get(value);
    }

    private static Method method(Class<?> owner, String name) {
        return Arrays.stream(owner.getMethods()).filter(m -> m.getName().equals(name))
                .findFirst().orElseThrow();
    }

    static void equalBodies(Object cold, Object actual, String label) throws Exception {
        for (Field member : cold.getClass().getFields()) {
            if (Modifier.isStatic(member.getModifiers())) continue;
            Object a = member.get(cold), b = member.get(actual);
            if (member.getName().equals("cx")) {
                for (Field entry : a.getClass().getFields()) {
                    if (Modifier.isStatic(entry.getModifiers())) continue;
                    Object x = entry.get(a), y = entry.get(b);
                    boolean equal = entry.getName().equals("jsig") ? x == y : SemanticSnapshot.same(x, y);
                    if (!equal) throw new AssertionError(label + " Cx." + entry.getName());
                }
            } else if (!SemanticSnapshot.same(a, b)) {
                throw new AssertionError(label + " " + member.getName());
            }
        }
    }

    private static String dump(Object value, IdentityHashMap<Object, Boolean> path) throws Exception {
        if (value == null) return "null";
        if (value instanceof String text) return "\"" + text.replace("\\", "\\\\")
                .replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r") + "\"";
        if (value instanceof Number || value instanceof Boolean) return value.toString();
        if (path.put(value, true) != null) throw new AssertionError("Unexpected product cycle");
        StringBuilder out = new StringBuilder();
        if (value.getClass().isArray()) {
            out.append('[');
            for (int i = 0; i < Array.getLength(value); i++) {
                if (i != 0) out.append(',');
                out.append(dump(Array.get(value, i), path));
            }
            out.append(']');
        } else {
            out.append(value.getClass().getName()).append('{');
            var fields = new ArrayList<Field>();
            for (Class<?> type = value.getClass(); type != Object.class; type = type.getSuperclass()) {
                fields.addAll(Arrays.asList(type.getDeclaredFields()));
            }
            fields.sort(Comparator.comparing(Field::getName));
            boolean first = true;
            for (Field f : fields) {
                if (Modifier.isStatic(f.getModifiers())) continue;
                f.setAccessible(true);
                if (!first) out.append(',');
                first = false;
                out.append(f.getName()).append('=').append(dump(f.get(value), path));
            }
            out.append('}');
        }
        path.remove(value);
        return out.toString();
    }

    public static void main(String[] args) throws Exception {
        boolean quiet = Arrays.asList(args).contains("--quiet");
        Class<?> reference = Class.forName("dawn$pkg$selfhost.contract.reference");
        Object samples = method(reference, "samples").invoke(null);
        long count = (Long) method(reference, "sample_count").invoke(null, samples);
        if (count != 3) throw new AssertionError("Expected three original bounded-generic classes");
        long pairs = 0, products = 0;
        for (long i = 0; i < count; i++) {
            Object sample = method(reference, "sample_at").invoke(null, samples, i);
            String label = (String) field(sample, "label");
            long n = (Long) method(reference, "pair_count").invoke(null, sample);
            if (n != 4) throw new AssertionError("Expected recording, replay, and two renewal pairs");
            for (long j = 0; j < n; j++) {
                Object pair = method(reference, "pair_at").invoke(null, sample, j);
                equalBodies(field(pair, "cold"), field(pair, "actual"), label + "/" + j);
                pairs++;
            }
            long p = (Long) method(reference, "product_count").invoke(null, sample);
            for (long j = 0; j < p; j++) {
                Object product = method(reference, "product_at").invoke(null, sample, j);
                if (!quiet) System.out.println("TRACE " + label + "/" + j + " " + dump(product, new IdentityHashMap<>()));
                products++;
            }
            if (!quiet) System.out.println("PASS: generic replay " + label + ", " + n + " full-body/context pairs");
        }
        if (pairs != 12 || products != 4) throw new AssertionError("Trace denominator changed");
        if (!quiet) System.out.println("PASS: generic trace 4 bounded products, 12 full-body/context pairs, actual cold entry counts");
    }
}
