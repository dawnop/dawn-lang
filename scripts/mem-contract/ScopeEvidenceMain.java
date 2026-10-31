// Invoke the class produced by Dawn's emitter, not a Java lookup substitute.
public final class ScopeEvidenceMain {
  public static void main(String[] args) throws Exception {
    long actual = (long) Class.forName("ScopeEvidenceProbe").getMethod("read").invoke(null);
    if (actual != 112233L) throw new AssertionError("scoped evidence selected " + actual);
    System.out.println("PASS  JVM evidence domains, append and fresh instances");
  }
}
