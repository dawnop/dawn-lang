// The real JVM collector must discard temporary allocations while an injected
// per-request reference survives the same full-GC sampling used for Dawn.
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.regex.Pattern;

class MemoryFixture {
    static final ArrayList<byte[]> held = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        var idPattern = Pattern.compile("\"id\":([0-9]+)");
        var lengthPattern = Pattern.compile("Content-Length: ([0-9]+)");
        while (true) {
            var header = new ByteArrayOutputStream();
            String text;
            do {
                int next = System.in.read();
                if (next < 0) return;
                header.write(next);
                text = header.toString(StandardCharsets.US_ASCII);
            } while (!text.endsWith("\r\n\r\n") && header.size() < 8192);
            if (!text.endsWith("\r\n\r\n")) {
                send("{\"jsonrpc\":\"2.0\",\"id\":null,\"error\":{\"code\":-32700,\"message\":\"Parse error\"}}");
                return;
            }
            var length = lengthPattern.matcher(text);
            if (!length.find()) throw new AssertionError("missing length");
            var body = new String(System.in.readNBytes(Integer.parseInt(length.group(1))),
                                  StandardCharsets.UTF_8);
            var id = idPattern.matcher(body);
            if (!id.find()) throw new AssertionError("missing id");
            var allocation = new byte[8 * 1024 * 1024];
            Arrays.fill(allocation, (byte) 1);
            if (args[0].equals("retain")) held.add(allocation);
            send("{\"jsonrpc\":\"2.0\",\"id\":" + id.group(1) + ",\"result\":{}}");
        }
    }

    static void send(String body) {
        System.out.print("Content-Length: " + body.length() + "\r\n\r\n" + body);
        System.out.flush();
    }
}
