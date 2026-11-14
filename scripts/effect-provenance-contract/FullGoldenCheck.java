/* Exercise every actual CLI producer and its public bulk consumer twice,
 * then compare the delivered text/bytes to the independent stored goldens. */
import java.nio.file.*;
import java.util.*;
public final class FullGoldenCheck {
  public static void main(String[] args) throws Exception {
    Path golden=Paths.get(args[0]),out=Paths.get(args[2]);Files.createDirectories(out);
    for(String name:Files.readAllLines(Paths.get(args[1]))) {
      dawn.rt.Tuple2 value=main.provenance_check_case(name);
      byte[] text=((String)value._0).getBytes(java.nio.charset.StandardCharsets.UTF_8),bytes=(byte[])value._1;
      if(!Arrays.equals(text,Files.readAllBytes(golden.resolve(name+".mlir"))) ||
         !Arrays.equals(bytes,Files.readAllBytes(golden.resolve(name+".tilebc"))))
        throw new AssertionError("golden differs: "+name);
      Files.write(out.resolve(name+".mlir"),text);Files.write(out.resolve(name+".tilebc"),bytes);
      System.out.println(name+" public CLI mapping and both goldens");
    }
  }
}
