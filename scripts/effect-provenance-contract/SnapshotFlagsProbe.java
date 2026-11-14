/* Export flags are supplied by a runtime test producer. The actual reader
 * is compiled Dawn code calling the public std/provenance interface. */
import dawn.rt.*;
public class SnapshotFlagsProbe {
  static java.lang.reflect.Field member(Class<?> cls,String name) throws Exception {
    java.lang.reflect.Field f=cls.getDeclaredField(name); f.setAccessible(true); return f;
  }
  public static void main(String[] args) throws Exception {
    Tuple2 table=dawn.provenance.StaticData.table;
    Array sites=(Array)table._0,defs=(Array)table._1; Tuple2 site=null;
    for(long i=0;i<Array.array_len(sites);i++) {
      Tuple2 value=(Tuple2)Array.array_get(sites,i);
      if(((Tuple5)value._1)._3.equals("perform")) { site=value; break; }
    }
    if(site==null) throw new AssertionError("no genuine operation Site");
    long s=Provenance.open(table),token=Provenance.before((Long)((Tuple5)site._0)._0,ProbeTables.metadata(site));
    Provenance.arrive(ProbeTables.definition((Tuple6)Array.array_get(defs,0)));
    Class<?> sessions=Class.forName("dawn.rt.Provenance$Sessions");
    java.util.Map<?,?> registry=(java.util.Map<?,?>)member(sessions,"REGISTRY").get(null);
    Object scope=registry.get(s),frames=member(scope.getClass(),"frames").get(scope);
    java.util.List<?> chunks=(java.util.List<?>)member(frames.getClass(),"chunks").get(frames);
    Object chunk=chunks.get(0); int[] status=(int[])member(chunk.getClass(),"status").get(chunk);
    int[] boundary=(int[])member(chunk.getClass(),"boundary").get(chunk);
    member(scope.getClass(),"completeness").setInt(scope,1);status[1]=3;boundary[1]=1;
    Tuple4 origin=Provenance.origin(s); Provenance.note(s,origin);status[1]=4;
    Tuple3 old=Provenance.completed(s);String oldText=snapshot_flags.text(old);
    status[1]=0;boundary[1]=0;member(scope.getClass(),"completeness").setInt(scope,0);
    Provenance.finish(token,true);Tuple3 fresh=Provenance.completed(s);Provenance.close(s,true);
    if(!oldText.equals(snapshot_flags.text(old))) throw new AssertionError("snapshot changed");
    System.out.println(snapshot_flags.describe(old)); System.out.println(snapshot_flags.describe(fresh));
    System.out.println(snapshot_flags.text(old));System.out.println("@@fresh");System.out.println(snapshot_flags.text(fresh));
  }
}
