// The correct half of the gate's own mutant pair (#129). pkgB.Caller reaches
// both members legally; the two mutant/pkgA/Target.java files are this class
// with one access flag turned down, and nothing else.
package pkgA;

public class Target {
  public static int g = 7;

  public static int f() {
    return 42;
  }
}
