/* The one C++ translation unit in the runtime, wasm32-wasi only.
 *
 * The wasi failure landing (dawn_rt.c, "landing at a handler on
 * wasm32-wasi") throws a wasm exception to reach its handler, and something
 * has to catch it. Today's clang will not lower a catch written in C for
 * this target -- `-fexceptions` on a C TU crashes the wasm instruction
 * selector (landingpad IR meets a funclet-only isel; #309 probe) -- but the
 * C++ funclet path compiles fine, so the two catch sites in the runtime
 * (dawn_run_caught, dawn_bracket) both funnel through this one function.
 *
 * Compiled with -fno-rtti and no C++ standard library: a bare catch(...)
 * needs exactly two libc++abi entry points, and dawn_rt.c defines them as
 * identity stubs -- the failure payload travels in the runtime's own
 * in-flight slot, never in the exception object.
 *
 * Nothing else belongs here. The runtime is C11 with no dialect anywhere
 * else, and this file exists only for as long as clang cannot compile the
 * catch in C (the wasm EH semantics themselves were validated for C frames;
 * the block in dawn_rt.c records the upgrade path). */

extern "C" int dawn_wasi_try(void *(*body)(void *), void *ctx, void **out) {
  try {
    *out = body(ctx);
    return 0;
  } catch (...) {
    return 1;
  }
}
