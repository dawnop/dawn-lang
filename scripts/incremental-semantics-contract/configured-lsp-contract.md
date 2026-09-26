# Configured LSP protocol contract

The configured server, method-entry observer, and edit matrices are independent
tools. This runner makes their composition reproducible without changing the
production server, treating stderr counters as protocol replies, or accepting a
broken compiler as a successful negative control.

`configured-lsp-contract.py --output <new-directory> --suite all` builds fresh
private Cold and PreparedBodies artifacts, both plain and stats-observed. It
compiles the existing ASM 9.7.1 observer with JDK 21. Each selected matrix runs
against all four artifacts and both bytecode-observed artifacts. All semantic
results must equal that matrix's plain Cold result. Stats-observed prepared runs
must pass the existing exact body-count oracle; bytecode-observed runs must also
pass the parser/index/projection oracle. The existing helper scripts remain the
authoritative fixture and count implementation.

Each scope then builds its own legacy-consumer reparse control. First, the
complete matrix must pass protocol equivalence and body counts with method-entry
observation enabled. Only then may a second run be rejected by the exact first
revision's parse-count assertion. Build failure, timeout, signal, linkage error,
unrelated assertion, wrong count, or a surviving control is a runner failure.
The first run preserves complete semantic evidence even though the second run
intentionally stops at its first bad count.

`--suite standalone` and `--suite project` are independent partitions; each
builds and runs all of its own positives before its control. `all` shares builds
but does not omit any case. `--functions` defaults to 20 for the synthetic
standalone correctness fixture; it does not replace the separate 1000-function
value gate. Every subprocess is sequential, logged, timed, and bounded. Output
directories must not exist, so canonical runs cannot silently reuse artifacts.
Artifact hashes, builder metadata, matrix samples, stderr, and command logs are
retained, including on failure. Self-tests exercise orchestration order and
strict rejection classification without launching a compiler.
Failed subprocesses print their identity, status, timeout flag, log hash and a
bounded log tail; builder failures also expose the private build log tail.
This makes CI failures diagnosable without printing complete artifacts, and
does not change which failures are accepted as negative-control evidence.

This is not a latency benchmark, a per-source attribution proof for the
two-module aggregate parse counts, retained-memory measurement, or default
activation evidence. Source-attributed project counters remain separate work.
No existing `/tmp` artifact is accepted by the canonical runner.

CI runs standalone in the `test-compiler` job and project in
`incremental-body-execution-1`. Each suite builds its own independent artifacts;
the runner self-test checks both invocations and itself appear exactly once.
No job is added. The measured all-suite command sums, including shared setup
and each scope's own control, are 118.98s and 119.11s. Doubling their rounded
values gives planning budgets of 908s and 901s including the prior job baselines,
below the unchanged 950s run pole. These are local planning figures, not whole
CI-job observations or performance acceptance.

Example (use the actual local JDK path, and a nonexistent output directory):

```bash
export JAVA_HOME=/path/to/jdk-21
python3 scripts/incremental-semantics-contract/configured-lsp-contract.py --self-test
python3 scripts/incremental-semantics-contract/configured-lsp-contract.py --suite all --output /tmp/configured-lsp-contract-run
```

The existing builder honors `DAWN_BIN` for its bootstrap compiler. Selecting a
stable launcher avoids rebuilding a separate worktree compiler; it does not
reuse any of the subject artifacts. An explicit `--asm-jar` may name the ASM
9.7.1 dependency when it is not in the normal Coursier cache. This runner pins
the child PATH to JAVA_HOME/bin and records both runtime/compiler version logs.
