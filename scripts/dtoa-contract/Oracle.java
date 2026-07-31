import java.util.Random;

// Prints "bits<TAB>Double.toString(v)" for a corpus of doubles:
// exhaustive boundary families + N random bit patterns (seeded).
public class Oracle {
    public static void main(String[] args) {
        long n = args.length > 0 ? Long.parseLong(args[0]) : 200000;
        long seed = args.length > 1 ? Long.parseLong(args[1]) : 20260731;
        StringBuilder sb = new StringBuilder();
        // boundary families
        long[] fixed = {
            0L, 0x8000000000000000L,                       // +-0.0
            0x7FF0000000000000L, 0xFFF0000000000000L,      // +-Inf
            0x7FF8000000000000L, 0x7FF0000000000001L,      // NaNs
            1L, 2L, 3L,                                    // smallest subnormals
            0x000FFFFFFFFFFFFFL,                           // largest subnormal
            0x0010000000000000L,                           // smallest normal
            0x7FEFFFFFFFFFFFFFL,                           // largest finite
            Double.doubleToRawLongBits(0.1),
            Double.doubleToRawLongBits(3.0e-7),
            Double.doubleToRawLongBits(9007199254740993.0), // 2^53+1 (rounds)
            Double.doubleToRawLongBits(9007199254740992.0),
            Double.doubleToRawLongBits(1e300), Double.doubleToRawLongBits(1e-300),
            Double.doubleToRawLongBits(4.9E-324),
        };
        for (long b : fixed) emit(sb, b);
        // decimal form-switch thresholds: powers of ten and neighbors
        for (int e = -5; e <= 9; e++) {
            double p = Math.pow(10, e);
            for (long d = -3; d <= 3; d++)
                emit(sb, Double.doubleToRawLongBits(p) + d);
        }
        // values near 1e7 / 1e-3 written as decimal literals
        double[] lits = {1e-3, 1e7, 9999999.0, 9999999.999999998, 1.0E7,
            0.001, 0.0009999999999999998, 123.456, 2.0, 100.0, 1.5e-3,
            6.999999999999999E6, 1.0000000000000002};
        for (double v : lits) emit(sb, Double.doubleToRawLongBits(v));
        // every exponent field value with a few mantissas
        Random r = new Random(seed);
        for (int bq = 0; bq <= 2046; bq++) {
            for (int i = 0; i < 6; i++) {
                long t = i == 0 ? 0 : i == 1 ? 1 : i == 2 ? (1L << 52) - 1
                        : r.nextLong() & ((1L << 52) - 1);
                long sign = r.nextBoolean() ? 0x8000000000000000L : 0;
                emit(sb, sign | ((long) bq << 52) | t);
            }
        }
        // random raw bit patterns (includes NaN payloads etc.)
        for (long i = 0; i < n; i++) emit(sb, r.nextLong());
        // random "nice" decimals: value round-trips through short strings
        for (long i = 0; i < n / 4; i++) {
            double v = (r.nextInt(2000001) - 1000000) / Math.pow(10, r.nextInt(7));
            emit(sb, Double.doubleToRawLongBits(v));
        }
        System.out.print(sb);
    }
    static void emit(StringBuilder sb, long bits) {
        sb.append(bits).append('\t')
          .append(Double.toString(Double.longBitsToDouble(bits))).append('\n');
    }
}
