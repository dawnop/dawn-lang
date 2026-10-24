#!/usr/bin/env bash
# The narrow-float contract: std/narrow against an exact rational oracle, on
# both backends, with a live mutant per rounding rule.
#
#   ./scripts/narrow-contract/run.sh
#
# Three kinds of check, answering three questions:
#
#   corpus    -- the corpus is what gen.py generates. The oracle is the
#                generator (fractions.Fraction, from the definition), and the
#                corpus is its output written down as literals; a corpus
#                edited by hand, or a generator changed without rerunning it,
#                would make the two say different things while both looked
#                current. gen.py --check regenerates in memory and compares.
#   contract  -- the corpus program on the JVM and on the native backend, each
#                against narrow_round.expect. The same entry runs in
#                scripts/spike-native (with the sanitizer, in the native-diff
#                job); it runs here too because the mutants below are only
#                evidence next to a clean run that the same script saw pass.
#   mutant    -- one rounding rule removed from a copy of std/narrow.dawn, the
#                corpus run against that copy on both backends, and one named
#                section required to report disagreements on both. A mutant
#                that stays green means the section that should own it is
#                decoration; a mutant red on one backend only means the two
#                do not compile the same rule.
#
# The rules and their owners (the section each must redden; the other
# sections it happens to move are printed, not required):
#
#   ties-away          ties to even -> ties away from zero     bf16 round ties
#   no-subnormal-clamp the quantum is never clamped to emin    bf16 round subnormal
#   emax-off-by-one    bf16's emax is 128 instead of 127       bf16 round overflow
#   away-ties-down     NearestAway breaks a tie toward zero    bf16 mode NearestAway
#   directed-swap      Down and Up trade places (#378)         bf16 mode Down
#   up-extra-ulp       Up steps an exact value up a quantum    f32 mode Up
#   down-ignores-sign  Down steps every inexact magnitude up   f32 mode Down
#
# The last four live in round_binary's `mode` match, which round_bf16 never
# reaches (it takes the default); the `mode` sections are the only ones that
# can see them, and directed-swap stayed green on all 27 sections the corpus
# had before them (#378).
#
# `--std` points a compile at the edited copy, as scripts/atomic-write-contract
# does for std/io. The anchors live in mutate.py, where
# mutation-anchor-preflight.py proves each one matches exactly once before any
# build, so a refactor that moves one fails there instead of silently
# un-mutating here.
#
# `no-subnormal-clamp`'s anchor carries the two comment lines above the
# statement it rewrites, and that is not decoration: knife T4 added a
# DIRECTED rounding function next to `round_binary`, and the two decompose
# the same way, so the statement alone stopped matching once (2 matches) and
# this script said so rather than un-mutating. Knife K1 folded the directed
# modes into `round_binary`'s `mode: Rounding`, so the statement is unique
# again; the comment stays in the anchor so that the next rounder written
# the same way is refused rather than silently mutated in its place.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/narrow-contract"
program="$root/scripts/spike-native/narrow_round.dawn"
expect="$root/scripts/spike-native/narrow_round.expect"
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
# a failure while mutants are still running stops them before their files go
trap 'kill ${pids[*]:-} 2> /dev/null || true; wait 2> /dev/null || true; rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

if command -v md5sum > /dev/null 2>&1; then
  digest() { md5sum "$1" | cut -d' ' -f1; }
else
  digest() { md5 -q "$1"; }
fi

# ---------------------------------------------------------------- corpus

python3 "$here/gen.py" --check || fail "the corpus is not what gen.py generates"

# ---------------------------------------------------------------- toolchain

"$root/bin/dawn" --version > /dev/null

# The runtime is compiled once; every native build below links this object.
rt_obj="$work/dawn_rt.o"
"$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -ffp-contract=off -pthread \
  -I "$root/runtime/c" -c -o "$rt_obj" "$root/runtime/c/dawn_rt.c" ||
  fail "the C runtime does not compile"

# A copy of std the caller may edit.
fork_std() { # dst
  rm -rf "$1"
  cp -r "$root/std" "$1"
}

run_jvm() { # stddir, out
  "$root/bin/dawn" run --std "$1" "$program" > "$2" 2> "$2.err"
}

run_native() { # stddir, out
  local stddir="$1" out="$2"
  "$root/bin/dawn" __emitc --std "$stddir" "$program" -o "$out.c" > "$out.emit" 2>&1 ||
    { cat "$out.emit" >&2; fail "native emit failed"; }
  "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -ffp-contract=off -pthread \
    -I "$root/runtime/c" -o "$out.bin" "$out.c" "$rt_obj" -lm > "$out.cc" 2>&1 ||
    { cat "$out.cc" >&2; fail "native compile failed"; }
  "$out.bin" > "$out" 2> "$out.err"
}

# ---------------------------------------------------------------- contract

fork_std "$work/std-clean"
run_jvm "$work/std-clean" "$work/clean.jvm" || { cat "$work/clean.jvm.err" >&2; fail "the corpus does not run on the JVM"; }
cmp -s "$expect" "$work/clean.jvm" || { diff "$expect" "$work/clean.jvm" >&2 || true; fail "JVM output differs from narrow_round.expect"; }
echo "PASS  contract: jvm matches the oracle ($(grep -c ' cases, ' "$work/clean.jvm") sections)"

run_native "$work/std-clean" "$work/clean.native" || { cat "$work/clean.native.err" >&2; fail "the corpus does not run natively"; }
cmp -s "$expect" "$work/clean.native" || { diff "$expect" "$work/clean.native" >&2 || true; fail "native output differs from narrow_round.expect"; }
echo "PASS  contract: native matches the oracle"

# ---------------------------------------------------------------- mutants

# The owning section's summary line must report a non-zero count on both
# backends. The program must have run to completion on both (the `total:`
# line is the witness): a mutant that crashes proves nothing about the rule.
expect_red() { # name, owner, jvm-out, native-out
  local name="$1" owner="$2"
  local backend out
  for backend in jvm native; do
    if [ "$backend" = jvm ]; then out="$3"; else out="$4"; fi
    grep -q '^total: ' "$out" || { cat "$out" >&2; fail "$name mutant did not run to completion on $backend"; }
    if grep -q "^$owner: [0-9]* cases, 0 bad\$" "$out"; then
      fail "$name mutant stayed green on $backend: '$owner' still reports 0 bad"
    fi
    grep -q "^$owner: [0-9]* cases, [1-9][0-9]* bad\$" "$out" ||
      { cat "$out" >&2; fail "$name mutant: '$owner' summary line missing on $backend"; }
  done
  local moved
  moved=$(grep -c ' cases, [1-9][0-9]* bad$' "$3")
  echo "PASS  mutant: $name ('$owner' turned red on both backends; $moved section(s) moved)"
}

mutant() { # name, owner
  local name="$1" owner="$2"
  local stddir="$work/$name/std"
  mkdir -p "$work/$name"
  fork_std "$stddir"
  local before after
  before=$(digest "$stddir/narrow.dawn")
  # Rewrite the registered anchor in the forked std, or fail.
  python3 "$here/mutate.py" "$name" "$work/$name"
  after=$(digest "$stddir/narrow.dawn")
  echo "      $name: std/narrow.dawn md5 $before -> $after"
  run_jvm "$stddir" "$work/$name.jvm" || { cat "$work/$name.jvm.err" >&2; fail "$name mutant did not compile and run on the JVM"; }
  run_native "$stddir" "$work/$name.native" || { cat "$work/$name.native.err" >&2; fail "$name mutant did not compile and run natively"; }
  expect_red "$name" "$owner" "$work/$name.jvm" "$work/$name.native"
}

# The mutants are independent (each has its own std copy and output files),
# and each costs a JVM run and a native build of the whole corpus, the C
# compile of which is one single-threaded cc over ~100k lines. So they run
# side by side, at most NARROW_JOBS at a time (default 3), each into a log of
# its own; the logs are printed and judged in the order the mutants are
# listed, so the output reads the same as a sequential run.
jobs_max="${NARROW_JOBS:-3}"
queue=()
pids=()

reap_oldest() {
  local name="${queue[0]}" pid="${pids[0]}"
  queue=("${queue[@]:1}")
  pids=("${pids[@]:1}")
  local rc=0
  wait "$pid" || rc=$?
  cat "$work/$name.log"
  [ "$rc" -eq 0 ] || fail "$name mutant: see above"
}

spawn() { # name, owner
  while [ "${#pids[@]}" -ge "$jobs_max" ]; do reap_oldest; done
  ( mutant "$1" "$2" ) > "$work/$1.log" 2>&1 &
  queue+=("$1")
  pids+=("$!")
}

# 1. Ties away from zero instead of to even. A midpoint with an even
#    significand below it now goes up.
spawn ties-away "bf16 round ties"

# 2. No subnormal clamp: below emin the quantum keeps shrinking with the
#    exponent, so a tiny value keeps all p bits instead of landing on the
#    grid.
spawn no-subnormal-clamp "bf16 round subnormal"

# 3. The overflow threshold one binade too high: a value that should round
#    to infinity rounds to 2^128 instead.
spawn emax-off-by-one "bf16 round overflow"

# 4. NearestAway takes the smaller magnitude on a tie: the tie cells of the
#    mode section, and nothing else, disagree.
spawn away-ties-down "bf16 mode NearestAway"

# 5. Down and Up swapped, both the step and the overflow saturation (#378).
#    Every inexact cell of either sign moves, and so do the overflow cells.
spawn directed-swap "bf16 mode Down"

# 6. Up steps a positive value that is already on the grid: the on-grid
#    cells of the mode section, through round_f32's `mode` argument.
spawn up-extra-ulp "f32 mode Up"

# 7. Down ignores the sign and rounds a positive inexact value away from
#    zero, the way it must round a negative one.
spawn down-ignores-sign "f32 mode Down"

while [ "${#pids[@]}" -gt 0 ]; do reap_oldest; done

echo "narrow contract ok"
