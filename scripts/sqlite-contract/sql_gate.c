/* Execute SQL while the host's C loading gate is open, inside extension init.
 * Testing only before/after loading would miss enable_load_extension(1). */
#include "sqlite3ext.h"
#include <string.h>
SQLITE_EXTENSION_INIT1
int sqlite3_extension_init(sqlite3 *db, char **error, const sqlite3_api_routines *routines) {
  SQLITE_EXTENSION_INIT2(routines);
  char *message = 0;
  int rc = sqlite3_exec(db, "select load_extension('missing')", 0, 0, &message);
  int blocked = rc != SQLITE_OK && message && strstr(message, "not authorized");
  sqlite3_free(message);
  if (blocked) return SQLITE_OK;
  *error = sqlite3_mprintf("sql load_extension was enabled during C loading");
  return SQLITE_ERROR;
}
