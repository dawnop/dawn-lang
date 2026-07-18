package dawn.rt;

/**
 * Source-compiled runtime support for the bundled standard library.
 *
 * <p>Most of {@code dawn.rt} is emitted by ASM at codegen time, which means the
 * checker cannot reflect on it and the bundled std cannot {@code use java} it
 * (docs/pure-ffi-design.md, section nine). A class compiled from source lives in
 * the compiler jar instead, which {@code use java} can see — so std forwards
 * here and wraps the call in {@code unsafe_pure}.
 *
 * <p>Deliberately <b>Java, not Kotlin</b>: these classes are copied verbatim into
 * every program Dawn builds, and a Kotlin class would drag
 * {@code kotlin.jvm.internal.Intrinsics} — and thus the whole Kotlin stdlib —
 * into each one. Plain Java keeps a built jar self-contained and dependency-free.
 *
 * <p>Two conventions shape the signatures: Dawn's {@code Int} is a JVM
 * {@code long}, and Dawn strings are measured in Unicode code points (so does
 * {@code str_len}), so anything index- or length-shaped counts code points too —
 * otherwise std would disagree with the builtins on astral text.
 *
 * <p>Every method here is pure: same input, same output, no observable effect.
 * That is what the {@code unsafe_pure} on the Dawn side vouches for.
 */
public final class StdStrings {

    private StdStrings() {
    }

    private static int[] codePoints(String s) {
        return s.codePoints().toArray();
    }

    /**
     * {@code s} left-padded with {@code pad} until it is {@code width} code
     * points wide. Returns {@code s} unchanged when it is already wide enough or
     * {@code pad} is empty; the filler is truncated to land exactly on width.
     */
    public static String padStart(String s, long width, String pad) {
        long have = codePoints(s).length;
        if (have >= width || pad.isEmpty()) {
            return s;
        }
        int[] padCps = codePoints(pad);
        StringBuilder fill = new StringBuilder();
        long need = width - have;
        int i = 0;
        while (fill.codePointCount(0, fill.length()) < need) {
            fill.appendCodePoint(padCps[i % padCps.length]);
            i++;
        }
        return fill.toString() + s;
    }

    /**
     * The code points of {@code s} in {@code [from, to)}, or {@code null} when
     * that range is not valid.
     *
     * <p>Out-of-range is reported as {@code null} — which the checker hands to
     * Dawn as {@code None} — rather than thrown, because {@code dawn.rt.PanicError}
     * is ASM-generated and so cannot be referenced from source. The std wrapper
     * turns the {@code None} back into the same panic via {@code expect}.
     */
    public static String substring(String s, long from, long to) {
        long n = s.codePointCount(0, s.length());
        if (from < 0 || from > to || to > n) {
            return null;
        }
        int start = s.offsetByCodePoints(0, (int) from);
        int end = s.offsetByCodePoints(0, (int) to);
        return s.substring(start, end);
    }

    /** Number of Unicode code points in {@code s}. */
    public static long len(String s) {
        return s.codePointCount(0, s.length());
    }

    /** {@code s} with surrounding whitespace removed. */
    public static String trim(String s) {
        return s.strip();
    }

    /** {@code s} lowercased, locale-independently. */
    public static String toLower(String s) {
        return s.toLowerCase(java.util.Locale.ROOT);
    }

    /** {@code s} uppercased, locale-independently. */
    public static String toUpper(String s) {
        return s.toUpperCase(java.util.Locale.ROOT);
    }

    /** Whether {@code sub} occurs anywhere in {@code s}. */
    public static boolean contains(String s, String sub) {
        return s.contains(sub);
    }

    /** Whether {@code s} begins with {@code prefix}. */
    public static boolean startsWith(String s, String prefix) {
        return s.startsWith(prefix);
    }

    /** Whether {@code s} ends with {@code suffix}. */
    public static boolean endsWith(String s, String suffix) {
        return s.endsWith(suffix);
    }

    /**
     * Code-point index of the first occurrence of {@code sub}, or {@code -1}.
     *
     * <p>The sentinel, rather than an {@code Option}, is what crosses the FFI
     * boundary: Dawn ADTs are not expressible as a Java return type. The std
     * wrapper turns {@code -1} back into {@code None}.
     */
    public static long indexOf(String s, String sub) {
        int u = s.indexOf(sub);
        return u < 0 ? -1 : s.codePointCount(0, u);
    }

    /** Code-point index of the last occurrence of {@code sub}, or {@code -1}. */
    public static long lastIndexOf(String s, String sub) {
        int u = s.lastIndexOf(sub);
        return u < 0 ? -1 : s.codePointCount(0, u);
    }

    /**
     * The one-code-point string for {@code c}, or {@code null} when {@code c} is
     * not a valid code point (the std wrapper turns that into the panic).
     *
     * <p>The narrowing to {@code int} happens before the validity check, matching
     * what the builtin's bytecode did — widening it would be a silent semantic
     * change riding along with a migration.
     */
    public static String charToString(long c) {
        int cp = (int) c;
        if (!Character.isValidCodePoint(cp)) {
            return null;
        }
        return String.valueOf(Character.toChars(cp));
    }

    /** {@code s} with its code points reversed (surrogate pairs stay intact). */
    public static String reverse(String s) {
        int[] cps = codePoints(s);
        StringBuilder out = new StringBuilder(s.length());
        for (int i = cps.length - 1; i >= 0; i--) {
            out.appendCodePoint(cps[i]);
        }
        return out.toString();
    }
}
