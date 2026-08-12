# For-pattern contract

This contract owns SYN-13's parser, checker, lowering, and LSP boundaries.
Every registered mutant changes tracked compiler production source, builds a
private compiler, runs the complete assertion set, and must turn exactly its
single matrix owner red. A completion sentinel makes an early probe return a
contract failure rather than apparent unique ownership. The parser mutant
rejects the `Record { ... }` form used only by `syntax.dawn`, so its syntax
failure cannot prevent the other fourteen owner assertions from running.

The bottom-source oracle requires a diagnostic-free check and Core containing
one discarded `Never` source with no loop or body. The LSP oracle probes nested
constructor binders and a later or-pattern alternative through the real server;
the full recursive header offers constructors but no value or local names.

The runtime oracle is `scripts/spike-native/iter_for.expect`, shared with the
JVM/native differential. Core-only checks count source, `iter_start`, and
`iter_get` evaluation sites and keep range induction separate from canonical
pattern slots. Existing range-bound-order and source-loop-label contracts keep
their established ownership; this contract does not duplicate those rules.

Run it from the repository root:

```sh
./scripts/for-pattern-contract/run.sh
```
