/* These mutations keep computation intact while removing an observed fact.
 * Finished test JARs alone are rewritten; product emission never uses ASM here. */
import java.nio.file.*;
import java.util.*;
import java.util.jar.*;
import org.objectweb.asm.*;
public final class ControlMutator {
  public static void main(String[] args) throws Exception {
    String target=args[2].equals("tail") ? "tailContext" : args[2].equals("control") ? "controlBody" : "unknownContext";
    int[] changed={0};
    try (JarFile input=new JarFile(args[0]); JarOutputStream output=new JarOutputStream(Files.newOutputStream(Path.of(args[1])))) {
      Enumeration<JarEntry> entries=input.entries();
      while(entries.hasMoreElements()) {
        JarEntry entry=entries.nextElement(); byte[] bytes=input.getInputStream(entry).readAllBytes();
        if(entry.getName().equals("dawn/rt/Provenance.class")) {
          ClassWriter writer=new ClassWriter(0);
          new ClassReader(bytes).accept(new ClassVisitor(Opcodes.ASM9,writer) {
            public MethodVisitor visitMethod(int access,String name,String desc,String signature,String[] exceptions) {
              MethodVisitor method=super.visitMethod(access,name,desc,signature,exceptions);
              if(!name.equals(target)) return method;
              method.visitCode();
              if(target.equals("controlBody")) {
                method.visitVarInsn(Opcodes.ALOAD,0); method.visitTypeInsn(Opcodes.CHECKCAST,"dawn/rt/Fn1");
                method.visitVarInsn(Opcodes.ALOAD,1);
                method.visitMethodInsn(Opcodes.INVOKEINTERFACE,"dawn/rt/Fn1","apply","(Ljava/lang/Object;)Ljava/lang/Object;",true);
                method.visitInsn(Opcodes.ARETURN); method.visitMaxs(2,3);
              } else {
                method.visitInsn(Opcodes.RETURN); method.visitMaxs(0,target.equals("tailContext") ? 4 : 1);
              }
              method.visitEnd(); changed[0]++; return null;
            }
          },0); bytes=writer.toByteArray();
        }
        JarEntry out=new JarEntry(entry.getName()); out.setTime(0); output.putNextEntry(out); output.write(bytes); output.closeEntry();
      }
    }
    if(changed[0]!=1) throw new AssertionError("expected one runtime fact mutation: "+changed[0]);
  }
}
