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
