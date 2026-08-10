#!/usr/bin/env bash
# SEM-07 public API surface contract (docs/public-surface-design.md).
#
# Two halves. The first checks what the validator accepts and rejects, message
# by message. The second builds one mutant compiler per rule, each of which
# must *compile and run* before its assertion counts -- "the mutant did not
# build" proves nothing about the rule (design §十二).
#
#   ./scripts/export-surface-contract/run.sh              # everything
#   ./scripts/export-surface-contract/run.sh --shard 1/2  # fixtures + half
#
# Sharding exists because a mutant costs one whole compiler build. The shard
# split is a CI wall-clock decision and nothing else: every shard runs the
# fixture contract, and the mutants are divided round-robin.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
here="$root/scripts/export-surface-contract"
cases="$here/cases"
work=$(mktemp -d "${TMPDIR:-/tmp}/export-surface-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

shard_i=1
shard_n=1
only=
case "${1:-}" in
  --shard) shard_i=${2%%/*}; shard_n=${2##*/} ;;
  --only) only=$2 ;;
esac

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

run_dawn() {
  local compiler=$1
  shift
  case "$compiler" in
    *.jar) java -jar "$compiler" "$@" ;;
    *) "$compiler" "$@" ;;
  esac
}

# every `D` line of a single-file check, tab-separated
diags_of() {
  local compiler=$1 source=$2 out
  out="$work/diags.$$.$RANDOM"
  run_dawn "$compiler" __check "$source" > "$out" 2>&1 || true
  grep '^D' "$out" || true
}

# ---- assertions on the real compiler -------------------------------------

expect_clean() {
  local name=$1 got
  got=$(diags_of "$dawn" "$cases/$name.dawn")
  [ -z "$got" ] || {
    echo "$got" >&2
    fail "$name: an accepted surface was rejected"
  }
}

expect_diags() {
  local name=$1 count=$2
  shift 2
  local got n
  got=$(diags_of "$dawn" "$cases/$name.dawn")
  n=$(printf '%s' "$got" | grep -c '^D' || true)
  [ "$n" -eq "$count" ] || {
    echo "$got" >&2
    fail "$name: expected $count diagnostic(s), got $n"
  }
  local message
  for message in "$@"; do
    printf '%s\n' "$got" | grep -Fq "$message" || {
      echo "$got" >&2
      fail "$name: missing expected diagnostic: $message"
    }
  done
}

expect_project_ok() {
  run_dawn "$dawn" check "$here/$1" > "$work/p.$RANDOM" 2>&1 ||
    fail "$1: an accepted project was rejected"
}

expect_project_fails() {
  local name=$1 message=$2 out="$work/p.$RANDOM"
  if run_dawn "$dawn" check "$here/$name" > "$out" 2>&1; then
    fail "$name: a rejected project was accepted"
  fi
  grep -Fq "$message" "$out" || {
    cat "$out" >&2
    fail "$name: missing expected diagnostic: $message"
  }
}

# ---- the bundled standard library, for the StdOnly audience --------------
#
# `StdOnly` is not reachable from a fixture: only `std/hamt` and `std/pvec` are
# internal-std modules, and a module's identity comes from where it is loaded.
# So the two Array cases mutate a copy of the real std instead: one adds a
# world-facing `pub` root that names `Array` (must be refused), the other adds
# an internal-std one (must be accepted, and its element still checked).

std_copy() {
  local dir="$work/std.$1"
  rm -rf "$dir"
  cp -R "$root/std" "$dir"
  printf '%s\n' "$dir"
}

check_with_std() {
  local stddir=$1 compiler=${2:-$dawn} out="$work/std-check.$RANDOM"
  run_dawn "$compiler" check --std "$stddir" "$cases/accepted.dawn" > "$out" 2>&1 && {
    printf '%s\n' ok
    return 0
  }
  cat "$out"
}

expect_std_refuses() {
  local stddir=$1 message=$2 got
  got=$(check_with_std "$stddir")
  printf '%s' "$got" | grep -Fq "$message" || {
    printf '%s\n' "$got" >&2
    fail "the bundled std was accepted, or refused for another reason: $message"
  }
}

expect_std_ok() {
  local stddir=$1 got
  got=$(check_with_std "$stddir")
  [ "$got" = ok ] || {
    printf '%s\n' "$got" >&2
    fail "the bundled std no longer loads"
  }
}

world_std=$(std_copy world)
cat >> "$world_std/bytes.dawn" <<'EOF'

pub fn surface_contract_world_array(a: Array[Int]) -> Int = array_len(a)
EOF

internal_std=$(std_copy internal)
cat >> "$internal_std/pvec.dawn" <<'EOF'

type SurfaceContractSecret = | SurfaceContractSecret

pub fn surface_contract_internal_array(a: Array[SurfaceContractSecret]) -> Int = array_len(a)
EOF

# ---- the fixture contract ------------------------------------------------

run_dawn "$dawn" --version > /dev/null

expect_clean accepted
expect_clean accept_private_impl
expect_clean accept_recursive_adt

expect_diags reject_alias 1 'public alias `Published` exposes private type `Secret`'
expect_diags reject_private_opaque 1 \
  'public function `hidden_id` exposes private type `HiddenId`'
expect_diags reject_opaque_arg 1 'public function `leak` exposes private type `Secret`'
expect_diags reject_adt_arg 1 'public function `leak` exposes private type `Secret`'
expect_diags reject_adt_field 1 'public type `Packet` exposes private type `Secret`'
expect_diags reject_const 1 'public constant `LEAK` exposes private type `Secret`'
expect_diags reject_trait_constraint 1 \
  'public function `keep` exposes private trait `Hidden`'
expect_diags reject_trait_method 1 \
  'public trait `Reveals` method `reveal` exposes private type `Secret`'
expect_diags reject_effect_op 1 \
  'public effect `Reveals` operation `reveal` exposes private type `Secret`'
expect_diags reject_private_effect 1 \
  'public function `raise_hidden` exposes private effect `Hidden`'
expect_diags reject_assoc_binding 1 \
  'observable impl `HasItem[PublicBox[T]]` exposes private type `Secret`'
expect_diags reject_impl_constraint 1 \
  'observable impl `HasItem[Holder[T]]` exposes private trait `Hidden`'
expect_diags reject_assoc_trait 2 \
  'function `project` return type projection `Item` trait -> private trait `Hidden`'
expect_diags reject_list_element 1 'function `leak` return type list element'
expect_diags reject_map_key 1 'function `leak` parameter `m` map key'
expect_diags reject_map_value 1 'function `leak` parameter `m` map value'
expect_diags reject_set_element 1 'function `leak` parameter `s` set element'
expect_diags reject_tuple_element 1 'function `leak` return type tuple element #2'
expect_diags reject_fn_param 1 'function `leak` parameter `f` function parameter #1'
expect_diags reject_fn_return 1 'function `leak` parameter `f` function return type'
expect_diags unused_export 1 'public function `never_used` exposes private type `Secret`'

# design §八: every occurrence, not just the first, and each on its own token
expect_diags reject_two_occurrences 2 \
  'function `leak` parameter `a` -> private type `Secret`' \
  'function `leak` parameter `b` list element -> private type `Secret`'

# design §六: `main`'s empty label set is main check's rule, and SEM-07 does
# not report a second diagnostic about the same public effect
expect_diags main_effect 1 'main cannot declare the effect `Ask`'

# design §三: the surface diagnostic precedes an unrelated body diagnostic
first=$(diags_of "$dawn" "$cases/order_before_body.dawn" | head -1)
case "$first" in
  *'public function `leak` exposes private type `Secret`'*) ;;
  *) echo "$first" >&2; fail "the surface diagnostic no longer comes first" ;;
esac

expect_project_ok consumer
expect_project_fails consumer_leak 'public function `imported_leak` exposes private type `Secret`'
expect_project_fails unused_export_project \
  'public function `never_imported` exposes private type `Secret`'
expect_project_fails phantom_distinct \
  'declares return type Phantom[String] but its body is Phantom[Int]'

expect_std_ok "$root/std"
expect_std_refuses "$world_std" \
  'public function `surface_contract_world_array` exposes standard-library-internal type `Array`'
expect_std_refuses "$internal_std" \
  'exposes private type `SurfaceContractSecret`'

echo "PASS  public surfaces name only what their audience can name"

# ---- mutants -------------------------------------------------------------

build_mutant() {
  local mutation=$1 dir="$work/$mutation"
  mkdir -p "$dir"
  cp -R "$root/selfhost" "$dir/selfhost"
  ln -s "$root/packages" "$dir/packages"
  ln -s "$root/compiler-plan" "$dir/compiler-plan"
  python3 "$here/mutate.py" "$mutation" "$dir"
  if ! run_dawn "$dawn" build "$dir/selfhost" -o "$dir/compiler.jar" > "$dir/build.out" 2>&1; then
    cat "$dir/build.out" >&2
    fail "$mutation mutant did not compile"
  fi
  if ! java -jar "$dir/compiler.jar" --version > "$dir/version.out" 2>&1; then
    cat "$dir/version.out" >&2
    fail "$mutation mutant compiled but could not run"
  fi
  printf '%s\n' "$dir/compiler.jar"
}

# The mutant must lose exactly the named diagnostic and keep everything else
# it had: a mutant that stops checking altogether is not evidence about a rule.
mutant_drops() {
  local mutation=$1 name=$2 message=$3 mutant got
  mutant=$(build_mutant "$mutation")
  got=$(diags_of "$mutant" "$cases/$name.dawn")
  if printf '%s' "$got" | grep -Fq "$message"; then
    echo "$got" >&2
    fail "$mutation: $name still reports its owning diagnostic"
  fi
  echo "PASS  $mutation compiles, then turns $name red"
}

mutant_adds() {
  local mutation=$1 name=$2 message=$3 mutant got
  mutant=$(build_mutant "$mutation")
  got=$(diags_of "$mutant" "$cases/$name.dawn")
  printf '%s' "$got" | grep -Fq "$message" || {
    echo "$got" >&2
    fail "$mutation: $name was still accepted"
  }
  echo "PASS  $mutation compiles, then turns $name red"
}

mutant_std_accepts() {
  local mutation=$1 stddir=$2 mutant got
  mutant=$(build_mutant "$mutation")
  got=$(check_with_std "$stddir" "$mutant")
  [ "$got" = ok ] || {
    printf '%s\n' "$got" >&2
    fail "$mutation: the std case is still refused"
  }
  echo "PASS  $mutation compiles, then turns the std audience case red"
}

mutant_std_refuses() {
  local mutation=$1 stddir=$2 message=$3 mutant got
  mutant=$(build_mutant "$mutation")
  got=$(check_with_std "$stddir" "$mutant")
  printf '%s' "$got" | grep -Fq "$message" || {
    printf '%s\n' "$got" >&2
    fail "$mutation: the std case was still accepted"
  }
  echo "PASS  $mutation compiles, then turns the std audience case red"
}

# A recursive public ADT is checked once, where it is its own root. A walker
# that also descended into fields at every *reference* does not terminate on
# `type Tree = | Node(left: Tree)` -- so the owning assertion is that the
# mutant cannot check the case at all, not that it says something different.
mutant_breaks_std() {
  local mutation=$1 message=$2 mutant out
  mutant=$(build_mutant "$mutation")
  out="$work/breaks.$RANDOM"
  if java -jar "$mutant" __check "$cases/accepted.dawn" > "$out" 2>&1; then
    cat "$out" >&2
    fail "$mutation: the bundled std still loads"
  fi
  grep -Fq "$message" "$out" || {
    cat "$out" >&2
    fail "$mutation: std broke for another reason"
  }
  echo "PASS  $mutation compiles, then turns the public-opaque contract red"
}

mutant_diverges() {
  local mutation=$1 name=$2 mutant out
  mutant=$(build_mutant "$mutation")
  out="$work/diverge.$RANDOM"
  if timeout 120 java -jar "$mutant" __check "$cases/$name.dawn" > "$out" 2>&1; then
    cat "$out" >&2
    fail "$mutation: the recursive type still checks once"
  fi
  echo "PASS  $mutation compiles, then turns $name red"
}

# design §八: the surface diagnostic must be *first*, so this mutant is caught
# by the order and not by the presence of either diagnostic
mutant_reorders() {
  local mutation=$1 mutant first
  mutant=$(build_mutant "$mutation")
  first=$(diags_of "$mutant" "$cases/order_before_body.dawn" | head -1)
  case "$first" in
    *'public function `leak` exposes private type `Secret`'*)
      fail "$mutation: the surface diagnostic still comes first" ;;
  esac
  echo "PASS  $mutation compiles, then turns the ordering contract red"
}

# design §7.1: the *exporter* refuses its own surface. This mutant moves the
# check to the importer, so it necessarily also stops rejecting the
# single-module fixtures -- a program with no importer has no use site to check
# at, which is the whole point. What identifies it is the pair below: the
# unimported export is accepted while the imported one is still refused.
mutant_moves_to_importer() {
  local mutation=$1 mutant out
  mutant=$(build_mutant "$mutation")
  out="$work/importer.$RANDOM"
  if ! run_dawn "$mutant" check "$here/unused_export_project" > "$out" 2>&1; then
    cat "$out" >&2
    fail "$mutation: the unimported export is still refused"
  fi
  if run_dawn "$mutant" check "$here/consumer_leak" > "$out" 2>&1; then
    cat "$out" >&2
    fail "$mutation: the imported leak is not refused either -- the pass is simply gone"
  fi
  echo "PASS  $mutation compiles, then turns the exporter contract red"
}

mutants=(
  "recurse-opaque-representation"
  "skip-opaque-args"
  "opaque-args-existential"
  "skip-adt-args"
  "recurse-adt-fields"
  "skip-alias-target"
  "skip-assoc-trait"
  "reject-all-effects"
  "pass-all-effects"
  "skip-impl-constraints"
  "skip-impl-assoc"
  "impl-always-observable"
  "surface-after-bodies"
  "check-imports-not-exports"
  "skip-list-element"
  "skip-map-key"
  "skip-map-value"
  "skip-set-element"
  "skip-array-element"
  "skip-tuple-element"
  "skip-fn-param"
  "skip-fn-return"
  "array-is-world"
  "stdonly-collapses-to-world"
)

run_mutant() {
  case "$1" in
    recurse-opaque-representation)
      # the witness is in the tree: std/bytes declares `pub opaque type Buf =
      # Array[Int]`, a public opaque over a standard-library-internal
      # representation. Walking the representation makes the bundled std
      # itself unloadable.
      mutant_breaks_std "$1" 'public function `buf` exposes standard-library-internal type `Array`' ;;
    skip-opaque-args)
      mutant_drops "$1" reject_opaque_arg 'public function `leak`' ;;
    opaque-args-existential)
      local mutant out
      mutant=$(build_mutant "$1")
      out="$work/phantom.$RANDOM"
      if ! run_dawn "$mutant" check "$here/phantom_distinct" > "$out" 2>&1; then
        cat "$out" >&2
        fail "$1: the phantom instances are still distinct"
      fi
      echo "PASS  $1 compiles, then turns phantom_distinct red" ;;
    skip-adt-args)
      mutant_drops "$1" reject_adt_arg 'public function `leak`' ;;
    recurse-adt-fields)
      mutant_diverges "$1" accept_recursive_adt ;;
    skip-alias-target)
      mutant_drops "$1" reject_alias 'public alias `Published`' ;;
    skip-assoc-trait)
      mutant_drops "$1" reject_assoc_trait 'projection `Item` trait' ;;
    reject-all-effects)
      mutant_adds "$1" accepted 'exposes private effect `Ask`' ;;
    pass-all-effects)
      mutant_drops "$1" reject_private_effect 'exposes private effect `Hidden`' ;;
    skip-impl-constraints)
      mutant_drops "$1" reject_impl_constraint 'observable impl' ;;
    skip-impl-assoc)
      mutant_drops "$1" reject_assoc_binding 'observable impl' ;;
    impl-always-observable)
      mutant_adds "$1" accept_private_impl 'exposes private type `Secret`' ;;
    surface-after-bodies)
      mutant_reorders "$1" ;;
    check-imports-not-exports)
      mutant_moves_to_importer "$1" ;;
    skip-list-element)
      mutant_drops "$1" reject_list_element 'list element' ;;
    skip-map-key)
      mutant_drops "$1" reject_map_key 'map key' ;;
    skip-map-value)
      mutant_drops "$1" reject_map_value 'map value' ;;
    skip-set-element)
      mutant_drops "$1" reject_set_element 'set element' ;;
    skip-array-element)
      mutant_std_accepts "$1" "$internal_std" ;;
    skip-tuple-element)
      mutant_drops "$1" reject_tuple_element 'tuple element' ;;
    skip-fn-param)
      mutant_drops "$1" reject_fn_param 'function parameter #1' ;;
    skip-fn-return)
      mutant_drops "$1" reject_fn_return 'function return type' ;;
    array-is-world)
      mutant_std_accepts "$1" "$world_std" ;;
    stdonly-collapses-to-world)
      mutant_std_refuses "$1" "$root/std" 'standard-library-internal type `Array`' ;;
    *) fail "no assertion for mutant $1" ;;
  esac
}

n=0
ran=0
for mutation in "${mutants[@]}"; do
  if [ -n "$only" ]; then
    if [ "$mutation" = "$only" ]; then
      run_mutant "$mutation"
      ran=$((ran + 1))
    fi
    n=$((n + 1))
    continue
  fi
  if [ $(( n % shard_n )) -eq $(( shard_i - 1 )) ]; then
    run_mutant "$mutation"
    ran=$((ran + 1))
  fi
  n=$((n + 1))
done

# Design §十二 lists a seventeenth mutant, `doc_json_omits_private_impl`, whose
# rule is the doc filter. That filter is stage three of the design and does not
# exist yet, so the mutant has nothing to remove; it lands with the filter.
#
# Two more of the design's mutants have no witness in today's language, and the
# walker keeps their branches anyway:
#   * a projection's *subject* is always a rigid type variable (reduction is
#     eager, assoc-types-design D3), so it can never be a private identity;
#   * a written function type may not name a declared effect at all
#     (effects-soundness-design §4.1), so a nested effect row is always empty.
# Both branches stay because the rule is about the type, not about what today's
# parser lets an author write.

echo "OK: ${ran} mutant(s) of ${#mutants[@]}, each red on its own contract"
