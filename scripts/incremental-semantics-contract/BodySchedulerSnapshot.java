package contract;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;

/** Compare every scheduler product and Cx field, without generated Eq dictionaries. */
public final class BodySchedulerSnapshot {
    public static void main(String[] args) throws Exception {
        Class<?> reference = Class.forName("reference");
        Object samples = reference.getMethod("samples").invoke(null);
        var count = java.util.Arrays.stream(reference.getMethods())
                .filter(m -> m.getName().equals("sample_count")).findFirst().orElseThrow();
        var at = java.util.Arrays.stream(reference.getMethods())
                .filter(m -> m.getName().equals("sample_at")).findFirst().orElseThrow();
        long length = (Long) count.invoke(null, samples);
        if (length != 16) throw new AssertionError("Expected 16 scheduler pairs, got " + length);
        for (int i = 0; i < length; i++) {
            Object pair = at.invoke(null, samples, (long) i);
            Object old = pair.getClass().getField("old").get(pair);
            Object current = pair.getClass().getField("current").get(pair);
            for (Field field : old.getClass().getFields()) {
                if (Modifier.isStatic(field.getModifiers())) continue;
                Object a = field.get(old), b = field.get(current);
                boolean equal;
                if (field.getName().equals("cx")) {
                    equal = true;
                    for (Field member : a.getClass().getFields()) {
                        if (Modifier.isStatic(member.getModifiers())) continue;
                        Object x = member.get(a), y = member.get(b);
                        // Both branches receive the same capability. Anything else
                        // is data and must be compared, including new Cx fields.
                        if (member.getName().equals("jsig") ? x != y : !SemanticSnapshot.same(x, y)) {
                            System.out.println("DIFF: Cx." + member.getName());
                            equal = false;
                        }
                    }
                } else {
                    equal = SemanticSnapshot.same(a, b);
                }
                if (!equal) {
                    System.out.println("FAIL: frozen body scheduler case " + i + " field " + field.getName());
                    System.exit(1);
                }
            }
        }
        System.out.println("PASS: frozen body scheduler, 16 complete product/context pairs");
    }
}
