# Or-pattern contract

`run.sh` builds the observed compiler and every production-source mutant in
`matrix.tsv`. Each compiler runs the same checker, parser, LSP, runtime, and
complexity probes. A mutant passes only when its red assertion set is exactly
its single recorded owner. Every other assertion is therefore a persistent
green control for that mutant.

The executable names from `mutate.py --list`, the matrix mutant names, and the
owner registry in `run.sh` must be exact sets in both directions. Harness
selftests reject duplicate mutants, duplicate owners, unknown owners, a missing
schema, a missing matrix member, and both extra and missing executable or owner
registry members.

The completion mutant changes both collection and exposure. `lspq.dawn`
collects every `TPOr` alternative, while `lspc.dawn` stops collapsing repeated
variable labels. The second mutation is necessary because the generic final
completion set otherwise masks repeated raw entries. Together they expose the
same canonical symbol twice and only the completion owner turns red.

`complexity.dawn` contains 24 complete Bool alternatives and must produce no
diagnostic within the loose smoke timeout. `budget.dawn` is a legal eight-item
tuple whose three alternatives per column exceed the bounded search. It must
produce exactly one complexity-budget diagnostic and no unrelated diagnostic.

The nested-runtime mutant truncates a list element's inner `TPOr` to its first
alternative. The source still compiles, but the written runtime oracle changes,
so the remaining-runtime assertion has one direct production owner. The native
fixture also assigns a reference through a nested alternative, fails a sibling
condition in the same parent pattern, and reaches the next arm. ASan therefore
observes cleanup of a partially assigned shared slot, not only successful arms.
