// A declaration is not evidence that a program needs the continuation runtime.
// Inspect symbolic references in emitted program classes independently of the
// compiler's reachability answer; runtime classes do not justify themselves.
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

final class ControlFreightCheck {
  private static final List<String> RUNTIME =
      List.of("dawn/rt/Ctl", "dawn/rt/CtlCont", "dawn/rt/CtlK");

  static boolean check(Path root) throws Exception {
    boolean needed = false;
    try (var paths = Files.walk(root)) {
      for (Path p : paths.filter(f -> f.toString().endsWith(".class")).toList()) {
        String owner = root.relativize(p).toString().replace('\\', '/');
        if (RUNTIME.stream().anyMatch(n -> owner.equals(n + ".class"))) continue;
        for (var ref : AccessCheck.refs(Files.readAllBytes(p), true)) {
          if (RUNTIME.contains(ref.owner())) needed = true;
          for (String n : RUNTIME) {
            // CONSTANT_Class may name an array descriptor rather than a
            // bare class. Both it and real member descriptors carry types;
            // ordinary UTF8/string constants never reach this loop.
            if (ref.owner().startsWith("[") && ref.owner().contains("L" + n + ";")) needed = true;
            if (ref.desc() != null && ref.desc().contains("L" + n + ";")) needed = true;
          }
        }
      }
    }
    boolean ok = true;
    for (String name : RUNTIME) {
      boolean emitted = Files.isRegularFile(root.resolve(name + ".class"));
      if (emitted != needed) {
        System.err.println("CONTROL_FREIGHT FAIL: " + root + ": " + name
            + " emitted=" + emitted + ", live references=" + needed);
        ok = false;
      }
    }
    return ok;
  }

  public static void main(String[] args) throws Exception {
    for (String arg : args) {
      if (!check(Path.of(arg))) System.exit(1);
    }
    System.out.println("CONTROL_FREIGHT PASS: runtime follows emitted program references");
  }
}
