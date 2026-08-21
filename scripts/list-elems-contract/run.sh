#!/usr/bin/env bash
# The list-literal element forms' negative control (spec §4.11).
#
#   ./scripts/list-elems-contract/run.sh                  # everything
#   ./scripts/list-elems-contract/run.sh --only cond-body-loses-expectation
#   ./scripts/list-elems-contract/run.sh --record         # re-record matrix.txt
#
# `..xs` and an else-less `if` are pinned as *behaviour* by three corpora
# already: grammar-corpus/accept/list_elems.dawn parses them,
# checker-corpus/cases/list_elems{,_bad}.dawn types them and records every
# diagnostic, and spike-native/list_elems.dawn runs them through both backends
# under AddressSanitizer. What none of those pins is that each rule is held by
# exactly one sentence of the implementation, and that property rots silently:
# a corpus of accepted programs stays green when a rule is deleted, as long as
# the programs still compile.
#
# The load-bearing one is the expectation push-down. `[text(s)]` cannot be
# typed when `text`'s type parameter appears only in its return type;
# `[header, if c { text(s) }]` can, because a sibling settled the element type
# and it reached into the body. Every accepted program in the corpora would go
# on compiling if that push-down were deleted -- they would simply be the
# programs that never needed it. `cond-body-loses-expectation` is the mutant
# that makes the difference observable, and it is the reason this directory
# exists.
#
# Structure copied from scripts/pipe-contract (the precedent gate-map's own
# mutant matrix cites), reduced to what one compiler build per sentence needs.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/list-elems-contract"
cases="$here/cases"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
work=$(mktemp -d "${TMPDIR:-/tmp}/list-elems-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

# The one assertion no mutant in this contract may redden: a list literal with
# neither element form. Held by hand rather than by the matrix, because "the
# feature did not touch the thing it is not about" is the claim a red set
# diffed against a record cannot make on its own -- a record that grew the line
# would still match itself.
CONTROL=plain_literal_unmoved

# Programs that must be refused, and programs that must be accepted. One shape
# per file: a diagnostic takes its whole file down, so two shapes sharing one
# could not own separate assertions (pipe-contract measured that).
REFUSE=(
  spread_item_type_joins
  spread_operand_must_be_list
  cond_condition_is_bool
)
ACCEPT=(
  spread_operand_gets_expectation
  spread_defers_to_second_round
  cond_body_gets_expectation
  cond_arm_settles_later_arms
  cond_defers_to_second_round
  else_if_chain_compiles
)
# Programs that must run and print what `<name>.expect` records. These are the
# assertions a type checker cannot make: a wrong *length* compiles.
RUN=(
  cond_false_contributes_nothing
  else_if_chain_picks_first_true
  "$CONTROL"
)

MUTANTS=(
  spread-item-type-not-joined
  spread-operand-list-check-dropped
  spread-operand-loses-expectation
  cond-body-loses-expectation
  cond-arm-does-not-settle-later-arms
  cond-condition-unchecked
  needs-expected-blind-to-spread
  needs-expected-blind-to-cond
  else-if-chain-truncated
  cond-always-contributes
)

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

mode=check
only=""
while [ $# -gt 0 ]; do
  case "$1" in
    --record) mode=record ;;
    --only) shift; only="${1:-}" ;;
    *) fail "unknown argument: $1" ;;
  esac
  shift
done

if [ -n "$only" ]; then
  found=0
  for m in "${MUTANTS[@]}"; do [ "$m" = "$only" ] && found=1; done
  [ "$found" -eq 1 ] || fail "--only names no mutant: $only"
  MUTANTS=("$only")
fi

# Every assertion prints `<name> PASS` or `<name> FAIL`, and every compiler
# runs the whole set. Asserting only that mutant X reddens assertion A would
# record ownership in prose and enforce nothing.
assess() { # compiler tag
  local compiler=$1 tag=$2 dir name
  dir="$work/assess-$tag"
  mkdir -p "$dir"

  for name in "${REFUSE[@]}"; do
    if "$compiler" check --std "$root/std" "$cases/$name.dawn" \
      > "$dir/$name.out" 2>&1; then
      echo "$name FAIL"
    else
      echo "$name PASS"
    fi
  done

  for name in "${ACCEPT[@]}"; do
    if "$compiler" check --std "$root/std" "$cases/$name.dawn" \
      > "$dir/$name.out" 2>&1; then
      echo "$name PASS"
    else
      echo "$name FAIL"
    fi
  done

  for name in "${RUN[@]}"; do
    if "$compiler" run --std "$root/std" "$cases/$name.dawn" \
      > "$dir/$name.out" 2> "$dir/$name.err" &&
      cmp -s "$cases/$name.expect" "$dir/$name.out"; then
      echo "$name PASS"
    else
      echo "$name FAIL"
    fi
  done
}

reds_of() { # compiler mutation
  local name state
  assess "$1" "$2" | while read -r name state; do
    if [ "$state" = FAIL ]; then printf 'red\t%s\t%s\n' "$2" "$name"; fi
  done
}

python3 "$here/matrix.py" --selftest
python3 "$here/matrix.py" --validate "$here/matrix.txt"

"$dawn" --version > /dev/null
baseline=$(assess "$dawn" baseline)
printf '%s\n' "$baseline" | while read -r name state; do
  [ "$state" = PASS ] || fail "$name: the real compiler does not satisfy the contract"
done
printf '%s\n' "$baseline" | sed 's/ PASS$//;s/^/OK   /'

observed="$work/observed.txt"
: > "$observed"

for mutation in "${MUTANTS[@]}"; do
  mutant="$work/$mutation"
  mkdir -p "$mutant"
  cp -R "$root/selfhost" "$mutant/selfhost"
  ln -s "$root/packages" "$mutant/packages"
  ln -s "$root/compiler-plan" "$mutant/compiler-plan"
  python3 "$here/mutate.py" "$mutation" "$mutant" > /dev/null

  if ! "$dawn" build "$mutant/selfhost" -o "$mutant/compiler.jar" \
      > "$mutant/build.out" 2>&1; then
    tail -30 "$mutant/build.out" >&2
    fail "$mutation mutant did not compile"
  fi
  cat > "$mutant/dawn" <<EOF
#!/bin/sh
exec java -Xss512m -Xmx2g -jar "$mutant/compiler.jar" "\$@"
EOF
  chmod +x "$mutant/dawn"
  if ! "$mutant/dawn" --version > "$mutant/version.out" 2>&1; then
    cat "$mutant/version.out" >&2
    fail "$mutation mutant compiled but --version exited nonzero"
  fi
  grep -Eq '^dawn [^[:space:]]' "$mutant/version.out" ||
    fail "$mutation mutant --version did not print a dawn version line"

  reds_of "$mutant/dawn" "$mutation" >> "$observed"
  n=$(grep -c $'\t'"$mutation"$'\t' "$observed" || true)
  echo "MUT  $mutation reddens $n assertion(s)"
done

if grep -q $'\t'"$CONTROL"'$' "$observed"; then
  grep $'\t'"$CONTROL"'$' "$observed" >&2
  fail "a mutant reddened the control assertion $CONTROL"
fi

if [ "$mode" = record ]; then
  [ -z "$only" ] || fail "--record needs every mutant in one run; drop --only"
  python3 "$here/matrix.py" --record "$observed" "$here/matrix.txt"
  exit 0
fi

python3 "$here/matrix.py" --check "$observed" "$here/matrix.txt"
echo "list element contract ok (${#MUTANTS[@]} mutant(s))"
