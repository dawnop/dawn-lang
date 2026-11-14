/* The producer may inspect live runtime fields to create adverse boundaries.
 * The consumer sees only frozen public values, after the scope has exited. */
import dawn.rt.*;
import java.lang.reflect.Field;
import java.util.*;

public final class PublicPreviewProbe {
  static Field field(Class<?> type,String name) throws Exception {
    Field field=type.getDeclaredField(name); field.setAccessible(true); return field;
  }
  static Tuple3 produce(String mode) throws Exception {
    Tuple2 table=dawn.provenance.StaticData.table;
    long id=Provenance.open(table);
    Class<?> sessions=Class.forName("dawn.rt.Provenance$Sessions");
    Map<?,?> registry=(Map<?,?>)field(sessions,"REGISTRY").get(null);
    Object scope=registry.get(id);
    if(mode.equals("truncated")) field(scope.getClass(),"completeness").setInt(scope,1);
    if(mode.equals("unknown")) {
      Object frames=field(scope.getClass(),"frames").get(scope);
      List<?> chunks=(List<?>)field(frames.getClass(),"chunks").get(frames);
      Object chunk=chunks.get(0); ((int[])field(chunk.getClass(),"boundary").get(chunk))[0]=1;
    }
    if(mode.equals("uncommitted")) {
      String mark=Provenance.checkpoint(id); Array sites=(Array)table._0,defs=(Array)table._1;
      Tuple2 site=null;
      for(long i=0;i<Array.array_len(sites);i++) {
        Tuple2 value=(Tuple2)Array.array_get(sites,i);
        if(((Tuple5)value._1)._3.equals("perform")) { site=value; break; }
      }
      if(site==null) throw new AssertionError("missing genuine operation Site");
      long token=Provenance.before((Long)((Tuple5)site._0)._0,ProbeTables.metadata(site));
      Provenance.arrive(ProbeTables.definition((Tuple6)Array.array_get(defs,0))); Tuple4 origin=Provenance.origin(id);
      Provenance.finish(token,true); Provenance.rewind(id,mark); Provenance.note(id,origin);
    }
    Tuple3 snapshot=Provenance.completed(id); Provenance.close(id,true); return snapshot;
  }
  public static void main(String[] args) throws Exception {
    for(String mode:new String[]{"truncated","unknown","uncommitted"}) {
      String result=main.check(produce(mode),"good");
      String expected=mode.equals("truncated")?"truncated provenance":mode.equals("unknown")?"unknown boundary":"uncommitted origin";
      if(!result.contains(expected)) throw new AssertionError(mode+" accepted: "+result);
      System.out.println("42 CLI "+mode+" rejected");
    }
  }
}
