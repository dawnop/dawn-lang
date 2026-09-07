// Real Java descriptors keep the callback checker and bridge under test together.
package fixture;

public final class SamValues {
    public interface ByteSource { byte get(); }
    public interface ShortSource { short get(); }
    public interface IntSource { int get(); }
    public interface BytesSource { byte[] get(); }
    public interface BytesSink { long size(byte[] value); }
    public interface ObjectSource { Object get(); }
    public static long byteValue(ByteSource f) { return f.get(); }
    public static long shortValue(ShortSource f) { return f.get(); }
    public static long intValue(IntSource f) { return f.get(); }
    public static byte[] bytesValue(BytesSource f) { return f.get(); }
    public static long bytesSink(BytesSink f) { return f.size(new byte[]{1, 2, 3}); }
    public static long nullSink(BytesSink f) { return f.size(null); }
    public static byte[] absent() { return null; }
    public static long objectBytes(ObjectSource f) { return ((byte[]) f.get()).length; }
}
