// The classfile gate's loader (TEST-01): force-link every emitted class so
// the JVM's bytecode verifier sees every method body now, not at first use.
//
// Read the coverage claim narrowly. Forcing a class to link runs the bytecode
// verifier over its method bodies -- that and only that. It is not a check
// that the class would run: the JVM resolves a symbolic reference when the
// instruction naming it first executes, so nothing here says the members a
// body reaches for exist or may be reached. AccessCheck.java, run as pass 2
// from main below, is what covers that; this file's number covers structural
// legality of the bytes.
//
// The gap was not theoretical. K-A3 emitted hoisted lambda bodies ACC_PRIVATE
// and this gate printed "1946 classes, 0 illegal" over a corpus whose first
// real run died of IllegalAccessError inside std.io.read_file. The header
// this replaces said the gate covered link-time errors, and a reader had no
// way to tell that "link" here meant verification and not resolution.
//
// Why this shape: differential testing proves the two backends agree, not
// that either is legal -- and lazy linking means a class no test touches is
// never verified at all. CheckClassAdapter would be the emission-time
// equivalent, but the vendored ASM carries only the core writer (asm-util's
// verifier is a separate artifact, and AdtClassWriter's source is archived
// with kotlin-final), while the real verifier ships in every JVM.
//
// The -Xverify family is not an alternative and was measured, not assumed: on
// JDK 21 -Xverify:all, :none (deprecated, still accepted) and :remote all
// leave the private-member mutant green, because verification is a different
// phase from resolution. jdeps has no access mode left either -- the old
// hidden -verify:access is gone, and `jdeps -v` reports the pkgB -> pkgA edge
// with exit 0.
//
// Class.forName with initialize=true is what forces linking; a Dawn class's
// static initializer only materialises comptime constants, so initialising
// is safe. VerifyError and ClassFormatError are the gate; any other linkage
// noise (a class referencing an optional dependency that is not on this
// class path) is reported but not fatal -- absence of a jar is not illegal
// bytecode.
//
// The loader is child-first, and that is not a detail. The toolchain jar has
// to be on the parent class path (selfhost's own classes reference vendored
// ASM and coursier types), but the selfhost corpus emits classes with exactly
// the names that jar already holds -- `std.cursor`, `emit`, `main`. Under the
// default parent-first delegation every one of them resolved out of the jar
// and the directory this gate was pointed at was never read: for that corpus
// the check could not fail no matter what `__emit` wrote. Demonstrated by
// corrupting one reachable instruction in an emitted class -- parent-first
// passed it, child-first reports the VerifyError.
//
// How that was found is worth keeping, because reading this file will not
// find it: nobody reviewed the delegation order. The mutation was built for
// an unrelated question (does the pre-50 verifier walk unreachable code?),
// and the mutant that was supposed to fail -- one reachable instruction
// replaced by athrow -- came back green. The gate, not the mutation, was
// the bug.
//
// And the counter-intuitive part, for whoever reads the fix in git history
// and asks why a repaired gate caught nothing new: after the switch to
// child-first the corpora still report 1946 classes, 0 illegal. Exactly the
// numbers from before. That is not a disappointing fix, it is the evidence
// -- a gate that has never let anything through and a gate that has never
// looked at anything print the same output, and no amount of green
// distinguishes them. Only a mutant does. So when this gate is changed,
// re-run the red demo; its passing count proves nothing on its own.
//
// That rule is no longer a note to the reader: selftest.sh holds the mutants
// and run.sh executes it before it emits anything, so the demo is re-run by
// construction. It also pins the blind spot above -- one of its four fixtures
// asserts that pass 1 still calls the private-member mutant legal.
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.stream.Collectors;
import java.util.stream.Stream;

public class Verify {
  /** Prefers the emitted directory over the parent, except for the JDK itself. */
  static final class EmittedFirst extends URLClassLoader {
    EmittedFirst(URL[] urls, ClassLoader parent) {
      super(urls, parent);
    }

    @Override
    protected Class<?> loadClass(String name, boolean resolve) throws ClassNotFoundException {
      synchronized (getClassLoadingLock(name)) {
        Class<?> c = findLoadedClass(name);
        if (c == null
            && !name.startsWith("java.")
            && !name.startsWith("jdk.")
            && !name.startsWith("sun.")) {
          try {
            c = findClass(name);
          } catch (ClassNotFoundException notEmitted) {
            // vendored ASM, coursier, anything else: the parent has it
          }
        }
        if (c == null) {
          c = super.loadClass(name, false);
        }
        if (resolve) {
          resolveClass(c);
        }
        return c;
      }
    }
  }

  public static void main(String[] args) throws Exception {
    Path dir = Path.of(args[0]);
    EmittedFirst cl =
        new EmittedFirst(new URL[] {dir.toUri().toURL()}, Verify.class.getClassLoader());
    List<String> names;
    try (Stream<Path> walk = Files.walk(dir)) {
      names = walk.filter(p -> p.toString().endsWith(".class"))
          .map(p -> dir.relativize(p).toString())
          .map(s -> s.substring(0, s.length() - ".class".length()).replace('/', '.'))
          .sorted()
          .collect(Collectors.toList());
    }
    int bad = 0;
    int linked = 0;
    int skipped = 0;
    for (String n : names) {
      try {
        Class.forName(n, true, cl);
        linked++;
      } catch (VerifyError | ClassFormatError e) {
        System.err.println("VERIFY FAIL " + n + ": " + e);
        bad++;
      } catch (Throwable t) {
        // NoClassDefFound for an optional dep, an initializer that needs the
        // world -- not a verdict on the bytecode itself
        System.err.println("note " + n + ": " + t);
        skipped++;
      }
    }
    System.out.println(linked + " classes verified, " + skipped + " not initializable, "
        + bad + " illegal");

    // Pass 2. Linking is not resolution: the references inside a method body
    // are checked when that instruction first runs, so pass 1 above says
    // nothing about them. See AccessCheck's header for what this covers.
    AccessCheck.Result r = new AccessCheck.Result();
    AccessCheck.scan(dir, cl, names, r);
    for (String note : r.unknownNotes) {
      System.err.println("note " + note);
    }
    for (String f : r.failures) {
      System.err.println(f);
    }
    System.out.println(r.classesScanned + " classes scanned, " + r.refsChecked
        + " references resolved, " + r.pruned + " freight-pruned, " + r.unknown + " unknown, "
        + r.failures.size() + " inaccessible");
    if (bad > 0 || !r.failures.isEmpty()) {
      System.exit(1);
    }
  }
}
