/* The stopwatch covers a request through preview plus source mapping and
 * cleanup. Independent N and hand tree judgements belong to PreviewCheck. */
import java.nio.file.*;

public final class PreviewBench {
  static volatile long sink;
  static volatile PreviewConsumer.Mapping delivered;
  static dawn$pkg$tileir.prog$TileProg latest;
  static PreviewConsumer.SourceIndex source;
  static String revision;
  static long once(dawn.rt.Fn1 work,boolean observed,String phase,String output) throws Exception {
    boolean consume=!phase.equals("record");
    dawn.rt.Tuple2 result=main.record_case(work,observed,consume);
    dawn$pkg$tileir.prog$TileProg program=(dawn$pkg$tileir.prog$TileProg)result._0;
    long checksum=0;
    if(observed && consume) {
      dawn.rt.Tuple3 snapshot=(dawn.rt.Tuple3)PreviewConsumer.some((Option)result._1);
      if(phase.equals("dump")) {
        String text=main.snapshot_text(snapshot); checksum^=text.length();
      } else {
        PreviewConsumer.Cache cache=new PreviewConsumer.Cache();
        PreviewConsumer.Mapping mapping=PreviewConsumer.consume(snapshot,source,revision,cache);
        delivered=mapping;
        checksum^=delivered.nodes.length+delivered.owners[delivered.owners.length-1];
        delivered=null;
        if(phase.equals("repeat")) {
          PreviewConsumer.Mapping again=PreviewConsumer.consume(snapshot,source,revision,cache);
          checksum^=again.nodes.length+again.owners[again.owners.length-1];
        }
      }
    }
    if(phase.equals("interactive") || phase.equals("repeat")) checksum^=main.preview_program(program).hashCode();
    if(phase.equals("generate")) {
      byte[] bytes=main.encode_program(program); checksum^=bytes.length;
      if(!output.equals("-")) Files.write(Paths.get(output),bytes);
    }
    latest=program; sink^=checksum; return checksum;
  }
  public static void main(String[] args) throws Exception {
    boolean observed=args[0].equals("observed"); String phase=args[2];
    int warm=Integer.parseInt(args[3]),batches=Integer.parseInt(args[4]),iterations=Integer.parseInt(args[5]);
    source=PreviewInputs.load(args[7]); revision=args[8];
    dawn.rt.Fn1 work=main.select_case(args[1]);
    for(int i=0;i<warm;i++) once(work,observed,phase,"-");
    for(int batch=0;batch<batches;batch++) {
      long start=System.nanoTime();
      for(int i=0;i<iterations;i++) once(work,observed,phase,args[6]);
      long duration=System.nanoTime()-start;
      System.out.println(batch+" "+duration/iterations+" "+main.operation_count(latest)+" "+sink);
    }
  }
}
