package fixture;

/**
 * The Java shapes a JDK-only subject cannot supply: an UPPERCASE instance
 * method, and a field and a method of the same name in both spellings.
 *
 * The JDK has neither. A scan of every exported package in java.* finds four
 * uppercase methods (Math.IEEEremainder, StrictMath.IEEEremainder, Date.UTC and
 * one internal), all static, and no public class at all with a public field and
 * a public method sharing a name. Java keeps fields and methods in separate
 * namespaces, so the pair is legal and ordinary Java; Dawn used to reach only
 * one of the two, and only by how the name was capitalized (SYN-09).
 *
 * Every member is public and non-final so that reflection sees exactly what the
 * declaration says, and the return values are distinct so that a call resolving
 * to the wrong member is caught by its value rather than by its type.
 */
public class Syn09 {
  public static final int UPPER_FIELD = 7;
  public static final String lower_field = "lf";

  public static int UpperStatic(int n) { return n + 1; }
  public static int lowerStatic(int n) { return n + 2; }

  public int UpperInstance(int n) { return n + 3; }
  public int lowerInstance(int n) { return n + 4; }

  /** A field and a method called PICK: the call suffix is the only difference. */
  public static final int PICK = 11;

  public static int PICK(int n) { return n + 100; }

  /** The same pair spelled lowercase, so neither reading can be case-driven. */
  public static final int pick = 21;

  public static int pick(int n) { return n + 200; }

  public int inst = 5;
}
