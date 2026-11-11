// Reuse the already-built candidate JAR instead of compiling a second
// compiler-sized probe. The selected Dawn entry owns its real IO handlers;
// this launcher only transfers a request path and the resulting JSON bytes.
import java.lang.reflect.InvocationTargetException;
import java.nio.file.Files;
import java.nio.file.Path;

public final class Snapshot {
    public static void main(String[] args) throws Exception {
        String module = args[0].equals("reflection")
            ? "java_signature_reflection_probe" : "java_signature_probe";
        String method = args[0].equals("reflection") ? "snapshot" : "native_snapshot";
        try {
            Object result = Class.forName(module).getMethod(method, String.class).invoke(null, args[1]);
            Files.writeString(Path.of(args[2]), (String) result);
        } catch (InvocationTargetException error) {
            throw new IllegalStateException("signature snapshot failed", error.getCause());
        }
    }
}
