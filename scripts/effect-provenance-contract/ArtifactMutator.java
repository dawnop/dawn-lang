/* Test-only mutations of finished classfiles. A successful mutant must still
 * compute the fixture's answer before the independent origin oracle rejects it. */
import java.nio.file.*;
import java.util.*;
import java.util.jar.*;
import org.objectweb.asm.*;

public final class ArtifactMutator {
  private static int changes;
  private static String lifted;
  private static String firstSite, secondSite;
  private static long firstId, secondId;
  private static int handlerStart;
  private static String source;
  private ArtifactMutator() {}
  public static void main(String[] args) throws Exception {
    String mode = args[2];
    source = Files.readString(Path.of(args[3]));
    if (mode.equals("query")) handlerStart = source.indexOf("query(n) origin source", source.indexOf("fn main()"))-source.indexOf("fn main()");
    Map<String, byte[]> entries = new LinkedHashMap<>();
    try (JarFile jar = new JarFile(args[0])) {
      Enumeration<JarEntry> enumeration = jar.entries();
      while (enumeration.hasMoreElements()) {
        JarEntry entry = enumeration.nextElement();
        entries.put(entry.getName(), jar.getInputStream(entry).readAllBytes());
      }
    }
    if (mode.equals("route") || mode.equals("devirtualized")) {
      new ClassReader(entries.get("modes.class")).accept(new ClassVisitor(Opcodes.ASM9) {
        public MethodVisitor visitMethod(int access, String name, String descriptor, String signature, String[] exceptions) {
          return new MethodVisitor(Opcodes.ASM9) {
            public void visitLdcInsn(Object value) {
              if (name.endsWith("$observed") && value instanceof String
                  && (mode.equals("route")
                    ? ((String)value).startsWith("modes\tNf4:make\t") && ((String)value).contains("\tlambda\t")
                    : ((String)value).startsWith("modes\tI4:Stepn7:Counter0;0;Nm4:step\t"))) lifted = name;
            }
          };
        }
      }, 0);
      if (lifted == null) throw new AssertionError("missing independently selected factory lambda");
    }
    if (mode.equals("chain")) {
      int main = source.indexOf("fn main()");
      int lo = source.indexOf("Counter { n = 1 }).bump()", main)-main;
      TreeMap<Integer, String[]> sites = new TreeMap<>();
      new ClassReader(entries.get("unwind$provenance_sites.class")).accept(new ClassVisitor(Opcodes.ASM9) {
        public MethodVisitor visitMethod(int access, String name, String descriptor, String signature, String[] exceptions) {
          return new MethodVisitor(Opcodes.ASM9) {
            public void visitLdcInsn(Object value) {
              if (value instanceof String && ((String)value).startsWith("unwind\tNf4:main\t"+lo+"\t")
                  && ((String)value).endsWith("\tcall\t")) {
                String text = (String)value;
                sites.put(Integer.parseInt(text.split("\t", -1)[3]), new String[]{name, text});
              }
            }
          };
        }
      }, 0);
      if (sites.size() != 2) throw new AssertionError("method chain Site selection");
      firstSite = sites.firstEntry().getValue()[1]; secondSite = sites.lastEntry().getValue()[1];
      firstId = Long.parseLong(sites.firstEntry().getValue()[0].substring(5));
      secondId = Long.parseLong(sites.lastEntry().getValue()[0].substring(5));
    }
    try (JarOutputStream out = new JarOutputStream(Files.newOutputStream(Path.of(args[1])))) {
      for (Map.Entry<String, byte[]> entry : entries.entrySet()) {
        byte[] bytes = entry.getValue();
        if (entry.getKey().endsWith(".class")) {
          ClassReader reader = new ClassReader(bytes);
          ClassWriter writer = new ClassWriter(0);
          reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
            public MethodVisitor visitMethod(int access, String name, String descriptor, String signature, String[] exceptions) {
              MethodVisitor delegate = super.visitMethod(access, name, descriptor, signature, exceptions);
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                private boolean query;
                public void visitMethodInsn(int opcode, String owner, String method, String desc, boolean itf) {
                  boolean route = mode.equals("route") && name.equals("applyObserved") && owner.equals("modes") && method.equals(lifted);
                  boolean pure = mode.equals("pure") && owner.equals("builder") && method.equals("pure$observed");
                  boolean trait = owner.equals("dawn/tr/modes$Step") && (
                      mode.equals("trait") && method.equals("step$observed")
                      || mode.equals("default") && method.equals("twice$observed"));
                  boolean devirtualized = mode.equals("devirtualized") && owner.equals("modes") && method.equals(lifted);
                  if (mode.equals("query") && query && owner.equals("dawn/rt/Provenance") && method.equals("note")) {
                    super.visitInsn(Opcodes.POP); super.visitInsn(Opcodes.POP2); changes++; return;
                  }
                  if (route || pure || trait || devirtualized) {
                    super.visitInsn(Opcodes.POP2);
                    method = method.substring(0, method.length()-"$observed".length());
                    int end = desc.indexOf(')');
                    if (desc.charAt(end-1) != 'J') throw new AssertionError("observed descriptor");
                    desc = desc.substring(0, end-1)+desc.substring(end);
                    changes++;
                  }
                  super.visitMethodInsn(opcode, owner, method, desc, itf);
                }
                public void visitFieldInsn(int opcode, String owner, String field, String desc) {
                  if (name.equals("record") && owner.equals("dawn/rt/Provenance$Frame") && opcode == Opcodes.GETFIELD) {
                    if (mode.equals("instance") && field.equals("id")) { field = "site"; changes++; }
                    if (mode.equals("parent") && field.equals("parent")) { field = "id"; changes++; }
                  }
                  super.visitFieldInsn(opcode, owner, field, desc);
                }
                public void visitLdcInsn(Object value) {
                  if (mode.equals("query") && value instanceof String && name.endsWith("$observed")
                      && ((String)value).startsWith("builder\tNf4:main\t"+handlerStart+"\t")
                      && ((String)value).contains("\thandler\t")) query = true;
                  if (mode.equals("chain")) {
                    if (value.equals(secondSite)) { value = firstSite; changes++; }
                    else if (value instanceof Long && ((Long)value).longValue() == secondId) { value = firstId; changes++; }
                  }
                  if (mode.equals("syntax") && value instanceof String) {
                    String text = (String)value;
                    for (String role : new String[]{"operator", "literal", "var", "for", "if"})
                      text = text.replace("\t"+role+"\t", "\tunknown\t");
                    if (!text.equals(value)) { value = text; changes++; }
                  }
                  if (mode.equals("handler") && value instanceof String) {
                    String text = (String)value;
                    if (text.startsWith("builder\tNf6:helper\t") && text.contains("\tperform\t")) {
                      value = text.replace("builder\tNf6:helper\t", "builder\tNf4:main\t"); changes++;
                    }
                  }
                  super.visitLdcInsn(value);
                }
              };
            }
          }, 0);
          bytes = writer.toByteArray();
        }
        out.putNextEntry(new JarEntry(entry.getKey())); out.write(bytes); out.closeEntry();
      }
    }
    if (changes == 0) throw new AssertionError("mutation did not touch an actual artifact");
    System.out.println("changed "+changes+" bytecode instructions");
  }
}
