#!/usr/bin/env bash
# The atomic-manifest-write contract: what `io.atomic_write_file` promises, the
# host failure at every step it has to survive, and a live mutant per promise.
#
# Three kinds of check live here, and they answer different questions:
#
#   contract    -- the probe's output on both backends against one golden file.
#                  Also the JVM/native agreement check: the two are compared to
#                  each other, so a backend that drifts fails here and not in
#                  whoever notices later.
#   injection   -- a failure forced at one step (create, write, close, read-back,
#                  permission, replace) with the same two assertions every time:
#                  the destination still holds what it held, and no staging file
#                  is left behind. Two of the six are real host failures rather
#                  than injected ones (an unwritable directory, and a directory
#                  where the destination should be), which is better evidence
#                  and is used wherever the host can be made to produce it.
#   mutant      -- one promise removed from std/io.dawn. Each must compile and
#                  run, and each must turn *one named* assertion red. A mutant
#                  that stays green means the assertion above it is decoration,
#                  which is the failure mode this whole directory exists for.
#
# The permission assertion deliberately does not come from the probe. It is read
# with `stat` after the fact, so the thing under test is not also the witness.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/atomic-write-contract"
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
# The fixtures include directories with the write bit off; put it back before
# the recursive delete, or the trap fails and takes the exit status with it.
trap 'chmod -R u+rwX "$work" 2>/dev/null || true; rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Root ignores the permission bits two of the checks are built on, and a check
# that cannot fail is worse than no check. Say so rather than skipping quietly.
if [ "$(id -u)" = 0 ]; then
  fail "this contract must not run as root: the unwritable-directory cases cannot fail for root"
fi

# ---------------------------------------------------------------- fixtures

prepare() { # dir -- the full fixture probe.dawn expects
  local d="$1"
  rm -rf "$d"
  mkdir -p "$d"/a "$d"/b "$d"/c "$d"/d/target.toml "$d"/e/.dawn-atomic.tmp "$d"/f "$d"/g
  printf 'old\n' > "$d/a/target.toml"
  chmod 640 "$d/a/target.toml"
  printf 'secret\n' > "$d/b/secret.txt"
  ln -s secret.txt "$d/b/link.toml"
  printf 'old\n' > "$d/c/hard.toml"
  ln "$d/c/hard.toml" "$d/c/hard.other"
  printf 'old\n' > "$d/e/target.toml"
  # f: the one shape where staging fails and a plain overwrite would not --
  # the directory refuses new entries while the file itself is writable.
  printf 'old\n' > "$d/f/target.toml"
  chmod 666 "$d/f/target.toml"
  chmod 500 "$d/f"
}

prepare_inject() { # dir -- one replaceable file and nothing else
  local d="$1"
  rm -rf "$d"
  mkdir -p "$d"
  printf 'old\n' > "$d/target.toml"
}

prepare_inject_dir_target() { # dir -- the destination is a directory
  local d="$1"
  rm -rf "$d"
  mkdir -p "$d/target.toml"
}

prepare_inject_readonly() { # dir -- unwritable directory, writable file
  local d="$1"
  rm -rf "$d"
  mkdir -p "$d"
  printf 'old\n' > "$d/target.toml"
  chmod 666 "$d/target.toml"
  chmod 500 "$d"
}

# ---------------------------------------------------------------- toolchain

# A copy of std the caller may edit. Every mutant and every injection is one of
# these: the primitive under test is std source, so a mutant is a source edit
# and `--std` is how a compile is pointed at it.
fork_std() { # dst
  rm -rf "$1"
  cp -r "$root/std" "$1"
}

# Rewrite exactly one anchor in a forked std, or fail. An anchor that no longer
# matches is the way a mutant quietly stops mutating, so it is an error and not
# a no-op (scripts/intrinsic-parity.py's note says the same thing about greps).
patch_std() { # stddir, label, old, new
  python3 - "$1/io.dawn" "$2" "$3" "$4" <<'PY'
import pathlib
import sys

path, label, old, new = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
p = pathlib.Path(path)
text = p.read_text()
if text.count(old) != 1:
    raise SystemExit(f"{label}: anchor is not unique in std/io.dawn ({text.count(old)} matches)")
p.write_text(text.replace(old, new))
PY
}

append_std() { # stddir, text
  printf '\n%s\n' "$2" >> "$1/io.dawn"
}

run_jvm() { # stddir, cwd, probe, out
  ( cd "$2" && "$root/bin/dawn" run --std "$1" "$3" ) > "$4" 2> "$4.err"
}

build_native() { # stddir, rtdir, probe, outbin
  local stddir="$1" rtdir="$2" probe="$3" outbin="$4"
  "$root/bin/dawn" __emitc --std "$stddir" "$probe" -o "$outbin.c" > "$outbin.emit" 2>&1 ||
    { cat "$outbin.emit" >&2; fail "native emit failed for $probe"; }
  "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -Wall -Wextra -Werror -Wno-unused-variable -Wno-unused-but-set-variable \
    -Wno-unused-parameter -Wno-unused-label -I "$rtdir" \
    -o "$outbin" "$outbin.c" "$rtdir/dawn_rt.c" -lm > "$outbin.cc" 2>&1 ||
    { cat "$outbin.cc" >&2; fail "native compile failed for $probe"; }
}

# ---------------------------------------------------------------- contract

"$root/bin/dawn" --version > /dev/null

prepare "$work/jvm-cwd"
run_jvm "$root/std" "$work/jvm-cwd" "$here/probe.dawn" "$work/jvm.out" ||
  { cat "$work/jvm.out.err" >&2; fail "JVM probe did not compile and run"; }
cmp -s "$here/expected.txt" "$work/jvm.out" || {
  diff -u "$here/expected.txt" "$work/jvm.out" >&2 || true
  fail "JVM behaviour differs from the contract"
}
echo "PASS  JVM contract"

build_native "$root/std" "$root/runtime/c" "$here/probe.dawn" "$work/probe"
prepare "$work/native-cwd"
( cd "$work/native-cwd" && "$work/probe" ) > "$work/native.out" 2> "$work/native.err" ||
  { cat "$work/native.err" >&2; fail "native probe did not run"; }
cmp -s "$here/expected.txt" "$work/native.out" || {
  diff -u "$here/expected.txt" "$work/native.out" >&2 || true
  fail "native behaviour differs from the contract"
}
echo "PASS  native contract"
cmp -s "$work/jvm.out" "$work/native.out" || fail "JVM and native answers differ"
echo "PASS  JVM and native agree"

# The permission witness, read from outside: an existing destination keeps its
# mode, and one that did not exist gets the creating call's own (0600 from
# mkstemp / createTempFile, not the umask's 0644 -- staging is private until it
# is published, and a destination that was never there has no mode to restore).
for cwd in "$work/jvm-cwd" "$work/native-cwd"; do
  kept="$(stat -c '%a' "$cwd/a/target.toml")"
  [ "$kept" = 640 ] || fail "replaced file lost its mode: $kept (expected 640) in $cwd"
  made="$(stat -c '%a' "$cwd/a/created.toml")"
  [ "$made" = 600 ] || fail "new file has mode $made (expected 600) in $cwd"
done
echo "PASS  mode preserved on replace, secure mode on create"

# ---------------------------------------------------------------- injections

# Every injection asserts the same two things about the destination, whatever
# the step that failed and whatever it was called.
expect_inject() { # label, expected-result, expected-content, out
  local label="$1" want="$2" content="$3" out="$4"
  grep -qx "result = $want" "$out" || { cat "$out" >&2; fail "$label: result was not '$want'"; }
  grep -qx "content = $content" "$out" ||
    { cat "$out" >&2; fail "$label: the destination did not survive unchanged"; }
  grep -qx 'entries = \["target.toml"\]' "$out" ||
    { cat "$out" >&2; fail "$label: a staging file was left behind"; }
  echo "PASS  injection: $label"
}

inject_helper='## Injected by scripts/atomic-write-contract.
fn inject_fault(step: String) -> Result[Unit, ForeignError] !io =
  Err(ForeignError { kind: "inject." ++ step, message: "injected", cause: None })

fn inject_bytes_fault(step: String) -> Result[Bytes, ForeignError] !io =
  Err(ForeignError { kind: "inject." ++ step, message: "injected", cause: None })'

# 1. create -- a real host failure: the directory takes no new entries. Nothing
#    is injected, and an unguarded implementation would still succeed here by
#    writing the destination directly, which is what mutant 1 does.
prepare_inject_readonly "$work/inj-create"
run_jvm "$root/std" "$work/inj-create" "$here/inject_probe.dawn" "$work/inj-create.out" ||
  { cat "$work/inj-create.out.err" >&2; fail "create injection did not run"; }
expect_inject "create (unwritable directory)" err old "$work/inj-create.out"

# 2. write
fork_std "$work/std-inj-write"
patch_std "$work/std-inj-write" "inject write" \
  '  match write_file(tmp, content) {' \
  '  match inject_fault("write") {'
append_std "$work/std-inj-write" "$inject_helper"
prepare_inject "$work/inj-write"
run_jvm "$work/std-inj-write" "$work/inj-write" "$here/inject_probe.dawn" "$work/inj-write.out" ||
  { cat "$work/inj-write.out.err" >&2; fail "write injection did not compile and run"; }
expect_inject write inject.write old "$work/inj-write.out"

# 3. close -- the one step with no seam in Dawn: `write_file` is open, write and
#    close in a single host call, so the failure is injected in the C runtime,
#    after the bytes are already on disk. Native only, and that is the honest
#    coverage: on the JVM the same failure comes back from `Files.write` as the
#    IOException the write injection above already stands for.
mkdir -p "$work/rt-close"
cp "$root/runtime/c/dawn_rt.c" "$root/runtime/c/dawn_rt.h" "$work/rt-close/"
python3 - "$work/rt-close/dawn_rt.c" <<'PY'
import pathlib
import sys

p = pathlib.Path(sys.argv[1])
text = p.read_text()
old = '''  if (fclose(f) != 0) bad = true;
  if (bad) {
    dawn_fault(DAWN_LIT("io_write_file: write failed"));'''
new = '''  if (fclose(f) != 0) bad = true;
  bad = true; /* injected: the close step reports failure */
  if (bad) {
    dawn_fault(DAWN_LIT("io_write_file: write failed"));'''
if text.count(old) != 1:
    raise SystemExit("close-injection anchor is not unique in dawn_rt.c")
p.write_text(text.replace(old, new))
PY
build_native "$root/std" "$work/rt-close" "$here/inject_probe.dawn" "$work/inj-close-bin"
prepare_inject "$work/inj-close"
( cd "$work/inj-close" && "$work/inj-close-bin" ) > "$work/inj-close.out" 2>&1 ||
  { cat "$work/inj-close.out" >&2; fail "close injection did not run"; }
expect_inject "close (native runtime)" err old "$work/inj-close.out"

# 4. read-back, both halves: the read itself failing, and the read succeeding
#    with bytes that are not the ones asked for.
fork_std "$work/std-inj-readback"
patch_std "$work/std-inj-readback" "inject readback" \
  '      match read_bytes(tmp) {' \
  '      match inject_bytes_fault("readback") {'
append_std "$work/std-inj-readback" "$inject_helper"
prepare_inject "$work/inj-readback"
run_jvm "$work/std-inj-readback" "$work/inj-readback" "$here/inject_probe.dawn" \
  "$work/inj-readback.out" ||
  { cat "$work/inj-readback.out.err" >&2; fail "readback injection did not compile and run"; }
expect_inject read-back inject.readback old "$work/inj-readback.out"

# The corrupting writer. This is the only injection whose expected result is a
# kind std mints rather than one it was handed: the write reported success and
# the check is what caught it. Mutant 3 is this same std with the check removed.
corrupt_std() { # dst
  fork_std "$1"
  patch_std "$1" "inject corrupt write" \
    '  match write_file(tmp, content) {' \
    '  match write_file(tmp, content ++ "corrupt") {'
}
corrupt_std "$work/std-inj-corrupt"
prepare_inject "$work/inj-corrupt"
run_jvm "$work/std-inj-corrupt" "$work/inj-corrupt" "$here/inject_probe.dawn" \
  "$work/inj-corrupt.out" ||
  { cat "$work/inj-corrupt.out.err" >&2; fail "corrupt-write injection did not compile and run"; }
expect_inject "read-back validate (corrupting writer)" io.atomic_write_verify_failed old \
  "$work/inj-corrupt.out"

# 5. permission
fork_std "$work/std-inj-perm"
patch_std "$work/std-inj-perm" "inject permission" \
  '  if exists(path) { copy_permissions(path, tmp) } else { Ok(()) }' \
  '  if exists(path) { inject_fault("permission") } else { Ok(()) }'
append_std "$work/std-inj-perm" "$inject_helper"
prepare_inject "$work/inj-perm"
run_jvm "$work/std-inj-perm" "$work/inj-perm" "$here/inject_probe.dawn" "$work/inj-perm.out" ||
  { cat "$work/inj-perm.out.err" >&2; fail "permission injection did not compile and run"; }
expect_inject permission inject.permission old "$work/inj-perm.out"

# 6. replace -- a real host failure again: a rename onto a directory is refused.
#    The destination is a directory here, so `content` reads as unreadable; what
#    is being asserted is that it is still a directory afterwards.
prepare_inject_dir_target "$work/inj-replace"
run_jvm "$root/std" "$work/inj-replace" "$here/inject_probe.dawn" "$work/inj-replace.out" ||
  { cat "$work/inj-replace.out.err" >&2; fail "replace injection did not run"; }
expect_inject "replace (destination is a directory)" err "<unreadable>" "$work/inj-replace.out"
[ -d "$work/inj-replace/target.toml" ] || fail "replace injection: the destination stopped being a directory"

# ---------------------------------------------------------------- concurrency

# Staging names come from the host, one per call, so writers in one directory do
# not collide. Eight at once, all publishing the same bytes: every one succeeds
# and nothing is left staged. Only the verdict lines are read -- a writer can
# see another's staging file while it is still there, so the listing each prints
# is its own business and not a contract.
build_native "$root/std" "$root/runtime/c" "$here/inject_probe.dawn" "$work/probe-race"
prepare_inject "$work/race"
race_pids=()
for i in 1 2 3 4 5 6 7 8; do
  ( cd "$work/race" && "$work/probe-race" ) > "$work/race.$i.out" 2>&1 &
  race_pids+=($!)
done
race_bad=0
for pid in "${race_pids[@]}"; do wait "$pid" || race_bad=1; done
if [ "$race_bad" != 0 ]; then
  fail "concurrent writers did not all run"
fi
for i in 1 2 3 4 5 6 7 8; do
  grep -qx 'result = ok' "$work/race.$i.out" ||
    { cat "$work/race.$i.out" >&2; fail "concurrent writer $i did not succeed"; }
done
left="$(cd "$work/race" && find . -mindepth 1 -maxdepth 1 | sort | tr '\n' ' ')"
[ "$left" = "./target.toml " ] || fail "concurrent writers left something behind: $left"
echo "PASS  eight concurrent writers, no name collision and no residue"

# ---------------------------------------------------------------- mutants

# Each mutant names the single assertion it must turn red. `expect_red` insists
# on both halves: the run has to happen (a mutant that fails to compile proves
# nothing), and the named line has to have moved.
expect_red() { # label, out, assertion-line
  if cmp -s "$here/expected.txt" "$2"; then
    fail "$1 mutant stayed green"
  fi
  if grep -qx "$3" "$2"; then
    diff -u "$here/expected.txt" "$2" >&2 || true
    fail "$1 mutant did not move its owning assertion: $3"
  fi
  local moved
  moved="$(diff "$here/expected.txt" "$2" | grep -c '^>' || true)"
  echo "PASS  mutant: $1 (owning assertion '$3' turned red; $moved line(s) moved)"
}

mutant_run() { # name, stddir
  local name="$1" stddir="$2"
  prepare "$work/cwd-$name"
  run_jvm "$stddir" "$work/cwd-$name" "$here/probe.dawn" "$work/mutant-$name.out" ||
    { cat "$work/mutant-$name.out.err" >&2; fail "$name mutant did not compile and run"; }
}

# 1. the rejected option B: fall back to writing the destination directly when
#    staging fails. Only visible where staging can fail and a direct write
#    cannot, which is the unwritable directory holding a writable file.
fork_std "$work/std-m1"
patch_std "$work/std-m1" "mutant direct-fallback" \
  '      Err(e) -> Err(e)
      Ok(tmp) -> stage_replace(path, content, tmp)' \
  '      Err(_) -> write_file(path, content)
      Ok(tmp) -> stage_replace(path, content, tmp)'
mutant_run m1 "$work/std-m1"
expect_red "direct-write fallback" "$work/mutant-m1.out" 'readonly dir content = old'

# 2. a staging name spelled here instead of claimed from the host. Visible
#    because something is already sitting on that name.
fork_std "$work/std-m2"
patch_std "$work/std-m2" "mutant fixed-temp-name" \
  '    match temp_file(parent_dir(path), ".dawn-atomic-") {' \
  '    match fixed_temp(parent_dir(path)) {'
append_std "$work/std-m2" '## Injected by scripts/atomic-write-contract.
fn fixed_temp(dir: String) -> Result[String, ForeignError] !io = Ok(dir ++ "/.dawn-atomic.tmp")'
mutant_run m2 "$work/std-m2"
expect_red "fixed staging name" "$work/mutant-m2.out" 'squat content = new'

# 3. the read-back check removed. Layered on the corrupting writer, because a
#    check for something that never happens is invisible either way -- which is
#    itself the reason the injection above exists.
corrupt_std "$work/std-m3"
patch_std "$work/std-m3" "mutant skip-verify" \
  '          if seen != bytes_utf8(content) {' \
  '          if false {'
prepare_inject "$work/cwd-m3"
run_jvm "$work/std-m3" "$work/cwd-m3" "$here/inject_probe.dawn" "$work/mutant-m3.out" ||
  { cat "$work/mutant-m3.out.err" >&2; fail "skip-verify mutant did not compile and run"; }
if grep -qx 'result = io.atomic_write_verify_failed' "$work/mutant-m3.out"; then
  fail "skip-verify mutant stayed green"
fi
if grep -qx 'content = old' "$work/mutant-m3.out"; then
  cat "$work/mutant-m3.out" >&2
  fail "skip-verify mutant did not publish the corrupted bytes"
fi
echo "PASS  mutant: skipped read-back (owning assertion 'result = io.atomic_write_verify_failed' turned red)"

# 4. delete the destination before renaming over it. The window is only
#    observable when the rename that follows fails, so the destination here is a
#    directory: refused by rename, but removable by delete.
fork_std "$work/std-m4"
patch_std "$work/std-m4" "mutant delete-before-rename" \
  '                match rename(tmp, path) {' \
  '                match rename_after_delete(tmp, path) {'
append_std "$work/std-m4" '## Injected by scripts/atomic-write-contract.
fn rename_after_delete(tmp: String, path: String) -> Result[Unit, ForeignError] !io = {
  let _ = delete(path)
  rename(tmp, path)
}'
mutant_run m4 "$work/std-m4"
expect_red "delete before rename" "$work/mutant-m4.out" 'dir target is dir = true'

# 5. follow the symlink instead of refusing it.
fork_std "$work/std-m5"
patch_std "$work/std-m5" "mutant follow-symlink" \
  '  } else if is_symlink(path) {' \
  '  } else if false {'
mutant_run m5 "$work/std-m5"
expect_red "followed symlink" "$work/mutant-m5.out" 'symlink still link = true'

# 6. leave the staging file behind on failure.
fork_std "$work/std-m6"
patch_std "$work/std-m6" "mutant no-cleanup" \
  'fn abandon(tmp: String, e: ForeignError) -> Result[Unit, ForeignError] !io = {
  let _ = delete(tmp)
  Err(e)
}' \
  'fn abandon(tmp: String, e: ForeignError) -> Result[Unit, ForeignError] !io = {
  let _ = tmp
  Err(e)
}'
mutant_run m6 "$work/std-m6"
expect_red "staging file not cleaned up" "$work/mutant-m6.out" 'dir target entries = \["target.toml"\]'

# 7. do not carry the destination's permissions over. The probe cannot see this
#    at all -- the witness is `stat`, from outside.
fork_std "$work/std-m7"
patch_std "$work/std-m7" "mutant no-permission-copy" \
  '  if exists(path) { copy_permissions(path, tmp) } else { Ok(()) }' \
  '  if false { copy_permissions(path, tmp) } else { Ok(()) }'
mutant_run m7 "$work/std-m7"
cmp -s "$here/expected.txt" "$work/mutant-m7.out" ||
  fail "no-permission-copy mutant changed the probe's output, so the stat witness is not what caught it"
after="$(stat -c '%a' "$work/cwd-m7/a/target.toml")"
if [ "$after" = 640 ]; then
  fail "no-permission-copy mutant stayed green: mode is still 640"
fi
echo "PASS  mutant: permissions not carried over (owning assertion 'stat a/target.toml = 640' turned red, saw $after)"

# ---------------------------------------------------------------- call sites
#
# Everything above tests the primitive. None of it can tell whether anything
# calls it: every mutant so far edits std/io.dawn, and a `dawn add` that still
# wrote its manifest with `io.write_file` would leave all seven green. The two
# writers TOOL-13 was raised for are compiler source, so the mutants here are
# private selfhost JARs -- the same harness the target-classpath contract uses,
# ~5s a build.
#
# The fixture is mutant 1's shape for mutant 1's reason: a directory that
# refuses new entries while the file inside it stays writable is the one place
# where staging fails and a plain overwrite would have succeeded. So "the
# command failed and the old bytes are still there" is precisely what a call
# site that regressed to `io.write_file` cannot produce -- and the writable
# half of each pair is there so that a mutant which merely broke the command
# cannot be mistaken for one that lost atomicity.
#
# Maven resolution is real but offline: a fixture repository under file:// with
# one empty jar, since `dawn lock` reaches its write only after a fetch and the
# fetch's contents are nothing this contract is about.

cs="$work/callsites"
mkdir -p "$cs/repo/fixture/dep/1"
python3 - "$cs/repo/fixture/dep/1/dep-1.jar" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1], "w") as z:
    z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
PY
cat > "$cs/repo/fixture/dep/1/dep-1.pom" <<'EOF'
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>fixture</groupId>
  <artifactId>dep</artifactId>
  <version>1</version>
</project>
EOF

# The lock is seeded with a hash that is deliberately not the jar's, so that a
# successful rewrite is visible as a change. `dawn lock` without --check does
# not read it first, so this is stale rather than invalid.
cs_project() { # dir, dir-mode
  local d="$1" mode="$2"
  rm -rf "$d"
  mkdir -p "$d/src"
  cat > "$d/dawn.toml" <<'EOF'
schema = 1
name = "fixture_app"

[java-deps]
dep = "fixture:dep:1"
EOF
  printf 'pub fn main() -> Unit !io = ()\n' > "$d/src/main.dawn"
  printf 'schema 1\ncoord fixture:dep:1\nartifact %064d  dep-1.jar\n' 0 > "$d/dawn.lock"
  chmod 666 "$d/dawn.toml" "$d/dawn.lock"
  chmod "$mode" "$d"
}

cs_state() { # file, reference
  if cmp -s "$1" "$2"; then echo old; else echo new; fi
}

cs_entries() { # dir
  ( cd "$1" && find . -mindepth 1 -maxdepth 1 -printf '%f\n' | sort |
      sed 's/^/"/; s/$/"/' | paste -sd, - | sed 's/,/, /g; s/^/[/; s/$/]/' )
}

cs_run() { # jar, args...
  local jar="$1"
  shift
  if env "DAWN_MAVEN_MIRROR=file://$cs/repo" "COURSIER_CACHE=$cs/coursier" \
      "DAWN_PKG_CACHE=$cs/pkg" "DAWN_SELFHOST_CP=" \
      "$JAVA_BIN" -Xss512m -Xmx2g -jar "$jar" "$@" > "$cs/last.out" 2> "$cs/last.err"; then
    echo ok
  else
    echo err
  fi
}

# One probe, four scenarios, run against whichever compiler it is handed.
cs_probe() { # jar, out
  local jar="$1" out="$2" r
  : > "$out"

  cs_project "$cs/add-ro" 500
  r="$(cs_run "$jar" add org.example:thing:1.2.3 --dir "$cs/add-ro")"
  chmod 700 "$cs/add-ro"
  {
    echo "add readonly result = $r"
    echo "add readonly manifest = $(cs_state "$cs/add-ro/dawn.toml" "$cs/manifest.ref")"
    echo "add readonly entries = $(cs_entries "$cs/add-ro")"
  } >> "$out"

  cs_project "$cs/add-rw" 700
  r="$(cs_run "$jar" add org.example:thing:1.2.3 --dir "$cs/add-rw")"
  {
    echo "add writable result = $r"
    echo "add writable manifest = $(cs_state "$cs/add-rw/dawn.toml" "$cs/manifest.ref")"
    echo "add writable manifest has thing = $(
      grep -Fq 'org.example:thing:1.2.3' "$cs/add-rw/dawn.toml" && echo true || echo false)"
  } >> "$out"

  cs_project "$cs/lock-ro" 500
  r="$(cs_run "$jar" lock "$cs/lock-ro")"
  chmod 700 "$cs/lock-ro"
  {
    echo "lock readonly result = $r"
    echo "lock readonly lockfile = $(cs_state "$cs/lock-ro/dawn.lock" "$cs/lock.ref")"
    echo "lock readonly entries = $(cs_entries "$cs/lock-ro")"
  } >> "$out"

  cs_project "$cs/lock-rw" 700
  r="$(cs_run "$jar" lock "$cs/lock-rw")"
  {
    echo "lock writable result = $r"
    echo "lock writable lockfile = $(cs_state "$cs/lock-rw/dawn.lock" "$cs/lock.ref")"
    echo "lock writable lockfile has coord = $(
      grep -Fq 'coord fixture:dep:1' "$cs/lock-rw/dawn.lock" && echo true || echo false)"
  } >> "$out"
}

# The reference copies the probe compares against: what a project holds before
# any command has touched it.
cs_project "$cs/ref" 700
cp "$cs/ref/dawn.toml" "$cs/manifest.ref"
cp "$cs/ref/dawn.lock" "$cs/lock.ref"

JAVA_BIN="${JAVA_HOME:+$JAVA_HOME/bin/}java"
command -v "$JAVA_BIN" > /dev/null || JAVA_BIN=java

# A private compiler built from a copy of selfhost, optionally with one call
# site put back the way it was. The baseline is built the same way as the
# mutants so that the only difference between the two runs is the mutation.
cs_build() { # name, sed-target-or-empty
  local name="$1" mutate="$2"
  local dir="$cs/build-$name"
  rm -rf "$dir"
  mkdir -p "$dir"
  cp -R "$root/selfhost" "$dir/selfhost"
  cp -R "$root/compiler-plan" "$dir/compiler-plan"
  ln -s "$root/packages" "$dir/packages"
  if [ -n "$mutate" ]; then
    python3 - "$dir/selfhost/src/$mutate" <<'PY'
import pathlib
import sys

p = pathlib.Path(sys.argv[1])
text = p.read_text()
if text.count("io.atomic_write_file(") != 1:
    raise SystemExit(f"{p}: expected exactly one atomic write call site")
p.write_text(text.replace("io.atomic_write_file(", "io.write_file("))
PY
  fi
  if ! DAWN_SELFHOST_CP="" "$root/bin/dawn" build "$dir/selfhost" -o "$dir/compiler.jar" \
      --std "$root/std" --vendor org/objectweb/asm --vendor coursierapi \
      > "$dir/build.out" 2> "$dir/build.err"; then
    cat "$dir/build.out" "$dir/build.err" >&2
    fail "$name private selfhost did not compile"
  fi
  CS_JAR="$dir/compiler.jar"
}

cs_build baseline ""
cs_probe "$CS_JAR" "$work/callsites.out"
cmp -s "$here/callsites-expected.txt" "$work/callsites.out" || {
  diff -u "$here/callsites-expected.txt" "$work/callsites.out" >&2 || true
  fail "the call sites do not behave as the contract says"
}
echo "PASS  call sites: dawn add and dawn lock publish rather than overwrite"

# Each call-site mutant owns one line, and must leave the other call site's
# lines alone -- an owning assertion that also moves for the other mutation is
# not owned by either.
cs_expect_red() { # label, out, assertion, untouched-prefix
  if cmp -s "$here/callsites-expected.txt" "$2"; then
    fail "$1 mutant stayed green"
  fi
  if grep -qx "$3" "$2"; then
    diff -u "$here/callsites-expected.txt" "$2" >&2 || true
    fail "$1 mutant did not move its owning assertion: $3"
  fi
  if ! diff <(grep "^$4" "$here/callsites-expected.txt") <(grep "^$4" "$2") > /dev/null; then
    diff -u "$here/callsites-expected.txt" "$2" >&2 || true
    fail "$1 mutant also moved the '$4' lines, so the assertion above is not owned"
  fi
  local moved
  moved="$(diff "$here/callsites-expected.txt" "$2" | grep -c '^>' || true)"
  echo "PASS  mutant: $1 (owning assertion '$3' turned red; $moved line(s) moved)"
}

cs_build add-plain-write pkg/add.dawn
cs_probe "$CS_JAR" "$work/callsites-m-add.out"
cs_expect_red "dawn add back to io.write_file" "$work/callsites-m-add.out" \
  'add readonly manifest = old' 'lock '

cs_build lock-plain-write main.dawn
cs_probe "$CS_JAR" "$work/callsites-m-lock.out"
cs_expect_red "dawn lock back to io.write_file" "$work/callsites-m-lock.out" \
  'lock readonly lockfile = old' 'add '

echo "OK: atomic-write contract, six injections, seven primitive mutants and two call-site mutants"
