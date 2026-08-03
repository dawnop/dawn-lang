// The differential behind K-A7 (docs/jvm-base-plan.md §5.7): the five null
// adapters Dawn now emits as `dawn/rt/Asm` must be indistinguishable from the
// five `dawn.tool.AdtClassWriter` statics they are going to replace.
//
// Why a differential and not "it still builds": in phase 1 nothing calls the
// emitted class, so an empty `dawn/rt/Asm` would leave every other gate green.
// The only check that can tell the two apart is one that drives both surfaces
// and compares what came out.
//
// The comparison is the class file each adapter produces. That is stronger
// than comparing return values: `beginOn` has to pass *null* for `signature`
// (a non-null one adds a Signature attribute), `beginOnWithInterface` has to
// build a one-element array (a wrong length or a null element changes the
// interfaces table), and `plain` has to forward its flag rather than pick one
// (COMPUTE_MAXS vs 0 is visible as maxStack/maxLocals). All of that lands in
// the bytes.
//
// The adapters are reached by reflection, deliberately: the reflection is
// itself the surface check. `getDeclaredMethod` with exact parameter types
// plus the public/static assertion says the two classes agree on names,
// descriptors and modifiers before a single byte is compared.
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.Arrays;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

public class Diff {
  static final String REF = "dawn.tool.AdtClassWriter";
  static final String NEW = "dawn.rt.Asm";

  static final int V49 = 49;
  static final int COMPUTE_MAXS = 1;
  static final int PUBLIC_FINAL = Opcodes.ACC_PUBLIC | Opcodes.ACC_FINAL;
  static final int PUBLIC_STATIC = Opcodes.ACC_PUBLIC | Opcodes.ACC_STATIC;

  static int failures = 0;

  static Method entry(Class<?> owner, String name, Class<?>... ps) throws Exception {
    Method m = owner.getDeclaredMethod(name, ps);
    if (!Modifier.isPublic(m.getModifiers()) || !Modifier.isStatic(m.getModifiers())) {
      throw new AssertionError(owner.getName() + "." + name + " is not public static");
    }
    return m;
  }

  /** The five entry points, driven once each, ending in a finished class file. */
  static byte[] probe(Class<?> a, int flags, boolean withInterface) throws Exception {
    Object w = entry(a, "plain", int.class).invoke(null, flags);
    if (!(w instanceof ClassWriter)) {
      throw new AssertionError(a.getName() + ".plain did not return a ClassWriter");
    }
    ClassWriter cw = (ClassWriter) w;

    if (withInterface) {
      entry(a, "beginOnWithInterface", ClassWriter.class, int.class, int.class, String.class,
              String.class, String.class)
          .invoke(null, cw, V49, PUBLIC_FINAL, "probe/P", "java/lang/Object", "java/lang/Runnable");
    } else {
      entry(a, "beginOn", ClassWriter.class, int.class, int.class, String.class, String.class)
          .invoke(null, cw, V49, PUBLIC_FINAL, "probe/P", "java/lang/Object");
    }

    entry(a, "fieldOn", ClassWriter.class, int.class, String.class, String.class)
        .invoke(null, cw, PUBLIC_STATIC, "f", "I");

    Method methodOn =
        entry(a, "methodOn", ClassWriter.class, int.class, String.class, String.class);
    Object mv = methodOn.invoke(null, cw, PUBLIC_STATIC, "square", "(I)I");
    if (!(mv instanceof MethodVisitor)) {
      throw new AssertionError(a.getName() + ".methodOn did not return a MethodVisitor");
    }
    square((MethodVisitor) mv);

    if (withInterface) {
      Object run = methodOn.invoke(null, cw, Opcodes.ACC_PUBLIC, "run", "()V");
      MethodVisitor r = (MethodVisitor) run;
      r.visitCode();
      r.visitInsn(Opcodes.RETURN);
      r.visitMaxs(0, 0);
      r.visitEnd();
    }

    cw.visitEnd();
    return cw.toByteArray();
  }

  /** `static int square(int n) { return n == 0 ? 0 : n * n; }` -- a branch, so
   * COMPUTE_MAXS has real work to do and the flag `plain` forwards shows up. */
  static void square(MethodVisitor m) {
    Label zero = new Label();
    m.visitCode();
    m.visitVarInsn(Opcodes.ILOAD, 0);
    m.visitJumpInsn(Opcodes.IFEQ, zero);
    m.visitVarInsn(Opcodes.ILOAD, 0);
    m.visitVarInsn(Opcodes.ILOAD, 0);
    m.visitInsn(Opcodes.IMUL);
    m.visitInsn(Opcodes.IRETURN);
    m.visitLabel(zero);
    m.visitInsn(Opcodes.ICONST_0);
    m.visitInsn(Opcodes.IRETURN);
    m.visitMaxs(0, 0);
    m.visitEnd();
  }

  static void check(String what, boolean ok) {
    System.out.println((ok ? "PASS  " : "FAIL  ") + what);
    if (!ok) {
      failures++;
    }
  }

  interface Probe {
    boolean run() throws Exception;
  }

  /** A check whose failure mode is a thrown linkage error, not a false. */
  static boolean attempt(Probe p) {
    try {
      return p.run();
    } catch (Throwable t) {
      System.out.println("      " + t);
      return false;
    }
  }

  static final class Bytes extends ClassLoader {
    Class<?> define(String name, byte[] bs) {
      return defineClass(name, bs, 0, bs.length);
    }
  }

  public static void main(String[] args) throws Exception {
    Class<?> ref = Class.forName(REF);
    Class<?> now = Class.forName(NEW);
    System.out.println("reference " + ref.getName() + " from " + where(ref));
    System.out.println("emitted   " + now.getName() + " from " + where(now));

    byte[] refPlain = probe(ref, COMPUTE_MAXS, false);
    byte[] nowPlain = probe(now, COMPUTE_MAXS, false);
    check("beginOn/fieldOn/methodOn produce identical class files",
        Arrays.equals(refPlain, nowPlain));

    byte[] refIface = probe(ref, COMPUTE_MAXS, true);
    byte[] nowIface = probe(now, COMPUTE_MAXS, true);
    check("beginOnWithInterface produces an identical class file",
        Arrays.equals(refIface, nowIface));

    byte[] refRaw = probe(ref, 0, false);
    byte[] nowRaw = probe(now, 0, false);
    check("plain(0) produces an identical class file", Arrays.equals(refRaw, nowRaw));

    // The control for the control: if the probe could not see the flag, the
    // three comparisons above would agree no matter what `plain` forwarded.
    check("the probe is flag-sensitive (COMPUTE_MAXS differs from 0)",
        !Arrays.equals(refPlain, refRaw));
    check("the emitted adapter forwards its flag", !Arrays.equals(nowPlain, nowRaw));

    // Bytes being equal says the adapters agree; this says they are right. A
    // class the adapter mis-assembled fails to link rather than compare
    // unequal, so the failure is reported instead of thrown -- a gate that
    // dies on its first red says less than one that finishes.
    check("the emitted adapter's class links and runs (square(7) == 49)",
        attempt(() -> {
          Class<?> p = new Bytes().define("probe.P", nowPlain);
          return Integer.valueOf(49).equals(p.getDeclaredMethod("square", int.class).invoke(null, 7));
        }));
    check("the interface form declares its interface",
        attempt(() -> {
          Class<?> pi = new Bytes().define("probe.P", nowIface);
          return Arrays.equals(new Class<?>[] {Runnable.class}, pi.getInterfaces());
        }));

    if (failures > 0) {
      System.err.println("FAIL: " + failures + " adapter difference(s); dawn/rt/Asm is not a "
          + "drop-in for dawn.tool.AdtClassWriter");
      System.exit(1);
    }
    System.out.println("OK: the emitted dawn/rt/Asm matches dawn.tool.AdtClassWriter on all "
        + "five entry points");
  }

  static String where(Class<?> c) {
    java.security.CodeSource cs = c.getProtectionDomain().getCodeSource();
    return cs == null ? "<no code source>" : String.valueOf(cs.getLocation());
  }

  static {
    // An InvocationTargetException from a reflective call would otherwise be
    // reported as the wrapper rather than the adapter's own failure.
    Thread.setDefaultUncaughtExceptionHandler((t, e) -> {
      Throwable c = e instanceof InvocationTargetException ? e.getCause() : e;
      c.printStackTrace();
      Runtime.getRuntime().halt(1);
    });
  }
}
