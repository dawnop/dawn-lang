#!/usr/bin/env bash
# Guest-retained init state, at both execution boundaries.
#
# One JVM process consumes all nine lines. One wasm module instance consumes
# them through nine independent `dawn_turn` calls. The transcript covers an
# event before init, a successful install, an event reading it, a panicking
# init attempt followed by an event that still reads the old state, a new init
# replacing it, and a decoder refusal that likewise leaves it untouched.
#
# A source-seam gate holds the retained-root intrinsics to std/reactor, the
# compiler/runtime implementations and this contract's direct C ownership
# probe. Its source mutant adds a call to an unrelated std module and must make
# that gate fail. Two production mutants then independently drop the installed
# root and commit a provisional root before a turn succeeds. They must compile,
# run and go red on both backends; a compile failure is not credited.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/wasm-dom-contract"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

record=0
case "${1:-}" in
  "") ;;
  --record) record=1 ;;
  *) echo "usage: $0 [--record]" >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
  echo "usage: $0 [--record]" >&2
  exit 2
fi

dawn="${DAWN_BIN:-$root/bin/dawn}"
dawnc="${DAWNC_BIN:-}"
if [ ! -x "$dawn" ]; then
  echo "MISSING: $dawn is not executable (the JVM leg needs bin/dawn)." >&2
  exit 1
fi
if [ -z "$dawnc" ] || [ ! -x "$dawnc" ]; then
  echo "MISSING: DAWNC_BIN must name the executable native driver." >&2
  exit 1
fi
if ! command -v node >/dev/null; then
  echo "MISSING: node is not on PATH (it hosts the wasm reactor)." >&2
  exit 1
fi
if ! command -v python3 >/dev/null; then
  echo "MISSING: python3 is not on PATH (it applies exact production mutants)." >&2
  exit 1
fi

cc_bin="${CC:-cc}"
if ! command -v "$cc_bin" >/dev/null; then
  echo "MISSING: $cc_bin is not on PATH (the retained-root RC probe is C)." >&2
  exit 1
fi

input="$here/retained-input.txt"
expected="$here/retained-expected.txt"
project="$here/retained"

# Keep this list literal: adding a new call site is a review event, not an
# automatically accepted consequence of adding a file. Embedded std/runtime
# sources and backend tables are compiler implementations of the same seam.
seam_expected() {
  cat <<'EOF'
./runtime/c/dawn_rt.c
./runtime/c/dawn_rt.h
./scripts/wasm-dom-contract/retained-rc.c
./selfhost/builtins.dawn
./selfhost/src/check/checker.dawn
./selfhost/src/check/types.dawn
./selfhost/src/embed/rtsrc.dawn
./selfhost/src/embed/stdsrc.dawn
./selfhost/src/ir/interp.dawn
./selfhost/src/jvm/rtclasses.dawn
./std/reactor.dawn
EOF
}

seam_files() { # <tree-root>
  (
    cd "$1"
    grep -RIl --fixed-strings 'reactor_state_' . \
      --exclude=retained.sh \
      --exclude-dir=.dawn --exclude-dir=.git --exclude-dir=build \
      --exclude-dir=core-golden --exclude-dir=target 2>/dev/null | LC_ALL=C sort || true
  )
}

check_seam() { # <tree-root>
  local tree="$1"
  local wanted="$work/seam-wanted.txt"
  local actual="$work/seam-actual.txt"
  seam_expected >"$wanted"
  seam_files "$tree" >"$actual"
  if ! diff -u "$wanted" "$actual"; then
    echo "retained-root seam changed: only the pinned production implementations and probe may name it" >&2
    return 1
  fi

  local reactor="$tree/std/reactor.dawn"
  local has_count get_count set_count guard_count
  has_count="$(grep -Foc 'reactor_state_has()' "$reactor" || true)"
  get_count="$(grep -Foc 'reactor_state_get()' "$reactor" || true)"
  set_count="$(grep -Foc 'reactor_state_set(' "$reactor" || true)"
  guard_count="$(grep -Fxc '        if reactor_state_has() { Some(reactor_state_get()) } else { None }' "$reactor" || true)"
  if [ "$has_count" -ne 1 ] || [ "$get_count" -ne 1 ] || \
     [ "$set_count" -ne 1 ] || [ "$guard_count" -ne 1 ]; then
    echo "retained-root seam changed: std/reactor must have one guarded get and one set" >&2
    return 1
  fi
}

if ! check_seam "$root" >"$work/seam-base.log" 2>&1; then
  echo "FAIL: retained-root source seam moved:" >&2
  cat "$work/seam-base.log" >&2
  exit 1
fi
echo "OK   retained source seam: one guarded std/reactor read, one write"

# This is a real source mutation, not a synthetic grep fixture: begin with the
# exact allowed files, then add an intrinsic call to an unrelated std module.
seam_mutant="$work/seam-mutant"
while IFS= read -r rel; do
  file="${rel#./}"
  mkdir -p "$seam_mutant/$(dirname "$file")"
  cp "$root/$file" "$seam_mutant/$file"
done < <(seam_expected)
cp "$root/std/str.dawn" "$seam_mutant/std/str.dawn"
cat >>"$seam_mutant/std/str.dawn" <<'EOF'

fn retained_seam_mutant[T]() -> T !io = reactor_state_get()
EOF
if check_seam "$seam_mutant" >"$work/seam-mutant.log" 2>&1; then
  echo "FAIL: retained-root source-seam mutant survived" >&2
  exit 1
fi
if ! grep -Fq './std/str.dawn' "$work/seam-mutant.log"; then
  echo "FAIL: source-seam mutant failed for an unrelated reason:" >&2
  cat "$work/seam-mutant.log" >&2
  exit 1
fi
echo "OK   mutant source-seam-call goes red"

# The root's native ownership is tested at the ABI itself: set takes its own
# reference, get answers an owned reference, replace drops the old root once,
# alias replacement is safe, and atexit clears the last root before observers.
"$cc_bin" -std=c11 -O1 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -Wall -Wextra -Werror -I "$root/runtime/c" \
  -o "$work/retained-rc" "$here/retained-rc.c" "$root/runtime/c/dawn_rt.c" -lm
if ! "$work/retained-rc" >"$work/retained-rc.txt"; then
  echo "FAIL: retained-root C ownership probe failed" >&2
  exit 1
fi
if [ "$(cat "$work/retained-rc.txt")" != $'retained_rc_replace PASS\nretained_rc_exit PASS' ]; then
  echo "FAIL: retained-root C ownership probe changed:" >&2
  cat "$work/retained-rc.txt" >&2
  exit 1
fi
echo "OK   retained C root: get/set/replace/exit ownership"

run_jvm() { # <tree-root> <output>
  "$dawn" run --std "$1/std" "$1/scripts/wasm-dom-contract/retained" \
    <"$input" >"$2" 2>"$work/jvm.err"
}

build_wasm() { # <tree-root> <output>
  "$dawnc" build --std "$1/std" --target wasm --reactor \
    "$1/scripts/wasm-dom-contract/retained" -o "$2" 2>"$work/wasm-build.err"
}

run_wasm() { # <tree-root> <wasm> <output>
  node --no-warnings "$1/scripts/wasm-dom-contract/retained.mjs" \
    "$2" "$input" >"$3" 2>"$work/wasm.err"
}

if ! run_jvm "$root" "$work/jvm.txt"; then
  echo "FAIL: retained JVM session did not run:" >&2
  cat "$work/jvm.err" >&2
  exit 1
fi
if [ "$record" -eq 0 ]; then
  if ! cmp -s "$expected" "$work/jvm.txt"; then
    echo "FAIL: retained JVM session changed:" >&2
    diff -u "$expected" "$work/jvm.txt" | head -40 >&2
    exit 1
  fi
  echo "OK   retained JVM: 9 lines in one process, byte for byte"
fi

if ! build_wasm "$root" "$work/base.wasm"; then
  echo "FAIL: retained wasm fixture did not build:" >&2
  cat "$work/wasm-build.err" >&2
  exit 1
fi
if ! run_wasm "$root" "$work/base.wasm" "$work/wasm.txt"; then
  echo "FAIL: retained wasm session did not run:" >&2
  cat "$work/wasm.err" >&2
  exit 1
fi
if ! cmp -s "$work/jvm.txt" "$work/wasm.txt"; then
  echo "FAIL: retained JVM and wasm sessions disagree:" >&2
  diff -u "$work/jvm.txt" "$work/wasm.txt" | head -40 >&2
  exit 1
fi

if [ "$record" -eq 1 ]; then
  cp "$work/jvm.txt" "$expected"
  echo "recorded $(wc -l <"$expected" | tr -d ' ') retained lines in $expected"
  exit 0
fi

if ! cmp -s "$expected" "$work/wasm.txt"; then
  echo "FAIL: retained wasm session changed:" >&2
  diff -u "$expected" "$work/wasm.txt" | head -40 >&2
  exit 1
fi
echo "OK   retained wasm: 9 separate dawn_turn calls, byte for byte"

# Copy only what this project and its compiler-visible std read. The driver is
# outside the tree on purpose: every mutation is in production std source, not
# in a rebuilt harness or a second implementation of the slot.
mutant_tree=""
prepare_mutant() { # <name>
  mutant_tree="$work/mutant-$1"
  mkdir -p "$mutant_tree/scripts/wasm-dom-contract"
  cp -r "$root/std" "$root/packages" "$mutant_tree/"
  cp -r "$project" "$mutant_tree/scripts/wasm-dom-contract/retained"
  cp "$here/retained.mjs" "$mutant_tree/scripts/wasm-dom-contract/retained.mjs"
}

apply_exact_mutant() { # <file> <old> <new>
  python3 - "$1" "$2" "$3" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
old = sys.argv[2]
new = sys.argv[3]
source = path.read_text()
if source.count(old) != 1:
    raise SystemExit(f"expected exactly one mutant target in {path}, found {source.count(old)}")
path.write_text(source.replace(old, new))
PY
}

run_mutant() { # <name> <tree-root> <oracle: any|line-five>
  local name="$1"
  local tree="$2"
  local oracle="$3"
  local jvm_out="$work/$name-jvm.txt"
  local wasm_out="$work/$name-wasm.txt"
  local wasm_bin="$work/$name.wasm"

  if ! run_jvm "$tree" "$jvm_out"; then
    echo "FAIL: $name mutant did not run on the JVM:" >&2
    cat "$work/jvm.err" >&2
    exit 1
  fi
  if ! build_wasm "$tree" "$wasm_bin"; then
    echo "FAIL: $name mutant did not build for wasm:" >&2
    cat "$work/wasm-build.err" >&2
    exit 1
  fi
  if ! run_wasm "$tree" "$wasm_bin" "$wasm_out"; then
    echo "FAIL: $name mutant did not run on wasm:" >&2
    cat "$work/wasm.err" >&2
    exit 1
  fi
  if ! cmp -s "$jvm_out" "$wasm_out"; then
    echo "FAIL: $name mutant disagrees between JVM and wasm:" >&2
    diff -u "$jvm_out" "$wasm_out" | head -40 >&2
    exit 1
  fi

  case "$oracle" in
    any)
      if cmp -s "$expected" "$jvm_out"; then
        echo "FAIL: $name mutant survived both retained sessions" >&2
        exit 1
      fi
      ;;
    line-five)
      awk 'NR != 5' "$expected" >"$work/$name-expected-rest.txt"
      awk 'NR != 5' "$jvm_out" >"$work/$name-actual-rest.txt"
      if ! cmp -s "$work/$name-expected-rest.txt" "$work/$name-actual-rest.txt"; then
        echo "FAIL: $name mutant changed lines other than the post-panic event:" >&2
        diff -u "$expected" "$jvm_out" | head -40 >&2
        exit 1
      fi
      if [ "$(sed -n '5p' "$expected")" = "$(sed -n '5p' "$jvm_out")" ]; then
        echo "FAIL: $name mutant preserved the old root after a panicking init" >&2
        exit 1
      fi
      ;;
    *) echo "FAIL: unknown mutant oracle: $oracle" >&2; exit 1 ;;
  esac
  echo "OK   mutant $name goes red on JVM and wasm"
}

prepare_mutant drop-retained-state
apply_exact_mutant "$mutant_tree/std/reactor.dawn" \
  '        if reactor_state_has() { Some(reactor_state_get()) } else { None }' \
  '        None'
run_mutant drop-retained-state "$mutant_tree" any

# Wrong on purpose: publish an uninitialised Root before calling `step`, then
# roll it back only after `step` returns. Successful turns are unchanged, but a
# panic skips the rollback and line 5 observes that the old state was lost.
prepare_mutant commit-before-success
apply_exact_mutant "$mutant_tree/std/reactor.dawn" \
  $'  Root(advance: line => {\n    let (replacement, reply) = step(Some(state), line)' \
  $'  Root(advance: line => {\n    let installed = rooted(state, step)\n    let pending = Root(advance: next_line => first(step, next_line))\n    unsafe_pure { reactor_state_set(pending) }\n    let (replacement, reply) = step(Some(state), line)\n    unsafe_pure { reactor_state_set(installed) }'
run_mutant commit-before-success "$mutant_tree" line-five

echo "retained state ok (JVM process + wasm instance, seam mutant + 2/2 production mutants killed)"
