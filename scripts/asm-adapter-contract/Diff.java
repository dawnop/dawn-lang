// The differential behind K-A7 (docs/jvm-base-plan.md §5.7): the five null
// adapters Dawn emits as `dawn/rt/Asm` must be indistinguishable from the five
// `dawn.tool.AdtClassWriter` statics they replaced.
//
// Why a differential and not "it still builds": in phase 1 nothing called the
// emitted class, so an empty `dawn/rt/Asm` would leave every other gate green.
// Since phase 2 the reason is stronger and stated in run.sh's header -- the
// adapter emits itself, so a wrong adapter can emit an equally wrong adapter
// and no gate downstream of the compiler can see it. The reference here is
// javac's build of the archived source, which is the one link that does not
// pass through the Dawn compiler.
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
//
// Two subjects, not one:
//   1. self-emitted      -- what bin/dawn puts in the jar, adapter written by
//                           adapter. This is the artifact that ships, and the
//                           only one that would carry a defect propagated from
//                           an earlier generation.
//   2. reference-emitted -- the same emitter run with javac's build of the
//                           archived source shadowing `dawn.rt.Asm` on the
//                           class path. Same bytes written by today's
//                           `gen_asm_class`, but written *by* the reference,
//                           so a defect cannot corrupt its own emission.
// Both get the full differential every run. When they are byte-identical the
// second pass is redundant by construction -- and running it anyway is the
// difference between discrimination that works and discrimination that is
// dormant behind a branch nobody takes.
import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

public class Diff {
  static final String REF = "dawn.tool.AdtClassWriter";
  static final String NEW = "dawn.rt.Asm";
  static final String WRITER = "dawn.rt.AsmWriter";

  static final int V49 = 49;
  static final int V52 = 52;
  static final int COMPUTE_MAXS = 1;
  static final int COMPUTE_FRAMES = 2;
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

  /**
   * The reference must not be an artifact of the compiler under test.
   *
   * A gate cannot assert its own independence, but it can assert that the class
   * it is comparing against is one this compiler could not have written. The
   * emitted adapter is exactly five public statics on `java.lang.Object`: no
   * fields, no constructor, no superclass. The tagged source is a `ClassWriter`
   * subclass with a `supers` map, two constructors, an override of
   * `getCommonSuperClass`, and the four instance helpers §5.7 measured at zero
   * call sites -- none of which `gen_asm_class` writes. (K-A8.1 brought the
   * frame half back, but as a *second* emitted class, `dawn/rt/AsmWriter`; the
   * reference stays one class carrying both halves, so this assertion is
   * unaffected and the instance helpers remain members nothing here emits.)
   * Repoint this gate's reference at anything our own build produced
   * and every clause below fails, which is the point: that refactor keeps all
   * seven differential checks green while destroying what they mean.
   */
  static boolean referenceIsForeign(Class<?> ref) {
    if (ref.getSuperclass() != ClassWriter.class) {
      System.out.println("      superclass is " + ref.getSuperclass() + ", not ClassWriter");
      return false;
    }
    if (ref.getDeclaredConstructors().length == 0 || ref.getDeclaredFields().length == 0) {
      System.out.println("      no declared constructor or field; the emitter writes neither");
      return false;
    }
    for (String n : new String[] {"getCommonSuperClass", "begin", "beginWithInterface", "field",
        "method"}) {
      boolean found = false;
      for (Method m : ref.getDeclaredMethods()) {
        found |= m.getName().equals(n);
      }
      if (!found) {
        System.out.println("      no " + n + "; the emitter writes only the five statics");
        return false;
      }
    }
    return true;
  }

  /** The seven-check differential, run against one subject's bytes. */
  static void differential(String tag, Class<?> ref, byte[] subject) throws Exception {
    System.out.println("-- " + tag + " --");
    Class<?> now;
    try {
      now = new Bytes().define(NEW, subject);
    } catch (Throwable t) {
      // `gen_asm_class` writes the adapter with the adapter, so a defect in
      // `plain`/`beginOn`/`methodOn` self-applies and the product is malformed
      // rather than wrong. Say so as a FAIL line instead of dying on a raw
      // ClassFormatError -- and read the other subject's block for which entry
      // point it was.
      check("the emitted " + NEW + " is a loadable class file", false);
      System.out.println("      " + t);
      return;
    }

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
  }

  // ------------------------------------------------------------------------
  // The frame half: dawn/rt/AsmWriter (K-A8.1, docs/jvm-base-plan.md §5.7)
  // ------------------------------------------------------------------------
  //
  // COMPUTE_FRAMES names the type at every merge point, and for two classes
  // this compilation is about to write, ASM's own answer -- `Class.forName` --
  // cannot work. `AdtClassWriter` carried the override; K-A4 stranded it and
  // K-A7 deleted it with the binary. It is back as an emitted class, and the
  // reference for it is the *same* archived Java source, so the differential
  // below is the same diverse-double-compiling argument as the one above.
  //
  // The emitter never asks the oracle anything today (V49 + COMPUTE_MAXS
  // computes no frames), so without this the class could answer nonsense --
  // or nothing -- with every gate green. That is the K-A7 phase-1 situation
  // again, and the answer is the same: drive it.

  /** A hierarchy of the shape `supers_of` builds: ADT bases and their ctors,
   * plus the JDK exception edges the emitted `Io.catch_fault` table needs. */
  static final List<String> SUPERS = List.of(
      "p/Base java/lang/Object",
      "p/Sub p/Base",
      "p/Other p/Base",
      "dawn/rt/PanicError java/lang/Error",
      "java/lang/Error java/lang/Throwable",
      "java/lang/Exception java/lang/Throwable",
      "java/lang/Throwable java/lang/Object");

  /** Questions whose answer is the table's, on both sides. Every pair has at
   * least one member in SUPERS, which is the branch `AdtClassWriter` answers
   * from its map; a pair with neither is the one place the two deliberately
   * differ (the reference delegates to `Class.forName`, the emitted writer
   * says Object -- see gen_asm_writer_class), so `x/A | y/B` is here with two
   * names no class loader can resolve, where the reference's delegation ends
   * at Object as well. */
  static final String[][] QUESTIONS = {
    {"p/Sub", "p/Sub"}, {"p/Sub", "p/Base"}, {"p/Base", "p/Sub"},
    {"p/Sub", "p/Other"}, {"p/Sub", "java/lang/Object"}, {"p/Base", "x/A"},
    {"dawn/rt/PanicError", "java/lang/Exception"}, {"x/A", "y/B"},
  };

  static Method oracleOf(Class<?> c) throws Exception {
    Method m = c.getDeclaredMethod("getCommonSuperClass", String.class, String.class);
    m.setAccessible(true);
    return m;
  }

  /** `AsmWriter.of(flags, supers)` -- declared to return the *supertype*, which
   * is what lets a Dawn call site keep its `ClassWriter` plumbing. */
  static ClassWriter writer(Class<?> w, int flags) throws Exception {
    Method of = entry(w, "of", int.class, List.class);
    if (of.getReturnType() != ClassWriter.class) {
      throw new AssertionError(WRITER + ".of returns " + of.getReturnType() + ", not ClassWriter");
    }
    return (ClassWriter) of.invoke(null, flags, SUPERS);
  }

  /** A class whose only interesting property is being a subclass of `Base`. */
  static byte[] plainClass(String name, String superName) {
    ClassWriter cw = new ClassWriter(COMPUTE_MAXS);
    cw.visit(V52, Opcodes.ACC_PUBLIC, name, null, superName, null);
    cw.visitEnd();
    return cw.toByteArray();
  }

  /** `static Base pick(boolean f, Sub s, Base b) { return f ? s : b; }` in a
   * writer that computes frames: the merge is the only thing that asks the
   * oracle, and the declared return type is what makes a wrong answer a
   * `VerifyError` rather than a class nobody notices is wrong. */
  static byte[] frameProbe(ClassWriter cw) {
    cw.visit(V52, PUBLIC_FINAL, "p/P", null, "java/lang/Object", null);
    MethodVisitor m =
        cw.visitMethod(PUBLIC_STATIC, "pick", "(ZLp/Sub;Lp/Base;)Lp/Base;", null, null);
    m.visitCode();
    Label other = new Label();
    Label join = new Label();
    m.visitVarInsn(Opcodes.ILOAD, 0);
    m.visitJumpInsn(Opcodes.IFEQ, other);
    m.visitVarInsn(Opcodes.ALOAD, 1);
    m.visitJumpInsn(Opcodes.GOTO, join);
    m.visitLabel(other);
    m.visitVarInsn(Opcodes.ALOAD, 2);
    m.visitLabel(join);
    m.visitInsn(Opcodes.ARETURN);
    m.visitMaxs(0, 0);
    m.visitEnd();
    cw.visitEnd();
    return cw.toByteArray();
  }

  /** Define `p/Base`, `p/Sub` and the probe in one loader and link the probe.
   * Returns null when it links, the linkage failure otherwise. */
  static Throwable linkProbe(byte[] probe) {
    try {
      Bytes ld = new Bytes();
      ld.define("p.Base", plainClass("p/Base", "java/lang/Object"));
      ld.define("p.Sub", plainClass("p/Sub", "p/Base"));
      Class<?> p = ld.define("p.P", probe);
      // defineClass does not verify; resolving the method does.
      p.getDeclaredMethod("pick", boolean.class, ld.loadClass("p.Sub"), ld.loadClass("p.Base"));
      java.lang.invoke.MethodHandles.lookup().ensureInitialized(p);
      return null;
    } catch (Throwable t) {
      return t;
    }
  }

  /** A writer with the oracle deliberately wrong in the only direction a table
   * can be wrong: too wide. Without it, the frame probe's green would not
   * distinguish "the oracle answered" from "the probe cannot tell". */
  static final class Widest extends ClassWriter {
    Widest() {
      super(COMPUTE_FRAMES);
    }

    @Override
    protected String getCommonSuperClass(String a, String b) {
      return "java/lang/Object";
    }
  }

  static void oracle(String tag, Class<?> ref, byte[] subject) throws Exception {
    System.out.println("-- " + tag + " --");
    Class<?> now;
    try {
      now = new Bytes().define(WRITER, subject);
    } catch (Throwable t) {
      check("the emitted " + WRITER + " is a loadable class file", false);
      System.out.println("      " + t);
      return;
    }
    if (now.getSuperclass() != ClassWriter.class) {
      check("the emitted " + WRITER + " extends ClassWriter", false);
      return;
    }

    Constructor<?> refCtor = ref.getConstructor(List.class);
    Object refWriter = refCtor.newInstance(SUPERS);
    Method refAsk = oracleOf(ref);
    Method nowAsk = oracleOf(now);
    Object nowWriter = writer(now, COMPUTE_MAXS);

    StringBuilder disagreed = new StringBuilder();
    for (String[] q : QUESTIONS) {
      Object r = refAsk.invoke(refWriter, q[0], q[1]);
      Object n = nowAsk.invoke(nowWriter, q[0], q[1]);
      if (!r.equals(n)) {
        disagreed.append("\n      ").append(q[0]).append(" | ").append(q[1])
            .append(": reference ").append(r).append(", emitted ").append(n);
      }
    }
    check("the oracle answers " + QUESTIONS.length + " questions as the reference does",
        disagreed.length() == 0);
    if (disagreed.length() > 0) {
      System.out.println("     " + disagreed);
    }

    // The positive control K-A8.1 exists for: the writer under the flag and the
    // version it was put back for. Nothing in the compiler runs this
    // combination yet, which is exactly why the gate has to.
    check("at (V52, COMPUTE_FRAMES) the writer produces a linkable class",
        attempt(() -> linkProbe(frameProbe(writer(now, COMPUTE_FRAMES))) == null));
    Throwable why = linkProbe(frameProbe(writer(now, COMPUTE_FRAMES)));
    if (why != null) {
      System.out.println("      " + why);
    }

    // ... and the control for that control. A frame probe that links whatever
    // the oracle says would make the check above decoration.
    check("the frame probe rejects a too-wide oracle (java/lang/Object)",
        linkProbe(frameProbe(new Widest())) instanceof VerifyError);
  }

  public static void main(String[] args) throws Exception {
    byte[] self = Files.readAllBytes(Path.of(args[0]));
    byte[] ddc = Files.readAllBytes(Path.of(args[1]));
    byte[] canary = Files.readAllBytes(Path.of(args[2]));
    byte[] selfWriter = Files.readAllBytes(Path.of(args[3]));
    byte[] ddcWriter = Files.readAllBytes(Path.of(args[4]));

    Class<?> ref = Class.forName(REF);
    System.out.println("reference " + ref.getName() + " from " + where(ref));
    System.out.printf("subject   self-emitted      %d B%n", self.length);
    System.out.printf("subject   reference-emitted %d B%n", ddc.length);
    System.out.printf("subject   %s self-emitted %d B, reference-emitted %d B%n", WRITER,
        selfWriter.length, ddcWriter.length);

    check("the reference carries the members this compiler does not emit",
        referenceIsForeign(ref));

    // Without this, a class-path shadow that silently stopped taking effect
    // would leave the two emissions identical and every check green, and the
    // decoupling below would be doing nothing at all.
    //
    // Against the *reference-emitted* subject, not the self-emitted one: both
    // sides of this comparison are shadow-emitted and differ only in the
    // shadow, so the two agree exactly when the mechanism is inert. Comparing
    // against the self-emitted subject instead would also go red whenever a
    // real defect happened to corrupt `plain` the same way the canary does --
    // a control that fires on the thing it is meant to be independent of.
    check("the class-path shadow is in effect (a doctored adapter changes the emission)",
        !Arrays.equals(ddc, canary));

    // Not a restatement of the differential: this compares the *emitted class
    // files*, so it also covers the case where today's `gen_asm_class` is
    // correct and the adapter that wrote the shipped copy -- inherited from the
    // previous generation -- is not.
    check("self-emitted and reference-emitted adapters are byte-identical",
        Arrays.equals(self, ddc));
    check("self-emitted and reference-emitted writers are byte-identical",
        Arrays.equals(selfWriter, ddcWriter));

    differential("self-emitted", ref, self);
    differential("reference-emitted", ref, ddc);
    oracle("self-emitted writer", ref, selfWriter);
    oracle("reference-emitted writer", ref, ddcWriter);

    if (failures > 0) {
      System.err.println("FAIL: " + failures + " difference(s); the emitted dawn/rt classes are "
          + "not a drop-in for dawn.tool.AdtClassWriter");
      System.exit(1);
    }
    System.out.println("OK: the emitted dawn/rt/Asm matches dawn.tool.AdtClassWriter on all "
        + "five entry points, and dawn/rt/AsmWriter on the common-superclass oracle");
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
