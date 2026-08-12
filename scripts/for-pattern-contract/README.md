# For-pattern contract

This contract owns SYN-13's parser, checker, lowering, and LSP boundaries.
Every registered mutant changes tracked compiler production source, builds a
private compiler, runs the complete assertion set, and must turn exactly its
single matrix owner red.

The runtime oracle is `scripts/spike-native/iter_for.expect`, shared with the
JVM/native differential. Core-only checks count source, `iter_start`, and
`iter_get` evaluation sites and keep range induction separate from canonical
pattern slots. Existing range-bound-order and source-loop-label contracts keep
their established ownership; this contract does not duplicate those rules.

Run it from the repository root:

```sh
./scripts/for-pattern-contract/run.sh
```
