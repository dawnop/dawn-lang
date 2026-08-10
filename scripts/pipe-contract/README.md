# pipe-contract

SYN-05's negative control: `29d04cd`, "Insert a piped argument into whatever
call the right side already is".

`|>` inserts an argument into an ordinary call and does nothing else. An
`EApply` or `EMethod` on the right takes the left side in front of its
*written* arguments; anything else is applied to it. Callability, arity,
duplicate names and the record rule are the checker's answers, not a second
rulebook living in the parser.

The main behaviour is pinned by corpora: `scripts/checker-corpus/cases/pipe.dawn`
and `records.dawn`, `scripts/grammar-corpus/accept/pipe_general.dawn`,
`scripts/spike-native/pipe_general.dawn`, and 180 lines of `parser_test.dawn`.
What those do not pin is that **each assertion is owned by exactly one sentence
of the implementation**, and that property rots without anyone noticing. It
already did once in this campaign: SYN-09 persisted its ten mutants, and that
is how an anchor drift was caught when SYN-05 added an `XCtor` arm to the same
match in `selfhost/src/lsp/lspq.dawn` (`2d5f19a`). This directory is the same
protection for the pipe.

## What runs

    ./scripts/pipe-contract/run.sh                        # everything
    ./scripts/pipe-contract/run.sh --shard 1/2            # CI's split
    ./scripts/pipe-contract/run.sh --only append-left-argument
    ./scripts/pipe-contract/run.sh --record               # re-record matrix.txt
    ./scripts/pipe-contract/matrix.py --selftest          # the gate's own control

Three halves:

* **The fixture contract.** `cases/*.dawn`, one shape per file. That is not
  tidiness: a parse error takes its whole file down with it, so two shapes
  sharing a file cannot own separate assertions. Measured: the first draft
  put all seven shapes in one `shapes.dawn`, and the constructor mutant
  reddened every line in it.
* **The editor and the formatter**, the two legs no corpus can see. Hover
  inside `m.f(a)` and `m.C(a)` used to answer with the enclosing call's type, a
  wrong answer rather than a missing one, which is why nobody noticed. And the
  formatter was *expected* not to move over the newly admitted shapes;
  idempotence is the check that expectation was standing in for.
* **The mutants.** One compiler build per sentence. A mutant must compile and
  answer `--version` before its assertion counts: "the mutant did not build" is
  not evidence about a rule.

`mutate.py` refuses to apply a mutation whose anchor does not match exactly
once. That guard is the load-bearing part: a rewrite of `pipe_expr` moves every
anchor at once, and a mutation that silently matched nothing would leave a gate
that still prints PASS while testing an unmutated compiler.

## The matrix is the gate

Every mutant runs the **whole** assertion set, and the set of assertions it
reddens is diffed against `matrix.txt`. Asserting only that a mutant reddens
its own owner would record the ownership in prose and enforce nothing: if a
later change made `append-left-argument` redden `named_arg_refused` as well,
that assertion would be owned by neither and nothing would go red. The
measurement that chose the owners has to be the gate, not a thing that happened
once.

Overlaps are recorded rather than forbidden, because several are by design: a
module-qualified call is an `EMethod`, so `drop-method-prepend` reddens
`qualified`, `probe_runs` and the piped hover probe too. What may not overlap
is an *owner*. `matrix.py` checks three rules:

1. every counted mutant has an owner, and that owner is in its own red set;
2. no other counted mutant reddens that owner, which is what "owns" means;
3. the observed red set equals the recorded one, in both directions.

Rules 1 and 2 read the record alone, so every shard validates the whole
ownership structure even though it builds half the mutants. Rule 3 catches an
owner that stops going red and a collision that appears where the record says
there was none.

`--record` rewrites the red sets and nothing else; the `owner` lines stay a
hand edit, because a recorder that could reassign owners would launder the
collision it exists to catch.

`matrix.py --selftest` perturbs a known-good record once per rule and requires
each perturbation to be refused, so this gate has been seen failing. The aim
side was checked the same way: re-aiming `wrap-nested-call` at every `EApply`
(its designed form) makes the run fail by name on `order`, `assoc` and
`eval_callee_first`, which are three other mutants' owners.

## The mutants and the assertion that owns each

| mutant | the sentence it removes | owning assertion |
| --- | --- | --- |
| `refuse-constructor-rhs` | the right side is not a shape the pipe approves | `bare_ctor` prints `7` |
| `drop-method-prepend` | a method call on the right takes the left side too | `method` prints `Some(20)` |
| `append-left-argument` | and takes it *in front of* the written arguments | `order` prints `ab` |
| `wrap-nested-call` | inserting into the call, not wrapping the call | `nested` prints `3` |
| `rebuild-arguments-positionally` | the written arguments keep their names | `named_arg` is refused |
| `parse-rhs-at-pipe-level` | the right side is one `or_expr`, so `\|>` associates left | `assoc` prints `6` |
| `parse-rhs-one-level-tighter` | and a whole one, not the tighter `and_expr` | `or_rhs` says `cannot call a value of type Bool` |
| `hoist-left-before-callee` | the left side is an argument, evaluated after the target | `eval_order`'s first line is `eval callee` |
| `allow-record-apply` | a record is built with braces however the call was spelled | `record_apply` reports both refusals |
| `route-qualified-name-into-call` | a bare `m.f` is a value the pipe applies | `module_member` says `has no exported value` |
| `drop-lsp-qualified-call-children` | the editor maps a qualified call's typed children | hover `qualified call, written` |
| `drop-lsp-qualified-ctor` | and a qualified construction's, which is an `XCtor` | hover `qualified ctor, written` |

Each owner was chosen by building the mutant and reading which assertions
actually went red, not by predicting it, and `matrix.txt` is that reading kept
under diff. Four of the twelve are aimed somewhere narrower than the designed
mutant was, and one assertion is deliberately weaker than it could be.

### The four retargets

* **`refuse-constructor-rhs`** is aimed at the constructor arm alone. The
  designed mutant restored the whole right-hand whitelist, and that one refuses
  every newly admitted shape at once. Measured: it reddens `bare_ctor`,
  `applied_ctor`, `qualified`, `method`, `field_fn`, `nested`, `module_member`,
  `record_apply`, `or_rhs`, both evaluation-order assertions and all five hover
  probes, eight of which are another mutant's owner. An assertion two mutants
  can redden is owned by neither, so the whitelist goes back for one shape.
* **`wrap-nested-call`** is aimed at the nested shape (`x |> make()(a)`), where
  "wrap" and "insert" differ without breaking anything else. Wrapping every
  `EApply` instead also reddens `order`, `assoc`, `nullary`, `applied_ctor` and
  both evaluation-order assertions (measured), taking the owners of
  `append-left-argument`, `parse-rhs-at-pipe-level` and
  `hoist-left-before-callee` with it.
* **`drop-method-prepend`** and **`drop-lsp-qualified-call-children`** overlap
  on the *piped* hover probe: a module-qualified call is an `EMethod`, so
  dropping the pipe's method arm stops `probe/src/main.dawn` compiling and the
  piped hover answers `?`. Both are owned by the spelling the other leaves
  alone: `method` for the first, the *written* hover for the second.
* The **LSP mutant is split in two**, one arm each, which is exactly the
  correction `2d5f19a` made: a single "drop the LSP child mappings" mutant is
  reddened by either hover probe and therefore owned by neither.

### The one deliberately weak assertion

`named_arg` asserts that `n |> f(a: 2)` is **refused**, and pointedly not which
diagnostic says so. Rebuilding the argument list positionally drops the name
and the call quietly compiles; appending the left side instead leaves the name
in place and the program is still refused, for a different reason. Pinning the
message would let both mutants redden one assertion. Splitting it this way is
the only thing that gives `rebuild-arguments-positionally` an assertion of its
own: its blast radius is otherwise a strict subset of `append-left-argument`'s,
because every fixture a positional rebuild changes carries a written name, and
appending after a written name is always refused.

The same split is why `hoist-left-before-callee` owns only the *first line* of
the evaluation trace. `append-left-argument` reorders the rest of it.

## The negative control

`negative-control-tighter-than-or` makes the pipe's *left* side bind tighter
than `||`. It builds, and it answers `--version`, but it is recorded rather
than counted: every `a || b` in the tree stops parsing, so the mutant cannot
load the bundled standard library (`std/cursor` fails first) and no assertion
it reddens says anything about the pipe. That is the designed mutant with no
compiling form, and the harness pins the failure so that "it does not build" is
a fact on the record instead of a mutant quietly dropped from the list.

Its red set is recorded anyway, and it is 21 of the 22: only `fmt_fixpoint`
survives, because the formatter is lexical and never loads std. That is why it
is excluded from the ownership rules. Counted, it would redden every owner.

## Not here

* **A pipe whose right side is a bare name or a lambda.** Both are the `other`
  arm, and no mutant separates them from the constructor and the function-typed
  field that share it. They are pinned by `grammar-corpus/accept` and by
  `spike-native/pipe_general.dawn` instead, where they always were.
* **The evaluation order on the native backend.**
  `scripts/spike-native/pipe_general.dawn` already runs the same trace through
  both backends; building a native mutant per rule would pay for one backend
  twice.
