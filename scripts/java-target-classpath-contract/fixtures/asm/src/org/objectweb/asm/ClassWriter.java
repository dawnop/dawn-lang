package org.objectweb.asm;

public class ClassWriter {
    public static final int COMPUTE_FRAMES = 2;

    public ClassWriter(int flags) {}

    public void visit(
            int version,
            int access,
            String name,
            String signature,
            String superName,
            String[] interfaces) {}

    public FieldVisitor visitField(
            int access, String name, String descriptor, String signature, Object value) {
        return new FieldVisitor();
    }

    public MethodVisitor visitMethod(
            int access, String name, String descriptor, String signature, String[] exceptions) {
        return new MethodVisitor();
    }

    public void visitEnd() {}

    public byte[] toByteArray() {
        return new byte[0];
    }

    protected String getCommonSuperClass(String left, String right) {
        return "java/lang/Object";
    }
}
