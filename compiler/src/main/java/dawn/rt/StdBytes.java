package dawn.rt;

/**
 * Source-compiled runtime support for {@code std/bytes.dawn}.
 *
 * <p>Companion to {@link StdStrings}; the same reasoning applies about why this
 * is Java source rather than ASM-generated or Kotlin (see that class).
 *
 * <p>Dawn's {@code Bytes} is a JVM {@code byte[]} and its {@code Int} is a
 * {@code long}, so the signatures below are {@code byte[]}/{@code long}
 * throughout. Byte <i>values</i> are unsigned 0..255 on the Dawn side, which is
 * what makes {@code -1} available as an out-of-range sentinel for {@link #at}.
 *
 * <p>Note that {@code dawn.rt.Bytes} still exists and is still ASM-generated: it
 * carries {@code concat}, which backs the {@code Bytes ++ Bytes} operator rather
 * than any migrated function.
 */
public final class StdBytes {

    private StdBytes() {
    }

    /** The UTF-8 encoding of {@code s}. */
    public static byte[] utf8(String s) {
        return s.getBytes(java.nio.charset.StandardCharsets.UTF_8);
    }

    /**
     * {@code b} decoded with the named charset, or {@code null} when no such
     * charset exists — which the std wrapper turns into a Dawn panic.
     *
     * <p>The builtin let {@code UnsupportedEncodingException} escape as a raw
     * Java stack trace. A panic carrying the charset name is the same failure
     * reported the way every other bad argument in Dawn is.
     */
    public static String decode(byte[] b, String charset) {
        try {
            return new String(b, charset);
        } catch (java.io.UnsupportedEncodingException e) {
            return null;
        }
    }

    /** Number of bytes. */
    public static long len(byte[] b) {
        return b.length;
    }

    /** The unsigned byte at {@code i} (0..255), or {@code -1} when out of range. */
    public static long at(byte[] b, long i) {
        if (i < 0 || i >= b.length) {
            return -1;
        }
        return b[(int) i] & 0xFF;
    }

    /**
     * The bytes in {@code [start, end)}, with both ends clamped into
     * {@code [0, len]}; {@code start > end} yields an empty result rather than
     * an error, matching the builtin this replaced.
     */
    public static byte[] slice(byte[] b, long start, long end) {
        long s = clamp(start, b.length);
        long e = clamp(end, b.length);
        if (s >= e) {
            return new byte[0];
        }
        return java.util.Arrays.copyOfRange(b, (int) s, (int) e);
    }

    private static long clamp(long v, int hi) {
        if (v < 0) {
            return 0;
        }
        return v > hi ? hi : v;
    }

    /**
     * Byte index of the first occurrence of {@code needle} at or after
     * {@code from}, or {@code -1}. An empty needle matches at {@code from}.
     */
    public static long indexOf(byte[] b, byte[] needle, long from) {
        long start = from < 0 ? 0 : from;
        if (start + needle.length > b.length) {
            return -1;
        }
        outer:
        for (int i = (int) start; i + needle.length <= b.length; i++) {
            for (int k = 0; k < needle.length; k++) {
                if (b[i + k] != needle[k]) {
                    continue outer;
                }
            }
            return i;
        }
        return -1;
    }
}
