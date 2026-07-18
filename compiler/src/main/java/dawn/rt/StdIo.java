package dawn.rt;

/**
 * Source-compiled runtime support for {@code std/io.dawn}.
 *
 * <p>Third of the reflectable runtime classes, after {@link StdStrings} and
 * {@link StdBytes}; the same reasoning applies about why it is Java source.
 *
 * <p>Unlike those two, nothing here is pure — every method is reached from a
 * Dawn function typed {@code !io}, so no {@code unsafe_pure} is involved on the
 * other side. The methods that can fail simply throw: {@code java_try} on the
 * Dawn side turns a {@code Throwable} into {@code Err(throwable.toString())},
 * which is exactly the error string the builtins produced.
 */
public final class StdIo {

    private StdIo() {
    }

    /** Print without a trailing newline. */
    public static void print(String s) {
        System.out.print(s);
    }

    /** Print followed by a newline. */
    public static void println(String s) {
        System.out.println(s);
    }

    // One shared reader: constructing a BufferedReader per call would let the
    // previous one's buffer swallow input that the next call should have seen.
    private static java.io.BufferedReader stdin;

    /** One line from stdin, or {@code null} at end of input. */
    public static String readLine() throws java.io.IOException {
        if (stdin == null) {
            // UTF-8 explicitly, not the platform default: that is what the builtin
            // did, and a machine with a non-UTF-8 default locale would otherwise
            // start decoding stdin differently after this migration.
            stdin = new java.io.BufferedReader(
                new java.io.InputStreamReader(System.in, java.nio.charset.StandardCharsets.UTF_8));
        }
        return stdin.readLine();
    }

    /** Whether {@code path} names a directory. */
    public static boolean isDir(String path) {
        return java.nio.file.Files.isDirectory(java.nio.file.Path.of(path));
    }

    /** The whole file as a UTF-8 string. */
    public static String readFile(String path) throws java.io.IOException {
        return java.nio.file.Files.readString(java.nio.file.Path.of(path));
    }

    /**
     * Write {@code content} to {@code path}.
     *
     * <p>Returns nothing. Until 2026-07-19 this handed back {@code String.length()}
     * — UTF-16 units, which is neither characters nor bytes, so the one number a
     * caller might have wanted (how many bytes landed on disk) was not the number
     * it got. No call site in either repo read it; both tests that did only
     * printed it. A wrong answer nobody asked for is worse than no answer.
     */
    public static void writeFile(String path, String content) throws java.io.IOException {
        java.nio.file.Path p = java.nio.file.Path.of(path);
        java.nio.file.Path parent = p.getParent();
        if (parent != null) {
            // the builtin created missing parents; a golden test pins it
            java.nio.file.Files.createDirectories(parent);
        }
        java.nio.file.Files.writeString(p, content);
    }

    /** The entry names directly under {@code path}. See {@link #args} on the return type. */
    public static Object listNames(String path) throws java.io.IOException {
        try (java.util.stream.Stream<java.nio.file.Path> s =
                 java.nio.file.Files.list(java.nio.file.Path.of(path))) {
            java.util.List<String> out = new java.util.ArrayList<>();
            for (java.nio.file.Path p : s.toList()) {
                out.add(p.getFileName().toString());
            }
            // sorted: Files.list gives no order guarantee, and both the builtin this
            // replaced and spec §11 promise sorted names
            java.util.Collections.sort(out);
            return out;
        }
    }
}
