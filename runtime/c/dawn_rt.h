/* The Phase -1 native runtime: the smallest thing the seam spike needs.
 *
 * See docs/native-backend-plan.md. This covers scalars, strings and stdout.
 * It does not free memory -- Perceus (Phase 4) is what makes that precise,
 * and a spike that guessed at a scheme now would only have to be undone.
 *
 * Compile generated code with -fwrapv (Dawn's Int wraps like the JVM's long)
 * and -fno-strict-aliasing. Both are load-bearing, not tuning. */
#ifndef DAWN_RT_H
#define DAWN_RT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Unit is a value, not an absence: keeping it uniform means Unit-returning
 * functions need no special case anywhere in the emitter. */
typedef unsigned char dawn_unit;
#define DAWN_UNIT ((dawn_unit)0)

/* UTF-8 bytes plus a length. Not NUL-terminated: the length is authoritative,
 * so slices can share a buffer and embedded NULs survive. Passed by value;
 * the two words are cheaper to copy than to chase. */
typedef struct {
  const char *p;
  int64_t len; /* bytes, not code points */
} dawn_str;

#define dawn_str_lit(s, n) ((dawn_str){(s), (int64_t)(n)})
#define dawn_str_empty ((dawn_str){"", 0})

/* One erased slot. Dawn boxes at type-variable positions and keeps concrete
 * positions native (llvm-backend-research.md 5.3); this union is what a
 * boxed slot looks like, and what an ADT field is stored in. Uniform for
 * now -- tagged pointers for small ints are a later optimisation. */
typedef union dawn_slot {
  int64_t i;
  double f;
  bool b;
  void *p;
  dawn_str s;
} dawn_slot;

/* Every ADT value, tuple included. `tag` is the constructor index, which is
 * exactly what CIsCtor tests -- the JVM backend uses class identity instead,
 * and that difference is confined to the two emitters. */
typedef struct {
  int32_t tag;
  int32_t nfields;
  dawn_slot fields[];
} dawn_adt;

dawn_adt *dawn_adt_new(int32_t tag, int32_t nfields);

/* A closure: a code pointer plus the captured environment. The JVM backend
 * gets this shape for free from invokedynamic and LambdaMetafactory; here it
 * is written out, which llvm-backend-research.md 3 called the biggest single
 * piece of native codegen. `fn` always points at the generated adapter, so
 * every call site is one indirect call regardless of capture count. */
typedef struct {
  void *fn;
  int32_t ncap;
  dawn_slot caps[];
} dawn_clo;

dawn_clo *dawn_clo_new(void *fn, int32_t ncap);

/* A trait dictionary: a flat table of function pointers in the trait's
 * declaration order. Dawn is dictionary-passing rather than monomorphising,
 * so this is the whole of generic dispatch -- llvm-backend-research.md 3
 * called it the cleanest part of native codegen, and it is. The JVM backend
 * uses an interface plus a singleton for the same thing.
 *
 * DAWN_DICT_MAX only bounds the static initialiser's shape; a dictionary is
 * never indexed beyond the slot count its trait declares. */
#define DAWN_DICT_MAX 16
typedef struct dawn_dict {
  int32_t nslots;
  void *slots[DAWN_DICT_MAX];
  /* A dictionary whose subject still mentions a type parameter is a function
   * of its arguments' dictionaries -- `Eq[Option[T]]` is not one relation but
   * a family, and which one is decided by the caller's `Eq[T]`. Those
   * arguments live here, and a slot body reads them back out of the
   * dictionary it is already handed. Zero for every dictionary the compiler
   * can build once, which is still nearly all of them. */
  int32_t nargs;
  struct dawn_dict *args[DAWN_DICT_MAX];
} dawn_dict;

/* Copy a static dictionary's slots and bind its arguments. Variadic in the
 * arguments so a call site emits one expression. */
dawn_dict *dawn_dict_new(const dawn_dict *tmpl, int32_t nargs, ...);

/* boxing: a type-variable slot holds a pointer to one of these */
dawn_slot *dawn_box_int(int64_t v);
dawn_slot *dawn_box_float(double v);
dawn_slot *dawn_box_bool(bool v);
dawn_slot *dawn_box_str(dawn_str v);

void dawn_rt_init(int argc, char **argv);

/* stdout */
dawn_unit dawn_print(dawn_str s);
dawn_unit dawn_println(dawn_str s);

/* strings */
dawn_str dawn_str_concat(dawn_str a, dawn_str b);
bool dawn_str_eq(dawn_str a, dawn_str b);
int64_t dawn_str_len(dawn_str s); /* code points, matching the JVM backend */
dawn_str dawn_str_of_int(int64_t v);
dawn_str dawn_str_of_float(double v);
dawn_str dawn_str_of_bool(bool v);
/* A String as it appears *inside* a rendered value: source-literal escaping
 * between double quotes. What the trait method `show` does at a String, so
 * that punctuation and content stay distinguishable. */
dawn_str dawn_str_quote(dawn_str s);

/* Unicode classification of one code point (the char_is_* intrinsics).
 *
 * Exact against the JVM backend for U+0000..U+007F. Above that the answer is a
 * Unicode derived-property lookup and this runtime has no table yet, so these
 * panic rather than guess: a wrong classification would differ from the JVM
 * silently, and a differential run comparing two backends would report ok. */
bool dawn_char_is_letter(int64_t c);
bool dawn_char_is_digit(int64_t c);
bool dawn_char_is_alnum(int64_t c);
bool dawn_char_is_upper(int64_t c);
bool dawn_char_is_lower(int64_t c);
bool dawn_char_is_space(int64_t c);

/* The prelude Hash and Ord over one scalar: what a `[T: Hash]` or `[T: Ord]`
 * bound instantiated at that scalar ends up calling.
 *
 * Both are observable -- a program can print `hash(x)` or `cmp(a, b)` -- so
 * these are not free choices. Each reproduces the JVM backend's answer bit
 * for bit; where that answer is surprising, the surprise is documented at the
 * definition rather than smoothed over here. */
int64_t dawn_hash_int(int64_t v);
int64_t dawn_hash_float(double v);
int64_t dawn_hash_bool(bool v);
int64_t dawn_hash_str(dawn_str s);
int64_t dawn_cmp_int(int64_t a, int64_t b);
int64_t dawn_cmp_float(double a, double b);
int64_t dawn_cmp_str(dawn_str a, dawn_str b);

/* arithmetic whose C behaviour would be undefined where the JVM's is not */
int64_t dawn_idiv(int64_t a, int64_t b);
int64_t dawn_imod(int64_t a, int64_t b);

/* control */
void dawn_panic(dawn_str msg);

#endif /* DAWN_RT_H */
