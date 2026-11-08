# Scaled MMA accumulator coverage

> Status: **current**. Exact accumulator fixtures and their acceptance criteria.

Add two cases through the existing five argument interface: FP8 E5M2/E8M0
V32 and FP4 E2M1/E8M0 V16, both with the existing 64 by 64 shape.
Keep the existing zero accumulator cases and reuse their operand and scale
corpus. This change covers accumulator semantics without expanding the type
combination matrix or parameter families.

Generate the f32 accumulator with two dimensional iota. For lane
`row * 64 + col`, its value is `lane + 1` at even lanes and its negative at
odd lanes. Every lane is nonzero and unique. Products and all partial sums,
including the accumulator, remain exactly representable in f32 with absolute
values below 2^24. Keep the existing exact comparison. The host reference
constructs the accumulator independently with scalar integer arithmetic;
a separate integer block dot oracle checks every answer and the guard tail.

First inject three legal faults: drop the accumulator, transpose its lanes,
and negate it. Both new cases must assemble and fail numerically at named
lanes while the existing cases remain exact. Then verify the clean program.
Run numerical cases on sm100; require explicit assembly rejection and SKIP
on sm90 and sm86, with all existing device families still executed.

Run mutation anchor preflight and anchor guard, including ASan variants,
the related CPU gates, and the complete golden suite. Freeze the inputs,
then record complete sm100, sm90, and sm86 runs in that order, checking
the toolchain pin, driver, and input digest before and after each run.
Require the complete gate suite at the final SHA, independent bundle
verification, and all thirteen tile checks before marking the PR ready.
Special value answers, opcodes, toolchain versions, and pins stay fixed.
This work makes no performance claim.


## Validation

Each new case checks 4096 results and eight guard lanes. The integer corpus
bounds every partial sum, including the accumulator, below 2^24. The
independent reference and integer block dot oracle agree with the clean
sm100 execution. All 508 inherited golden objects remain unchanged.

All three legal faults ran before the first clean numerical execution.
Each fault changes only the new cases; eleven existing architecture cases
remain exact. These are the first wrong lanes, shown as actual / expected:

| Fault | FP8 E5M2/E8M0 V32 | FP4 E2M1/E8M0 V16 |
|---|---|---|
| Dropped accumulator | lane 0: -10 / -9 | lane 0: -97 / -96 |
| Transposed accumulator | lane 1: -3 / -70 | lane 1: 183 / 116 |
| Negated accumulator | lane 0: -11 / -9 | lane 0: -98 / -96 |

The complete golden suite passes all 401 work items, including trace twice,
JVM and native parity, assembly, and disassembly. The CPU interpreter,
reference, documentation, source map, and anchor checks also pass.
Fresh complete sm100, sm90, and sm86 recordings share one frozen input
digest. Both lower targets explicitly reject the two new goldens, with
accepted sm100 assembly counterparts, and record the numerical cases as
SKIP. All existing device families still run in each complete recording.
The feature table cites the sm100 results and the three numerical faults.
