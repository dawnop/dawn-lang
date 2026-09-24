# Bounded generic dictionary admission: trace-first slice

> Status: current. Pure explicit bounded trait-call replay and assembly-owned renewal are implemented. The uncached baseline below was slower than cold checking; full G3 acceptance remains separate from these correctness and work-count results. Earlier refusal and entry-only sections are historical evidence.

This tracks the M3.3 prerequisites and subsequent bounded admission class, not a completed G3 gate.
The original workload remains `Scale[T]`: a nominal `Coin` implementation and
explicit-return generic functions making three dictionary-dispatched calls.
Unbounded identity functions are not a substitute. Additional fixtures use two
bounds and two bounded type parameters to expose dictionary ordering and key
axis mistakes. The initial trace-only slice did not change admission; the
current implementation described below admits the proven pure bounded class.

## Historical refusal-baseline contract

Capture each fixture through `body_execution.record`, then use
`scalar_replay.admit`, `replay`, and `replay_and_record` over repeated, shifted,
and reordered revisions. Count actual canonical checks independently of the
reported counters. Bound functions and implementation bodies must currently
remain cold: capture success does not imply admission. Compare every mutable
body product and checker context field against fresh cold execution, excluding
Java capability equality only when identity is preserved. Inspect every saved
read, write, typed tree, symbol, bound delta, and dictionary frame through a
private reflection trace rather than introducing broad printing dictionaries
into the compiler.

## Historical candidate entry-proof proposal

The proposed helper takes the candidate scheduler entry `Cx`, exact candidate
declaration and signature, and projected saved product. It returns a temporary
validation context plus an entry proof, or refuses. It must derive each hidden
dictionary from candidate signature type-parameter/bound order and the
candidate declaration's allocation slots, not from the saved frame.

For each bound slot prove the exact binder identity, current trait name,
`(binder, trait)` frame key, `(trait, binder)` symbol tag, hidden symbol spelling,
symbol type/owner/source location, and ordered `TFun.dict_syms` entry. Check
parameter and dictionary allocations against the authoritative checker entry
contract. Preserve all unrelated bound rows while applying this function's
bound delta. Require empty evidence for this pure slice. Do not execute entry
twice or consume candidate slots while merely validating a candidate.

The trace must determine which scoped reads need this reconstructed context
and which observations involve temporary inference substitutions. Revalidate
each before/after unification fact, candidate namespace, and trait fact in its
proper scope. Dictionary call witnesses need explicit correspondence to
validated entry dictionaries; expression shape alone is insufficient. No new
fact family becomes shared memo evidence in this slice.

## Deferred work

The implemented guard changes passed trace review and independent compiling
negative controls. Effect evidence, inferred generic signatures, associated
outputs, defaults, lambdas, and wider nominal values remain separate classes.
G3 still requires the original 1000-function generic workload, truthful cold
implementation-body denominators, real edit hit rates, and replay per-body
cost below cold checking. No speedup follows from this refusal baseline.

## Historical observed production refusal baseline

The private `scripts/incremental-semantics-contract/generic-trace.py` fixture
retains two original `g0`/`g1` functions, each making the benchmark's three
`scale` calls. The additional functions call `Scale`/`Stamp` through two bounds
on one binder, and `Scale` through two distinct binders. All remain pure and
explicit-return; their nominal implementation bodies remain in the denominator.

| Fixture | Generic functions | Implementation bodies | Actual cold checks per pass | Reused |
| --- | ---: | ---: | ---: | ---: |
| Original Scale | 2 | 1 | 3 | 0 |
| Multiple bounds | 1 | 2 | 3 | 0 |
| Two parameters | 1 | 1 | 2 | 0 |

Each history checks recording, unchanged replay, shifted renewal, and another
renewal (including declaration reorder for the original workload). All twelve
full body/context comparisons agree with independent cold execution; recording
and renewal have zero capture refusals. The baseline is refusal by class, not
dependency rejection. The Java oracle instruments canonical checker entries in
a private source copy, so executor counters alone cannot satisfy the contract.

The complete read traces have exactly the following family counts per generic
function. They are pinned by the fixture rather than inferred from AST shape.

| Read family | Original Scale | Multiple bounds | Two parameters |
| --- | ---: | ---: | ---: |
| TraitName | 4 | 5 | 5 |
| FunctionAnswer | 6 | 6 | 6 |
| ReducedAssociatedType | 9 | 8 | 9 |
| ReducedTypeEffects | 9 | 8 | 9 |
| ConcreteType | 6 | 5 | 6 |
| UnifiedTypes | 6 | 5 | 6 |
| DictionarySymbol | 3 | 3 | 3 |
| ReducedEffect | 3 | 3 | 3 |
| AssignableType | 1 | 1 | 1 |

There are no `ParameterBounds`, `FunctionCandidates`, or
`ScopedTypeParameter` reads in these exact expressions. This does not license
dropping those dependencies in other generic forms. The current signature and
header namespace must still be validated. Function answers are canonical trait
method signatures, including the trait's own binder and constraint. Unification
maps that binder to the caller's distinct binder; subsequent primitive argument
and return/effect reductions carry that nonempty map. `ConcreteType` returns
false for the trait binder and true for primitive arguments. Simply permitting
generic types while retaining the empty-substitution guard would refuse these
bodies; dropping substitution validation would be unsafe.

`passes.register_fns` already installs every function's bound rows in headers.
Consequently all four recorded products have an empty net `bounds` delta, but
their write journals retain every `BoundsKey`. Dictionary symbols precede
ordinary parameter symbols after the signature binder slots: one binder plus
one dictionary plus two parameters uses four slots; one binder plus two
dictionaries uses five; two binders plus two dictionaries uses six. The fixture
checks the exact journal, recorded header slot offsets, symbol names/types and
tags, dictionary frame axes, and `TFun.dict_syms` order. No alias/signature or
diagnostic delta is present. All three calls carry `WForward` witnesses; the
multi-bound and two-parameter sequences are first dictionary, second dictionary,
first dictionary. Effect evidence is empty.

## Concrete next helper and integration boundary

Prefer factoring the existing pure `enter_fn` plus ordinary parameter-declare
loop into an authoritative checker helper shared with `check_fn_body`, rather
than independently reimplementing its allocation/spelling rules. A proposed
`function_entry(cx, declaration, signature)` result contains the temporary entry
context and ordered parameter/dictionary/evidence symbol lists. The validation
caller uses the real candidate scheduler context and exact signature, with
defaults and effects excluded for this class. It compares every saved entry
symbol against the helper's independently generated candidate symbol, including
relative name/parameter spans, and refuses entry diagnostics or unexpected
journal/allocation differences.

The helper computes an immutable temporary context: it must not replace the
live candidate state. On a hit, existing product assembly installs the validated
final slot row once; on a miss, canonical cold checking receives the original
candidate context. Do not compare the saved post-body scope stack directly with
the entry stack: `check_fn_body` pops the root scope before saving its product.
Validate the final-frame invariants separately and use the temporary entry
dictionary map for scoped `DictionarySymbol` revalidation.

Trait calls need a separate proof path: `callee_index` deliberately excludes
trait signatures. Preserve that ordinary-call contract. Bind each typed trait
call to its revalidated canonical method answer, derive its type substitution
from candidate operand types, and require each forwarded witness to name the
corresponding candidate entry dictionary in signature constraint order. Do not
accept `WConcrete` or `WApply` merely because the saved tree contains them.
Revalidate all nine observed families, including complete unification
before/after bindings, without extending shared memoization. The current
`checker.revalidate_witness_read` already recomputes these reductions and
unifications and rejects noncanonical duplicate binding maps; class membership
must still restrict the operands to the separately justified bounded shape.

The strengthened baseline ran successfully on 2026-09-22 in 11.03s with the
existing JDK 21 compiler launcher. This is fixture build/validation time, not
generic replay performance. No native, Core-golden, CI, or production admission
change is included.

## Helper-only extraction

The next implementation step exposes `FunctionEntry { cx, parameters }` and
`function_entry(cx, declaration, signature)`. It factors only the existing
`enter_fn` and ordinary parameter declaration loop from `check_fn_body`.
The cold body checker consumes the returned context and parameter IDs; it keeps
its final dictionary and evidence collection in exactly the same position.
In particular, `ev_sym_list` is not moved to entry, because doing so could
change effect-related observation ordering. Default preparation and inferred
signature scheduling are untouched. A separate pure `function_dictionaries`
accessor reuses the existing canonical dictionary ordering only when a proof
caller asks for it; ordinary cold checks gain no extra dictionary traversal.

The helper is a temporary computation over immutable contexts, not an entry
installation API. Tests must call it from real scheduler entry contexts, then
check/replay from the original input and compare every final body/context field.
They must compare the helper's independently produced entry symbols, dictionary
order and slots with captured products, including multiple bounds and distinct
type parameters. The existing frozen ordinary-body loop remains the independent
reference for extraction equivalence, including effect/default cases. No
production admission guard is opened by this extraction.

`FunctionEntry` adds a small return-record allocation to ordinary cold function
entry. This extraction is not claimed to have zero overhead; the production
workload measurements must include it. The minimal record avoids additional
dictionary traversal and derived whole-context equality/printing dictionaries.

The helper-only validation on 2026-09-22 passed 359 focused checker tests and
the formatter check. `scripts/incremental-semantics-contract/function-entry.py`
passed in 14.79s: the original twelve generic body/context pairs remain intact,
and 32 additional full context/tree pairs match the exact frozen pre-extraction
body loop from `f688f4b4`. These cover the three original generic classes plus
scalar, named-effect, declared-IO, ordinary-default, bounded-default,
duplicate-parameter, wrong-default-type and wrong-return-type functions, with
logging both disabled and enabled. The malformed cases must emit diagnostics;
the other cases must not. Two real scalar replay histories still hit after a
private candidate hook computes and discards the temporary entry context.

The host compares returned contexts and trees field by field, not through
generated Dawn equality. Temporary entry contexts are also compared with a
second independent entry from the same scheduler input, and ordered parameter
and dictionary symbol metadata must match the checked body. This is an
extraction oracle, not a second checker: its frozen body loop still calls the
unchanged canonical type/effect/default helpers.

Core review lowered all 107 modules successfully. Only `check.checker.core`
changed: two added helpers and the changed `check_fn_body` prologue. Every other
existing Core function is unchanged. The return-record constructor, field
loads and release are visible in Core; no new equality or printing dictionary
is generated. No golden was re-recorded in this slice. Native and full-suite
integration remain separate acceptance work.

## Entry-only candidate proof

The bounded API is `function_entry_proof.prove(candidate, declaration,
signature, product) -> Option[Proof]`, with an opaque temporary result and
context/ordered-symbol accessors. It proves only entry correspondence, not
source pairing, expression shape, call witnesses, or complete dependency
validity. The caller must supply the real candidate scheduler context and an
already paired/projected product. A successful result cannot authorize replay
on its own and must not be retained in a cache or installed into the scheduler.

This first proof accepts the measured entry-only bounded class: explicit pure
primitive return, ordinary top-level function, own type binders and primitive
or own-binder parameter types, nonempty trait bounds, no defaults or effects,
and no body-local allocations. It resolves written bounds through the existing
canonical header helper, verifies published signature and packed binder/header
slots, and reconstructs dictionary/parameter symbols with `function_entry`.
Saved metadata, relative spans, roles, dictionary axes/order, final frame,
entry journal and product allocation must match that independently generated
entry. No saved frame is used to reconstruct the proof context. Missing logs,
diagnostics, unsupported writes, or extra body allocations refuse cleanly.

Positive and compiling-negative tests precede any production admission change.
Body locals, effect evidence, defaults, inferred signatures, and general typed
call witnesses remain separate proof extensions; this boundary is deliberately
narrower than complete M3.3.

The proof resets observation logs only in its detached context. The saved read
log must begin with the complete canonical entry-read prefix; neither a missing
log nor an empty-present replacement is accepted. The exact matcher admits
only paired `TraitName(id, name)` facts, in order, after checking the saved
length. Any unknown canonical entry fact refuses instead of being skipped;
future entry-query extensions therefore require an explicit review. Existing live observation
prefixes and unrelated bounds are preserved. This does not revalidate the
remaining body reads: those still require a separately reviewed trait-call,
substitution and witness proof before bounded generic replay can be enabled.

`scripts/incremental-semantics-contract/bounded-entry-proof.py` exercises the
three original bounded workloads through actual scheduler callbacks. Sixteen
accepted entries cover unchanged and moved source with disabled and nonempty
enclosing logs. Every product also passes the existing product projection and
is proved again. Sixteen complete cold body/context histories include a real
bound-order change plus effect, default and body-local refusals. Dictionary
read axes must agree with the newly constructed caller-binder frame; the proof
context is discarded before cold-checking the original live input.

Forged inputs cover dictionary metadata, parameter roles/order, an empty
dictionary frame, owner identity, allocation interval, entry writes, missing
and borrowed reads, stale header bounds, invalid written bounds and an actual
entry diagnostic caused by a module-alias/parameter collision. Ten private
mutants remove individual entry gates or execute the whole body checker inside
the proof. The latter must fail the actual checker-call counter around the
proof invocation, not merely an output comparison. The negative classifier
requires exit status one, the precise sole owning panic and only the expected
reflection stack; its selftests reject wrong owners, extra exceptions,
linkage/verification failures, signals and timeouts. Run `--positive-only` for
the compiling positive fixture or `--self-test` for the classifier alone.

The final validation on 2026-09-22 passed 377 focused tests (including the
matcher and imported checker/product tests), the formatter check, classifier
selftests and the positive plus all ten compiling controls in 66.57s. These
are fixture measurements, not production latency measurements.

Core lowering passed all 108 modules. All 107 helper-baseline modules remain
byte-identical. The new proof module contains 3,465 lines / 131,004 bytes,
53 functions and 20 dictionary declarations. Using an exact entry-family
matcher and length-only presence checks reduced it from 5,977 lines /
318,389 bytes, 105 functions and 34 dictionaries: whole `FunctionRead` and
unnecessary diagnostic/change-list equality derivations disappeared. Required
signature, frame, symbol and journal comparisons remain; so do temporary
entry allocation and their runtime costs. No zero-overhead claim is made.
No golden was re-recorded at this prerequisite stage, and production replay
did not yet call the module. The subsequent admission below now does so.

## Pure bounded trait-call replay

The current implementation enables the original `Scale[T]`, multiple-bound and
two-type-parameter workloads as a separately validated replay class. Ordinary
callee indexing and shared-query memo rules remain unchanged. Admission pairs
source and signatures exactly as before, reconstructs a temporary canonical
entry, and validates every retained call against its current trait signature.
Argument types determine a fresh ordered unification; instantiated result and
every forwarded dictionary must match the retained typed call exactly. An
existing dictionary ID, or independently valid but unattached query facts,
cannot establish that call's correctness.

Only pure explicit integer-valued bounded functions without defaults, effects
or body-local allocations are in scope. Typed arguments are integers or the declaration's
own type binders. Concrete/recursive witnesses, inferred bodies, lambdas,
dynamic calls and unsupported query families remain cold. All newly supported
facts are validated per body under the proven entry; no function memo sharing
is added. Proof contexts are discarded and only the existing projected product
is installed, preserving current observation prefixes and scheduler state.

Acceptance requires real hits with zero body execution on those hits, three
generations of record/admit/replay/renew on all original workloads, prepared
Session versus full cold products, and strict compiling controls for swapped
dictionary roles, call substitutions, stale trait signatures and lost renewal.
After correctness, measure the original 1,000-function bounded value workload
across cold, record, admit, replay and renewal. Fixture time and isolated
measurements are not a production speed claim or completion of the G3 gate.

The first actual replay fixture passed on 2026-09-22: four captured bounded
products and twelve complete cold body/context pairs, with twelve real generic
hits over same-source replay and two renewed source generations. Canonical
trait methods intentionally store an empty parameter-default vector; requiring
the ordinary padded-false convention initially refused every call. The trait
guard now requires that canonical empty vector without changing ordinary
callee or source-default rules.

The expanded positive and all ten compiling controls passed in 70.99s. Fifteen
additional full-body histories cover nine targeted malformed products and six
observed/unobserved renewals with enclosing log prefixes. Four prepared Session
histories compare every returned Program and CheckedMod field, including full
Cx, syntax, typed output, comptime output, diagnostics and position views.
Counters independently measure checker entries, so executing a cold body while
reporting a hit fails. Mutants also cover root result type, dictionary order,
argument unification and symbol roles, callee owner, full fact validation,
entry frame, unknown families and lost renewal. These are targeted product
defenses, not an AST-to-TAST rechecker or proof against arbitrary fabrication.

The original 1,000-function `Scale[T]` benchmark keeps its exact source and
1,001-body denominator, including its unsupported implementation method. Its
generic hit expectation is now 1,000. Full G3 acceptance remains separate;
the first isolated, uncached value measurement below was negative.

## Real dependency invalidation and recovery

The expanded fixture now compares twelve complete prepared Session/cold
Programs. A full trait-signature change (parameter spelling) rejects both
unchanged callers: four actual cold checks, then two cold/two hits on the next
source move. Adding a second bound to one caller yields three cold/one hit,
then two cold/two hits. Changing the trait result to Bool produces diagnostics
and four cold checks; repair remains cold, then the next generation recovers
two hits. Full syntax, typed/comptime products, contexts, diagnostics and views
remain equal to fresh cold analysis. The FunctionAnswer-only bypass fails the
exact dependency-transition owner. The positive and all eleven compiling
controls passed in 81.81s; these are correctness-fixture times, not latency.

## Original uncached workload baseline

The unchanged 1,000-function Scale workload was measured in isolated fresh
JVMs, 30 rounds with 12 warmups (18 measured samples), keeping the 1,001-body
census and complete cold oracle. Median operation times were cold 52.613 ms,
record 165.253 ms, admit 7.812 ms, replay 124.647 ms and renewal 232.101 ms.
Replay was approximately 2.37 times slower than cold at that point, before
`f4f6062e`. These are operation wall times, not CPU or retained
semantic-cache memory.

These numbers are superseded. After `f4f6062e` the same 1,000-function
workload measured locally (2026-09-22) replayed generic bodies in 46.5 ms
against 52.2 ms cold (0.89), which did not reproduce elsewhere. The
2026-09-24 remeasurement at `b2e19e06` on a cluster machine, three rounds of
18 samples each, every round followed by an adjacent cold guard, gives these
median replay/cold ratios: calls 0.80, generic 1.15 (1.08 to 1.24), lambda
inferred 1.17 (no body admitted) and primitive inferred about 1.5. Renewal is
about 1.3 times cold for generic and 1.15 for calls, down from about 3 before
assembly-owned renewal (`9b74b720`, `2e2daf57`); lambda inferred renewal is
still about 4 times cold. Only calls replays below cold: **G3 is still not
met**.

Private exact-method instrumentation on the identical frozen benchmark JAR
attributes 77.227 ms of a 133.148 ms instrumented replay to 1,000 exact source
text comparisons. Renewal additionally spends 80.075 ms in 1,001 capture
environment comparisons. The adjacent uninstrumented/instrumented medians
differ by about 4.1% for replay and 1.5% for renewal; instrumentation and JIT
effects preclude treating phase sums as uninstrumented latency. Preserve every
proof and the original workload while addressing these measured costs.

## Assembly-owned renewal capture

Assembly-owned renewal targets measured repeated environment comparisons on
renewed hits. A renewal callback requests installation with a product, not a
saved context or certificate. The recording owner installs against its actual
observed scheduler input and receives one opaque assembly/output/capture result.
Only this local constructor may omit comparison of environment fields it
provably never changes; all slot, frame, diagnostic, read/write prefix and
touched-change checks remain. Arbitrary Checked callbacks and existing
`record_using` remain strict. A successful installation with refused capture
keeps its output and does not execute the body again. Inferred index publication
runs after the actual chosen output and can update only pass state.

Acceptance requires field-for-field agreement with strict capture on real hits,
compiling refusal controls, unchanged source/body equivalence and current
observer prefixes. Original Scale renewal should retain 1,001 visits and 1,000
hits, with full environment comparison for its one cold implementation. New
opaque-result allocation and callback costs need measurement; no speed claim
or G3 completion follows from this design.

The initial assembly-owned implementation passes 456 focused tests on both JVM
and native backends. The strict/certified oracle compares saved products, full
cold body results and real hit counts across three chained generations, with
both absent and nonempty enclosing observer logs. The renewal harness retains
six existing compiling controls and adds five for unchecked environments,
unbound output, unnormalized products, repeated cold execution and stale
inferred publication. All eleven controls reached their named runtime failure
on 2026-09-23 (86.07 seconds locally). These results do not replace integrated
Core, full-family or performance acceptance.

After integration with exact source-range caching and current main, the JVM
selfhost suite passes 907 tests. An independent exact-method counter on the
frozen original 1,000-function Scale benchmark observes three actual renewal
operations: each installs 1,000 certified products and calls strict environment
comparison exactly once, for the cold implementation. The ordinary benchmark
also retains 1,001 visits, 1,000 renewed admissions and zero capture refusals.
This verifies eliminated repeated environment work, not end-to-end latency,
CPU, memory or complete G3 acceptance. Instrumented and concurrent smoke times
are not performance evidence.
