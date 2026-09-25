package contract;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.Arrays;

/** Include every returned checker field, typed product, comptime result and view. */
public final class BoundedReplayTrace {
    private static Method method(Class<?> owner, String name) {
        return Arrays.stream(owner.getMethods()).filter(m -> m.getName().equals(name)).findFirst().orElseThrow();
    }
    private static Object field(Object value, String name) throws Exception {
        return value.getClass().getField(name).get(value);
    }
    public static void main(String[] args) throws Exception {
        GenericTrace.main(new String[]{"--quiet"});
        Class<?> reference = Class.forName("dawn$pkg$selfhost.contract.reference");
        Object suite = method(reference, "bounded_cases").invoke(null);
        long bodies = (Long) method(reference, "bounded_body_count").invoke(null, suite);
        long programs = (Long) method(reference, "bounded_program_count").invoke(null, suite);
        if (bodies != 15 || programs != 12) throw new AssertionError("bounded replay full-product denominator");
        for (long i = 0; i < bodies; i++) {
            Object pair = method(reference, "bounded_body_at").invoke(null, suite, i);
            GenericTrace.equalBodies(field(pair, "cold"), field(pair, "actual"), "bounded replay " + i);
        }
        for (long i = 0; i < programs; i++) {
            Object pair = method(reference, "bounded_program_at").invoke(null, suite, i);
            Object cold = field(pair, "cold"), actual = field(pair, "actual");
            for (String name : new String[]{"diags", "decl_spans"}) {
                if (!SemanticSnapshot.same(field(cold, name), field(actual, name))) {
                    throw new AssertionError("bounded prepared Program." + name);
                }
            }
            long count = (Long) method(reference, "bounded_module_count").invoke(null, cold);
            if ((Long) method(reference, "bounded_module_count").invoke(null, actual) != count) {
                throw new AssertionError("bounded prepared module count");
            }
            for (long j = 0; j < count; j++) {
                Object a = method(reference, "bounded_module_at").invoke(null, cold, j);
                Object b = method(reference, "bounded_module_at").invoke(null, actual, j);
                for (Field f : a.getClass().getFields()) {
                    if (Modifier.isStatic(f.getModifiers())) continue;
                    if (f.getName().equals("cx")) FunctionEntryTrace.context(f.get(a), f.get(b));
                    else if (!SemanticSnapshot.same(f.get(a), f.get(b))) {
                        throw new AssertionError("bounded prepared CheckedMod." + f.getName());
                    }
                }
            }
        }
        System.out.println("PASS: bounded replay 15 full-body histories and 12 complete prepared Programs");
    }
}
