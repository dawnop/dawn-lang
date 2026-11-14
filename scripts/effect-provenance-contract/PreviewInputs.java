/* Loading a cached parser index is a source revision operation. Each preview
 * still checks the artifact revision and every materialized user source span. */
import java.nio.file.*;
import java.util.*;

final class PreviewInputs {
  static PreviewConsumer.SourceIndex load(String path) throws Exception {
    List<String> lines=Files.readAllLines(Paths.get(path));
    String[] first=lines.get(0).split("\t",-1);
    PreviewConsumer.require(first.length==2 && first[0].equals("revision"),"invalid source index");
    Map<String,long[]> declarations=new HashMap<>(); Set<Long> spans=new HashSet<>();
    for(int i=1;i<lines.size();i++) {
      String[] fields=lines.get(i).split("\t",-1);
      if(fields[0].equals("declaration") && fields.length==4)
        declarations.put(fields[1],new long[]{Long.parseLong(fields[2]),Long.parseLong(fields[3])});
      else if(fields[0].equals("span") && fields.length==3)
        spans.add((Long.parseLong(fields[1])<<32)|Long.parseLong(fields[2]));
      else throw new IllegalArgumentException("invalid source index entry");
    }
    return new PreviewConsumer.SourceIndex(first[1],declarations,spans);
  }
}
