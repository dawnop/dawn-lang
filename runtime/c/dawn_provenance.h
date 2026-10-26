/* Observation owns its records independently of C activation storage. The
 * invocation channel is separate from effect evidence and exists only in
 * programs that contain observation. Callers finish evaluating operands
 * before opening a record; cleanup closes an interrupted invocation. */
#ifndef DAWN_PROVENANCE_H
#define DAWN_PROVENANCE_H
#include "dawn_rt.h"

/* A distinct output section keeps observation code out of ordinary text.
 * A .text.unlikely subsection is merged before Plain code by common linkers
 * and would still perturb its instruction-cache placement. */
#if defined(__GNUC__) || defined(__clang__)
#define DAWN_PROV_CODE __attribute__((section("dawn_observed")))
#define DAWN_PROV_ENTRY __attribute__((aligned(64)))
#else
#define DAWN_PROV_CODE
#define DAWN_PROV_ENTRY
#endif

typedef struct dawn_prov_guard {
  int64_t token;
} dawn_prov_guard;

/* Canonical addresses are semantic keys. The cold index rejects duplicate
 * keys, and observed dispatch uses a binary search rather than a linear walk. */
typedef struct { int64_t id; const char *metadata; } dawn_prov_site;
extern const dawn_prov_site dawn_prov_sites[];
extern const size_t dawn_prov_sites_n;

typedef struct { void *canonical, *observed; } dawn_prov_target;
extern const dawn_prov_target dawn_prov_entries[];
extern const size_t dawn_prov_entries_n;
void *dawn_prov_select(void *canonical);
void *dawn_prov_select_closure(dawn_clo *body);
dawn_clo *dawn_prov_wrap(dawn_clo *body, int arity, int64_t site, const char *metadata);

typedef struct dawn_prov_function_guard {
  int64_t token, boundary;
  int normal;
} dawn_prov_function_guard;
dawn_prov_function_guard dawn_prov_enter_function(const char *definition);
void dawn_prov_function_cleanup(dawn_prov_function_guard *guard);
#define DAWN_PROV_ARRIVE(d) dawn_prov_arrive(d)
#define DAWN_PROV_BEFORE(s, m, c, cm) dawn_prov_before_at((s), (m), (c), (cm))
#define DAWN_PROV_RESULT(e) ({ __auto_type dawn_prov_result_ = (e); dawn_prov_callback.normal = 1; if (dawn_prov_callback.token) { dawn_prov_finish(dawn_prov_callback.token, 1); dawn_prov_callback.token = 0; } dawn_prov_result_; })

void *dawn_prov_observe(dawn_clo *body, void *evidence, int64_t site, const char *metadata);
int64_t dawn_prov_before(int64_t site, const char *metadata);
int64_t dawn_prov_before_at(int64_t site, const char *metadata, int64_t callback_site, const char *callback_metadata);
int64_t dawn_prov_arrive(const char *definition);
void dawn_prov_finish(int64_t token, int normal);
void dawn_prov_cleanup(dawn_prov_guard *guard);
int64_t dawn_prov_open(void);
void dawn_prov_close(int64_t scope, int normal);
dawn_str *dawn_prov_checkpoint(int64_t scope);
void dawn_prov_rewind(int64_t scope, dawn_str *checkpoint);
dawn_str *dawn_prov_origin(int64_t scope);
dawn_str *dawn_prov_field(dawn_str *origin, int64_t index);
int64_t dawn_prov_number(dawn_str *origin, int64_t index);
dawn_str *dawn_prov_parent(dawn_str *origin);
void dawn_prov_note(int64_t scope, dawn_str *origin);
dawn_str *dawn_prov_completed(int64_t scope);
void dawn_prov_unsupported(const char *boundary);

#endif
