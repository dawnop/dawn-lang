# The end-to-end evidence gate

What a call site puts in an evidence slot, and what the callee reads back out
of it, checked by running the program.

    ./scripts/effect-evidence-contract/run.sh
    ./scripts/effect-evidence-contract/run.sh --self-test

## Why it exists

On 2026-08-25 three defects landed in one day (#335, #345, #346) with one
shape between them: `dawn check` accepts the program and the run panics with
`effect evidence missing: no pack entry for the atom this call site asked
for`. A checker corpus is structurally unable to see that class -- the checker
is the component that said yes -- so the only witness is a program that runs.

Those programs existed. What did not exist was a gate whose subject they are:

* The **native differential** (`scripts/spike-native/run.sh`) ran them, and it
  is the only thing that did. That job needs a C compiler and
  AddressSanitizer, its own note in `gates.yml` records 281s, 365s, 533s and
  557s for an unchanged script, and what it is *about* is two backends
  agreeing rather than one of them being right.
* Nothing held the corpus to a roster. The differential globs its directory,
  so deleting `effect_io_absorb.dawn` was green, and a corpus that shrank
  looked exactly like a corpus that never had the case.
* `scripts/gate-map/gatemap.py selfhost/src/check/types.dawn` returned
  nineteen verdicts across twelve jobs, and `native-diff` -- the one job that
  ran an effect program -- was not among them. Reading the map before touching
  the row arithmetic told you the Core golden would move; it did not tell you
  anything ran a handler.

This gate is the fast lane: the same corpus on the JVM alone, no `cc`, no
sanitizer, no second backend, ~18s locally. It does not replace the
differential, which still owns "the two backends agree" and is still the only
gate that compiles the C.

## The two lanes

**Transcript.** `dawn run` against `<name>.expect`, byte for byte. This is the
only check here that can see the *order* two closures ran in: `bracket`'s
release closure reading an operation on the way out prints between the use
closure's line and the value, and no assertion about a returned value can tell
that apart from a release that never ran at all.

**Assertions.** `dawn test` runs the file's inline `test` blocks. A transcript
is a wall of integers whose only witness is the transcript it was recorded
from; an `assert` is a number a person wrote down and said what it meant.

`roster.txt` says which lane each entry is in, and is a ratchet in both
directions: a listed entry that is gone fails, an `effect_*.dawn` that is not
listed fails, and a file that grew `test` blocks while the roster still calls
it `transcript` fails. The two lanes are independent -- a `main` that panics
blocks the transcript comparison and nothing else, because the assertions are
a separate run of a separate program.

## The corpus discipline

Two rules, both bought with a measurement rather than reasoned to:

**Every line installs its own handlers.** With one `with handle` per effect at
the top of `main`, a single line that charges its label correctly seeds the
shared remainder's pack and every other line reads the node out of it for
free. During #345 a repair that fixed four call sites out of five printed the
right answer five times. Handlers also answer distinct primes, so no two lines
can agree by arithmetic accident.

**Every case reads through the slot.** A closure with nothing in it that reads
a pack answers the same whether the pack was built right, built wrong, or
passed as null -- which is exactly why every gate in the tree stayed green
over #346 for as long as it did. Each corpus file keeps one such line anyway,
labelled as the control.

## Negative controls

`--self-test` breaks each of this script's own judgements in a synthetic
corpus under a temp directory and requires it to go red. Ten probes, ~12s: a
deleted entry, a missing `.expect`, a wrong answer, an unrostered file, a lane
downgraded from `assertions` to `transcript`, an unknown lane word, an
`assertions` entry with its `test` blocks stripped, a false `assert` while the
transcript still matches, and a `main` that dies while every assertion still
passes. The last two are there so neither lane can be deleted without this
noticing, which is what the roster's two words rest on.

The tenth is the positive control: the untouched synthetic corpus must be
green. A harness that reds on everything reds on mutants too and proves
nothing by it.

## Production mutants

The self-test proves the script's own arithmetic. What proves the *corpus* is
reverting a real repair in the compiler and watching this gate fail. These
were measured on `ev-corpus-348` at `32341d9`; each was applied, the toolchain
rebuilt, the gate run, and the edit reverted. None of them is committed.

### A. `base_union` absorbs effect variables into io again (#345)

`selfhost/src/check/types.dawn`, one line into `base_union` after its
accumulation loop:

```
  if io { vars = [] }
```

Result: **red.**

    effect_decl_row:run                FAIL
      panic: effect evidence missing: no pack entry for the atom this call
      site asked for
    effect_decl_row:assertions         FAIL
      FAIL  nor does an inferred io row inside a primitive's use closure
      1 of 8 test(s) failed
    effect_io_absorb:run               FAIL
    effect evidence contract FAILED

Reverted: **green** (`effect evidence contract ok`).

The half this reaches is the *inferred* row -- a closure that does io and
calls an `!e` parameter -- because a written `!io !e` signature keeps its slot
whatever the union does with it. The declared half is held by the arms
`abab133` changed in `checker.dawn`, which mutant C's neighbourhood covers.

### B. `builtin_evidence` discards what the checker resolved (#346)

`selfhost/src/ir/lower.dawn`, delete the line that forwards it:

```
  if len(evid) == want { return lower_evidence(st, evid) }
```

so every primitive call site fills its evidence slots with placeholders, which
is what `XCallBuiltin` did before `49e2118`.

Result: **red.**

    effect_decl_row:run                FAIL
    effect_decl_row:assertions         FAIL
      FAIL  nor does an inferred io row inside a primitive's use closure
      1 of 8 test(s) failed
    effect_widen_row:run               FAIL
    effect_widen_row:assertions        FAIL
      FAIL  a primitive's use closure carries the widened row
      FAIL  so does a comparator the primitive applies
      2 of 8 test(s) failed
    effect_primitive_row:run           FAIL
    effect evidence contract FAILED

Reverted: **green.**

### C. `unify_eff`'s declared-label arm loses the residual (#335)

`selfhost/src/check/checker.dawn`, the `ELabeled(b, ls)` arm of `unify_eff`,
back to the two lines `7fe4cb5` replaced:

```
      let (em1, ok) = unify_eff(cx, b, eff_base(actual), m, em)
      (em1, ok && eff_subsumes(ELabeled(EPure, ls),
        eff_with_labels(EPure, eff_labels(actual))))
```

Result: **red**, and at check time rather than at run time -- this one refuses
the program instead of miscompiling it, which is what #335 was.

    effect_widen_row:run               FAIL
      error: argument type mismatch: expected fn() -> Int !AskE,
      got fn() -> Int !(AskE|TellE)
    effect_widen_row:assertions        FAIL
    effect_primitive_row:run           FAIL
    effect evidence contract FAILED

Reverted: **green.**

### D. `ev_select` casts the projection's slot instead of walking it (#355)

`selfhost/src/ir/lower.dawn`, the one-word edit that puts the reader back where
it was before #355 -- a devirtualised label taken out of a projection's slot by
CHECKCAST rather than by a walk to its node:

```
fn ev_select(v: CExpr, from: Ty, to: Ty, via: Int) -> CExpr =
  if false { ev_from_pack(ev_value(v), via) } else { adapt_out(ev_value(v), from, to) }
```

Result: **red.**

    effect_primitive_row:run           FAIL
    assoc_effects:run                  FAIL
      Exception in thread "main" java.lang.ClassCastException:
      class ev$Pack cannot be cast to class ev$AskE
    effect_assoc_row:run               FAIL
    effect_assoc_row:assertions        FAIL
      9 of 13 test(s) failed
    effect evidence contract FAILED

Reverted: **green.**

### E. the call site puts no node in the projection's slot (#355, the other half)

`selfhost/src/check/checker.dawn`, in `evidence_assoc_args`, the row handed to
`evidence_pack` stripped of the labels the reduction just produced:

```
      let (cx2, pack, un) = evidence_pack(cx1, eff_with_labels(eff_base(red), []), true, lo, hi)
```

Result: **red**, and by the other report -- the pack is built, it is simply
empty, so a reader walks it to the end.

    effect_primitive_row:run           FAIL
    effect_barrier_row:run             FAIL
    assoc_effects:run                  FAIL
    effect_assoc_row:run               FAIL
      panic: effect evidence missing: no pack entry for the atom this call
      site asked for
    effect_assoc_row:assertions        FAIL
      9 of 13 test(s) failed
    effect evidence contract FAILED

Reverted: **green.**

D and E are the two halves of one convention -- what a call site puts in a
projection's slot, and what the callee takes back out -- and each is red on its
own, which is what says neither half is decoration.

Between them the five mutants have different owners, which is the property
worth having: A is answered by `effect_decl_row` and `effect_io_absorb`, B by
`effect_widen_row`, `effect_decl_row` and `effect_primitive_row`, C by
`effect_widen_row` and `effect_primitive_row`, D and E by `effect_assoc_row`,
`assoc_effects` and `effect_primitive_row`. No single corpus file carries the
gate.

## What the corpus does not reach

Written down because a shape nobody could build is not the same as a shape
nobody thought of, and the difference is invisible six months later.

* `fn(...) -> T !io !e` in **parameter** position rejects a labelled closure:
  `fn() -> Int !(Tell|io)` does not unify into `fn() -> Int !(e|io)`. Whether
  that is 丙′ working as intended or a corner #345 left behind is a language
  question, not this gate's. The `!io !e` cases here are all written the way
  the compiler accepts: an `!e` parameter under an `!io !e` result.
* A `fn` with an effect variable cannot be annotated into a value at a ground
  row (`let w: fn(fn() -> Int !AskE !TellE) -> ... = widen` is refused), so
  `effect_widen_row` reaches `lift_fn_value` through a monomorphic wrapper
  instead. That is #344: the binder exists and there is no use-site effect
  argument to instantiate it with.
* Ordering inside a `test` block. A `with handle` arm captures by value and
  may not assign to a `var`, so there is no accumulator an assertion could
  read. Order is the transcript lane's, and that is not a workaround -- it is
  why both lanes exist.
