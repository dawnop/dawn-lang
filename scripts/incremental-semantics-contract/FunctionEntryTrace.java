package contract;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.lang.reflect.Method;
import java.util.Arrays;

/** Isolate prologue extraction against a frozen body loop, including all logs. */
public final class FunctionEntryTrace {

    public static void context(Object expected, Object actual) throws Exception {
        for (Field field : expected.getClass().getFields()) {
            if (Modifier.isStatic(field.getModifiers())) continue;
            Object a = field.get(expected), b = field.get(actual);
            if (field.getName().equals("jsig") ? a != b : !SemanticSnapshot.same(a, b)) {
                throw new AssertionError("function entry frozen Cx." + field.getName());
            }
        }
    }

    private static Object field(Object value, String name) throws Exception {
        return value.getClass().getField(name).get(value);
    }

    private static Method method(Class<?> owner, String name) {
        return Arrays.stream(owner.getMethods()).filter(m -> m.getName().equals(name)).findFirst().orElseThrow();
    }

    public static void main(String[] args) throws Exception {
        GenericTrace.main(args);
        Class<?> reference = Class.forName("dawn$pkg$selfhost.contract.reference");
        Object suite = method(reference, "entry_cases").invoke(null);
        long comparisons = (Long) method(reference, "entry_pair_count").invoke(null, suite);
        if (comparisons != 32) throw new AssertionError("function entry baseline expected 32 pairs, got " + comparisons);
        for (long i = 0; i < comparisons; i++) {
            Object pair = method(reference, "entry_pair_at").invoke(null, suite, i);
            context(field(pair, "expected"), field(pair, "actual"));
            context(field(pair, "detached"), field(pair, "repeated"));
            if (!SemanticSnapshot.same(field(pair, "expected_tree"), field(pair, "tree"))) {
                throw new AssertionError("function entry frozen typed tree " + i);
            }
        }
        long hits = (Long) method(reference, "entry_hit_count").invoke(null, suite);
        if (hits != 2) throw new AssertionError("function entry needs two actual replay histories");
        for (long i = 0; i < hits; i++) {
            Object pair = method(reference, "entry_hit_at").invoke(null, suite, i);
            GenericTrace.equalBodies(field(pair, "cold"), field(pair, "actual"), "detached proof hit " + i);
        }
        System.out.println("PASS: function entry " + comparisons + " complete frozen Cx/tree comparisons, "
                + "2 detached candidate proof histories with real replay hits");
    }
}
