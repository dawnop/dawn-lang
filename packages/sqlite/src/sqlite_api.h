/* Private declarations avoid accidentally requiring a development sqlite3.h.
 * Signatures and constants follow SQLite's stable C API, minimum 3.35. */
#ifndef DAWN_SQLITE_API_H
#define DAWN_SQLITE_API_H
typedef struct sqlite3 sqlite3;
typedef struct sqlite3_stmt sqlite3_stmt;
struct sqlite_api {
  int (*open_v2)(const char *, sqlite3 **, int, const char *);
  int (*close)(sqlite3 *);
  int (*prepare_v2)(sqlite3 *, const char *, int, sqlite3_stmt **, const char **);
  int (*finalize)(sqlite3_stmt *);
  const char *(*errmsg)(sqlite3 *);
  int (*extended_errcode)(sqlite3 *);
  int (*libversion_number)(void);
};
#endif
