/* Keep the native probe independent of the Dawn emitter so mismatched
 * checkpoint lifetime rules cannot hide behind an emitter implementation. */
#include "dawn_provenance.c"
#include <assert.h>
#include "unicode_stubs.h"
#include <stdio.h>
#include <string.h>

const dawn_prov_site dawn_prov_sites[] = {{11, "helper"}, {12, "pure"}, {13, "query"}, {14, "pure\t\t0\t1\t0\t1\tperform\tAsk:ask"}};
const size_t dawn_prov_sites_n = 4;
#define HELPER "helper\t\t0\t1\tfunction\t101"
#define PURE "pure\t\t0\t1\tfunction\t102"
#define QUERY "query\t\t0\t1\tfunction\t103"
const char *const dawn_prov_definitions[] = {HELPER, PURE, QUERY};
const size_t dawn_prov_definitions_n = 3;
#define PROBE_STRING(name, value) static dawn_str name = {{DAWN_IMMORTAL, DAWN_K_STR}, sizeof(value)-1, value}
PROBE_STRING(helper, "helper"); PROBE_STRING(pure, "pure"); PROBE_STRING(query, "query");
PROBE_STRING(empty, ""); PROBE_STRING(call, "call"); PROBE_STRING(perform, "perform"); PROBE_STRING(operation, "Ask:ask"); PROBE_STRING(function, "function");
const dawn_prov_site_fields dawn_prov_static_sites[] = {
  {11,0,1,0,1,&helper,&empty,&call,&empty}, {12,0,1,0,1,&pure,&empty,&call,&empty}, {13,0,1,0,1,&query,&empty,&call,&empty}, {14,0,1,0,1,&pure,&empty,&perform,&operation}
};
const dawn_prov_definition_fields dawn_prov_static_definitions[] = {
  {101,0,1,&helper,&empty,&function}, {102,0,1,&pure,&empty,&function}, {103,0,1,&query,&empty,&function}
};
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
  int64_t s = !strncmp(mode,"bounded_",8) ? dawn_prov_open_capacity(1) : dawn_prov_open();
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
      int64_t token = dawn_prov_before(11, "helper"); dawn_prov_arrive(HELPER);
      dawn_str *mark = dawn_prov_checkpoint(id);
      int64_t nested = dawn_prov_before(12, "pure"); dawn_prov_arrive(PURE); dawn_prov_finish(nested, 1);
      dawn_prov_rewind(id, mark); dawn_prov_finish(token, 1);
      dawn_adt *frozen = dawn_prov_completed(id);
      dawn_str *prefix = dawn_prov_render_snapshot(frozen); dawn_drop(frozen); dawn_prov_close(id, 1);
      assert(prefix->len > 2 && !memcmp(prefix->p, "S1\t", 3));
      dawn_drop(prefix); dawn_drop(mark);
      assert(dawn_prov_registry == NULL && dawn_prov_peek_state() == NULL);
    }
    puts("clean"); return;
  }
  if (!strcmp(mode, "reuse")) {
    int64_t f = dawn_prov_before(11, "helper"); dawn_prov_arrive(HELPER);
    dawn_str *c = dawn_prov_checkpoint(s);
    int64_t a = dawn_prov_before(12, "pure"); dawn_prov_arrive(PURE); dawn_prov_finish(a, 1);
    dawn_prov_rewind(s, c);
    int64_t b = dawn_prov_before(12, "pure"); dawn_prov_arrive(PURE); dawn_prov_finish(b, 1);
    dawn_prov_rewind(s, c);
    dawn_str *inner = dawn_prov_checkpoint(s);
    int64_t q = dawn_prov_before(13, "query"); dawn_prov_arrive(QUERY); dawn_prov_finish(q, 1);
    dawn_prov_rewind(s, inner); dawn_prov_rewind(s, c);
    dawn_prov_finish(f, 1);
    dawn_adt *frozen = dawn_prov_completed(s);
    dawn_str *snapshot = dawn_prov_render_snapshot(frozen); dawn_drop(frozen);
    fwrite(snapshot->p, 1, (size_t)snapshot->len, stdout); putchar('\n');
    dawn_drop(snapshot); dawn_drop(inner); dawn_drop(c);
    dawn_prov_close(s, 1); return;
  }
  if (!strcmp(mode,"unknown")) {
    int64_t f=dawn_prov_before(11,"helper"); dawn_prov_unknown_ctx(dawn_prov_context()); dawn_prov_finish(f,1);
    dawn_adt *snapshot=dawn_prov_completed(s); dawn_str *text=dawn_prov_render_snapshot(snapshot);
    puts(text->p); dawn_drop(text); dawn_drop(snapshot); dawn_prov_close(s,1); return;
  }
  if (!strncmp(mode,"bounded_",8)) {
    int64_t f=!strcmp(mode,"bounded_tail_epoch") ? dawn_prov_before(14,"pure\t\t0\t1\t0\t1\tperform\tAsk:ask") : dawn_prov_before(11,"helper"); dawn_prov_arrive(HELPER);
    dawn_str *mark=dawn_prov_checkpoint(s);
    if (!strcmp(mode,"bounded_tail_epoch")) {
      int64_t child=dawn_prov_before(12,"pure"); dawn_prov_arrive(PURE); dawn_prov_finish(child,1);
      dawn_prov_rewind(s,mark); dawn_prov_tail(14,"pure\t\t0\t1\t0\t1\tperform\tAsk:ask");
      dawn_adt *origin=dawn_prov_origin(s); dawn_str *text=dawn_prov_render_origin(origin);
      assert(strstr(text->p,"\nF\t1\t1\t2\t0\t0\t14\tpure"));
      dawn_drop(text); dawn_drop(origin); dawn_drop(mark); dawn_prov_finish(f,1); dawn_prov_close(s,1);
      puts("1 2 original operation identity after rewind and tail"); return;
    }
    if (!strcmp(mode,"bounded_suspended")) {
      void *driver=dawn_prov_control_capture(), *target=dawn_prov_control_capture();
      dawn_prov_before(12,"pure"); dawn_prov_arrive(PURE);
      dawn_prov_control_save(target,0); dawn_prov_control_attach(driver); dawn_prov_control_release(driver);
      dawn_prov_rewind(s,mark);
    }
    if (!strcmp(mode,"bounded_finished")) { dawn_prov_finish(f,1); dawn_prov_rewind(s,mark); }
    if (!strcmp(mode,"bounded_deeper")) { dawn_prov_before(12,"pure"); dawn_prov_arrive(PURE); dawn_prov_rewind(s,mark); }
    for (int i=0;i<2;i++) {
      int64_t child=dawn_prov_before(12,"pure"); dawn_prov_arrive(PURE); dawn_prov_finish(child,1); dawn_prov_rewind(s,mark);
    }
    dawn_prov_finish(f,1);
    dawn_adt *snapshot=dawn_prov_completed(s); dawn_str *text=dawn_prov_render_snapshot(snapshot);
    puts(text->p); dawn_drop(text); dawn_drop(snapshot); dawn_drop(mark); dawn_prov_close(s,1); return;
  }
  dawn_str *c = dawn_prov_checkpoint(s);
  if (!strcmp(mode, "invalidated")) {
    dawn_str *later = dawn_prov_checkpoint(s); dawn_prov_rewind(s, c); dawn_prov_rewind(s, later);
  } else if (!strcmp(mode, "other")) {
    int64_t other = dawn_prov_open(); dawn_prov_rewind(other, c);
  } else if (!strcmp(mode, "exited")) {
    dawn_prov_close(s, 1); int64_t other = dawn_prov_open(); dawn_prov_rewind(other, c);
  } else if (!strcmp(mode, "deeper")) {
    dawn_prov_before(11, "helper"); dawn_prov_arrive(HELPER); dawn_prov_rewind(s, c);
  } else if (!strcmp(mode, "finished") || !strcmp(mode, "same_site")) {
    int64_t f = dawn_prov_before(11, "helper"); dawn_prov_arrive(HELPER);
    dawn_drop(c); c = dawn_prov_checkpoint(s); dawn_prov_finish(f, 1);
    if (!strcmp(mode, "same_site")) { dawn_prov_before(11, "helper"); dawn_prov_arrive(HELPER); }
    dawn_prov_rewind(s, c);
  }
}
int main(int argc, char **argv) {
  if (argc != 2) return 2;
  mode = argv[1]; int status = dawn_rt_main(argc, argv, run);
  return status ? status : worker_status;
}
