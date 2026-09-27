# Session-owned body replay

> 状态：**historical** —— 已归档：增量引擎的 opt-in 切片于 #259 与 #261 拆除，最后一版树在 tag `incremental-slice-final`，考古看那个 tag；拆除的理由与留下了什么见 [incremental-semantics-removal.md](../incremental-semantics-removal.md)。
> 下面是归档前的原文，其中的「现状」「当前」「实施中」都指拆除之前。
>
> 归档前的状态：Status: current. Opt-in implementation and outstanding production acceptance.

This is the production integration work following the opt-in body executor,
single-pass renewal, and primitive inferred publication. It is not a phase-5
acceptance report. No speedup is asserted: the repaired production benchmarks
and end-to-end measurements must establish the value gate before activation.

## One module transition

Keep `analyze_module_step` and its recorded counterpart as wrappers around one
implementation. Add an explicitly cached transition returning the ordinary
`ModuleStep`, an optional opaque body cache, and execution counts. The cache
contains only an owner/module identity and `scalar_replay.Admitted`: never a
historical `Cx`, `ModuleHeaders`, Java probe closure, or complete recording.

Every changed module must reconstruct its context and run the canonical header
passes from the current `AnalysisCarry`. The existing standard-library identity
correction and `impls_before` baseline remain authoritative. The cached branch
belongs exactly where the recorded branch currently executes module bodies.
On its first revision, record once and admit; on later revisions, invoke
`replay_and_record` once. Always assemble the current pass and continue through
the existing comptime, diagnostics, exports, implementation-table fold, identity
table, and declaration-span publication. Never restore the old module suffix.

Parse failure, absent outer `AnalysisCarry.provenance`, unsupported snapshot
binding, and disabled caching select the unobserved canonical cold branch. A
changed owner identity prevents borrowing the old admission but permits a fresh
recorded cold execution. Missing inner provenance tables do not currently gate
this primitive producer: it reconstructs the required local/compiler header
tables and revalidates actual query answers. Broader imported type classes must
establish their own provenance coverage before admission expands. Header
or body errors cannot borrow an old success. Cache renewal must describe the
actual current execution; it must not union entries with an older generation.
The completed checker context used by the query Program keeps the original Java
oracle, not the temporary observation counter used during this execution.

## Loader and source binding

There is a concrete integration constraint, not just an API mismatch:
`source_snapshot.of(text)` stores the parsed source tree, while the loader's
`qualify_uses` and `apply_rewrites` may replace `DUseModule` path segments before
headers run. The current `snapshot_matches` requires equality of the entire
module. Passing an unmodified snapshot for that resolved module therefore
correctly refuses admission, but would leave package imports without reuse.

Do not weaken the equality check globally or accept arbitrary caller-supplied
AST/text pairs. Introduce a narrowly checked source-resolution binding: compare
every declaration, permitting only import path-segment replacement, preserving
declaration count, order, import selection/alias, and all source coordinates.
All non-import declarations, including every body, must remain exactly equal.
The resulting snapshot retains the same indexed text and tokens and the verified
resolved syntax. The actual header/query facts continue to establish whether
the newly resolved imports mean the same thing. Negative controls must reject
changed bodies, spans, declaration order, and import aliases/selections.

The legacy cached entry reconstructs a snapshot from arbitrary loaded text;
that duplicate parse must be included whenever measuring that entry. The opt-in
prepared loader now produces an optional clean snapshot beside its parse result,
propagates the checked import rewrite, and preserves recovered syntax/diagnostics.
Its prepared Session consumer does not recreate a missing proof. Cold CLI callers
use capture-off parsing and must not pay for an unused replay token index.
This is parse sharing within one load/check update, not an incremental parser or
a claim that unchanged dependencies remain parsed across separate loader calls.

### Single-parse source input

The first additive API is `source_snapshot.parse(text, capture) -> Parsed`, where
`Parsed` contains `syntax: Module`, ordered `diagnostics: List[Diag]`, and
`snapshot: Option[Snapshot]`. It always returns the canonical parser's recovered
syntax and diagnostics. It calls `parse_module_lexed` once; only clean input with
capture enabled proceeds to replay index/token projection construction. A
projection refusal removes only the optional snapshot, never the syntax or
diagnostics. `of(text)` delegates to `parse(text, true).snapshot`.

The result record is not itself a source-binding capability: callers can copy
or alter its public fields. Only the opaque snapshot certifies its own syntax,
index and tokens. There is no unchecked public constructor from separately
provided text, syntax, code points or tokens. Later prepared loader inputs must
preserve this proof through checked import resolution; arbitrary LoadedModule
values must retain the existing safe binding checks.

Capture disabled means no replay index or per-function token projection is
constructed or retained. It does not mean the parser avoids ordinary lexing or
temporary code points/tokens. The initial slice leaves all loader, Session and
LSP callers unchanged. Semantic tests compare recovered syntax, diagnostic
ordering and captured fields with the existing independently indexed oracle.
Actual API method-entry instrumentation now observes one parser/index/projection
for clean capture and `of`, and one parser with zero indexes/projections for
capture-off and lexer/parser errors. Three independently compiled duplicate/eager
controls change the exact expected vectors. This is not evidence of end-to-end
speedup. Loader/consumer invocation counts require their own intervals and
controls, and all original production activation gates remain in force.

## Session ownership and eviction

### Prepared loader proof

An opaque `PreparedLoad` owns the canonical `LoadResult` together with the
optional snapshots produced at its actual seed/dependency parse sites. Its
public accessors expose the ordinary result and opaque prepared modules, but
there is no constructor from caller-supplied loaded syntax or snapshot maps.
The resolver shares one capture-flagged implementation with existing cold
loaders. Capture-off parsing preserves recovered syntax and ordered diagnostics
without building replay indexes. A proof is replaced or removed whenever its
loaded source is replaced; missing proofs must never borrow an older entry.
Transient proofs carry their original path and text. Final binding compares
both with the actual loaded module before checking the resolved AST: a same-name
dependency can replace a queued module while its final rewrite restores an
earlier source, and equal-shaped ASTs do not prove that text/index pair agrees.
After all package-path rewrites and topological sorting, each proof is bound to
the final syntax through `source_snapshot.resolved` before publication.

Standalone preparation shares filename diagnostics and the proposed `main`
identity with cold standalone analysis; the analysis transition still settles
standard-library identity. Prepared values are transient update inputs, not
additional fields retained in a Session. Tests must compare complete cold and
prepared loader results on package rewrites, overlays, recovered sources and
loader errors. Host method-entry instrumentation observes `(parse,index,
projection) = (3,3,3)` for the three-module prepared loader, `(3,0,0)` for its
cold counterpart, and `(1,1,1)` for standalone preparation. A separate prepared
Session interval, excluding explicitly marked setup, observes `(0,0,0)` even
after eviction. Four compiling controls independently duplicate seed/dependency
parses, eagerly capture cold input, or reparse in the consumer; each preserves
semantic samples and fails its exact count vector. These are invocation proofs,
not latency or retained-memory measurements.

`analyze_module_step_prepared` consumes an opaque prepared module and never
falls back to reparsing when that module has no proof. The legacy cached-module
entry retains its checked reparse fallback for arbitrary `LoadedModule` callers.
`incremental.analyze_prepared` derives both ordinary inputs and prepared modules
from one opaque load and enters the same Session loop as the legacy API. It
cannot accept a separately supplied syntax list. Prefix hits and all body/cache
accounting remain shared; disabling caching does not create another parser.

Keep exact-prefix module hits as their existing distinct optimization. Add a
separate bounded current-generation module-to-body-cache table inside the opaque
session. A prefix mismatch ends whole-module reuse, but does not prevent current
headers from revalidating a later module's body products. A changed upstream
implementation can leave runtime callers reusable while comptime executes again;
a changed signature must invalidate affected consumers.

The returned session replaces, rather than appends to, the previous revision's
table. Deleted modules disappear; evict drops prefix and body caches together.
Bound module count, source units, and admitted product count. Count prefix hits,
cold module transitions, comptime transitions, cold bodies, reused bodies,
unadmitted/rejected bodies, capture refusals, and retained products separately.
Changing the captured project plan, standard library, options, or Java lease
constructs a new owner. FFI runs and unproven Java queries must not retain an
apparently pure prefix. Eviction and the explicit cold switch affect only speed.

The implemented owner uses `new_with_body_cache`; `new` keeps prefix-only
behavior. Prefix and body representations are charged separately against the
same module/text budgets, even when they refer to one source file. Current body
products take priority at each module; a product set that exceeds the remaining
product budget is not retained. Budget pressure may stop prefix retention but
does not prohibit later smaller body entries that fit. All accounting is for
the returned generation, not every version of the immutable owner a caller
could choose to retain externally.

`retained_modules` and `retained_text_units` retain their prefix-only meanings;
the `retained_total_*` and `retained_body_*` fields describe aggregate storage.
Body execution counts exclude whole-prefix hits. `unobserved_modules` reports
module checks on paths where no body counter ran; zero observed body checks is
not a claim that those modules did no work. `evict` clears both cache tables but
allows the next revision to record anew. `disable_reuse` clears both, disables
body recording, and sets retention budgets to zero for subsequent updates.

Body keys contain raw module/class/path identity, canonical path, and current
standard-library identity. A collision in effective module name, class name or
canonical source path disables both caches for that run. Source deletion removes
its entry; changing canonical path prevents borrowing either representation.

## Consumers and acceptance

### Explicit LSP configuration and lifetime

`run_lsp` keeps its existing CLI and delegates to `run_lsp_configured` with
`legacy_analysis_config()`. The immutable `LspAnalysisConfig` selects `Legacy`,
`PreparedBodies`, or `Cold` and supplies nonnegative `max_modules`,
`max_text_units`, and `max_products`. Legacy preserves prefix-only projects and
cold standalone documents. PreparedBodies is explicitly opt-in: projects use
prepared loading and `new_with_body_cache`; each standalone Doc retains its
own Session and stats, while all standalone documents still borrow the existing
shared Java lease. Cold uses capture-off loaders and permanently disabled
project Sessions; it must not reacquire a cache on its next revision.

Limits charge both retained prefix/body representations. The legacy default
remains 128 modules and 1048576 text units, with no body products; opt-in callers
must provide product limits explicitly. No new default budget or activation is
claimed before G3 measurements. A one-module standalone file can occupy two
representations. Configuration is fixed for a server lifetime; changes to std,
options, captured project plan, configuration, or lease require new owners.

Program, returned owner, execution stats, source view and document version are
committed together. Project conflict evicts both cache tables; last close drops
the workspace before closing its lease. Standalone close drops only that Doc's
owner, never the shared lease. Shutdown clears documents and workspace owners
before lease disposal, preserving exactly-once close and close-failure isolation.
Close/reopen starts a fresh document lifetime; repeated didOpen of an existing
URI retains the existing update behavior. Analysis remains synchronous and the
existing pending-message flush semantics are unchanged. Lower/equal document
versions are not currently rejected; this opt-in must not be described as
providing a stale-version guard or change version policy implicitly.

Project LSP sessions already own `driver/incremental.Session`; standalone and
untitled buffers currently call cold `analyze_standalone`. Give those buffers an
owner with the same lifecycle, preserving path checks, standard-library identity,
document version publication and lease disposal. The synchronous server does not
currently reject lower/equal versions. Normal Playground
editing uses this persistent LSP path. Only the LSP process persists: production
`run_lsp` is fixed to `legacy_analysis_config()`, and untitled documents still run
`analyze_standalone` cold on every edit, which is not incremental reuse.
Do not invent cross-request identity or
global caching for the stateless HTTP `/check` fallback.

Before enabling the new path, require:

1. Multiple-revision module and session cold equivalence: rendered diagnostics,
   typed trees, symbols, export/impl/identity carry, source views, and comptime.
2. Real execution counts for body edits, whitespace, declaration insertion,
   deletion and reorder, inferred signature changes, error/recovery, renamed
   imports, dependency changes, duplicate module identities, and cache eviction.
3. Compiling negative controls proving that missing guards/counts are detected.
4. LSP hover, definition, completion, diagnostics and lifecycle equivalence for
   project, standalone, and Playground-style untitled documents.
5. Full incremental contracts, reviewed Core hashes without widened
   normalization, JVM/native differentials, bootstrap fixed points, and docs.
6. Production benchmark counts/equivalence outside timers and session p50/p95,
   CPU, hit-rate, and retained-memory evidence. Body-only timings do not prove
   end-to-end speedup. The existing calls/inferred/generic value gate remains.

## Non-goals and remaining scope

This integration does not make the currently conservative body shape admit all
language constructs. Generic dictionaries have only the bounded explicit-integer
slice (see [generic-dictionary-admission-design.md](generic-dictionary-admission-design.md));
the remaining generic shapes are not done. Methods, defaults, tests, constants,
closures, Java and comptime dependency handling still require their planned
work. No disk/global cache, incremental parser, checker parallelism, new language
semantics, backend ABI change, or deployment is included. Phase-5 and phase-7
reports remain contingent on their full original acceptance requirements.
