// Mutant 1: the K-A3 defect, reduced. Same class, same members, same
// descriptors -- `public` turned down to `private`. pkgB/Caller.class is
// compiled against the legal version and dropped on top of this one, exactly
// how the closure lowering produced a caller compiled for one access level
// and a callee emitted with another.
//
// `use` exists so javac does not reject the members as unused; it also keeps
// the class from being trivially empty.
package pkgA;

public class Target {
  private static int g = 7;

  private static int f() {
    return 42;
  }

  static int use() {
    return f() + g;
  }
}
