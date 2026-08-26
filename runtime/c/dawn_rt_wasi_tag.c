/* The wasm exception tag this runtime throws through, defined here and
 * nowhere else. wasm32-wasi only; empty on every other target.
 *
 * dawn_rt.c's raise reaches its handler with __builtin_wasm_throw(0, ...)
 * and dawn_rt_wasi_eh.cc catches it. Tag 0 is the C++ exception tag, so both
 * sides reference the symbol __cpp_exception. Through LLVM 21 the backend
 * emitted a weak definition of it into every object file that mentioned it,
 * and the link needed nothing else. LLVM 22 stopped: the tag is an
 * undefined reference now, defined once by the runtime libraries
 * (llvm-project#159143, then #160959 and #185770 moved it to libunwind).
 *
 * Upstream's answer is -lunwind, which exists only in wasi-sdk 33 and newer
 * sysroots. This runtime defines the tag itself instead, so one link line
 * works across every wasi-sdk from 25 to 34 and pulls in no unwinder the
 * runtime never calls. The three lines below are a copy of libunwind's own
 * definition, which is this same inline assembly.
 *
 * It must be its own translation unit. On LLVM 21 and earlier the backend
 * still emits its weak definition into any object file that throws or
 * catches, and a strong definition in the same unit is an assembler error
 * ("symbol '__cpp_exception' is already defined"). A unit that neither
 * throws nor catches never gets the weak one, so this file is the only
 * place the definition can sit and still link on both sides of LLVM 22. */

#ifdef __wasi__
__asm__(
  "  .tagtype __cpp_exception i32\n"
  "  .globl __cpp_exception\n"
  "__cpp_exception:\n"
);
#endif
