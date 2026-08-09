// This class is injected only into the probe application JAR; a platform-parent
// target loader must not inherit it from the system application classpath.
package host;

public final class Leak {}
