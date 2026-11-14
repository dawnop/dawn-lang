/* Keep frozen typed export checks independent of its live producer. */
#define main dawn_original_main
#include "snapshot_flags-native.c"
#undef main
#include <assert.h>
static void probe(void) {
  dawn_adt *table=dawn_prov_static_table(); const dawn_prov_site *site=NULL;
  for(size_t i=0;i<dawn_prov_sites_n;i++) if(strstr(dawn_prov_sorted_sites[i].metadata,"\tperform\t")) { site=&dawn_prov_sorted_sites[i]; break; }
  assert(site);int64_t s=dawn_prov_open(),token=dawn_prov_before(site->id,site->metadata);dawn_prov_arrive(dawn_prov_definitions[0]);
  dawn_prov_scope *scope=dawn_prov_scope_at(s);dawn_prov_record *record=dawn_prov_record_at(scope,2);
  scope->completeness=1;record->status=3;record->boundary=1;
  dawn_adt *origin=dawn_prov_origin(s);dawn_prov_note(s,origin);record->status=4;
  dawn_adt *old=dawn_prov_completed(s);dawn_str *old_text=dawn_prov_render_snapshot(old);
  record->status=0;record->boundary=0;scope->completeness=0;dawn_prov_finish(token,1);
  dawn_adt *fresh=dawn_prov_completed(s);dawn_prov_close(s,1);
  dawn_str *again=dawn_snapshot_1flags__text(old);assert(dawn_str_eq(old_text,again));
  dawn_str *a=dawn_snapshot_1flags__describe(dawn_dup(old)),*b=dawn_snapshot_1flags__describe(dawn_dup(fresh));
  printf("%.*s\n%.*s\n",(int)a->len,a->p,(int)b->len,b->p);
  printf("%.*s\n@@fresh\n",(int)old_text->len,old_text->p);
  dawn_str *new_text=dawn_snapshot_1flags__text(fresh);printf("%.*s\n",(int)new_text->len,new_text->p);
  dawn_drop(a);dawn_drop(b);dawn_drop(old_text);dawn_drop(again);dawn_drop(new_text);dawn_drop(old);dawn_drop(fresh);dawn_drop(origin);
  (void)table;
}
int main(int argc,char **argv) { return dawn_rt_main(argc,argv,probe); }
