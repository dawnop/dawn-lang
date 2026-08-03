// The classfile gate's loader (TEST-01): force-link every emitted class so
// the JVM's bytecode verifier sees every method body now, not at first use.
//
// Why this shape: differential testing proves the two backends agree, not
// that either is legal -- and lazy linking means a class no test touches is
// never verified at all. CheckClassAdapter would be the emission-time
// equivalent, but the vendored ASM carries only the core writer (asm-util's
// verifier is a separate artifact, and AdtClassWriter's source is archived
// with kotlin-final), while the real verifier ships in every JVM.
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
    if (bad > 0) {
      System.exit(1);
    }
  }
}
