/* Adverse frozen producers stay outside the public command line consumer. */
#define main public_preview_generated_main
#include "public_preview.c"
#undef main
#include <assert.h>
#include "preview_control_producer.h"
static void public_preview_entry(void) {
  const char *modes[]={"truncated","unknown","uncommitted"};
  const char *expected[]={"truncated provenance","unknown boundary","uncommitted origin"};
  for(int i=0;i<3;i++) {
    dawn_adt *snapshot=preview_control_produce(modes[i]);
    dawn_str *message=dawn_main__check(snapshot,DAWN_LIT("good"));
    assert(strstr(message->p,expected[i]));dawn_drop(message);
    printf("42 CLI %s rejected\n",modes[i]);
  }
}
int main(int argc,char **argv) { return dawn_rt_main(argc,argv,public_preview_entry); }
