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
  int64_t id, epoch, parent, site;
  const char *metadata, *definition;
  int status;
} dawn_prov_record;

typedef struct {
  int64_t ordinal, frame, boundary, note_boundary;
  int valid;
} dawn_prov_mark;

typedef struct dawn_prov_scope {
  int64_t id, epoch, next_instance, current;
  pthread_t owner;
  dawn_prov_record *records;
  size_t count, capacity;
  size_t *view, nview, view_capacity;
  dawn_prov_mark *marks;
  size_t nmarks, mark_capacity;
  size_t *mark_stack, nmark_stack, mark_stack_capacity;
  dawn_str **notes;
  size_t nnotes, note_capacity;
  struct dawn_prov_scope *outer, *registered;
} dawn_prov_scope;

typedef struct {
  dawn_prov_scope *scope;
  int64_t frame, parent;
} dawn_prov_entry;

typedef struct dawn_prov_invocation {
  int64_t token;
  int arrived;
  const char *metadata;
  int64_t site, callback_site;
  const char *callback_metadata;
  dawn_prov_entry *entries;
  size_t count;
  struct dawn_prov_invocation *parent;
} dawn_prov_invocation;

static _Atomic int64_t dawn_prov_next_scope = 1;
static _Atomic int64_t dawn_prov_next_token = 1;
static pthread_mutex_t dawn_prov_registry_lock = PTHREAD_MUTEX_INITIALIZER;
static dawn_prov_scope *dawn_prov_registry;
/* Optional observation must not shift the base runtime's static TLS data.
 * Plain execution never initializes this key or allocates its context. */
typedef struct {
  int enabled;
  dawn_prov_scope *active;
  dawn_prov_invocation *current;
} dawn_prov_thread_state;
static pthread_key_t dawn_prov_state_key;
static pthread_once_t dawn_prov_state_once = PTHREAD_ONCE_INIT;
static DAWN_PROV_CODE void dawn_prov_state_destroy(void *state) { dawn_free(state); }
static DAWN_PROV_CODE void dawn_prov_state_init(void) {
  if (pthread_key_create(&dawn_prov_state_key, dawn_prov_state_destroy)) abort();
}
static DAWN_PROV_CODE dawn_prov_thread_state *dawn_prov_peek_state(void) {
  return pthread_getspecific(dawn_prov_state_key);
}
static DAWN_PROV_CODE dawn_prov_thread_state *dawn_prov_state(void) {
  pthread_once(&dawn_prov_state_once, dawn_prov_state_init);
  dawn_prov_thread_state *state = pthread_getspecific(dawn_prov_state_key);
  if (!state) {
    state = calloc(1, sizeof(*state));
    if (!state || pthread_setspecific(dawn_prov_state_key, state)) abort();
  }
  return state;
}
#define dawn_prov_enabled (dawn_prov_state()->enabled)
#define dawn_prov_active (dawn_prov_state()->active)
#define dawn_prov_current (dawn_prov_state()->current)

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
  int foreign = s && !pthread_equal(s->owner, pthread_self());
  pthread_mutex_unlock(&dawn_prov_registry_lock);
  if (!s) dawn_prov_fail("provenance: scope has exited");
  if (foreign) dawn_prov_fail("provenance: different execution context");
  return s;
}

static DAWN_PROV_CODE dawn_prov_record *dawn_prov_record_at(dawn_prov_scope *s, int64_t id) {
  if (id < 1 || (size_t)id > s->count) return NULL;
  return &s->records[id - 1];
}

static DAWN_PROV_CODE int64_t dawn_prov_append(dawn_prov_scope *s, int64_t site, const char *metadata) {
  s->records = dawn_prov_grow(s->records, &s->capacity, s->count + 1, sizeof(*s->records));
  int64_t id = s->next_instance++;
  dawn_prov_record r = {id, s->epoch, s->current, site, metadata, "", 0};
  s->records[s->count++] = r;
  s->view = dawn_prov_grow(s->view, &s->view_capacity, s->nview + 1, sizeof(*s->view));
  s->view[s->nview++] = s->count - 1;
  s->current = id;
  return id;
}

DAWN_PROV_CODE int64_t dawn_prov_before(int64_t site, const char *metadata) {
  if (!dawn_prov_active) return 0;
  dawn_prov_invocation *v = calloc(1, sizeof(*v));
  if (!v) abort();
  v->token = atomic_fetch_add(&dawn_prov_next_token, 1);
  v->parent = dawn_prov_current;
  v->site = site;
  v->metadata = metadata;
  v->callback_site = site; v->callback_metadata = metadata;
  for (dawn_prov_scope *s = dawn_prov_active; s; s = s->outer) v->count++;
  v->entries = calloc(v->count, sizeof(*v->entries));
  if (!v->entries) abort();
  size_t i = 0;
  for (dawn_prov_scope *s = dawn_prov_active; s; s = s->outer) {
    int64_t parent = s->current;
    int64_t frame = dawn_prov_append(s, site, metadata);
    v->entries[i++] = (dawn_prov_entry){s, frame, parent};
  }
  dawn_prov_current = v;
  return v->token;
}

DAWN_PROV_CODE int64_t dawn_prov_before_at(int64_t site, const char *metadata,
    int64_t callback_site, const char *callback_metadata) {
  int64_t token = dawn_prov_before(site, metadata);
  if (token) {
    dawn_prov_current->callback_site = callback_site;
    dawn_prov_current->callback_metadata = callback_metadata;
  }
  return token;
}

DAWN_PROV_CODE int64_t dawn_prov_arrive(const char *definition) {
  if (!dawn_prov_active) return 0;
  int64_t created = 0;
  if (!dawn_prov_current || dawn_prov_current->arrived) {
    /* A missing source-bearing Core seam is explicitly unknown. Reusing
     * the surrounding written Site would invent a plausible call edge. */
    created = dawn_prov_before(0, "\t\t-1\t-1\t-1\t-1\tunknown\t");
  }
  dawn_prov_invocation *v = dawn_prov_current;
  v->arrived = 1;
  for (size_t i = 0; i < v->count; i++) {
    dawn_prov_record *r = dawn_prov_record_at(v->entries[i].scope, v->entries[i].frame);
    if (!r) dawn_prov_fail("provenance: missing active frame");
    r->definition = definition;
  }
  return created;
}

DAWN_PROV_CODE void dawn_prov_finish(int64_t token, int normal) {
  if (!token) return;
  dawn_prov_invocation *v = dawn_prov_current;
  if (!v || v->token != token) dawn_prov_fail("provenance: invocation closed out of order");
  for (size_t i = 0; i < v->count; i++) {
    dawn_prov_scope *s = v->entries[i].scope;
    dawn_prov_record *r = dawn_prov_record_at(s, v->entries[i].frame);
    if (!r || r->status) dawn_prov_fail("provenance: frame closed twice");
    r->status = normal ? 1 : 2;
    s->current = v->entries[i].parent;
    /* Frame completion invalidates its markers regardless of how it exits.
     * The frame status remains available to distinguish this from rewind. */
  }
  dawn_prov_current = v->parent;
  dawn_free(v->entries);
  dawn_free(v);
}

/* One lexical cleanup boundary replaces per-call unwind registrations.
 * Calls finish normally at their source seam. Exceptional exit closes only
 * invocations opened inside this activation, preserving the caller's token. */
DAWN_PROV_CODE dawn_prov_function_guard dawn_prov_enter_function(const char *definition) {
  int64_t token = dawn_prov_arrive(definition);
  dawn_prov_invocation *current = dawn_prov_current;
  return (dawn_prov_function_guard){token, current ? current->token : 0, 0};
}
DAWN_PROV_CODE void dawn_prov_function_cleanup(dawn_prov_function_guard *guard) {
  if (guard->normal) return;
  while (dawn_prov_current && dawn_prov_current->token != guard->boundary)
    dawn_prov_finish(dawn_prov_current->token, 0);
  if (guard->token) dawn_prov_finish(guard->token, 0);
}

DAWN_PROV_CODE void dawn_prov_cleanup(dawn_prov_guard *guard) {
  if (guard->token) dawn_prov_finish(guard->token, 0);
}

DAWN_PROV_CODE int64_t dawn_prov_open(void) {
  dawn_prov_scope *s = calloc(1, sizeof(*s));
  if (!s) abort();
  s->id = atomic_fetch_add(&dawn_prov_next_scope, 1);
  s->epoch = 1;
  s->next_instance = 1;
  s->owner = pthread_self();
  s->outer = dawn_prov_active;
  dawn_prov_append(s, 0, "");
  pthread_mutex_lock(&dawn_prov_registry_lock);
  s->registered = dawn_prov_registry;
  dawn_prov_registry = s;
  pthread_mutex_unlock(&dawn_prov_registry_lock);
  dawn_prov_active = s;
  dawn_prov_enabled = 1;
  return s->id;
}

DAWN_PROV_CODE void dawn_prov_close(int64_t id, int normal) {
  dawn_prov_scope *s = dawn_prov_scope_at(id);
  if (s != dawn_prov_active || s->current != 1)
    dawn_prov_fail("provenance: scope closed with active calls");
  s->records[0].status = normal ? 1 : 2;
  dawn_prov_active = s->outer;
  dawn_prov_enabled = dawn_prov_active != NULL;
  pthread_mutex_lock(&dawn_prov_registry_lock);
  dawn_prov_scope **slot = &dawn_prov_registry;
  while (*slot != s) slot = &(*slot)->registered;
  *slot = s->registered;
  pthread_mutex_unlock(&dawn_prov_registry_lock);
  for (size_t i = 0; i < s->nnotes; i++) dawn_drop(s->notes[i]);
  dawn_free(s->notes);
  dawn_free(s->marks);
  dawn_free(s->mark_stack);
  dawn_free(s->view);
  dawn_free(s->records);
  dawn_free(s);
  dawn_prov_thread_state *state = dawn_prov_peek_state();
  if (!state->active && !state->current) {
    if (pthread_setspecific(dawn_prov_state_key, NULL)) abort();
    dawn_free(state);
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
  s->marks[s->nmarks++] = (dawn_prov_mark){ordinal, s->current, (int64_t)s->nview, (int64_t)s->nnotes, 1};
  s->mark_stack = dawn_prov_grow(s->mark_stack, &s->mark_stack_capacity, s->nmark_stack + 1, sizeof(*s->mark_stack));
  s->mark_stack[s->nmark_stack++] = (size_t)ordinal - 1;
  dawn_prov_text b = {0};
  dawn_prov_text_add(&b, "%lld:%lld", (long long)id, (long long)ordinal);
  return dawn_prov_text_done(&b);
}

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
  dawn_prov_record *f = dawn_prov_record_at(s, c->frame);
  if (f && f->status) dawn_prov_fail("provenance: creating frame has finished");
  if (!c->valid || !f) dawn_prov_fail("provenance: checkpoint has been invalidated");
  if (s->current != c->frame) dawn_prov_fail("provenance: not in the creating frame");
  while (s->nmark_stack && s->mark_stack[s->nmark_stack - 1] != (size_t)ordinal - 1)
    s->marks[s->mark_stack[--s->nmark_stack]].valid = 0;
  s->nview = (size_t)c->boundary;
  while (s->nnotes > (size_t)c->note_boundary) dawn_drop(s->notes[--s->nnotes]);
  s->epoch++;
}

static DAWN_PROV_CODE void dawn_prov_write_record(dawn_prov_text *b, dawn_prov_scope *s, dawn_prov_record *r) {
  dawn_prov_text_add(b, "F\t%lld\t%lld\t%lld\t%lld\t%d\t%lld\t%s\t%s",
    (long long)s->id, (long long)r->epoch, (long long)r->id, (long long)r->parent,
    r->status, (long long)r->site, r->metadata, r->definition);
}

/* Immutable Origin inspection never consults a current scope or registry. */
typedef struct { const char *start; size_t length; } dawn_prov_span;
static DAWN_PROV_CODE dawn_prov_span dawn_prov_field_span(const dawn_str *origin, int64_t index) {
  const char *start = origin->p, *end = start + origin->len;
  if (origin->len < 2 || start[0] != 'O' || start[1] != '\t') dawn_prov_fail("provenance: invalid Origin");
  const char *header = memchr(start, '\n', (size_t)(end - start));
  if (!header) dawn_prov_fail("provenance: invalid Origin");
  if (index == -1) {
    const char *field = start;
    for (const char *p = start; p < header; p++) if (*p == '\t') field = p + 1;
    return (dawn_prov_span){field, (size_t)(header - field)};
  }
  if (index < 0) dawn_prov_fail("provenance: invalid Origin field index");
  start = header + 1;
  if (end - start < 2 || start[0] != 'F' || start[1] != '\t') dawn_prov_fail("provenance: invalid Origin");
  const char *line = memchr(start, '\n', (size_t)(end - start));
  if (line) end = line;
  for (int64_t i = 0; i < index; i++) {
    const char *tab = memchr(start, '\t', (size_t)(end - start));
    if (!tab) return (dawn_prov_span){end, 0};
    start = tab + 1;
  }
  const char *tab = memchr(start, '\t', (size_t)(end - start));
  if (tab) end = tab;
  return (dawn_prov_span){start, (size_t)(end - start)};
}
DAWN_PROV_CODE dawn_str *dawn_prov_field(dawn_str *origin, int64_t index) {
  dawn_prov_span span = dawn_prov_field_span(origin, index);
  /* Validate before allocating, so malformed input cannot strand an owned
   * result while a panic unwinds through this pure byte reader. */
  size_t length = span.length;
  for (size_t i = 0; i < span.length; i++) {
    if (span.start[i] != '%') continue;
    if (i + 2 >= span.length) dawn_prov_fail("provenance: invalid Origin");
    char a = span.start[i + 1], b = span.start[i + 2];
    if (!((a == '2' && b == '5') ||
          (a == '0' && (b == '9' || b == 'A' || b == 'D' || b == '0'))))
      dawn_prov_fail("provenance: invalid Origin");
    length -= 2; i += 2;
  }
  dawn_str *value = dawn_str_new((int64_t)length);
  char *out = dawn_str_data(value);
  size_t cursor = 0;
  for (size_t i = 0; i < span.length; i++) {
    char c = span.start[i];
    if (c == '%') {
      char a = span.start[i + 1], b = span.start[i + 2];
      c = a == '2' ? '%' : b == '9' ? '\t' : b == 'A' ? '\n' : b == 'D' ? '\r' : 0;
      i += 2;
    }
    out[cursor++] = c;
  }
  return value;
}

DAWN_PROV_CODE int64_t dawn_prov_number(dawn_str *origin, int64_t index) {
  dawn_prov_span span = dawn_prov_field_span(origin, index);
  if (!span.length) return -1;
  size_t i = span.start[0] == '-' ? 1 : 0;
  int negative = i != 0;
  if (i == span.length) dawn_prov_fail("provenance: invalid Origin");
  uint64_t value = 0, limit = negative ? UINT64_C(9223372036854775808) : INT64_MAX;
  for (; i < span.length; i++) {
    unsigned digit = (unsigned char)span.start[i] - '0';
    if (digit > 9 || value > (limit - digit) / 10) dawn_prov_fail("provenance: invalid Origin");
    value = value * 10 + digit;
  }
  if (negative && value == UINT64_C(9223372036854775808)) return INT64_MIN;
  return negative ? -(int64_t)value : (int64_t)value;
}
DAWN_PROV_CODE dawn_str *dawn_prov_parent(dawn_str *origin) {
  dawn_prov_field_span(origin, 0);
  const char *start = origin->p, *end = start + origin->len;
  const char *header = memchr(start, '\n', (size_t)(end - start));
  const char *next = memchr(header + 1, '\n', (size_t)(end - header - 1));
  if (!next || next + 1 == end) return dawn_str_new(0);
  size_t prefix = (size_t)(header - start) + 1;
  size_t suffix = (size_t)(end - next - 1);
  dawn_str *value = dawn_str_new((int64_t)(prefix + suffix));
  memcpy(dawn_str_data(value), start, prefix);
  memcpy(dawn_str_data(value) + prefix, next + 1, suffix);
  return value;
}

DAWN_PROV_CODE dawn_str *dawn_prov_origin(int64_t id) {
  dawn_prov_scope *s = dawn_prov_scope_at(id);
  dawn_prov_invocation *operation = dawn_prov_current;
  while (operation && !strstr(operation->metadata, "\tperform\t")) operation = operation->parent;
  if (!operation) dawn_prov_fail("provenance: no operation origin");
  int64_t sender = 0;
  for (size_t i = 0; i < operation->count; i++)
    if (operation->entries[i].scope == s) sender = operation->entries[i].frame;
  if (!sender) dawn_prov_fail("provenance: operation is outside the observation scope");
  dawn_prov_text b = {0};
  dawn_prov_text_add(&b, "O\t%lld\t%s", (long long)operation->site, operation->metadata);
  while (sender) {
    dawn_prov_record *r = dawn_prov_record_at(s, sender);
    if (!r) dawn_prov_fail("provenance: missing origin parent");
    dawn_prov_text_add(&b, "\n");
    if (sender == s->current) {
      dawn_prov_record envelope = *r;
      envelope.definition = "";
      dawn_prov_write_record(&b, s, &envelope);
    } else { dawn_prov_write_record(&b, s, r); }
    sender = r->parent;
  }
  return dawn_prov_text_done(&b);
}

DAWN_PROV_CODE void dawn_prov_note(int64_t id, dawn_str *origin) {
  dawn_prov_scope *s = dawn_prov_scope_at(id);
  s->notes = dawn_prov_grow(s->notes, &s->note_capacity, s->nnotes + 1, sizeof(*s->notes));
  s->notes[s->nnotes++] = dawn_dup(origin);
}

DAWN_PROV_CODE dawn_str *dawn_prov_completed(int64_t id) {
  dawn_prov_scope *s = dawn_prov_scope_at(id);
  dawn_prov_text b = {0};
  dawn_prov_text_add(&b, "S\t%lld\t%lld", (long long)s->id, (long long)s->epoch);
  for (size_t i = 0; i < s->nview; i++) {
    dawn_prov_text_add(&b, "\n");
    dawn_prov_write_record(&b, s, &s->records[s->view[i]]);
  }
  for (size_t i = 0; i < s->nnotes; i++) {
    dawn_prov_text_add(&b, "\n\n%.*s", (int)s->notes[i]->len, s->notes[i]->p);
  }
  return dawn_prov_text_done(&b);
}

DAWN_PROV_CODE void dawn_prov_unsupported(const char *boundary) {
  if (!dawn_prov_active) return;
  dawn_prov_text b = {0};
  dawn_prov_text_add(&b, "provenance: %s under observation is not supported in W2", boundary);
  dawn_panic(dawn_prov_text_done(&b));
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
    dawn_prov_unsupported("control operations");
  return dawn_prov_select(body->fn);
}

/* These adapters exist only around synchronous runtime callback operands.
 * They keep the canonical closure intact and own no source observation
 * capability. Their temporary owner checks scope and thread before dispatch. */
static DAWN_PROV_CODE void *dawn_prov_callback1(dawn_clo *proxy, void *a0) {
  dawn_prov_scope_at(proxy->caps[3].i);
  dawn_clo *body = proxy->caps[0].p;
  DAWN_CLEANUP(dawn_prov_cleanup) dawn_prov_guard guard = {
    dawn_prov_before(proxy->caps[1].i, proxy->caps[2].p)
  };
  void *result = ((void *(*)(dawn_clo *, void *))dawn_prov_select_closure(body))(body, a0);
  dawn_prov_finish(guard.token, 1); guard.token = 0;
  return result;
}
static DAWN_PROV_CODE void *dawn_prov_callback2(dawn_clo *proxy, void *a0, void *a1) {
  dawn_prov_scope_at(proxy->caps[3].i);
  dawn_clo *body = proxy->caps[0].p;
  DAWN_CLEANUP(dawn_prov_cleanup) dawn_prov_guard guard = {
    dawn_prov_before(proxy->caps[1].i, proxy->caps[2].p)
  };
  void *result = ((void *(*)(dawn_clo *, void *, void *))dawn_prov_select_closure(body))(body, a0, a1);
  dawn_prov_finish(guard.token, 1); guard.token = 0;
  return result;
}
DAWN_PROV_CODE dawn_clo *dawn_prov_wrap(dawn_clo *body, int arity, int64_t site, const char *metadata) {
  if (!dawn_prov_active) dawn_prov_fail("provenance: callback is outside observation");
  if (site < 0) {
    if (!dawn_prov_current) dawn_prov_fail("provenance: callback has no initiating invocation");
    site = dawn_prov_current->callback_site;
    metadata = dawn_prov_current->callback_metadata;
  }
  void *entry = arity == 1 ? (void *)dawn_prov_callback1 :
                arity == 2 ? (void *)dawn_prov_callback2 : NULL;
  if (!entry) dawn_prov_fail("provenance: unsupported runtime callback arity");
  dawn_clo *proxy = dawn_clo_new(entry, 4, 1);
  proxy->caps[0].p = dawn_dup(body);
  proxy->caps[1].i = site;
  proxy->caps[2].p = (void *)metadata;
  proxy->caps[3].i = dawn_prov_active->id;
  return proxy;
}

DAWN_PROV_CODE void *dawn_prov_observe(dawn_clo *body, void *evidence, int64_t site, const char *metadata) {
  DAWN_CLEANUP(dawn_prov_observer_cleanup) dawn_prov_observer_guard guard = {dawn_prov_open(), 0};
  guard.token = dawn_prov_before(site, metadata);
  void *result = ((void *(*)(dawn_clo *, void *, void *))dawn_prov_select_closure(body))(body, dawn_box_int(guard.scope), dawn_dup(evidence));
  dawn_prov_finish(guard.token, 1);
  dawn_prov_close(guard.scope, 1);
  guard.scope = 0;
  return result;
}
