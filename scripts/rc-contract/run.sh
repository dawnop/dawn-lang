#!/usr/bin/env bash
# Contract test for the C runtime's reference counting (perceus-design.md).
#
#   ./scripts/rc-contract/run.sh
#
# Two runs, because the two things worth checking need different settings:
#
#   * under AddressSanitizer, where a drop that does not recurse is a reported
#     leak and a drop that recurses twice is a double free. Neither is visible
#     from inside the program, which is why the oracle is the sanitizer rather
#     than printed output.
#   * under a small stack, where a drop that went back to C recursion crashes
#     on the 200k-node chain instead of quietly working until some larger
#     input. `ulimit -s` is the whole point of this second run.
#   * under AddressSanitizer *with* the slab allocator (-DDAWN_SLAB_FORCE),
#     which the sanitized run above deliberately does not have. Blocks that
#     are not malloc's are blocks the sanitizer knows nothing about, so
#     dawn_rt.c poisons the free ones by hand and poison_probe.c asks whether
#     that works. This leg cannot carry leak assertions -- LSan has no way to
#     be told about an object it did not allocate -- so it runs with
#     detect_leaks=0 and the legs above keep that half untouched.
#
# Strings and Bytes are counted like everything else (they joined the ledger
# 2026-07-29), so the sanitized run keeps leak detection on and a reported
# leak here is always a real one. Only the --rc=leak run turns it off: that
# mode leaks everything on purpose.
#
# A last run mutates the runtime instead of the test. The green of a gate
# that has never seen a red is not evidence, and the properties the singleton
# knife added -- two constructions of one field-less tag are one object, and
# that object is out of the ledger -- are invisible from Dawn, so nothing else
# in the tree can go red when they stop holding. matrix.txt records which
# assertions each mutant reddens; this compares that record with what the
# mutated runtime actually does. A mutant of the allocator's *behaviour* is
# compiled without the sanitizers: it leaks the objects it no longer shares,
# on purpose, and a leak report would drown the per-assertion answer this run
# exists to read. A mutant of the *poisoning* is the other way round, because
# without the sanitizer there is nothing there to break; those are the
# `poisoned` role in matrix.txt and they are read off the probes.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/rc-contract"
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

warn=(-Wall -Wextra -Werror -Wno-unused-parameter)

# Pinned rather than inherited, because both halves of it decide whether the
# poisoning leg means anything. allow_user_poisoning defaults on, and a
# caller who had turned it off would turn every poison call in dawn_rt.c into
# a no-op: the probes would go quiet and the leg would pass while measuring
# nothing. detect_leaks is off because leak detection cannot work on slab
# blocks at all (dawn_rt.h beside DAWN_SLAB_ACTIVE), and a leg that cannot
# fail a leak assertion should not be seen to make one.
asan_opts=detect_leaks=0,allow_user_poisoning=1

# The probe roster, as name, argv mode, and the verdict the sanitizer is
# expected to reach: `poisoned` for a use-after-poison report, `clean` for
# no report at all. Compared against matrix.txt's `probe` records the same
# way the assertion roster is compared against rc_test.c's output.
#
# The last line is a record of what this leg does not catch, kept as a probe
# rather than as a comment. Two live neighbours are both unpoisoned, so an
# overflow from one into the other has nothing in the shadow to trip over;
# catching it needs red zones between blocks, and dawn_rt.c ("manual
# poisoning") says why there are none. Written down as an expectation so
# that the day it changes, this reddens and the record has to be rewritten
# deliberately instead of a gap quietly closing unnoticed.
probes=$(
  cat <<'EOF'
slab_block_stays_clean_while_live	live	clean
slab_poisons_a_freed_block	uaf	poisoned
slab_poisons_the_whole_block	uaf-write	poisoned
slab_catches_a_double_free	double-free	poisoned
slab_poisons_an_unissued_neighbour	overflow	poisoned
slab_misses_an_overflow_into_a_live_neighbour	overflow-live	clean
EOF
)

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

python3 "$here/matrix_check.py" --self-test
python3 "$here/matrix_check.py" "$here/matrix.txt"

# The runtime does not get its blocks from malloc, and the redirection that
# says so is a macro inside dawn_rt.c: it reaches that translation unit and
# nothing else. So a `free()` written anywhere else in the tree is handed an
# address libc never issued, which under AddressSanitizer is a reported
# bad-free and without it is undefined. `dawn_free` is exported for exactly
# this, and this is what keeps the count of bare calls at zero.
echo "== no bare free outside the runtime =="
stray="$(grep -rn --include='*.c' --include='*.cc' --include='*.h' \
  -E '(^|[^_[:alnum:]])free[[:space:]]*\(' "$root/runtime" "$root/scripts" |
  grep -v "^$root/runtime/c/dawn_rt.c:" || true)"
if [ -n "$stray" ]; then
  echo "$stray" >&2
  fail "a bare free() outside runtime/c/dawn_rt.c; call dawn_free instead"
fi

echo "== sanitized =="
"$cc_bin" -std=c11 -O1 -g -fsanitize=address -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  "${warn[@]}" -I "$root/runtime/c" \
  -o "$work/rc_asan" "$here/rc_test.c" "$root/runtime/c/dawn_rt.c"
"$work/rc_asan"
ASAN_OPTIONS=detect_leaks=0 "$work/rc_asan" leak

# ASan replaces the allocator and grows stack frames, so the stack-depth check
# has to be a plain build.
echo "== small stack =="
"$cc_bin" -std=c11 -O1 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  "${warn[@]}" -I "$root/runtime/c" \
  -o "$work/rc_plain" "$here/rc_test.c" "$root/runtime/c/dawn_rt.c"
( ulimit -s 512 && "$work/rc_plain" )

# The roster the matrix names has to be the roster the binary runs, or the
# comparison below is between two different questions.
"$work/rc_plain" > "$work/baseline.out"
awk -F '\t' '$1 == "assert" { print $2 }' "$here/matrix.txt" > "$work/roster.txt"
sed '/^ok$/d' "$work/baseline.out" | awk '{ print $1 }' > "$work/ran.txt"
diff -u "$work/roster.txt" "$work/ran.txt" ||
  fail "matrix.txt names a different assertion roster than rc_test.c runs"
if grep -q ' FAIL$' "$work/baseline.out"; then
  fail "the unmutated runtime does not satisfy the contract"
fi

build_plain() { # runtime-dir output
  "$cc_bin" -std=c11 -O1 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    "${warn[@]}" -I "$1" -o "$2" "$here/rc_test.c" "$1/dawn_rt.c"
}

build_poisoned() { # runtime-dir source output
  "$cc_bin" -std=c11 -O1 -g -fsanitize=address -DDAWN_SLAB_FORCE \
    -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    "${warn[@]}" -I "$1" -o "$3" "$2" "$1/dawn_rt.c"
}

# One process per probe, because the sanitizer's verdict is an abort and not
# a line of output. The verdict becomes the same `<name> PASS|FAIL` stream
# rc_test.c prints, so the red sets below are read the one way whichever leg
# produced them.
#
# The report, not the exit status, is what is read: without the poisoning
# these probes leave the free list holding a block twice and the object
# header holding a link, so whether the runtime then trips its own "drop of a
# value with rc=..." check depends on whether the low half of a slab address
# happens to look like a count. That is a coin flip on the address layout,
# and a harness whose answer turns on it would be flaky. A run that did not
# report a use-after-poison did not detect anything, however it ended, so
# that is `clean`. A death by signal is still refused: it means the verdict
# was never observed.
run_probes() { # binary output
  local bin="$1" out="$2" name mode want status got
  : > "$out"
  while IFS=$'\t' read -r name mode want; do
    set +e
    ASAN_OPTIONS="$asan_opts" "$bin" "$mode" > "$work/probe.out" 2> "$work/probe.err"
    status=$?
    set -e
    [ "$status" -lt 128 ] ||
      fail "probe $name died on signal $((status - 128))"
    got=clean
    if grep -q 'ERROR: AddressSanitizer: use-after-poison' "$work/probe.err"; then
      got=poisoned
    fi
    if [ "$got" = "$want" ]; then
      printf '%s PASS\n' "$name" >> "$out"
    else
      printf '%s FAIL\n' "$name" >> "$out"
    fi
  done <<< "$probes"
}

# The allocator under the sanitizer, which is the one build where both are
# present. Every assertion has to run here -- a SKIP would mean the force
# switch stopped working and the leg went vacuous -- and then the probes ask
# the questions that need the sanitizer to answer.
echo "== sanitized, with the allocator =="
build_poisoned "$root/runtime/c" "$here/rc_test.c" "$work/rc_asan_slab"
ASAN_OPTIONS="$asan_opts" "$work/rc_asan_slab" > "$work/forced.out"
sed '/^ok$/d' "$work/forced.out" | awk '{ print $1 }' > "$work/forced_ran.txt"
diff -u "$work/roster.txt" "$work/forced_ran.txt" ||
  fail "the forced build ran a different assertion roster"
if grep -q ' SKIP$' "$work/forced.out"; then
  fail "-DDAWN_SLAB_FORCE did not bring the allocator into the sanitized build"
fi
if grep -q ' FAIL$' "$work/forced.out"; then
  fail "the allocator does not satisfy the contract under the sanitizer"
fi

awk -F '\t' '$1 == "probe" { print $2 }' "$here/matrix.txt" > "$work/probe_roster.txt"
cut -f1 <<< "$probes" > "$work/probe_ran.txt"
diff -u "$work/probe_roster.txt" "$work/probe_ran.txt" ||
  fail "matrix.txt names a different probe roster than run.sh runs"

build_poisoned "$root/runtime/c" "$here/poison_probe.c" "$work/probe"
run_probes "$work/probe" "$work/probe_baseline.txt"
if grep -q ' FAIL$' "$work/probe_baseline.txt"; then
  cat "$work/probe_baseline.txt" >&2
  fail "the unmutated runtime does not poison its free blocks"
fi

echo "== mutants =="

observed="$work/observed.txt"
: > "$observed"
while IFS=$'\t' read -r mutation role; do
  dir="$work/$mutation"
  mkdir -p "$dir"
  cp "$root/runtime/c/dawn_rt.c" "$root/runtime/c/dawn_rt.h" "$dir/"
  python3 "$here/mutate.py" "$mutation" "$dir"
  cmp -s "$root/runtime/c/dawn_rt.h" "$dir/dawn_rt.h" &&
    cmp -s "$root/runtime/c/dawn_rt.c" "$dir/dawn_rt.c" &&
    fail "$mutation changed nothing"
  if [ "$role" = poisoned ]; then
    # The poisoning is not behaviour, so a mutant of it must leave every
    # answer the program prints alone: the roster is the control here, and
    # the red set comes from the probes.
    build_poisoned "$dir" "$here/rc_test.c" "$dir/rc_test" > "$dir/cc.out" 2>&1 ||
      { cat "$dir/cc.out" >&2; fail "$mutation did not compile"; }
    build_poisoned "$dir" "$here/poison_probe.c" "$dir/probe" >> "$dir/cc.out" 2>&1 ||
      { cat "$dir/cc.out" >&2; fail "$mutation did not compile"; }
    ASAN_OPTIONS="$asan_opts" "$dir/rc_test" > "$dir/out.txt" 2> "$dir/err.txt" ||
      { cat "$dir/out.txt" "$dir/err.txt" >&2; fail "$mutation broke the allocator"; }
    if grep -qE ' (FAIL|SKIP)$' "$dir/out.txt"; then
      cat "$dir/out.txt" >&2
      fail "$mutation is more than a change of poisoning"
    fi
    run_probes "$dir/probe" "$dir/probes.txt"
    grep -q ' FAIL$' "$dir/probes.txt" || fail "$mutation reddened no probe"
    awk -v m="$mutation" '$2 == "FAIL" { printf "red\t%s\t%s\n", m, $1 }' \
      "$dir/probes.txt" >> "$observed"
    echo "OK   $mutation"
    continue
  fi
  build_plain "$dir" "$dir/rc_test" > "$dir/cc.out" 2>&1 ||
    { cat "$dir/cc.out" >&2; fail "$mutation did not compile"; }
  # A mutant is expected to exit nonzero; what must not happen is a crash or a
  # signal, which would mean the red set was never fully observed.
  set +e
  "$dir/rc_test" > "$dir/out.txt" 2> "$dir/err.txt"
  status=$?
  set -e
  [ "$status" -lt 128 ] || fail "$mutation died on signal $((status - 128))"
  [ "$status" -ne 0 ] || fail "$mutation passed every assertion"
  awk -v m="$mutation" '$2 == "FAIL" { printf "red\t%s\t%s\n", m, $1 }' \
    "$dir/out.txt" >> "$observed"
  echo "OK   $mutation"
done < <(awk -F '\t' '$1 == "role" { printf "%s\t%s\n", $2, $3 }' "$here/matrix.txt")

expected="$work/expected.txt"
awk -F '\t' '$1 == "red" { print }' "$here/matrix.txt" | LC_ALL=C sort > "$expected"
LC_ALL=C sort -o "$observed" "$observed"
diff -u "$expected" "$observed" || fail "the observed red set differs from matrix.txt"

# The owner has to be red under the mutant that claims it, which is the half
# of "owns" that can be checked here; matrix_check.py has already refused a
# file where two mutants claim one assertion.
while IFS=$'\t' read -r _ mutation owner; do
  [ "$(grep -Fxc "$(printf 'red\t%s\t%s' "$mutation" "$owner")" "$observed")" -eq 1 ] ||
    fail "$mutation does not redden the assertion it owns"
done < <(awk -F '\t' '$1 == "owner" { print }' "$here/matrix.txt")

echo "rc contract ok"
