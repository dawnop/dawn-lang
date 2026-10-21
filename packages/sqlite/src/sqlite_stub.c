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
  if (api.libversion_number() < 3035000) {
    dlclose(lib); memset(&api, 0, sizeof(api));
    loader_kind = "sqlite.version"; loader_message = "SQLite 3.35 or newer is required";
    return dawn_ffi_err(loader_kind, loader_message);
  }
  /* F3b and F3c resolve their complete capability table before publishing it. */
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
  else forget(h);
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
