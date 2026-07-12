// Spike: can ASM-generated invokedynamic + LambdaMetafactory adapt a "Dawn fn"
// (a plain static method, which is what Dawn codegen emits) into arbitrary Java
// SAM interfaces -- including jdk.httpserver's HttpHandler -- and does the same
// bytecode work under GraalVM native-image?
//
// This generator emits SpikeSam.class, standing in for Dawn codegen output:
//   - greet()V / greetName(String)String / handleImpl(HttpExchange)V
//       ... the "Dawn functions" (static impl methods)
//   - mkRunnable() / mkSupplier(String) / mkHandler()
//       ... call sites doing indy-LMF against a JDK SAM, exactly the shape a
//           future `use java` SAM conversion would emit. mkSupplier captures an
//           argument, covering the closure-capture path.
//
// Compile/run via run.sh (borrows unrelocated ASM from compiler fat jar).

import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Handle;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Type;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.objectweb.asm.Opcodes.*;

public final class SamGen {
    static final String CLS = "SpikeSam";
    static final Handle LMF_BSM = new Handle(
            H_INVOKESTATIC,
            "java/lang/invoke/LambdaMetafactory",
            "metafactory",
            "(Ljava/lang/invoke/MethodHandles$Lookup;Ljava/lang/String;"
                    + "Ljava/lang/invoke/MethodType;Ljava/lang/invoke/MethodType;"
                    + "Ljava/lang/invoke/MethodHandle;Ljava/lang/invoke/MethodType;)"
                    + "Ljava/lang/invoke/CallSite;",
            false);

    public static void main(String[] args) throws Exception {
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS);
        cw.visit(V21, ACC_PUBLIC | ACC_FINAL | ACC_SUPER, CLS, null, "java/lang/Object", null);

        greet(cw);
        greetName(cw);
        handleImpl(cw);
        mkRunnable(cw);
        mkSupplier(cw);
        mkHandler(cw);

        cw.visitEnd();
        Path out = Path.of(args[0], CLS + ".class");
        Files.write(out, cw.toByteArray());
        System.out.println("wrote " + out);
    }

    // public static void greet() { System.out.println("runnable: hi from dawn fn"); }
    static void greet(ClassWriter cw) {
        MethodVisitor mv = cw.visitMethod(ACC_PUBLIC | ACC_STATIC, "greet", "()V", null, null);
        mv.visitCode();
        mv.visitFieldInsn(GETSTATIC, "java/lang/System", "out", "Ljava/io/PrintStream;");
        mv.visitLdcInsn("runnable: hi from dawn fn");
        mv.visitMethodInsn(INVOKEVIRTUAL, "java/io/PrintStream", "println", "(Ljava/lang/String;)V", false);
        mv.visitInsn(RETURN);
        mv.visitMaxs(0, 0);
        mv.visitEnd();
    }

    // public static String greetName(String name) { return "supplier: hi, " + name; }
    static void greetName(ClassWriter cw) {
        MethodVisitor mv = cw.visitMethod(ACC_PUBLIC | ACC_STATIC, "greetName",
                "(Ljava/lang/String;)Ljava/lang/String;", null, null);
        mv.visitCode();
        mv.visitTypeInsn(NEW, "java/lang/StringBuilder");
        mv.visitInsn(DUP);
        mv.visitMethodInsn(INVOKESPECIAL, "java/lang/StringBuilder", "<init>", "()V", false);
        mv.visitLdcInsn("supplier: hi, ");
        mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/StringBuilder", "append",
                "(Ljava/lang/String;)Ljava/lang/StringBuilder;", false);
        mv.visitVarInsn(ALOAD, 0);
        mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/StringBuilder", "append",
                "(Ljava/lang/String;)Ljava/lang/StringBuilder;", false);
        mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/StringBuilder", "toString",
                "()Ljava/lang/String;", false);
        mv.visitInsn(ARETURN);
        mv.visitMaxs(0, 0);
        mv.visitEnd();
    }

    // public static void handleImpl(HttpExchange ex) throws IOException {
    //   byte[] b = "hi from dawn handler".getBytes();
    //   ex.sendResponseHeaders(200, b.length); ex.getResponseBody().write(b); ...close
    // }
    static void handleImpl(ClassWriter cw) {
        MethodVisitor mv = cw.visitMethod(ACC_PUBLIC | ACC_STATIC, "handleImpl",
                "(Lcom/sun/net/httpserver/HttpExchange;)V", null,
                new String[]{"java/io/IOException"});
        mv.visitCode();
        mv.visitLdcInsn("hi from dawn handler");
        mv.visitMethodInsn(INVOKEVIRTUAL, "java/lang/String", "getBytes", "()[B", false);
        mv.visitVarInsn(ASTORE, 1);
        mv.visitVarInsn(ALOAD, 0);
        mv.visitIntInsn(SIPUSH, 200);
        mv.visitVarInsn(ALOAD, 1);
        mv.visitInsn(ARRAYLENGTH);
        mv.visitInsn(I2L);
        mv.visitMethodInsn(INVOKEVIRTUAL, "com/sun/net/httpserver/HttpExchange",
                "sendResponseHeaders", "(IJ)V", false);
        mv.visitVarInsn(ALOAD, 0);
        mv.visitMethodInsn(INVOKEVIRTUAL, "com/sun/net/httpserver/HttpExchange",
                "getResponseBody", "()Ljava/io/OutputStream;", false);
        mv.visitVarInsn(ASTORE, 2);
        mv.visitVarInsn(ALOAD, 2);
        mv.visitVarInsn(ALOAD, 1);
        mv.visitMethodInsn(INVOKEVIRTUAL, "java/io/OutputStream", "write", "([B)V", false);
        mv.visitVarInsn(ALOAD, 2);
        mv.visitMethodInsn(INVOKEVIRTUAL, "java/io/OutputStream", "close", "()V", false);
        mv.visitVarInsn(ALOAD, 0);
        mv.visitMethodInsn(INVOKEVIRTUAL, "com/sun/net/httpserver/HttpExchange", "close", "()V", false);
        mv.visitInsn(RETURN);
        mv.visitMaxs(0, 0);
        mv.visitEnd();
    }

    // public static Runnable mkRunnable() { return SpikeSam::greet; }  (non-capturing)
    static void mkRunnable(ClassWriter cw) {
        MethodVisitor mv = cw.visitMethod(ACC_PUBLIC | ACC_STATIC, "mkRunnable",
                "()Ljava/lang/Runnable;", null, null);
        mv.visitCode();
        mv.visitInvokeDynamicInsn("run", "()Ljava/lang/Runnable;", LMF_BSM,
                Type.getMethodType("()V"),
                new Handle(H_INVOKESTATIC, CLS, "greet", "()V", false),
                Type.getMethodType("()V"));
        mv.visitInsn(ARETURN);
        mv.visitMaxs(0, 0);
        mv.visitEnd();
    }

    // public static Supplier<String> mkSupplier(String s) { return () -> greetName(s); }  (capturing)
    static void mkSupplier(ClassWriter cw) {
        MethodVisitor mv = cw.visitMethod(ACC_PUBLIC | ACC_STATIC, "mkSupplier",
                "(Ljava/lang/String;)Ljava/util/function/Supplier;", null, null);
        mv.visitCode();
        mv.visitVarInsn(ALOAD, 0);
        mv.visitInvokeDynamicInsn("get", "(Ljava/lang/String;)Ljava/util/function/Supplier;", LMF_BSM,
                Type.getMethodType("()Ljava/lang/Object;"),
                new Handle(H_INVOKESTATIC, CLS, "greetName",
                        "(Ljava/lang/String;)Ljava/lang/String;", false),
                Type.getMethodType("()Ljava/lang/String;"));
        mv.visitInsn(ARETURN);
        mv.visitMaxs(0, 0);
        mv.visitEnd();
    }

    // public static HttpHandler mkHandler() { return SpikeSam::handleImpl; }
    static void mkHandler(ClassWriter cw) {
        MethodVisitor mv = cw.visitMethod(ACC_PUBLIC | ACC_STATIC, "mkHandler",
                "()Lcom/sun/net/httpserver/HttpHandler;", null, null);
        mv.visitCode();
        mv.visitInvokeDynamicInsn("handle", "()Lcom/sun/net/httpserver/HttpHandler;", LMF_BSM,
                Type.getMethodType("(Lcom/sun/net/httpserver/HttpExchange;)V"),
                new Handle(H_INVOKESTATIC, CLS, "handleImpl",
                        "(Lcom/sun/net/httpserver/HttpExchange;)V", false),
                Type.getMethodType("(Lcom/sun/net/httpserver/HttpExchange;)V"));
        mv.visitInsn(ARETURN);
        mv.visitMaxs(0, 0);
        mv.visitEnd();
    }
}
