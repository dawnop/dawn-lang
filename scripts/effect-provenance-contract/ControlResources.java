/* Private state is inspected only by this lifecycle correctness probe.
 * The timed product consumer uses the public std/provenance interface. */
import java.lang.reflect.*;
public final class ControlResources {
  static Object get(Object value,String name) throws Exception {
    Field f=value.getClass().getDeclaredField(name); f.setAccessible(true); return f.get(value);
  }
  static Object call(String name,Object first) throws Exception {
    for(Method m:Class.forName("control_resources").getDeclaredMethods()) if(m.getName().equals(name)) {
      Object[] args=new Object[m.getParameterCount()]; args[0]=first;
      try { return m.invoke(null,args); }
      catch(InvocationTargetException e) { throw new AssertionError(e.getCause()); }
    }
    throw new AssertionError(name);
  }
  static void check(boolean ok) { if(!ok) throw new AssertionError("activation resource survived completion"); }
  static void empty(Object a) throws Exception {
    check(get(a,"state")==null && get(a,"armState")==null && get(a,"boundary")==null);
    for(String field:new String[]{"scopes","currents","recordedCurrents","armCurrents","armRecordedCurrents"})
      check(((java.util.List<?>)get(a,field)).isEmpty());
    Object running=get(a,"running");
    if(running!=null) check(get(running,"active")==null && get(running,"current")==null && get(running,"pending")==null);
  }
  public static void main(String[] args) throws Exception {
    for(String mode:new String[]{"normal","panic","discard"}) for(int i=0;i<100;i++) {
      Object stage=call("make",mode.equals("panic")),ticket=null;
      for(Field f:stage.getClass().getDeclaredFields()) { f.setAccessible(true); Object v=f.get(stage); if(v instanceof dawn.rt.Fn2) ticket=v; }
      check(ticket!=null); Object activation=get(get(ticket,"f"),"provenance");
      check(activation!=null);
      if(mode.equals("normal")) check(((Long)call("value",call("finish",stage)))==42);
      else if(mode.equals("panic")) check((Boolean)call("fail_finish",stage));
      else call("stop",stage);
      empty(activation); // ticket deliberately remains strongly reachable
      check(ticket!=null);
    }
    Class<?> sessions=Class.forName("dawn.rt.Provenance$Sessions");
    Field registry=sessions.getDeclaredField("REGISTRY"); registry.setAccessible(true);
    check(((java.util.Map<?,?>)registry.get(null)).isEmpty());
    System.out.println("42 control resource normal panic discard");
  }
}
