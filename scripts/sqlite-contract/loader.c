/* Wrap only the package's one soname at link time. LD_PRELOAD is insufficient:
 * ASan's executable-level dlopen interceptor can bypass a preload. The fixture
 * path and version are verified without adding test controls to production. */
#include <dlfcn.h>
#include <stdlib.h>
#include <string.h>
void *__real_dlopen(const char *, int);
void *__real_dlsym(void *, const char *);
void *__wrap_dlopen(const char *path, int flags) {
  const char *fixture = NULL;
  if (path && !strcmp(path, "libsqlite3.so.0")) {
    if (flags != (RTLD_NOW | RTLD_LOCAL)) abort();
    const char *mode = getenv("F3_LOADER_MODE");
    if (mode && !strcmp(mode, "no-library")) return NULL;
    fixture = getenv("F3_SQLITE_LIBRARY");
    if (fixture) path = fixture;
  }
  void *handle = __real_dlopen(path, flags);
  if (fixture) {
    if (!handle) abort();
    int (*version)(void) = (int (*)(void))__real_dlsym(handle, "sqlite3_libversion_number");
    if (!version || (version() != 3054001 && version() != 3035005)) abort();
  }
  return handle;
}
void *__wrap_dlsym(void *handle, const char *symbol) {
  const char *mode = getenv("F3_LOADER_MODE");
  if (mode && !strcmp(mode, "no-symbol") && !strcmp(symbol, "sqlite3_step")) return NULL;
  return __real_dlsym(handle, symbol);
}
