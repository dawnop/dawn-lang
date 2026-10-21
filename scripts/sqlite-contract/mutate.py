#!/usr/bin/env python3
"""Own each production mutation exactly once, including backend refusals.

The harness first compiles each mutant, then checks a named failing observation
or a precise ASan/LSan diagnosis. Preflight applies this registry in memory.
"""
from pathlib import Path
import sys

C = "packages/sqlite/src/sqlite_stub.c"
D = "packages/sqlite/src/sqlite.dawn"
MUTATIONS = {
    "static": ((C, "(void (*)(void *))-1", "(void (*)(void *))0"),),
    "column-delayed": ((C,
        "return dawn_ffi_ok(dawn_ffi_str_copy((const char *)text, size));",
        "api.step(s->ptr.stmt); api.finalize(s->ptr.stmt); return dawn_ffi_ok(dawn_ffi_str_copy((const char *)text, size));"),),
    "leak-finalize": ((C, "int rc = api.finalize(h->ptr.stmt);", "int rc = 0; /* omit finalization */"),),
    "double-finalize": ((C,
        "forget(h); /* finalize destroys the statement even when it reports a step error. */",
        "/* Leave a dead SQLite pointer under a live token. */"),),
    "stale-token": ((C, "*p = h->next; free(h);", "*p = h->next; next_token = h->token; free(h);"),),
    "parent": ((C, "!find_handle(db, 1) || !h || h->parent != db", "!find_handle(db, 1) || !h"),),
    "row-state": ((C, "#define COLUMN_CHECK if (s->state != 1) return state_error();", "#define COLUMN_CHECK /* omit the row state check */"),),
    "column-range": ((C,
        "COLUMN_CHECK; return integer(api.column_int64(s->ptr.stmt, (int)index));",
        "if (s->state != 1) return state_error(); return integer(api.column_int64(s->ptr.stmt, (int)index));"),),
    "utf8": ((C,
        'if (!valid_utf8(text, size)) return dawn_ffi_err("sqlite.invalid_utf8", "column is not valid UTF-8");',
        '/* accept invalid UTF-8 */'),),
    "bind-range": ((C,
        "if (index < 1 || index > api.bind_parameter_count(s->ptr.stmt)) return range_error()",
        "if (false) return range_error()"),),
    "text-nul": ((C, "(int)dawn_ffi_str_len(value), (void (*)(void *))-1", "(int)strlen(dawn_ffi_str_data(value)), (void (*)(void *))-1"),),
    "int-width": ((C, "api.bind_int64(s->ptr.stmt, (int)index, value)", "api.bind_int64(s->ptr.stmt, (int)index, (int)value)"),),
    "null": ((D, "if kind == 5 { return Ok(Null) }", "if kind == -1 { return Ok(Null) }"),),
    "empty-label": ((C,
        "const char *name = api.column_name(s->ptr.stmt, (int)index);",
        "if (s->state != 1) return state_error(); const char *name = api.column_name(s->ptr.stmt, (int)index);"),),
    "path-nul": ((C, "const char *name = dawn_ffi_cstr(path);", "const char *name = dawn_ffi_str_data(path);"),),
    "sql-nul": ((C, "const char *text = dawn_ffi_cstr(sql);", "const char *text = dawn_ffi_str_data(sql);"),),
    "entry-nul": ((C,
        "symbol = dawn_ffi_cstr((dawn_str *)dawn_ffi_payload(entry));",
        "symbol = dawn_ffi_str_data((dawn_str *)dawn_ffi_payload(entry));"),),
    "empty-path": ((C, "if (!name) return dawn_ffi_err", "if (!name || !*name) return dawn_ffi_err"),),
    "autocommit": ((C, "dawn_ffi_box_bool(api.get_autocommit(d->ptr.db) != 0)", "dawn_ffi_box_bool(true)"),),
    "panic-rollback": ((D, "report_cleanup(rollback(connection))", "report_cleanup(Ok(()))"),),
    "commit-rollback": ((D,
        'Err(e) -> finish(Err(e), rollback(held))\n    }',
        'Err(e) -> Err(e)\n    }'),
        (D, "report_cleanup(rollback(connection))", "report_cleanup(Ok(()))")),
    "nested-rollback": ((D,
        '  if in_transaction(db)? { return Err(error("nested_transaction", "transaction already active")) }',
        '  rollback(db)?\n  if in_transaction(db)? { return Err(error("nested_transaction", "transaction already active")) }'),),
    "sql-load": ((C, "int rc = api.db_config(d->ptr.db, 1005, 1, NULL);",
        'int rc = ((int (*)(sqlite3 *, int))dlsym(library, "sqlite3_enable_load_extension"))(d->ptr.db, 1);'),),
    "no-simple": ((C, "rc = api.load_extension(d->ptr.db, file, symbol, &message);", "rc = 0; /* swallow all extension loading */"),),
    "swallow-extension": ((C, "if (error) return error; /* Preserve the load failure after closing the C gate. */",
        "if (error) return unit(); /* swallow the extension failure */"),),
    "jvm-success": ((D,
        'extern c "sqlite_busy_timeout" else Err(unsupported())',
        'extern c "sqlite_busy_timeout" else Ok(())'),),
    "wasi-success": ((C,
        'return dawn_ffi_err("sqlite.unsupported_backend", "SQLite requires Linux native");',
        'return dawn_ffi_ok(dawn_ffi_box_unit());'),),
}


def main():
    name, root = sys.argv[1], Path(sys.argv[2])
    for rel, old, new in MUTATIONS[name]:
        path = root / rel
        source = path.read_text()
        assert source.count(old) == 1, (name, rel, source.count(old))
        path.write_text(source.replace(old, new))


if __name__ == "__main__":
    main()
