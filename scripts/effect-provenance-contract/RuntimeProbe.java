/* Exercise checkpoint identities independently of compiler-generated call
 * metadata. The expected prefixes live in runtime.py and are handwritten. */
import dawn.rt.Provenance;
import dawn.rt.PanicError;

public final class RuntimeProbe {
  private RuntimeProbe() {}
  private static void run(String mode) {
    long s = Provenance.open();
    if (mode.equals("cross_thread")) {
      final String[] message = {null};
      Thread worker = new Thread(() -> {
        try { Provenance.completed(s); }
        catch (PanicError error) { message[0] = error.getMessage(); }
      });
      worker.start();
      try { worker.join(); } catch (InterruptedException error) { throw new AssertionError(error); }
      Provenance.close(s, true);
      if (message[0] == null) throw new AssertionError("foreign context accepted");
      throw new PanicError(message[0]);
    }
    if (mode.equals("cleanup")) {
      Provenance.close(s, true);
      for (int i = 0; i < 1000; i++) {
        long id = Provenance.open();
        long token = Provenance.before(11, "helper"); Provenance.arrive("helper");
        String mark = Provenance.checkpoint(id);
        long nested = Provenance.before(12, "pure"); Provenance.arrive("pure"); Provenance.finish(nested, true);
        Provenance.rewind(id, mark); Provenance.finish(token, true);
        String prefix = Provenance.completed(id); Provenance.close(id, true);
        if (!prefix.startsWith("S\t")) throw new AssertionError("lost snapshot");
      }
      try {
        Class<?> sessions = Class.forName("dawn.rt.Provenance$Sessions");
        java.lang.reflect.Field registry = sessions.getDeclaredField("REGISTRY"); registry.setAccessible(true);
        java.lang.reflect.Field state = sessions.getDeclaredField("STATE"); state.setAccessible(true);
        java.lang.reflect.Field active = sessions.getDeclaredField("active"); active.setAccessible(true);
        if (!((java.util.Map<?, ?>)registry.get(null)).isEmpty()
            || ((ThreadLocal<?>)state.get(null)).get() != null || active.getInt(null) != 0)
          throw new AssertionError("observation resources survived scope exit");
      } catch (ReflectiveOperationException error) { throw new AssertionError(error); }
      System.out.println("clean"); return;
    }
    if (mode.equals("reuse")) {
      long f = Provenance.before(11, "helper"); Provenance.arrive("helper");
      String c = Provenance.checkpoint(s);
      long a = Provenance.before(12, "pure"); Provenance.arrive("pure"); Provenance.finish(a, true);
      Provenance.rewind(s, c);
      long b = Provenance.before(12, "pure"); Provenance.arrive("pure"); Provenance.finish(b, true);
      Provenance.rewind(s, c);
      String inner = Provenance.checkpoint(s);
      long q = Provenance.before(13, "query"); Provenance.arrive("query"); Provenance.finish(q, true);
      Provenance.rewind(s, inner); Provenance.rewind(s, c);
      Provenance.finish(f, true);
      System.out.println(Provenance.completed(s));
      Provenance.close(s, true); return;
    }
    String c = Provenance.checkpoint(s);
    if (mode.equals("invalidated")) {
      String later = Provenance.checkpoint(s); Provenance.rewind(s, c); Provenance.rewind(s, later);
    } else if (mode.equals("other")) {
      long other = Provenance.open(); Provenance.rewind(other, c);
    } else if (mode.equals("exited")) {
      Provenance.close(s, true); long other = Provenance.open(); Provenance.rewind(other, c);
    } else if (mode.equals("deeper")) {
      Provenance.before(11, "helper"); Provenance.arrive("helper"); Provenance.rewind(s, c);
    } else if (mode.equals("finished") || mode.equals("same_site")) {
      long f = Provenance.before(11, "helper"); Provenance.arrive("helper");
      c = Provenance.checkpoint(s); Provenance.finish(f, true);
      if (mode.equals("same_site")) { Provenance.before(11, "helper"); Provenance.arrive("helper"); }
      Provenance.rewind(s, c);
    } else { throw new AssertionError(mode); }
  }
  public static void main(String[] args) {
    try { run(args[0]); }
    catch (PanicError ex) { System.err.println("panic: " + ex.getMessage()); System.exit(1); }
  }
}
