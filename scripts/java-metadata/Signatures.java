// Small real class files expose reflection rules that JDK-only queries cannot
// isolate: hidden parents, generic bridges, diamonds and synthetic members.
// The harness only inspects these classes; it never executes their methods.
package fixture;

import java.io.IOException;

class Hidden {
    public int length() { return 3; }
    public static final int INHERITED = 3;
}

public final class Signatures {
    public static final class Facade extends Hidden { }

    public static class Base<T> {
        public static final String CODE = "base";
        public Object value() { return null; }
        public int compare(T value) { return 1; }
        public int syntheticOnly() { return 1; }
    }

    public static final class Child extends Base<String> {
        public static final int CODE = 1;
        @Override public String value() { return "child"; }
        @Override public int compare(String value) { return 2; }
    }

    public interface Left {
        int SHARED = 1;
        static int staticOnly() { return 1; }
        default int defaulted() { return 1; }
        void run(String value);
    }

    public interface Right {
        int SHARED = 2;
        void run(String value);
    }

    public interface Diamond extends Left, Right { }

    public interface StringSam {
        boolean equals(Object other);
        int hashCode();
        String toString();
        void take(String value);
    }

    public interface NotSam {
        void first(String value);
        void second(String value);
    }

    public interface Wider { Object get(); }
    public interface Narrower extends Wider { @Override String get(); }

    public static final class Constructors {
        public Constructors() throws IOException { }
        public Constructors(String... values) throws IOException, IllegalArgumentException { }
        public Constructors(int synthetic) { }
    }

    public static final class Utilities {
        public static int[] ints() { return null; }
        public static int[][] matrix() { return null; }
        public static String[] strings() { return null; }
        public static void objects(Object[] values) { }
        public static void integers(int[] values) { }
        public static void stringSam(StringSam callback) { }
    }

    public static class Nested { }

    public static Class<?> local() {
        class Local { public String value() { return "local"; } }
        return Local.class;
    }

    public static Object anonymous() { return new Object() { }; }
}
