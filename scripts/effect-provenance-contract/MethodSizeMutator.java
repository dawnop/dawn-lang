/* Padding a real reached entry preserves values and provenance but must fail
 * the independent Code-size reader. This is a test artifact, never codegen. */
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;
import java.io.*;
import org.objectweb.asm.*;

public final class MethodSizeMutator {
  public static void main(String[] args) throws Exception {
    int[] changed={0};
    try(ZipFile source=new ZipFile(args[0]);
        ZipOutputStream out=new ZipOutputStream(Files.newOutputStream(Paths.get(args[1])))) {
      Enumeration<? extends ZipEntry> entries=source.entries();
      while(entries.hasMoreElements()) {
        ZipEntry entry=entries.nextElement();
        byte[] data=source.getInputStream(entry).readAllBytes();
        if(entry.getName().endsWith(".class")) {
          ClassReader reader=new ClassReader(data); ClassWriter writer=new ClassWriter(0);
          reader.accept(new ClassVisitor(Opcodes.ASM9,writer) {
            public MethodVisitor visitMethod(int access,String name,String desc,String signature,String[] exceptions) {
              MethodVisitor method=super.visitMethod(access,name,desc,signature,exceptions);
              if(name.equals(args[2]) && changed[0]==0) {
                changed[0]++;
                return new MethodVisitor(Opcodes.ASM9,method) {
                  public void visitCode() {
                    super.visitCode();
                    for(int i=0;i<8001;i++) super.visitInsn(Opcodes.NOP);
                  }
                };
              }
              return method;
            }
          },0);
          data=writer.toByteArray();
        }
        out.putNextEntry(new ZipEntry(entry.getName()));out.write(data);out.closeEntry();
      }
    }
    if(changed[0]!=1) throw new AssertionError("one reached observed entry must be padded");
  }
}
