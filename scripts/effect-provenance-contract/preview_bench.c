/* Every preview builds a fresh lazy getter cache inside its stopwatch. The
 * immutable parser index is the only cross-request consumer cache. */
#include "preview_api.h"
#include <time.h>
#include "preview_consumer.h"
#include "preview_inputs.h"
static volatile uint64_t preview_sink;
static preview_mapping *volatile preview_delivered;
static dawn_adt *preview_latest;
static preview_source preview_bench_source;
static const char *preview_revision;
static uint64_t preview_once(dawn_clo *work,bool observed,const char *phase,const char *output) {
  bool read=strcmp(phase,"record")!=0;
  dawn_adt *result=dawn_main__record_1case(dawn_dup(work),observed,read);
  dawn_adt *program=dawn_dup(result->fields[0].p); uint64_t checksum=0;
  if(observed && read) {
    dawn_adt *snapshot=preview_some(result->fields[1].p);
    if(strcmp(phase,"dump")==0) {
      dawn_str *text=dawn_main__snapshot_1text(snapshot); checksum^=(uint64_t)text->len; dawn_drop(text);
    } else {
      preview_cache cache=preview_cache_new();
      preview_mapping map=preview_consume(snapshot,&preview_bench_source,preview_revision,&cache);
      preview_delivered=&map;
      checksum^=preview_delivered->count+(uint64_t)preview_delivered->owners[preview_delivered->rows-1];
      preview_delivered=NULL;
      if(strcmp(phase,"repeat")==0) {
        preview_mapping again=preview_consume(snapshot,&preview_bench_source,preview_revision,&cache);
        checksum^=again.count+(uint64_t)again.owners[again.rows-1]; preview_mapping_drop(&again);
      }
      preview_mapping_drop(&map); preview_cache_drop(&cache);
    }
  }
  if(strcmp(phase,"interactive")==0 || strcmp(phase,"repeat")==0) {
    dawn_str *text=dawn_main__preview_1program(program); checksum^=(uint64_t)text->len; dawn_drop(text);
  }
  if(strcmp(phase,"generate")==0) {
    dawn_bytes *bytes=dawn_main__encode_1program(program); checksum^=(uint64_t)bytes->len;
    if(strcmp(output,"-")!=0) { FILE *f=fopen(output,"wb"); assert(f); assert(fwrite(bytes->p,1,(size_t)bytes->len,f)==(size_t)bytes->len && fclose(f)==0); }
    dawn_drop(bytes);
  }
  dawn_drop(result); dawn_drop(preview_latest); preview_latest=program; preview_sink^=checksum; return checksum;
}
static int preview_bench_argc; static char **preview_bench_argv;
static int64_t preview_nanos(void) { struct timespec t; assert(clock_gettime(CLOCK_MONOTONIC,&t)==0); return t.tv_sec*INT64_C(1000000000)+t.tv_nsec; }
static void preview_bench_entry(void) {
  assert(preview_bench_argc==10); char **a=preview_bench_argv;
  bool observed=strcmp(a[1],"observed")==0; const char *phase=a[3];
  int warm=atoi(a[4]),batches=atoi(a[5]),iterations=atoi(a[6]);
  preview_bench_source=preview_inputs_load(a[8]); preview_revision=a[9];
  dawn_clo *work=dawn_main__select_1case(dawn_str_copy(a[2],(int64_t)strlen(a[2])));
  for(int i=0;i<warm;i++) preview_once(work,observed,phase,"-");
  for(int batch=0;batch<batches;batch++) {
    int64_t start=preview_nanos();
    for(int i=0;i<iterations;i++) preview_once(work,observed,phase,a[7]);
    int64_t duration=preview_nanos()-start;
    printf("%d %lld %lld %llu\n",batch,(long long)(duration/iterations),(long long)dawn_main__operation_1count(preview_latest),(unsigned long long)preview_sink);
  }
  dawn_drop(preview_latest); preview_latest=NULL; dawn_drop(work);
}
int main(int argc,char **argv) { preview_bench_argc=argc; preview_bench_argv=argv; return dawn_rt_main(argc,argv,preview_bench_entry); }
