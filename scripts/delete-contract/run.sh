#!/usr/bin/env bash
# The public delete contract, plus live mutants for the regressions that
# created LIB-07. Each mutant must compile and run; only its behavior may fail.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/delete-contract"
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

prepare_cwd() { # directory
  mkdir -p "$1"
  printf 'target\n' > "$1/delete-contract-nul-symlink-target"
  ln -s delete-contract-nul-symlink-target "$1/delete-contract-nul-symlink"
}

check_exact() { # label, output
  if ! cmp -s "$here/expected.txt" "$2"; then
    diff -u "$here/expected.txt" "$2" >&2 || true
    fail "$1 delete behavior differs from the contract"
  fi
  echo "PASS  $1 delete behavior"
}

expect_mutant_red() { # label, output
  if cmp -s "$here/expected.txt" "$2"; then
    fail "$1 mutant stayed green"
  fi
  if ! grep -qx 'nonempty = NotFound' "$2"; then
    cat "$2" >&2
    fail "$1 mutant missed the non-empty-directory boundary"
  fi
  echo "PASS  $1 mutant compiles, runs, and turns the contract red"
}

expect_nul_mutant_red() { # label, output
  if cmp -s "$here/expected.txt" "$2"; then
    fail "$1 mutant stayed green"
  fi
  if ! grep -qx 'nul = Deleted' "$2" ||
      ! grep -qx 'nul prefix remains = false' "$2"; then
    cat "$2" >&2
    fail "$1 mutant missed the embedded-NUL target boundary"
  fi
  echo "PASS  $1 mutant compiles, runs, and turns the NUL boundary red"
}

expect_query_mutant_red() { # label, query label, output
  if cmp -s "$here/expected.txt" "$3"; then
    fail "$1 mutant stayed green"
  fi
  if ! grep -qx "$2 = Fault" "$3"; then
    cat "$3" >&2
    fail "$1 mutant missed the Bool-query NUL boundary"
  fi
  echo "PASS  $1 mutant compiles, runs, and turns the query contract red"
}

expect_getenv_mutant_red() { # label, output
  if cmp -s "$here/expected.txt" "$2"; then
    fail "$1 mutant stayed green"
  fi
  if ! grep -qx 'nul getenv = Fault' "$2"; then
    cat "$2" >&2
    fail "$1 mutant missed the Option-query NUL boundary"
  fi
  echo "PASS  $1 mutant compiles, runs, and turns the getenv contract red"
}

expect_preflight_mutant_red() { # label, output
  if cmp -s "$here/expected.txt" "$2"; then
    fail "$1 mutant stayed green"
  fi
  if grep -qx 'empty path = io.invalid_delete_path: io.delete: path must not be empty' "$2" &&
      grep -qx "trailing slash = io.invalid_delete_path: io.delete: path must not end with '/'" "$2" &&
      grep -qx 'empty target remains = true' "$2" &&
      grep -qx 'trailing target remains = true' "$2"; then
    cat "$2" >&2
    fail "$1 mutant did not cross either preflight boundary"
  fi
  echo "PASS  $1 mutant compiles, runs, and turns the preflight boundary red"
}

"$root/bin/dawn" --version > /dev/null

prepare_cwd "$work/jvm-cwd"
if ! (cd "$work/jvm-cwd" &&
    "$root/bin/dawn" run --std "$root/std" "$here/probe.dawn") \
    > "$work/jvm.out" 2> "$work/jvm.err"; then
  cat "$work/jvm.err" >&2
  fail "JVM delete probe did not compile and run"
fi
check_exact JVM "$work/jvm.out"

if ! "$root/bin/dawn" __emitc --std "$root/std" "$here/probe.dawn" \
    -o "$work/probe.c" > "$work/emitc.out" 2>&1; then
  cat "$work/emitc.out" >&2
  fail "native delete probe did not emit C"
fi
if ! "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -Wall -Wextra -Werror -Wno-unused-variable -Wno-unused-but-set-variable \
    -Wno-unused-parameter -Wno-unused-label -I "$root/runtime/c" \
    -o "$work/probe" "$work/probe.c" "$root/runtime/c/dawn_rt.c" -lm \
    > "$work/cc.out" 2>&1; then
  cat "$work/cc.out" >&2
  fail "native delete probe did not compile"
fi
prepare_cwd "$work/native-cwd"
if ! (cd "$work/native-cwd" && "$work/probe") \
    > "$work/native.out" 2> "$work/native.err"; then
  cat "$work/native.err" >&2
  fail "native delete probe did not run"
fi
check_exact native "$work/native.out"
cmp -s "$work/jvm.out" "$work/native.out" || fail "JVM and native delete outputs differ"

# C path-bridge mutant: remove the embedded-NUL rejection. The old bridge
# silently terminates at the first zero byte, so delete acts on the prefix.
mkdir -p "$work/cpath-mutant"
cp "$root/runtime/c/dawn_rt.c" "$root/runtime/c/dawn_rt.h" "$work/cpath-mutant/"
python3 - "$work/cpath-mutant/dawn_rt.c" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
old = '''static char *dawn_cpath(dawn_str *s) {
  if (dawn_has_nul(s)) {
    dawn_fault(DAWN_LIT("path contains an embedded NUL byte"));
  }
  char *p = (char *)dawn_alloc((size_t)s->len + 1);'''
new = '''static char *dawn_cpath(dawn_str *s) {
  char *p = (char *)dawn_alloc((size_t)s->len + 1);'''
if text.count(old) != 1:
    raise SystemExit("C path mutation anchor is not unique")
path.write_text(text.replace(old, new))
PY
if ! "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -Wall -Wextra -Werror -Wno-unused-variable -Wno-unused-but-set-variable \
    -Wno-unused-parameter -Wno-unused-label -I "$work/cpath-mutant" \
    -o "$work/cpath-mutant/probe" "$work/probe.c" "$work/cpath-mutant/dawn_rt.c" -lm \
    > "$work/cpath-mutant/cc.out" 2>&1; then
  cat "$work/cpath-mutant/cc.out" >&2
  fail "C embedded-NUL mutant did not compile"
fi
prepare_cwd "$work/cpath-mutant/cwd"
if ! (cd "$work/cpath-mutant/cwd" && "$work/cpath-mutant/probe") \
    > "$work/cpath-mutant/out" 2> "$work/cpath-mutant/err"; then
  cat "$work/cpath-mutant/err" >&2
  fail "C embedded-NUL mutant did not run"
fi
expect_nul_mutant_red "C embedded-NUL truncation" "$work/cpath-mutant/out"

# C Bool-query mutants remove one preflight at a time. The shared cpath guard
# stays fail-closed, so the probe catches the resulting fault and keeps running.
for query_case in \
    "dawn_io_exists|nul exists" \
    "dawn_io_is_dir|nul is_dir" \
    "dawn_io_is_symlink|nul is_symlink"; do
  IFS='|' read -r query_fn query_label <<< "$query_case"
  query_name="${query_fn#dawn_io_}"
  query_dir="$work/c-query-$query_name-mutant"
  mkdir -p "$query_dir"
  cp "$root/runtime/c/dawn_rt.c" "$root/runtime/c/dawn_rt.h" "$query_dir/"
  python3 - "$query_dir/dawn_rt.c" "$query_fn" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
function = sys.argv[2]
text = path.read_text()
old = f'''bool {function}(dawn_str *path) {{
  if (dawn_has_nul(path)) return false;
  char *p = dawn_cpath(path);'''
new = f'''bool {function}(dawn_str *path) {{
  char *p = dawn_cpath(path);'''
if text.count(old) != 1:
    raise SystemExit(f"C {function} NUL-guard mutation anchor is not unique")
path.write_text(text.replace(old, new))
PY
  if ! "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
      -Wall -Wextra -Werror -Wno-unused-variable -Wno-unused-but-set-variable \
      -Wno-unused-parameter -Wno-unused-label -I "$query_dir" \
      -o "$query_dir/probe" "$work/probe.c" "$query_dir/dawn_rt.c" -lm \
      > "$query_dir/cc.out" 2>&1; then
    cat "$query_dir/cc.out" >&2
    fail "C $query_name NUL-query mutant did not compile"
  fi
  prepare_cwd "$query_dir/cwd"
  if ! (cd "$query_dir/cwd" && "$query_dir/probe") \
      > "$query_dir/out" 2> "$query_dir/err"; then
    cat "$query_dir/err" >&2
    fail "C $query_name NUL-query mutant did not run"
  fi
  expect_query_mutant_red "C $query_name NUL-query" "$query_label" "$query_dir/out"
done

# C Option-query mutant: remove getenv's NUL preflight. The shared bridge must
# then fault rather than truncate, and catch_fault keeps the mutant executable
# alive long enough for the same public contract to observe the wrong result.
mkdir -p "$work/c-getenv-mutant"
cp "$root/runtime/c/dawn_rt.c" "$root/runtime/c/dawn_rt.h" "$work/c-getenv-mutant/"
python3 - "$work/c-getenv-mutant/dawn_rt.c" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
old = '''dawn_adt *dawn_io_getenv(dawn_str *name) {
  if (dawn_has_nul(name)) return dawn_none();
  char *p = dawn_cpath(name);'''
new = '''dawn_adt *dawn_io_getenv(dawn_str *name) {
  char *p = dawn_cpath(name);'''
if text.count(old) != 1:
    raise SystemExit("C getenv NUL-guard mutation anchor is not unique")
path.write_text(text.replace(old, new))
PY
if ! "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -Wall -Wextra -Werror -Wno-unused-variable -Wno-unused-but-set-variable \
    -Wno-unused-parameter -Wno-unused-label -I "$work/c-getenv-mutant" \
    -o "$work/c-getenv-mutant/probe" "$work/probe.c" \
    "$work/c-getenv-mutant/dawn_rt.c" -lm \
    > "$work/c-getenv-mutant/cc.out" 2>&1; then
  cat "$work/c-getenv-mutant/cc.out" >&2
  fail "C getenv NUL-query mutant did not compile"
fi
prepare_cwd "$work/c-getenv-mutant/cwd"
if ! (cd "$work/c-getenv-mutant/cwd" && "$work/c-getenv-mutant/probe") \
    > "$work/c-getenv-mutant/out" 2> "$work/c-getenv-mutant/err"; then
  cat "$work/c-getenv-mutant/err" >&2
  fail "C getenv NUL-query mutant did not run"
fi
expect_getenv_mutant_red "C getenv NUL-query" "$work/c-getenv-mutant/out"

# C mutant: restore the old collapse where every remove(3) failure returned
# false. The exact replacement only prepares the executable; the verdict above
# is read from the process output, never from this source text.
mkdir -p "$work/c-mutant"
cp "$root/runtime/c/dawn_rt.c" "$root/runtime/c/dawn_rt.h" "$work/c-mutant/"
python3 - "$work/c-mutant/dawn_rt.c" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
old = '''bool dawn_io_delete(dawn_str *path) {
  char *p = dawn_cpath(path);
  int rc = remove(p);
  int saved_errno = errno;
  free(p);
  if (rc == 0) return true;
  if (saved_errno == ENOENT) return false;
  dawn_fault(DAWN_LIT("io_delete: cannot delete path"));
  return false;
}'''
new = '''bool dawn_io_delete(dawn_str *path) {
  char *p = dawn_cpath(path);
  bool gone = remove(p) == 0;
  free(p);
  return gone;
}'''
if text.count(old) != 1:
    raise SystemExit("C delete mutation anchor is not unique")
path.write_text(text.replace(old, new))
PY
if ! "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -Wall -Wextra -Werror -Wno-unused-variable -Wno-unused-but-set-variable \
    -Wno-unused-parameter -Wno-unused-label -I "$work/c-mutant" \
    -o "$work/c-mutant/probe" "$work/probe.c" "$work/c-mutant/dawn_rt.c" -lm \
    > "$work/c-mutant/cc.out" 2>&1; then
  cat "$work/c-mutant/cc.out" >&2
  fail "C collapse mutant did not compile"
fi
prepare_cwd "$work/c-mutant/cwd"
if ! (cd "$work/c-mutant/cwd" && "$work/c-mutant/probe") \
    > "$work/c-mutant/out" 2> "$work/c-mutant/err"; then
  cat "$work/c-mutant/err" >&2
  fail "C collapse mutant did not run"
fi
expect_mutant_red "C all-failures-false" "$work/c-mutant/out"

# JVM mutant: restore File.delete in the compiler's runtime generator. Build a
# runnable compiler from the mutated Dawn source, then let that compiler build
# and execute the same probe so the generated dawn/rt/Io is what is exercised.
mkdir -p "$work/jvm-mutant"
cp -R "$root/selfhost" "$work/jvm-mutant/selfhost"
cp -R "$root/packages" "$work/jvm-mutant/packages"
python3 - "$work/jvm-mutant/selfhost/src/jvm/rtclasses.dawn" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
old = '''  push_path(dv, 0)
  dv.visitMethodInsn(OP_INVOKESTATIC, "java/nio/file/Files", "deleteIfExists",
    "(Ljava/nio/file/Path;)Z", false)'''
new = '''  dv.visitTypeInsn(OP_NEW, "java/io/File")
  dv.visitInsn(OP_DUP)
  dv.visitVarInsn(OP_ALOAD, 0)
  dv.visitMethodInsn(OP_INVOKESPECIAL, "java/io/File", "<init>", "(Ljava/lang/String;)V", false)
  dv.visitMethodInsn(OP_INVOKEVIRTUAL, "java/io/File", "delete", "()Z", false)'''
if text.count(old) != 1:
    raise SystemExit("JVM delete mutation anchor is not unique")
path.write_text(text.replace(old, new))
PY
if ! java -Xss512m -Xmx2g -jar "$root/build/dawn-selfhost.jar" build \
    "$work/jvm-mutant/selfhost" -o "$work/jvm-mutant/compiler.jar" \
    --std "$root/std" --vendor org/objectweb/asm --vendor coursierapi \
    > "$work/jvm-mutant/build.out" 2>&1; then
  cat "$work/jvm-mutant/build.out" >&2
  fail "JVM File.delete mutant compiler did not build"
fi
prepare_cwd "$work/jvm-mutant/cwd"
if ! (cd "$work/jvm-mutant/cwd" &&
    java -Xss512m -Xmx2g -jar "$work/jvm-mutant/compiler.jar" run \
    --std "$root/std" "$here/probe.dawn") \
    > "$work/jvm-mutant/out" 2> "$work/jvm-mutant/err"; then
  cat "$work/jvm-mutant/err" >&2
  fail "JVM File.delete mutant did not compile and run the probe"
fi
expect_mutant_red "JVM File.delete" "$work/jvm-mutant/out"

# JVM Bool-query mutant: Files.isSymbolicLink reaches Path and throws for NUL,
# unlike File.exists/isDirectory. Removing its explicit preflight must produce
# a caught fault rather than the public false result.
mkdir -p "$work/jvm-query-mutant"
cp -R "$root/selfhost" "$work/jvm-query-mutant/selfhost"
cp -R "$root/packages" "$work/jvm-query-mutant/packages"
python3 - "$work/jvm-query-mutant/selfhost/src/jvm/rtclasses.dawn" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
old = '''  return_false_if_nul_path(sv, 0)
  push_path(sv, 0)'''
new = '''  push_path(sv, 0)'''
if text.count(old) != 1:
    raise SystemExit("JVM is_symlink NUL-guard mutation anchor is not unique")
path.write_text(text.replace(old, new))
PY
if ! java -Xss512m -Xmx2g -jar "$root/build/dawn-selfhost.jar" build \
    "$work/jvm-query-mutant/selfhost" -o "$work/jvm-query-mutant/compiler.jar" \
    --std "$root/std" --vendor org/objectweb/asm --vendor coursierapi \
    > "$work/jvm-query-mutant/build.out" 2>&1; then
  cat "$work/jvm-query-mutant/build.out" >&2
  fail "JVM is_symlink NUL-query mutant compiler did not build"
fi
prepare_cwd "$work/jvm-query-mutant/cwd"
if ! (cd "$work/jvm-query-mutant/cwd" &&
    java -Xss512m -Xmx2g -jar "$work/jvm-query-mutant/compiler.jar" run \
    --std "$root/std" "$here/probe.dawn") \
    > "$work/jvm-query-mutant/out" 2> "$work/jvm-query-mutant/err"; then
  cat "$work/jvm-query-mutant/err" >&2
  fail "JVM is_symlink NUL-query mutant did not compile and run the probe"
fi
expect_query_mutant_red "JVM is_symlink NUL-query" "nul is_symlink" \
  "$work/jvm-query-mutant/out"

# Std mutant: remove both public preflight branches, then exercise the same
# probe on both backends. The cwd is an isolated, non-empty scratch directory
# so the empty-path mutation cannot act outside the contract fixture.
mkdir -p "$work/preflight-mutant"
cp -R "$root/std" "$work/preflight-mutant/std"
python3 - "$work/preflight-mutant/std/io.dawn" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
old = '''pub fn delete(path: String) -> Result[DeleteOutcome, ForeignError] !io =
  if path == "" {
    Err(ForeignError {
      kind: "io.invalid_delete_path",
      message: "io.delete: path must not be empty",
      cause: None
    })
  } else if str.ends_with(path, "/") {
    Err(ForeignError {
      kind: "io.invalid_delete_path",
      message: "io.delete: path must not end with '/'",
      cause: None
    })
  } else {
    match catch_fault(() => io_delete(path)) {
      Ok(gone) -> if gone { Ok(Deleted) } else { Ok(NotFound) }
      Err(e) -> Err(e)
    }
  }'''
new = '''pub fn delete(path: String) -> Result[DeleteOutcome, ForeignError] !io =
  match catch_fault(() => io_delete(path)) {
    Ok(gone) -> if gone { Ok(Deleted) } else { Ok(NotFound) }
    Err(e) -> Err(e)
  }'''
if text.count(old) != 1:
    raise SystemExit("delete preflight mutation anchor is not unique")
path.write_text(text.replace(old, new))
PY
prepare_cwd "$work/preflight-mutant/jvm-cwd"
if ! (cd "$work/preflight-mutant/jvm-cwd" &&
    "$root/bin/dawn" run --std "$work/preflight-mutant/std" "$here/probe.dawn") \
    > "$work/preflight-mutant/jvm.out" 2> "$work/preflight-mutant/jvm.err"; then
  cat "$work/preflight-mutant/jvm.err" >&2
  fail "JVM delete-preflight mutant did not compile and run"
fi
expect_preflight_mutant_red "JVM delete-preflight removal" "$work/preflight-mutant/jvm.out"

if ! "$root/bin/dawn" __emitc --std "$work/preflight-mutant/std" "$here/probe.dawn" \
    -o "$work/preflight-mutant/probe.c" \
    > "$work/preflight-mutant/emitc.out" 2>&1; then
  cat "$work/preflight-mutant/emitc.out" >&2
  fail "native delete-preflight mutant did not emit C"
fi
if ! "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -Wall -Wextra -Werror -Wno-unused-variable -Wno-unused-but-set-variable \
    -Wno-unused-parameter -Wno-unused-label -I "$root/runtime/c" \
    -o "$work/preflight-mutant/probe" "$work/preflight-mutant/probe.c" \
    "$root/runtime/c/dawn_rt.c" -lm > "$work/preflight-mutant/cc.out" 2>&1; then
  cat "$work/preflight-mutant/cc.out" >&2
  fail "native delete-preflight mutant did not compile"
fi
prepare_cwd "$work/preflight-mutant/native-cwd"
if ! (cd "$work/preflight-mutant/native-cwd" && "$work/preflight-mutant/probe") \
    > "$work/preflight-mutant/native.out" 2> "$work/preflight-mutant/native.err"; then
  cat "$work/preflight-mutant/native.err" >&2
  fail "native delete-preflight mutant did not run"
fi
expect_preflight_mutant_red "native delete-preflight removal" \
  "$work/preflight-mutant/native.out"

echo "delete contract ok"
