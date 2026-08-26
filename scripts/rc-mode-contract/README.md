# The parameter-mode mutant gate

Single-sided flips of the Perceus parameter-mode contract (`core.CMode`),
each required to go red under a machine, and the coherent flip required to
run clean.

    ./scripts/rc-mode-contract/run.sh

## Why it exists

The mode contract has two readers that must agree per function: the callee
side is `CParam.mode` (`rc.rc_fn` decides what enters the ledger,
`emitc.emit_fn` what gets an own-slot), the call-site side is the
program-wide table keyed `(owner, name)` (`rc.owned_positions` and
`emitc.arg_flags`, one table, two readers). The borrowed-inference pass
(docs/perceus-design.md 6) will stamp both from one fixpoint, and its whole
semantic risk is a disagreement:

* table says borrowed, callee still drops — the caller keeps no extra
  reference, the callee releases the last one, and the next read is a
  use-after-free that prints the right bytes until the allocator reuses the
  block;
* callee stops dropping, callers still hand over — a leak, which never
  prints a wrong byte at all.

Neither is visible to a differential. Before the inference lands, this
harness proves the net underneath it — the rc pass's own balance oracle,
AddressSanitizer, LeakSanitizer — catches each half-flip *when it happens*,
not by luck. "The green of a gate that has never seen a red is not
evidence"; these are the reds.

## The channel

`DAWN_RC_MODE_FLIPS=owner:name:arity:index=callee|callsite|both`
(comma-separated), parsed in `c/cdriver.dawn` where `build_units` builds the
table and hands lowered Core to `rc_module`. `:` separates fields because
the owner itself is slash-spelled (`std/cursor`). A malformed entry is a
compile-time panic, never a skip: the only writer is this harness, and a
flip that silently did not happen turns a red mutant into a green lie (the
`parse-guard` check keeps the panic honest).

Unset — every real compile — the channel must be invisible. Measured when it
landed, against the true parent compiler (57c2f67, before the channel
existed):

* all 88 spike-native corpus entries and all 4 corpus programs here emit
  **byte-identical C** from both compilers;
* `selfhost-prev-diff.sh` green with no new declarations — the JVM leg is
  identical too.

The `identity` check keeps a live fragment of that: a flip naming a function
that does not exist must produce byte-identical C. And every mutant that
emits must produce *different* C from the clean emit (`cmp`), so a renamed
env var or broken parser cannot quietly leave the whole matrix testing the
unmutated compiler.

## The matrix

Six sites (roster.txt), three shapes each, plus per-program clean controls.
What the harness pins **today**:

| site \ shape        | callsite            | callee   | both        |
|---------------------|---------------------|----------|-------------|
| std/cursor:done:2:0 | `rc: unbalanced` ✓  | LSan ✓   | known-red 1 |
| std/cursor:next:2:0 | `rc: unbalanced` ✓  | LSan ✓   | known-red 1 |
| std/str:len:1:0     | `rc: unbalanced` ✓  | LSan ✓   | known-red 1 |
| std/pvec:index:2:0  | `rc: unbalanced` ✓  | LSan ✓   | known-red 2 |
| std/list:reverse:1:0| `rc: unbalanced` ✓  | LSan ✓   | known-red 1 |
| std/list:take:2:0   | `rc: unbalanced` ✓  | LSan ✓   | known-red 1 |

A mutant (callsite, callee) is judged by "any machine red counts": the rc
balance panic, an ASan report, an LSan report, a wrong byte, a wrong exit. A
mutant that sails through everything fails the run by name. The coherent
flip (both) must be green end to end; the six failures are the two findings
below, ratcheted in known-red.txt.

### callee, the leak mutant (verbatim)

    ==2614392==ERROR: LeakSanitizer: detected memory leaks
    Direct leak of 145 byte(s) in 1 object(s) allocated from:
        ...
        #3 dawn_str_concat runtime/c/dawn_rt.c:655
        #4 dawn_std_2str__repeat ...
        #5 dawn_cursor_1scan__main ...

Restore the flip, the run is clean. The corpus programs build their values
at runtime on purpose: a string literal is an immortal static, and an
immortal neither double-frees when over-released nor leaks when
under-released — a mutant against a literal is invisible to both
sanitizers.

## Finding 1: the balance oracle predates the table (5 known-red)

Every callsite or both flip dies at *compile time*:

    panic: rc: unbalanced in std/cursor: skip_go: released a binding that
    was not held: 24; ...

The **rewrite is right and the oracle is behind**. `rc_check`'s `CCall` arm
marks every argument consuming (`chk_expr(c1, a, true)`; its signature has
no mode table), while the pass classifies the same positions with
`owned_positions` — and `rc_module` panics on the checker's verdict. Minimal
shape, `fn h(s) = g(s, 1)` with `g`'s first parameter borrowed in the table;
the pass produces exactly the right Core:

    block : Int
      let v1 : Int
        call direct m.g : Int    -- s passes bare, no dup: borrowed position
          local v0
          int 7
      drop v0                    -- h still owns s, releases it after the call
      local v1

and the checker, reading the call as a transfer, counts `drop v0` as a
double release. With the self-check bypassed (a local experiment, not
committed), all five table-jurisdiction sites emit, print the expected
bytes, and run ASan+LSan clean under the coherent flip — and the callsite
mutants are then caught by ASan instead:

    ==2609417==ERROR: AddressSanitizer: heap-use-after-free ...
        #0 dawn_dup runtime/c/dawn_rt.c:368
        #1 dawn_cursor_1scan__main ...

So the projected end-state matrix is already measured: teaching `rc_check`
the table (scheduled as part of knife 2, perceus-design.md 6 oracle (2))
flips these five known-red entries green and hands the callsite mutants to
ASan, with no other change. When that happens the ratchet fires
(`FIXED -- delete it from known-red.txt`) and the entries come out.

## Finding 2: `list_index` is outside the table's jurisdiction (1 known-red)

`xs[i]` lowers to the Core intrinsic `list_index`
(`ir/lower.dawn`); only the C emitter maps it onto `std/pvec.index`. So the
function's *executed* call sites never consult the mode table — flipping
`std/pvec:index` at the callsite changes exactly one call in the whole
program (`nth`, which nothing runs), and the coherent flip still leaks: the
intrinsic-lowered callers keep the all-owned convention while the callee
stops dropping. Measured with the checker bypassed: `both` is an LSan
direct leak, and the callsite mutant *survives* the sanitizers.

The obligation this pins on the inference pass: **a function reachable
through an intrinsic lowering (`list_index` / `list_slice` / `list_push`
family) must not have its callee side stamped borrowed** unless the
intrinsic lowering reads the same table. Today the site's callsite mutant is
still caught (the compile-time panic covers `nth`), and the day the checker
learns the table, this site's callsite flip becomes a survivor and fails the
run — deliberately, so the jurisdiction question cannot be skipped.

## The harness's own reds

Each judgement was broken once and watched refuse (2026-08-27, locally):

* a corpus file deleted from the roster → `corpus file str_len.dawn is on
  nobody's roster line`, fatal before any check runs;
* a known-red line removed → its check reports FAIL and the run fails;
* a stale known-red id → `known-red.txt names ..., which is not a check this
  harness runs`;
* the roster pointed at a function the program never calls
  (`std/str:reverse`) → callsite red (`byte-identical C: the mutation never
  engaged`), callee red (`the mutant SURVIVED`) — bad site selection cannot
  look like coverage.

## Cost

34s locally (2026-08-27, warm toolchain): ~24 `__emitc` runs, ~14 ASan
builds, ~14 sanitized runs. Rides in the `contracts` job (it wants a JVM
compile plus a `cc` with sanitizers, and that job is off the critical path);
see the budget note in gates.yml.
