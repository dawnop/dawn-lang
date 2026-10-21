/* Keep SQLite outside the compiler and the Dawn allocator. The table stores
 * only C resources, never borrowed Dawn values. Positive tokens are never reused;
 * deleting the final entry leaves no global root hiding a leaked SQLite object.
 * Production resolves one system soname; fixtures interpose the loader externally. */
#include "dawn_ffi.h"
DAWN_FFI_REQUIRE(1);

#ifdef __wasi__
static dawn_adt *unsupported(void) {
  return dawn_ffi_err("sqlite.unsupported_backend", "SQLite requires Linux native");
}
#else
#include <dlfcn.h>
#include <limits.h>
#include <stdlib.h>
#include "sqlite_api.h"

static struct sqlite_api api;
static void *library;
static const char *loader_kind;
static const char *loader_message;

static dawn_adt *load_api(void) {
  if (library) return NULL;
  if (loader_kind) return dawn_ffi_err(loader_kind, loader_message);
  void *lib = dlopen("libsqlite3.so.0", RTLD_NOW | RTLD_LOCAL);
  if (!lib) {
    loader_kind = "sqlite.no_library";
    loader_message = "cannot load libsqlite3.so.0";
    return dawn_ffi_err(loader_kind, loader_message);
  }
#define RESOLVE(field) do { \
  *(void **)(&api.field) = dlsym(lib, "sqlite3_" #field); \
  if (!api.field) { loader_kind = "sqlite.no_symbol"; \
    loader_message = "missing sqlite3_" #field; dlclose(lib); \
    memset(&api, 0, sizeof(api)); return dawn_ffi_err(loader_kind, loader_message); } \
} while (0)
  RESOLVE(open_v2); RESOLVE(close); RESOLVE(prepare_v2); RESOLVE(finalize);
  RESOLVE(errmsg); RESOLVE(extended_errcode); RESOLVE(libversion_number);
  if (api.libversion_number() < 3035005) {
    dlclose(lib); memset(&api, 0, sizeof(api));
    loader_kind = "sqlite.version"; loader_message = "SQLite 3.35.5 or newer is required";
    return dawn_ffi_err(loader_kind, loader_message);
  }
  RESOLVE(bind_parameter_count); RESOLVE(bind_int64); RESOLVE(bind_double);
  RESOLVE(bind_text); RESOLVE(bind_null); RESOLVE(step); RESOLVE(column_count);
  RESOLVE(column_type); RESOLVE(column_int64); RESOLVE(column_double);
  RESOLVE(column_text); RESOLVE(column_bytes); RESOLVE(column_name); RESOLVE(changes);
  RESOLVE(last_insert_rowid); RESOLVE(get_autocommit); RESOLVE(busy_timeout);
  RESOLVE(db_config); RESOLVE(load_extension); RESOLVE(free);
  library = lib;
  return NULL;
}

struct handle {
  int64_t token, parent;
  int kind, state;
  union { sqlite3 *db; sqlite3_stmt *stmt; } ptr;
  struct handle *next;
};
static struct handle *handles;
static int64_t next_token = 1;

static struct handle *find_handle(int64_t token, int kind) {
  for (struct handle *h = handles; h; h = h->next)
    if (h->token == token && h->kind == kind) return h;
  return NULL;
}
static struct handle *statement(int64_t db, int64_t token) {
  struct handle *h = find_handle(token, 2);
  if (!find_handle(db, 1) || !h || h->parent != db) return NULL;
  return h;
}
static struct handle *new_handle(int kind, int64_t parent) {
  if (next_token == INT64_MAX) return NULL;
  struct handle *h = calloc(1, sizeof(*h));
  if (!h) return NULL;
  h->token = next_token++; h->kind = kind; h->parent = parent;
  h->next = handles; handles = h;
  return h;
}
static void forget(struct handle *h) {
  struct handle **p = &handles;
  while (*p != h) p = &(*p)->next;
  *p = h->next; free(h);
}
static dawn_adt *invalid(void) {
  return dawn_ffi_err("sqlite.invalid_handle", "expired handle or wrong parent connection");
}
static dawn_adt *unit(void) { return dawn_ffi_ok(dawn_ffi_box_unit()); }
static dawn_adt *integer(int64_t n) { return dawn_ffi_ok(dawn_ffi_box_int(n)); }
static dawn_adt *failure(sqlite3 *db, int rc) {
  const char *kind;
  switch (rc & 255) {
    case 5: kind = "sqlite.busy"; break;
    case 6: kind = "sqlite.locked"; break;
    case 7: kind = "sqlite.no_memory"; break;
    case 8: kind = "sqlite.readonly"; break;
    case 14: kind = "sqlite.cant_open"; break;
    case 19: kind = "sqlite.constraint"; break;
    default: kind = "sqlite.error"; break;
  }
  return dawn_ffi_err(kind, db ? api.errmsg(db) : "SQLite operation failed");
}
static dawn_adt *close_handle(int64_t token, bool quiet) {
  struct handle *h = find_handle(token, 1);
  if (!h) return quiet ? unit() : invalid();
  dawn_adt *error = NULL;
  for (struct handle *s = handles, *next; s; s = next) {
    next = s->next;
    if (s->kind == 2 && s->parent == token) {
      int rc = api.finalize(s->ptr.stmt);
      if (rc && !error) error = failure(h->ptr.db, rc);
      forget(s);
    }
  }
  int rc = api.close(h->ptr.db);
  if (rc) { if (!error) error = failure(h->ptr.db, rc); }
  /* Retire the token even on a close error; never hide unreleased C resources
   * behind a permanent global root. The caller observes the cleanup failure. */
  forget(h);
  return error ? error : unit();
}
static dawn_adt *finalize_handle(int64_t db, int64_t token, bool quiet) {
  struct handle *h = statement(db, token);
  if (!h) return quiet && !find_handle(token, 2) ? unit() : invalid();
  int rc = api.finalize(h->ptr.stmt);
  forget(h); /* finalize destroys the statement even when it reports a step error. */
  return rc ? failure(find_handle(db, 1)->ptr.db, rc) : unit();
}
#endif

dawn_adt *DAWN_EXTERN(sqlite_open)(dawn_str *path, bool uri) {
#ifdef __wasi__
  return unsupported();
#else
  const char *name = dawn_ffi_cstr(path);
  if (!name) return dawn_ffi_err("sqlite.embedded_nul", "NUL in database path");
  dawn_adt *error = load_api(); if (error) return error;
  sqlite3 *db = NULL;
  int rc = api.open_v2(name, &db, 2 | 4 | 0x10000 | (uri ? 0x40 : 0), NULL);
  if (rc) { error = failure(db, rc); if (db) api.close(db); return error; }
  struct handle *h = new_handle(1, 0);
  if (!h) { api.close(db); return dawn_ffi_err("sqlite.no_memory", "handle allocation failed"); }
  h->ptr.db = db; return integer(h->token);
#endif
}
dawn_adt *DAWN_EXTERN(sqlite_close)(int64_t db) {
#ifdef __wasi__
  return unsupported();
#else
  return close_handle(db, false);
#endif
}
dawn_adt *DAWN_EXTERN(sqlite_release_db)(int64_t db) {
#ifdef __wasi__
  return unsupported();
#else
  return close_handle(db, true);
#endif
}
dawn_adt *DAWN_EXTERN(sqlite_prepare)(int64_t db, dawn_str *sql) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *h = find_handle(db, 1); if (!h) return invalid();
  const char *text = dawn_ffi_cstr(sql);
  if (!text) return dawn_ffi_err("sqlite.embedded_nul", "NUL in SQL");
  if (dawn_ffi_str_len(sql) >= INT_MAX) return dawn_ffi_err("sqlite.range", "SQL exceeds C int length");
  sqlite3_stmt *stmt = NULL; const char *tail = NULL;
  int rc = api.prepare_v2(h->ptr.db, text, (int)dawn_ffi_str_len(sql) + 1, &stmt, &tail);
  if (rc) { dawn_adt *e = failure(h->ptr.db, rc); if (stmt) api.finalize(stmt); return e; }
  if (!stmt) return dawn_ffi_err("sqlite.empty_sql", "expected one SQL statement");
  /* Let SQLite parse the suffix: comments and quoted semicolons are not SQL splitting. */
  while (tail && *tail) {
    sqlite3_stmt *extra = NULL; const char *next = NULL;
    rc = api.prepare_v2(h->ptr.db, tail, -1, &extra, &next);
    if (rc || extra) {
      dawn_adt *e = rc ? failure(h->ptr.db, rc) : dawn_ffi_err("sqlite.multiple_statements", "expected one SQL statement");
      if (extra) api.finalize(extra);
      api.finalize(stmt); return e;
    }
    if (next == tail) break;
    tail = next;
  }
  struct handle *s = new_handle(2, db);
  if (!s) { api.finalize(stmt); return dawn_ffi_err("sqlite.no_memory", "handle allocation failed"); }
  s->ptr.stmt = stmt; return integer(s->token);
#endif
}
dawn_adt *DAWN_EXTERN(sqlite_finalize)(int64_t db, int64_t stmt) {
#ifdef __wasi__
  return unsupported();
#else
  return finalize_handle(db, stmt, false);
#endif
}
dawn_adt *DAWN_EXTERN(sqlite_release_stmt)(int64_t db, int64_t stmt) {
#ifdef __wasi__
  return unsupported();
#else
  return finalize_handle(db, stmt, true);
#endif
}

#ifndef __wasi__
static dawn_adt *range_error(void) { return dawn_ffi_err("sqlite.range", "index, size or timeout outside C int range"); }
static dawn_adt *state_error(void) { return dawn_ffi_err("sqlite.statement_state", "operation invalid in this statement state"); }
#define BIND_CHECK struct handle *d = find_handle(db, 1); \
  if (s->state != 0) return state_error(); \
  if (index < 1 || index > api.bind_parameter_count(s->ptr.stmt)) return range_error()
#define COLUMN_CHECK if (s->state != 1) return state_error(); \
  if (index < 0 || index >= api.column_count(s->ptr.stmt)) return range_error()

/* Reject overlong encodings, surrogates, truncation and values above U+10FFFF.
 * SQLite permits arbitrary TEXT bytes; Dawn String requires valid UTF-8. */
static bool valid_utf8(const unsigned char *p, int n) {
  for (int i = 0; i < n;) {
    unsigned c = p[i++], v, count, minimum;
    if (c < 0x80) continue;
    if (c >= 0xc2 && c <= 0xdf) { v = c & 31; count = 1; minimum = 0x80; }
    else if (c >= 0xe0 && c <= 0xef) { v = c & 15; count = 2; minimum = 0x800; }
    else if (c >= 0xf0 && c <= 0xf4) { v = c & 7; count = 3; minimum = 0x10000; }
    else return false;
    if ((unsigned)(n - i) < count) return false;
    while (count--) { c = p[i++]; if ((c & 0xc0) != 0x80) return false; v = (v << 6) | (c & 63); }
    if (v < minimum || v > 0x10ffff || (v >= 0xd800 && v <= 0xdfff)) return false;
  }
  return true;
}
#endif

dawn_adt *DAWN_EXTERN(sqlite_bind_count)(int64_t db, int64_t stmt) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *s = statement(db, stmt); if (!s) return invalid();
  return integer(api.bind_parameter_count(s->ptr.stmt));
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_bind_int)(int64_t db, int64_t stmt, int64_t index, int64_t value) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *s = statement(db, stmt); if (!s) return invalid();
  BIND_CHECK; int rc = api.bind_int64(s->ptr.stmt, (int)index, value); return rc ? failure(d->ptr.db, rc) : unit();
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_bind_float)(int64_t db, int64_t stmt, int64_t index, double value) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *s = statement(db, stmt); if (!s) return invalid();
  BIND_CHECK; int rc = api.bind_double(s->ptr.stmt, (int)index, value); return rc ? failure(d->ptr.db, rc) : unit();
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_bind_null)(int64_t db, int64_t stmt, int64_t index) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *s = statement(db, stmt); if (!s) return invalid();
  BIND_CHECK; int rc = api.bind_null(s->ptr.stmt, (int)index); return rc ? failure(d->ptr.db, rc) : unit();
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_bind_text)(int64_t db, int64_t stmt, int64_t index, dawn_str *value) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *s = statement(db, stmt); if (!s) return invalid();
  BIND_CHECK;
  if (dawn_ffi_str_len(value) > INT_MAX) return range_error();
  /* Arguments are borrowed: TRANSIENT copies before Dawn can release value.
   * STATIC would retain a dangling pointer after this call. Length preserves NUL. */
  int rc = api.bind_text(s->ptr.stmt, (int)index, dawn_ffi_str_data(value),
                         (int)dawn_ffi_str_len(value), (void (*)(void *))-1);
  return rc ? failure(d->ptr.db, rc) : unit();
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_step)(int64_t db, int64_t stmt) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *s = statement(db, stmt); if (!s) return invalid();
  if (s->state > 1) return state_error();
  int rc = api.step(s->ptr.stmt);
  s->state = rc == 100 ? 1 : rc == 101 ? 2 : 3;
  return rc == 100 || rc == 101 ? integer(rc) : failure(find_handle(db, 1)->ptr.db, rc);
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_column_count)(int64_t db, int64_t stmt) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *s = statement(db, stmt); if (!s) return invalid();
  return integer(api.column_count(s->ptr.stmt));
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_column_type)(int64_t db, int64_t stmt, int64_t index) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *s = statement(db, stmt); if (!s) return invalid();
  COLUMN_CHECK; return integer(api.column_type(s->ptr.stmt, (int)index));
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_column_int)(int64_t db, int64_t stmt, int64_t index) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *s = statement(db, stmt); if (!s) return invalid();
  COLUMN_CHECK; return integer(api.column_int64(s->ptr.stmt, (int)index));
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_column_float)(int64_t db, int64_t stmt, int64_t index) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *s = statement(db, stmt); if (!s) return invalid();
  COLUMN_CHECK; return dawn_ffi_ok(dawn_ffi_box_float(api.column_double(s->ptr.stmt, (int)index)));
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_column_text)(int64_t db, int64_t stmt, int64_t index) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *s = statement(db, stmt); if (!s) return invalid();
  COLUMN_CHECK;
  const unsigned char *text = api.column_text(s->ptr.stmt, (int)index);
  int size = api.column_bytes(s->ptr.stmt, (int)index);
  if (!text) return failure(find_handle(db, 1)->ptr.db, 7);
  if (!valid_utf8(text, size)) return dawn_ffi_err("sqlite.invalid_utf8", "column is not valid UTF-8");
  /* Copy now: the next conversion, step or finalize can invalidate text. */
  return dawn_ffi_ok(dawn_ffi_str_copy((const char *)text, size));
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_column_name)(int64_t db, int64_t stmt, int64_t index) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *s = statement(db, stmt); if (!s) return invalid();
  if (index < 0 || index >= api.column_count(s->ptr.stmt)) return range_error();
  const char *name = api.column_name(s->ptr.stmt, (int)index);
  if (!name) return failure(find_handle(db, 1)->ptr.db, 7);
  if (!valid_utf8((const unsigned char *)name, (int)strlen(name))) return dawn_ffi_err("sqlite.invalid_utf8", "column name is not valid UTF-8");
  return dawn_ffi_ok(dawn_ffi_str_from_cstr(name));
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_changes)(int64_t db) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *d = find_handle(db, 1); if (!d) return invalid();
  return integer(api.changes(d->ptr.db));
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_last_id)(int64_t db) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *d = find_handle(db, 1); if (!d) return invalid();
  return integer(api.last_insert_rowid(d->ptr.db));
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_autocommit)(int64_t db) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *d = find_handle(db, 1); if (!d) return invalid();
  return dawn_ffi_ok(dawn_ffi_box_bool(api.get_autocommit(d->ptr.db) != 0));
#endif
}

dawn_adt *DAWN_EXTERN(sqlite_busy_timeout)(int64_t db, int64_t ms) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *d = find_handle(db, 1); if (!d) return invalid();
  if (ms < 0 || ms > INT_MAX) return range_error();
  int rc = api.busy_timeout(d->ptr.db, (int)ms);
  return rc ? failure(d->ptr.db, rc) : unit();
#endif
}


dawn_adt *DAWN_EXTERN(sqlite_load_extension)(int64_t db, dawn_str *path, dawn_adt *entry) {
#ifdef __wasi__
  return unsupported();
#else
  struct handle *d = find_handle(db, 1); if (!d) return invalid();
  const char *file = dawn_ffi_cstr(path), *symbol = NULL;
  if (dawn_ffi_is_some(entry)) symbol = dawn_ffi_cstr((dawn_str *)dawn_ffi_payload(entry));
  if (!file || (dawn_ffi_is_some(entry) && !symbol))
    return dawn_ffi_err("sqlite.embedded_nul", "NUL in extension path or entry");
  /* db_config enables ONLY the C API, never the SQL load_extension function. */
  int rc = api.db_config(d->ptr.db, 1005, 1, NULL);
  if (rc) return failure(d->ptr.db, rc);
  char *message = NULL;
  rc = api.load_extension(d->ptr.db, file, symbol, &message);
  dawn_adt *error = rc ? dawn_ffi_err("sqlite.extension", message ? message : api.errmsg(d->ptr.db)) : NULL;
  if (message) api.free(message);
  int disabled = api.db_config(d->ptr.db, 1005, 0, NULL);
  if (error) return error; /* Preserve the load failure after closing the C gate. */
  return disabled ? failure(d->ptr.db, disabled) : unit();
#endif
}
