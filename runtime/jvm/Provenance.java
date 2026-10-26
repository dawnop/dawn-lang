/* Observation is an invocation protocol independent of lexical effect
 * evidence. Only active scopes live in the owner registry; exported Origins
 * and completed prefixes are immutable strings, not mutable frame handles.
 * The compiler embeds deterministic class bytes generated from this source. */
package dawn.rt;

import java.util.ArrayList;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

public final class Provenance {
  private Provenance() {}
  private static volatile boolean enabled;
  private static final class Sessions {
    static final AtomicLong SCOPES = new AtomicLong(1);
    static final AtomicLong TOKENS = new AtomicLong(1);
    static final ConcurrentHashMap<Long, Scope> REGISTRY = new ConcurrentHashMap<>();
    static final ThreadLocal<State> STATE = new ThreadLocal<>();
    static int active;
  }

  private static final class State {
    Scope active;
    Invocation current;
  }
  private static final class Frame {
    long id, epoch, parent, site;
    String metadata, definition = "";
    int status;
    Frame(long id, long epoch, long parent, long site, String metadata) {
      this.id = id; this.epoch = epoch; this.parent = parent;
      this.site = site; this.metadata = metadata;
    }
  }
  private static final class Mark {
    long frame;
    int boundary, noteBoundary;
    boolean valid = true;
    Mark(long frame, int boundary, int noteBoundary) {
      this.frame = frame; this.boundary = boundary; this.noteBoundary = noteBoundary;
    }
  }
  private static final class Scope {
    final long id = Sessions.SCOPES.getAndIncrement();
    final Thread owner = Thread.currentThread();
    final Scope outer;
    long epoch = 1, current;
    final ArrayList<Frame> frames = new ArrayList<>();
    final ArrayList<Integer> view = new ArrayList<>();
    final ArrayList<Mark> marks = new ArrayList<>();
    final ArrayList<Integer> markStack = new ArrayList<>();
    final ArrayList<String> notes = new ArrayList<>();
    Scope(Scope outer) { this.outer = outer; append(0, ""); }
    long append(long site, String metadata) {
      long id = frames.size() + 1L;
      frames.add(new Frame(id, epoch, current, site, metadata));
      view.add(frames.size() - 1); current = id; return id;
    }
    Frame frame(long id) { return frames.get(Math.toIntExact(id - 1)); }
  }
  private static final class Entry {
    final Scope scope;
    final long frame, parent;
    Entry(Scope scope, long frame, long parent) {
      this.scope = scope; this.frame = frame; this.parent = parent;
    }
  }
  private static final class Invocation {
    final long token = Sessions.TOKENS.getAndIncrement();
    final long site;
    final String metadata;
    final Invocation parent;
    final ArrayList<Entry> entries = new ArrayList<>();
    boolean arrived;
    long callbackSite; String callbackMetadata;
    Invocation(long site, String metadata, Invocation parent) {
      this.site = site; this.metadata = metadata; this.parent = parent;
      callbackSite = site; callbackMetadata = metadata;
    }
  }
  private static void fail(String message) { throw new PanicError(message); }
  private static Scope scope(long id) {
    Scope s = Sessions.REGISTRY.get(id);
    if (s == null) fail("provenance: scope has exited");
    if (s.owner != Thread.currentThread()) fail("provenance: different execution context");
    return s;
  }
  private static abstract class Callback {
    final Object body; final long site, owner; final String metadata;
    Callback(Object body, long site, String metadata) {
      State state = Sessions.STATE.get();
      if (state == null || state.active == null) fail("provenance: callback is outside observation");
      if (site < 0) {
        if (state.current == null) fail("provenance: callback has no initiating invocation");
        site = state.current.callbackSite; metadata = state.current.callbackMetadata;
      }
      this.body = body; this.site = site; this.metadata = metadata; owner = state.active.id;
    }
    long enter() { scope(owner); return before(site, metadata); }
  }
  private static final class Callback1 extends Callback implements Fn1 {
    Callback1(Object body, long site, String metadata) { super(body, site, metadata); }
    public Object apply(Object a0) {
      long token = enter(); boolean normal = false;
      try { Object value = ((Fn1)body).applyObserved(a0, 0L); normal = true; return value; }
      finally { finish(token, normal); }
    }
    public Object applyObserved(Object a0, long context) { return apply(a0); }
  }
  private static final class Callback2 extends Callback implements Fn2 {
    Callback2(Object body, long site, String metadata) { super(body, site, metadata); }
    public Object apply(Object a0, Object a1) {
      long token = enter(); boolean normal = false;
      try { Object value = ((Fn2)body).applyObserved(a0, a1, 0L); normal = true; return value; }
      finally { finish(token, normal); }
    }
    public Object applyObserved(Object a0, Object a1, long context) { return apply(a0, a1); }
  }
  public static Object callback(Object body, long arity, long site, String metadata) {
    if (arity == 1) return new Callback1(body, site, metadata);
    if (arity == 2) return new Callback2(body, site, metadata);
    fail("provenance: unsupported runtime callback arity"); return null;
  }
  public static void checkFunction(Object function) {
    if (function.getClass().getName().equals("dawn.rt.CtlK")) unsupported("control operations");
  }
  public static Object observe(Object body, Object evidence, long site, String metadata) {
    long s = open();
    long token = before(site, metadata);
    boolean normal = false;
    try {
      Object result = ((Fn2) body).applyObserved(Long.valueOf(s), evidence, 0L);
      normal = true;
      return result;
    } finally {
      finish(token, normal);
      close(s, normal);
    }
  }
  public static long before(long site, String metadata) {
    if (!enabled) return 0;
    State state = Sessions.STATE.get();
    if (state == null || state.active == null) return 0;
    Invocation v = new Invocation(site, metadata, state.current);
    for (Scope s = state.active; s != null; s = s.outer) {
      long parent = s.current;
      v.entries.add(new Entry(s, s.append(site, metadata), parent));
    }
    state.current = v; return v.token;
  }
  public static long beforeAt(long site, String metadata, long callbackSite, String callbackMetadata) {
    long token = before(site, metadata);
    if (token != 0) {
      Invocation current = Sessions.STATE.get().current;
      current.callbackSite = callbackSite; current.callbackMetadata = callbackMetadata;
    }
    return token;
  }
  public static long arrive(String definition) {
    if (!enabled) return 0;
    State state = Sessions.STATE.get();
    if (state == null || state.active == null) return 0;
    long created = 0;
    if (state.current == null || state.current.arrived) {
      // Emitter-owned calls without a source-bearing Core node must not
      // inherit a written caller's Site and pretend it was their own.
      created = before(0, "\t\t-1\t-1\t-1\t-1\tunknown\t");
    }
    Invocation v = state.current; v.arrived = true;
    for (Entry e : v.entries) e.scope.frame(e.frame).definition = definition;
    return created;
  }
  public static void finish(long token, boolean normal) {
    if (token == 0) return;
    State state = Sessions.STATE.get(); Invocation v = state.current;
    if (v == null || v.token != token) fail("provenance: invocation closed out of order");
    for (Entry e : v.entries) {
      Frame r = e.scope.frame(e.frame);
      if (r.status != 0) fail("provenance: frame closed twice");
      r.status = normal ? 1 : 2; e.scope.current = e.parent;
    }
    state.current = v.parent;
  }
  public static long open() {
    State state = Sessions.STATE.get();
    if (state == null) { state = new State(); Sessions.STATE.set(state); }
    Scope s = new Scope(state.active);
    Sessions.REGISTRY.put(s.id, s); state.active = s;
    synchronized (Sessions.class) { Sessions.active++; enabled = true; }
    return s.id;
  }
  public static void close(long id, boolean normal) {
    State state = Sessions.STATE.get(); Scope s = scope(id);
    if (s != state.active || s.current != 1)
      fail("provenance: scope closed with active calls");
    s.frames.get(0).status = normal ? 1 : 2;
    state.active = s.outer; Sessions.REGISTRY.remove(id);
    if (state.active == null) Sessions.STATE.remove();
    synchronized (Sessions.class) { Sessions.active--; enabled = Sessions.active != 0; }
  }
  public static String checkpoint(long id) {
    Scope s = scope(id);
    s.marks.add(new Mark(s.current, s.view.size(), s.notes.size()));
    s.markStack.add(s.marks.size() - 1);
    return id + ":" + s.marks.size();
  }
  public static void rewind(long id, String checkpoint) {
    String[] parts = checkpoint.split(":", -1);
    long owner; int ordinal;
    try {
      if (parts.length != 2) { fail("provenance: invalid checkpoint"); return; }
      owner = Long.parseLong(parts[0]); ordinal = Integer.parseInt(parts[1]);
    } catch (NumberFormatException ex) { fail("provenance: invalid checkpoint"); return; }
    Scope s = scope(owner);
    if (owner != id) fail("provenance: checkpoint belongs to another scope");
    if (ordinal < 1 || ordinal > s.marks.size()) fail("provenance: invalid checkpoint");
    Mark c = s.marks.get(ordinal - 1);
    Frame f = s.frame(c.frame);
    if (f.status != 0) fail("provenance: creating frame has finished");
    if (!c.valid) fail("provenance: checkpoint has been invalidated");
    if (s.current != c.frame) fail("provenance: not in the creating frame");
    while (!s.markStack.isEmpty() && s.markStack.get(s.markStack.size() - 1) != ordinal - 1)
      s.marks.get(s.markStack.remove(s.markStack.size() - 1)).valid = false;
    s.view.subList(c.boundary, s.view.size()).clear();
    s.notes.subList(c.noteBoundary, s.notes.size()).clear();
    s.epoch++;
  }
  private static void record(StringBuilder b, Scope s, Frame r) {
    b.append("F\t").append(s.id).append('\t').append(r.epoch).append('\t')
      .append(r.id).append('\t').append(r.parent).append('\t').append(r.status)
      .append('\t').append(r.site).append('\t').append(r.metadata).append('\t').append(r.definition);
  }
  // Reserve once before copying immutable snapshot text. Geometric growth
  // otherwise retains multiple large buffers during a recording's GC cycle.
  private static long recordCapacity(Frame r) {
    return 129L + r.metadata.length() + r.definition.length();
  }
  private static int textCapacity(long chars) {
    return (int)Math.min(chars, Integer.MAX_VALUE - 8L);
  }
  public static String origin(long id) {
    Scope s = scope(id); Invocation operation = Sessions.STATE.get().current;
    while (operation != null && !operation.metadata.contains("\tperform\t")) operation = operation.parent;
    if (operation == null) fail("provenance: no operation origin");
    long sender = 0;
    for (Entry e : operation.entries) if (e.scope == s) sender = e.frame;
    if (sender == 0) fail("provenance: operation is outside the observation scope");
    long chars = 32L + operation.metadata.length();
    for (long parent = sender; parent != 0; parent = s.frame(parent).parent)
      chars += 1 + recordCapacity(s.frame(parent));
    StringBuilder b = new StringBuilder(textCapacity(chars));
    b.append("O\t").append(operation.site).append('\t').append(operation.metadata);
    while (sender != 0) {
      Frame r = s.frame(sender); b.append('\n');
      if (sender == s.current) {
        Frame envelope = new Frame(r.id, r.epoch, r.parent, r.site, r.metadata);
        record(b, s, envelope);
      } else { record(b, s, r); }
      sender = r.parent;
    }
    return b.toString();
  }
  private static String unescape(String value) {
    if (value.indexOf('%') < 0) return value;
    StringBuilder out = new StringBuilder();
    for (int i = 0; i < value.length(); i++) {
      char c = value.charAt(i);
      if (c == '%') {
        if (i + 2 >= value.length()) fail("provenance: invalid Origin");
        String code = value.substring(i + 1, i + 3);
        if (code.equals("25")) c = '%';
        else if (code.equals("09")) c = '\t';
        else if (code.equals("0A")) c = '\n';
        else if (code.equals("0D")) c = '\r';
        else if (code.equals("00")) c = 0;
        else fail("provenance: invalid Origin");
        i += 2;
      }
      out.append(c);
    }
    return out.toString();
  }
  // These accessors read snapshot bytes only, including after scope exit.
  public static String field(String origin, long index) {
    int header = origin.indexOf('\n');
    if (!origin.startsWith("O\t") || header < 0) fail("provenance: invalid Origin");
    if (index == -1) return unescape(origin.substring(origin.lastIndexOf('\t', header) + 1, header));
    if (index < 0) fail("provenance: invalid Origin field index");
    int start = header + 1, end = origin.indexOf('\n', start);
    if (end < 0) end = origin.length();
    if (!origin.startsWith("F\t", start)) fail("provenance: invalid Origin");
    for (long i = 0; i < index; i++) {
      int tab = origin.indexOf('\t', start);
      if (tab < 0 || tab >= end) return "";
      start = tab + 1;
    }
    int tab = origin.indexOf('\t', start);
    return unescape(origin.substring(start, tab >= 0 && tab < end ? tab : end));
  }
  public static long number(String origin, long index) {
    String value = field(origin, index);
    if (value.isEmpty()) return -1;
    try { return Long.parseLong(value); }
    catch (NumberFormatException invalid) { fail("provenance: invalid Origin"); return 0; }
  }
  public static String parent(String origin) {
    field(origin, 0);
    int header = origin.indexOf('\n'), next = origin.indexOf('\n', header + 1);
    if (next < 0 || next + 1 == origin.length()) return "";
    return origin.substring(0, header + 1) + origin.substring(next + 1);
  }
  public static void note(long id, String origin) { scope(id).notes.add(origin); }
  public static String completed(long id) {
    Scope s = scope(id);
    long chars = 48;
    for (int index : s.view) chars += 1 + recordCapacity(s.frames.get(index));
    for (String note : s.notes) chars += 2L + note.length();
    StringBuilder b = new StringBuilder(textCapacity(chars));
    b.append("S\t").append(s.id).append('\t').append(s.epoch);
    for (int index : s.view) { b.append('\n'); record(b, s, s.frames.get(index)); }
    for (String note : s.notes) b.append("\n\n").append(note);
    return b.toString();
  }
  public static void unsupported(String boundary) {
    if (!enabled) return;
    State state = Sessions.STATE.get();
    if (state != null && state.active != null)
      fail("provenance: " + boundary + " under observation is not supported in W2");
  }
}
