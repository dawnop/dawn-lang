// The referring side. Its constant pool names pkgA/Target once as a class and
// twice as a member, which is the shape K-A3 broke: a method body reaching a
// member of another class. The body is never run by the gate -- that is the
// point, since the JVM would only access-check these at the instruction.
//
// `iadd; ireturn` (60 ac) is also the byte pair selftest.sh rewrites to build
// the bytecode-verifier mutant, so keep the addition.
package pkgB;

import pkgA.Target;

public class Caller {
  public static int call() {
    return Target.f() + Target.g;
  }
}
