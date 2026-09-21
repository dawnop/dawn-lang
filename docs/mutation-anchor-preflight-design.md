# Mutation anchor preflight

> Status: **current**. Source-anchor preflight for issue #92.

`python3 scripts/mutation-anchor-preflight.py` checks mutation applicability
before any compiler build. It executes the existing source mutators with
in-memory file writes, preserving their exact-match guards, secondary edits,
instrumentation and sequential replacements. It does not maintain another
copy of the anchor text. An initial local run checked 198 mutation
applications/locators in 5.38 seconds.

Adapters specify invocation paths only. Modes are discovered from literal
`MUTATIONS` keys and explicit name/mutation dispatch comparisons. The inventory
of `scripts/**/mutate.py` must match the adapters and explicit exclusions; adding
a mutator without an adapter fails. The two shell contract adapters extract
their existing mutation Python blocks without executing the surrounding shell.
The Java classpath bracket mutant receives its existing instrumentation first.

Gate-map edits are applied to its own baseline texts without running each
mutated coverage map. Their existing cardinality contracts remain authoritative:
single replacements require one match; deliberate global replacements require
at least one; file-addition and append controls retain their own preconditions.
The bundled-module expression is checked exactly once. The builtin-declaration
reader checks the real `comptime_rejects` loop spellings without emitting a
compiler artifact.

Two helpers do not own checkout-source anchors: classfile-verify mutates generated
bytecode, and tile-gpu-diff receives all replacement text from its callers. Their
exclusions are explicit and printed, not silently treated as source coverage.
Inline mutation harnesses outside the issue's named scope and documentation
quotations are not covered by this check. Existing executable semantic contracts
remain mandatory: applicability is not proof that a mutant compiles or detects
its intended defect.

CI runs the preflight and its negative controls in tree-policy, without a JDK.
Controls cover pure spelling drift, duplicate anchors, secondary edits, shell
anchors, unknown mutators, sequential instrumentation and refusal to start builds
or write directly to disk. The checkout must remain unchanged after every test.
