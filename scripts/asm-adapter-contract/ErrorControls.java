/* Synthetic failures exercise cause identity and diagnostics independently of
 * successful compiler runs, including the actual generated writer boundary.
 */
import dawn.rt.Asm;
import dawn.rt.AsmWriter;
import dawn.rt.AsmDiagnostics;
import org.objectweb.asm.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;

public final class ErrorControls implements Opcodes {
  static final class Fault extends Attribute {
    final RuntimeException cause;
    Fault(RuntimeException cause) { super("FaultControl"); this.cause=cause; }
    @Override protected ByteVector write(ClassWriter cw,byte[] code,int length,int stack,int locals) { throw cause; }
  }
  static ClassWriter writer() {
    ClassWriter cw=AsmWriter.of(ClassWriter.COMPUTE_FRAMES,List.of());
    Asm.beginOn(cw,V1_8,ACC_PUBLIC,"sample/Writer","java/lang/Object");return cw;
  }
  static RuntimeException guarded(RuntimeException cause) {
    ClassWriter cw=writer();cw.visitAttribute(new Fault(cause));cw.visitEnd();
    try {cw.toByteArray();throw new AssertionError("failure was accepted");}
    catch(RuntimeException error){return error;}
  }
  static RuntimeException refusal(int opcode,int operand) throws Exception {
    Class<?> frame=Class.forName("org.objectweb.asm.Frame");
    Constructor<?> ctor=frame.getDeclaredConstructor(Label.class);ctor.setAccessible(true);
    Method execute=Arrays.stream(frame.getDeclaredMethods()).filter(m->m.getName().equals("execute")).findFirst().orElseThrow();execute.setAccessible(true);
    try {execute.invoke(ctor.newInstance(new Label()),opcode,operand,null,null);throw new AssertionError("expected refusal");}
    catch(InvocationTargetException error){if(!(error.getCause() instanceof IllegalArgumentException))throw error;return(RuntimeException)error.getCause();}
  }
  static void errorControl(int opcode,int operand) throws Exception {
    RuntimeException cause=refusal(opcode,operand),error=guarded(cause);
    if(!(error instanceof AsmDiagnostics.Failure) || error.getCause()!=cause)throw new AssertionError("original cause lost");
    if(!error.getMessage().contains("class=sample/Writer") || !error.getMessage().contains("opcode=unknown") || !error.getMessage().contains("org.objectweb.asm.Frame.execute"))throw new AssertionError(error);
    RuntimeException supplied=AsmDiagnostics.report(cause,new AsmDiagnostics.Context("sample/Writer","run()V","rewrite",5,opcode,operand,null),null);
    if(supplied.getCause()!=cause || !supplied.getMessage().contains("opcode="+opcode) || !supplied.getMessage().contains("pc=5"))throw new AssertionError(supplied);
    RuntimeException signed=AsmDiagnostics.report(cause,new AsmDiagnostics.Context("C","m()V","rewrite",5,16,-128,null),null);
    if(!signed.getMessage().contains("operand=-128"))throw new AssertionError("known signed operand lost");
  }
  static byte[] emit(ClassWriter cw) {
    Asm.beginOn(cw,V1_8,ACC_PUBLIC,"Legal","java/lang/Object");
    MethodVisitor m=Asm.methodOn(cw,ACC_PUBLIC|ACC_STATIC,"run","(I)I");m.visitCode();Label done=new Label();
    m.visitVarInsn(ILOAD,0);m.visitJumpInsn(IFEQ,done);
    for(int i=0;i<33000;i++)m.visitInsn(NOP);
    m.visitInsn(ICONST_1);m.visitInsn(IRETURN);m.visitLabel(done);m.visitInsn(ICONST_2);m.visitInsn(IRETURN);
    m.visitMaxs(0,0);m.visitEnd();cw.visitEnd();return cw.toByteArray();
  }
  public static void main(String[] args) throws Exception {
    byte[] plain=emit(new ClassWriter(ClassWriter.COMPUTE_FRAMES)),protectedBytes=emit(AsmWriter.of(ClassWriter.COMPUTE_FRAMES,List.of()));
    if(!Arrays.equals(plain,protectedBytes))throw new AssertionError("legal rewrite output changed");
    System.out.println("PASS unchanged legal rewrite bytes");
    errorControl(250,7);System.out.println("PASS illegal opcode cause and available context");
    errorControl(NEWARRAY,99);System.out.println("PASS illegal atype cause and available context");
    RuntimeException cause=new IllegalArgumentException("original");RuntimeException empty=AsmDiagnostics.report(cause,null,null);
    if(empty.getCause()!=cause || !empty.getMessage().contains("class=unknown") || !empty.getMessage().contains("pc=unknown"))throw new AssertionError(empty);
    System.out.println("PASS empty context");
    String previous=System.getProperty("dawn.jvm.diagnostics");
    try {
      System.setProperty("dawn.jvm.diagnostics","");
      if(!AsmDiagnostics.failure(cause,null).getMessage().contains("diagnostic=unavailable"))throw new AssertionError("empty directory selected the working directory");
    } finally {if(previous==null)System.clearProperty("dawn.jvm.diagnostics");else System.setProperty("dawn.jvm.diagnostics",previous);}
    System.out.println("PASS empty directory does not enable preservation");
    Path bad=Files.createTempFile(Path.of(args[0]),"not-directory-", ".file");
    RuntimeException unsaved=AsmDiagnostics.report(cause,null,bad);
    if(unsaved.getCause()!=cause || cause.getSuppressed().length!=1 || !unsaved.getMessage().contains("Suppressed:"))throw new AssertionError("preservation replaced original failure");
    System.out.println("PASS preservation failure retains original cause");
    for(RuntimeException capacity:List.of(new MethodTooLargeException("C","m","()V",65536),new ClassTooLargeException("C",65536)))
      if(guarded(capacity)!=capacity)throw new AssertionError("capacity failure was wrapped");
    System.out.println("PASS typed capacity exceptions unchanged");
    Path dir=Files.createDirectory(Path.of(args[0]).resolve("selected-diagnostics"));byte[] input={1,2,3};
    AsmDiagnostics.Context context=new AsmDiagnostics.Context("C","m()V","rewrite",1,16,7,input);input[0]=9;
    AsmDiagnostics.report(new IllegalArgumentException(),context,dir);
    try(var paths=Files.list(dir)) {
      Path bytes=paths.filter(p->p.toString().endsWith(".class")).findFirst().orElseThrow();
      if(!Arrays.equals(Files.readAllBytes(bytes),new byte[]{1,2,3}))throw new AssertionError("input was not copied");
      if(!Files.getPosixFilePermissions(bytes).equals(java.nio.file.attribute.PosixFilePermissions.fromString("rw-------")))throw new AssertionError("diagnostic permissions");
    }
    System.out.println("PASS explicit input snapshot and private permissions");
  }
}
