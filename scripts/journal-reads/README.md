# journal-reads: which Cx table reads are written down

`check.py` answers one question about the incremental semantic engine: for the
checker code a function body can reach, which reads of a `Cx` table leave a log
entry, and which do not.

A cached body is readmitted on a later revision by installing its recorded
product instead of checking it again. That is sound only if every question the
body asked of the module environment was recorded while it ran, so admission
can put the same question to the candidate revision and compare. Two logs carry
those answers: the read log (`check/semantic_reads`, revalidated by
`checker.revalidate_read`) and the write journal (`check/write_journal`,
consumed by `body_product.capture_journaled`).

A read that reaches a table directly and records nothing is invisible to both,
and also to every dynamic gate here, because a dynamic gate only sees the
revisions its fixtures were written with. `cx.alias_shadow` is the case that
prompted this: it reports a binder that shadows an imported module alias by
reading `cx.module_aliases`, and records nothing, so a candidate revision that
adds `use dep as y` in front of a body holding `let y = ...` lost the
diagnostic on replay. That was found by walking the admitted AST class by hand.
This is the mechanical version of that walk, so the next widening of admission
(calls, generics, methods) does not have to repeat it.

## What it does

1. Reads the `Cx` record out of `check/cx.dawn` and takes its fields as the
   table inventory. The field list is never hand-written here.
2. Indexes every top-level `fn` in `selfhost/src`, lexically, dropping comments,
   string literals and inline `test` blocks.
3. Builds a conservative call graph and walks it from the seven body-checking
   entry points in `check/checker` (`check_fn`, `check_fn_body`,
   `check_fn_inferred`, `check_fn_inferred_body`, `check_trait_default`,
   `check_test`, `check_const_init`), which are exactly what
   `check/body_execution.record` and `checker.cold_body_executor` call.
4. In each reachable function, finds every `<name>.<field>` where `<field>` is
   a `Cx` field and `<name>` holds a `Cx`, and separates a read from the old
   value inside that field's own `Cx { .. }` update.
5. Holds the whole set to `ledger.txt` in both directions: a read that is not
   in the ledger fails, and a ledger row whose read has gone fails.

`ledger.txt` gives every read one of four verdicts (`logged`, `product`,
`write`, `uncovered`) and a reason in the author's own words. The header of
that file is the format. `--uncovered` prints just the holes, which is the
wiring backlog.

## What each verdict is actually checked against

* `logged` names a `semantic_reads` fact. The gate checks the variant exists in
  `FunctionRead`, that the named function still builds it (directly, or through
  a `check/semantic_reads` helper that builds exactly that one variant, which
  is how `semantic_reads.record` spells `FunctionAnswer`), and that the
  recording function and the reading function still call one another.
* `product` names the `Cx` field `body_product.assemble` reinstalls from the
  product. The gate checks `assemble` still writes it.
* `write` needs nothing further: the read is syntactically inside the update.
* `uncovered` must say `backlog`, or `compensated-by=<site>` naming the
  admission-side guard that re-asks the question. The gate checks that guard
  still reads that field. Reverting the `module_aliases` guard in
  `check/scalar_replay.candidate` reddens the gate for exactly this reason.

## What this cannot see

Say it plainly, because a green run here is not a proof of soundness.

* **It is a textual scan, not a type checker.** A name is treated as holding a
  `Cx` when it comes from a `: Cx` parameter, a `Cx { .. }` literal, another
  such name, or a call whose declared return is `Cx` or `(Cx, ..)`. That
  over-approximates on purpose. It does not follow a `Cx` through a closure
  parameter, a record field other than one spelled `cx`, a list, or a generic
  container, so a read reached that way is missed.
* **The call graph is names, not values.** A call resolves to every definition
  of that name, narrowed to the same module when one exists and to the module a
  qualifier names. A qualified call whose qualifier matches no scanned module
  is dropped, which is why `map.values(..)` is not read as a call into
  `check/function_product`. Dispatch through a closure stored in a record (the
  `BodyExecutor` fields, for instance) is not an edge, so reachability is not
  closed under higher-order calls.
* **`logged` is a claim about the call chain, not about the answer.** The gate
  proves a fact was recorded in a function that calls, or is called by, the one
  doing the read. It cannot prove the fact's answer determines the read's
  answer, and it cannot prove the recording function is on *every* path to the
  read. Both are what the reason column is for.
* **It says nothing about revalidation.** A fact that
  `checker.revalidate_read` does not recompute makes admission refuse rather
  than trust, which is safe but not free; this gate does not count them.
* **It says nothing about writes.** Table writer ownership is a separate closed
  inventory in
  `scripts/incremental-semantics-contract/journal-coverage.py`.
* **Header passes are out of scope by construction.** A table read only reached
  from `check/passes` or the driver is not reachable from a body entry point
  and never appears here.

## Running it

```
python3 scripts/journal-reads/check.py              # the gate (about 0.8s)
python3 scripts/journal-reads/check.py --self-test  # its own controls
python3 scripts/journal-reads/check.py --uncovered  # the wiring backlog
python3 scripts/journal-reads/check.py --record     # redraft the ledger skeleton
python3 scripts/journal-reads/check.py --src <dir>  # scan a tree somewhere else
```

`--self-test` runs a five-module synthetic tree: one positive control that must
stay clean, six negative controls (an unledgered read, a reason-free exemption,
a reverted compensating guard, a read accessor that stopped recording its fact,
a `product` claim `assemble` does not back, and a stale row), and three lexical
controls (a `test` block, a comment and a string literal, each spelling a table
read that must not count).
