/* Keep unexpected writer failures distinct from capacity limits and preserve
 * the original Java cause across the language's rendered ForeignError bridge.
 * The public ASM boundary cannot supply a private rewrite input or opcode.
 */
package dawn.rt;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.Map;
import java.util.WeakHashMap;

public final class AsmDiagnostics {
  private AsmDiagnostics() {}
  private static final Map<Object, Context> CONTEXTS = Collections.synchronizedMap(new WeakHashMap<Object, Context>());

  public static final class Context {
    public final String owner, method, phase;
    public final Integer pc, opcode, operand;
    private final byte[] input;
    public Context(String owner, String method, String phase, Integer pc, Integer opcode, Integer operand, byte[] input) {
      this.owner = known(owner); this.method = known(method); this.phase = known(phase);
      this.pc = pc; this.opcode = opcode; this.operand = operand;
      this.input = input == null ? null : input.clone();
    }
  }

  public static final class Failure extends IllegalStateException {
    private Failure(String message, RuntimeException cause) { super(message, cause); }
  }

  private static String known(String value) { return value == null || value.isEmpty() ? "unknown" : value; }
  private static String number(Integer value) { return value == null ? "unknown" : value.toString(); }

  public static void attach(Object writer, String owner) {
    CONTEXTS.put(writer, new Context(owner, null, null, null, null, null, null));
  }

  public static RuntimeException failure(RuntimeException cause, Object writer) {
    if (cause instanceof Failure) return cause;
    Path directory = null;
    try {
      String selected = System.getProperty("dawn.jvm.diagnostics");
      if (selected != null && !selected.isEmpty()) directory = Paths.get(selected);
    } catch (RuntimeException selection) { cause.addSuppressed(selection); }
    return report(cause, CONTEXTS.get(writer), directory);
  }

  private static String stack(Throwable cause) {
    StringWriter text = new StringWriter(); cause.printStackTrace(new PrintWriter(text)); return text.toString();
  }

  private static String phase(RuntimeException cause, Context context) {
    if (!context.phase.equals("unknown")) return context.phase;
    for (StackTraceElement frame : cause.getStackTrace())
      if (frame.getClassName().equals("org.objectweb.asm.ClassWriter") && frame.getMethodName().equals("replaceAsmInstructions")) return "rewrite";
    return "serialization";
  }

  private static String details(RuntimeException cause, Context context) {
    return "JVM bytecode emission failed: class=" + context.owner + " method=" + context.method
        + " phase=" + phase(cause, context) + " pc=" + number(context.pc) + " opcode=" + number(context.opcode)
        + " operand=" + number(context.operand) + "; cause=" + cause.getClass().getName()
        + "; input=" + (context.input == null ? "unavailable" : "available");
  }

  private static String source(Class<?> type) {
    try { return type.getProtectionDomain().getCodeSource().getLocation().toString(); }
    catch (RuntimeException unavailable) { return "unknown"; }
  }

  private static String asmSource() {
    try { return source(Class.forName("org.objectweb.asm.ClassWriter")); }
    catch (ClassNotFoundException unavailable) { return "unknown"; }
  }

  private static String sha256(byte[] input) throws Exception {
    StringBuilder text = new StringBuilder();
    for (byte value : MessageDigest.getInstance("SHA-256").digest(input)) text.append(String.format("%02x", value & 255));
    return text.toString();
  }

  public static RuntimeException report(RuntimeException cause, Context supplied, Path directory) {
    if (cause instanceof Failure) return cause;
    Context context = supplied == null ? new Context(null, null, null, null, null, null, null) : supplied;
    String saved = "unavailable";
    if (directory != null) {
      try {
        String input = "unavailable";
        if (context.input != null) {
          Path bytes = Files.createTempFile(directory, "dawn-jvm-", ".class", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
          Files.write(bytes, context.input);
          input = bytes + " length=" + context.input.length + " sha256=" + sha256(context.input);
        }
        Path metadata = Files.createTempFile(directory, "dawn-jvm-", ".txt", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        Files.write(metadata, (details(cause, context) + "\ncompiler=" + source(AsmDiagnostics.class)
            + "\nasm=" + asmSource() + "\ninput=" + input + "\n" + stack(cause)).getBytes(StandardCharsets.UTF_8));
        saved = metadata.toString();
      } catch (Exception preservation) { cause.addSuppressed(preservation); }
    }
    return new Failure(details(cause, context) + "; diagnostic=" + saved + "\n" + stack(cause), cause);
  }
}
