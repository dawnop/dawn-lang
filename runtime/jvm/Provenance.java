/* Observation is an invocation protocol independent of lexical effect
 * evidence. Only active scopes live in the owner registry; exported Origins
 * and completed prefixes are frozen values, not mutable frame handles.
 * The compiler embeds deterministic class bytes generated from this source. */
package dawn.rt;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.Arrays;
import java.lang.ref.WeakReference;
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
    Object owner = new Object();
    Invocation current, pending;
    boolean controlCallback;
  }
  private static final class Frame {
    long id, epoch, parent, site;
    long definition = -1;
    int status, boundary;
    Frame(long id, long epoch, long parent, long site) {
      this.id = id; this.epoch = epoch; this.parent = parent;
      this.site = site;
    }
  }
  private static final class Mark {
    long frame, logicalBoundary;
    Invocation creator;
    int boundary, noteBoundary;
    boolean valid = true;
    Mark(long frame, int boundary, int noteBoundary, Invocation creator, long logicalBoundary) {
      this.frame = frame; this.boundary = boundary; this.noteBoundary = noteBoundary;
      this.creator = creator; this.logicalBoundary = logicalBoundary; retain(creator);
    }
  }
  /* Primitive chunks avoid per-record objects, boxed view indices and bulk
   * relocation. Artifact-local slots refer to emitted immutable Site/definition data. */
  private static final class RecordChunk {
    final long[] epoch = new long[256], parent = new long[256], site = new long[256], definition = new long[256];
    final int[] status = new int[256], boundary = new int[256];
  }
  private static final class Records {
    final ArrayList<RecordChunk> chunks = new ArrayList<>(); int size;
    int size() { return size; }
    RecordChunk chunk(long id) { return chunks.get(Math.toIntExact((id - 1) / 256)); }
    int offset(long id) { return (int)((id - 1) % 256); }
    void add(Frame r) {
      if (size / 256 == chunks.size()) chunks.add(new RecordChunk());
      RecordChunk c = chunks.get(size / 256); int i = size++ % 256;
      c.epoch[i] = r.epoch; c.parent[i] = r.parent; c.site[i] = r.site;
      c.status[i] = r.status; c.boundary[i] = r.boundary; c.definition[i] = r.definition;
    }
    long append(long epoch, long parent, long site, String metadata) {
      if (size / 256 == chunks.size()) chunks.add(new RecordChunk());
      RecordChunk c = chunks.get(size / 256); int i = size++ % 256;
      c.epoch[i] = epoch; c.parent[i] = parent; c.site[i] = site;
      c.status[i] = 0; c.definition[i] = -1;
      return size;
    }
    Frame get(int index) {
      long id = index + 1L; RecordChunk c = chunk(id); int i = offset(id);
      Frame r = new Frame(id, c.epoch[i], c.parent[i], c.site[i]);
      r.status = c.status[i]; r.boundary = c.boundary[i]; r.definition = c.definition[i]; return r;
    }
  }
  private static final class Indices {
    final ArrayList<int[]> chunks = new ArrayList<>(); int size;
    int size() { return size; }
    void add(int value) {
      if (size / 256 == chunks.size()) chunks.add(new int[256]);
      chunks.get(size / 256)[size++ % 256] = value;
    }
    int get(int i) { return chunks.get(i / 256)[i % 256]; }
    void truncate(int boundary) { size = boundary; }
  }
  private static final class ActivationRef extends WeakReference<Activation> {
    long suspendedMaximum;
    ActivationRef(Activation a) { super(a); }
  }
  private static final class Scope {
    final long id = Sessions.SCOPES.getAndIncrement();
    final Object owner; final Scope outer;
    long epoch = 1, current, recordedCurrent, nextInstance = 1, unresumed;
    final long capacity; long notesWritten; int completeness;
    final Tuple2 table;
    final Records frames = new Records(); final Indices view = new Indices();
    final ArrayList<Mark> marks = new ArrayList<>();
    final ArrayList<ActivationRef> activations = new ArrayList<>();
    final ArrayList<Integer> markStack = new ArrayList<>();
    final ArrayList<Tuple4> notes = new ArrayList<>();
    final ArrayList<WeakReference<Invocation>[]> pool = new ArrayList<>();
    Invocation free;
    Scope(Scope outer, Tuple2 table, long capacity) {
      this.outer = outer; this.table = table; this.capacity = capacity;
      owner = Sessions.STATE.get().owner; append(-1, "");
    }
    long append(long site, String metadata) {
      long id = nextInstance++;
      if (frames.size() < capacity) {
        frames.append(epoch, current, site, metadata);
        view.add(frames.size() - 1); recordedCurrent = id;
      } else completeness = 1;
      current = id; return id;
    }
    boolean recorded(long id) { return id > 0 && id <= frames.size(); }
    Frame frame(long id) { return frames.get(Math.toIntExact(id - 1)); }
    int status(long id) { return frames.chunk(id).status[frames.offset(id)]; }
    void status(long id, int status) { frames.chunk(id).status[frames.offset(id)] = status; }
    long parent(long id) { return frames.chunk(id).parent[frames.offset(id)]; }
    long definition(long id) { return frames.chunk(id).definition[frames.offset(id)]; }
    void definition(long id, long value) { frames.chunk(id).definition[frames.offset(id)] = value; }
    @SuppressWarnings("unchecked") Invocation take() {
      if (free == null) {
        // Weak occupied slots let a naturally abandoned JVM continuation be
        // collected even while its observation is still live. Active leases
        // keep their own strong references and are never overwritten.
        for (WeakReference<Invocation>[] block : pool)
          for (int i = 0; i < block.length; i++) if (block[i].get() == null) {
            Invocation v = new Invocation(this); block[i] = new WeakReference<>(v);
            v.next = free; free = v;
          }
        if (free == null) {
          WeakReference<Invocation>[] block = new WeakReference[128];
          for (int i = 0; i < block.length; i++) {
            Invocation v = new Invocation(this); block[i] = new WeakReference<>(v);
            v.next = free; free = v;
          }
          pool.add(block);
        }
      }
      Invocation v = free; free = v.next; v.next = null; return v;
    }
  }
  private static final class Entry {
    Scope scope; long frame, parent, recordedParent, tip, epoch, logicalTip;
    RecordChunk chunk; int offset;
    // Chunks never move. Keep the location of this same live record, rather
    // than resolving its identity again at every arrive and normal return.
    void set(Scope scope, long frame, long parent, long recordedParent) {
      this.scope = scope; this.frame = frame; this.parent = parent;
      this.recordedParent = recordedParent; epoch = scope.epoch; logicalTip = frame;
      tip = scope.recorded(frame) ? frame : 0;
      chunk = tip == 0 ? null : scope.frames.chunk(frame);
      offset = tip == 0 ? 0 : scope.frames.offset(frame);
    }
    void clear() { scope = null; chunk = null; }
  }
  private static final class Invocation {
    final Scope poolOwner;
    long token, site, callbackSite; String metadata, callbackMetadata;
    Invocation parent, next; Entry[] entries = { new Entry() }; int count, refs; boolean arrived, finished, suspended;
    Invocation(Scope owner) { poolOwner = owner; }
    void initialize(long site, String metadata, Invocation parent, int count) {
      token = Sessions.TOKENS.getAndIncrement(); refs = 1; arrived = finished = suspended = false;
      this.site = site; this.metadata = metadata; this.parent = parent; retain(parent);
      callbackSite = site; callbackMetadata = metadata; this.count = count;
      if (entries.length < count) {
        entries = new Entry[count]; for (int i = 0; i < count; i++) entries[i] = new Entry();
      }
    }
  }
  private static void retain(Invocation v) { if (v != null) v.refs++; }
  private static void drop(Invocation v) {
    while (v != null && --v.refs == 0) {
      Invocation parent = v.parent; v.parent = null; v.metadata = v.callbackMetadata = null;
      for (int i = 0; i < v.count; i++) v.entries[i].clear();
      v.count = 0; v.next = v.poolOwner.free; v.poolOwner.free = v; v = parent;
    }
  }
  private static void retainState(State state) { if (state != null) { retain(state.current); retain(state.pending); } }
  private static void dropState(State state) { if (state != null) { drop(state.current); drop(state.pending); } }
  private static void fail(String message) { throw new PanicError(message); }
  private static Scope scope(long id) {
    Scope s = Sessions.REGISTRY.get(id);
    if (s == null) fail("provenance: scope has exited");
    State state = Sessions.STATE.get();
    if (state == null || s.owner != state.owner) fail("provenance: different execution context");
    return s;
  }
  private static Scope leaseScope(long id) {
    State state = Sessions.STATE.get();
    if (state != null) for (Scope s = state.active; s != null; s = s.outer) if (s.id == id) {
      if (s.owner != state.owner) fail("provenance: different execution context"); return s;
    }
    return scope(id);
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
    long enter() { leaseScope(owner); return beforeContext(context(), site, metadata); }
  }
  private static final class Callback1 extends Callback implements Fn1 {
    Callback1(Object body, long site, String metadata) { super(body, site, metadata); }
    public Object apply(Object a0) {
      long token = enter(); boolean normal = false; Throwable failure=null;
      try { Object value = ((Fn1)body).applyObserved(a0, 0L); normal = true; return value; }
      catch (Throwable error) { failure=error; throw error; }
      finally { if (failure==null) finish(token,normal); else failureContext(context(),token,failure); }
    }
    public Object applyObserved(Object a0, long context) { return apply(a0); }
  }
  private static final class Callback2 extends Callback implements Fn2 {
    Callback2(Object body, long site, String metadata) { super(body, site, metadata); }
    public Object apply(Object a0, Object a1) {
      long token = enter(); boolean normal = false; Throwable failure=null;
      try { Object value = ((Fn2)body).applyObserved(a0, a1, 0L); normal = true; return value; }
      catch (Throwable error) { failure=error; throw error; }
      finally { if (failure==null) finish(token,normal); else failureContext(context(),token,failure); }
    }
    public Object applyObserved(Object a0, Object a1, long context) { return apply(a0, a1); }
  }
  public static Object callback(Object body, long arity, long site, String metadata) {
    if (arity == 1) return new Callback1(body, site, metadata);
    if (arity == 2) return new Callback2(body, site, metadata);
    fail("provenance: unsupported runtime callback arity"); return null;
  }
  public static void checkFunction(Object function) {}
  public static Object observe(Object body, long capacity, Object evidence, long site, String metadata, Tuple2 table) {
    long s = open(table, capacity);
    long token = beforeContext(context(), site, metadata);
    boolean normal = false; Throwable failure=null;
    try {
      Object result = ((Fn2) body).applyObserved(Long.valueOf(s), evidence, 0L);
      normal = true;
      return result;
    } catch (Throwable error) { failure=error; throw error; }
    finally {
      try { if (failure==null) finish(token,normal); else failureContext(context(),token,failure); }
      finally { close(s,normal); }
    }
  }
  public static Object context() { return Sessions.STATE.get(); }
  public static long before(long site, String metadata) {
    State state = Sessions.STATE.get(); if (state == null || state.active == null) return 0;
    int slot = siteIndex(state.active.table,site);
    return beforeContext(state, slot, metadata);
  }
  public static long beforeContext(Object context, long site, String metadata) {
    State state = (State) context; if (state == null || state.active == null) return 0;
    int count = 0; for (Scope s = state.active; s != null; s = s.outer) count++;
    Invocation v = state.active.take(); v.initialize(site, metadata, state.current, count);
    int i = 0;
    for (Scope s = state.active; s != null; s = s.outer) {
      long parent = s.current, recordedParent = s.recordedCurrent;
      v.entries[i++].set(s, s.append(site, metadata), parent, recordedParent);
    }
    state.current = v; return v.token;
  }
  public static long beforeAt(long site, String metadata, long callbackSite, String callbackMetadata) {
    State state = Sessions.STATE.get(); if (state == null || state.active == null) return 0;
    int a = siteIndex(state.active.table,site),b = siteIndex(state.active.table,callbackSite);
    return beforeAtContext(state, a, metadata, b, callbackMetadata);
  }
  public static long beforeAtContext(Object context, long site, String metadata, long callbackSite, String callbackMetadata) {
    long token = beforeContext(context, site, metadata);
    if (token != 0) {
      Invocation current = ((State)context).current;
      current.callbackSite = callbackSite; current.callbackMetadata = callbackMetadata;
    }
    return token;
  }
  public static long arrive(String definition) {
    State state = Sessions.STATE.get();
    if (state == null || state.active == null) return 0;
    int slot = definitionIndex(state.active.table,definition);
    return arriveContext(state, slot, definition);
  }
  public static long arriveContext(Object context, long slot, String definition) {
    State state = (State) context; if (state == null || state.active == null) return 0;
    Invocation v = state.current;
    if (v == null || v.arrived) return arriveImplicit(state, slot);
    v.arrived = true;
    for (int i = 0; i < v.count; i++) {
      Entry e = v.entries[i]; if (e.chunk != null) e.chunk.definition[e.offset] = slot;
    }
    return 0;
  }
  private static long arriveImplicit(State state, long slot) {
    Invocation parent = state.current;
    long created = state.controlCallback && parent != null
        ? beforeContext(state, parent.callbackSite, parent.callbackMetadata)
        : beforeContext(state, -1, "\t\t-1\t-1\t-1\t-1\tunknown\t");
    state.controlCallback = false;
    Invocation v = state.current; v.arrived = true;
    for (int i = 0; i < v.count; i++) {
      Entry e = v.entries[i]; if (e.chunk != null) e.chunk.definition[e.offset] = slot;
    }
    return created;
  }
  public static void tail(long site, String metadata) {
    State state = Sessions.STATE.get(); if (state == null || state.active == null) return;
    int slot = siteIndex(state.active.table,site);
    tailContext(state, slot, metadata);
  }
  public static void tailContext(Object context, long site, String metadata) {
    State state = (State) context; if (state == null || state.current == null) return;
    Invocation v = state.current;
    for (int i = 0; i < v.count; i++) {
      Entry e = v.entries[i]; Scope s = e.scope;
      long definition = s.recorded(s.current) ? s.definition(s.current) : -1;
      long next = s.append(site, metadata); e.logicalTip = next;
      if (s.recorded(next)) { s.definition(next, definition); e.tip = next; }
    }
  }
  public static void finish(long token, boolean normal) { finishContext(context(), token, normal); }
  public static void finishContext(Object context, long token, boolean normal) {
    if (token == 0) return; State state = (State) context; Invocation v = state.current;
    if (v == null || v.token != token) fail("provenance: invocation closed out of order");
    for (int i = 0; i < v.count; i++) {
      Entry e = v.entries[i]; Scope s = e.scope;
      if (e.chunk != null) {
        int status = e.chunk.status[e.offset];
        if (status != 0 && status != 4) fail("provenance: frame closed twice");
        if (e.tip == e.frame) {
          if (status != 4) e.chunk.status[e.offset] = normal ? 1 : 2;
        } else finishTail(e, normal);
      }
      s.current = e.parent; s.recordedCurrent = e.recordedParent;
    }
    v.finished = true; state.current = v.parent; drop(v);
  }
  public static void failureContext(Object context, long token, Throwable failure) {
    if (token==0) return;
    if (failure instanceof CtlDiscard) {
      Invocation v=((State)context).current;
      if (v==null || v.token!=token) fail("provenance: invocation closed out of order");
      for (int i=0;i<v.count;i++) { markSegment(v.entries[i],0,4); markSegment(v.entries[i],3,4); }
    }
    finishContext(context,token,false);
  }
  private static void finishTail(Entry e, boolean normal) {
    Scope s = e.scope; long current = e.tip;
    while (current != e.recordedParent) {
      RecordChunk chunk = s.frames.chunk(current); int offset = s.frames.offset(current);
      int status = chunk.status[offset];
      if (status != 0 && status != 4) fail("provenance: invalid tail segment");
      if (status != 4) chunk.status[offset] = normal ? 1 : 2;
      current = chunk.parent[offset];
    }
    s.current = current;
  }
  public static long open(Tuple2 table) { return open(table, 1048576); }
  public static long open(Tuple2 table, long capacity) {
    if (capacity < 1 || capacity > 38347921)
      fail("provenance: capacity must be between 1 and 38347921");
    State state = Sessions.STATE.get();
    if (state == null) { state = new State(); Sessions.STATE.set(state); }
    Scope s = new Scope(state.active, table, capacity);
    Sessions.REGISTRY.put(s.id, s); state.active = s;
    synchronized (Sessions.class) { Sessions.active++; enabled = true; }
    return s.id;
  }
  public static void close(long id, boolean normal) {
    State state = Sessions.STATE.get(); Scope s = scope(id);
    if (s != state.active || s.current != 1)
      fail("provenance: scope closed with active calls");
    s.status(1, normal ? 1 : 2);
    for (Mark mark : s.marks) { drop(mark.creator); mark.creator = null; }
    state.active = s.outer; Sessions.REGISTRY.remove(id);
    if (state.active == null) { drop(state.pending); state.pending = null; Sessions.STATE.remove(); }
    synchronized (Sessions.class) { Sessions.active--; enabled = Sessions.active != 0; }
  }
  public static String checkpoint(long id) {
    Scope s = scope(id);
    s.marks.add(new Mark(s.current, s.view.size(), s.notes.size(), Sessions.STATE.get().current, s.nextInstance));
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
    if (c.creator != null ? c.creator.finished : s.status(1) != 0)
      fail("provenance: creating frame has finished");
    if (!c.valid) fail("provenance: checkpoint has been invalidated");
    if (s.current != c.frame) fail("provenance: not in the creating frame");
    if (hasSuspended(s, c.logicalBoundary)) fail("provenance: checkpoint has suspended calls");
    for (int i = c.boundary; i < s.view.size(); i++)
      if (s.frames.get(s.view.get(i)).status == 3) fail("provenance: checkpoint has suspended calls");
    while (!s.markStack.isEmpty() && s.markStack.get(s.markStack.size() - 1) != ordinal - 1)
      s.marks.get(s.markStack.remove(s.markStack.size() - 1)).valid = false;
    s.view.truncate(c.boundary);
    s.notes.subList(c.noteBoundary, s.notes.size()).clear();
    s.epoch++;
  }
  /* Typed program metadata is generated by the compiler and shared by all
   * snapshots. Only cold instrumentation adapters look up semantic IDs. */
  public static Tuple2 table(Object[] sites, Object[] definitions) {
    return new Tuple2(Array.array_wrap(sites,sites.length),Array.array_wrap(definitions,definitions.length));
  }
  private static int siteIndex(Tuple2 table,long id) {
    if(id<=0) return -1;
    Array sites=(Array)table._0; int lo=0,hi=(int)Array.array_len(sites);
    while(lo<hi) { int mid=lo+(hi-lo)/2; Tuple5 numbers=(Tuple5)((Tuple2)Array.array_get(sites,mid))._0;
      if((Long)numbers._0<id) lo=mid+1; else hi=mid; }
    if(lo==Array.array_len(sites) || (Long)((Tuple5)((Tuple2)Array.array_get(sites,lo))._0)._0!=id) fail("provenance: missing static Site");
    return lo;
  }
  private static int definitionIndex(Tuple2 table,String metadata) {
    Array definitions=(Array)table._1;
    for(int i=0;i<Array.array_len(definitions);i++) {
      StringBuilder text=new StringBuilder(); renderDefinition(text,(Tuple6)Array.array_get(definitions,i));
      if(text.toString().equals(metadata)) return i;
    }
    fail("provenance: missing static Definition"); return -1;
  }
  public static long header(Tuple3 view,long field) {
    if(field<0 || field>=4) fail("provenance: invalid frozen field");
    return word((byte[])view._0,field);
  }
  public static long column(Tuple3 view,long row,long field) {
    byte[] data=(byte[])view._0;
    if(row<0 || row>=word(data,2)) fail("provenance: record index out of bounds");
    if(field<0 || field>=7) fail("provenance: invalid frozen field");
    return word(data,4+row*7+field);
  }
  private static void put(byte[] data, int index, long value) {
    int at=index*8; for(int i=0;i<8;i++) { data[at+i]=(byte)value; value>>>=8; }
  }
  public static long word(byte[] data, long index) {
    if(index<0 || index>=data.length/8) fail("provenance: invalid frozen word");
    int at=(int)index*8; long value=0; for(int i=7;i>=0;i--) value=(value<<8)|(data[at+i]&255L); return value;
  }
  private static byte[] freeze(Scope s, int[] view, boolean envelope) {
    int n=view.length; if(n>(Integer.MAX_VALUE/8-4)/7) fail("provenance: snapshot capacity exceeded");
    byte[] data=new byte[(4+n*7)*8]; put(data,0,s.id); put(data,1,s.epoch); put(data,2,n); put(data,3,s.completeness);
    int[] rows=envelope ? null : new int[s.frames.size()+1]; if(rows!=null) Arrays.fill(rows,-1);
    for(int i=0;i<n;i++) {
      long id=view[i]+1L; RecordChunk c=s.frames.chunk(id); int j=s.frames.offset(id),at=4+i*7;
      long p=c.parent[j]; int parent=p==0 ? -1 : envelope ? i-1 : rows[Math.toIntExact(p)];
      if(p!=0 && parent<0) throw new AssertionError("missing frozen parent");
      if(rows!=null) rows[(int)id]=i; put(data,at,c.epoch[j]); put(data,at+1,id); put(data,at+2,parent); put(data,at+3,c.status[j]);
      put(data,at+4,c.site[j]); put(data,at+5,envelope && i+1==n ? -1 : c.definition[j]); put(data,at+6,c.boundary[j]);
    }
    return data;
  }
  public static Tuple4 origin(long id) {
    Scope s=leaseScope(id); Invocation operation=Sessions.STATE.get().current;
    while(operation!=null && !operation.metadata.contains("\tperform\t")) operation=operation.parent;
    if(operation==null) operation=Sessions.STATE.get().pending;
    while(operation!=null && !operation.metadata.contains("\tperform\t")) operation=operation.parent;
    if(operation==null) fail("provenance: no operation origin");
    long sender=0; for(int i=0;i<operation.count;i++) { Entry e=operation.entries[i]; if(e.scope==s) sender=e.frame; }
    if(sender==0) fail("provenance: operation is outside the observation scope");
    if (!s.recorded(sender)) {
      byte[] data = new byte[88]; put(data,0,s.id); put(data,1,s.epoch); put(data,2,1); put(data,3,1);
      long epoch = s.epoch;
      for (int i=0;i<operation.count;i++) if (operation.entries[i].scope==s) epoch=operation.entries[i].epoch;
      put(data,4,epoch); put(data,5,sender); put(data,6,-1); put(data,7,operation.suspended ? 3 : 0);
      put(data,8,operation.site); put(data,9,-1); put(data,10,1);
      Tuple5 text=(Tuple5)((Tuple2)Array.array_get((Array)s.table._0,operation.site))._1;
      return new Tuple4(data,s.table,Long.valueOf(0),text._4);
    }
    int n=0; for(long f=sender;f!=0;f=s.parent(f)) n++;
    int[] view=new int[n]; int at=n;
    for(long f=sender;f!=0;f=s.parent(f)) view[--at]=Math.toIntExact(f-1);
    Tuple5 strings=(Tuple5)((Tuple2)Array.array_get((Array)s.table._0,operation.site))._1;
    return new Tuple4(freeze(s,view,true),s.table,Long.valueOf(n-1),strings._4);
  }
  private static String unescape(String value) {
    if(value.indexOf('%')<0) return value;
    StringBuilder out=new StringBuilder();
    for(int i=0;i<value.length();i++) {
      char c=value.charAt(i);
      if(c=='%') {
        if(i+2>=value.length()) fail("provenance: invalid static escape");
        String code=value.substring(i+1,i+3);
        if(code.equals("25")) c='%'; else if(code.equals("09")) c='\t'; else if(code.equals("0A")) c='\n';
        else if(code.equals("0D")) c='\r'; else if(code.equals("00")) c=0; else fail("provenance: invalid static escape"); i+=2;
      }
      out.append(c);
    }
    return out.toString();
  }
  public static String field(String raw,long index) {
    if(index<0) fail("provenance: invalid static field"); int start=0;
    while(index-->0) { int next=raw.indexOf('\t',start); if(next<0) fail("provenance: invalid static field"); start=next+1; }
    int end=raw.indexOf('\t',start); return unescape(raw.substring(start,end<0 ? raw.length() : end));
  }
  public static long number(String raw,long index) {
    String value=field(raw,index); if(value.isEmpty()) return -1;
    try { return Long.parseLong(value); } catch(NumberFormatException invalid) { fail("provenance: invalid static number"); return 0; }
  }
  public static void note(long id,Tuple4 origin) {
    Scope s = scope(id);
    if (s.notesWritten++ < s.capacity) s.notes.add(origin); else s.completeness = 1;
  }
  public static Tuple3 completed(long id) {
    Scope s=scope(id); int[] view=new int[s.view.size()]; for(int i=0;i<view.length;i++) view[i]=s.view.get(i);
    return new Tuple3(freeze(s,view,false),s.table,Array.array_wrap(s.notes.toArray(),s.notes.size()));
  }
  private static String escape(String value) {
    return value.replace("%","%25").replace("\t","%09").replace("\n","%0A").replace("\r","%0D").replace("\0","%00");
  }
  private static void renderSite(StringBuilder b,Tuple2 row) {
    Tuple5 n=(Tuple5)row._0,s=(Tuple5)row._1;
    b.append(n._0).append('\t').append(escape((String)s._0)).append('\t').append(escape((String)s._2))
      .append('\t').append(n._1).append('\t').append(n._2).append('\t').append(n._3).append('\t').append(n._4)
      .append('\t').append(escape((String)s._3)).append('\t').append(escape((String)s._4));
  }
  private static void renderDefinition(StringBuilder b,Tuple6 d) {
    b.append(escape((String)d._1)).append('\t').append(escape((String)d._2)).append('\t').append(d._3)
      .append('\t').append(d._4).append('\t').append(escape((String)d._5)).append('\t').append(d._0);
  }
  private static void renderRecord(StringBuilder b,byte[] data,Tuple2 table,long row) {
    long at=4+row*7,site=word(data,at+4),def=word(data,at+5),parent=word(data,at+2);
    b.append("F\t").append(word(data,0)).append('\t').append(word(data,at)).append('\t').append(word(data,at+1))
      .append('\t').append(parent<0 ? 0 : word(data,4+parent*7+1)).append('\t').append(word(data,at+3)).append('\t');
    if(site>=0) renderSite(b,(Tuple2)Array.array_get((Array)table._0,site)); else b.append("0\t");
    b.append('\t'); if(def>=0) renderDefinition(b,(Tuple6)Array.array_get((Array)table._1,def));
    b.append('\t').append(word(data,at+6));
  }
  private static void renderOriginInto(StringBuilder b,Tuple4 origin) {
    byte[] data=(byte[])origin._0; Tuple2 table=(Tuple2)origin._1; long row=(Long)origin._2,site=word(data,4+(word(data,2)-1)*7+4);
    b.append("O1\t");
    if(site>=0) renderSite(b,(Tuple2)Array.array_get((Array)table._0,site)); else b.append("0\t");
    b.append('\t').append(word(data,3));
    while(row>=0) { b.append('\n'); renderRecord(b,data,table,row); row=word(data,4+row*7+2); }
  }
  public static String renderOrigin(Tuple4 origin) { StringBuilder b=new StringBuilder(); renderOriginInto(b,origin); return b.toString(); }
  public static String renderSnapshot(Tuple3 snapshot) {
    byte[] data=(byte[])snapshot._0; Tuple2 table=(Tuple2)snapshot._1; Array notes=(Array)snapshot._2;
    StringBuilder b=new StringBuilder(); b.append("S1\t").append(word(data,0)).append('\t').append(word(data,1)).append('\t').append(word(data,3));
    for(long i=0;i<word(data,2);i++) { b.append('\n'); renderRecord(b,data,table,i); }
    for(long i=0;i<Array.array_len(notes);i++) { b.append("\n\n"); renderOriginInto(b,(Tuple4)Array.array_get(notes,i)); }
    return b.toString();
  }
  /* A continuation owns its execution snapshot. Mounting switches only the
   * metadata channel; lexical effect evidence remains in the frozen frames. */
  private static final class Activation {
    State state, running, armState; Invocation boundary;
    final boolean registered; int armCount;
    boolean suspended, closed;
    final ArrayList<Scope> scopes = new ArrayList<>();
    final ArrayList<Long> currents = new ArrayList<>(), recordedCurrents = new ArrayList<>();
    final ArrayList<Long> armCurrents = new ArrayList<>(), armRecordedCurrents = new ArrayList<>();
    Activation(State source, boolean registered) {
      this.registered=registered;
      state = copy(source); running = copy(source); retainState(state);
      armState=registered ? copy(source) : null; retainState(armState);
      boundary = source == null ? null : source.current;
      if (source != null) for (Scope s = source.active; s != null; s = s.outer) {
        scopes.add(s); currents.add(s.current); recordedCurrents.add(s.recordedCurrent);
        armCurrents.add(s.current); armRecordedCurrents.add(s.recordedCurrent);
        if (registered) register(s);
      }
      armCount=scopes.size();
    }
    void register(Scope s) {
      for (int i=s.activations.size()-1;i>=0;i--) {
        ActivationRef ref=s.activations.get(i); Activation old=ref.get();
        if (old==null || old.closed) {
          if (old==null) s.unresumed=Math.max(s.unresumed,ref.suspendedMaximum);
          s.activations.remove(i);
        }
      }
      s.activations.add(new ActivationRef(this));
    }
    void track(State source) {
      for (int i=scopes.size()-1;i>=armCount;i--) {
        boolean live=false;
        for (Scope s=source==null ? null : source.active;s!=null;s=s.outer) if (s==scopes.get(i)) live=true;
        if (!live) { scopes.remove(i); currents.remove(i); recordedCurrents.remove(i); }
      }
      for (Scope s=source==null ? null : source.active;s!=null;s=s.outer) if (!scopes.contains(s)) {
        scopes.add(s); currents.add(s.current); recordedCurrents.add(s.recordedCurrent);
        if (registered) register(s);
      }
    }
    void updateSuspended() {
      for (Scope scope : scopes) {
        long maximum=0;
        if (suspended) for (Invocation v=state==null ? null : state.current;v!=null && v!=boundary;v=v.parent)
          for (int i=0;i<v.count;i++) if (v.entries[i].scope==scope) maximum=Math.max(maximum,v.entries[i].logicalTip);
        for (ActivationRef ref : scope.activations) if (ref.get()==this) ref.suspendedMaximum=maximum;
      }
    }
    void restore() {
      suspended = false; updateSuspended();
      for (int i = 0; i < scopes.size(); i++) {
        scopes.get(i).current = currents.get(i); scopes.get(i).recordedCurrent = recordedCurrents.get(i);
      }
      for (Invocation v = state == null ? null : state.current; v != null && v != boundary; v = v.parent) {
        v.suspended = false;
        for (int i = 0; i < v.count; i++) { Entry e = v.entries[i]; markSegment(e, 3, 0); }
      }
    }
    void save(boolean done) {
      suspended = !done; closed = done;
      running=Sessions.STATE.get(); track(running);
      State next = copy(running); retainState(next); dropState(state); state = next;
      for (int i = 0; i < scopes.size(); i++) {
        currents.set(i, scopes.get(i).current); recordedCurrents.set(i, scopes.get(i).recordedCurrent);
      }
      updateSuspended();
      if (!done) for (Invocation v = state == null ? null : state.current; v != null && v != boundary; v = v.parent) {
        v.suspended = true;
        for (int i = 0; i < v.count; i++) { Entry e = v.entries[i]; markSegment(e, 0, 3); }
      }
    }
  }
  private static void markSegment(Entry e, int before, int after) {
    for (long f=e.tip; f!=0 && f!=e.recordedParent; f=e.scope.parent(f))
      if (e.scope.status(f)==before) e.scope.status(f,after);
  }
  private static State copy(State source) {
    if (source == null) return null;
    State value = new State(); value.owner = source.owner; value.active = source.active; value.current = source.current;
    value.pending = source.pending; value.controlCallback = source.controlCallback; return value;
  }
  public static Object capture() { return new Activation(Sessions.STATE.get(),true); }
  private static boolean hasSuspended(Scope s, long boundary) {
    if (s.unresumed>=boundary) return true;
    for (ActivationRef ref : s.activations) if (ref.suspendedMaximum>=boundary) return true;
    return false;
  }
  private static void assign(State target, State source) {
    target.owner = source.owner; target.active = source.active; target.current = source.current;
    target.pending = source.pending; target.controlCallback = source.controlCallback;
  }
  public static Object mount(Object context) {
    Activation saved = new Activation(Sessions.STATE.get(),false);
    saved.running = Sessions.STATE.get();
    State current = Sessions.STATE.get(); if (current != null) drop(current.pending);
    if (context != null) {
      Activation a = (Activation) context;
      if (current!=null && current.active!=null && (a.state==null || current.active!=a.state.active)) unknownContext(current);
      a.restore();
      if (a.state==null) Sessions.STATE.remove();
      else {
        if (a.running==null) a.running=copy(a.state);
        assign(a.running, a.state); retain(a.running.pending); Sessions.STATE.set(a.running);
      }
    } else {
      if (current!=null && current.active!=null) unknownContext(current);
      Sessions.STATE.remove();
    }
    return saved;
  }
  public static void unmount(Object context, Object previous, boolean done) {
    Activation saved = (Activation) previous;
    if (context != null) {
      Activation a = (Activation) context; a.save(done);
      if (!done && saved.state != null) {
        drop(saved.state.pending); saved.state.pending = a.state == null ? null : a.state.current;
        retain(saved.state.pending);
      }
    }
    State current = Sessions.STATE.get(); if (current != null) drop(current.pending);
    saved.restore();
    if (saved.state == null) Sessions.STATE.remove();
    else { assign(saved.running, saved.state); retain(saved.running.pending); Sessions.STATE.set(saved.running); }
    dropState(saved.state); saved.state = null;
    if (done && context != null) {
      Activation a = (Activation)context; dropState(a.state); a.state = null;
      dropState(a.armState); a.armState=null;
      if (a.running!=null) { a.running.active = null; a.running.current = a.running.pending = null; }
      a.boundary=null; a.scopes.clear(); a.currents.clear(); a.recordedCurrents.clear();
      a.armCurrents.clear(); a.armRecordedCurrents.clear();
    }
  }
  public static void abandon(Object context) {
    if (context == null) return; Activation a = (Activation)context;
    for (Invocation v = a.state == null ? null : a.state.current; v != null && v != a.boundary; v = v.parent)
      for (int i = 0; i < v.count; i++) {
        Entry e = v.entries[i]; Scope s = e.scope;
        for (long f = e.tip; f != 0 && f != e.recordedParent; f = s.parent(f))
          if (s.status(f) == 0 || s.status(f) == 3) s.status(f, 4);
      }
  }
  public static Object controlBody(Object body, Object evidence, Object context) {
    if (context == null || ((Activation)context).armState==null || ((Activation)context).armState.active==null)
      return ((Fn1)body).apply(evidence);
    State state = Sessions.STATE.get(); state.controlCallback = true;
    return ((Fn1)body).applyObserved(evidence, 0L);
  }
  public static Object controlArm(Object body, Object[] args, Object k, Object evidence, Object context) {
    State driver=Sessions.STATE.get(); Activation previous=new Activation(driver,false); previous.running=driver;
    if (driver!=null) { drop(driver.pending); driver.pending=null; }
    Activation owner=context==null ? null : (Activation)context;
    boolean observed=owner!=null && owner.armState!=null && owner.armState.active!=null;
    if (observed) {
      Activation a=owner; State arm=copy(a.armState);
      arm.current=a.boundary; arm.pending=a.state==null ? null : a.state.current; retain(arm.pending); arm.controlCallback=true;
      for (int i=0;i<a.armCount;i++) {
        a.scopes.get(i).current=a.armCurrents.get(i);
        a.scopes.get(i).recordedCurrent=a.armRecordedCurrents.get(i);
      }
      Sessions.STATE.set(arm);
    } else Sessions.STATE.remove();
    try { switch (args.length) {
      case 0: return observed ? ((Fn2)body).applyObserved(k, evidence, 0L) : ((Fn2)body).apply(k, evidence);
      case 1: return observed ? ((Fn3)body).applyObserved(args[0], k, evidence, 0L) : ((Fn3)body).apply(args[0], k, evidence);
      case 2: return observed ? ((Fn4)body).applyObserved(args[0], args[1], k, evidence, 0L) : ((Fn4)body).apply(args[0], args[1], k, evidence);
      case 3: return observed ? ((Fn5)body).applyObserved(args[0], args[1], args[2], k, evidence, 0L) : ((Fn5)body).apply(args[0], args[1], args[2], k, evidence);
      case 4: return observed ? ((Fn6)body).applyObserved(args[0], args[1], args[2], args[3], k, evidence, 0L) : ((Fn6)body).apply(args[0], args[1], args[2], args[3], k, evidence);
      case 5: return observed ? ((Fn7)body).applyObserved(args[0], args[1], args[2], args[3], args[4], k, evidence, 0L) : ((Fn7)body).apply(args[0], args[1], args[2], args[3], args[4], k, evidence);
      case 6: return observed ? ((Fn8)body).applyObserved(args[0], args[1], args[2], args[3], args[4], args[5], k, evidence, 0L) : ((Fn8)body).apply(args[0], args[1], args[2], args[3], args[4], args[5], k, evidence);
      case 7: return observed ? ((Fn9)body).applyObserved(args[0], args[1], args[2], args[3], args[4], args[5], args[6], k, evidence, 0L) : ((Fn9)body).apply(args[0], args[1], args[2], args[3], args[4], args[5], args[6], k, evidence);
      default: throw new AssertionError("control arity");
    } } finally {
      State arm=Sessions.STATE.get(); if (arm!=null) drop(arm.pending);
      previous.restore();
      if (previous.state==null) Sessions.STATE.remove();
      else {
        assign(previous.running,previous.state); retain(previous.running.pending); Sessions.STATE.set(previous.running);
      }
      dropState(previous.state);
    }
  }
  public static boolean observing() {
    State state = Sessions.STATE.get(); return state != null && state.active != null;
  }
  public static void unknownContext(Object context) {
    State state=(State)context; Invocation v=state==null ? null : state.current;
    if (v==null) return; v.arrived=true;
    for (int i=0;i<v.count;i++) { Entry e=v.entries[i]; if (e.chunk!=null) e.chunk.boundary[e.offset]=1; }
  }
  public static Object externalCallback(Object body, Object[] args) {
    State state=(State)context(); boolean observed=state!=null && state.active!=null;
    long token=observed ? beforeContext(state,-1,"\t\t-1\t-1\t-1\t-1\tunknown\t") : 0;
    if (observed) {
      unknownContext(state); state.current.arrived=false;
    }
    boolean normal=false; Throwable failure=null;
    try {
      Object result;
      switch(args.length) {
        case 1: result=observed ? ((Fn1)body).applyObserved(args[0],0L) : ((Fn1)body).apply(args[0]); break;
        case 2: result=observed ? ((Fn2)body).applyObserved(args[0],args[1],0L) : ((Fn2)body).apply(args[0],args[1]); break;
        case 3: result=observed ? ((Fn3)body).applyObserved(args[0],args[1],args[2],0L) : ((Fn3)body).apply(args[0],args[1],args[2]); break;
        case 4: result=observed ? ((Fn4)body).applyObserved(args[0],args[1],args[2],args[3],0L) : ((Fn4)body).apply(args[0],args[1],args[2],args[3]); break;
        case 5: result=observed ? ((Fn5)body).applyObserved(args[0],args[1],args[2],args[3],args[4],0L) : ((Fn5)body).apply(args[0],args[1],args[2],args[3],args[4]); break;
        case 6: result=observed ? ((Fn6)body).applyObserved(args[0],args[1],args[2],args[3],args[4],args[5],0L) : ((Fn6)body).apply(args[0],args[1],args[2],args[3],args[4],args[5]); break;
        case 7: result=observed ? ((Fn7)body).applyObserved(args[0],args[1],args[2],args[3],args[4],args[5],args[6],0L) : ((Fn7)body).apply(args[0],args[1],args[2],args[3],args[4],args[5],args[6]); break;
        case 8: result=observed ? ((Fn8)body).applyObserved(args[0],args[1],args[2],args[3],args[4],args[5],args[6],args[7],0L) : ((Fn8)body).apply(args[0],args[1],args[2],args[3],args[4],args[5],args[6],args[7]); break;
        case 9: result=observed ? ((Fn9)body).applyObserved(args[0],args[1],args[2],args[3],args[4],args[5],args[6],args[7],args[8],0L) : ((Fn9)body).apply(args[0],args[1],args[2],args[3],args[4],args[5],args[6],args[7],args[8]); break;
        default: throw new AssertionError("external callback arity");
      }
      normal=true; return result;
    } catch (Throwable error) { failure=error; throw error; }
    finally { if (observed) {
      if (failure==null) finishContext(state,token,normal); else failureContext(state,token,failure);
    } }
  }
}
