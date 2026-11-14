/* The CLI returns ordinary public output values, never private trace bytes. */
#define main full_golden_generated_main
#include "full_golden.c"
#undef main
#include <assert.h>
static int full_golden_argc;static char **full_golden_argv;
static void full_golden_file(const char *dir,const char *name,const char *suffix,const void *data,size_t size) {
  char path[4096];assert(snprintf(path,sizeof(path),"%s/%s.%s",dir,name,suffix)<(int)sizeof(path));
  FILE *f=fopen(path,"rb");assert(f);assert(fseek(f,0,SEEK_END)==0 && ftell(f)==(long)size && fseek(f,0,SEEK_SET)==0);
  unsigned char *bytes=malloc(size?size:1);assert(bytes);assert(fread(bytes,1,size,f)==size && fclose(f)==0);
  assert(memcmp(bytes,data,size)==0);dawn_free(bytes);
}
static void full_golden_entry(void) {
  assert(full_golden_argc==3);char **a=full_golden_argv;FILE *names=fopen(a[2],"r");assert(names);char name[256];
  while(fscanf(names,"%255s",name)==1) {
    dawn_adt *value=dawn_main__provenance_1check_1case(dawn_str_copy(name,(int64_t)strlen(name)));
    dawn_str *text=value->fields[0].p;dawn_bytes *bytes=value->fields[1].p;
    full_golden_file(a[1],name,"mlir",text->p,(size_t)text->len);
    full_golden_file(a[1],name,"tilebc",bytes->p,(size_t)bytes->len);
    dawn_drop(value);printf("%s public CLI mapping and both goldens\n",name);
  }
  assert(fclose(names)==0);
}
int main(int argc,char **argv) { full_golden_argc=argc;full_golden_argv=argv;return dawn_rt_main(argc,argv,full_golden_entry); }
