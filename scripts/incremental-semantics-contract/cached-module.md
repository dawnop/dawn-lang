# Cached module transition controls

`python3 scripts/incremental-semantics-contract/cached-module.py` runs independent
positive subjects followed by nine compiling mutations of the actual
`driver/analyze` implementation in a temporary copy. `--suite driver` selects the
seven transition controls; `--suite observer` selects the two host-boundary
controls. `--only NAME` narrows driver controls but keeps their positive.
`--self-test` checks every exact source anchor without compiling.
The driver suite also accepts `--shards N --shard I` (zero-based), applying
deterministic modulo partitioning after `--only` selection. Empty partitions are
rejected and every partition retains an independent positive. Three driver
partitions contain 3/2/2 controls; the separate observer suite contains two,
covering all nine exactly once. Self-tests verify this coverage and reject
invalid partitions and false failure evidence. They also read the actual CI
commands and require every control exactly once, rejecting missing driver or
observer coverage and duplicated invocations.

The transition controls pin reuse counts, module ownership, source binding,
FFI refusal, error-cache eviction, fresh comptime evaluation, and current carry
publication. A negative must fail its named assertion owner, not compilation,
linkage, or a panic. Each subject reports elapsed wall time, including compilation
and its test dependency closure; these are gate-cost measurements, not replay
speedup measurements.

The `selfhost/src/contract/cached_module_observer.dawn` test module owns mutable Java
state outside the portable compiler: it is a module of the compiler package, because
the analysis steps it drives carry checker state, which is `pub(pkg)`, and nothing in
`main.dawn` or `nmain.dawn` imports it. It observes the exact ordered module/check/comptime
intervals on both cold and warm transitions, compares semantic products, and
checks that a tooling query after a warm hit reaches the current host oracle
without touching the previous generation's oracle. A warm hit must occur before
the host assertions are meaningful. Its Java import reaches neither driver's module
graph, and it does not duplicate the semantic engine.

CI runs the three driver partitions in checker-corpus, docs, and prev-diff;
prev-diff-native runs the separate observer suite. No controls are omitted or
duplicated, and each partition retains its positive. Budget planning uses the
54.59-second maximum measured driver subject, rounded to 55 seconds, and the
130.31-second observer suite, rounded to 131 seconds. Each local allowance is
doubled before adding it to the prior job baseline; the 950-second pole remains
unchanged. These are conservative gate allocations, not semantic speedup claims.
