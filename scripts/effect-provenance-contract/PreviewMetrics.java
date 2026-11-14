/* Management snapshots run after all request stopwatches, using the same VM
 * flags. Keep raw diagnostics: code-cache usage includes metadata, whereas
 * codelist address ranges describe code and must not be called heap sizes. */
import java.lang.management.*;
import javax.management.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;

public final class PreviewMetrics {
  static void write(String prefix,String suffix,String value) throws Exception {
    Files.write(Paths.get(prefix+suffix),value.getBytes(StandardCharsets.UTF_8));
  }
  public static void main(String[] args) throws Exception {
    PreviewBench.main(args);
    capture();
  }
  static void capture() throws Exception {
    String prefix=System.getenv("DAWN_PROVENANCE_JIT_METRICS");
    if(prefix==null) throw new IllegalArgumentException("missing JIT evidence path");
    CompilationMXBean compiler=ManagementFactory.getCompilationMXBean();
    write(prefix,".compilation",compiler.getName()+"\n"+
          (compiler.isCompilationTimeMonitoringSupported()?compiler.getTotalCompilationTime():-1)+"\n");
    write(prefix,".vmargs",String.join("\n",ManagementFactory.getRuntimeMXBean().getInputArguments())+"\n");
    MBeanServer server=ManagementFactory.getPlatformMBeanServer();
    ObjectName diagnostic=new ObjectName("com.sun.management:type=DiagnosticCommand");
    for(String operation:new String[]{"compilerCodecache","compilerCodelist"})
      write(prefix,"."+operation,(String)server.invoke(diagnostic,operation,new Object[0],new String[0]));
    write(prefix,".compilerCodeHeapAnalytics",(String)server.invoke(diagnostic,
      "compilerCodeHeapAnalytics",new Object[]{new String[]{"all"}},new String[]{"[Ljava.lang.String;"}));
  }
}
