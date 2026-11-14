/* Public named record layouts are the generated Dawn ABI. Opaque snapshots,
 * tables and origins are passed only to public std/provenance functions. The
 * result owns a real call projection plus an index for every recorded row. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { const char *key; int64_t lo, hi; } preview_declaration;
typedef struct { int64_t lo, hi; } preview_span;
typedef struct {
  const char *revision;
  const preview_declaration *declarations; size_t declarations_n;
  const preview_span *spans; size_t spans_n;
} preview_source;
typedef struct { int64_t slot; dawn_adt *value; } preview_slot;
typedef struct { preview_slot *slots; size_t capacity, count; } preview_entries;
typedef struct { preview_entries sites, definitions; } preview_cache;
typedef struct { dawn_adt *key, *state, *site, *definition; int64_t parent; } preview_node;
typedef struct { preview_node *nodes; int64_t *owners; size_t count, rows; } preview_mapping;
static void preview_require(int ok, const char *why) {
  if (!ok) { fprintf(stderr,"preview: %s\n",why); exit(86); }
}
static int preview_string(dawn_str *value, const char *text) {
  return value->len==(int64_t)strlen(text) && memcmp(value->p,text,(size_t)value->len)==0;
}
static int preview_user_definition(dawn_adt *value) {
  return value && preview_string(value->fields[1].p,"main") && ((dawn_str*)value->fields[2].p)->len>0;
}
static dawn_adt *preview_some(dawn_adt *option) {
  preview_require(option->tag==0,"missing public value"); return option->fields[0].p;
}
static int64_t preview_slot_index(int64_t slot) {
  return dawn_std_2provenance__index_1present(slot) ? dawn_std_2provenance__index_1value(slot) : -1;
}
static int64_t preview_index(dawn_adt *option) {
  return option->tag==0 ? dawn_peek_int(option->fields[0].p) : -1;
}
static void preview_match(const preview_source *source, dawn_str *key, int64_t lo, int64_t hi, int syntax) {
  size_t a=0,b=source->declarations_n;
  while(a<b) { size_t m=a+(b-a)/2; int order=strcmp(source->declarations[m].key,key->p);
    if(order<0) a=m+1; else b=m; }
  preview_require(a<source->declarations_n && preview_string(key,source->declarations[a].key),"source declaration mismatch");
  preview_declaration d=source->declarations[a];
  if(!(lo>=0 && hi>=lo && d.lo+hi<=d.hi)) {
    fprintf(stderr,"preview source %.*s: relative %lld..%lld declaration %lld..%lld\n",(int)key->len,key->p,(long long)lo,(long long)hi,(long long)d.lo,(long long)d.hi);
    preview_require(0,"source range mismatch");
  }
  if(syntax) {
    lo+=d.lo; hi+=d.lo; a=0; b=source->spans_n;
    while(a<b) { size_t m=a+(b-a)/2; preview_span s=source->spans[m];
      if(s.lo<lo || (s.lo==lo && s.hi<hi)) a=m+1; else b=m; }
    preview_require(a<source->spans_n && source->spans[a].lo==lo && source->spans[a].hi==hi,"source syntax mismatch");
  }
}
static preview_cache preview_cache_new(void) { return (preview_cache){0}; }
static preview_slot *preview_cache_slot(preview_entries *entries,int64_t index) {
  if(entries->count*2>=entries->capacity) {
    size_t capacity=entries->capacity ? entries->capacity*2 : 16;
    preview_slot *slots=calloc(capacity,sizeof(*slots)); assert(slots);
    for(size_t i=0;i<entries->capacity;i++) if(entries->slots[i].value) {
      preview_slot old=entries->slots[i];
      size_t at=((uint64_t)old.slot*UINT64_C(11400714819323198485))&(capacity-1);
      while(slots[at].value) at=(at+1)&(capacity-1); slots[at]=old;
    }
    dawn_free(entries->slots); entries->slots=slots; entries->capacity=capacity;
  }
  size_t at=((uint64_t)index*UINT64_C(11400714819323198485))&(entries->capacity-1);
  while(entries->slots[at].value && entries->slots[at].slot!=index) at=(at+1)&(entries->capacity-1);
  if(!entries->slots[at].value) entries->count++;
  entries->slots[at].slot=index; return entries->slots+at;
}
static void preview_cache_drop(preview_cache *cache) {
  for(size_t i=0;i<cache->sites.capacity;i++) dawn_drop(cache->sites.slots[i].value);
  for(size_t i=0;i<cache->definitions.capacity;i++) dawn_drop(cache->definitions.slots[i].value);
  dawn_free(cache->sites.slots); dawn_free(cache->definitions.slots);
}
static preview_mapping preview_consume(dawn_adt *snapshot,const preview_source *source,const char *artifact_revision,preview_cache *cache) {
  preview_require(strcmp(source->revision,artifact_revision)==0,"source revision mismatch");
  dawn_adt *info=dawn_std_2provenance__snapshot_1info(dawn_dup(snapshot));
  preview_require(((dawn_adt*)info->fields[4].p)->tag==0,"truncated provenance");
  int64_t scope=info->fields[0].i,n=info->fields[2].i,notes=info->fields[3].i;
  dawn_adt *table=dawn_std_2provenance__static_1table(dawn_dup(snapshot));
  preview_mapping map={NULL,malloc((size_t)n*sizeof(int64_t)),0,(size_t)n};
  size_t node_capacity=0; assert(map.owners);
  dawn_adt *view=dawn_std_2provenance__records(dawn_dup(snapshot));
  preview_require(dawn_std_2provenance__record_1scope(view)==scope && dawn_std_2provenance__record_1count(view)==n,"scope mismatch");
  for(int64_t row=0;row<n;row++) {
    dawn_adt *boundary=dawn_std_2provenance__record_1boundary(view,row);
    preview_require(boundary->tag==0,"unknown boundary"); dawn_drop(boundary);
    dawn_adt *state=dawn_std_2provenance__record_1state(view,row);
    int64_t parent=preview_slot_index(dawn_std_2provenance__record_1parent(view,row));
    preview_require(parent>=-1 && parent<row,"invalid parent index");
    int64_t owner=parent<0 ? -1 : map.owners[parent];
    int64_t si=preview_slot_index(dawn_std_2provenance__record_1site(view,row));
    int64_t di=preview_slot_index(dawn_std_2provenance__record_1definition(view,row));
    dawn_adt *site=NULL,*definition=NULL;
    if(si>=0) {
      preview_slot *entry=preview_cache_slot(&cache->sites,si);
      if(!entry->value) {
        dawn_adt *o=dawn_std_2provenance__site_1at(dawn_dup(table),si);
        site=entry->value=dawn_dup(preview_some(o)); dawn_drop(o);
        if(preview_string(site->fields[1].p,"main")) {
          preview_require(preview_string(site->fields[2].p,"main"),"source file mismatch");
          preview_match(source,site->fields[3].p,site->fields[4].i,site->fields[5].i,1);
          preview_require((site->fields[6].i==-1 && site->fields[7].i==-1) || (site->fields[6].i>=site->fields[4].i && site->fields[7].i>=site->fields[6].i && site->fields[7].i<=site->fields[5].i),"source name range mismatch");
        }
      } else site=entry->value;
    }
    if(di>=0) {
      preview_slot *entry=preview_cache_slot(&cache->definitions,di);
      if(!entry->value) {
        dawn_adt *o=dawn_std_2provenance__definition_1at(dawn_dup(table),di);
        definition=entry->value=dawn_dup(preview_some(o)); dawn_drop(o);
        if(preview_user_definition(definition))
          preview_match(source,definition->fields[2].p,definition->fields[3].i,definition->fields[4].i,0);
        else if(preview_string(definition->fields[1].p,"main"))
          preview_require(definition->fields[3].i==-1 && definition->fields[4].i==-1 &&
            (preview_string(definition->fields[5].p,"primitive-slot") || preview_string(definition->fields[5].p,"derived-relation") || preview_string(definition->fields[5].p,"constructor-value")),"unknown synthetic definition");
      } else definition=entry->value;
    }
    preview_require(row==0 || site || definition,"unknown call identity");
    if((site && preview_string(site->fields[1].p,"main")) || preview_user_definition(definition)) {
      if(map.count==node_capacity) { node_capacity=node_capacity ? node_capacity*2 : 16;
        map.nodes=realloc(map.nodes,node_capacity*sizeof(preview_node)); assert(map.nodes); }
      dawn_adt *key=dawn_adt_new(0,3,0);
      key->fields[0].i=scope; key->fields[1].i=dawn_std_2provenance__record_1epoch(view,row);
      key->fields[2].i=dawn_std_2provenance__record_1instance(view,row);
      map.nodes[map.count]=(preview_node){key,dawn_dup(state),dawn_dup(site),dawn_dup(definition),owner};
      owner=(int64_t)map.count++;
    }
    map.owners[row]=owner; dawn_drop(state);
  }
  for(int64_t i=0;i<notes;i++) {
    dawn_adt *o=dawn_std_2provenance__note_1at(dawn_dup(snapshot),i),*origin=preview_some(o);
    dawn_adt *complete=dawn_std_2provenance__origin_1completeness(dawn_dup(origin));
    dawn_adt *boundary=dawn_std_2provenance__origin_1boundary(dawn_dup(origin));
    preview_require(complete->tag==0 && boundary->tag==0,"truncated or unknown origin");
    dawn_adt *key=dawn_adt_new(0,3,0);
    key->fields[0].i=dawn_std_2provenance__scope(dawn_dup(origin));
    key->fields[1].i=dawn_std_2provenance__epoch(dawn_dup(origin));
    key->fields[2].i=dawn_std_2provenance__instance(dawn_dup(origin));
    dawn_adt *found=dawn_std_2provenance__find_1instance(dawn_dup(snapshot),key);
    preview_require(found->tag==0,"uncommitted origin");
    dawn_drop(found); dawn_drop(key); dawn_drop(boundary); dawn_drop(complete); dawn_drop(o);
  }
  dawn_drop(view); dawn_drop(info); dawn_drop(table); return map;
}
static void preview_mapping_drop(preview_mapping *map) {
  for(size_t i=0;i<map->count;i++) { preview_node n=map->nodes[i]; dawn_drop(n.key); dawn_drop(n.state); dawn_drop(n.site); dawn_drop(n.definition); }
  dawn_free(map->nodes); dawn_free(map->owners);
}
