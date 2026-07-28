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
  dawn_unit u;
  void *p;
  dawn_str s;
} dawn_slot;

/* Dawn's `Bytes`: a byte array behind a pointer. Text is `dawn_str`; this is
 * what `bytes_utf8` produces and `std/bytes` walks. Separate because the two
 * are separate Dawn types, and conflating them here would let one be passed
 * where the other belongs without the C compiler saying so. */
typedef struct {
  const unsigned char *p;
  int64_t len;
} dawn_bytes;

/* Every ADT value, tuple included. `tag` is the constructor index, which is
 * exactly what CIsCtor tests -- the JVM backend uses class identity instead,
 * and that difference is confined to the two emitters. */
typedef struct {
  int32_t tag;
  int32_t nfields;
  dawn_slot fields[];
} dawn_adt;

dawn_adt *dawn_adt_new(int32_t tag, int32_t nfields);

/* The prelude ADTs the runtime itself has to build: `parse_int` and
 * `bytes_decode` return an Option, `catch_fault` a Result. A constructor's tag is
 * its index in the declaration order, and these four numbers are the one place
 * that order is written down outside the compiler -- emitc's test "the C
 * runtime's constructor tags are the prelude's" is the joint that keeps them
 * honest. A field at a type-variable position is boxed, here as on the JVM,
 * so each of these takes a slot pointer. */
#define DAWN_TAG_SOME 0
#define DAWN_TAG_NONE 1
#define DAWN_TAG_OK 0
#define DAWN_TAG_ERR 1

dawn_adt *dawn_some(void *boxed);
dawn_adt *dawn_none(void);

/* `Array[T]` -- the one collection primitive a backend owes the language
 * (native-backend-plan D1). std's List, Map and Set are all built on it, so
 * nothing collection-shaped compiles natively until this does.
 *
 * The contract has two halves (scripts/array-contract/README.md):
 *
 *   1. VALUE SEMANTICS. Every operation returns a new array and none is
 *      observably destructive. Two pushes onto the same version must each see
 *      their own element.
 *   2. `array_push` EXTENDS IN PLACE WHEN IT IS ALONE. Deliberately not
 *      observable from Dawn -- if it were, the semantics would not be pure --
 *      so it is measured with a clock instead: accumulation is O(n) with it
 *      and O(n^2) without, which at the contract's sizes is 10ms against a
 *      minute.
 *
 * A `dawn_array` is a length plus a shared buffer, and the buffer carries the
 * high-water mark of how many slots have ever been handed out. A push may
 * write slot `len` in place exactly when `len == buf->high`: that slot has
 * never belonged to any version, so no one can be reading it. Otherwise it
 * copies. This is the same rule the JVM backend enforces with a CAS on the
 * frontier slot; single-threaded C needs no atomic to state it.
 *
 * `array_with` always copies, and that asymmetry is the design rather than a
 * gap: slot `i < len` has already been handed to this version and maybe to
 * others, and there is no watermark that can say who still reads it. Perceus
 * will be able to say (`rc == 1`), and can lift this later. */
/* Elements are erased, so an Array holds boxed slots by pointer -- the same
 * shape the JVM backend gets from an Object[]. `array_get` therefore hands
 * back what `CUnbox` expects to dereference, and `array_push` takes what
 * `CBox` just produced. */
typedef struct {
  void **data;
  int32_t cap;
  int32_t high; /* slots ever handed out; only push may raise it */
} dawn_array_buf;

typedef struct {
  dawn_array_buf *buf;
  int32_t len;
} dawn_array;

dawn_array *dawn_array_new(void);
int64_t dawn_array_len(const dawn_array *a);
void *dawn_array_get(const dawn_array *a, int64_t i);
dawn_array *dawn_array_push(dawn_array *a, void *x);
dawn_array *dawn_array_with(const dawn_array *a, int64_t i, void *x);

/* The one bit-twiddle std/hamt needs that C does not portably spell. */
int64_t dawn_popcount(int64_t n);

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
dawn_slot *dawn_box_unit(dawn_unit v);
dawn_slot *dawn_box_str(dawn_str v);

void dawn_rt_init(int argc, char **argv);

/* ---- the runtime-intrinsic contract ------------------------------------
 *
 * Everything from here to `dawn_panic` implements a primitive the intrinsic
 * table says a runtime module owns, and each is named `dawn_` plus the
 * intrinsic's own name. That is not a convention the emitter can be talked
 * out of: it emits the call from the table, so a primitive whose C function
 * is missing or misspelled fails to link, and one that is added here needs no
 * emitter change at all (docs/runtime-intrinsics-design.md 4). */

/* io */
dawn_unit dawn_io_print(dawn_str s);
dawn_unit dawn_io_println(dawn_str s);
dawn_unit dawn_io_eprint(dawn_str s);
dawn_unit dawn_io_eprintln(dawn_str s);
dawn_adt *dawn_io_read_line(void); /* Option[String]; None at EOF */
bool dawn_io_is_dir(dawn_str path);
bool dawn_io_exists(dawn_str path);
dawn_unit dawn_io_mkdirs(dawn_str path); /* panics on failure */
dawn_unit dawn_io_exit(int64_t code);    /* returns a Unit it never delivers */
dawn_str dawn_io_read_file(dawn_str path);      /* panics on failure */
dawn_unit dawn_io_write_file(dawn_str path, dawn_str content);
dawn_array *dawn_io_list_names(dawn_str path);  /* boxed dawn_str elements */
dawn_str dawn_io_cwd(void);
dawn_adt *dawn_io_getenv(dawn_str name); /* Option[String] */
dawn_bytes *dawn_io_read_bytes(dawn_str path);
dawn_unit dawn_io_write_bytes(dawn_str path, const dawn_bytes *content);
bool dawn_io_delete(dawn_str path); /* false when there was nothing to delete */
dawn_unit dawn_io_rename(dawn_str src, dawn_str dst); /* rename(2): atomic or panic */
dawn_str dawn_io_temp_dir(dawn_str parent, dawn_str prefix); /* "" parent = $TMPDIR */
bool dawn_io_is_symlink(dawn_str path);
dawn_bytes *dawn_io_read_stdin(int64_t n); /* short only at end of input */
/* argv holds boxed dawn_str; an empty path inherits this process's stream */
int64_t dawn_io_run(dawn_array *argv, dawn_str out_path, dawn_str err_path);
dawn_array *dawn_args(void);

/* `f` returns an erased slot, so one cast serves whatever `T` is -- the same
 * reason the JVM hands these an `Fn0` whose `apply` returns `Object`.
 *
 * The JVM catches an exception; native has no exceptions, so these catch a
 * panic, which is the one failure mechanism there is. The consequence is
 * visible: the `Err` payload is the panic message rather than a Java
 * exception's `toString`, so a program that prints it prints different text
 * on the two backends. Everything that only branches on Ok/Err agrees. */
dawn_adt *dawn_catch_fault(dawn_clo *f);
dawn_adt *dawn_catch_panic(dawn_clo *f);

/* Simple (1:1) Unicode case mapping: a code point in `lo..hi` maps to itself
 * plus `delta`, and one in no range maps to itself.
 *
 * Defined by the *generated program*, not by this runtime, because the table
 * belongs to the compiler (selfhost/src/case_table.dawn) and the JVM backend
 * receives the same rows in dawn/rt/Strings. It lived here as a generated
 * header until 2026-07-28, which made it one mapping only while the JDK that
 * generated it was the JDK the JVM backend happened to be running -- Unicode
 * 15 and 16 differ by 18 code points, and nothing said so. `dawn __emitc`
 * always emits these, so the runtime is linked against a program that has
 * them. */
typedef struct {
  int32_t lo;
  int32_t hi;
  int32_t delta;
} dawn_case_range;

extern const dawn_case_range dawn_upper_ranges[];
extern const int64_t dawn_upper_ranges_n;
extern const dawn_case_range dawn_lower_ranges[];
extern const int64_t dawn_lower_ranges_n;

/* Unicode classification, as the ranges each predicate holds at. Defined by
 * the generated program for the same reason as the case table above. */
typedef struct {
  int32_t lo;
  int32_t hi;
} dawn_cp_range;

extern const dawn_cp_range dawn_letter_ranges[];
extern const int64_t dawn_letter_ranges_n;
extern const dawn_cp_range dawn_digit_ranges[];
extern const int64_t dawn_digit_ranges_n;
extern const dawn_cp_range dawn_upper_class_ranges[];
extern const int64_t dawn_upper_class_ranges_n;
extern const dawn_cp_range dawn_lower_class_ranges[];
extern const int64_t dawn_lower_class_ranges_n;
extern const dawn_cp_range dawn_space_ranges[];
extern const int64_t dawn_space_ranges_n;

/* strings */
dawn_str dawn_str_concat(dawn_str a, dawn_str b);
bool dawn_str_eq(dawn_str a, dawn_str b);
dawn_str dawn_str_lower(dawn_str s);
dawn_str dawn_str_upper(dawn_str s);
/* code-point indices, -1 when absent: the wrappers in std/str turn the
 * sentinel into None, and the index is observable, so it is not the byte
 * offset the search actually ran on. */
dawn_adt *dawn_parse_int(dawn_str s);                    /* Option[Int] */
dawn_adt *dawn_parse_float(dawn_str s);                  /* Option[Float] */
dawn_adt *dawn_parse_int_radix(dawn_str s, int64_t radix);
dawn_array *dawn_code_points(dawn_str s);                /* boxed Int elements */
dawn_str dawn_from_code_points(dawn_array *cps);
dawn_str dawn_join(dawn_array *parts, dawn_str sep);

/* Cursors. A position is a byte offset into the UTF-8 here and a UTF-16 index
 * on the JVM, and neither is observable: `Cursor` is opaque outside
 * std/cursor, so nothing can print one or do arithmetic on one. What is
 * observable -- the order, and what `slice` returns -- agrees.
 *
 * `cursor_slice` panics on a range that is out of bounds or lands inside a
 * character. The JVM's returns a sentinel and its emitter raises the panic;
 * that split is why this one is not in the intrinsic table. */
int64_t dawn_cursor_start(dawn_str s);
int64_t dawn_cursor_end(dawn_str s);
bool dawn_cursor_done(dawn_str s, int64_t c);
int64_t dawn_cursor_char(dawn_str s, int64_t c); /* -1 at the end */
int64_t dawn_cursor_next(dawn_str s, int64_t c);
int64_t dawn_cursor_prev(dawn_str s, int64_t c);
dawn_str dawn_cursor_slice(dawn_str s, int64_t from, int64_t to);

/* bytes. `concat` and `eq` are not intrinsics -- they are what `++` and `==`
 * at Bytes compile to, the way dawn_str_concat and dawn_str_eq are for text. */
dawn_bytes *dawn_bytes_concat(const dawn_bytes *a, const dawn_bytes *b);
bool dawn_bytes_eq(const dawn_bytes *a, const dawn_bytes *b);
dawn_bytes *dawn_bytes_utf8(dawn_str s);
int64_t dawn_bytes_len(const dawn_bytes *b);
int64_t dawn_bytes_at(const dawn_bytes *b, int64_t i); /* 0..255, -1 out of range */
dawn_bytes *dawn_bytes_slice(const dawn_bytes *b, int64_t from, int64_t to);
/* The one way to make bytes that did not come from text. Elements are boxed
 * (the array is erased) and truncated to a byte. */
dawn_bytes *dawn_bytes_from_array(const dawn_array *a);
/* Option[String]; None only for a charset this runtime cannot decode, which
 * is what the JVM's UnsupportedEncodingException arm means. Malformed input
 * is replaced rather than refused, as `new String(bytes, charset)` does. */
dawn_adt *dawn_bytes_decode(const dawn_bytes *b, dawn_str charset);
dawn_str dawn_str_of_int(int64_t v);
dawn_str dawn_str_of_float(double v);
dawn_str dawn_str_of_bool(bool v);
/* A String as it appears *inside* a rendered value: source-literal escaping
 * between double quotes. What the trait method `show` does at a String, so
 * that punctuation and content stay distinguishable. */
dawn_str dawn_str_quote(dawn_str s);

/* Unicode classification of one code point (the char_is_* intrinsics), out of
 * the tables above. Exact against the JVM backend everywhere, because both
 * read the same rows.
 *
 * These classified ASCII and panicked above U+007F until 2026-07-28, on the
 * grounds that a wrong answer would differ from the JVM silently while a panic
 * would not. That was the right call while the JVM's answer came from the
 * running JDK -- there was nothing to copy that would stay copied. */
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
int64_t dawn_hash_bytes(const dawn_bytes *b);
int64_t dawn_cmp_int(int64_t a, int64_t b);
int64_t dawn_cmp_float(double a, double b);
int64_t dawn_cmp_str(dawn_str a, dawn_str b);

/* arithmetic whose C behaviour would be undefined where the JVM's is not */
int64_t dawn_idiv(int64_t a, int64_t b);
int64_t dawn_imod(int64_t a, int64_t b);

/* Control. The two failure kinds, and the difference is which barrier stops
 * one: `catch_fault` takes a fault (the outside world said no) and lets a panic
 * past, `catch_panic` takes both. The JVM gets the same split from `Error` vs
 * `Exception`; here it is a flag on the handler. Everything in this file
 * raises a fault only where an io primitive failed -- a bad index or a bad
 * argument is the language's own failure and panics. */
void dawn_panic(dawn_str msg);
void dawn_fault(dawn_str msg);

#endif /* DAWN_RT_H */
