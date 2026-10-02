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
table the way any consumer would: import a module, call a function, print what
it returns. The function is `builtin_mirror_lines()` in
`selfhost/src/driver/builtin_mirror.dawn`, which returns the records as
`List[String]`: reading a signature back needs a checker context, and that
context is `pub(pkg)`, so the reading happens inside the package and only data
crosses the boundary. There is no subcommand of its own.

The dump prints five record kinds:

```
builtin<TAB>name<TAB>pub|internal<TAB>signature
roundtrip<TAB>name<TAB>rendered<TAB>rendered-again
roundtrip-skip<TAB>name
lowering<TAB>name
owned<TAB>name<TAB>0,2
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
| P5 | the `# comptime: rejected` markers are exactly the names a `const` cannot use: the ones the comptime interpreter refuses by name, and the Map/Set names lowering routes to std/hamt, whose Core it refuses |
| P6 | every signature, parsed back as the declaration it claims to be and rendered again, is the same string |
| P7 | the `# owned: 0, 2` markers, plus the `# owned: <name> 0` comment records for the lowering-internal names the mirror does not declare, are exactly the table's owned argument positions (`types.intr_owned_args`) |
| P8 | the `DAWN_CONSUMES(...)` marks on the prototypes in `runtime/c/dawn_rt.h` are exactly the table's owned positions for every intrinsic whose `dawn_<name>` is declared there, and each names a parameter the prototype has |

P1 and P2 are two judgements over the same two sets rather than one equality,
because "the sets differ" names neither side, and a mirror carrying a name the
compiler dropped needs a different fix from one missing a name the compiler
gained.

P6 asks a different question from the other five. Those hold the mirror
against the table, and all five stay green when the *rendering* loses
something: the mirror is a copy of what the renderer printed, so both sides
agree about a signature the compiler cannot read back. P6 is the only one that
asks whether the line means what the entry means, and it asks the compiler's
own parser -- `parse_module` then `pass_fn_signatures`, so the answer is the
one a source file would get. The reading happens as if inside `std/`, because
seven of the signatures name `Array` and that is where `Array` is a type.

It found three when it was written: `sort_by`, `map_fold` and `bracket` each
raised an effect variable without recording that they bound it, and so
rendered `!e` with no visible introduction -- `fn sort_by[T](xs: List[T], cmp:
fn(T, T) -> Int !e) -> List[T] !e`, which reads back as `[T, !e]`. The table
was fixed rather than the renderer, and the fix moved nothing else: the ABI
row `types.sig_abi_eff` computes already unioned the binder list into the
declared row, and for these three the row carried the variable already.

`cast` is the one signature not read back, and check.py holds the skip list to
exactly that name. Its parameter renders `java.lang.Object`, and a dotted type
path is not a spelling the parser takes anywhere -- the mirror's own header
names that line as one that would not compile even with a body.

Two meta-judgements, because a comparison of two empty sets passes:

| | |
|---|---|
| M1 | the dumped names plus lowering's internal intrinsics are exactly three pairwise-disjoint lists: `interp_arms` and `comptime_rejects` in `src/ir/interp.dawn`, and `lowered_intrinsics` in `src/ir/lower.dawn` |
| M2 | the mirror parses to at least one declaration |
| M3 | the owned-argument table is not empty, and names only intrinsics: the table's own, or lowering's internal ones |

## Owned argument positions (#212)

Which argument positions the native runtime consumes rather than borrows is
the one per-intrinsic fact the table does not hold: it is a name-keyed constant
in `types.dawn`, because three of its four names are lowering-internal and
have no table entry to carry a field. P7 and P8 hold it to the two places that
state ownership at a declaration -- the mirror line and the C prototype -- so
dropping `list_push`'s position, or marking a C primitive as consuming without
registering its intrinsic, is red before any sanitizer corpus runs.
`list_push` has no C primitive (it lowers to `std/pvec.push`), so P7 is its
only check. The header is read as source text by `read_runtime_consumes`,
which `scripts/mutation-anchor-preflight.py` also runs before any build.

## Where P5's other input comes from

`interp_arms()`, `comptime_rejects()` and `comptime_refused_after_lowering()`
are private to `src/ir/interp.dawn`, so `check.py` reads them out of the source
text with a small evaluator for the three shapes they are written in. The
third group of the partition, `lowered_intrinsics()` in `src/ir/lower.dawn`,
is read the same way: it is lowering's classification rather than a table of
builtins, so it does not belong in the dump. Publishing them instead would widen the
compiler's export surface to serve a gate, which is the worse trade -- but a
source-text reader can be wrong quietly, so it is audited rather than trusted.

That audit is M1. Those three lists between them name every intrinsic in the
program, which `interp.dawn`'s own test asserts; M1 re-derives the same
equality from the parse. An under-read drops names from one side of it and an
over-read adds them, so a parser that has gone wrong is named rather than
believed. This is also the emptiness guard on the dump side: a truncated dump
cannot satisfy an equality against 110 names.

## Scope

The mirror covers the 95 builtins and nothing else. `internal_intrinsics()` in
`src/ir/lower.dawn` -- 15 names lowering emits between itself and the emitters
-- has no declaration in the mirror, because no source file may write one under
any visibility. Those names reach this directory as M1's second input,
and the three that consume an argument as P7's comment records.

The partition assertion in `src/ir/interp.dawn` keeps reading both sources
directly. It is that module's own test, about that module's own tables, and
nothing here replaces it.

## The mutants

`matrix.txt`, sixteen of them, one for each judgement plus a second for P3,
P4, P6, P7 and P8, and the two #185 was about: `parse_int`'s interpreter arm put back
(M1), and `parse_int_radix`'s marker put back (P5). Both builtins left the table at K19
(`parse_int` is a std/fmt function now), so those two land on `parse_float`, the
lowered parser that is still a builtin. The P7 pair is #212's
negative control (`list_push` loses its position) and a mirror marker dropped;
the P8 pair is a mark on a primitive the table says borrows, and a mark
dropped from `dawn_cell_set`. Each perturbs the real mirror in memory and asserts its own judgement goes
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
