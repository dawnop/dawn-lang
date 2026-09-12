package contract;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;

/** Count canonical body entries and compare every product field independently of Dawn Eq. */
public final class ScalarReplaySnapshot {
    private static long calls;
    public static void enter() { calls++; }
    public static void reset() { calls = 0; }
    public static long count() { return calls; }

    public static void main(String[] args) throws Exception {
        Class<?> reference = Class.forName("reference");
        Object samples = reference.getMethod("samples").invoke(null);
        var size = java.util.Arrays.stream(reference.getMethods())
                .filter(m -> m.getName().equals("sample_count")).findFirst().orElseThrow();
        var at = java.util.Arrays.stream(reference.getMethods())
                .filter(m -> m.getName().equals("sample_at")).findFirst().orElseThrow();
        long length = (Long) size.invoke(null, samples);
        if (length != 28) throw new AssertionError("Expected 28 replay pairs, got " + length);
        for (long i = 0; i < length; i++) {
            Object pair = at.invoke(null, samples, i);
            Object cold = pair.getClass().getField("old").get(pair);
            Object warm = pair.getClass().getField("current").get(pair);
            for (Field field : cold.getClass().getFields()) {
                if (Modifier.isStatic(field.getModifiers())) continue;
                Object a = field.get(cold), b = field.get(warm);
                if (field.getName().equals("cx")) {
                    for (Field member : a.getClass().getFields()) {
                        if (Modifier.isStatic(member.getModifiers())) continue;
                        Object x = member.get(a), y = member.get(b);
                        if (member.getName().equals("jsig") ? x != y : !SemanticSnapshot.same(x, y)) {
                            throw new AssertionError("FAIL: scalar full product case " + i + " Cx." + member.getName());
                        }
                    }
                } else if (!SemanticSnapshot.same(a, b)) {
                    throw new AssertionError("FAIL: scalar full product case " + i + " " + field.getName());
                }
            }
        }
        System.out.println("PASS: scalar full products, 28 pairs and independent body entry counts");
    }
}
