/* This source includes an emitted program, but reads opaque provenance only
 * through its public compiled module. Correctness uses independent inputs. */
#include "preview_api.h"
#include "preview_consumer.h"
#include "preview_inputs.h"
#include "preview_controls.h"
static int preview_argc; static char **preview_argv;
static void preview_write(const char *directory,const char *name,const char *suffix,const void *data,size_t len) {
  char path[4096]; assert(snprintf(path,sizeof(path),"%s/%s.%s",directory,name,suffix)<(int)sizeof(path));
  FILE *f=fopen(path,"wb"); assert(f); assert(fwrite(data,1,len,f)==len && fclose(f)==0);
}
static void preview_compare_rows(dawn_adt *snapshot) {
  dawn_adt *view=dawn_std_2provenance__records(dawn_dup(snapshot));
  int64_t count=dawn_std_2provenance__record_1count(view),scope=dawn_std_2provenance__record_1scope(view);
  preview_require(!dawn_std_2provenance__record_1exists(view,-1) && !dawn_std_2provenance__record_1exists(view,count),"bulk bounds mismatch");
  for(int64_t row=0;row<count;row++) {
    dawn_adt *option=dawn_std_2provenance__record_1at(dawn_dup(snapshot),row),*record=preview_some(option),*key=record->fields[0].p;
    dawn_adt *state=dawn_std_2provenance__record_1state(view,row),*boundary=dawn_std_2provenance__record_1boundary(view,row);
    preview_require(dawn_std_2provenance__record_1exists(view,row) && scope==key->fields[0].i &&
      dawn_std_2provenance__record_1epoch(view,row)==key->fields[1].i && dawn_std_2provenance__record_1instance(view,row)==key->fields[2].i &&
      preview_slot_index(dawn_std_2provenance__record_1parent(view,row))==preview_index(record->fields[1].p) &&
      preview_slot_index(dawn_std_2provenance__record_1site(view,row))==preview_index(record->fields[3].p) &&
      preview_slot_index(dawn_std_2provenance__record_1definition(view,row))==preview_index(record->fields[4].p) &&
      state->tag==((dawn_adt*)record->fields[2].p)->tag && boundary->tag==((dawn_adt*)record->fields[5].p)->tag,"bulk and row facts differ");
    dawn_drop(state);dawn_drop(boundary);dawn_drop(option);
  }
  dawn_drop(view);
}
static void preview_check_entry(void) {
  assert(preview_argc==5 || preview_argc==6); char **args=preview_argv;
  preview_source source=preview_inputs_load(args[1]); FILE *cases=fopen(args[4],"r"); assert(cases);
  if(preview_argc==6) { assert(fclose(cases)==0); preview_control(args[5],source,args[2]); return; }
  char name[256]; long long expected;
  while(fscanf(cases,"%255s %lld",name,&expected)==2) {
    dawn_clo *work=dawn_main__select_1case(dawn_str_copy(name,(int64_t)strlen(name)));
    dawn_adt *result=dawn_main__record_1case(dawn_dup(work),true,true),*program=result->fields[0].p;
    dawn_adt *snapshot=preview_some(result->fields[1].p);
    dawn_adt *info=dawn_std_2provenance__snapshot_1info(dawn_dup(snapshot));
    preview_require(info->fields[2].i==expected,"independent N mismatch"); dawn_drop(info);
    preview_compare_rows(snapshot);
    preview_cache cache=preview_cache_new();
    preview_mapping map=preview_consume(snapshot,&source,args[2],&cache);
    preview_mapping again=preview_consume(snapshot,&source,args[2],&cache);
    preview_require(map.count==again.count && map.rows==again.rows && memcmp(map.owners,again.owners,map.rows*sizeof(int64_t))==0,"repeated getter mismatch");
    char path[4096]; assert(snprintf(path,sizeof(path),"%s/%s.map",args[3],name)<(int)sizeof(path));
    FILE *f=fopen(path,"w"); assert(f);
    for(size_t i=0;i<map.count;i++) { preview_node node=map.nodes[i];
      fprintf(f,"%lld %lld %lld %lld %d %lld %lld\n",(long long)node.key->fields[0].i,(long long)node.key->fields[1].i,(long long)node.key->fields[2].i,(long long)node.parent,node.state->tag,(long long)(node.site?node.site->fields[0].i:0),(long long)(node.definition?node.definition->fields[0].i:0)); }
    fprintf(f,"owners\n"); for(size_t i=0;i<map.rows;i++) fprintf(f,"%lld\n",(long long)map.owners[i]); assert(fclose(f)==0);
    dawn_str *text=dawn_main__preview_1program(program);
    preview_write(args[3],name,"mlir",text->p,(size_t)text->len); dawn_drop(text);
    dawn_bytes *bytes=dawn_main__encode_1program(program);
    preview_write(args[3],name,"tilebc",bytes->p,(size_t)bytes->len); dawn_drop(bytes);
    text=dawn_main__snapshot_1text(snapshot);
    preview_write(args[3],name,"snapshot",text->p,(size_t)text->len); dawn_drop(text);
    printf("%s %lld %zu %lld\n",name,expected,map.count,(long long)dawn_main__operation_1count(program));
    preview_mapping_drop(&again); preview_mapping_drop(&map); preview_cache_drop(&cache);
    dawn_drop(result); dawn_drop(work);
  }
  assert(fclose(cases)==0);
}
int main(int argc,char **argv) { preview_argc=argc; preview_argv=argv; return dawn_rt_main(argc,argv,preview_check_entry); }
