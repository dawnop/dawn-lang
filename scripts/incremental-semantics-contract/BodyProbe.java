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
        long expected = args.length == 0 ? 11 : Long.parseLong(args[0]);
        if (length != expected) throw new AssertionError("Unexpected body trial count: " + length);
        for (long i = 0; i < length; i++) {
            Object trial = at.invoke(null, samples, i);
            Class<?> t = trial.getClass();
            String name = (String) t.getField("name").get(trial);
            Object before = t.getField("before").get(trial);
            Object after = t.getField("after").get(trial);
            if (expected == 23 && !SemanticSnapshot.same(t.getField("assembled").get(trial), after)) {
                Object assembled = t.getField("assembled").get(trial);
                var differences = new ArrayList<String>();
                for (var field : after.getClass().getFields()) {
                    if (Modifier.isStatic(field.getModifiers()) || field.getName().equals("jsig")) continue;
                    if (!SemanticSnapshot.same(field.get(assembled), field.get(after))) differences.add(field.getName());
                }
                throw new AssertionError(name + ": captured body product differs from complete cold state: " + differences);
            }
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
        if (expected == 23)
            System.out.println("captured-state\t" + length + "\tproduction body products assemble complete cold Cx");
        Object edits = probe.getMethod("edit_samples").invoke(null);
        var editCount = Arrays.stream(probe.getMethods()).filter(m -> m.getName().equals("edit_count"))
                .findFirst().orElseThrow();
        var editAt = Arrays.stream(probe.getMethods()).filter(m -> m.getName().equals("edit_at"))
                .findFirst().orElseThrow();
        long editedLength = (Long) editCount.invoke(null, edits);
        if (editedLength != expected - 1) throw new AssertionError("Unexpected reused body count: " + editedLength);
        for (long i = 0; i < editedLength; i++) {
            Object edit = editAt.invoke(null, edits, i);
            Class<?> e = edit.getClass();
            if (!SemanticSnapshot.same(e.getField("relocated").get(edit), e.getField("cold").get(edit)))
                throw new AssertionError("edited source: relocated body differs from shifted cold check (" + i + ")");
            if (!SemanticSnapshot.same(e.getField("replayed_cx").get(edit), e.getField("cold_cx").get(edit)))
                throw new AssertionError("edited source: replayed Cx differs from cold body boundary (" + i + ")");
        }
        System.out.println("edited-source\t" + editedLength + "\tstable keys, TFun and full body-boundary Cx agree with cold products");
        if (expected == 23) {
            Object header = probe.getMethod("header_sample").invoke(null);
            Class<?> h = header.getClass();
            if (!SemanticSnapshot.same(h.getField("relocated").get(header), h.getField("cold").get(header)))
                throw new AssertionError("reordered header: relocated body differs from cold check");
            if (!SemanticSnapshot.same(h.getField("replayed_state").get(header), h.getField("cold_state").get(header))) {
                Object replayed = h.getField("replayed_state").get(header);
                Object checked = h.getField("cold_state").get(header);
                var fields = new ArrayList<String>();
                for (var field : replayed.getClass().getFields()) {
                    if (Modifier.isStatic(field.getModifiers()) || field.getName().equals("jsig")) continue;
                    if (!SemanticSnapshot.same(field.get(replayed), field.get(checked))) fields.add(field.getName());
                }
                throw new AssertionError("reordered header: replayed Cx differs from cold body boundary: " + fields);
            }
            System.out.println("reordered-header\t1\treversed effect declarations and evidence slots agree with cold");
            Object inferred = probe.getMethod("inferred_samples").invoke(null);
            var stateCount = Arrays.stream(probe.getMethods()).filter(m -> m.getName().equals("state_count")).findFirst().orElseThrow();
            var stateAt = Arrays.stream(probe.getMethods()).filter(m -> m.getName().equals("state_at")).findFirst().orElseThrow();
            long inferredLength = (Long) stateCount.invoke(null, inferred);
            if (inferredLength != 6) throw new AssertionError("Unexpected inferred state trial count");
            for (long i = 0; i < inferredLength; i++) {
                Object trial = stateAt.invoke(null, inferred, i);
                Class<?> t = trial.getClass();
                if (!SemanticSnapshot.same(t.getField("replayed").get(trial), t.getField("cold").get(trial)))
                    throw new AssertionError("inferred state: replayed Cx differs from cold body boundary (" + i + ")");
                if (!SemanticSnapshot.same(t.getField("relocated").get(trial), t.getField("cold_body").get(trial))
                        || !SemanticSnapshot.same(t.getField("cold_body").get(trial), t.getField("module_body").get(trial)))
                    throw new AssertionError("inferred state: body differs from cold module (" + i + ")");
            }
            System.out.println("inferred-state\t6\tsealed scalar and generic closure signatures replay with allocation provenance");
            Object tests = probe.getMethod("test_samples").invoke(null);
            if ((Long) stateCount.invoke(null, tests) != 1) throw new AssertionError("Unexpected test state trial count");
            Object test = stateAt.invoke(null, tests, 0L);
            Class<?> tt = test.getClass();
            if (!SemanticSnapshot.same(tt.getField("replayed").get(test), tt.getField("cold").get(test)))
                throw new AssertionError("test state: replayed Cx differs from cold body boundary");
            if (!SemanticSnapshot.same(tt.getField("relocated").get(test), tt.getField("cold_body").get(test))
                    || !SemanticSnapshot.same(tt.getField("cold_body").get(test), tt.getField("module_body").get(test)))
                throw new AssertionError("test state: body differs from cold module");
            System.out.println("test-state\t1\tassertion source and test frame agree with cold module products");
            Object defaults = probe.getMethod("default_samples").invoke(null);
            if ((Long) stateCount.invoke(null, defaults) != 6) throw new AssertionError("Unexpected default trial count");
            for (long i = 0; i < 6; i++) {
                Object def = stateAt.invoke(null, defaults, i);
                Class<?> dt = def.getClass();
                if (!SemanticSnapshot.same(dt.getField("replayed").get(def), dt.getField("cold").get(def)))
                    throw new AssertionError("default state: replayed Cx differs from cold body boundary (" + i + ")");
                if (!SemanticSnapshot.same(dt.getField("relocated").get(def), dt.getField("cold_body").get(def))
                        || !SemanticSnapshot.same(dt.getField("cold_body").get(def), dt.getField("module_body").get(def)))
                    throw new AssertionError("default state: body differs from cold module (" + i + ")");
            }
            System.out.println("default-state\t6\tdefaults, dictionaries and moved error diagnostics replay before explicit and inferred bodies");
            Object imports = probe.getMethod("import_samples").invoke(null);
            if ((Long) stateCount.invoke(null, imports) != 2) throw new AssertionError("Unexpected import trial count");
            for (long i = 0; i < 2; i++) {
                Object imported = stateAt.invoke(null, imports, i);
                Class<?> it = imported.getClass();
                if (!SemanticSnapshot.same(it.getField("replayed").get(imported), it.getField("cold").get(imported)))
                    throw new AssertionError("import state: replayed Cx differs from cold body boundary");
                if (!SemanticSnapshot.same(it.getField("relocated").get(imported), it.getField("cold_body").get(imported))
                        || !SemanticSnapshot.same(it.getField("cold_body").get(imported), it.getField("module_body").get(imported)))
                    throw new AssertionError("import state: body differs from cold module");
            }
            System.out.println("import-state\t2\tprovider provenance survives selective and qualified imports");
            checkModuleAssembly(probe);
            checkReadObservation(probe);
            Object metadata = probe.getMethod("metadata_sample").invoke(null);
            Class<?> mt = metadata.getClass();
            if (!SemanticSnapshot.same(mt.getField("projected").get(metadata), mt.getField("cold").get(metadata)))
                throw new AssertionError("header metadata: projected exports differ from cold headers");
            System.out.println("header-metadata\t1\tcomplete exported metadata agrees after ID and source movement");
            if (!SemanticSnapshot.same(mt.getField("assembled").get(metadata), mt.getField("header_state").get(metadata)))
                throw new AssertionError("header state: assembled context differs from cold headers");
            System.out.println("header-state\t1\tcomplete same-revision header context agrees after assembly");
            if (!SemanticSnapshot.same(mt.getField("moved_state").get(metadata), mt.getField("next_state").get(metadata)))
                throw new AssertionError("header state: projected context differs from cold headers");
            System.out.println("header-state-projection\t1\tcomplete header context agrees after ID and source movement");
        }
    }

    private static void checkReadObservation(Class<?> probe) throws Exception {
        Object trials = probe.getMethod("read_samples").invoke(null);
        var count = Arrays.stream(probe.getMethods()).filter(m -> m.getName().equals("module_count")).findFirst().orElseThrow();
        var at = Arrays.stream(probe.getMethods()).filter(m -> m.getName().equals("module_at")).findFirst().orElseThrow();
        if ((Long) count.invoke(null, trials) != 56) throw new AssertionError("Unexpected function read trial count");
        for (long i = 0; i < 56; i++) {
            Object trial = at.invoke(null, trials, i);
            Class<?> t = trial.getClass();
            if (!SemanticSnapshot.same(t.getField("replayed_cx").get(trial), t.getField("cold_cx").get(trial)))
                throw new AssertionError("function reads: observed Cx differs from cold module state (" + i + ")");
            if (!SemanticSnapshot.same(t.getField("replayed").get(trial), t.getField("cold").get(trial)))
                throw new AssertionError("function reads: observed module differs from cold module (" + i + ")");
        }
        System.out.println("function-reads\t56\tobservation preserves complete cold Cx and module products");
    }

    private static void checkModuleAssembly(Class<?> probe) throws Exception {
        Object modules = probe.getMethod("module_samples").invoke(null);
        var moduleCount = Arrays.stream(probe.getMethods()).filter(m -> m.getName().equals("module_count")).findFirst().orElseThrow();
        var moduleAt = Arrays.stream(probe.getMethods()).filter(m -> m.getName().equals("module_at")).findFirst().orElseThrow();
        if ((Long) moduleCount.invoke(null, modules) != 10) throw new AssertionError("Unexpected module assembly trial count");
        for (long i = 0; i < 10; i++) {
            Object trial = moduleAt.invoke(null, modules, i);
            Class<?> t = trial.getClass();
            if (!SemanticSnapshot.same(t.getField("replayed").get(trial), t.getField("cold").get(trial)))
                throw new AssertionError("module assembly: replayed module differs from cold module (" + i + ")");
            if (!SemanticSnapshot.same(t.getField("replayed_cx").get(trial), t.getField("cold_cx").get(trial)))
                throw new AssertionError("module assembly: replayed Cx differs from cold module state (" + i + ")");
        }
        System.out.println("module-assembly\t10\treordered functions, methods, constants and tests assemble complete cold modules and Cx");
    }
}
