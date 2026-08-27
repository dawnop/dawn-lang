# builtin-decl-contract

`selfhost/builtins.dawn` is the builtin table written out as declarations, one
line each. This directory is what keeps it true.

```
./scripts/builtin-decl-contract/run.sh
```

Roughly two seconds, and it needs nothing but the repo's own toolchain.

## The two sides

The truth is `intrinsics()` in `selfhost/src/check/types.dawn`. `dump/` is an
ordinary Dawn project with a path dependency on `selfhost`, so it reads that
table the way any consumer would: import the module, call the function, print
what it holds. There is no compiler API here and no subcommand of its own,
because the table needs neither.

The dump prints two record kinds:

```
builtin<TAB>name<TAB>pub|internal<TAB>signature
lowering<TAB>name
```

Signatures are rendered by `sig_render_fqn`, which differs from the
`sig_render` every reader surface uses in exactly one entry: `cast`'s parameter
comes out `java.lang.Object` rather than `Object`. A table dump needs the name
that identifies the type; a hover needs the one that reads.

## What is compared

| | |
|---|---|
| P1 | every name the mirror declares is in the table |
| P2 | every name in the table is in the mirror |
| P3 | the signatures are equal character for character |
| P4 | `pub fn` in the mirror ⇔ the table says the name is not internal |
| P5 | the `# comptime: rejected` markers are exactly the names the comptime interpreter refuses |

P1 and P2 are two judgements over the same two sets rather than one equality,
because "the sets differ" names neither side, and a mirror carrying a name the
compiler dropped needs a different fix from one missing a name the compiler
gained.

Two meta-judgements, because a comparison of two empty sets passes:

| | |
|---|---|
| M1 | the dumped names plus lowering's internal intrinsics are exactly the two lists in `src/ir/interp.dawn` |
| M2 | the mirror parses to at least one declaration |

## Where P5's other input comes from

`interp_arms()` and `comptime_rejects()` are private to `src/ir/interp.dawn`,
so `check.py` reads them out of the source text with a small evaluator for the
three shapes they are written in. Publishing them instead would widen the
compiler's export surface to serve a gate, which is the worse trade -- but a
source-text reader can be wrong quietly, so it is audited rather than trusted.

That audit is M1. Those two lists between them name every intrinsic in the
program, which `interp.dawn`'s own test asserts; M1 re-derives the same
equality from the parse. An under-read drops names from one side of it and an
over-read adds them, so a parser that has gone wrong is named rather than
believed. This is also the emptiness guard on the dump side: a truncated dump
cannot satisfy an equality against 110 names.

## Scope

The mirror covers the 95 builtins and nothing else. `internal_intrinsics()` in
`src/ir/lower.dawn` -- 15 names lowering emits between itself and the emitters
-- has no declaration in the mirror, because no source file may write one under
any visibility. Those names reach this directory only as M1's second input.

The partition assertion in `src/ir/interp.dawn` keeps reading both sources
directly. It is that module's own test, about that module's own tables, and
nothing here replaces it.

## The mutants

`matrix.txt`, seven of them, one for each judgement plus a second for P3 and
P4. Each perturbs the real mirror in memory and asserts its own judgement goes
red; the working tree never holds a mutant, and no compiler is rebuilt.

They exist because `--self-test` is not enough. The self-test runs the
judgements against a synthetic table and proves each one *can* be red, which a
checker pointed at the wrong file, or reading a real signature into the wrong
field, would also pass. The mutants prove the judgements are red about this
repository. Both run, in that order, on every invocation.

`run.sh` reads the executable list back out of `check.py` and holds it equal to
`matrix.txt` in both directions, so a mutant added to one and not the other is
named at startup.

This harness is not sharded -- a mutant is a string edit, and the whole set
runs inside one job step -- so it does not source
`scripts/mutant-coverage/shard.sh`, and `scripts/mutant-coverage/check.py`
does not expect a coverage report from it.

## When it goes red

The table is right and the mirror is what changes. Adding a builtin means one
`##` line and one declaration in `selfhost/builtins.dawn`, in the section its
family already has.
