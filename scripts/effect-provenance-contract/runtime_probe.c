/* Keep the native probe independent of the Dawn emitter so mismatched
 * checkpoint lifetime rules cannot hide behind an emitter implementation. */
#include "dawn_provenance.c"
#include <assert.h>
#include "unicode_stubs.h"
#include <stdio.h>
#include <string.h>

const dawn_prov_site dawn_prov_sites[] = {{0, NULL}};
const size_t dawn_prov_sites_n = 0;
const dawn_prov_target dawn_prov_entries[] = {{NULL, NULL}};
const size_t dawn_prov_entries_n = 0;

static const char *mode;
static int64_t foreign_scope;
static int worker_status;
static void foreign_read(void) { dawn_drop(dawn_prov_completed(foreign_scope)); }
static void *worker(void *unused) {
  (void)unused;
  worker_status = dawn_rt_main(0, NULL, foreign_read);
  return NULL;
}
static void run(void) {
  int64_t s = dawn_prov_open();
  if (!strcmp(mode, "cross_thread")) {
    foreign_scope = s;
    pthread_t thread;
    assert(pthread_create(&thread, NULL, worker, NULL) == 0);
    assert(pthread_join(thread, NULL) == 0);
    assert(worker_status == 1);
    dawn_prov_close(s, 1); return;
  }
  if (!strcmp(mode, "cleanup")) {
    dawn_prov_close(s, 1);
    for (int i = 0; i < 1000; i++) {
      int64_t id = dawn_prov_open();
      int64_t token = dawn_prov_before(11, "helper"); dawn_prov_arrive("helper");
      dawn_str *mark = dawn_prov_checkpoint(id);
      int64_t nested = dawn_prov_before(12, "pure"); dawn_prov_arrive("pure"); dawn_prov_finish(nested, 1);
      dawn_prov_rewind(id, mark); dawn_prov_finish(token, 1);
      dawn_str *prefix = dawn_prov_completed(id); dawn_prov_close(id, 1);
      assert(prefix->len > 2 && !memcmp(prefix->p, "S\t", 2));
      dawn_drop(prefix); dawn_drop(mark);
      assert(dawn_prov_registry == NULL && dawn_prov_peek_state() == NULL);
    }
    puts("clean"); return;
  }
  if (!strcmp(mode, "reuse")) {
    int64_t f = dawn_prov_before(11, "helper"); dawn_prov_arrive("helper");
    dawn_str *c = dawn_prov_checkpoint(s);
    int64_t a = dawn_prov_before(12, "pure"); dawn_prov_arrive("pure"); dawn_prov_finish(a, 1);
    dawn_prov_rewind(s, c);
    int64_t b = dawn_prov_before(12, "pure"); dawn_prov_arrive("pure"); dawn_prov_finish(b, 1);
    dawn_prov_rewind(s, c);
    dawn_str *inner = dawn_prov_checkpoint(s);
    int64_t q = dawn_prov_before(13, "query"); dawn_prov_arrive("query"); dawn_prov_finish(q, 1);
    dawn_prov_rewind(s, inner); dawn_prov_rewind(s, c);
    dawn_prov_finish(f, 1);
    dawn_str *snapshot = dawn_prov_completed(s);
    fwrite(snapshot->p, 1, (size_t)snapshot->len, stdout); putchar('\n');
    dawn_drop(snapshot); dawn_drop(inner); dawn_drop(c);
    dawn_prov_close(s, 1); return;
  }
  dawn_str *c = dawn_prov_checkpoint(s);
  if (!strcmp(mode, "invalidated")) {
    dawn_str *later = dawn_prov_checkpoint(s); dawn_prov_rewind(s, c); dawn_prov_rewind(s, later);
  } else if (!strcmp(mode, "other")) {
    int64_t other = dawn_prov_open(); dawn_prov_rewind(other, c);
  } else if (!strcmp(mode, "exited")) {
    dawn_prov_close(s, 1); int64_t other = dawn_prov_open(); dawn_prov_rewind(other, c);
  } else if (!strcmp(mode, "deeper")) {
    dawn_prov_before(11, "helper"); dawn_prov_arrive("helper"); dawn_prov_rewind(s, c);
  } else if (!strcmp(mode, "finished") || !strcmp(mode, "same_site")) {
    int64_t f = dawn_prov_before(11, "helper"); dawn_prov_arrive("helper");
    dawn_drop(c); c = dawn_prov_checkpoint(s); dawn_prov_finish(f, 1);
    if (!strcmp(mode, "same_site")) { dawn_prov_before(11, "helper"); dawn_prov_arrive("helper"); }
    dawn_prov_rewind(s, c);
  }
}
int main(int argc, char **argv) {
  if (argc != 2) return 2;
  mode = argv[1]; int status = dawn_rt_main(argc, argv, run);
  return status ? status : worker_status;
}
