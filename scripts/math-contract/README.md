# Binary64 host mathematics contract

All runtime algorithms are pure Dawn in `std/math.dawn`. The C snapshots are
provenance and retained error analyses, never a second runtime implementation.
The license check verifies every pinned digest and every distinct Sun notice in
both source and embedded std.

The permanent corpus compares raw bits for direct calls, function values and
111 actual folded constants. Only NaNs are canonicalized. The input contains
special values, every log exponent layer, every representable binary power,
exact root midpoint neighborhoods, fma cancellation and extreme exponents,
large trig reduction and the recorded accuracy failures with adjacent inputs.

- `gen.py --check` reruns Java **21.0.2** StrictMath and checks committed products
  and their SHA-256 values. `oracle-differences.json` explicitly selects MPFR for
  exp2/log2 and the four corrected functions. The frozen directed intervals
  decide nearest-even bits using exact rational conversion; CI needs no MPFR.
- `run.sh` executes JVM, native and ASan, then all four controls. This is wired
  into native-diff-2; `math_contract` is also an ordinary spike-native corpus.
- `run.py --wasm --driver PATH` reuses wasm-contract's existing native compiler
  and SDK. Both compilers emit actual constants, their C artifacts must agree,
  and each artifact is executed on native and wasm. Software fma is linked and
  run; the wasm leak ledger must be zero.
- `audit.py` is the offline MPFR audit. It decides real-error bounds adaptively,
  rather than treating integer bit distance as true error. The committed audit
  records source, generator, auditor, binary and input/output digests, MPFR
  version, per-function maxima and exact worst-case intervals. It is finite
  search evidence, alongside the source analyses and correction bounds in
  `docs/std-math-design.md`.

Regenerate the ordinary corpus with `python3 scripts/math-contract/gen.py`.
Regenerate corrected-function witnesses separately with `--record-mpfr`, which
requires `libmpfr.so.6`. There is no command to record an implementation's output
as an expectation.

To reproduce the extended accuracy search after building the corpus executable:

```sh
python3 scripts/math-contract/gen.py --inputs-only INPUT --extra 12000
BINARY < INPUT > OUTPUT
python3 scripts/math-contract/audit.py --inputs INPUT --actual OUTPUT \
  --binary BINARY --backend 'native C, clang 18.1.3, -O2 -ffp-contract=off' --out REPORT
```

The fixed search includes the original K1 tanh LCG stream, neighboring failures,
all exp2 reduction cells, powers near positive and negative one with huge
integer exponents, and disparate hypot/atan2 scales. Changing the generator or
algorithm requires a new offline audit before the gate accepts its evidence.

The controls delete exp's last polynomial term, corrupt the large-argument
pi/2 split, and replace round with floor(x+0.5). Each must compile and finish on
JVM and native before its named oracle can count it as killed. The fourth
control changes one native direct exp call by exactly one representable value;
function values and folded constants stay untouched. A compile error, crash,
timeout, missing row or unrelated failure is never a successful control.
