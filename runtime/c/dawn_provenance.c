/* Integer identities and immutable exported strings keep checkpoints and
 * Origins independent of arena relocation and C stack lifetime. A registry
 * contains active scopes only, so checking execution ownership does not pin
 * completed sessions. This file is embedded only for observation programs. */
#ifndef DAWN_PROV_EMBEDDED
#include "dawn_provenance.h"
#endif
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

/* Entry addresses must remain distinct. Reading canonical addresses through
 * this externally visible index makes their identity significant to the C
 * optimizer. Toolchain configurations enabling unsafe ICF are unsupported. */
static void dawn_prov_fail(const char *message);
static pthread_once_t dawn_prov_index_once = PTHREAD_ONCE_INIT;
static dawn_prov_target *dawn_prov_index;
static DAWN_PROV_CODE int dawn_prov_target_compare(const void *a, const void *b) {
  uintptr_t left = (uintptr_t)((const dawn_prov_target *)a)->canonical;
  uintptr_t right = (uintptr_t)((const dawn_prov_target *)b)->canonical;
  return (left > right) - (left < right);
}
static DAWN_PROV_CODE void dawn_prov_build_index(void) {
  if (!dawn_prov_entries_n) return;
  dawn_prov_index = malloc(sizeof(*dawn_prov_index) * dawn_prov_entries_n);
  if (!dawn_prov_index) abort();
  memcpy(dawn_prov_index, dawn_prov_entries, sizeof(*dawn_prov_index) * dawn_prov_entries_n);
  qsort(dawn_prov_index, dawn_prov_entries_n, sizeof(*dawn_prov_index), dawn_prov_target_compare);
  for (size_t i = 1; i < dawn_prov_entries_n; i++) {
    if (dawn_prov_index[i - 1].canonical == dawn_prov_index[i].canonical) {
      dawn_prov_fail("provenance: duplicate canonical entry");
    }
  }
}
DAWN_PROV_CODE void *dawn_prov_select(void *canonical) {
  pthread_once(&dawn_prov_index_once, dawn_prov_build_index);
  size_t lo = 0, hi = dawn_prov_entries_n;
  uintptr_t key = (uintptr_t)canonical;
  while (lo < hi) {
    size_t mid = lo + (hi - lo) / 2;
    uintptr_t at = (uintptr_t)dawn_prov_index[mid].canonical;
    if (at < key) lo = mid + 1;
    else if (at > key) hi = mid;
    else return dawn_prov_index[mid].observed;
  }
  dawn_prov_fail("provenance: missing internal observed entry");
  return NULL;
}

typedef struct {
  int64_t id, epoch, parent, site, definition;
  int status, boundary;
} dawn_prov_record;

typedef struct dawn_prov_invocation dawn_prov_invocation;
typedef struct dawn_prov_activation dawn_prov_activation;
typedef struct {
  int64_t ordinal, frame, boundary, note_boundary, logical_boundary;
  dawn_prov_invocation *creator;
  int valid;
} dawn_prov_mark;

typedef struct dawn_prov_scope {
  int64_t id, epoch, next_instance, current, recorded_current, capacity, unresumed;
  size_t notes_written;
  pthread_t owner;
  size_t leases;
  int closed, completeness;
  dawn_adt *table;
  dawn_prov_record **record_chunks;
  size_t count, nchunks, chunk_capacity;
  void *pool_blocks, *pool_free;
  size_t *view, nview, view_capacity;
  dawn_prov_activation **activations;
  size_t nactivations, activation_capacity;
  dawn_prov_mark *marks;
  size_t nmarks, mark_capacity;
  size_t *mark_stack, nmark_stack, mark_stack_capacity;
  dawn_adt **notes;
  size_t nnotes, note_capacity;
  struct dawn_prov_scope *outer, *registered;
} dawn_prov_scope;

typedef struct {
  dawn_prov_scope *scope;
  int64_t frame, parent, recorded_parent, tip, epoch, logical_tip;
} dawn_prov_entry;

struct dawn_prov_invocation {
  dawn_prov_scope *pool_owner;
  struct dawn_prov_invocation *pool_next;
  dawn_prov_entry inline_entry;
  size_t entry_capacity;
  int64_t token;
  int arrived, finished, suspended, reclaiming;
  size_t refs;
  const char *metadata;
  int64_t site, callback_site;
  const char *callback_metadata;
  dawn_prov_entry *entries;
  size_t count;
  struct dawn_prov_invocation *parent;
};

/* The scope owns every pool block. A retained continuation keeps its
 * invocation lease, so only a zero-reference slot can return to the free list. */
typedef struct dawn_prov_pool_block {
  struct dawn_prov_pool_block *next;
  dawn_prov_invocation slots[128];
} dawn_prov_pool_block;
static void dawn_prov_scope_free(dawn_prov_scope *s);
static DAWN_PROV_CODE dawn_prov_invocation *dawn_prov_pool_take(dawn_prov_scope *s) {
  if (!s->pool_free) {
    dawn_prov_pool_block *b = calloc(1, sizeof(*b));
    if (!b) abort();
    b->next = s->pool_blocks; s->pool_blocks = b;
    for (size_t i = 0; i < 128; i++) {
      b->slots[i].pool_next = s->pool_free; s->pool_free = &b->slots[i];
    }
  }
  dawn_prov_invocation *v = s->pool_free;
  s->pool_free = v->pool_next;
  dawn_prov_entry *entries = v->entries; size_t capacity = v->entry_capacity;
  memset(v, 0, sizeof(*v));
  v->entries = entries; v->entry_capacity = capacity; v->pool_owner = s; s->leases++;
  return v;
}
static DAWN_PROV_CODE void dawn_prov_pool_put(dawn_prov_invocation *v) {
  dawn_prov_scope *s = v->pool_owner;
  for (size_t i=0;i<v->count;i++) {
    dawn_prov_scope *outer=v->entries[i].scope;
    v->entries[i].scope=NULL;
    if (outer!=s && !--outer->leases && outer->closed) dawn_prov_scope_free(outer);
  }
  v->pool_next = s->pool_free; s->pool_free = v;
  if (!--s->leases && s->closed) dawn_prov_scope_free(s);
}

static _Atomic int64_t dawn_prov_next_scope = 1;
static _Atomic int64_t dawn_prov_next_token = 1;
static pthread_mutex_t dawn_prov_registry_lock = PTHREAD_MUTEX_INITIALIZER;
static dawn_prov_scope *dawn_prov_registry;
/* Optional observation must not shift the base runtime's static TLS data.
 * Plain execution never initializes this key or allocates its context. */
struct dawn_prov_thread_state {
  int enabled;
  dawn_prov_scope *active;
  dawn_prov_invocation *current, *pending;
  pthread_t owner;
  int control_callback;
};
static pthread_key_t dawn_prov_state_key;
static pthread_once_t dawn_prov_state_once = PTHREAD_ONCE_INIT;
static void dawn_prov_invocation_drop(dawn_prov_invocation *v);
static DAWN_PROV_CODE void dawn_prov_state_destroy(void *opaque) {
  dawn_prov_thread_state *state = opaque;
  dawn_prov_invocation_drop(state->pending); dawn_free(state);
}
static DAWN_PROV_CODE void dawn_prov_state_init(void) {
  if (pthread_key_create(&dawn_prov_state_key, dawn_prov_state_destroy)) abort();
}
static DAWN_PROV_CODE dawn_prov_thread_state *dawn_prov_peek_state(void) {
  return pthread_getspecific(dawn_prov_state_key);
}
DAWN_PROV_CODE dawn_prov_thread_state *dawn_prov_context(void) {
  pthread_once(&dawn_prov_state_once, dawn_prov_state_init);
  dawn_prov_thread_state *state = pthread_getspecific(dawn_prov_state_key);
  if (!state) {
    state = calloc(1, sizeof(*state));
    if (!state || pthread_setspecific(dawn_prov_state_key, state)) abort();
    state->owner = pthread_self();
  }
  return state;
}
#define dawn_prov_enabled (dawn_prov_context()->enabled)
#define dawn_prov_active (dawn_prov_context()->active)
#define dawn_prov_current (dawn_prov_context()->current)

static DAWN_PROV_CODE void dawn_prov_fail(const char *message) {
  dawn_str *s = dawn_str_new((int64_t)strlen(message));
  memcpy(dawn_str_data(s), message, strlen(message));
  dawn_panic(s);
}

static DAWN_PROV_CODE void *dawn_prov_grow(void *old, size_t *capacity, size_t need, size_t width) {
  if (need <= *capacity) return old;
  size_t n = *capacity ? *capacity : 32;
  while (n < need) {
    if (n > SIZE_MAX / 2) abort();
    n *= 2;
  }
  if (n > SIZE_MAX / width) abort();
  void *p = realloc(old, n * width);
  if (!p) abort();
  *capacity = n;
  return p;
}

static DAWN_PROV_CODE dawn_prov_scope *dawn_prov_scope_at(int64_t id) {
  pthread_mutex_lock(&dawn_prov_registry_lock);
  dawn_prov_scope *s = dawn_prov_registry;
  while (s && s->id != id) s = s->registered;
  int foreign = s && !pthread_equal(s->owner, dawn_prov_context()->owner);
  pthread_mutex_unlock(&dawn_prov_registry_lock);
  if (!s) dawn_prov_fail("provenance: scope has exited");
  if (foreign) dawn_prov_fail("provenance: different execution context");
  return s;
}

/* Only compiler-owned origin/callback boundaries may use the retained active
 * activation after its lexical user capability has expired. */
static DAWN_PROV_CODE dawn_prov_scope *dawn_prov_lease_scope(int64_t id) {
  dawn_prov_thread_state *state = dawn_prov_context();
  for (dawn_prov_scope *s = state->active; s; s = s->outer) if (s->id == id) {
    if (!pthread_equal(s->owner, state->owner)) dawn_prov_fail("provenance: different execution context");
    return s;
  }
  return dawn_prov_scope_at(id);
}

static DAWN_PROV_CODE dawn_prov_record *dawn_prov_record_at(dawn_prov_scope *s, int64_t id) {
  if (id < 1 || (size_t)id > s->count) return NULL;
  size_t index = (size_t)id - 1;
  return &s->record_chunks[index / 256][index % 256];
}

static DAWN_PROV_CODE int64_t dawn_prov_append(dawn_prov_scope *s, int64_t site, const char *metadata) {
  int64_t id = s->next_instance++;
  if (s->count >= (size_t)s->capacity) {
    s->completeness = 1; s->current = id; return id;
  }
  if (s->count / 256 == s->nchunks) {
    s->record_chunks = dawn_prov_grow(s->record_chunks, &s->chunk_capacity,
      s->nchunks + 1, sizeof(*s->record_chunks));
    s->record_chunks[s->nchunks] = malloc(256 * sizeof(dawn_prov_record));
    if (!s->record_chunks[s->nchunks++]) abort();
  }
  dawn_prov_record r = {id, s->epoch, s->current, site, -1, 0, 0};
  size_t index = s->count++;
  s->record_chunks[index / 256][index % 256] = r;
  s->view = dawn_prov_grow(s->view, &s->view_capacity, s->nview + 1, sizeof(*s->view));
  s->view[s->nview++] = s->count - 1;
  s->current = s->recorded_current = id;
  return id;
}

DAWN_PROV_CODE int64_t dawn_prov_before_ctx(dawn_prov_thread_state *ctx, int64_t site, const char *metadata) {
  if (!ctx->active) return 0;
  dawn_prov_invocation *v = dawn_prov_pool_take(ctx->active);
  if (!v) abort();
  v->refs = 1;
  v->token = atomic_fetch_add(&dawn_prov_next_token, 1);
  v->parent = ctx->current;
  if (v->parent) v->parent->refs++;
  v->site = site;
  v->metadata = metadata;
  v->callback_site = site; v->callback_metadata = metadata;
  for (dawn_prov_scope *s = ctx->active; s; s = s->outer) v->count++;
  if (v->count == 1 && !v->entry_capacity) { v->entries = &v->inline_entry; }
  else {
    if (v->entries == &v->inline_entry) v->entries = NULL;
    v->entries = dawn_prov_grow(v->entries, &v->entry_capacity, v->count, sizeof(*v->entries));
  }
  size_t i = 0;
  for (dawn_prov_scope *s = ctx->active; s; s = s->outer) {
    int64_t parent = s->current, recorded_parent = s->recorded_current;
    int64_t frame = dawn_prov_append(s, site, metadata);
    v->entries[i++] = (dawn_prov_entry){s, frame, parent, recorded_parent,
      (size_t)frame <= s->count ? frame : 0, s->epoch, frame};
    if (s!=v->pool_owner) s->leases++;
  }
  ctx->current = v;
  return v->token;
}

DAWN_PROV_CODE int64_t dawn_prov_before_at_ctx(dawn_prov_thread_state *ctx, int64_t site, const char *metadata,
    int64_t callback_site, const char *callback_metadata) {
  int64_t token = dawn_prov_before_ctx(ctx, site, metadata);
  if (token) {
    ctx->current->callback_site = callback_site;
    ctx->current->callback_metadata = callback_metadata;
  }
  return token;
}

DAWN_PROV_CODE int64_t dawn_prov_arrive_ctx(dawn_prov_thread_state *ctx, int64_t slot, const char *definition) {
  (void)definition;
  if (!ctx->active) return 0;
  int64_t created = 0;
  if (!ctx->current || ctx->current->arrived) {
    /* A missing source-bearing Core seam is explicitly unknown. Reusing
     * the surrounding written Site would invent a plausible call edge. */
    dawn_prov_thread_state *state = ctx;
    dawn_prov_invocation *parent = state->current;
    created = state->control_callback && parent
      ? dawn_prov_before_ctx(ctx, parent->callback_site, parent->callback_metadata)
      : dawn_prov_before_ctx(ctx, -1, "\t\t-1\t-1\t-1\t-1\tunknown\t");
    state->control_callback = 0;
  }
  dawn_prov_invocation *v = ctx->current;
  v->arrived = 1;
  for (size_t i = 0; i < v->count; i++) {
    dawn_prov_record *r = dawn_prov_record_at(v->entries[i].scope, v->entries[i].frame);
    if (r) r->definition = slot;
  }
  return created;
}

static DAWN_PROV_CODE void dawn_prov_invocation_drop(dawn_prov_invocation *v) {
  while (v && --v->refs == 0) {
    dawn_prov_invocation *parent = v->parent;
    dawn_prov_pool_put(v); v = parent;
  }
}

/* A tail segment belongs to one physical invocation. Each logical parent
 * remains pending until that invocation returns or unwinds. */
DAWN_PROV_CODE void dawn_prov_tail_ctx(dawn_prov_thread_state *ctx, int64_t site, const char *metadata) {
  dawn_prov_invocation *v = ctx->current;
  if (!v) return;
  for (size_t i = 0; i < v->count; i++) {
    dawn_prov_scope *s = v->entries[i].scope;
    dawn_prov_entry *e = &v->entries[i];
    dawn_prov_record *previous = dawn_prov_record_at(s, s->current);
    int64_t definition = previous ? previous->definition : -1;
    int64_t next = dawn_prov_append(s, site, metadata); e->logical_tip = next;
    dawn_prov_record *record = dawn_prov_record_at(s, next);
    if (record) { record->definition = definition; e->tip = next; }
  }
}

DAWN_PROV_CODE void dawn_prov_finish_ctx(dawn_prov_thread_state *ctx, int64_t token, int normal) {
  if (!token) return;
  dawn_prov_invocation *v = ctx->current;
  if (!v || v->token != token) dawn_prov_fail("provenance: invocation closed out of order");
  for (size_t i = 0; i < v->count; i++) {
    dawn_prov_scope *s = v->entries[i].scope;
    dawn_prov_record *r = dawn_prov_record_at(s, v->entries[i].frame);
    if (r && r->status && r->status != 4 && !(v->reclaiming && r->status == 3)) dawn_prov_fail("provenance: frame closed twice");
    int64_t current = v->entries[i].tip;
    while (current && current != v->entries[i].recorded_parent) {
      dawn_prov_record *part = dawn_prov_record_at(s, current);
      if (!part || (part->status && part->status != 4 && !(v->reclaiming && part->status == 3))) dawn_prov_fail("provenance: invalid tail segment");
      if (part->status != 4 && !v->reclaiming) part->status = normal ? 1 : 2;
      current = part->parent;
    }
    s->current = v->entries[i].parent;
    s->recorded_current = v->entries[i].recorded_parent;
    /* Frame completion invalidates its markers regardless of how it exits.
     * The frame status remains available to distinguish this from rewind. */
  }
  v->finished = !v->reclaiming; ctx->current = v->parent;
  dawn_prov_invocation_drop(v);
}

/* One lexical cleanup boundary replaces per-call unwind registrations.
 * Calls finish normally at their source seam. Exceptional exit closes only
 * invocations opened inside this activation, preserving the caller's token. */
DAWN_PROV_CODE dawn_prov_function_guard dawn_prov_enter_function_ctx(dawn_prov_thread_state *ctx, int64_t slot, const char *definition) {
  int64_t token = dawn_prov_arrive_ctx(ctx, slot, definition);
  dawn_prov_invocation *current = ctx->current;
  return (dawn_prov_function_guard){ctx, token, current ? current->token : 0, 0};
}
DAWN_PROV_CODE void dawn_prov_function_cleanup(dawn_prov_function_guard *guard) {
  if (guard->normal) return;
  dawn_prov_thread_state *ctx = guard->context;
  while (ctx->current && ctx->current->token != guard->boundary)
    dawn_prov_finish_ctx(ctx, ctx->current->token, 0);
  if (guard->token) dawn_prov_finish_ctx(ctx, guard->token, 0);
}

DAWN_PROV_CODE void dawn_prov_cleanup(dawn_prov_guard *guard) {
  if (guard->token) dawn_prov_finish(guard->token, 0);
}

static const dawn_control_observer dawn_prov_control_hooks;
/* A Plain control activation may enter observe later in its remainder.
 * Install the optional baton hooks before that activation is created; this
 * does not create a session, TLS value, record, or Plain function wrapper. */
static DAWN_PROV_CODE __attribute__((constructor)) void dawn_prov_install_control(void) {
  dawn_control_observation=&dawn_prov_control_hooks;
}
DAWN_PROV_CODE int64_t dawn_prov_open(void) { return dawn_prov_open_capacity(1048576); }
DAWN_PROV_CODE int64_t dawn_prov_open_capacity(int64_t capacity) {
  if (capacity < 1 || capacity > 38347921)
    dawn_prov_fail("provenance: capacity must be between 1 and 38347921");
  dawn_prov_thread_state *cached = dawn_prov_context();
  dawn_control_observation = &dawn_prov_control_hooks;
  dawn_prov_scope *s = calloc(1, sizeof(*s));
  if (!s) abort();
  s->id = atomic_fetch_add(&dawn_prov_next_scope, 1);
  s->epoch = 1;
  s->table = dawn_prov_static_table();
  s->next_instance = 1; s->capacity = capacity;
  s->owner = dawn_prov_context()->owner;
  s->outer = cached->active;
  dawn_prov_append(s, -1, "");
  pthread_mutex_lock(&dawn_prov_registry_lock);
  s->registered = dawn_prov_registry;
  dawn_prov_registry = s;
  pthread_mutex_unlock(&dawn_prov_registry_lock);
  cached->active = s;
  cached->enabled = 1;
  return s->id;
}

static DAWN_PROV_CODE void dawn_prov_scope_free(dawn_prov_scope *s) {
  for (size_t i = 0; i < s->nnotes; i++) dawn_drop(s->notes[i]);
  dawn_free(s->notes);
  dawn_free(s->marks);
  dawn_free(s->activations);
  dawn_free(s->mark_stack);
  dawn_free(s->view);
  for (size_t i = 0; i < s->nchunks; i++) dawn_free(s->record_chunks[i]);
  dawn_free(s->record_chunks);
  dawn_prov_pool_block *b = s->pool_blocks;
  while (b) {
    dawn_prov_pool_block *next = b->next;
    for (size_t i = 0; i < 128; i++)
      if (b->slots[i].entries != &b->slots[i].inline_entry) dawn_free(b->slots[i].entries);
    dawn_free(b); b = next;
  }
  dawn_free(s);
}

DAWN_PROV_CODE void dawn_prov_close(int64_t id, int normal) {
  dawn_prov_thread_state *cached = dawn_prov_context();
  dawn_prov_scope *s = dawn_prov_scope_at(id);
  if (s != cached->active || s->current != 1)
    dawn_prov_fail("provenance: scope closed with active calls");
  dawn_prov_record_at(s, 1)->status = normal ? 1 : 2;
  cached->active = s->outer;
  cached->enabled = cached->active != NULL;
  pthread_mutex_lock(&dawn_prov_registry_lock);
  dawn_prov_scope **slot = &dawn_prov_registry;
  while (*slot != s) slot = &(*slot)->registered;
  *slot = s->registered;
  pthread_mutex_unlock(&dawn_prov_registry_lock);
  for (size_t i = 0; i < s->nmarks; i++) {
    dawn_prov_invocation_drop(s->marks[i].creator); s->marks[i].creator = NULL;
  }
  s->closed = 1;
  if (!s->leases) dawn_prov_scope_free(s);
  dawn_prov_thread_state *state = dawn_prov_peek_state();
  if (!state->active && !state->current) {
    if (pthread_setspecific(dawn_prov_state_key, NULL)) abort();
    dawn_prov_state_destroy(state);
  }
}

typedef struct { char *data; size_t length, capacity; } dawn_prov_text;

static DAWN_PROV_CODE void dawn_prov_text_add(dawn_prov_text *b, const char *fmt, ...) {
  va_list ap, copy;
  va_start(ap, fmt);
  va_copy(copy, ap);
  int n = vsnprintf(NULL, 0, fmt, copy);
  va_end(copy);
  if (n < 0) abort();
  b->data = dawn_prov_grow(b->data, &b->capacity, b->length + (size_t)n + 1, 1);
  vsnprintf(b->data + b->length, (size_t)n + 1, fmt, ap);
  va_end(ap);
  b->length += (size_t)n;
}

static DAWN_PROV_CODE dawn_str *dawn_prov_text_done(dawn_prov_text *b) {
  dawn_str *s = dawn_str_new((int64_t)b->length);
  if (b->length) memcpy(dawn_str_data(s), b->data, b->length);
  dawn_free(b->data);
  return s;
}

DAWN_PROV_CODE dawn_str *dawn_prov_checkpoint(int64_t id) {
  dawn_prov_scope *s = dawn_prov_scope_at(id);
  s->marks = dawn_prov_grow(s->marks, &s->mark_capacity, s->nmarks + 1, sizeof(*s->marks));
  int64_t ordinal = (int64_t)s->nmarks + 1;
  dawn_prov_invocation *creator = dawn_prov_context()->current;
  if (creator) creator->refs++;
  s->marks[s->nmarks++] = (dawn_prov_mark){ordinal, s->current,
    (int64_t)s->nview, (int64_t)s->nnotes, s->next_instance, creator, 1};
  s->mark_stack = dawn_prov_grow(s->mark_stack, &s->mark_stack_capacity, s->nmark_stack + 1, sizeof(*s->mark_stack));
  s->mark_stack[s->nmark_stack++] = (size_t)ordinal - 1;
  dawn_prov_text b = {0};
  dawn_prov_text_add(&b, "%lld:%lld", (long long)id, (long long)ordinal);
  return dawn_prov_text_done(&b);
}

static int dawn_prov_has_suspended(dawn_prov_scope *s, int64_t boundary);
DAWN_PROV_CODE void dawn_prov_rewind(int64_t id, dawn_str *checkpoint) {
  long long scope_id = 0, ordinal = 0;
  char *text = malloc((size_t)checkpoint->len + 1);
  if (!text) abort();
  memcpy(text, checkpoint->p, (size_t)checkpoint->len);
  text[checkpoint->len] = 0;
  int parsed = sscanf(text, "%lld:%lld", &scope_id, &ordinal);
  dawn_free(text);
  if (parsed != 2) dawn_prov_fail("provenance: invalid checkpoint");
  dawn_prov_scope *s = dawn_prov_scope_at((int64_t)scope_id);
  if (scope_id != id) dawn_prov_fail("provenance: checkpoint belongs to another scope");
  if (ordinal < 1 || (size_t)ordinal > s->nmarks) dawn_prov_fail("provenance: invalid checkpoint");
  dawn_prov_mark *c = &s->marks[ordinal - 1];
  if (c->creator ? c->creator->finished : dawn_prov_record_at(s,1)->status != 0)
    dawn_prov_fail("provenance: creating frame has finished");
  if (!c->valid) dawn_prov_fail("provenance: checkpoint has been invalidated");
  if (s->current != c->frame) dawn_prov_fail("provenance: not in the creating frame");
  if (dawn_prov_has_suspended(s,c->logical_boundary)) dawn_prov_fail("provenance: checkpoint has suspended calls");
  for (size_t i = (size_t)c->boundary; i < s->nview; i++)
    if (dawn_prov_record_at(s, (int64_t)s->view[i] + 1)->status == 3) dawn_prov_fail("provenance: checkpoint has suspended calls");
  while (s->nmark_stack && s->mark_stack[s->nmark_stack - 1] != (size_t)ordinal - 1)
    s->marks[s->mark_stack[--s->nmark_stack]].valid = 0;
  s->nview = (size_t)c->boundary;
  while (s->nnotes > (size_t)c->note_boundary) dawn_drop(s->notes[--s->nnotes]);
  s->epoch++;
}

/* Serialization is a consumer, separate from event recording. Append static
 * metadata directly and format integer fields without a varargs parser or a
 * sizing printf pass for every record. No field or parent is omitted. */
static DAWN_PROV_CODE void dawn_prov_text_bytes(dawn_prov_text *b, const char *text, size_t n) {
  b->data = dawn_prov_grow(b->data, &b->capacity, b->length + n + 1, 1);
  memcpy(b->data + b->length, text, n); b->length += n; b->data[b->length] = 0;
}
static DAWN_PROV_CODE void dawn_prov_text_char(dawn_prov_text *b, char c) {
  dawn_prov_text_bytes(b, &c, 1);
}
static DAWN_PROV_CODE void dawn_prov_text_integer(dawn_prov_text *b, int64_t value) {
  char buffer[24], *end = buffer + sizeof(buffer), *at = end;
  uint64_t n = value < 0 ? UINT64_C(0) - (uint64_t)value : (uint64_t)value;
  do { *--at = (char)('0' + n % 10); n /= 10; } while (n);
  if (value < 0) *--at = '-';
  dawn_prov_text_bytes(b, at, (size_t)(end - at));
}
typedef struct {
  int64_t id, epoch, parent, site;
  const char *metadata, *definition;
  int status;
} dawn_prov_text_record;
static DAWN_PROV_CODE void dawn_prov_write_record(dawn_prov_text *b, dawn_prov_scope *s, dawn_prov_text_record *r) {
  dawn_prov_text_bytes(b, "F\t", 2);
  dawn_prov_text_integer(b, s->id); dawn_prov_text_char(b, '\t');
  dawn_prov_text_integer(b, r->epoch); dawn_prov_text_char(b, '\t');
  dawn_prov_text_integer(b, r->id); dawn_prov_text_char(b, '\t');
  dawn_prov_text_integer(b, r->parent); dawn_prov_text_char(b, '\t');
  dawn_prov_text_integer(b, r->status); dawn_prov_text_char(b, '\t');
  dawn_prov_text_integer(b, r->site); dawn_prov_text_char(b, '\t');
  dawn_prov_text_bytes(b, r->metadata, strlen(r->metadata)); dawn_prov_text_char(b, '\t');
  dawn_prov_text_bytes(b, r->definition, strlen(r->definition));
}

/* Frozen storage contains only little endian dynamic words and references to
 * immutable language values. No getter can reach a scope or invocation. */
static pthread_once_t dawn_prov_table_once = PTHREAD_ONCE_INIT;
static dawn_adt *dawn_prov_table_value;
static dawn_prov_site *dawn_prov_sorted_sites;
static DAWN_PROV_CODE int dawn_prov_site_compare(const void *a, const void *b) {
  int64_t x = ((const dawn_prov_site *)a)->id, y = ((const dawn_prov_site *)b)->id;
  return (x > y) - (x < y);
}
static DAWN_PROV_CODE void dawn_prov_table_init(void) {
  dawn_array *sites = dawn_array_new(), *defs = dawn_array_new();
  dawn_prov_sorted_sites = malloc((dawn_prov_sites_n + 1) * sizeof(*dawn_prov_sorted_sites));
  if (!dawn_prov_sorted_sites) abort();
  memcpy(dawn_prov_sorted_sites, dawn_prov_sites, dawn_prov_sites_n * sizeof(*dawn_prov_sites));
  qsort(dawn_prov_sorted_sites, dawn_prov_sites_n, sizeof(*dawn_prov_sorted_sites), dawn_prov_site_compare);
  for (size_t i = 0; i < dawn_prov_sites_n; i++) {
    const dawn_prov_site_fields *x = &dawn_prov_static_sites[i];
    dawn_adt *numbers = dawn_adt_new(0, 5, 31), *strings = dawn_adt_new(0, 5, 31);
    numbers->fields[0].p = dawn_box_int(x->id); numbers->fields[1].p = dawn_box_int(x->start);
    numbers->fields[2].p = dawn_box_int(x->end); numbers->fields[3].p = dawn_box_int(x->name_start);
    numbers->fields[4].p = dawn_box_int(x->name_end);
    strings->fields[0].p = dawn_dup(x->owner); strings->fields[1].p = dawn_dup(x->owner);
    strings->fields[2].p = dawn_dup(x->declaration); strings->fields[3].p = dawn_dup(x->role);
    strings->fields[4].p = dawn_dup(x->operation);
    dawn_adt *row = dawn_adt_new(0, 2, 3); row->fields[0].p = numbers; row->fields[1].p = strings;
    sites = dawn_array_push_own(sites, row);
  }
  for (size_t i = 0; i < dawn_prov_definitions_n; i++) {
    const dawn_prov_definition_fields *x = &dawn_prov_static_definitions[i];
    dawn_adt *row = dawn_adt_new(0, 6, 63);
    row->fields[0].p = dawn_box_int(x->id); row->fields[1].p = dawn_dup(x->owner);
    row->fields[2].p = dawn_dup(x->declaration); row->fields[3].p = dawn_box_int(x->start);
    row->fields[4].p = dawn_box_int(x->end); row->fields[5].p = dawn_dup(x->role);
    defs = dawn_array_push_own(defs, row);
  }
  dawn_prov_table_value = dawn_adt_new(0, 2, 3);
  dawn_prov_table_value->fields[0].p = sites; dawn_prov_table_value->fields[1].p = defs;
}
DAWN_PROV_CODE dawn_adt *dawn_prov_static_table(void) {
  pthread_once(&dawn_prov_table_once, dawn_prov_table_init); return dawn_prov_table_value;
}
static DAWN_PROV_CODE int64_t dawn_prov_site_index(int64_t id) {
  if (id <= 0) return -1;
  size_t lo = 0, hi = dawn_prov_sites_n;
  while (lo < hi) { size_t mid = lo + (hi - lo) / 2;
    if (dawn_prov_sorted_sites[mid].id < id) lo = mid + 1; else hi = mid; }
  if (lo == dawn_prov_sites_n || dawn_prov_sorted_sites[lo].id != id) dawn_prov_fail("provenance: missing static Site");
  return (int64_t)lo;
}
static DAWN_PROV_CODE int64_t dawn_prov_definition_index(const char *definition) {
  if (!*definition) return -1;
  size_t lo = 0, hi = dawn_prov_definitions_n;
  while (lo < hi) { size_t mid = lo + (hi - lo) / 2;
    if (strcmp(dawn_prov_definitions[mid], definition) < 0) lo = mid + 1; else hi = mid; }
  if (lo == dawn_prov_definitions_n || strcmp(dawn_prov_definitions[lo], definition)) dawn_prov_fail("provenance: missing static Definition");
  return (int64_t)lo;
}
static DAWN_PROV_CODE dawn_bytes *dawn_prov_frozen_new(size_t records) {
  if (records > (INT32_MAX / 8 - 4) / 7) dawn_prov_fail("provenance: snapshot capacity exceeded");
  dawn_bytes *value = malloc(sizeof(*value)); if (!value) abort();
  value->h = (dawn_hdr){1, DAWN_K_BYTES};
  value->len = (int64_t)(4 + records * 7) * 8; value->p = malloc((size_t)value->len + 1);
  if (!value->p) abort(); return value;
}
static DAWN_PROV_CODE void dawn_prov_put_word(dawn_bytes *value, size_t index, int64_t number) {
  unsigned char *p = (unsigned char *)value->p + index * 8;
  uint64_t bits = (uint64_t)number; for (int i = 0; i < 8; i++) { p[i] = (unsigned char)bits; bits >>= 8; }
}
DAWN_PROV_CODE int64_t dawn_prov_word(dawn_bytes *data, int64_t index) {
  if (index < 0 || index >= data->len / 8) dawn_prov_fail("provenance: invalid frozen word");
  const unsigned char *p = data->p + index * 8; uint64_t bits = 0;
  for (int i = 7; i >= 0; i--) bits = (bits << 8) | p[i]; return (int64_t)bits;
}
DAWN_PROV_CODE int64_t dawn_prov_header(dawn_adt *view, int64_t field) {
  if (field < 0 || field >= 4) dawn_prov_fail("provenance: invalid frozen field");
  return dawn_prov_word(view->fields[0].p, field);
}
DAWN_PROV_CODE int64_t dawn_prov_column(dawn_adt *view, int64_t row, int64_t field) {
  dawn_bytes *data = view->fields[0].p;
  if (row < 0 || row >= dawn_prov_word(data, 2)) dawn_prov_fail("provenance: record index out of bounds");
  if (field < 0 || field >= 7) dawn_prov_fail("provenance: invalid frozen field");
  return dawn_prov_word(data, 4 + row * 7 + field);
}
static DAWN_PROV_CODE dawn_bytes *dawn_prov_freeze(dawn_prov_scope *s, const size_t *view, size_t n, int envelope) {
  dawn_bytes *data = dawn_prov_frozen_new(n);
  dawn_prov_put_word(data, 0, s->id); dawn_prov_put_word(data, 1, s->epoch);
  dawn_prov_put_word(data, 2, (int64_t)n); dawn_prov_put_word(data, 3, s->completeness);
  /* IDs are monotonic even after rewind. A temporary ID-to-row array makes
   * parent translation linear and never reconnects a missing ancestor. */
  int64_t *rows = envelope ? NULL : malloc((s->count + 1) * sizeof(*rows));
  if (!envelope && !rows) abort();
  if (rows) for (size_t i = 0; i <= s->count; i++) rows[i] = -1;
  for (size_t i = 0; i < n; i++) {
    dawn_prov_record *r = dawn_prov_record_at(s, (int64_t)view[i] + 1);
    int64_t parent = r->parent ? (envelope ? (int64_t)i-1 : rows[r->parent]) : -1;
    if (r->parent && parent < 0) abort();
    if (rows) rows[r->id] = (int64_t)i; size_t at = 4 + i * 7;
    dawn_prov_put_word(data, at, r->epoch); dawn_prov_put_word(data, at + 1, r->id);
    dawn_prov_put_word(data, at + 2, parent); dawn_prov_put_word(data, at + 3, r->status);
    dawn_prov_put_word(data, at + 4, r->site);
    dawn_prov_put_word(data, at + 5, envelope && i + 1 == n ? -1 : r->definition);
    dawn_prov_put_word(data, at + 6, r->boundary);
  }
  dawn_free(rows); return data;
}
typedef struct { const char *start; size_t length; } dawn_prov_span;
static DAWN_PROV_CODE dawn_prov_span dawn_prov_field_span(const dawn_str *raw, int64_t index) {
  if (index < 0) dawn_prov_fail("provenance: invalid static field");
  const char *p = raw->p, *end = p + raw->len;
  while (index--) { p = memchr(p, '\t', (size_t)(end - p)); if (!p) dawn_prov_fail("provenance: invalid static field"); p++; }
  const char *next = memchr(p, '\t', (size_t)(end - p));
  return (dawn_prov_span){p, (size_t)((next ? next : end) - p)};
}
DAWN_PROV_CODE dawn_str *dawn_prov_field(dawn_str *raw, int64_t index) {
  dawn_prov_span span = dawn_prov_field_span(raw, index); dawn_prov_text b = {0};
  for (size_t i = 0; i < span.length; i++) {
    char c = span.start[i];
    if (c == '%') {
      if (i + 2 >= span.length) dawn_prov_fail("provenance: invalid static escape");
      char a = span.start[i+1], d = span.start[i+2];
      if (a == '2' && d == '5') c = '%';
      else if (a == '0' && (d == '9' || d == 'A' || d == 'D' || d == '0')) c = d == '9' ? '\t' : d == 'A' ? '\n' : d == 'D' ? '\r' : 0;
      else dawn_prov_fail("provenance: invalid static escape"); i += 2;
    }
    dawn_prov_text_char(&b, c);
  }
  return dawn_prov_text_done(&b);
}
DAWN_PROV_CODE int64_t dawn_prov_number(dawn_str *raw, int64_t index) {
  dawn_prov_span span = dawn_prov_field_span(raw, index); if (!span.length) return -1;
  size_t i = span.start[0] == '-'; int negative = i != 0; uint64_t n = 0;
  uint64_t limit = negative ? UINT64_C(9223372036854775808) : INT64_MAX;
  if (i == span.length) dawn_prov_fail("provenance: invalid static number");
  for (; i < span.length; i++) { unsigned d = (unsigned char)span.start[i] - '0';
    if (d > 9 || n > (limit-d)/10) dawn_prov_fail("provenance: invalid static number"); n = n*10+d; }
  return negative ? (int64_t)(UINT64_C(0)-n) : (int64_t)n;
}
DAWN_PROV_CODE dawn_adt *dawn_prov_origin(int64_t id) {
  dawn_prov_thread_state *cached = dawn_prov_context(); dawn_prov_scope *s = dawn_prov_lease_scope(id);
  dawn_prov_invocation *operation = cached->current;
  while (operation && !strstr(operation->metadata, "\tperform\t")) operation = operation->parent;
  if (!operation) operation = cached->pending;
  while (operation && !strstr(operation->metadata, "\tperform\t")) operation = operation->parent;
  if (!operation) dawn_prov_fail("provenance: no operation origin");
  int64_t sender = 0;
  for (size_t i = 0; i < operation->count; i++) if (operation->entries[i].scope == s) sender = operation->entries[i].frame;
  if (!sender) dawn_prov_fail("provenance: operation is outside the observation scope");
  if ((size_t)sender > s->count) {
    dawn_bytes *data = dawn_prov_frozen_new(1);
    int64_t epoch = s->epoch;
    for (size_t i=0; i<operation->count; i++) if (operation->entries[i].scope==s) epoch=operation->entries[i].epoch;
    int64_t words[] = {s->id, s->epoch, 1, 1, epoch, sender, -1, operation->suspended ? 3 : 0, operation->site, -1, 1};
    for (size_t i=0;i<11;i++) dawn_prov_put_word(data,i,words[i]);
    dawn_adt *value = dawn_adt_new(0,4,15);
    value->fields[0].p=data; value->fields[1].p=dawn_dup(s->table); value->fields[2].p=dawn_box_int(0);
    dawn_adt *site=dawn_array_get(s->table->fields[0].p,operation->site);
    value->fields[3].p=dawn_dup(((dawn_adt *)site->fields[1].p)->fields[4].p); return value;
  }
  size_t n = 0; for (int64_t f = sender; f; f = dawn_prov_record_at(s, f)->parent) n++;
  size_t *view = malloc(n * sizeof(*view)); if (!view) abort(); size_t at = n;
  for (int64_t f = sender; f; f = dawn_prov_record_at(s, f)->parent) view[--at] = (size_t)f - 1;
  dawn_bytes *data = dawn_prov_freeze(s, view, n, 1); dawn_free(view);
  dawn_adt *value = dawn_adt_new(0, 4, 15);
  value->fields[0].p = data; value->fields[1].p = dawn_dup(s->table); value->fields[2].p = dawn_box_int((int64_t)n-1);
  dawn_adt *site = dawn_array_get(s->table->fields[0].p, operation->site);
  value->fields[3].p = dawn_dup(((dawn_adt *)site->fields[1].p)->fields[4].p); return value;
}
DAWN_PROV_CODE void dawn_prov_note(int64_t id, dawn_adt *origin) {
  dawn_prov_scope *s = dawn_prov_scope_at(id);
  if (s->notes_written++ >= (size_t)s->capacity) { s->completeness = 1; return; }
  s->notes = dawn_prov_grow(s->notes, &s->note_capacity, s->nnotes+1, sizeof(*s->notes));
  s->notes[s->nnotes++] = dawn_dup(origin);
}
DAWN_PROV_CODE dawn_adt *dawn_prov_completed(int64_t id) {
  dawn_prov_scope *s = dawn_prov_scope_at(id); dawn_adt *value = dawn_adt_new(0, 3, 7);
  value->fields[0].p = dawn_prov_freeze(s, s->view, s->nview, 0);
  value->fields[1].p = dawn_dup(s->table); dawn_array *notes = dawn_array_new();
  for (size_t i = 0; i < s->nnotes; i++) notes = dawn_array_push_own(notes, dawn_dup(s->notes[i]));
  value->fields[2].p = notes; return value;
}
static DAWN_PROV_CODE void dawn_prov_render_string(dawn_prov_text *b, dawn_str *value) {
  for (int64_t i = 0; i < value->len; i++) {
    char c = value->p[i]; const char *escape = c == '%' ? "%25" : c == '\t' ? "%09" : c == '\n' ? "%0A" : c == '\r' ? "%0D" : c == 0 ? "%00" : NULL;
    if (escape) dawn_prov_text_bytes(b, escape, 3); else dawn_prov_text_char(b, c);
  }
}
static DAWN_PROV_CODE void dawn_prov_render_site(dawn_prov_text *b, dawn_adt *site) {
  dawn_adt *numbers = site->fields[0].p, *strings = site->fields[1].p;
  dawn_prov_text_integer(b, dawn_peek_int(numbers->fields[0].p)); dawn_prov_text_char(b, '\t');
  dawn_prov_render_string(b, strings->fields[0].p); dawn_prov_text_char(b, '\t');
  dawn_prov_render_string(b, strings->fields[2].p);
  for (int i = 1; i < 5; i++) { dawn_prov_text_char(b, '\t'); dawn_prov_text_integer(b, dawn_peek_int(numbers->fields[i].p)); }
  dawn_prov_text_char(b, '\t'); dawn_prov_render_string(b, strings->fields[3].p);
  dawn_prov_text_char(b, '\t'); dawn_prov_render_string(b, strings->fields[4].p);
}
static DAWN_PROV_CODE void dawn_prov_render_definition(dawn_prov_text *b, dawn_adt *d) {
  dawn_prov_render_string(b, d->fields[1].p); dawn_prov_text_char(b, '\t');
  dawn_prov_render_string(b, d->fields[2].p); dawn_prov_text_char(b, '\t');
  dawn_prov_text_integer(b, dawn_peek_int(d->fields[3].p)); dawn_prov_text_char(b, '\t');
  dawn_prov_text_integer(b, dawn_peek_int(d->fields[4].p)); dawn_prov_text_char(b, '\t');
  dawn_prov_render_string(b, d->fields[5].p); dawn_prov_text_char(b, '\t');
  dawn_prov_text_integer(b, dawn_peek_int(d->fields[0].p));
}
static DAWN_PROV_CODE void dawn_prov_render_record(dawn_prov_text *b, dawn_bytes *data, dawn_adt *table, int64_t row) {
  int64_t at = 4 + row * 7, site = dawn_prov_word(data, at+4), def = dawn_prov_word(data, at+5);
  int64_t parent = dawn_prov_word(data, at+2);
  dawn_prov_text_bytes(b, "F\t", 2); dawn_prov_text_integer(b, dawn_prov_word(data, 0));
  dawn_prov_text_char(b, '\t'); dawn_prov_text_integer(b, dawn_prov_word(data, at));
  dawn_prov_text_char(b, '\t'); dawn_prov_text_integer(b, dawn_prov_word(data, at+1));
  dawn_prov_text_char(b, '\t'); dawn_prov_text_integer(b, parent < 0 ? 0 : dawn_prov_word(data, 4+parent*7+1));
  dawn_prov_text_char(b, '\t'); dawn_prov_text_integer(b, dawn_prov_word(data, at+3));
  dawn_prov_text_char(b, '\t');
  if (site >= 0) dawn_prov_render_site(b, dawn_array_get(table->fields[0].p, site));
  else dawn_prov_text_bytes(b, "0\t", 2);
  dawn_prov_text_char(b, '\t');
  if (def >= 0) dawn_prov_render_definition(b, dawn_array_get(table->fields[1].p, def));
  dawn_prov_text_char(b, '\t'); dawn_prov_text_integer(b, dawn_prov_word(data, at+6));
}
static DAWN_PROV_CODE void dawn_prov_render_origin_into(dawn_prov_text *b, dawn_adt *origin) {
  dawn_bytes *data = origin->fields[0].p; dawn_adt *table = origin->fields[1].p; int64_t row = dawn_peek_int(origin->fields[2].p);
  int64_t site = dawn_prov_word(data, 4+(dawn_prov_word(data, 2)-1)*7+4); dawn_prov_text_bytes(b, "O1\t", 3);
  if (site >= 0) dawn_prov_render_site(b, dawn_array_get(table->fields[0].p, site));
  else dawn_prov_text_bytes(b, "0\t", 2);
  dawn_prov_text_char(b, '\t'); dawn_prov_text_integer(b, dawn_prov_word(data, 3));
  while (row >= 0) { dawn_prov_text_char(b, '\n'); dawn_prov_render_record(b, data, table, row); row = dawn_prov_word(data, 4+row*7+2); }
}
DAWN_PROV_CODE dawn_str *dawn_prov_render_origin(dawn_adt *origin) {
  dawn_prov_text b = {0}; dawn_prov_render_origin_into(&b, origin); return dawn_prov_text_done(&b);
}
DAWN_PROV_CODE dawn_str *dawn_prov_render_snapshot(dawn_adt *snapshot) {
  dawn_bytes *data = snapshot->fields[0].p; dawn_adt *table = snapshot->fields[1].p; dawn_array *notes = snapshot->fields[2].p;
  dawn_prov_text b = {0}; dawn_prov_text_bytes(&b, "S1\t", 3); dawn_prov_text_integer(&b, dawn_prov_word(data, 0));
  dawn_prov_text_char(&b, '\t'); dawn_prov_text_integer(&b, dawn_prov_word(data, 1));
  dawn_prov_text_char(&b, '\t'); dawn_prov_text_integer(&b, dawn_prov_word(data, 3));
  for (int64_t i = 0; i < dawn_prov_word(data, 2); i++) { dawn_prov_text_char(&b, '\n'); dawn_prov_render_record(&b, data, table, i); }
  for (int64_t i = 0; i < dawn_array_len(notes); i++) { dawn_prov_text_bytes(&b, "\n\n", 2); dawn_prov_render_origin_into(&b, dawn_array_get(notes, i)); }
  return dawn_prov_text_done(&b);
}

DAWN_PROV_CODE void dawn_prov_unknown_ctx(dawn_prov_thread_state *ctx) {
  dawn_prov_invocation *v=ctx->current; if (!v) return;
  v->arrived=1;
  for (size_t i=0;i<v->count;i++) {
    dawn_prov_record *r=dawn_prov_record_at(v->entries[i].scope,v->entries[i].frame);
    if (r) r->boundary=1;
  }
}


typedef struct { int64_t scope, token; } dawn_prov_observer_guard;
static DAWN_PROV_CODE void dawn_prov_observer_cleanup(dawn_prov_observer_guard *guard) {
  if (!guard->scope) return;
  dawn_prov_finish(guard->token, 0);
  dawn_prov_close(guard->scope, 0);
}

DAWN_PROV_CODE void *dawn_prov_select_closure(dawn_clo *body) {
  /* A continuation is the runtime's two-capture ticket with a private ctl
   * activation in its first counted slot. Source closures cannot hold this
   * private activation directly. Reject before touching its carrier. */
  if (body->ncap == 2 && body->capmask.narrow == 1 && body->caps[0].p &&
      !dawn_is_imm(body->caps[0].p) && ((dawn_hdr *)body->caps[0].p)->kind == DAWN_K_CTL)
    return body->fn;
  return dawn_prov_select(body->fn);
}

/* These adapters exist only around synchronous runtime callback operands.
 * They keep the canonical closure intact and own no source observation
 * capability. Their temporary owner checks scope and thread before dispatch. */
static DAWN_PROV_CODE void *dawn_prov_callback1(dawn_clo *proxy, void *a0) {
  dawn_prov_lease_scope(proxy->caps[3].i);
  dawn_clo *body = proxy->caps[0].p;
  DAWN_CLEANUP(dawn_prov_cleanup) dawn_prov_guard guard = {
    dawn_prov_before_ctx(dawn_prov_context(), proxy->caps[1].i, proxy->caps[2].p)
  };
  void *result = ((void *(*)(dawn_clo *, void *))dawn_prov_select_closure(body))(body, a0);
  dawn_prov_finish(guard.token, 1); guard.token = 0;
  return result;
}
static DAWN_PROV_CODE void *dawn_prov_callback2(dawn_clo *proxy, void *a0, void *a1) {
  dawn_prov_lease_scope(proxy->caps[3].i);
  dawn_clo *body = proxy->caps[0].p;
  DAWN_CLEANUP(dawn_prov_cleanup) dawn_prov_guard guard = {
    dawn_prov_before_ctx(dawn_prov_context(), proxy->caps[1].i, proxy->caps[2].p)
  };
  void *result = ((void *(*)(dawn_clo *, void *, void *))dawn_prov_select_closure(body))(body, a0, a1);
  dawn_prov_finish(guard.token, 1); guard.token = 0;
  return result;
}
DAWN_PROV_CODE dawn_clo *dawn_prov_wrap(dawn_clo *body, int arity, int64_t site, const char *metadata) {
  dawn_prov_thread_state *cached = dawn_prov_context();
  if (!cached->active) dawn_prov_fail("provenance: callback is outside observation");
  if (site < 0) {
    if (!cached->current) dawn_prov_fail("provenance: callback has no initiating invocation");
    site = cached->current->callback_site;
    metadata = cached->current->callback_metadata;
  }
  void *entry = arity == 1 ? (void *)dawn_prov_callback1 :
                arity == 2 ? (void *)dawn_prov_callback2 : NULL;
  if (!entry) dawn_prov_fail("provenance: unsupported runtime callback arity");
  dawn_clo *proxy = dawn_clo_new(entry, 4, 1);
  proxy->caps[0].p = dawn_dup(body);
  proxy->caps[1].i = site;
  proxy->caps[2].p = (void *)metadata;
  proxy->caps[3].i = cached->active->id;
  return proxy;
}

DAWN_PROV_CODE void *dawn_prov_observe(dawn_clo *body, int64_t capacity, void *evidence, int64_t site, const char *metadata, dawn_adt *table) {
  (void)table;
  DAWN_CLEANUP(dawn_prov_observer_cleanup) dawn_prov_observer_guard guard = {dawn_prov_open_capacity(capacity), 0};
  guard.token = dawn_prov_before_ctx(dawn_prov_context(), site, metadata);
  void *result = ((void *(*)(dawn_clo *, void *, void *))dawn_prov_select_closure(body))(body, dawn_box_int(guard.scope), dawn_dup(evidence));
  dawn_prov_finish(guard.token, 1);
  dawn_prov_close(guard.scope, 1);
  guard.scope = 0;
  return result;
}

/* Snapshots follow the control baton. Frame numbers are saved independently
 * for each scope; mounting never derives logical parents from a host stack. */
struct dawn_prov_activation {
  dawn_prov_thread_state state, arm_state;
  dawn_prov_scope **scopes;
  int64_t *currents, *recorded_currents, *arm_currents, *arm_recorded_currents;
  size_t count, arm_count;
  int suspended;
  int64_t mode_scope;
  dawn_prov_invocation *boundary;
};
static DAWN_PROV_CODE int dawn_prov_has_suspended(dawn_prov_scope *s, int64_t boundary) {
  if (s->unresumed>=boundary) return 1;
  for (size_t i=0;i<s->nactivations;i++) {
    dawn_prov_activation *a=s->activations[i]; if (!a->suspended) continue;
    for (dawn_prov_invocation *v=a->state.current; v && v!=a->boundary; v=v->parent)
      for (size_t j=0;j<v->count;j++) if (v->entries[j].scope==s && v->entries[j].logical_tip>=boundary) return 1;
  }
  return 0;
}
static DAWN_PROV_CODE void dawn_prov_mark_segment(dawn_prov_entry *e, int before, int after) {
  for (int64_t f=e->tip; f && f!=e->recorded_parent; f=dawn_prov_record_at(e->scope,f)->parent) {
    dawn_prov_record *r=dawn_prov_record_at(e->scope,f); if (r->status==before) r->status=after;
  }
}

static DAWN_PROV_CODE void *dawn_prov_control_capture(void) {
  pthread_once(&dawn_prov_state_once,dawn_prov_state_init);
  dawn_prov_thread_state empty = {0}; empty.owner=pthread_self();
  dawn_prov_thread_state *state = dawn_prov_peek_state();
  if (!state) state=&empty;
  dawn_prov_activation *a = calloc(1, sizeof(*a));
  if (!a) abort();
  a->state = a->arm_state = *state; a->boundary = state->current;
  a->mode_scope=state->active ? state->active->id : 0;
  if (a->state.current) a->state.current->refs+=2;
  if (a->state.pending) a->state.pending->refs+=2;
  for (dawn_prov_scope *s = state->active; s; s = s->outer) a->count++;
  a->scopes = calloc(a->count, sizeof(*a->scopes));
  a->currents = calloc(a->count, sizeof(*a->currents));
  a->recorded_currents = calloc(a->count, sizeof(*a->recorded_currents));
  a->arm_count=a->count;
  a->arm_currents = calloc(a->count, sizeof(*a->arm_currents));
  a->arm_recorded_currents = calloc(a->count, sizeof(*a->arm_recorded_currents));
  for (size_t i = 0; i < a->count; i++) {
    dawn_prov_scope *s = i ? a->scopes[i-1]->outer : state->active;
    a->scopes[i] = s; a->currents[i] = s->current; a->recorded_currents[i]=s->recorded_current;
    a->arm_currents[i]=s->current; a->arm_recorded_currents[i]=s->recorded_current; s->leases++;
    s->activations=dawn_prov_grow(s->activations,&s->activation_capacity,s->nactivations+1,sizeof(*s->activations));
    s->activations[s->nactivations++]=a;
  }
  return a;
}
static DAWN_PROV_CODE void dawn_prov_activation_clear(dawn_prov_activation *a) {
  if (!a) return;
  dawn_prov_invocation_drop(a->state.current);
  dawn_prov_invocation_drop(a->state.pending);
  dawn_prov_invocation_drop(a->arm_state.current);
  dawn_prov_invocation_drop(a->arm_state.pending);
  for (size_t i = 0; i < a->count; i++) {
    dawn_prov_scope *s = a->scopes[i];
    size_t j=0; while (j<s->nactivations && s->activations[j]!=a) j++;
    if (j==s->nactivations) abort();
    memmove(s->activations+j,s->activations+j+1,(s->nactivations-j-1)*sizeof(*s->activations)); s->nactivations--;
    if (!--s->leases && s->closed) dawn_prov_scope_free(s);
  }
  dawn_free(a->scopes); dawn_free(a->currents); dawn_free(a->recorded_currents); dawn_free(a->arm_currents); dawn_free(a->arm_recorded_currents);
  int64_t mode_scope=a->mode_scope;
  memset(a,0,sizeof(*a)); a->mode_scope=mode_scope;
}
static DAWN_PROV_CODE void dawn_prov_control_release(void *opaque) {
  dawn_prov_activation *a=opaque; if (!a) return;
  dawn_prov_activation_clear(a); dawn_free(a);
}
static DAWN_PROV_CODE void dawn_prov_control_attach(void *opaque) {
  dawn_prov_activation *a = opaque;
  dawn_prov_thread_state *state = dawn_prov_context();
  if (a->state.pending) a->state.pending->refs++;
  dawn_prov_invocation_drop(state->pending);
  *state = a->state; a->suspended=0;
  for (size_t i = 0; i < a->count; i++) {
    a->scopes[i]->current = a->currents[i]; a->scopes[i]->recorded_current=a->recorded_currents[i];
  }
  for (dawn_prov_invocation *v = state->current; v && v != a->boundary; v = v->parent)
    { v->suspended=0;
      for (size_t i = 0; i < v->count; i++) dawn_prov_mark_segment(&v->entries[i],3,0);
    }
  if (!state->active && !state->current && !state->pending) {
    if (pthread_setspecific(dawn_prov_state_key,NULL)) abort();
    dawn_prov_state_destroy(state);
  }
}
static DAWN_PROV_CODE void dawn_prov_track_scopes(dawn_prov_activation *a, dawn_prov_scope *active) {
  for (size_t i=a->count;i>a->arm_count;) {
    i--; dawn_prov_scope *scope=a->scopes[i]; int live=0;
    for (dawn_prov_scope *s=active;s;s=s->outer) if (s==scope) live=1;
    if (!live) {
      size_t j=0; while (j<scope->nactivations && scope->activations[j]!=a) j++;
      if (j==scope->nactivations) abort();
      memmove(scope->activations+j,scope->activations+j+1,(scope->nactivations-j-1)*sizeof(*scope->activations)); scope->nactivations--;
      memmove(a->scopes+i,a->scopes+i+1,(a->count-i-1)*sizeof(*a->scopes));
      memmove(a->currents+i,a->currents+i+1,(a->count-i-1)*sizeof(*a->currents));
      memmove(a->recorded_currents+i,a->recorded_currents+i+1,(a->count-i-1)*sizeof(*a->recorded_currents)); a->count--;
      if (!--scope->leases && scope->closed) dawn_prov_scope_free(scope);
    }
  }
  for (dawn_prov_scope *s=active;s;s=s->outer) {
    size_t i=0; while (i<a->count && a->scopes[i]!=s) i++;
    if (i==a->count) {
      a->scopes=realloc(a->scopes,(a->count+1)*sizeof(*a->scopes));
      a->currents=realloc(a->currents,(a->count+1)*sizeof(*a->currents));
      a->recorded_currents=realloc(a->recorded_currents,(a->count+1)*sizeof(*a->recorded_currents));
      if (!a->scopes || !a->currents || !a->recorded_currents) abort();
      a->scopes[a->count++]=s; s->leases++;
      s->activations=dawn_prov_grow(s->activations,&s->activation_capacity,s->nactivations+1,sizeof(*s->activations));
      s->activations[s->nactivations++]=a;
    }
  }
}
static DAWN_PROV_CODE void dawn_prov_control_save(void *opaque, int done) {
  dawn_prov_activation *a = opaque;
  dawn_prov_thread_state *state = dawn_prov_context();
  if (state->current) state->current->refs++;
  if (state->pending) state->pending->refs++;
  dawn_prov_invocation_drop(a->state.current);
  dawn_prov_invocation_drop(a->state.pending); a->state = *state;
  a->mode_scope=state->active ? state->active->id : 0;
  dawn_prov_track_scopes(a,state->active);
  a->suspended=!done;
  for (size_t i = 0; i < a->count; i++) {
    a->currents[i] = a->scopes[i]->current; a->recorded_currents[i]=a->scopes[i]->recorded_current;
  }
  if (!done) for (dawn_prov_invocation *v = state->current; v && v != a->boundary; v = v->parent)
    { v->suspended=1;
      for (size_t i = 0; i < v->count; i++) dawn_prov_mark_segment(&v->entries[i],0,3);
    }
  if (done) dawn_prov_activation_clear(a);
}
static DAWN_PROV_CODE void dawn_prov_control_relate(void *driver, void *activation) {
  dawn_prov_activation *saved = driver, *a = activation;
  if (saved->state.active && saved->state.active->id!=a->mode_scope)
    dawn_prov_unknown_ctx(&saved->state);
  if (!a->suspended) return;
  if (a->state.current) a->state.current->refs++;
  dawn_prov_invocation_drop(saved->state.pending);
  saved->state.pending = a->state.current;
}
static DAWN_PROV_CODE void *dawn_prov_control_select(void *canonical) {
  dawn_prov_thread_state *state = dawn_prov_peek_state();
  if (!state || !state->active) return canonical;
  state->control_callback = 1;
  return dawn_prov_select(canonical);
}
static DAWN_PROV_CODE void dawn_prov_control_abandon(void *opaque, int explicit_discard) {
  dawn_prov_activation *a = opaque;
  for (dawn_prov_invocation *v = a->state.current; v && v != a->boundary; v = v->parent) {
    v->reclaiming = !explicit_discard;
    for (size_t i = 0; i < v->count; i++) {
      dawn_prov_scope *s = v->entries[i].scope;
      if (!explicit_discard && v->entries[i].logical_tip>s->unresumed) s->unresumed=v->entries[i].logical_tip;
      for (int64_t f = v->entries[i].tip; f && f != v->entries[i].recorded_parent; f = dawn_prov_record_at(s, f)->parent) {
        dawn_prov_record *r = dawn_prov_record_at(s, f);
        if (r->status == 0 || r->status == 3) r->status = explicit_discard ? 4 : 3;
      }
    }
  }
}
static DAWN_PROV_CODE void *dawn_prov_control_arm_enter(void *opaque) {
  dawn_prov_activation *a=opaque;
  void *previous=dawn_prov_control_capture();
  dawn_prov_thread_state *state=dawn_prov_context();
  dawn_prov_invocation_drop(state->pending);
  *state=a->arm_state; state->current=a->boundary; state->pending=a->state.current;
  if (state->pending) state->pending->refs++;
  state->control_callback=1;
  for (size_t i=0;i<a->arm_count;i++) {
    a->scopes[i]->current=a->arm_currents[i]; a->scopes[i]->recorded_current=a->arm_recorded_currents[i];
  }
  return previous;
}
static DAWN_PROV_CODE void dawn_prov_control_arm_leave(void *previous) {
  dawn_prov_control_attach(previous); dawn_prov_control_release(previous);
}
static const dawn_control_observer dawn_prov_control_hooks = {
  dawn_prov_control_capture, dawn_prov_control_release, dawn_prov_control_attach,
  dawn_prov_control_save, dawn_prov_control_relate, dawn_prov_control_select, dawn_prov_control_abandon,
  dawn_prov_control_arm_enter, dawn_prov_control_arm_leave
};

/* Boundary wrappers preserve the runtime ABI used by synchronous callbacks. */
DAWN_PROV_CODE int64_t dawn_prov_before(int64_t site, const char *metadata) { return dawn_prov_before_ctx(dawn_prov_context(), dawn_prov_site_index(site), metadata); }
DAWN_PROV_CODE int64_t dawn_prov_before_at(int64_t site, const char *metadata,
    int64_t callback_site, const char *callback_metadata) { return dawn_prov_before_at_ctx(dawn_prov_context(), dawn_prov_site_index(site), metadata, dawn_prov_site_index(callback_site), callback_metadata); }
DAWN_PROV_CODE int64_t dawn_prov_arrive(const char *definition) { return dawn_prov_arrive_ctx(dawn_prov_context(), dawn_prov_definition_index(definition), definition); }
DAWN_PROV_CODE void dawn_prov_finish(int64_t token, int normal) { dawn_prov_finish_ctx(dawn_prov_context(), token, normal); }
DAWN_PROV_CODE void dawn_prov_tail(int64_t site, const char *metadata) { dawn_prov_tail_ctx(dawn_prov_context(), dawn_prov_site_index(site), metadata); }
DAWN_PROV_CODE dawn_prov_function_guard dawn_prov_enter_function(const char *definition) { return dawn_prov_enter_function_ctx(dawn_prov_context(), dawn_prov_definition_index(definition), definition); }
