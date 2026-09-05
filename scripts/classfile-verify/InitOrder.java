// NEW initializes the class before argument evaluation. A constructor-body
// assertion alone cannot see reordering, especially if the first argument
// exits the loop before any constructor body runs.
package operandprobe;

public final class InitOrder {
  static { System.out.println("initialize"); }
  public InitOrder(int value) { System.out.println("construct " + value); }
}
