package contract;

import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Arrays;

/** Observe the real body's state footprint without a generated Cx Eq dictionary. */
public final class BodyProbe {
    public static void main(String[] args) throws Exception {
        Class<?> probe = Class.forName("bodyprobe");
        Object samples = probe.getMethod("samples").invoke(null);
        var count = Arrays.stream(probe.getMethods()).filter(m -> m.getName().equals("sample_count"))
                .findFirst().orElseThrow();
        var at = Arrays.stream(probe.getMethods()).filter(m -> m.getName().equals("sample_at"))
                .findFirst().orElseThrow();
        long length = (Long) count.invoke(null, samples);
        if (length != 11) throw new AssertionError("Expected eleven body trials");
        for (long i = 0; i < length; i++) {
            Object trial = at.invoke(null, samples, i);
            Class<?> t = trial.getClass();
            String name = (String) t.getField("name").get(trial);
            Object before = t.getField("before").get(trial);
            Object after = t.getField("after").get(trial);
            Object shifted = t.getField("shifted").get(trial);
            if (!SemanticSnapshot.same(t.getField("body").get(trial), t.getField("module_body").get(trial)))
                throw new AssertionError(name + ": isolated header sequence differs from check_module");
            if (!SemanticSnapshot.same(t.getField("relocated").get(trial), t.getField("shifted_body").get(trial)))
                throw new AssertionError(name + ": relocated body differs from shifted cold check");
            var changed = new ArrayList<String>();
            for (var field : before.getClass().getFields()) {
                if (Modifier.isStatic(field.getModifiers()) || field.getName().equals("jsig")) continue;
                if (!SemanticSnapshot.same(field.get(before), field.get(after))) changed.add(field.getName());
            }
            changed.sort(String::compareTo);
            var next = before.getClass().getField("next_id");
            long allocations = next.getLong(after) - next.getLong(before);
            if (next.getLong(shifted) - next.getLong(after) != 1000)
                throw new AssertionError(name + ": allocation count depends on starting ID");
            System.out.println(name + "\t" + allocations + "\t" + String.join(",", changed));
        }
        Object edits = probe.getMethod("edit_samples").invoke(null);
        var editCount = Arrays.stream(probe.getMethods()).filter(m -> m.getName().equals("edit_count"))
                .findFirst().orElseThrow();
        var editAt = Arrays.stream(probe.getMethods()).filter(m -> m.getName().equals("edit_at"))
                .findFirst().orElseThrow();
        long editedLength = (Long) editCount.invoke(null, edits);
        if (editedLength != 10) throw new AssertionError("Expected ten reused body products");
        for (long i = 0; i < editedLength; i++) {
            Object edit = editAt.invoke(null, edits, i);
            Class<?> e = edit.getClass();
            if (!SemanticSnapshot.same(e.getField("relocated").get(edit), e.getField("cold").get(edit)))
                throw new AssertionError("edited source: relocated body differs from shifted cold check (" + i + ")");
            if (!SemanticSnapshot.same(e.getField("replayed_cx").get(edit), e.getField("cold_cx").get(edit)))
                throw new AssertionError("edited source: replayed Cx differs from cold body boundary (" + i + ")");
        }
        System.out.println("edited-source\t10\tstable keys, TFun and full body-boundary Cx agree with cold products");
    }
}
