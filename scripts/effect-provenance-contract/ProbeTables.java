/* Adverse producers use the generated typed metadata ABI. This test helper
 * renders cold raw-adapter inputs; preview consumers never call it. */
import dawn.rt.*;
final class ProbeTables {
  static String escape(String s) {
    return s.replace("%","%25").replace("\t","%09").replace("\n","%0A").replace("\r","%0D").replace("\0","%00");
  }
  static Tuple2 site(long id,String owner) {
    return new Tuple2(new Tuple5(id,0L,1L,0L,1L),new Tuple5(owner,owner,"","call",""));
  }
  static String metadata(Tuple2 row) {
    Tuple5 n=(Tuple5)row._0,s=(Tuple5)row._1;
    return escape((String)s._0)+"\t"+escape((String)s._2)+"\t"+n._1+"\t"+n._2+"\t"+n._3+"\t"+n._4+"\t"+escape((String)s._3)+"\t"+escape((String)s._4);
  }
  static String definition(Tuple6 d) {
    return escape((String)d._1)+"\t"+escape((String)d._2)+"\t"+d._3+"\t"+d._4+"\t"+escape((String)d._5)+"\t"+d._0;
  }
}
