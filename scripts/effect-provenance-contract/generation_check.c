/* The same generation request, with no timing calls on this execution path. */
#define GENERATION_CHECK 1
#include "generation_bench.c"
static int generation_check_argc; static char **generation_check_argv;
static void generation_check_entry(void) {
  assert(generation_check_argc==8); char **a=generation_check_argv;
  preview_bench_source=preview_inputs_load(a[3]); preview_revision=a[4];
  if(a[2][0]=='@') {
    FILE *cases=fopen(a[2]+1,"r");assert(cases);char name[256],target[32],directory[4096];size_t count=0;
    while(fscanf(cases,"%255s %31s",name,target)==2) {
      assert(snprintf(directory,sizeof(directory),"%s/%s",a[5],name)<(int)sizeof(directory));
      assert(mkdir(directory,0700)==0);
      dawn_clo *work=dawn_main__select_1case(dawn_str_copy(name,(int64_t)strlen(name)));
      generation_once(work,strcmp(a[1],"observed")==0,directory,0,a[6],target);
      dawn_drop(work);printf("%s generated\n",name);count++;
    }
    assert(fclose(cases)==0 && count==248);
  } else {
    dawn_clo *work=dawn_main__select_1case(dawn_str_copy(a[2],(int64_t)strlen(a[2])));
    generation_once(work,strcmp(a[1],"observed")==0,a[5],0,a[6],a[7]);
    dawn_drop(work);puts("generated");
  }
}
int main(int argc,char **argv) { generation_check_argc=argc;generation_check_argv=argv;return dawn_rt_main(argc,argv,generation_check_entry); }
