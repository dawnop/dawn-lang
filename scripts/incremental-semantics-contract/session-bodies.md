# Session body-cache controls

`python3 scripts/incremental-semantics-contract/session-bodies.py` runs the
`selfhost/src/contract/session_bodies.dawn` test module against private copies of the actual
`driver/incremental` implementation. Thirteen compiling mutations cover actual
body counts, current-generation replacement, canonical prefix identity,
duplicate identities, eviction, persistent disablement, four shared-capacity
charges, the product limit, and error/Java barriers.

Every negative must reach its named assertion owner. Compilation errors,
linkage failures, panics, a different failing test, or a successful exit cannot
stand in for that assertion. The positive must run all selected owners.

`--shards N --shard I` applies zero-based deterministic modulo partitioning;
each nonempty partition has its own independent positive. `--only NAME` may be
repeated and selects controls before partitioning. The default runs all thirteen.
`--self-test` checks unique source anchors, exact 5/4/4 coverage across three
partitions, independent positives, invalid/empty partitions, and rejected false
failure evidence without compiling. It reads the actual CI commands as well:
missing partitions, duplicate controls, and an empty workflow are rejected.

Each subject reports real elapsed time including compilation and the complete
test dependency closure. These numbers size gates, not semantic-engine speedups.
The complete local positive plus thirteen controls took 644.33 seconds under
concurrent validation load; subjects ranged from 40.65 to 48.95 seconds. CI
allocates three partitions to compiler-weight-contract, java-member-dispatch,
and dependency-heap-contract. Each allocation doubles the rounded 49-second
maximum per subject, including its independent positive, before adding the
prior job baseline. The first job additionally budgets toolchain setup. The
950-second pole and runner job count are unchanged.
