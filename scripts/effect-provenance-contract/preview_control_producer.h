/* Test producer only. This code runs before consumption, never in a timed
 * preview request; the public typed reader cannot inspect its live fields. */
dawn_adt *preview_control_produce(const char *mode) {
  int64_t id=dawn_prov_open(); dawn_prov_scope *scope=dawn_prov_scope_at(id);
  if(strcmp(mode,"truncated")==0) scope->completeness=1;
  if(strcmp(mode,"unknown")==0) dawn_prov_record_at(scope,1)->boundary=1;
  if(strcmp(mode,"uncommitted")==0) {
    dawn_str *mark=dawn_prov_checkpoint(id); const dawn_prov_site *site=NULL;
    for(size_t i=0;i<dawn_prov_sites_n;i++) if(strstr(dawn_prov_sorted_sites[i].metadata,"\tperform\t")) { site=&dawn_prov_sorted_sites[i]; break; }
    assert(site); int64_t token=dawn_prov_before(site->id,site->metadata);
    dawn_prov_arrive(dawn_prov_definitions[0]); dawn_adt *origin=dawn_prov_origin(id);
    dawn_prov_finish(token,1); dawn_prov_rewind(id,mark); dawn_prov_note(id,origin);
    dawn_drop(origin); dawn_drop(mark);
  }
  dawn_adt *snapshot=dawn_prov_completed(id); dawn_prov_close(id,1); return snapshot;
}
