# Source equality oracle coverage

> 状态：**historical** —— 已归档：增量引擎的 opt-in 切片于 #259 与 #261 拆除，最后一版树在 tag `incremental-slice-final`，考古看那个 tag；拆除的理由与留下了什么见 [incremental-semantics-removal.md](../incremental-semantics-removal.md)。
> 下面是归档前的原文，其中的「现状」「当前」「实施中」都指拆除之前。
>
> 归档前的状态：Status: current. The source-bound declaration range cache is implemented; focused correctness and Core checks pass. Whole-engine G3 acceptance is a separate requirement.

Repeated declaration equality currently seeks through raw source strings.
Before changing that implementation, preserve its observable contract with
an independent oracle built from the existing raw-string operations.

The tests enumerate small half-open code-point ranges, including negative,
reversed, out-of-bounds and empty ranges. Sources contain ASCII, BMP and
supplementary characters, combining marks, comments and line endings. These
checks are independent of declaration/token pairing: `same_text` also accepts
valid ranges that cut tokens or contain no tokens.

Equal-length trivia mutations receive separate examples so replacing raw
comparison with token equality cannot satisfy the oracle. No timing assertion
is made; performance attribution and the original Scale workload remain
separate acceptance work.

## Initial verification

On JDK 21 with the normal seed-backed launcher, targeted
`dawn test selfhost/src/check/source_projection.dawn` passes all 40 tests.
A temporary compiling mutant that rejects valid empty ranges fails exactly
the two new tests; the original implementation is restored afterward.
These checks establish oracle coverage, not an optimized implementation or
performance improvement.

The same 40 targeted tests also pass on the native backend using a freshly
built cold-configured compiler and its matching staged standard library.

## Not included

- No relaxation of trusted from-parts constructor preconditions.
- No backend-specific malformed Unicode construction in shared Dawn tests.
- No default activation, deployment or phase acceptance claim.

## Source-bound declaration range cache

The isolated instrumented original 1000-function Scale workload attributed
77.23 ms of 133.15 ms replay time to 1000 `same_text` calls. Instrumentation
overhead means these figures locate work, not establish an uninstrumented
speedup. The current routine counts both entire module strings and seeks from
their starts for every declaration. Token equality is not a replacement:
equal-width trivia changes must still reject replay.

Extend the private `TokensData` with exact `(lo, hi)` raw declaration strings.
`tokens_from` already consumes ascending disjoint declaration spans. A single
monotone cursor traversal over its own raw source can obtain each span once,
without retaining a cursor per code point. Only actual reachable source
boundaries are cached: supplied code points and token spellings never supply
the raw equality value. Existing from-parts preconditions remain unchanged.

`same_text` keeps its negative/reversed/unequal-width checks. If both exact
ranges have cached raw values, compare them directly. Otherwise use the
existing raw-string implementation, including its real source-length checks.
This preserves arbitrary ranges, token-cutting ranges, empty ranges and
out-of-bounds refusal even when no declaration cache entry exists. An empty
string is a present cached result, not a miss.

Additional retained data is bounded by disjoint declaration text plus one map
entry per distinct range; it is not a per-code-point cursor table. Projection
construction gains one monotone raw traversal and declaration copies. Public
parse/index signatures and the capture-disabled zero-index path do not change.

Acceptance includes the independent JVM/native raw-range oracle, cache-hit
versus fallback cases, malformed ranges, equal-width trivia changes, Unicode,
and deliberate mismatched supplied code points. Existing compiling controls
must continue to reject the intended assertion owner; source producer counts
must remain unchanged. Isolated performance runs happen only after source and
tests freeze, and retained-memory cost must be reported separately.

The optimized implementation passes 43 targeted tests on both JVM and native:
the original 40 plus cached/fallback Unicode range products, forged supplied
parts, and duplicate empty/disjoint boundary cases. The independent
`scripts/incremental-semantics-contract/source-equality.py` runner passes its
positive and four compiling negative controls (negative ranges, valid empty
ranges, cached equal-width trivia, and unreachable raw boundaries). Its strict
classifier rejects compile/link errors, panics, timeout, wrong status, missing
summary and unrelated assertion owners. These are correctness results, not a
claim that replay or snapshot construction is faster.

Matched Core lowering on 2026-09-23 produced 109 modules on both sides of the
range-cache change, with zero failures. Only `check/source_projection` changed:
the range map adds tuple Eq/Hash dictionaries and monotone cursor traversal;
unrelated modules remain byte-identical. Integrated golden recording retains
all 17 existing example/standard-library dumps and adds two bounded-admission
module hashes, with five existing compiler module hashes intentionally updated.
