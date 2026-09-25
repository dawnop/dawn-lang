package contract;

import java.lang.reflect.Method;
import java.util.Arrays;

/** Compare live cold contexts independently from the entry proof's own equality. */
public final class BoundedEntryProofTrace {
    private static Method method(Class<?> owner, String name) {
        return Arrays.stream(owner.getMethods()).filter(m -> m.getName().equals(name)).findFirst().orElseThrow();
    }

    public static void main(String[] args) throws Exception {
        Class<?> reference = Class.forName("dawn$pkg$selfhost.contract.reference");
        Object suite = method(reference, "proof_cases").invoke(null);
        long count = (Long) method(reference, "proof_pair_count").invoke(null, suite);
        long accepted = (Long) method(reference, "proof_accept_count").invoke(null, suite);
        long refused = (Long) method(reference, "proof_refuse_count").invoke(null, suite);
        if (count != 16 || accepted != 16 || refused != 4) {
            throw new AssertionError("bounded entry proof denominator: " + count + "/" + accepted + "/" + refused);
        }
        for (long i = 0; i < count; i++) {
            Object pair = method(reference, "proof_pair_at").invoke(null, suite, i);
            GenericTrace.equalBodies(pair.getClass().getField("cold").get(pair),
                    pair.getClass().getField("actual").get(pair), "bounded entry proof " + i);
        }
        System.out.println("PASS: bounded entry proof 16 accepted entries, 16 full cold histories, 4 excluded entries refused");
    }
}
