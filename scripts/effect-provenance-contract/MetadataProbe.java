/* The producer owns ordinary typed tuples. The source reader receives only
 * the opaque immutable snapshot, after the creating scope has exited. */
import dawn.rt.*;
public final class MetadataProbe {
  public static void main(String[] args) {
    String owner="unit%09\t雪",declaration="decl%25\n雪";
    Tuple2 site=new Tuple2(new Tuple5(999L,1L,7L,2L,4L),new Tuple5(owner,owner,declaration,"call","op%09\t雪"));
    Tuple6 definition=new Tuple6(888L,owner,declaration,0L,9L,"function");
    Tuple2 table=Provenance.table(new Object[]{site},new Object[]{definition});
    long scope=Provenance.open(table),token=Provenance.beforeAtContext(Provenance.context(),0L,"",0L,"");
    Provenance.arriveContext(Provenance.context(),0L,""); Provenance.finish(token,true);
    Tuple3 snapshot=Provenance.completed(scope); Provenance.close(scope,true);
    table=null; site=null; definition=null;
    System.out.println(snapshot_metadata.inspect(snapshot));
    System.out.println(snapshot_metadata.text(snapshot));
  }
}
