// Mutant 2: the class-level half of the same rule. The members stay public;
// the class loses `public`, so pkgB cannot resolve pkgA/Target at all. This
// is the CONSTANT_Class path rather than the member path -- a checker that
// only looked at member flags would pass it, and JVMS 5.4.3.1 would not.
package pkgA;

class Target {
  public static int g = 7;

  public static int f() {
    return 42;
  }
}
