/* Scope mutation is confined to this adverse producer. All actual field
 * assertions execute in the public compiled Dawn reader after scope exit. */
#define main dawn_original_main
#include "snapshot_metadata-native.c"
#undef main
#include <stdio.h>
static dawn_str *text(const char *s) { return dawn_str_copy(s,(int64_t)strlen(s)); }
static void probe(void) {
  dawn_adt *numbers=dawn_adt_new(0,5,31),*strings=dawn_adt_new(0,5,31);
  int64_t ns[]={999,1,7,2,4}; for(int i=0;i<5;i++) numbers->fields[i].p=dawn_box_int(ns[i]);
  strings->fields[0].p=text("unit%09\t雪"); strings->fields[1].p=text("unit%09\t雪");
  strings->fields[2].p=text("decl%25\n雪"); strings->fields[3].p=text("call"); strings->fields[4].p=text("op%09\t雪");
  dawn_adt *site=dawn_adt_new(0,2,3); site->fields[0].p=numbers;site->fields[1].p=strings;
  dawn_adt *definition=dawn_adt_new(0,6,63);
  definition->fields[0].p=dawn_box_int(888);definition->fields[1].p=text("unit%09\t雪");
  definition->fields[2].p=text("decl%25\n雪");definition->fields[3].p=dawn_box_int(0);
  definition->fields[4].p=dawn_box_int(9);definition->fields[5].p=text("function");
  dawn_adt *table=dawn_adt_new(0,2,3);
  table->fields[0].p=dawn_array_push_own(dawn_array_new(),site);
  table->fields[1].p=dawn_array_push_own(dawn_array_new(),definition);
  int64_t scope=dawn_prov_open(); dawn_prov_scope *live=dawn_prov_scope_at(scope);
  /* The scope borrows program metadata. Keep the producer's owner until
   * close; completed creates the escaping snapshot's independent owner. */
  live->table=table;
  int64_t token=dawn_prov_before_ctx(dawn_prov_context(),0,"");
  dawn_prov_arrive_ctx(dawn_prov_context(),0,"");dawn_prov_finish(token,1);
  dawn_adt *snapshot=dawn_prov_completed(scope);dawn_prov_close(scope,1);dawn_drop(table);
  dawn_str *result=dawn_snapshot_1metadata__inspect(dawn_dup(snapshot));
  printf("%.*s\n",(int)result->len,result->p);dawn_drop(result);
  result=dawn_snapshot_1metadata__text(snapshot);printf("%.*s\n",(int)result->len,result->p);
  dawn_drop(result);dawn_drop(snapshot);
}
int main(int argc,char **argv) { return dawn_rt_main(argc,argv,probe); }
