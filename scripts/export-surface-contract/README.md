# export-surface-contract

SEM-07's negative control: `docs/public-surface-design.md`.

The validator answers one question — *can the audience this declaration is
published to name every identity in its header?* — and the ways to get that
wrong are all silent. A walker that peels an opaque type's representation still
accepts every legal program. One that stops at the first leak in a root still
rejects the fixture. One that runs after the bodies still produces the same
diagnostic, in a different place. None of those show up in a golden of accepted
programs, which is why this directory is mutants rather than goldens.

## What runs

    ./scripts/export-surface-contract/run.sh                 # everything
    ./scripts/export-surface-contract/run.sh --shard 1/3     # CI's split
    ./scripts/export-surface-contract/run.sh --only skip-map-key

Two halves:

* **The fixture contract.** `cases/*.dawn` for the single-module rules,
  `consumer/`, `consumer_leak/`, `unused_export_project/` and
  `phantom_distinct/` for the ones that only exist across a module boundary.
  Each rejection is asserted by message *and* by diagnostic count, so a rule
  that starts reporting twice is a failure and not a footnote.
* **The mutants.** One compiler build per rule. A mutant must compile and run
  `--version` before its assertion counts: "the mutant did not build" is not
  evidence about a rule (design §十二).

`mutate.py` refuses to apply a mutation whose anchor does not match exactly
once. That guard is the load-bearing part — a rewrite of the pass moves every
anchor, and a mutation that silently matched nothing would leave a gate that
still prints PASS while testing an unmutated compiler.

## The standard-library audience

`StdOnly` cannot be reached from a fixture: it belongs to `std/hamt` and
`std/pvec`, and a module's identity is where it was loaded from, not what it
contains. So the two `Array` cases mutate a *copy of the real std*:

* adding `pub fn f(a: Array[Int])` to `std/bytes` — a world-facing root inside
  std, which can spell `Array` and still may not publish it — must be refused;
* adding the same to `std/pvec`, whose roots stop at `StdOnly`, must be
  accepted, while a private type in its element must still be refused.

Those two are why the audience model has three values. A public/private boolean
gets one of them wrong whichever way it is drawn.

Two of the tree's own declarations are live witnesses and need no fixture:
`std/bytes`'s `pub opaque type Buf = Array[Int]` is legal exactly because a
public opaque root does not publish its representation, and
`examples/traits/traits.dawn` is a private trait implemented for a private type.

## The two consumers

`dawn doc` and the language server publish a surface, so they are held to the
same audience the checker is (design §7.1), and they are held to it by reading
what the checker decided rather than deciding again:

* `doc_impls.dawn` registers three impls and publishes one. "No filter" gives
  three and "filter everything" gives none, so the assertion is an equality and
  not a `grep -v`.
* `lsp-use-completion.py` computes what a `use` line should answer from the
  tree, and that now includes which std modules the checker will let the
  document name. `use std/pvec` is refused outside the bundled library, so
  offering `pvec` — or its exported names — is offering a name the next
  keystroke cannot use.

`impl-always-observable` is aimed at the *validator's* use of
`impl_is_observable`, not at the predicate, and the run asserts that the doc
filter stays green under it. Aimed one line higher it would redden mutant #15
as well (measured: the doc output becomes all three impls), and an assertion two
mutants can redden is owned by neither. Same correction as `2d5f19a`.

## Not here

* **A projection's private subject, and a private effect nested in a written
  function type.** Both branches exist in the walker; neither is reachable in
  today's language (design §15.4 says why). They have no mutant because a
  mutant has to turn something red, and these turn nothing red — recording that
  is better than an assertion that is green for the wrong reason.
