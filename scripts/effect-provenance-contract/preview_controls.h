/* Adverse live producers are instrumentation. They freeze and close before
 * invoking the same public API consumer used by actual preview requests. */
dawn_adt *preview_control_produce(const char *mode);
static void preview_control(const char *mode,preview_source source,const char *revision) {
  dawn_adt *snapshot,*result=NULL;
  if(strcmp(mode,"truncated")==0 || strcmp(mode,"unknown")==0 || strcmp(mode,"uncommitted")==0)
    snapshot=preview_control_produce(mode);
  else {
    dawn_clo *work=dawn_main__select_1case(dawn_str_copy("vadd",4));
    result=dawn_main__record_1case(work,true,true); snapshot=preview_some(result->fields[1].p);
    if(strcmp(mode,"revision")==0) source.revision="wrong revision";
    if(strcmp(mode,"declaration")==0) source.declarations_n=0;
    if(strcmp(mode,"span")==0) source.spans_n=0;
  }
  printf("42 %s\n",mode); fflush(stdout);
  preview_cache cache=preview_cache_new();
  preview_mapping map=preview_consume(snapshot,&source,revision,&cache);
  preview_mapping_drop(&map); preview_cache_drop(&cache);
  if(result) dawn_drop(result); else dawn_drop(snapshot);
  preview_require(0,"negative control accepted");
}
