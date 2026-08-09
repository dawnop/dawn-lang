// B-side SAM metadata differs from A-side metadata to expose loader reuse.
package fixture;

public interface Action {
  void onlyB(String value);
}
