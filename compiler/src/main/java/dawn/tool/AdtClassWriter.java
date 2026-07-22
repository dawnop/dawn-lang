package dawn.tool;

import java.util.Map;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.FieldVisitor;
import org.objectweb.asm.MethodVisitor;

/**
 * The class writer both compilers share (Kotlin CodeGen and the self-hosted
 * one, docs/selfhost-codegen.md). COMPUTE_FRAMES needs common superclasses,
 * but generated classes are not on the compiler's classpath — so the synthetic
 * hierarchy (ADT ctor → base → Object, tuples → Object) is passed in and
 * walked here; anything unknown falls back to Object.
 *
 * The begin/field/method helpers exist for the Dawn side: Dawn has no null,
 * and ASM's raw visit methods take nullable signature/interfaces arguments.
 */
public final class AdtClassWriter extends ClassWriter {
    private static final String OBJ = "java/lang/Object";
    private final Map<String, String> supers;

    public AdtClassWriter(Map<String, String> supers) {
        super(COMPUTE_FRAMES);
        this.supers = supers;
    }

    private java.util.List<String> chain(String t) {
        java.util.ArrayList<String> c = new java.util.ArrayList<>();
        String cur = t;
        while (cur != null) {
            c.add(cur);
            cur = supers.get(cur);
        }
        if (!c.get(c.size() - 1).equals(OBJ)) c.add(OBJ);
        return c;
    }

    @Override
    protected String getCommonSuperClass(String type1, String type2) {
        if (type1.equals(type2)) return type1;
        if (supers.containsKey(type1) || supers.containsKey(type2)) {
            java.util.HashSet<String> above2 = new java.util.HashSet<>(chain(type2));
            for (String s : chain(type1)) {
                if (above2.contains(s)) return s;
            }
            return OBJ;
        }
        try {
            return super.getCommonSuperClass(type1, type2);
        } catch (Throwable e) {
            return OBJ;
        }
    }

    // ---- null-free conveniences for the Dawn side ----

    /** visit(version, access, name, null, superName, null) */
    public void begin(int version, int access, String name, String superName) {
        visit(version, access, name, null, superName, null);
    }

    /** visit with one implemented interface */
    public void beginWithInterface(int version, int access, String name, String superName, String iface) {
        visit(version, access, name, null, superName, new String[] { iface });
    }

    /** visitField(access, name, desc, null, null) + visitEnd */
    public void field(int access, String name, String desc) {
        FieldVisitor f = visitField(access, name, desc, null, null);
        f.visitEnd();
    }

    /** visitMethod(access, name, desc, null, null) */
    public MethodVisitor method(int access, String name, String desc) {
        return visitMethod(access, name, desc, null, null);
    }
}
