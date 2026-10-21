/* Private declarations avoid accidentally requiring a development sqlite3.h.
 * Signatures and constants follow SQLite's stable C API, minimum 3.35.5.
 * SQLite's int64 typedef is long long, whereas glibc's int64_t may be long;
 * the function pointer type must match even when both use 64-bit registers. */
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
  int (*bind_parameter_count)(sqlite3_stmt *);
  int (*bind_int64)(sqlite3_stmt *, int, long long);
  int (*bind_double)(sqlite3_stmt *, int, double);
  int (*bind_text)(sqlite3_stmt *, int, const char *, int, void (*)(void *));
  int (*bind_null)(sqlite3_stmt *, int);
  int (*step)(sqlite3_stmt *);
  int (*column_count)(sqlite3_stmt *);
  int (*column_type)(sqlite3_stmt *, int);
  long long (*column_int64)(sqlite3_stmt *, int);
  double (*column_double)(sqlite3_stmt *, int);
  const unsigned char *(*column_text)(sqlite3_stmt *, int);
  int (*column_bytes)(sqlite3_stmt *, int);
  const char *(*column_name)(sqlite3_stmt *, int);
  int (*changes)(sqlite3 *);
  long long (*last_insert_rowid)(sqlite3 *);
  int (*get_autocommit)(sqlite3 *);
  int (*busy_timeout)(sqlite3 *, int);
  int (*db_config)(sqlite3 *, int, ...);
  int (*load_extension)(sqlite3 *, const char *, const char *, char **);
  void (*free)(void *);
};
#endif
