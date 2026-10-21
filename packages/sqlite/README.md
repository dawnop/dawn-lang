# sqlite

Scoped SQLite connections and materialized queries through the C extern ABI.
The native package loads the system `libsqlite3.so.0` using
`RTLD_NOW | RTLD_LOCAL`. It supports Linux with glibc 2.34 or newer and dynamic
linking. SQLite 3.35 or newer is required. Missing libraries and symbols return
`sqlite.no_library` and `sqlite.no_symbol`; loading never calls a missing symbol.
JVM and WASI operations return `sqlite.unsupported_backend`.

Use `sqlite/sqlite`. Connections are valid only inside `with_db`; statements
remain private. Tokens are never reused, so a connection captured from a finished
scope returns `sqlite.invalid_handle`. Calls belong to one OS thread; multiple
connections may be used on that thread. Dawn reference counting manages copied
values, while `bracket` closes SQLite resources on return and panic.

The package does not bundle SQLite or libsimple, expose borrowed column views,
or support static linking, other operating systems, or WASI persistence.

```dawn
use sqlite/sqlite

# Give the result a type so the callback's ? expressions have context.
let answer: Result[sqlite.Rows, ForeignError] = sqlite.with_db(":memory:", db =>
  sqlite.query(db, "select ? as title", [sqlite.Text("hello")], [sqlite.ColText]))
```

`Value` is `Integer`, `Real`, `Text` or `Null`. `ColInt`, `ColFloat` and `ColText`
request SQLite conversions; SQL NULL always becomes `Null`. `Rows.names` keeps
labels (including duplicates) even for an empty result. Every text and label is
copied, and invalid UTF-8 returns `sqlite.invalid_utf8`. Bindings preserve embedded
NUL; paths, SQL and extension entry points reject it as `sqlite.embedded_nul`.
Parameters start at 1 and columns at 0. Counts must match. Empty SQL and multiple
statements are refused; trailing comments are allowed.

`execute` consumes one statement and discards rows. `execute_changes` is for DML:
it returns `sqlite3_changes`, limited to C int range. DDL retains the preceding
DML count in SQLite; use `execute` for DDL, PRAGMA and transaction statements.
`last_id` preserves signed 64-bit rowids. `busy_timeout` accepts 0 to 2147483647 ms.

`with_tx(db, Deferred | Immediate, body)` rejects nesting. It commits `Ok` and
rolls back `Err`, panic and failed commits. `in_transaction` reads SQLite's real
autocommit flag, including automatic rollbacks. Cleanup errors append to a
primary error's message and preserve its kind. During panic, cleanup is best
effort and the original panic propagates. There are no automatic savepoints.
