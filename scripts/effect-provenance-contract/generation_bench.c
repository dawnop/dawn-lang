/* This includes the same public product consumer as the interactive path.
 * No private provenance structure enters the generation stopwatch. */
#define _POSIX_C_SOURCE 200809L
#define main interactive_benchmark_main
#include "preview_bench.c"
#undef main
#include <spawn.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/wait.h>
extern char **environ;
static int generation_argc; static char **generation_argv;
static void generation_once(dawn_clo *work,bool observed,const char *output,int batch,const char *assembler,const char *gpu) {
    char bytes[4096],cubin[4096],log[4096];
    assert(snprintf(bytes,sizeof(bytes),"%s/request-%d.tilebc",output,batch)<(int)sizeof(bytes));
    assert(snprintf(cubin,sizeof(cubin),"%s/request-%d.cubin",output,batch)<(int)sizeof(cubin));
    assert(snprintf(log,sizeof(log),"%s/request-%d.assembler.log",output,batch)<(int)sizeof(log));
    preview_once(work,observed,"generate",bytes);
    posix_spawn_file_actions_t actions; assert(posix_spawn_file_actions_init(&actions)==0);
    assert(posix_spawn_file_actions_addopen(&actions,1,log,O_WRONLY|O_CREAT|O_TRUNC,0600)==0);
    assert(posix_spawn_file_actions_adddup2(&actions,1,2)==0);
    char *argv[]={(char *)assembler,"--gpu-name",(char *)gpu,"-o",cubin,bytes,NULL}; pid_t child;
    assert(posix_spawn(&child,assembler,&actions,NULL,argv,environ)==0);
    assert(posix_spawn_file_actions_destroy(&actions)==0);
    int status; assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);
    FILE *diagnostics=fopen(log,"r");assert(diagnostics);char line[4096];
    while(fgets(line,sizeof(line),diagnostics)) assert(strncmp(line,"error:",6)!=0);
    assert(fclose(diagnostics)==0);
    FILE *artifact=fopen(cubin,"rb");assert(artifact);unsigned char magic[4];
    assert(fread(magic,1,4,artifact)==4 && memcmp(magic,"\177ELF",4)==0 && fclose(artifact)==0);
    dawn_drop(preview_latest); preview_latest=NULL;
}
static void generation_entry(void) {
  assert(generation_argc==9);char **a=generation_argv;
  bool observed=strcmp(a[1],"observed")==0;int warm=atoi(a[3]),batches=atoi(a[4]);
  preview_bench_source=preview_inputs_load(a[6]);preview_revision=a[7];
  struct generation_case { char name[256],target[32],directory[4096];dawn_clo *work; } cases[248];
  size_t count=0;FILE *input=fopen(a[2],"r");assert(input);
  while(count<248 && fscanf(input,"%255s %31s",cases[count].name,cases[count].target)==2) {
    struct generation_case *c=&cases[count++];
    assert(snprintf(c->directory,sizeof(c->directory),"%s/%s",a[5],c->name)<(int)sizeof(c->directory));
    assert(mkdir(c->directory,0700)==0);
    c->work=dawn_main__select_1case(dawn_str_copy(c->name,(int64_t)strlen(c->name)));
    char warmfile[4096];assert(snprintf(warmfile,sizeof(warmfile),"%s/warmup.tilebc",c->directory)<(int)sizeof(warmfile));
    for(int i=0;i<warm;i++) preview_once(c->work,observed,"generate",warmfile);
  }
  int trailing; do { trailing=fgetc(input); } while(trailing!=EOF && (trailing==' ' || trailing=='\n' || trailing=='\r' || trailing=='\t'));
  assert(trailing==EOF && fclose(input)==0 && count==248 && warm>=0 && batches>0);
  for(size_t i=0;i<count;i++) for(size_t j=0;j<i;j++) assert(strcmp(cases[i].name,cases[j].name)!=0);
  dawn_drop(preview_latest);preview_latest=NULL;
  int64_t *elapsed=calloc(count*(size_t)batches,sizeof(*elapsed));assert(elapsed);
  int64_t total_start=preview_nanos();
  for(size_t c=0;c<count;c++) for(int batch=0;batch<batches;batch++) {
    int64_t start=preview_nanos();
    generation_once(cases[c].work,observed,cases[c].directory,batch,a[8],cases[c].target);
    elapsed[c*(size_t)batches+(size_t)batch]=preview_nanos()-start;
  }
  int64_t total=preview_nanos()-total_start;
  for(size_t c=0;c<count;c++) for(int batch=0;batch<batches;batch++)
    printf("%s %d %lld\n",cases[c].name,batch,(long long)elapsed[c*(size_t)batches+(size_t)batch]);
  printf("TOTAL %lld\n",(long long)total);
  dawn_free(elapsed);for(size_t c=0;c<count;c++) dawn_drop(cases[c].work);
}
#ifndef GENERATION_CHECK
int main(int argc,char **argv) { generation_argc=argc;generation_argv=argv;return dawn_rt_main(argc,argv,generation_entry); }
#endif
