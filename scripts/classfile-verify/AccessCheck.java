// Symbolic-reference resolution for the classfile gate (TEST-01, #129): for
// every CONSTANT_Class / Fieldref / Methodref / InterfaceMethodref an emitted
// class names, resolve it and check the referring class may reach it.
//
// Why a second pass exists at all. Verify.java force-links classes, and
// linking is not resolution: the JVM resolves a symbolic reference at the
// moment an instruction that names it first executes, so a method body nobody
// calls is never resolved and its references are never access-checked. That
// blind spot is not hypothetical. K-A3 (closure lowering, 2026-08-03) emitted
// hoisted lambda bodies as ACC_PRIVATE; under invokedynamic that was fine
// because LambdaMetafactory gets a private-access Lookup, but once the bodies
// became standalone classes the first real run died with IllegalAccessError
// inside std.io.read_file -- the compiler could not read its own first file.
// The gate printed "1946 classes, 0 illegal" over a corpus that held it.
// Measured again on this branch with a hand-built mutant, and selftest.sh is
// that measurement kept runnable rather than remembered.
//
// The access check is the JVM's own, not a re-implementation of JVMS 5.4.4.
// `MethodHandles.privateLookupIn(referrer, lookup())` yields a Lookup whose
// lookup class is the referrer with full power, i.e. exactly the access a
// method body inside that class has; `unreflect` / `accessClass` on it then
// run the real Reflection.verifyMemberAccess. Hand-written rules would have
// to get nest mates, protected-in-subclass and runtime packages right, and
// would be a second opinion about the very thing under test.
//
// Fatal: a member that is private, package-private or protected out of the
// referrer's reach; a CONSTANT_Class the referrer may not resolve; and a
// member that does not exist at all, NoSuchMethodError's static shape.
//
// Four deliberate limits, so this header does not overstate the way the one
// it sits next to did:
//   * the receiver-type clause of protected access (JVMS 5.4.4 final
//     paragraph) is a property of the instruction's operand stack, not of the
//     constant pool, and is not checked here;
//   * neither is anything else about the instruction. A pool entry does not
//     say which opcode names it, so the IncompatibleClassChangeError family
//     -- invokestatic on an instance method, invokevirtual on an interface,
//     putfield on a static -- is out of scope;
//   * a reference whose owner class is absent from both the emitted directory
//     and the class path cannot be resolved, so it is counted as `unknown`
//     and reported, never silently dropped -- absence of a jar is not
//     illegal bytecode, same rule Verify.java uses;
//   * a missing member of an emitted `dawn/rt/*` class is counted as
//     `freight-pruned` rather than failed, because reach.dawn removes those
//     on purpose; see the comment at that branch.
import java.lang.invoke.MethodHandles;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Member;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

final class AccessCheck {
  /** One symbolic reference out of a constant pool. */
  record Ref(int tag, String owner, String name, String desc) {}

  /** What a whole directory's scan found. */
  static final class Result {
    int classesScanned;
    int refsChecked;
    int unknown;
    int pruned;
    final List<String> failures = new ArrayList<>();
    final List<String> unknownNotes = new ArrayList<>();
  }

  private AccessCheck() {}

  // ---------------------------------------------------------------- pool

  private static int u1(byte[] b, int off) {
    return b[off] & 0xff;
  }

  private static int u2(byte[] b, int off) {
    return ((b[off] & 0xff) << 8) | (b[off + 1] & 0xff);
  }

  /**
   * Every class and member reference this class file names.
   *
   * <p>Hand-rolled rather than read through the vendored ASM, for the reason
   * constpool-scan.py gives: a scanner that used the emitter's own library to
   * check the emitter's own output would go blind exactly where the library is
   * wrong.
   */
  static List<Ref> refs(byte[] b) {
    return refs(b, false);
  }

  // Freight also observes declaration descriptors: a parameter/field can
  // name a runtime type without any instruction carrying a CONSTANT_Class.
  // Keep the existing access check's scope unchanged; only its freight
  // reader opts into these additional type references.
  static List<Ref> refs(byte[] b, boolean declarationTypes) {
    if (b.length < 10 || u1(b, 0) != 0xca || u1(b, 1) != 0xfe || u1(b, 2) != 0xba
        || u1(b, 3) != 0xbe) {
      throw new IllegalArgumentException("not a class file");
    }
    int count = u2(b, 8);
    String[] utf8 = new String[count];
    int[] classNameIx = new int[count];
    int[] natName = new int[count];
    int[] natDesc = new int[count];
    int[] refClass = new int[count];
    int[] refNat = new int[count];
    int[] methodType = new int[count];
    int[] tag = new int[count];
    int off = 10;
    for (int i = 1; i < count; i++) {
      int t = u1(b, off);
      off++;
      tag[i] = t;
      switch (t) {
        case 1 -> {
          int n = u2(b, off);
          utf8[i] = new String(b, off + 2, n, java.nio.charset.StandardCharsets.UTF_8);
          off += 2 + n;
        }
        case 3, 4 -> off += 4;
        case 5, 6 -> {
          off += 8;
          i++; // long and double take two pool slots
        }
        case 7, 8, 16, 19, 20 -> {
          if (t == 7) {
            classNameIx[i] = u2(b, off);
          }
          if (t == 16) methodType[i] = u2(b, off);
          off += 2;
        }
        case 9, 10, 11 -> {
          refClass[i] = u2(b, off);
          refNat[i] = u2(b, off + 2);
          off += 4;
        }
        case 12 -> {
          natName[i] = u2(b, off);
          natDesc[i] = u2(b, off + 2);
          off += 4;
        }
        case 15 -> off += 3;
        case 17, 18 -> off += 4;
        default -> throw new IllegalArgumentException("unknown constant tag " + t + " at " + i);
      }
    }
    List<Ref> out = new ArrayList<>();
    for (int i = 1; i < count; i++) {
      if (tag[i] == 7) {
        out.add(new Ref(7, utf8[classNameIx[i]], null, null));
      } else if (tag[i] == 9 || tag[i] == 10 || tag[i] == 11) {
        int c = refClass[i];
        int nt = refNat[i];
        out.add(new Ref(tag[i], utf8[classNameIx[c]], utf8[natName[nt]], utf8[natDesc[nt]]));
      }
    }
    if (declarationTypes) {
      for (int i = 1; i < count; i++) {
        if (methodType[i] != 0) descriptorRefs(utf8[methodType[i]], out);
      }
      // access_flags, this_class, super_class, then interfaces.
      off += 6;
      int interfaces = u2(b, off);
      off += 2 + 2 * interfaces;
      // The field and method tables have the same member_info layout.
      for (int table = 0; table < 2; table++) {
        int members = u2(b, off);
        off += 2;
        for (int i = 0; i < members; i++) {
          descriptorRefs(utf8[u2(b, off + 4)], out);
          int attrs = u2(b, off + 6);
          off += 8;
          for (int j = 0; j < attrs; j++) {
            int size = (u2(b, off + 2) << 16) | u2(b, off + 4);
            off += 6 + size;
          }
        }
      }
    }
    return out;
  }

  private static void descriptorRefs(String desc, List<Ref> out) {
    for (int i = 0; i < desc.length(); i++) {
      if (desc.charAt(i) == 'L') {
        int end = desc.indexOf(';', i);
        if (end < 0) throw new IllegalArgumentException("invalid descriptor " + desc);
        out.add(new Ref(7, desc.substring(i + 1, end), null, null));
        i = end;
      }
    }
  }

  // ------------------------------------------------------------ resolution

  private static String typeDesc(Class<?> c) {
    if (c == int.class) {
      return "I";
    } else if (c == long.class) {
      return "J";
    } else if (c == double.class) {
      return "D";
    } else if (c == float.class) {
      return "F";
    } else if (c == boolean.class) {
      return "Z";
    } else if (c == byte.class) {
      return "B";
    } else if (c == short.class) {
      return "S";
    } else if (c == char.class) {
      return "C";
    } else if (c == void.class) {
      return "V";
    } else if (c.isArray()) {
      return c.getName().replace('.', '/');
    } else {
      return "L" + c.getName().replace('.', '/') + ";";
    }
  }

  private static String methodDesc(Class<?>[] params, Class<?> ret) {
    StringBuilder sb = new StringBuilder("(");
    for (Class<?> p : params) {
      sb.append(typeDesc(p));
    }
    return sb.append(')').append(typeDesc(ret)).toString();
  }

  /** JVMS 5.4.3.3: the class itself, then superclasses, then superinterfaces. */
  private static Member findMethod(Class<?> owner, String name, String desc) {
    Deque<Class<?>> queue = new ArrayDeque<>();
    Set<Class<?>> seen = new HashSet<>();
    for (Class<?> c = owner; c != null; c = c.getSuperclass()) {
      Member m = declaredMethod(c, name, desc);
      if (m != null) {
        return m;
      }
      queue.add(c);
    }
    while (!queue.isEmpty()) {
      Class<?> c = queue.poll();
      for (Class<?> i : c.getInterfaces()) {
        if (seen.add(i)) {
          Member m = declaredMethod(i, name, desc);
          if (m != null) {
            return m;
          }
          queue.add(i);
        }
      }
    }
    return null;
  }

  private static Member declaredMethod(Class<?> c, String name, String desc) {
    if (name.equals("<init>")) {
      for (Constructor<?> k : c.getDeclaredConstructors()) {
        if (methodDesc(k.getParameterTypes(), void.class).equals(desc)) {
          return k;
        }
      }
      return null;
    }
    for (Method m : c.getDeclaredMethods()) {
      if (m.getName().equals(name)
          && methodDesc(m.getParameterTypes(), m.getReturnType()).equals(desc)) {
        return m;
      }
    }
    return null;
  }

  /** JVMS 5.4.3.2: the class itself, then its superinterfaces, then its superclass. */
  private static Member findField(Class<?> owner, String name, String desc) {
    for (Class<?> c = owner; c != null; c = c.getSuperclass()) {
      for (Field f : c.getDeclaredFields()) {
        if (f.getName().equals(name) && typeDesc(f.getType()).equals(desc)) {
          return f;
        }
      }
      for (Class<?> i : c.getInterfaces()) {
        Member m = findField(i, name, desc);
        if (m != null) {
          return m;
        }
      }
    }
    return null;
  }

  // ---------------------------------------------------------------- check

  /**
   * A public member of a public class is reachable from anywhere in the unnamed
   * module, and that is the overwhelming majority of an emitted pool. Skipping
   * the Lookup for those is what keeps this pass cheap; every other shape goes
   * through the real check.
   */
  private static boolean trivially(Member m) {
    return Modifier.isPublic(m.getModifiers())
        && Modifier.isPublic(m.getDeclaringClass().getModifiers());
  }

  static void scan(Path dir, ClassLoader cl, List<String> names, Result r) {
    MethodHandles.Lookup here = MethodHandles.lookup();
    Map<String, Object> resolved = new HashMap<>(); // owner#name#desc -> Member or NOT_FOUND
    for (String n : names) {
      Class<?> referrer;
      byte[] bytes;
      try {
        referrer = Class.forName(n, false, cl);
        bytes = Files.readAllBytes(dir.resolve(n.replace('.', '/') + ".class"));
      } catch (Throwable t) {
        r.unknown++;
        r.unknownNotes.add("cannot read " + n + ": " + t);
        continue;
      }
      MethodHandles.Lookup as;
      try {
        as = MethodHandles.privateLookupIn(referrer, here);
      } catch (Throwable t) {
        r.unknown++;
        r.unknownNotes.add("no lookup in " + n + ": " + t);
        continue;
      }
      r.classesScanned++;
      for (Ref ref : refs(bytes)) {
        if (ref.owner() == null || ref.owner().startsWith("[")) {
          continue; // array types: members are Object's, and Object is public
        }
        Class<?> owner;
        try {
          owner = Class.forName(ref.owner().replace('/', '.'), false, cl);
        } catch (Throwable t) {
          r.unknown++;
          r.unknownNotes.add(n + " -> " + ref.owner() + ": " + t);
          continue;
        }
        r.refsChecked++;
        if (ref.tag() == 7) {
          try {
            as.accessClass(owner);
          } catch (IllegalAccessException e) {
            r.failures.add("ACCESS FAIL " + n + " -> class " + ref.owner() + ": " + e.getMessage());
          } catch (Throwable t) {
            r.unknown++;
            r.unknownNotes.add(n + " -> class " + ref.owner() + ": " + t);
          }
          continue;
        }
        if (ref.owner().startsWith("java/lang/invoke/")) {
          continue; // signature-polymorphic: no declared method matches the descriptor
        }
        String key = ref.owner() + "#" + ref.name() + "#" + ref.desc();
        Object hit = resolved.get(key);
        if (hit == null) {
          hit = ref.tag() == 9
              ? findField(owner, ref.name(), ref.desc())
              : findMethod(owner, ref.name(), ref.desc());
          resolved.put(key, hit == null ? Boolean.FALSE : hit);
          if (hit == null) {
            hit = Boolean.FALSE;
          }
        }
        if (hit == Boolean.FALSE) {
          if (ref.owner().startsWith("dawn/rt/")) {
            // Freight pruning, not a defect: selfhost/src/ir/reach.dawn drops the
            // Unicode-table intrinsics a program cannot reach out of the
            // emitted dawn/rt classes, and leans on lazy resolution to make
            // the dangling reference from unreachable std code harmless
            // ("a pruned method is absent, not stubbed"). Measured shape on
            // this branch: twelve references across five of the eight corpora,
            // every one of them std.str naming
            // dawn/rt/Strings.{str_lower,str_upper,char_is_space}. Whether the
            // pruning itself is right is scripts/table-freight's question --
            // it owns the NoSuchMethodError this would otherwise duplicate --
            // and answering it here would mean re-implementing reach.dawn.
            r.pruned++;
            continue;
          }
          r.failures.add("RESOLVE FAIL " + n + " -> " + ref.owner() + "." + ref.name()
              + ref.desc() + ": no such " + (ref.tag() == 9 ? "field" : "method"));
          continue;
        }
        Member m = (Member) hit;
        if (trivially(m)) {
          continue;
        }
        try {
          if (m instanceof Field f) {
            as.unreflectGetter(f);
          } else if (m instanceof Constructor<?> k) {
            as.unreflectConstructor(k);
          } else {
            as.unreflect((Method) m);
          }
        } catch (IllegalAccessException e) {
          r.failures.add("ACCESS FAIL " + n + " -> " + ref.owner() + "." + ref.name() + ref.desc()
              + ": " + e.getMessage());
        } catch (Throwable t) {
          r.unknown++;
          r.unknownNotes.add(n + " -> " + ref.owner() + "." + ref.name() + ": " + t);
        }
      }
    }
  }
}
