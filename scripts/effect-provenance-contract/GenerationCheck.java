/* Correctness runs the complete product request without a stopwatch. */
import java.nio.file.*;
public final class GenerationCheck {
  public static void main(String[] args) throws Exception {
    PreviewBench.source=PreviewInputs.load(args[2]); PreviewBench.revision=args[3];
    Path output=Paths.get(args[4]); Files.createDirectories(output);
    if(args[1].startsWith("@")) {
      java.util.List<String> cases=Files.readAllLines(Paths.get(args[1].substring(1)));
      if(cases.size()!=248) throw new IllegalArgumentException("incomplete correctness corpus");
      for(String line:cases) {
        String[] fields=line.split("\\s+");Path directory=output.resolve(fields[0]);Files.createDirectories(directory);
        GenerationBench.once(main.select_case(fields[0]),args[0].equals("observed"),directory,0,args[5],fields[1]);
        System.out.println(fields[0]+" generated");
      }
    } else {
      GenerationBench.once(main.select_case(args[1]),args[0].equals("observed"),output,0,args[5],args[6]);
      System.out.println("generated");
    }
  }
}
