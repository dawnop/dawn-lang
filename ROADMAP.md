# Roadmap

Directions, not commitments. Dawn is a research project with a single
maintainer; interfaces break when a design turns out to be wrong, and the
version number promises nothing yet. This file says where the work is going so
that a reader can pick something that will not be swept away next month. The
detailed thinking behind every line here lives in a design document under
[`docs/`](docs/README.md), and that index is the authority on what is settled,
what is in flight, and what was tried and closed.

## Active directions

**Frontend.** The goal is writing browser applications in Dawn. The Elm
architecture is in the tree today ([`packages/tea-core`](packages/tea-core),
[`packages/tea-dom`](packages/tea-dom)), the compiler emits wasm reactors for
it (`dawn build --target wasm --reactor`), and the stack passed its first real
browser run in 2026-08. The public demo is live at `/tea.html` on the project
site (source under `site/`, applications under `examples/projects/`); next are
the pieces the demo proves a need for. A declarative UI DSL in the Compose
style is the long-range
aim and is what several syntax decisions (trailing blocks, named arguments)
were made for.

**A native toolchain that owes Java nothing.** The compiler self-hosts on two
peer backends, JVM and C, and the native line is about making the C side fully
independent: the runtime-intrinsics contract
([`docs/runtime-intrinsics-design.md`](docs/runtime-intrinsics-design.md))
pushes `java.*` behind backend-owned intrinsics so the standard library stops
assuming a JVM underneath. Memory management on the native side is Perceus
reference counting with a slab allocator; that line is largely landed and its
remaining measured gap is recorded below under "good starting points".

**Tooling.** The LSP serves whole-workspace diagnostics today; a real LSP for
the online playground is deferred but wanted. `dawn fmt`, `dawn doc` and the
gate scripts are living surfaces and small sharp fixes to them are welcome.

## Closed lines

Several directions were investigated to a verdict and closed: alternative
allocators under the slab, reuse tokens for in-place update, sibling relative
imports, dotted module paths, and others. The design documents record each
verdict and the evidence it stands on. Reopening one takes new evidence, not
preference; a pull request that reopens a closed line without engaging its
design document will be declined on that ground alone.

## Contributing

[`CONTRIBUTING.md`](CONTRIBUTING.md) describes the one process this repository
actually runs: a design document before code, and gates instead of review
checklists. Concrete starting points are kept as GitHub issues; each names the
file it lives in, the way to reproduce or measure it, and the gate that will
hold the fix.
