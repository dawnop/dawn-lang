#!/usr/bin/env bash
# The second-backend differential for the driver's shared subcommands (K-B2).
#
# Why it exists: `selfhost-fmt-diff.sh` and `selfhost-run-diff.sh` were read as
# "the formatter/CLI is checked", and they are — on the JVM. Both hardcoded
# ./bin/dawn as the toolchain under test, so no native binary was ever
# executed by either. Wiring fmt/doc/add into selfhost/src/nmain.dawn does not
# by itself put them under a gate; this script is what does.
#
# Two legs, two different oracles:
#
#   fmt   the N-1 release, by running selfhost-fmt-diff.sh with DAWN_SELF
#   lsp   pointed at the native binary. Same corpus (327 tracked .dawn files
#         plus mangled copies for fmt; the scripted LSP session for lsp), same
#         oracle, other backend.
#   doc   HEAD's JVM driver, byte for byte. There is no N-1 native driver to
#   add   diff against — these subcommands did not exist on this backend
#         before — and the JVM side is itself pinned to N-1 by
#         selfhost-run-diff.sh, so the chain is native == JVM == N-1.
#
# The doc/add legs have no Emit-Change escape hatch on purpose. An
# Emit-Change declares an intended change *over time*; a disagreement between
# two backends at the same commit is a bug in one of them, and there is no
# version of this repository in which it is approved.
#
# The corpus is deliberately free of `use java`: the native driver refuses it
# (jsig_refused), so `doc site` is not a divergence but the documented answer.
#
# ---- twenty-four cases left this file in 2026-09-04 ----
#
# `Console` and `Exit` became effects that day, so a usage refusal is readable
# from inside the tree for the first time: `compiler-plan/src/consolemem.dawn`
# answers the writes from a table and `exitmem.dawn` catches the status. Every
# case whose whole content was "this argv printed that and exited with this"
# is an inline test now, twice over -- once against `selfhost/src/main.dawn`'s
# parsers and once against `selfhost/src/nmain.dawn`'s, which is the doubling
# the pairing here used to provide. Look for `cli_read` in either file;
# docs/effects-design.md §8.1 has the ledger.
#
#   check   zero targets, missing target
#   test    zero targets, usage, multiple targets, the --stdlib conflict,
#           missing target, wrong suffix, --cp with no path, --cp entry not found
#   doc     zero targets, usage, multiple targets, all three mode conflicts,
#           missing target
#   build   zero targets, multiple targets
#   fmt     zero targets, usage, missing target
#   run     a bare token and a flag-like token after the target
#
# What stayed, by the reason it stayed. **Both backends at once**: every
# `pair` judges "and the two agree", which no single-process test can say, and
# the three `emitc` cases are entirely that (the drivers spell the command
# differently, `__emitc` against `emitc`). **A build product**: the six
# `pair_report` cases spawn a JVM or compile a binary and then read its
# report. **The network and the package cache**: the five `add_pair` cases.
# **A real process**: legs 1 and 4 need the N-1 release binary, and legs 4b,
# 5, 7 and 8 judge framing on a real stdout, an answer mid-session, a file
# dropped by an assertion, and a report that reached stdout before the process
# ended. One movable case stayed too: `check (std stamped with another
# release)` wants a std directory built on disk, so moving it would move the
# fixture rather than the judgment.
#
# The moved cases are not lost coverage on this backend: `gates.yml` runs
# `dawnc test selfhost/src/nmain.dawn` under the native binary, which is where
# nmain's half of them executes. See that job's note.
#
#   ./scripts/native-cli-diff.sh              # builds the native driver
#   DAWNC_BIN=/path/to/dawnc ./scripts/native-cli-diff.sh   # reuse one
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

OUT=${TMPDIR:-/tmp}/native-cli-diff.$$
mkdir -p "$OUT"
if [ -z "${KEEP:-}" ]; then trap 'rm -rf "$OUT"' EXIT; fi

# the JVM driver is both the reference for doc/add and the compiler that
# produces the native one, so build it first and keep rebuild chatter out of
# the transcripts below
./bin/dawn --version > /dev/null

DAWNC=${DAWNC_BIN:-}
if [ -z "$DAWNC" ]; then
  echo "building the native driver from selfhost/src/nmain.dawn..."
  ./bin/dawn __emitc selfhost/src/nmain.dawn -o "$OUT/nmain.c"
  "${CC:-cc}" -std=c11 -Wno-parentheses-equality -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread -I "$ROOT/runtime/c" \
    -o "$OUT/dawnc" "$OUT/nmain.c" "$ROOT/runtime/c/dawn_rt.c" -lm
  DAWNC="$OUT/dawnc"
fi
# an absolute path: the add leg runs both drivers with a --dir elsewhere, and
# a relative one would resolve against the wrong place if that ever changes
case "$DAWNC" in /*) ;; *) DAWNC="$ROOT/$DAWNC" ;; esac

# Both drivers on the same std. Neither reads the working directory's `std`
# any more (#291): with no `--std` a command takes DAWN_STD, then the copy
# compiled in. ./bin/dawn exports DAWN_STD=$ROOT/std for the JVM side; dawnc
# has no launcher, so without this line it would answer every pair below from
# its embedded copy while the JVM answered from the checkout. The two hold the
# same text, but not the same provenance: a definition into std names a file
# only when a directory supplied it, and leg 4's session asks for exactly that.
# The leg that tests the resolution itself sets the variable per command.
DAWN_STD="$ROOT/std"
export DAWN_STD

fail=0
PAIR_J=0
PAIR_N=0

## Run the same argv through both drivers; stdout, stderr and the exit code
## must agree.
pair() { # label args...
  local label=$1
  shift
  ./bin/dawn "$@" > "$OUT/j.txt" 2>&1 && PAIR_J=0 || PAIR_J=$?
  "$DAWNC" "$@" > "$OUT/n.txt" 2>&1 && PAIR_N=0 || PAIR_N=$?
  if [ "$PAIR_J" != "$PAIR_N" ] || ! diff "$OUT/j.txt" "$OUT/n.txt" > "$OUT/d.txt"; then
    echo "FAIL: $label differs between backends (exits jvm=$PAIR_J native=$PAIR_N)"
    head -20 "$OUT/d.txt"
    fail=1
  else
    echo "OK   $label (exit $PAIR_J)"
  fi
}

## `pair`, plus an independent exit oracle. Equality alone lets both drivers
## accept the same invalid argv and call that agreement.
pair_expect_exit() { # exit label args...
  local want=$1
  local label=$2
  shift 2
  pair "$label" "$@"
  if [ "$PAIR_J" != "$want" ] || [ "$PAIR_N" != "$want" ]; then
    echo "FAIL: $label exits jvm=$PAIR_J native=$PAIR_N, want $want"
    fail=1
  fi
}

## A usage rejection has an absolute byte contract as well as exit 2.
pair_expect_error() { # expected label args...
  local expected=$1
  local label=$2
  shift 2
  ./bin/dawn "$@" > "$OUT/j.out" 2> "$OUT/j.err" && PAIR_J=0 || PAIR_J=$?
  "$DAWNC" "$@" > "$OUT/n.out" 2> "$OUT/n.err" && PAIR_N=0 || PAIR_N=$?
  printf '%s' "$expected" > "$OUT/expected.txt"
  if [ "$PAIR_J" != 2 ] || [ "$PAIR_N" != 2 ] ||
    [ -s "$OUT/j.out" ] || [ -s "$OUT/n.out" ] ||
    ! cmp -s "$OUT/j.err" "$OUT/expected.txt" ||
    ! cmp -s "$OUT/n.err" "$OUT/expected.txt"
  then
    echo "FAIL: $label did not match stdout-empty + stderr-bytes + exit-2"
    [ ! -s "$OUT/j.out" ] || { echo "--- unexpected JVM stdout"; head -20 "$OUT/j.out"; }
    [ ! -s "$OUT/n.out" ] || { echo "--- unexpected native stdout"; head -20 "$OUT/n.out"; }
    diff -u "$OUT/expected.txt" "$OUT/j.err" | sed -n '1,20p' || true
    diff -u "$OUT/expected.txt" "$OUT/n.err" | sed -n '1,20p' || true
    fail=1
  else
    echo "OK   $label (stdout empty, stderr exact, exit 2)"
  fi
}

## JVM spells the hidden C-emitter command `__emitc`; the native driver spells
## its public backend command `emitc`. Their cardinality and C text are one
## contract despite that dispatch-name difference.
emitc_pair() { # label args...
  local label=$1
  shift
  ./bin/dawn __emitc "$@" > "$OUT/j.txt" 2>&1 && PAIR_J=0 || PAIR_J=$?
  "$DAWNC" emitc "$@" > "$OUT/n.txt" 2>&1 && PAIR_N=0 || PAIR_N=$?
  if [ "$PAIR_J" != "$PAIR_N" ] || ! diff "$OUT/j.txt" "$OUT/n.txt" > "$OUT/d.txt"; then
    echo "FAIL: $label differs between backends (exits jvm=$PAIR_J native=$PAIR_N)"
    head -20 "$OUT/d.txt"
    fail=1
  else
    echo "OK   $label (exit $PAIR_J)"
  fi
}

emitc_expect_exit() { # exit label args...
  local want=$1
  local label=$2
  shift 2
  emitc_pair "$label" "$@"
  if [ "$PAIR_J" != "$want" ] || [ "$PAIR_N" != "$want" ]; then
    echo "FAIL: $label exits jvm=$PAIR_J native=$PAIR_N, want $want"
    fail=1
  fi
}

emitc_expect_error() { # expected label args...
  local expected=$1
  local label=$2
  shift 2
  ./bin/dawn __emitc "$@" > "$OUT/j.out" 2> "$OUT/j.err" && PAIR_J=0 || PAIR_J=$?
  "$DAWNC" emitc "$@" > "$OUT/n.out" 2> "$OUT/n.err" && PAIR_N=0 || PAIR_N=$?
  printf '%s' "$expected" > "$OUT/expected.txt"
  if [ "$PAIR_J" != 2 ] || [ "$PAIR_N" != 2 ] ||
    [ -s "$OUT/j.out" ] || [ -s "$OUT/n.out" ] ||
    ! cmp -s "$OUT/j.err" "$OUT/expected.txt" ||
    ! cmp -s "$OUT/n.err" "$OUT/expected.txt"
  then
    echo "FAIL: $label did not match stdout-empty + stderr-bytes + exit-2"
    [ ! -s "$OUT/j.out" ] || { echo "--- unexpected JVM stdout"; head -20 "$OUT/j.out"; }
    [ ! -s "$OUT/n.out" ] || { echo "--- unexpected native stdout"; head -20 "$OUT/n.out"; }
    diff -u "$OUT/expected.txt" "$OUT/j.err" | sed -n '1,20p' || true
    diff -u "$OUT/expected.txt" "$OUT/n.err" | sed -n '1,20p' || true
    fail=1
  else
    echo "OK   $label (stdout empty, stderr exact, exit 2)"
  fi
}

## Run one argv through both drivers against absolute stdout, stderr and exit
## expectations. A backend-to-backend diff cannot detect a shared boundary bug.
run_expect() { # exit stdout stderr label args...
  local want=$1
  local expected_out=$2
  local expected_err=$3
  local label=$4
  shift 4
  ./bin/dawn "$@" > "$OUT/j.out" 2> "$OUT/j.err" && PAIR_J=0 || PAIR_J=$?
  "$DAWNC" "$@" > "$OUT/n.out" 2> "$OUT/n.err" && PAIR_N=0 || PAIR_N=$?
  printf '%s' "$expected_out" > "$OUT/expected.out"
  printf '%s' "$expected_err" > "$OUT/expected.err"
  if [ "$PAIR_J" != "$want" ] || [ "$PAIR_N" != "$want" ] ||
    ! cmp -s "$OUT/j.out" "$OUT/expected.out" ||
    ! cmp -s "$OUT/n.out" "$OUT/expected.out" ||
    ! cmp -s "$OUT/j.err" "$OUT/expected.err" ||
    ! cmp -s "$OUT/n.err" "$OUT/expected.err"
  then
    echo "FAIL: $label did not match absolute stdout/stderr/exit $want"
    echo "--- JVM stdout"; diff -u "$OUT/expected.out" "$OUT/j.out" | sed -n '1,20p' || true
    echo "--- native stdout"; diff -u "$OUT/expected.out" "$OUT/n.out" | sed -n '1,20p' || true
    echo "--- JVM stderr"; diff -u "$OUT/expected.err" "$OUT/j.err" | sed -n '1,20p' || true
    echo "--- native stderr"; diff -u "$OUT/expected.err" "$OUT/n.err" | sed -n '1,20p' || true
    echo "exits: jvm=$PAIR_J native=$PAIR_N want=$want"
    fail=1
  else
    echo "OK   $label (stdout/stderr exact, exit $want)"
  fi
}

# ---- leg 0: positional arity, against absolute contracts ----
echo "== command arity, JVM and native vs absolute contracts =="
ARITY_A="$OUT/arity_a.dawn"
ARITY_B="$OUT/arity_b.dawn"
cat > "$ARITY_A" <<'EOF'
pub fn main() -> Unit !io = ()

test "arity fixture" {
  assert true
}
EOF
cat > "$ARITY_B" <<'EOF'
pub fn main() -> Unit !io = ()

test "second arity fixture" {
  assert true
}
EOF

pair_expect_exit 0 "check (one target)" check "$ARITY_A"
pair_expect_exit 0 "check (multiple targets)" check "$ARITY_A" "$ARITY_B"

# A std stamped with another release. The two drivers used to word this class
# of failure differently (`main.dawn` named the directory, `nmain.dawn` said
# "bundled std is broken"), so it is exactly the kind of sentence that drifts
# when only one of them is edited. Both render it through driver/stdlib now,
# and this is what holds them to that (#226).
SKEW_STD="$OUT/skew-std"
mkdir -p "$SKEW_STD"
cp "$ROOT"/std/*.dawn "$ROOT/std/modules.txt" "$SKEW_STD/"
printf '0.0.1-native-cli-diff\n' > "$SKEW_STD/VERSION"
DAWN_VERSION=$(sed -n 's/^pub const VERSION: String = "\(.*\)"$/\1/p' "$ROOT/selfhost/src/version.dawn")
SKEW_EXPECT="error: std version mismatch: the std in $SKEW_STD is 0.0.1-native-cli-diff,"
SKEW_EXPECT="$SKEW_EXPECT this toolchain is $DAWN_VERSION"$'\n'
SKEW_EXPECT="$SKEW_EXPECT  a toolchain only ever checked the std it was released with."$'\n'
SKEW_EXPECT="$SKEW_EXPECT  Use the $DAWN_VERSION std, or run the 0.0.1-native-cli-diff toolchain."$'\n'
pair_expect_error "$SKEW_EXPECT" \
  "check (std stamped with another release)" check --std "$SKEW_STD" "$ARITY_A"

pair_expect_exit 0 "test (one target)" test "$ARITY_A"
pair_expect_exit 0 "test (--stdlib selector)" test --stdlib

pair_expect_exit 0 "doc (one target)" doc "$ARITY_A"
pair_expect_exit 0 "doc (--stdlib selector)" doc --stdlib
pair_expect_exit 0 "doc (--builtins selector)" doc --builtins

rm -f "$OUT/arity.jar" "$OUT/arity-bin"
./bin/dawn build "$ARITY_A" -o "$OUT/arity.jar" > "$OUT/j.txt" 2>&1 && jbuild=0 || jbuild=$?
"$DAWNC" build "$ARITY_A" -o "$OUT/arity-bin" > "$OUT/n.txt" 2>&1 && nbuild=0 || nbuild=$?
if [ "$jbuild" != 0 ] || [ "$nbuild" != 0 ] ||
  [ ! -s "$OUT/arity.jar" ] || [ ! -s "$OUT/arity-bin" ]
then
  echo "FAIL: build (one target) must produce both backend-specific artifacts"
  fail=1
else
  echo "OK   build (one target: JVM jar and native executable both exist)"
fi

emitc_expect_error \
  $'error: usage: dawn emitc [--std <dir>] <file.dawn | project-dir> [-o out]\n' \
  "emitc (zero targets)"
emitc_expect_exit 0 "emitc (one target)" "$ARITY_A"
emitc_expect_error \
  "error: dawn emitc takes one target, got \`$ARITY_A\` and \`$ARITY_B\`; a bare word after the target is not a flag this subcommand knows"$'\n' \
  "emitc (multiple targets)" "$ARITY_A" "$ARITY_B"

pair_expect_exit 0 "fmt (one target)" fmt --check "$ARITY_A"
pair_expect_exit 0 "fmt (multiple targets)" fmt --check "$ARITY_A" "$ARITY_B"

if [ "${NATIVE_CLI_ARITY_ONLY:-}" = 1 ]; then
  [ "$fail" = 0 ] || { echo "FAIL: command arity contract"; exit 1; }
  echo "OK: command arity agrees across both backends and matches the absolute contract"
  exit 0
fi

# ---- leg 0b: run argv boundary, against absolute contracts ----
echo "== run argv boundary, JVM and native vs absolute contracts =="
RUN_ARGV="$OUT/run_argv.dawn"
cat > "$RUN_ARGV" <<'EOF'
use std/str

pub fn main() -> Unit !io = {
  println("argc=" ++ to_string(len(args())))
  var i = 0
  for arg in args() {
    println(to_string(i) ++ "|" ++ to_string(str.len(arg)) ++ "|" ++ arg)
    i = i + 1
  }
}
EOF

RUN_EMPTY=$'argc=0\n'
RUN_OPTION_LIKE=$'argc=4\n0|0|\n1|2|--\n2|9|--closure\n3|2|-o\n'

run_expect 0 "$RUN_EMPTY" "" "run (empty argv, omitted separator)" run "$RUN_ARGV"
run_expect 0 "$RUN_EMPTY" "" "run (empty argv, explicit separator)" run "$RUN_ARGV" --
run_expect 0 "$RUN_OPTION_LIKE" "" "run (opaque option-like and empty argv)" \
  run "$RUN_ARGV" -- "" -- --closure -o
run_expect 0 "$RUN_EMPTY" "" "run (compiler option before target)" \
  run --std "$ROOT/std" "$RUN_ARGV"

if [ "${NATIVE_CLI_RUN_ONLY:-}" = 1 ]; then
  [ "$fail" = 0 ] || { echo "FAIL: run argv boundary contract"; exit 1; }
  echo "OK: run argv boundary matches the absolute contract on both backends"
  exit 0
fi

# ---- leg 0c: where a command's std comes from, both drivers ----
# #291: `--std <dir>`, else DAWN_STD (non-empty), else the copy compiled into
# the toolchain; never the working directory. The inline test on
# `std_choice` in selfhost/src/driver/stdlib.dawn pins the order; this leg
# pins that both drivers' command lines reach it, on real processes and real
# directories.
#
# The probe tells the stds apart by what they compute, not by a message: a
# complete std (modules.txt and this release's VERSION, so nothing about it is
# refused) whose `str.to_upper` lowers. It sits under the working directory as
# `std/`, the exact shape that used to be loaded without being asked for.
#
# The JVM side runs the jar directly, not ./bin/dawn: the launcher exports
# DAWN_STD from its own location, so "neither" cannot be said through it.
# `env -u` takes away the DAWN_STD this script exported above.
echo "== std resolution, JVM and native vs absolute contracts =="
STDRES="$OUT/stdres"
mkdir -p "$STDRES/cwd" "$STDRES/elsewhere"
cp -R "$ROOT/std" "$STDRES/cwd/std"
STDRES_LINE='pub fn to_upper(s: String) -> String = str_upper(s)'
if [ "$(grep -cxF "$STDRES_LINE" "$STDRES/cwd/std/str.dawn")" != 1 ]; then
  echo "FAIL: std/str.dawn no longer defines to_upper as: $STDRES_LINE"
  exit 1
fi
sed -i 's/^pub fn to_upper(s: String) -> String = str_upper(s)$/pub fn to_upper(s: String) -> String = str_lower(s)/' \
  "$STDRES/cwd/std/str.dawn"
LOWERING_STD="$STDRES/cwd/std"
cat > "$STDRES/cwd/up.dawn" <<'EOF'
use std/str

pub fn main() -> Unit !io = println(str.to_upper("Hello"))
EOF
STDRES_JAVA=$(DAWN_LAUNCHER_PRINT_JAVA=1 ./bin/dawn)

## Run one argv from directory `dir`, through the jar and through dawnc, each
## with the environment given; both must print exactly `want`.
std_expect() { # want label dir env-args -- dawn-args...
  local want=$1
  local label=$2
  local dir=$3
  shift 3
  local envs=()
  while [ "$1" != -- ]; do envs+=("$1"); shift; done
  shift
  (cd "$dir" && env "${envs[@]}" "$STDRES_JAVA" -Xss512m -Xmx2g \
    -jar "$ROOT/build/dawn-selfhost.jar" "$@") > "$OUT/j.out" 2> "$OUT/j.err" \
    && PAIR_J=0 || PAIR_J=$?
  (cd "$dir" && env "${envs[@]}" "$DAWNC" "$@") > "$OUT/n.out" 2> "$OUT/n.err" \
    && PAIR_N=0 || PAIR_N=$?
  printf '%s\n' "$want" > "$OUT/expected.out"
  if [ "$PAIR_J" != 0 ] || [ "$PAIR_N" != 0 ] ||
    ! cmp -s "$OUT/j.out" "$OUT/expected.out" ||
    ! cmp -s "$OUT/n.out" "$OUT/expected.out" ||
    [ -s "$OUT/j.err" ] || [ -s "$OUT/n.err" ]
  then
    echo "FAIL: $label did not print $want on both backends (exits jvm=$PAIR_J native=$PAIR_N)"
    echo "--- JVM stdout"; diff -u "$OUT/expected.out" "$OUT/j.out" | sed -n '1,10p' || true
    echo "--- native stdout"; diff -u "$OUT/expected.out" "$OUT/n.out" | sed -n '1,10p' || true
    echo "--- JVM stderr"; head -10 "$OUT/j.err"
    echo "--- native stderr"; head -10 "$OUT/n.err"
    fail=1
  else
    echo "OK   $label ($want on both, stderr empty, exit 0)"
  fi
}

UP="$STDRES/cwd/up.dawn"
# the #291 acceptance: a complete std under the working directory changes nothing
std_expect HELLO "std (neither: the embedded copy, not ./std)" "$STDRES/cwd" \
  -u DAWN_STD -- run "$UP"
# an empty DAWN_STD names no directory
std_expect HELLO "std (empty DAWN_STD: the embedded copy)" "$STDRES/cwd" \
  DAWN_STD= -- run "$UP"
# DAWN_STD selects that directory, from a cwd with no std/ of its own, so the
# answer can only have come from the variable
std_expect hello "std (DAWN_STD selects its directory)" "$STDRES/elsewhere" \
  DAWN_STD="$LOWERING_STD" -- run "$UP"
# and --std overrides it, in both directions
std_expect HELLO "std (--std overrides DAWN_STD)" "$STDRES/elsewhere" \
  DAWN_STD="$LOWERING_STD" -- run --std "$ROOT/std" "$UP"
std_expect hello "std (--std overrides DAWN_STD, the other way)" "$STDRES/elsewhere" \
  DAWN_STD="$ROOT/std" -- run --std "$LOWERING_STD" "$UP"

if [ "${NATIVE_CLI_STD_ONLY:-}" = 1 ]; then
  [ "$fail" = 0 ] || { echo "FAIL: std resolution contract"; exit 1; }
  echo "OK: std resolution agrees across both backends and matches the absolute contract"
  exit 0
fi

# ---- leg 1: fmt, against the previous release ----
echo "== fmt vs N-1, native backend =="
DAWN_SELF="$DAWNC" ./scripts/selfhost-fmt-diff.sh

# `fmt --check` is a transcript, not a tree: it prints the unformatted files.
# Their order comes from a directory walk, and io.list_dir does not return the
# same order on both backends (#114) — the drivers sort, and this is what says
# so. A directory of deliberately mangled sources makes the list non-empty.
CHK="$OUT/fmtcheck"
mkdir -p "$CHK/b/c"
i=0
while IFS= read -r -d '' f; do
  if [ ! -f "$f" ]; then
    if git ls-files --deleted --error-unmatch -- "$f" > /dev/null 2>&1; then
      continue
    fi
    echo "ERROR: tracked Dawn corpus entry is unreadable: $f" >&2
    exit 1
  fi
  i=$((i + 1))
  if [ "$i" -gt 24 ]; then break; fi
  case $((i % 3)) in
    0) d="$CHK" ;;
    1) d="$CHK/b" ;;
    *) d="$CHK/b/c" ;;
  esac
  sed -e 's/^[[:space:]]*//' -e 's/   */ /g' "$f" > "$d/$i.dawn"
done < <(git ls-files -z 'selfhost/src/*.dawn')
pair "fmt --check (walk order)" fmt --check "$CHK"
pair "fmt --check (a clean file)" fmt --check "$ROOT/selfhost/src/version.dawn"

# ---- leg 2: doc, against HEAD's JVM driver ----
echo "== doc, JVM vs native =="
pair "doc --builtins" doc --builtins
pair "doc --stdlib" doc --stdlib
pair "doc (traits example)" doc examples/traits/traits.dawn
pair "doc (multi-module project)" doc packages/json
pair "doc (single-module package)" doc packages/sha2

# a pub effect and its operations reach the JSON; a private one does not (#115)
cat > "$OUT/effects_doc.dawn" <<'EOF'
## Answer questions from ambient context.
pub effect Ask {
  ## The context's number.
  fn ask(prompt: String) -> Int
  fn tell(n: Int) -> Unit
}

effect Hidden {
  fn peek() -> Int
}

pub fn main() -> Unit !io = println("ok")
EOF
pair "doc (pub effect)" doc "$OUT/effects_doc.dawn"

# error paths: compile errors (no count line) and a manifest the loader
# rejects. The usage and missing-target refusals of these two subcommands are
# inline tests now (see this file's header); what is left needs a real
# compile, which is what a table cannot answer.
cat > "$OUT/broken.dawn" <<'EOF'
fn f(x: Int) -> String = x + 1

pub fn main() -> Unit !io = {
  let y = undefined_fn(2)
  println(f(3))
}
EOF
BADMF="$OUT/badmf"
mkdir -p "$BADMF/src"
printf 'name = "x"\nschema = 1\nweird = true\n\n[stuff]\na = 1.5\n' > "$BADMF/dawn.toml"
printf 'pub fn main() -> Unit !io = println("hi")\n' > "$BADMF/src/main.dawn"
pair "doc (compile errors)" doc "$OUT/broken.dawn"
pair "doc (manifest diagnostics)" doc "$BADMF"

# fmt's two refusals (#189). Both are in-place-write guards, so the pairing is
# not only "same message" but "same file afterwards": the check below re-reads
# the inputs, which both drivers have now been handed.
printf 'hello\n' > "$OUT/plain.txt"
printf 'fn main() -> Unit !io = {\n  let x = 1 \\ 2\n  let a = 1; let b = 2\n}\n' > "$OUT/nolex.dawn"
cp "$OUT/plain.txt" "$OUT/plain.orig"
cp "$OUT/nolex.dawn" "$OUT/nolex.orig"
pair "fmt (a named file that is not .dawn)" fmt "$OUT/plain.txt"
pair "fmt (a file that does not lex)" fmt "$OUT/nolex.dawn"
pair "fmt --check (a file that does not lex)" fmt --check "$OUT/nolex.dawn"
if ! cmp -s "$OUT/plain.txt" "$OUT/plain.orig" || ! cmp -s "$OUT/nolex.dawn" "$OUT/nolex.orig"; then
  echo "FAIL: fmt rewrote a file it refused (this is the bug the refusals exist to stop)"
  fail=1
else
  echo "OK   fmt left both refused files byte-identical"
fi

# check, whose exit status is its answer since #189. The JVM driver hands the
# checker the reflecting `use java` hook and the native one refuses it, so this
# pairing holds only for a target free of `use java` -- which packages/sha2 and
# the broken fixture both are.
pair "check (a clean target)" check packages/sha2
pair "check (diagnostics)" check "$OUT/broken.dawn"

# version -m: one Planner and one listing format (docs/build-info-design.md
# §八). The binary under test is listed from outside by both drivers, so the
# JVM's reading of its manifest section and the native one are compared too
# (or both refusals, when the binary was linked without the manifest unit).
pair "version -m (a project)" version -m packages/sha2
pair "version -m (the binary under test)" version -m "$DAWNC"

# ---- leg 3: add, against HEAD's JVM driver ----
# Both sides edit a fresh copy of the same project, so the summary line and
# the rewritten dawn.toml must both come out identical.
echo "== add, JVM vs native =="
PKG="$OUT/greeter-src"
mkdir -p "$PKG/src"
printf 'schema = 1\nname = "greeter"\nversion = "1.0.0"\n' > "$PKG/dawn.toml"
cat > "$PKG/src/hello.dawn" <<'EOF'
pub fn greet(who: String) -> String = "hello, " ++ who
EOF
HASH=$(./bin/dawn __pkghash "$PKG")
python3 - "$PKG" "$OUT/greeter.zip" <<'EOF'
import os, sys, zipfile
src, dst = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(dst, 'w') as z:
    for root, _, files in os.walk(src):
        for f in sorted(files):
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, src))
EOF

ADDT="$OUT/add-template"
mkdir -p "$ADDT/src"
printf '# my app\nschema = 1\nname = "app"   # keep\n' > "$ADDT/dawn.toml"
printf 'pub fn main() -> Unit !io = println("x")\n' > "$ADDT/src/main.dawn"
PROJ="$OUT/addproj"

add_pair() { # label spec...
  label=$1; shift
  rm -rf "$PROJ"; cp -r "$ADDT" "$PROJ"
  DAWN_PKG_CACHE="$OUT/pkgcache-j" ./bin/dawn add "$@" --dir "$PROJ" > "$OUT/j.txt" 2>&1 && j=0 || j=$?
  cp "$PROJ/dawn.toml" "$OUT/j.toml"
  rm -rf "$PROJ"; cp -r "$ADDT" "$PROJ"
  DAWN_PKG_CACHE="$OUT/pkgcache-n" "$DAWNC" add "$@" --dir "$PROJ" > "$OUT/n.txt" 2>&1 && n=0 || n=$?
  if ! diff "$OUT/j.toml" "$PROJ/dawn.toml" > "$OUT/t.txt"; then
    echo "FAIL: $label rewrote dawn.toml differently"
    head -20 "$OUT/t.txt"
    fail=1
  fi
  if [ "$j" != "$n" ] || ! diff "$OUT/j.txt" "$OUT/n.txt" > "$OUT/d.txt"; then
    echo "FAIL: $label differs between backends (exits jvm=$j native=$n)"
    head -20 "$OUT/d.txt"
    fail=1
  else
    echo "OK   $label (exit $j)"
  fi
}

add_pair "add (local path dep)" "$PKG"
add_pair "add (maven coordinate)" "org.ow2.asm:asm:9.7.1"
# the url dep exercises curl, the zip reader and the d1 hash on both backends
add_pair "add (url dep, aliased)" "file://$OUT/greeter.zip" --as g
add_pair "add (bad coordinate)" "a::c"
add_pair "add (usage)" --as g

BADTOML="$OUT/badtoml"
mkdir -p "$BADTOML/src"
printf 'schema = 1\nname = "x\nver = 1.5.2\n' > "$BADTOML/dawn.toml"
printf 'pub fn main() -> Unit !io = println("hi")\n' > "$BADTOML/src/main.dawn"
pair "add (invalid manifest)" add ../nowhere --dir "$BADTOML"

# ---- leg 4: lsp, against the previous release ----
# Same shape as leg 1: the whole scripted session, the N-1 oracle, the subject
# swapped for the native binary. Every message of that session is produced by
# server/lspq/lspc running on the C backend.
echo "== lsp vs N-1, native backend =="
DAWN_SELF="$DAWNC" ./scripts/selfhost-lsp-diff.sh

# ---- leg 4b: raw LSP framing, native backend independently ----
# The transcript above starts from valid frames and normalizes JSON. Run the
# byte-level framing contract directly against the release artifact as well;
# the ordinary gates run the same script against the JVM driver.
echo "== lsp framing boundaries, native backend =="
if LSP_FRAMING_LABEL=native ./scripts/lsp-framing.py "$DAWNC" lsp; then :; else fail=1; fi

# ---- leg 5: lsp answers a client that has not closed the connection ----
# selfhost-lsp-diff.sh writes the whole session, closes stdin and reads the
# transcript at EOF, so it cannot see *when* a byte left the server — and a
# server that only flushes at exit produces a byte-identical transcript while
# hanging every real editor. That is what the native backend did when `lsp`
# was first wired: stdout is block-buffered there and nothing flushed, so the
# initialize response sat in a 64 KiB buffer forever. The runtime now copies
# System.out's autoflush rule; this is the check that says so.
echo "== lsp responds before end of input, both backends =="
if python3 - "$DAWNC" <<'PYEOF'
import json, os, select, signal, subprocess, sys, time
body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"processId": None, "rootUri": None, "capabilities": {}}}).encode()


def reap(p):
    """Kill the process GROUP, not the process.

    ./bin/dawn is a launcher that rebuilds the toolchain in a child JVM before
    it execs the driver, so a kill landing mid-rebuild reaps the wrapper and
    leaves the compile running. Same rule as leg 8 and scripts/lsp-liveness.py:
    what was spawned as a session gets killed as a session."""
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except OSError:
        p.kill()
    p.wait()


bad = 0
for label, cmd in [("jvm", ["./bin/dawn", "lsp"]), ("native", [sys.argv[1], "lsp"])]:
    # own session, so `reap` below has a group to aim at
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    p.stdin.write(b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
    p.stdin.flush()  # and leave it open, the way a client holds the session
    t0 = time.time()
    ready = select.select([p.stdout], [], [], 60.0)[0]
    head = p.stdout.read(16) if ready else b""
    reap(p)
    if head.startswith(b"Content-Length:"):
        print("OK   lsp %s answered in %.2fs with stdin still open" % (label, time.time() - t0))
    else:
        print("FAIL: lsp %s wrote nothing in 60s with stdin still open" % label)
        bad = 1
sys.exit(bad)
PYEOF
then :; else fail=1; fi

# ---- leg 6: test, against HEAD's JVM driver ----
# Unlike doc/add, the thing under comparison here is *not* shared code. A test
# block is not Dawn-callable, so neither backend can write the runner in Dawn:
# the JVM synthesises a dawn$TestMain class with ASM (testrun.dawn) and native
# generates C (ctestrun.dawn). Two independent implementations of one report,
# so this leg is double-entry on the report shape rather than a check that one
# implementation was reached twice. The other half of the chain is
# selfhost-run-diff.sh, which already pins the JVM's `dawn test` to N-1
# (green suite, failing fixture, no-test error, usage).
#
# A test runner is the one gate where "green" is least informative: a runner
# that executes nothing prints the same thing as a runner where everything
# passed. That is not a worry, it is measured — a mutant whose thunk never
# calls the test body left `test (multi-module package)` and
# `test (single-module package)` GREEN, summary count and all, and was caught
# only by the two failing fixtures below.
#
# So: **the failing fixtures are the load-bearing cases of this leg.** A
# report that names a failure and its assertion text cannot have been produced
# without running the test; "6 test(s) passed" can. Do not delete them, and do
# not let this leg become an all-green corpus.
#
# Three things beyond byte equality are checked here, one per way a runner can
# be vacuous. `pair_report` holds the report to its own count; `test
# (assertions are evaluated)` puts the side effects outside the report
# entirely; and the flush check says the report exists before the process
# does.
echo "== test, JVM vs native =="

## `pair`, and then: each backend's report has to account for itself.
##
## The summary line is not evidence of execution. "N test(s) passed" is a
## generation-time constant on both backends — an LDC on the JVM, a static
## dawn_str in the generated C — so a runner that called nothing prints the
## same summary as a runner where everything passed. The PASS/FAIL lines are
## the part that costs one call each, so they are counted and held to the
## summary's number, and the failure count is held to the FAIL lines.
##
## This runs on both transcripts separately, not on the diff: two runners that
## both print a summary and no report lines agree with each other perfectly.
pair_report() { # label args...
  pair "$@"
  label=$1
  for side in j n; do
    if python3 - "$OUT/$side.txt" "$label" "$side" <<'PYEOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
label, side = sys.argv[2], sys.argv[3]
reported = sum(1 for ln in text if ln.startswith("PASS  "))
failed = sum(1 for ln in text if ln.startswith("FAIL  "))
passed_re = re.compile(r"^(\d+) test\(s\) passed$")
failed_re = re.compile(r"^(\d+) of (\d+) test\(s\) failed$")
summary = [ln for ln in text if passed_re.match(ln) or failed_re.match(ln)]
if len(summary) != 1:
    print("FAIL: %s (%s) has %d summary lines, want 1" % (label, side, len(summary)))
    sys.exit(1)
m = passed_re.match(summary[0])
if m:
    total, want_failed = int(m.group(1)), 0
else:
    m = failed_re.match(summary[0])
    want_failed, total = int(m.group(1)), int(m.group(2))
if total == 0:
    print("FAIL: %s (%s) claims a suite of 0 tests" % (label, side))
    sys.exit(1)
if reported + failed != total:
    print("FAIL: %s (%s) reported %d PASS + %d FAIL lines, summary says %d"
          % (label, side, reported, failed, total))
    sys.exit(1)
if failed != want_failed:
    print("FAIL: %s (%s) printed %d FAIL lines, summary says %d failed"
          % (label, side, failed, want_failed))
    sys.exit(1)
print("OK   %s (%s accounts for all %d)" % (label, side, total))
PYEOF
    then :; else fail=1; fi
  done
}

# a multi-module suite (labels get the `mod :: name` prefix) and a single one
pair_report "test (multi-module package)" test packages/json
pair_report "test (single-module package)" test packages/sha2
# tea-core's tests hoist a derived Int equality wrapper after the production
# functions. Its dictionary parameter is the exact boundary that used to share
# a symbol with rc_module's first emitted local, so compiling this suite on the
# native side is the regression oracle as well as another report comparison.
pair_report "test (test-hoisted dictionary symbols)" test packages/tea-core
# the bundled std's own suite. This is the only place the native backend runs
# it: gates.yml calls `./bin/dawn test --stdlib`, which is the JVM and only
# the JVM, and std is where "both backends answer the same" is least optional
# -- the case tables, the cursor walk and the surrogate-pair arithmetic are
# each written once per backend.
pair_report "test (the bundled std)" test --stdlib
# --cp names host jars. The native driver validates the entries the way the
# JVM one does and then drops them: they can only matter to a `use java`
# program, which this backend refuses at `check`. Both spellings of an entry
# that exists; the two refusals are inline tests now (see this file's header),
# and these two are what says the accepted spelling still compiles.
pair "test (--cp, entry exists)" test --cp "$ROOT/runtime/c" packages/sha2
pair "test (--cp=, entry exists)" test "--cp=$ROOT/runtime/c" packages/sha2

# the failing path: report shape, six-space message indentation, the count
# line and exit 1. `selfhost-run-diff.sh` has the same fixture against N-1.
cat > "$OUT/failing.dawn" <<'EOF'
fn double(x: Int) -> Int = x * 2

test "doubling four" {
  assert double(4) == 8
}

test "a deliberate failure" {
  assert double(3) == 7
}
EOF
pair_report "test (a failing fixture)" test "$OUT/failing.dawn"

# a panic message with newlines and a quote in it: the JVM splits on "\n" and
# indents each line, and the C runner walks the bytes to the same effect. The
# quote is there because the label and the message travel through two
# different escapers (LDC on one side, a C string literal on the other).
#
# The long one is over 512 bytes on purpose: the native runtime used to
# truncate a caught failure at a fixed buffer size (#193 ARC-03) and every
# message here stayed under it, so the runner never saw the divergence. The
# payload owns a real string now, and this line is what keeps it owning one.
cat > "$OUT/messages.dawn" <<'EOF'
use std/str

pub fn lines() -> Int = panic("first line\nsecond line\nthird")

pub fn quoted() -> Int = panic("a \"quoted\" message")

pub fn blank() -> Int = panic("")

pub fn long() -> Int = panic(str.repeat("long-", 130) ++ "|END")

test "a multi-line message is indented a line at a time" {
  assert lines() == 1
}

test "a quote survives both escapers" {
  assert quoted() == 1
}

test "an empty message is still one line" {
  assert blank() == 1
}

test "a message past 512 bytes arrives whole" {
  assert long() == 1
}
EOF
pair_report "test (failure message shapes)" test "$OUT/messages.dawn"

# the one error path of this subcommand that needs a real compile to reach:
# the target names a file that is Dawn, is readable, and has nothing to run.
# The usage, missing-target and wrong-suffix refusals are inline tests now
# (see this file's header).
printf 'fn g() -> Int = 2\n' > "$OUT/notest.dawn"
pair "test (no test blocks)" test "$OUT/notest.dawn"

# ---- leg 7: the assertions are evaluated, not just reported on ----
# Every check above reads the runner's own report, and a report is what a
# vacuous runner is best at producing. This fixture puts the evidence outside
# it: each assertion goes through `note`, which drops a file named after its
# tag. The files are counted after the run, in a directory each backend gets
# to itself, so "the assertion ran" is answered by the filesystem rather than
# by the thing under test.
#
# The middle test fails on its *second* assertion, which pins two more things
# an all-green fixture cannot: the first assertion of a failing test still
# runs, and a failure does not stop the suite (`d` is dropped by the test
# after it).
echo "== test, the assertions really run =="
cat > "$OUT/sidefx.dawn" <<'EOF'
use std/io
use std/io.{Fs}

pub fn note(tag: String) -> Bool !Fs !io = {
  println("  side effect: " ++ tag)
  let _ = io.write_file("MARK-" ++ tag, tag)
  true
}

test "the first test's assertion is evaluated" {
  io.with_fs_real(() => {
    assert note("a")
  })
}

test "the second test evaluates both of its assertions, then fails" {
  io.with_fs_real(() => {
    assert note("b")
    assert note("c") && false
  })
}

test "a third test runs even though the second one failed" {
  io.with_fs_real(() => {
    assert note("d")
  })
}
EOF
# --std is absolute because each side runs from its own directory; the argv
# stays identical across the two, which is what makes this a differential
rm -rf "$OUT/sfx-j" "$OUT/sfx-n"
mkdir -p "$OUT/sfx-j" "$OUT/sfx-n"
(cd "$OUT/sfx-j" && "$ROOT/bin/dawn" test --std "$ROOT/std" "$OUT/sidefx.dawn") \
  > "$OUT/j.txt" 2>&1 && jx=0 || jx=$?
(cd "$OUT/sfx-n" && "$DAWNC" test --std "$ROOT/std" "$OUT/sidefx.dawn") \
  > "$OUT/n.txt" 2>&1 && nx=0 || nx=$?
jm=$(cd "$OUT/sfx-j" && ls | tr '\n' ' ')
nm=$(cd "$OUT/sfx-n" && ls | tr '\n' ' ')
if [ "$jx" != 1 ] || [ "$nx" != 1 ]; then
  echo "FAIL: the side-effect fixture must exit 1 on both (jvm=$jx native=$nx)"
  fail=1
elif [ "$jm" != "MARK-a MARK-b MARK-c MARK-d " ] || [ "$nm" != "$jm" ]; then
  echo "FAIL: assertions were skipped (jvm left [$jm], native left [$nm])"
  fail=1
elif ! diff "$OUT/j.txt" "$OUT/n.txt" > "$OUT/d.txt"; then
  echo "FAIL: test (assertions are evaluated) differs between backends"
  head -20 "$OUT/d.txt"
  fail=1
else
  echo "OK   test (assertions are evaluated: both left $jm, exit 1)"
fi

# ---- leg 8: the report reaches stdout before the process ends ----
# The same hazard leg 5 caught in `lsp`, in the form it takes here. The C
# runtime block-buffers stdout (dawn_rt_init, 64 KiB), and every check above
# reads the transcript after the process is gone — so a runner that only
# flushed at exit would be byte-identical to one that reports as it goes,
# while showing a user watching a hung suite nothing at all. A suite that
# hangs or is killed is exactly when the report matters most.
#
# Two tests report, the third does not return, both backends get SIGKILLed.
# What is on stdout at that point is the whole answer: `dawn_io_println`
# flushes per line (the fix leg 5 forced), so it is the two PASS lines.
echo "== test, the report is flushed as it goes =="
cat > "$OUT/hang.dawn" <<'EOF'
fn spin(n: Int) -> Int = {
  var i = 0
  var acc = 0
  while i < n {
    acc = (acc + i) % 1000003
    i = i + 1
  }
  acc
}

test "one reports before the hang" {
  assert spin(10) == 45
}

test "two reports before the hang" {
  assert spin(10) == 45
}

test "three never finishes" {
  assert spin(1000000000000000) == -1
}
EOF
# Read the pipe while the runner is still alive rather than after a fixed
# timeout: the native side compiles the program before it runs it, and a
# budget large enough for that build would be a budget the check could pass by
# waiting rather than by flushing. The window starts when the first byte
# arrives.
if python3 - "$DAWNC" "$ROOT" "$OUT/hang.dawn" <<'PYEOF'
import os, select, signal, subprocess, sys, time
dawnc, root, fixture = sys.argv[1], sys.argv[2], sys.argv[3]


def reap(p):
    """Kill the process GROUP, not the process.

    Neither driver runs the tests itself: the JVM one spawns `java
    dawn$TestMain` over freshly emitted classes and waits (main.dawn,
    spawn_java), and the native one builds a binary under /tmp/dawnc-test.*
    and runs it (nmain.dawn, build_and_exec). A SIGKILL to the driver cannot
    be caught -- no shutdown hook, no `finally` -- so it takes the waiter and
    leaves the grandchild, which is the one process here that never returns by
    construction. Measured: `p.kill()` left a dawn$TestMain and a
    /tmp/dawnc-test.*/tests burning a core each, long after this script had
    printed OK and exited; several accumulated over a few gate runs, and the
    native ones also kept dcap's fixed-name build scope alive (its cgroup is
    non-empty until they die), blocking every later build on the box.

    So the kill has to reach whatever the driver started. Both drivers spawn
    without touching the process group, so start_new_session plus killpg is
    exactly the whole subtree -- the rule scripts/lsp-liveness.py already
    follows for the same reason."""
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except OSError:
        p.kill()
    p.wait()


bad = 0
got = {}
for label, cmd in [("jvm", [root + "/bin/dawn"]), ("native", [dawnc])]:
    # own session, so `reap` below has a group to aim at
    p = subprocess.Popen(cmd + ["test", "--std", root + "/std", fixture],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         start_new_session=True)
    # Five minutes for the first byte, because the native side compiles the
    # program before it runs it (measured at well under one). Then 30 seconds
    # to see the rest of what a hung suite is supposed to have said. A runner
    # that never flushes spends the whole first budget, so a red here is slow
    # on purpose rather than by accident.
    seen, deadline, t0 = b"", time.time() + 300.0, None
    while time.time() < deadline:
        if not select.select([p.stdout], [], [], deadline - time.time())[0]:
            break
        chunk = p.stdout.read1(4096)
        if not chunk:
            break
        if t0 is None:
            t0, deadline = time.time(), time.time() + 30.0
        seen += chunk
        if seen.count(b"PASS  ") >= 2:
            break
    reap(p)
    got[label] = seen.decode("utf-8", "replace")
    n = got[label].count("PASS  ")
    if n == 2:
        print("OK   test %s printed both reports %.2fs into a run that never ends"
              % (label, time.time() - t0))
    else:
        print("FAIL: test %s had %d reports on stdout when it was killed, want 2"
              % (label, n))
        print(got[label])
        bad = 1
if got["jvm"] != got["native"]:
    print("FAIL: what survived the kill differs between backends")
    print("jvm:    %r" % got["jvm"])
    print("native: %r" % got["native"])
    bad = 1
sys.exit(bad)
PYEOF
then :; else fail=1; fi

# ---- leg 9: cache verify and __pkghash, against absolute contracts ----
# Both drivers call the same pkg/cachecmd functions with the raw argv tail
# (#304), so what this leg holds apart is the backend: the C build of that
# module against the JVM one, on a real cache and a real tree. The cases that
# can carry an oracle of their own do; the d1 hash is recomputed here in
# Python from its definition (pkgfetch.tree_hash), so a bug both backends
# share in the hash cannot pass as agreement.
echo "== cache verify and __pkghash, JVM and native =="
CACHE_USAGE=$'error: usage: dawn cache verify\n'
pair_expect_error "$CACHE_USAGE" "cache (no argument)" cache
pair_expect_error "$CACHE_USAGE" "cache (wrong argument)" cache check

CACHE_NONE="$OUT/pkgcache-none"
CACHE_EMPTY="$OUT/pkgcache-empty"
mkdir -p "$CACHE_EMPTY"
DAWN_PKG_CACHE="$CACHE_NONE" run_expect 0 "cache is empty ($CACHE_NONE)"$'\n' "" \
  "cache verify (no cache directory)" cache verify
DAWN_PKG_CACHE="$CACHE_EMPTY" run_expect 0 $'0 entries checked, 0 bad\n' "" \
  "cache verify (empty cache directory)" cache verify

# The cache leg 3's url dep filled, copied so that neither add_pair cache is
# touched, plus a copy of its entry filed under a name it does not hash to.
CACHE_FULL="$OUT/pkgcache-verify"
cp -r "$OUT/pkgcache-j" "$CACHE_FULL"
GOOD_ENTRY=$(cd "$CACHE_FULL" && ls -d d1-* 2>/dev/null | sed -n 1p)
if [ -z "$GOOD_ENTRY" ]; then
  echo "FAIL: leg 3 left no d1 entry in $OUT/pkgcache-j to verify"
  fail=1
else
  BAD_ENTRY=d1-0000000000000000000000000000000000000000000000000000000000000000
  cp -r "$CACHE_FULL/$GOOD_ENTRY" "$CACHE_FULL/$BAD_ENTRY"
  DAWN_PKG_CACHE="$CACHE_FULL" pair_expect_exit 1 "cache verify (populated, one entry bad)" cache verify
  if ! grep -qx "ok   $GOOD_ENTRY" "$OUT/j.txt" || ! grep -qx "BAD  $BAD_ENTRY" "$OUT/j.txt" ||
    ! grep -qx "2 entries checked, 1 bad" "$OUT/j.txt"; then
    echo "FAIL: cache verify (populated) did not report one ok, one BAD, two checked"
    head -20 "$OUT/j.txt"
    fail=1
  fi
fi

D1_ORACLE=$(python3 - "$PKG" <<'PYEOF'
import hashlib, os, sys
root = sys.argv[1]
files = []
for dirpath, _, names in os.walk(root):
    for n in names:
        files.append(os.path.relpath(os.path.join(dirpath, n), root))
h = hashlib.sha256()
for rel in sorted(files):
    data = open(os.path.join(root, rel), "rb").read()
    h.update(rel.encode() + b"\0" + str(len(data)).encode() + b"\0" + data)
print("d1:" + h.hexdigest())
PYEOF
)
run_expect 0 "$D1_ORACLE"$'\n' "" "__pkghash (fixture directory)" __pkghash "$PKG"

PKGHASH_MISSING="$OUT/no-such-package"
pair_expect_error "error: not a directory: $PKGHASH_MISSING"$'\n' \
  "__pkghash (missing path)" __pkghash "$PKGHASH_MISSING"

# ---- leg 10: comptime recursion stops at one depth limit on both ----
#
# A comptime call nests host frames, and the two compilers' host stacks hold
# different numbers of them: the native compiler runs on a 512 MiB
# continuation carrier (every subcommand runs inside io's `Exit` handler, a
# `ctl` handler; see leg 11), the JVM one on -Xss512m, and the native frames
# are the bigger ones. Until 2026-10-04 each compiler had its own limit (JVM
# 100,000, native 1,500), so a recursion between the two folded on one and
# was refused by the other. ir/interp MAX_CALL_DEPTH is now one number, set
# under what the native stack holds, and both drivers must give a program
# near it the same answer.
#
# Three judgments, each the same bytes and exit code from both drivers. Past
# the limit, both answer with the depth diagnostic, not a signal. The
# heaviest call shape measured when the limit was set folds ten calls under
# it (headroom for `rec`'s own caller), so neither raising the limit nor
# fattening the interpreter's frames can put the native stack back in front
# of the counter without this going red. At the limit, the same shape is
# refused by both, so the limit both report is the one both enforce.
echo "== comptime depth limit, JVM and native =="
DEPTH_DEEP="$OUT/depth_deep.dawn"
cat > "$DEPTH_DEEP" <<'EOF'
fn down(n: Int) -> Int = if n == 0 { 0 } else { 1 + down(n - 1) }

const D: Int = down(20000)

pub fn main() -> Unit !io = println("${D}")
EOF
pair_expect_exit 1 "comptime depth (past the limit)" check "$DEPTH_DEEP"
DEPTH_LIMIT=$(sed -n 's/^error: comptime: call depth limit (\([0-9]*\)) exceeded$/\1/p' "$OUT/n.txt" | sed -n 1p)
if [ -z "$DEPTH_LIMIT" ]; then
  echo "FAIL: comptime depth (past the limit): no depth diagnostic"
  head -5 "$OUT/n.txt"
  fail=1
else
  # a block, a `let` and a `match` per level: the heaviest of the shapes
  # measured for MAX_CALL_DEPTH
  depth_heavy() { # n -> path of a program folding rec(n)
    local f="$OUT/depth_heavy_$1.dawn"
    cat > "$f" <<EOF
fn rec(n: Int) -> Int = {
  if n == 0 { return 0 }
  let a = n * 2
  match a % 3 {
    0 -> {
      let b = rec(n - 1)
      b + 1
    }
    _ -> {
      let c = [a, n]
      let b = rec(n - 1)
      b + len(c)
    }
  }
}

const D: Int = rec($1)

pub fn main() -> Unit !io = println("\${D}")
EOF
    echo "$f"
  }
  pair_expect_exit 0 "comptime depth (heaviest shape, ten under the limit of $DEPTH_LIMIT)" \
    check "$(depth_heavy $((DEPTH_LIMIT - 10)))"
  pair_expect_exit 1 "comptime depth (heaviest shape, at the limit of $DEPTH_LIMIT)" \
    check "$(depth_heavy "$DEPTH_LIMIT")"
fi

# ---- leg 11: deep source nesting fits the compiler's stack ----
#
# Parsing and checking recurse on the source's nesting, and no counter bounds
# that: only the stack does. The native compiler runs on a continuation
# carrier (leg 10), and while that carrier was 64 MiB a right-nested input of
# about 62 KB, inside the Playground LSP's 64 KiB source limit, killed `dawnc
# check` and `dawnc lsp` with SIGSEGV and no output. The carrier is now
# DAWN_CTL_STACK_BYTES = DAWN_STACK_BYTES (runtime/c/dawn_rt.c), the JVM's
# -Xss512m. 15,000 nested calls is 45 KB of source; measured on 2026-10-04 it
# checks in about 1 s and 195 MB on the native compiler and crashes it from
# about 10,000 levels on a 64 MiB carrier, so shrinking the carrier back turns
# this red. This shape and not nested parentheses: those cost the same stack
# per level but 20 to 30 s at the depth that crashed.
echo "== deep source nesting, JVM and native =="
DEEP_NEST="$OUT/deep_nest.dawn"
python3 - "$DEEP_NEST" <<'PYEOF'
import sys
n = 15000
with open(sys.argv[1], "w") as f:
    f.write("fn g(x: Int) -> Int = x\n")
    f.write("fn f() -> Int = " + "g(" * n + "1" + ")" * n + "\n")
    f.write('pub fn main() -> Unit !io = println("${f()}")\n')
PYEOF
pair_expect_exit 0 "check (15,000 nested calls)" check "$DEEP_NEST"

# ---- leg 12: hover folds an expression to the same value on both servers ----
#
# Hover shows the value of a closed, pure expression (docs/lsp-hover-design.md
# §C5), folded by the comptime interpreter under the editor's budget,
# ir/interp `ct_hover`: the same fuel and a call depth of 1,500 on both hosts,
# below the 5,000 both language servers give their own analysis (`ct_lsp`).
# A server that folded a hover with that budget would answer `down(1600)`,
# and one whose host budget drifted from the other's would make VS Code and
# the Playground disagree about the same line. Leg 4 runs the session's hovers on native too, but
# against the previous release, and an Emit-Change can stand in for it; this
# leg has no such hatch, for the reason given at the top: two backends that
# disagree at one commit are a bug. Each hover point must answer the same on
# both, a value must actually be shown (so two servers that folded nothing
# cannot agree vacuously), and the call just past the editor's depth must
# show none on either.
echo "== hover folds, JVM vs native =="
cat > "$OUT/evals.dawn" <<'EOF'
const LIMIT: Int = 10

fn fib(n: Int) -> Int = if n < 2 { n } else { fib(n - 1) + fib(n - 2) }

fn down(n: Int) -> Int = if n == 0 { 0 } else { 1 + down(n - 1) }

fn spin(n: Int) -> Int = {
  var i = 0
  var acc = 0
  while i < n {
    acc = acc + i
    i = i + 1
  }
  acc
}

pub fn probe(k: Int) -> Int = {
  let a = fib(15) + 1
  let b = "n=${fib(10)} limit=${LIMIT}"
  let c = map([1, 2, 3], x => x * x)
  let e = k + 1
  let h = spin(60000) + 3
  let i = down(1600) + 4
  let j = down(1400) + 5
  let _ = b
  a + j + e + h + i + len(c)
}
EOF
if python3 - "$DAWNC" "$OUT/evals.dawn" <<'PYEOF'
import json, subprocess, sys

sys.path.insert(0, "scripts")
from lsp_hover import hover_code

dawnc, path = sys.argv[1:]
text = open(path).read()
uri = "file://" + path
points = [
    ("fib(15) + 1", 8),
    ('"n=', 0),
    ("map([1, 2, 3]", 3),
    ("k + 1", 2),
    ("spin(60000) + 3", 12),
    ("down(1600) + 4", 11),
    ("down(1400) + 5", 11),
]

def pos(needle, delta):
    i = text.index(needle) + delta
    line = text.count("\n", 0, i)
    return {"line": line, "character": i - (text.rfind("\n", 0, i) + 1)}

msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
         "params": {"processId": None, "rootUri": None, "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": uri, "languageId": "dawn", "version": 1, "text": text}}}]
for k, (needle, delta) in enumerate(points):
    msgs.append({"jsonrpc": "2.0", "id": k + 1, "method": "textDocument/hover",
                 "params": {"textDocument": {"uri": uri}, "position": pos(needle, delta)}})
msgs.append({"jsonrpc": "2.0", "id": 99, "method": "shutdown", "params": None})
msgs.append({"jsonrpc": "2.0", "method": "exit", "params": {}})
payload = b"".join(b"Content-Length: %d\r\n\r\n%s" % (len(b), b)
                   for b in (json.dumps(m).encode() for m in msgs))

def hovers(cmd):
    data = subprocess.run(cmd, input=payload, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=300).stdout
    got, i = {}, 0
    while True:
        j = data.find(b"\r\n\r\n", i)
        if j < 0:
            break
        n = int(data[i:j].decode().split(":", 1)[1])
        f = json.loads(data[j + 4:j + 4 + n].decode())
        i = j + 4 + n
        if isinstance(f.get("id"), int) and 1 <= f["id"] <= len(points):
            got[f["id"]] = hover_code(f.get("result"))
    return [got.get(k + 1) for k in range(len(points))]

jvm = hovers(["./bin/dawn", "lsp"])
native = hovers([dawnc, "lsp"])
bad = 0
for (needle, _), j, n in zip(points, jvm, native):
    if j != n:
        print("FAIL: hover at %r: jvm %r, native %r" % (needle, j, n))
        bad = 1
if not any(j and " = " in j for j in jvm):
    print("FAIL: no hover showed a value: %r" % (jvm,))
    bad = 1
deep = jvm[[p for p, _ in points].index("down(1600) + 4")]
if deep is None or " = " in deep:
    print("FAIL: down(1600) folded past the editor's depth: %r" % (deep,))
    bad = 1
if not bad:
    print("OK   hover folds agree at %d points: %s" % (len(points), "; ".join(map(str, jvm))))
sys.exit(bad)
PYEOF
then :; else fail=1; fi

# ---- leg 13: left-out default arguments fold to the same values on both servers ----
#
# An inlay hint for left-out default arguments shows their values where they
# fold (docs/lsp-hover-design.md §C4), under the same editor budget as hover.
# Same reasoning as leg 12, for the other caller of that budget: both servers
# must give the same labels, some label must carry a value (`gap: 4`, not the
# text `gap: GAP`), and the default just past the editor's depth must stay
# its text on both.
echo "== default argument values, JVM vs native =="
cat > "$OUT/dvalues.dawn" <<'EOF'
const GAP: Int = 4

fn down(n: Int) -> Int = if n == 0 { 0 } else { 1 + down(n - 1) }

fn sep(s: String, gap: Int = GAP, wide: Int = GAP * 2 + 1, tag: String = "<${GAP}>") -> String = s

fn span(lo: Int = 1, hi: Int = lo + 9) -> Int = hi - lo

fn near(n: Int, k: Int = down(1400)) -> Int = n + k

fn far(n: Int, k: Int = down(1600)) -> Int = n + k

pub fn probe(s: String) -> Int = {
  let a = sep(s)
  let b = span(lo: 5)
  let c = near(1)
  let d = far(1)
  len([a]) + b + c + d
}
EOF
if python3 - "$DAWNC" "$OUT/dvalues.dawn" <<'PYEOF'
import json, subprocess, sys

dawnc, path = sys.argv[1:]
text = open(path).read()
uri = "file://" + path
msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
         "params": {"processId": None, "rootUri": None, "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
            "uri": uri, "languageId": "dawn", "version": 1, "text": text}}},
        {"jsonrpc": "2.0", "id": 1, "method": "textDocument/inlayHint", "params": {
            "textDocument": {"uri": uri}, "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": text.count("\n") + 1, "character": 0}}}},
        {"jsonrpc": "2.0", "id": 99, "method": "shutdown", "params": None},
        {"jsonrpc": "2.0", "method": "exit", "params": {}}]
payload = b"".join(b"Content-Length: %d\r\n\r\n%s" % (len(b), b)
                   for b in (json.dumps(m).encode() for m in msgs))

def labels(cmd):
    data = subprocess.run(cmd, input=payload, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=300).stdout
    i = 0
    while True:
        j = data.find(b"\r\n\r\n", i)
        if j < 0:
            return None
        n = int(data[i:j].decode().split(":", 1)[1])
        f = json.loads(data[j + 4:j + 4 + n].decode())
        i = j + 4 + n
        if f.get("id") == 1 and isinstance(f.get("result"), list):
            return [h.get("label") for h in f["result"] if h.get("kind") == 2]

jvm = labels(["./bin/dawn", "lsp"])
native = labels([dawnc, "lsp"])
bad = 0
if jvm != native:
    print("FAIL: default argument hints: jvm %r, native %r" % (jvm, native))
    bad = 1
want = [', gap: 4, wide: 9, tag: "<4>"', ", hi: 14", ", k: 1400", ", k: down(1600)"]
if jvm != want:
    print("FAIL: default argument hints on jvm: %r, expected %r" % (jvm, want))
    bad = 1
if not bad:
    print("OK   default argument values agree: %s" % "; ".join(jvm))
sys.exit(bad)
PYEOF
then :; else fail=1; fi

[ "$fail" = 0 ] || { echo "FAIL: the native driver and the JVM driver disagree"; exit 1; }
echo "OK: fmt/doc/add/lsp/test/cache/__pkghash agree across both backends, native fmt/lsp match the previous release, raw LSP framing holds on native, both lsp servers answer mid-session, the test reports account for themselves, comptime stops at one depth limit on both, hover folds to the same values on both, and so do left-out default arguments"
