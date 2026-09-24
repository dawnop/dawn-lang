# Opt-in prepared LSP ownership controls

`python3 scripts/lsp-workspace-contract/prepared-lifecycle.py` runs the full
server test closure once unchanged, then once for each of seven isolated
production mutations. The unchanged run's `N test(s) passed` is the total the
controls are held to: each must report `1 of N test(s) failed`. No total is
written down here or in the script (#217). Set `DAWN_BIN` to a current compiler launcher and use
JDK 21 for both `JAVA_HOME` and `PATH`. The subjects live in a temporary copy;
the repository source and every inline assertion remain unchanged.

The controls disable body admission independently in project and standalone
dispatch, discard each kind of previous owner, borrow another standalone
document's owner, retain standalone documents during teardown, and enable
reuse in the explicitly cold project configuration. They must reach their
exact owning count or lifetime assertion, with no other failed test. Compiler
errors, linker failures, incidental panics, timeouts, and unrelated assertions
do not count as successful controls. `--self-test` exercises that rejection
oracle; `--check-anchors` validates all production replacements without
invoking the compiler.

`--shards N --shard I` runs one modulo partition, always with an independent
unchanged positive first. Partitions must be nonempty; invalid bounds are
rejected before invoking the compiler. Five shards contain 2, 2, 1, 1, and 1
controls respectively. The default remains the complete seven-control run.
Self-tests verify every control appears exactly once across each partition
count from one through seven, and reject invalid partition arguments.
The CI inventory check requires all five shards and the self-test exactly once;
its own controls remove a shard, duplicate one, and change the partition width.
This family lives outside the incremental sweep's discovery namespace and
must be validated separately rather than counted in that sweep's total.

The five existing CI jobs are prev-diff, dependency-heap-contract,
native-selfhost-tests, pipe-contract, and export-surface respectively. Using
the rounded 52s maximum local subject and twofold planning allowance gives
892s, 909s, 912s, 859s, and 852s including their previous allocations. Every
shard includes its own positive. These are planning allowances, not observed
runner times; no runner job was added and the 950s run pole is unchanged.

The exact owners are `lsp/server :: prepared standalone LSP owners preserve
queries counts and shared lease lifetime` (S) and `lsp/server :: prepared
project LSP owners drop conflicts and recreate leases on reopen` (P).

| Mutation | Owner | Required assertion text |
| --- | --- | --- |
| Project body admission disabled | P | `stats.checked_bodies == 1 && stats.reused_bodies == 1` |
| Standalone body admission disabled | S | `map.get(warm.docs, uri).expect("first").analysis_stats.expect("counts").checked_bodies == 2` |
| Standalone owner lost | S | `stats.reused_modules == 1 && stats.visited_bodies == 0` |
| Project owner lost | P | `stats.checked_bodies == 1 && stats.reused_bodies == 1` |
| Standalone owner shared | S | `map.get(warm.docs, second_uri).expect("second").analysis_stats.expect("counts").checked_bodies == 2` |
| Standalone teardown retains documents | S | `count(closed) == 1 && map.len(stopped.docs) == 0 && map.len(stopped.workspaces) == 0` |
| Cold reuse enabled | P | `cold_stats.reused_modules == 0 && cold_stats.retained_total_modules == 0` |

These are inline consumer ownership and work-count controls, not a JSON-RPC
benchmark. A safe legacy loader can reparse and still preserve body reuse;
counts cannot distinguish that behavior from prepared proof consumption.
Consequently these controls do not claim parse avoidance at the LSP dispatch
seam, production latency improvements, or completion of default-activation
acceptance. Protocol cold/warm equivalence, direct parse instrumentation,
native acceptance, and end-to-end workload measurements remain separate gates.

The complete local run on 2026-09-22 passed in 387.20s: positive 46.04s;
project admission 44.70s; standalone admission 47.38s; standalone owner
45.46s; project owner 51.45s; shared owner 50.80s; teardown 50.93s; cold
switch 50.40s. Every control compiled and reached its sole expected assertion.
This run shared the host with a separate five-job incremental sweep; these
numbers describe validation cost, not isolated performance or CI budgets.
