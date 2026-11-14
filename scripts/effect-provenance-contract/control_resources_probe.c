/* Include generated source and runtime together to inspect ownership only.
 * This probe is separate from all timed product consumers. */
#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE 1
#define main resource_generated_main
#include "control_resources.c"
#undef main
#include "dawn_rt.c"
#include <assert.h>
static void resource_entry(void) {
  for(int mode=0;mode<4;mode++) for(int i=0;i<100;i++) {
    dawn_adt *stage=RESOURCE_MAKE(mode==1);
    assert(stage->tag==1);
    dawn_clo *ticket=dawn_dup(stage->fields[0].p);
    dawn_ctl *f=ticket->caps[0].p;
    dawn_prov_activation *a=f->observation; assert(a);
    if(mode==0) { dawn_adt *done=RESOURCE_FINISH(stage); assert(RESOURCE_VALUE(done)==42); dawn_drop(done); }
    else if(mode==1) assert(RESOURCE_FAIL(stage));
    else if(mode==2) { RESOURCE_STOP(stage); dawn_drop(stage); }
    else { dawn_drop(ticket); dawn_drop(stage); continue; }
    assert(!a->state.active && !a->state.current && !a->state.pending);
    assert(!a->arm_state.active && !a->arm_state.current && !a->arm_state.pending);
    assert(!a->boundary && !a->count && !a->scopes && !a->currents && !a->recorded_currents);
    dawn_drop(ticket);
  }
  assert(!dawn_ctl_live && !dawn_prov_registry && !dawn_prov_peek_state());
  puts("42 control resource normal panic discard natural drop");
}
int main(int argc,char **argv) { return dawn_rt_main(argc,argv,resource_entry); }
