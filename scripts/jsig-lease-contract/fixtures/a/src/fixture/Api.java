// The A-side API deliberately shares its binary name with the B-side class so
// a merged or reused target loader produces an observable signature mismatch.
package fixture;

public final class Api extends Parent {
  public static final int A_FIELD = 1;

  public Api(int ignored) {}

  public void onlyA() {}
}
