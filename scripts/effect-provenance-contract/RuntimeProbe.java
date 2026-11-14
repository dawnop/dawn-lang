/* Exercise checkpoint identities independently of compiler-generated call
 * metadata. The expected prefixes live in runtime.py and are handwritten. */
import dawn.rt.Provenance;
import dawn.rt.PanicError;

public final class RuntimeProbe {
  private RuntimeProbe() {}
  private static final String HELPER="helper\t\t0\t1\tfunction\t101", PURE="pure\t\t0\t1\tfunction\t102", QUERY="query\t\t0\t1\tfunction\t103";
  private static final dawn.rt.Tuple2 TABLE = Provenance.table(
    new Object[]{ProbeTables.site(11,"helper"),ProbeTables.site(12,"pure"),ProbeTables.site(13,"query"),new dawn.rt.Tuple2(new dawn.rt.Tuple5(14L,0L,1L,0L,1L),new dawn.rt.Tuple5("pure","pure","","perform","Ask:ask"))},
    new Object[]{new dawn.rt.Tuple6(101L,"helper","",0L,1L,"function"),new dawn.rt.Tuple6(102L,"pure","",0L,1L,"function"),new dawn.rt.Tuple6(103L,"query","",0L,1L,"function")});
  private static long open() { return Provenance.open(TABLE); }
  private static void run(String mode) {
    long s = mode.startsWith("bounded_") ? Provenance.open(TABLE,1) : open();
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
        long id = open();
        long token = Provenance.before(11, "helper"); Provenance.arrive(HELPER);
        String mark = Provenance.checkpoint(id);
        long nested = Provenance.before(12, "pure"); Provenance.arrive(PURE); Provenance.finish(nested, true);
        Provenance.rewind(id, mark); Provenance.finish(token, true);
        String prefix = Provenance.renderSnapshot(Provenance.completed(id)); Provenance.close(id, true);
        if (!prefix.startsWith("S1\t")) throw new AssertionError("lost snapshot");
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
      long f = Provenance.before(11, "helper"); Provenance.arrive(HELPER);
          String c = Provenance.checkpoint(s);
      long a = Provenance.before(12, "pure"); Provenance.arrive(PURE); Provenance.finish(a, true);
      Provenance.rewind(s, c);
      long b = Provenance.before(12, "pure"); Provenance.arrive(PURE); Provenance.finish(b, true);
      Provenance.rewind(s, c);
      String inner = Provenance.checkpoint(s);
      long q = Provenance.before(13, "query"); Provenance.arrive(QUERY); Provenance.finish(q, true);
      Provenance.rewind(s, inner); Provenance.rewind(s, c);
      Provenance.finish(f, true);
      System.out.println(Provenance.renderSnapshot(Provenance.completed(s)));
      Provenance.close(s, true); return;
    }
    if (mode.equals("unknown")) {
      long f=Provenance.before(11,"helper"); Provenance.unknownContext(Provenance.context()); Provenance.finish(f,true);
      System.out.println(Provenance.renderSnapshot(Provenance.completed(s))); Provenance.close(s,true); return;
    }
    if (mode.startsWith("bounded_")) {
      long f=mode.equals("bounded_tail_epoch") ? Provenance.before(14,"pure\t\t0\t1\t0\t1\tperform\tAsk:ask") : Provenance.before(11,"helper"); Provenance.arrive(HELPER);
      String mark=Provenance.checkpoint(s);
      if (mode.equals("bounded_tail_epoch")) {
        long child=Provenance.before(12,"pure"); Provenance.arrive(PURE); Provenance.finish(child,true);
        Provenance.rewind(s,mark); Provenance.tail(14,"pure\t\t0\t1\t0\t1\tperform\tAsk:ask");
        String text=Provenance.renderOrigin(Provenance.origin(s));
        if(!text.contains("\nF\t1\t1\t2\t0\t0\t14\tpure")) throw new AssertionError(text);
        Provenance.finish(f,true); Provenance.close(s,true);
        System.out.println("1 2 original operation identity after rewind and tail"); return;
      }
      if (mode.equals("bounded_suspended")) {
        Object target=Provenance.capture(), driver=Provenance.mount(target);
        Provenance.before(12,"pure"); Provenance.arrive(PURE);
        Provenance.unmount(target,driver,false); Provenance.rewind(s,mark);
      }
      if (mode.equals("bounded_finished")) { Provenance.finish(f,true); Provenance.rewind(s,mark); }
      if (mode.equals("bounded_deeper")) { Provenance.before(12,"pure"); Provenance.arrive(PURE); Provenance.rewind(s,mark); }
      for (int i=0;i<2;i++) {
        long child=Provenance.before(12,"pure"); Provenance.arrive(PURE); Provenance.finish(child,true); Provenance.rewind(s,mark);
      }
      Provenance.finish(f,true);
      System.out.println(Provenance.renderSnapshot(Provenance.completed(s))); Provenance.close(s,true); return;
    }
    String c = Provenance.checkpoint(s);
    if (mode.equals("invalidated")) {
      String later = Provenance.checkpoint(s); Provenance.rewind(s, c); Provenance.rewind(s, later);
    } else if (mode.equals("other")) {
      long other = open(); Provenance.rewind(other, c);
    } else if (mode.equals("exited")) {
      Provenance.close(s, true); long other = open(); Provenance.rewind(other, c);
    } else if (mode.equals("deeper")) {
      Provenance.before(11, "helper"); Provenance.arrive(HELPER); Provenance.rewind(s, c);
    } else if (mode.equals("finished") || mode.equals("same_site")) {
      long f = Provenance.before(11, "helper"); Provenance.arrive(HELPER);
      c = Provenance.checkpoint(s); Provenance.finish(f, true);
      if (mode.equals("same_site")) { Provenance.before(11, "helper"); Provenance.arrive(HELPER); }
      Provenance.rewind(s, c);
    } else { throw new AssertionError(mode); }
  }
  public static void main(String[] args) {
    try { run(args[0]); }
    catch (PanicError ex) { System.err.println("panic: " + ex.getMessage()); System.exit(1); }
  }
}
