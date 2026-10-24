// StrictMath is an executable reference only. No OpenJDK implementation is
// copied into the Dawn port; corrected algorithms use separate MPFR witnesses.
import java.io.*;
import java.util.*;

class Oracle {
    static double run(String op, double x, double y, double z) {
        return switch (op) {
            case "exp" -> StrictMath.exp(x);
            case "expm1" -> StrictMath.expm1(x);
            case "log" -> StrictMath.log(x);
            case "log1p" -> StrictMath.log1p(x);
            case "log10" -> StrictMath.log10(x);
            case "sin" -> StrictMath.sin(x);
            case "cos" -> StrictMath.cos(x);
            case "tan" -> StrictMath.tan(x);
            case "asin" -> StrictMath.asin(x);
            case "acos" -> StrictMath.acos(x);
            case "atan" -> StrictMath.atan(x);
            case "atan2" -> StrictMath.atan2(x, y);
            case "sinh" -> StrictMath.sinh(x);
            case "cosh" -> StrictMath.cosh(x);
            case "tanh" -> StrictMath.tanh(x);
            case "cbrt" -> StrictMath.cbrt(x);
            case "pow" -> StrictMath.pow(x, y);
            case "hypot" -> StrictMath.hypot(x, y);
            case "sqrt" -> StrictMath.sqrt(x);
            case "fma" -> StrictMath.fma(x, y, z);
            case "floor" -> StrictMath.floor(x);
            case "ceil" -> StrictMath.ceil(x);
            case "trunc" -> Math.copySign(StrictMath.floor(StrictMath.abs(x)), x);
            case "round_even" -> StrictMath.rint(x);
            case "round" -> {
                double t = Math.copySign(StrictMath.floor(StrictMath.abs(x)), x);
                double d = x - t;
                yield d >= 0.5 ? t + 1 : d <= -0.5 ? t - 1 : t;
            }
            default -> throw new IllegalArgumentException(op);
        };
    }
    public static void main(String[] args) throws Exception {
        var v = Runtime.version();
        if (v.feature() != 21 || v.interim() != 0 || v.update() != 2)
            throw new IllegalStateException("oracle requires Java 21.0.2, got " + v);
        var in = new BufferedReader(new InputStreamReader(System.in));
        for (String line; (line = in.readLine()) != null;) {
            var p = line.split(" ");
            double[] x = new double[3];
            for (int i = 0; i < 3; i++) x[i] = Double.longBitsToDouble(Long.parseLong(p[i + 1]));
            System.out.println(Double.doubleToLongBits(run(p[0], x[0], x[1], x[2])));
        }
    }
}
