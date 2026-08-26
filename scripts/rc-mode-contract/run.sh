#!/usr/bin/env bash
# Mutant harness for the Perceus parameter-mode contract (core.CMode).
#
#   ./scripts/rc-mode-contract/run.sh
#
# The mode contract has two readers that must agree per function: the callee
# reads `CParam.mode`, every call site reads the program-wide table keyed
# `(owner, name)`. The borrowed-inference knife (docs/perceus-design.md 6)
# will one day stamp both from one fixpoint, and the whole risk of that knife
# is a disagreement: a table that says borrowed while the callee still drops
# is a double free, a callee that stops dropping while callers still hand
# over is a leak. Neither is visible in printed output until the allocator
# feels like showing it, so before the inference exists, this harness proves
# the net underneath it catches each half-flip -- "the green of a gate that
# has never seen a red is not evidence".
#
# `DAWN_RC_MODE_FLIPS` (parsed in c/cdriver.dawn) is the injection channel:
# `owner:name:arity:index=callee|callsite|both` turns one parameter of one
# function `CBorrowed` on one or both sides. roster.txt names the sites; for
# each, three flips:
#
#   callsite  the table row alone -- a mutant. Must be caught: today by the
#             rc pass's own balance check (`rc: unbalanced`, at compile
#             time), and once rc_check learns the table, by AddressSanitizer
#             (measured: heap-use-after-free on every table-jurisdiction
#             site). Any machine red counts; a flip that sails through
#             everything is the failure this harness exists to make loud.
#   callee    `CParam.mode` alone -- the mirror mutant. Caught by
#             LeakSanitizer (the callee stops releasing what callers still
#             hand over).
#   both      the coherent flip, knife 2's semantics in miniature. This one
#             must be GREEN all the way -- same bytes, clean sanitizers --
#             and the sites where it is not are the harness's findings,
#             listed in known-red.txt with their reasons. That file is a
#             ratchet, spike-native's rules: an unlisted red is fatal, and a
#             listed entry that starts passing is fatal too (delete it and
#             upgrade the expectation).
#
# Two controls guard the harness itself:
#
#   clean     each corpus program, no flips: output matches .expect, both
#             sanitizers clean.
#   identity  a flip naming a function that does not exist must produce
#             byte-identical C -- the channel engaged (it parsed) and
#             changed nothing, which is also the shape of every real compile
#             (no env var, empty flip list, same bytes; pinned against the
#             pre-channel compiler when the channel landed).
#
# And one parse guard: a malformed spec must fail the compile loudly. The
# only writer of this env var is this harness; a flip that silently did not
# happen would turn a red mutant into a green lie.
#
# A mutant that emits C must also produce *different* C from the clean emit
# (checked with cmp). Without that, a renamed env var or a broken parser
# would leave every mutant testing the unmutated compiler, and the matrix
# would be green forever -- the exact disease this directory treats.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/rc-mode-contract"
cc_bin="${CC:-cc}"
known="$here/known-red.txt"

# an inherited flip spec would poison every baseline below
unset DAWN_RC_MODE_FLIPS

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail=0
known_hit=0

is_known() {
  [ -f "$known" ] || return 1
  # exact-token match; the ids carry `/` and `:` so no regex
  awk -v id="$1" '!/^[[:space:]]*#/ && $1 == id { found = 1 } END { exit !found }' "$known"
}

# verdict <id> <ok|bad> [detail...]
verdict() {
  local id="$1" state="$2"
  shift 2
  if [ "$state" = ok ]; then
    if is_known "$id"; then
      printf '  %-34s FIXED -- delete it from known-red.txt\n' "$id"
      fail=1
    else
      printf '  %-34s ok\n' "$id"
    fi
    return
  fi
  if is_known "$id"; then
    printf '  %-34s known-red\n' "$id"
    known_hit=$((known_hit + 1))
  else
    printf '  %-34s FAIL\n' "$id"
    if [ "$#" -gt 0 ]; then printf '%s\n' "$@" | head -20; fi
    fail=1
  fi
}

# The sanitizer is the oracle here; a machine without it cannot render the
# verdicts this harness is for, and skipping them quietly would be a green
# that means nothing.
probe="$work/asan_probe"
printf 'int main(void){return 0;}\n' > "$probe.c"
if ! "$cc_bin" -fsanitize=address -o "$probe" "$probe.c" 2>/dev/null; then
  echo "error: $cc_bin cannot build with AddressSanitizer; this harness has no oracle without it" >&2
  exit 1
fi

# emit <out.c> [spec] -> 0/rc, stderr in <out.c>.err
emit() {
  local out="$1" spec="${2:-}"
  local rc=0
  if [ -n "$spec" ]; then
    DAWN_RC_MODE_FLIPS="$spec" "$root/bin/dawn" __emitc "$3" -o "$out" \
      >"$out.err" 2>&1 || rc=$?
  else
    "$root/bin/dawn" __emitc "$3" -o "$out" >"$out.err" 2>&1 || rc=$?
  fi
  return "$rc"
}

# build_asan <c-file> <bin> -- flags are spike-native's asan leg: -O0 so a
# report names the Dawn function, the -f flags because they are correctness
# flags for this code generator, not tuning.
build_asan() {
  "$cc_bin" -std=c11 -g -O0 -fno-omit-frame-pointer -fwrapv -fexceptions \
    -fno-strict-aliasing -fsanitize=address -pthread \
    -I "$root/runtime/c" \
    -o "$2" "$1" "$root/runtime/c/dawn_rt.c" -lm >"$2.cc" 2>&1
}

# run_asan <bin> <stdout-file> <err-file>; echoes the exit code
run_asan() {
  local rc=0
  ASAN_OPTIONS=detect_leaks=1 "$1" >"$2" 2>"$3" </dev/null || rc=$?
  echo "$rc"
}

san_red() { grep -Eq 'ERROR: (Address|Leak)Sanitizer' "$1"; }

# ---------------------------------------------------------------- roster
# `<owner:name:arity:index> <program>` per line. Ratcheted both ways: a
# roster program must exist with its .expect, and every corpus .dawn must be
# on the roster -- a corpus that shrank must not look like one that never
# had the case (the effect-evidence lesson).
declare -A prog_of=()
sites=()
while read -r spec prog; do
  case "$spec" in ''|'#'*) continue ;; esac
  sites+=("$spec")
  prog_of["$spec"]="$prog"
  if [ ! -f "$here/$prog.dawn" ] || [ ! -f "$here/$prog.expect" ]; then
    echo "roster names $prog but $prog.dawn/.expect is not here" >&2
    exit 1
  fi
done < "$here/roster.txt"

for f in "$here"/*.dawn; do
  name="$(basename "$f" .dawn)"
  used=0
  for spec in "${sites[@]}"; do
    [ "${prog_of[$spec]}" = "$name" ] && used=1
  done
  if [ "$used" -eq 0 ]; then
    echo "corpus file $name.dawn is on nobody's roster line" >&2
    exit 1
  fi
done

# ---------------------------------------------------------------- clean
# every program once, no flips: the baseline C every mutant is compared
# against, and the positive control that the corpus itself is green
progs=()
for spec in "${sites[@]}"; do
  p="${prog_of[$spec]}"
  seen=0
  for q in "${progs[@]:-}"; do [ "$q" = "$p" ] && seen=1; done
  [ "$seen" -eq 0 ] && progs+=("$p")
done

for p in "${progs[@]}"; do
  if ! emit "$work/$p.c" "" "$here/$p.dawn"; then
    verdict "$p:clean" bad "$(cat "$work/$p.c.err")"
    continue
  fi
  if ! build_asan "$work/$p.c" "$work/$p.clean"; then
    verdict "$p:clean" bad "$(cat "$work/$p.clean.cc")"
    continue
  fi
  rc="$(run_asan "$work/$p.clean" "$work/$p.clean.out" "$work/$p.clean.err2")"
  if [ "$rc" -ne 0 ] || san_red "$work/$p.clean.err2" ||
    ! diff -q "$here/$p.expect" "$work/$p.clean.out" >/dev/null; then
    verdict "$p:clean" bad "exit $rc" "$(head -15 "$work/$p.clean.err2")" \
      "$(diff -u "$here/$p.expect" "$work/$p.clean.out" 2>/dev/null | head -10)"
  else
    verdict "$p:clean" ok
  fi
done

# ---------------------------------------------------------------- identity
# a flip that matches nothing must be invisible in the bytes
idp="${progs[0]}"
if emit "$work/identity.c" "zz/nowhere:absent:1:0=both" "$here/$idp.dawn" &&
  cmp -s "$work/$idp.c" "$work/identity.c"; then
  verdict "identity" ok
else
  verdict "identity" bad "an unmatched flip changed the emitted C (or failed to emit)" \
    "$(head -5 "$work/identity.c.err" 2>/dev/null)"
fi

# ---------------------------------------------------------------- parse guard
if emit "$work/guard.c" "std/str:len:1:0=bogus" "$here/$idp.dawn"; then
  verdict "parse-guard" bad "a malformed spec was accepted"
elif grep -q "DAWN_RC_MODE_FLIPS" "$work/guard.c.err"; then
  verdict "parse-guard" ok
else
  verdict "parse-guard" bad "the compile failed, but not on the spec:" \
    "$(head -5 "$work/guard.c.err")"
fi

# ---------------------------------------------------------------- the matrix
for spec in "${sites[@]}"; do
  p="${prog_of[$spec]}"

  for shape in callsite callee; do
    id="$spec=$shape"
    tag="$(echo "$id" | tr '/:=' '___')"
    if ! emit "$work/$tag.c" "$id" "$here/$p.dawn"; then
      # a compile-time red counts only when it is the balance oracle
      # speaking, not some unrelated crash
      if grep -q "rc: unbalanced" "$work/$tag.c.err"; then
        verdict "$id" ok
      else
        verdict "$id" bad "emit failed, but not on the rc balance check:" \
          "$(head -5 "$work/$tag.c.err")"
      fi
      continue
    fi
    if cmp -s "$work/$p.c" "$work/$tag.c"; then
      verdict "$id" bad "the flip produced byte-identical C: the mutation never engaged"
      continue
    fi
    if ! build_asan "$work/$tag.c" "$work/$tag.bin"; then
      # a mutant that breaks the C build is caught, if noisily
      verdict "$id" ok
      continue
    fi
    rc="$(run_asan "$work/$tag.bin" "$work/$tag.out" "$work/$tag.err2")"
    if san_red "$work/$tag.err2" || [ "$rc" -ne 0 ] ||
      ! diff -q "$here/$p.expect" "$work/$tag.out" >/dev/null; then
      verdict "$id" ok
    else
      verdict "$id" bad "the mutant SURVIVED: no oracle went red"
    fi
  done

  id="$spec=both"
  tag="$(echo "$id" | tr '/:=' '___')"
  if ! emit "$work/$tag.c" "$id" "$here/$p.dawn"; then
    verdict "$id" bad "$(head -3 "$work/$tag.c.err")"
    continue
  fi
  if cmp -s "$work/$p.c" "$work/$tag.c"; then
    verdict "$id" bad "the coherent flip produced byte-identical C: it never engaged"
    continue
  fi
  if ! build_asan "$work/$tag.c" "$work/$tag.bin"; then
    verdict "$id" bad "$(cat "$work/$tag.bin.cc")"
    continue
  fi
  rc="$(run_asan "$work/$tag.bin" "$work/$tag.out" "$work/$tag.err2")"
  if [ "$rc" -eq 0 ] && ! san_red "$work/$tag.err2" &&
    diff -q "$here/$p.expect" "$work/$tag.out" >/dev/null; then
    verdict "$id" ok
  else
    verdict "$id" bad "exit $rc" "$(head -15 "$work/$tag.err2")" \
      "$(diff -u "$here/$p.expect" "$work/$tag.out" 2>/dev/null | head -10)"
  fi
done

# a known-red entry that matched nothing this run names a check that no
# longer exists; that is the other jaw of the ratchet
if [ -f "$known" ]; then
  while read -r id _; do
    case "$id" in ''|'#'*) continue ;; esac
    found=0
    for spec in "${sites[@]}"; do
      [ "$id" = "$spec=both" ] && found=1
    done
    if [ "$found" -eq 0 ]; then
      echo "known-red.txt names $id, which is not a check this harness runs" >&2
      fail=1
    fi
  done < "$known"
fi

echo
if [ "$fail" -ne 0 ]; then
  echo "rc-mode-contract: FAIL"
  exit 1
fi
echo "rc-mode-contract: ok ($known_hit known-red)"
