package contract;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.IdentityHashMap;

/**
 * Independent test oracle: do not rely on the compiler's generated Eq dictionaries.
 * Dawn Array backing capacity and the append watermark are not logical contents.
 * Everything else is compared field-for-field; unknown host capabilities fail closed.
 */
public final class SemanticSnapshot {
    public static void main(String[] args) throws Exception {
        selfTest();
        String owner = "cold transition agrees with the frozen loop on full semantic products";
        Class<?> reference = Class.forName("reference");
        Object samples = reference.getMethod("samples").invoke(null);
        var count = java.util.Arrays.stream(reference.getMethods())
                .filter(m -> m.getName().equals("sample_count")).findFirst().orElseThrow();
        var at = java.util.Arrays.stream(reference.getMethods())
                .filter(m -> m.getName().equals("sample_at")).findFirst().orElseThrow();
        long length = (Long) count.invoke(null, samples);
        if (length != 13) throw new AssertionError("Expected 13 full-product pairs, got " + length);
        for (int i = 0; i < length; i++) {
            Object pair = at.invoke(null, samples, (long) i);
            Object a = pair.getClass().getField("old").get(pair);
            Object b = pair.getClass().getField("current").get(pair);
            if (!same(a, b)) {
                System.out.println("FAIL  reference :: " + owner + " (case " + i + ")");
                System.exit(1);
            }
        }
        System.out.println("PASS  reference :: " + owner);
    }

    private static void selfTest() throws ReflectiveOperationException {
        if (!same(new Object[]{new long[]{1, 2}, "x", null},
                  new Object[]{new long[]{1, 2}, "x", null})
                || same(new Object[]{new long[]{1, 2}}, new Object[]{new long[]{1, 3}})
                || same(new long[]{1}, new long[]{1, 2})
                || same(null, "x") || same(0.0, -0.0)
                || same(Double.longBitsToDouble(0x7ff8000000000001L),
                        Double.longBitsToDouble(0x7ff8000000000002L))) {
            throw new AssertionError("Structural comparator control failed");
        }
        Object[] a = new Object[2];
        Object[] b = new Object[2];
        a[0] = a;
        b[0] = b;
        a[1] = 1L;
        b[1] = 1L;
        if (!same(a, b)) throw new AssertionError("Cycle equality control failed");
        b[1] = 2L;
        if (same(a, b)) throw new AssertionError("Cycle inequality control failed");
        try {
            same(new Object(), new Object());
            throw new AssertionError("Unknown host object was accepted");
        } catch (IllegalArgumentException expected) {
            // Unknown capabilities cannot silently compare equal.
        }
    }

    public static boolean same(Object a, Object b) throws ReflectiveOperationException {
        return same(a, b, new IdentityHashMap<>());
    }

    private static boolean same(Object a, Object b,
            IdentityHashMap<Object, IdentityHashMap<Object, Boolean>> seen)
            throws ReflectiveOperationException {
        if (a == null || b == null) return a == b;
        Class<?> type = a.getClass();
        if (type != b.getClass()) return false;
        if (a instanceof String || a instanceof Long || a instanceof Integer
                || a instanceof Boolean || a instanceof Byte || a instanceof Short
                || a instanceof Character) return a.equals(b);
        if (a instanceof Double x) {
            return Double.doubleToRawLongBits(x) == Double.doubleToRawLongBits((Double) b);
        }
        if (a instanceof Float x) {
            return Float.floatToRawIntBits(x) == Float.floatToRawIntBits((Float) b);
        }
        if (!type.isArray() && (!(type.getName().startsWith("dawn.")
                || type.getName().startsWith("dawn$")
                || type.getName().startsWith("std.")
                || type.getName().startsWith("Option$")
                || type.getName().startsWith("Result$"))
                || type.isSynthetic())) {
            throw new IllegalArgumentException("Unsupported semantic product: " + type.getName());
        }
        var partners = seen.computeIfAbsent(a, ignored -> new IdentityHashMap<>());
        if (partners.put(b, Boolean.TRUE) != null) return true;
        if (type.getName().equals("dawn.rt.Array")) {
            Field length = type.getDeclaredField("len");
            Field contents = type.getDeclaredField("a");
            length.setAccessible(true);
            contents.setAccessible(true);
            int n = length.getInt(a);
            if (n != length.getInt(b)) return false;
            Object[] left = (Object[]) contents.get(a);
            Object[] right = (Object[]) contents.get(b);
            for (int i = 0; i < n; i++) {
                if (!same(left[i], right[i], seen)) return false;
            }
            return true;
        }
        if (type.isArray()) {
            int n = java.lang.reflect.Array.getLength(a);
            if (n != java.lang.reflect.Array.getLength(b)) return false;
            for (int i = 0; i < n; i++) {
                if (!same(java.lang.reflect.Array.get(a, i),
                        java.lang.reflect.Array.get(b, i), seen)) return false;
            }
            return true;
        }
        for (Class<?> parent = type; parent != Object.class; parent = parent.getSuperclass()) {
            for (Field field : parent.getDeclaredFields()) {
                if (Modifier.isStatic(field.getModifiers())) continue;
                // Cx carries an oracle capability, not semantic data. Both paths
                // receive the same refusing oracle; every other field is compared.
                if (field.getName().equals("jsig")
                        && type.getName().endsWith("$Cx")) continue;
                field.setAccessible(true);
                if (!same(field.get(a), field.get(b), seen)) return false;
            }
        }
        return true;
    }
}
