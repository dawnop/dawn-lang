/* The full generation stopwatch covers recording, public source projection,
 * lower/encode, file output, one pinned assembler invocation and cleanup. */
import java.nio.file.*;
public final class GenerationBench {
  static void once(dawn.rt.Fn1 work,boolean observed,Path output,int batch,String assembler,String gpu) throws Exception {
    Path bytes=output.resolve("request-"+batch+".tilebc");
    Path cubin=output.resolve("request-"+batch+".cubin");
    Path log=output.resolve("request-"+batch+".assembler.log");
    PreviewBench.once(work,observed,"generate",bytes.toString());
    Process child=new ProcessBuilder(assembler,"--gpu-name",gpu,"-o",cubin.toString(),bytes.toString())
      .redirectErrorStream(true).redirectOutput(log.toFile()).start();
    if(child.waitFor()!=0) throw new IllegalStateException("assembler refused request: "+log);
    for(String line:Files.readAllLines(log)) if(line.startsWith("error:"))
      throw new IllegalStateException("assembler reported an error: "+log);
    try(java.io.InputStream artifact=Files.newInputStream(cubin)) {
      byte[] magic=new byte[4];
      if(artifact.read(magic)!=4 || magic[0]!=127 || magic[1]!='E' || magic[2]!='L' || magic[3]!='F')
        throw new IllegalStateException("assembler did not deliver an ELF artifact");
    }
    PreviewBench.latest=null;
  }
  public static void main(String[] args) throws Exception {
    boolean observed=args[0].equals("observed");
    java.util.List<String> lines=Files.readAllLines(Paths.get(args[1]));
    int warm=Integer.parseInt(args[2]),batches=Integer.parseInt(args[3]);
    if(lines.size()!=248 || warm<0 || batches<=0) throw new IllegalArgumentException("incomplete generation corpus");
    java.util.Set<String> unique=new java.util.HashSet<>();
    Path output=Paths.get(args[4]);Files.createDirectories(output);
    PreviewBench.source=PreviewInputs.load(args[5]);PreviewBench.revision=args[6];
    dawn.rt.Fn1[] work=new dawn.rt.Fn1[lines.size()];
    String[] names=new String[lines.size()],targets=new String[lines.size()];
    for(int c=0;c<lines.size();c++) {
      String[] fields=lines.get(c).split("\\s+");
      if(fields.length!=2 || !unique.add(fields[0])) throw new IllegalArgumentException("duplicate or malformed generation case");
      names[c]=fields[0];targets[c]=fields[1];
      work[c]=main.select_case(names[c]);Path directory=output.resolve(names[c]);Files.createDirectories(directory);
      // Warm all in-process generation, including encode and file output.
      // Every measured assembler is a fresh process, as in production.
      for(int i=0;i<warm;i++) PreviewBench.once(work[c],observed,"generate",directory.resolve("warmup.tilebc").toString());
    }
    PreviewBench.latest=null;
    long[][] elapsed=new long[work.length][batches];
    long totalStart=System.nanoTime();
    for(int c=0;c<work.length;c++) for(int batch=0;batch<batches;batch++) {
      long start=System.nanoTime();
      once(work[c],observed,output.resolve(names[c]),batch,args[7],targets[c]);
      elapsed[c][batch]=System.nanoTime()-start;
    }
    long total=System.nanoTime()-totalStart;
    for(int c=0;c<work.length;c++) for(int batch=0;batch<batches;batch++)
      System.out.println(names[c]+" "+batch+" "+elapsed[c][batch]);
    System.out.println("TOTAL "+total);
  }
}
