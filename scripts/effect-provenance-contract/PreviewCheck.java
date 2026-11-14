/* Correctness runs have no clocks. Independent event counts, device goldens
 * and serialized projection comparisons run before the measurement phases. */
import java.nio.file.*;
import java.util.*;

public final class PreviewCheck {
  static int state(std.provenance$CallState state) {
    if(state instanceof std.provenance$CallState$Active) return 0;
    if(state instanceof std.provenance$CallState$Returned) return 1;
    if(state instanceof std.provenance$CallState$Unwound) return 2;
    if(state instanceof std.provenance$CallState$Suspended) return 3;
    if(state instanceof std.provenance$CallState$Abandoned) return 4;
    throw new AssertionError("unknown state");
  }
  static void compareRows(dawn.rt.Tuple3 snapshot) {
    dawn.rt.Tuple3 view=std.provenance.records(snapshot);
    long count=std.provenance.record_count(view),scope=std.provenance.record_scope(view);
    PreviewConsumer.require(!std.provenance.record_exists(view,-1) && !std.provenance.record_exists(view,count),"bulk bounds mismatch");
    for(long row=0;row<count;row++) {
      std.provenance$CallRecord record=(std.provenance$CallRecord)PreviewConsumer.some(std.provenance.record_at(snapshot,row));
      PreviewConsumer.require(std.provenance.record_exists(view,row) && scope==record.key.scope &&
        std.provenance.record_epoch(view,row)==record.key.epoch && std.provenance.record_instance(view,row)==record.key.instance &&
        PreviewConsumer.slot(std.provenance.record_parent(view,row))==PreviewConsumer.index(record.parent) &&
        PreviewConsumer.slot(std.provenance.record_site(view,row))==PreviewConsumer.index(record.site) &&
        PreviewConsumer.slot(std.provenance.record_definition(view,row))==PreviewConsumer.index(record.definition) &&
        std.provenance.record_state(view,row).equals(record.state) && std.provenance.record_boundary(view,row).equals(record.boundary),"bulk and row facts differ");
    }
  }
  public static void main(String[] args) throws Exception {
    PreviewConsumer.SourceIndex source=PreviewInputs.load(args[0]);
    String revision=args[1]; Path out=Paths.get(args[2]); Files.createDirectories(out);
    for(String line:Files.readAllLines(Paths.get(args[3]))) {
      String[] fields=line.split("\t"); String name=fields[0]; long n=Long.parseLong(fields[1]);
      dawn.rt.Fn1 work=main.select_case(name);
      dawn.rt.Tuple2 result=main.record_case(work,true,true);
      dawn$pkg$tileir.prog$TileProg program=(dawn$pkg$tileir.prog$TileProg)result._0;
      dawn.rt.Tuple3 snapshot=(dawn.rt.Tuple3)PreviewConsumer.some((Option)result._1);
      PreviewConsumer.require(std.provenance.snapshot_info(snapshot).records==n,"independent N mismatch");
      compareRows(snapshot);
      PreviewConsumer.Cache cache=new PreviewConsumer.Cache();
      PreviewConsumer.Mapping map=PreviewConsumer.consume(snapshot,source,revision,cache);
      PreviewConsumer.Mapping again=PreviewConsumer.consume(snapshot,source,revision,cache);
      PreviewConsumer.require(map.nodes.length==again.nodes.length && Arrays.equals(map.owners,again.owners),"repeated getter mismatch");
      StringBuilder projection=new StringBuilder();
      for(PreviewConsumer.Node node:map.nodes) projection.append(node.key.scope).append(' ').append(node.key.epoch).append(' ').append(node.key.instance).append(' ').append(node.parent).append(' ').append(state(node.state)).append(' ').append(node.site==null?0:node.site.id).append(' ').append(node.definition==null?0:node.definition.id).append('\n');
      projection.append("owners\n"); for(int owner:map.owners) projection.append(owner).append('\n');
      Files.write(out.resolve(name+".map"),projection.toString().getBytes("UTF-8"));
      Files.write(out.resolve(name+".mlir"),main.preview_program(program).getBytes("UTF-8"));
      Files.write(out.resolve(name+".tilebc"),main.encode_program(program));
      Files.write(out.resolve(name+".snapshot"),main.snapshot_text(snapshot).getBytes("UTF-8"));
      boolean rejected=false;
      try { PreviewConsumer.consume(snapshot,source,"wrong source revision",new PreviewConsumer.Cache()); }
      catch(IllegalArgumentException expected) { rejected=true; }
      PreviewConsumer.require(rejected,"source revision mutant escaped");
      System.out.println(name+" "+n+" "+map.nodes.length+" "+main.operation_count(program));
    }
  }
}
