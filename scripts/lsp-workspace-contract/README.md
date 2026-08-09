# LSP workspace contract

This directory owns the behavior added by slice D of
`docs/lsp-workspace-design.md`. `workspace.py` drives real JSON-RPC sessions;
an unsupported request is the synchronization barrier after every update, so
the contract contains no timing sleeps. `run.sh` builds both Java fixtures from
tracked sources into a private `file://` Maven repository and compiles private
selfhost copies for the positive server and every mutant.

The eighteen cases cover full live overlays, unsaved modules, on-disk module
self-exclusion, extensionless local buffers, same-project source-root isolation
in both open orders, close rollback, duplicate canonical paths, root-scoped
definitions, all-URI diagnostics and source views, external-diagnostic
aggregation, same-FQCN Java isolation in both open orders, standalone classpath
isolation, and lease cleanup on last close, shutdown, running exit, EOF, fatal
framing, and injected close failure. An unavailable workspace also stays
unavailable across `didChange` and retries exactly at `didSave`. Lease
assertions use a private test-only wrapper around `jsig_for`; production sources
expose no test hook and do not print lease events. The injected failure runs
only after the private wrapper has closed the real project loader and recorded
that successful close.

Every mutant is compiled before its one selected case runs. A mutant is
accepted as red only when the output contains that case's owning failure label;
a build failure, timeout, protocol failure, or unrelated assertion is not a
negative control.
