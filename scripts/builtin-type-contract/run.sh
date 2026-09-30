#!/usr/bin/env bash
# The checker, LSP and reference expose different views of one layered
# builtin-type inventory; twenty-six compiling mutants prove each consumer,
# every Never context, and both sides of the reference's reverse
# function-membership check.
#
#   ./scripts/builtin-type-contract/run.sh                 # everything
#   ./scripts/builtin-type-contract/run.sh --shard 2/4     # probe + a quarter
#   ./scripts/builtin-type-contract/run.sh --only <mutant> # one mutant
#
#   ITEM_TIMES=<file> ./scripts/builtin-type-contract/run.sh
#                                # also append `<mutant> <seconds>` per mutant,
#                                # for balancing the shards (matrix.txt says how)
#
# Sharding exists because a mutant costs one whole compiler build plus a
# probe. Every shard first runs probe.py against the real compiler, so no
# shard is a partial verdict about what the inventory contract asserts; the
# mutants are divided round-robin, and each shard records what it ran for
# scripts/mutant-coverage/check.py to hold the union to matrix.txt.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
probe="$root/scripts/builtin-type-contract/probe.py"
matrix="$root/scripts/builtin-type-contract/matrix.txt"
work=$(mktemp -d "${TMPDIR:-/tmp}/builtin-type-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

# shellcheck source=scripts/mutant-coverage/shard.sh
source "$root/scripts/mutant-coverage/shard.sh"
shard_parse "$@"
only=
if [ "${#shard_rest[@]}" -gt 0 ]; then
  case "${shard_rest[0]}" in
    --only)
      [ "${#shard_rest[@]}" -eq 2 ] || { echo "--only needs a mutant name" >&2; exit 2; }
      only=${shard_rest[1]}
      ;;
    *)
      echo "builtin-type-contract: unknown argument(s): ${shard_rest[*]}" >&2
      exit 2
      ;;
  esac
fi

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# The executable mutant list, in run order. matrix.txt is the persistent
# record the coverage checker reads; the two are held equal in both
# directions below.
mutants=(
  stale-checker-consumer
  stale-lsp-consumer
  omit-return-lsp
  omit-return-hover
  omit-doc-type
  flatten-return-doc
  omit-public-function-doc
  omit-prelude-function-doc
  reject-top-return
  reject-local-return
  reject-trait-return
  reject-impl-return
  reject-effect-return
  reject-function-type-return
  allow-storage-parameter
  allow-storage-field
  allow-storage-const
  allow-storage-let
  allow-storage-generic
  allow-storage-tuple
  allow-function-parameter
  allow-storage-assoc
  allow-direct-alias
  allow-reserved-name
  allow-never-fallthrough
  make-io-exit-bottom
)

printf '%s\n' "${mutants[@]}" > "$work/matrix.executable"
grep -v '^#' "$matrix" | grep -v '^$' > "$work/matrix.recorded" || true
cmp -s "$work/matrix.executable" "$work/matrix.recorded" || {
  diff -u "$work/matrix.recorded" "$work/matrix.executable" >&2 || true
  fail "matrix.txt and the runner's executable mutant list disagree"
}

new_mutant() {
  mutant="$work/$1"
  mkdir -p "$mutant"
  cp -R "$root/selfhost" "$mutant/selfhost"
  cp -R "$root/compiler-plan" "$mutant/compiler-plan"
  ln -s "$root/packages" "$mutant/packages"
}

build_mutant() {
  if ! "$dawn" build "$mutant/selfhost" -o "$mutant/compiler.jar" \
      > "$mutant/build.out" 2>&1; then
    cat "$mutant/build.out" >&2
    fail "$1 mutant did not compile"
  fi
  if ! java -jar "$mutant/compiler.jar" --version \
      > "$mutant/version.out" 2>&1; then
    cat "$mutant/version.out" >&2
    fail "$1 mutant jar did not answer --version"
  fi
}

expect_marker() {
  local name=$1
  local marker=$2
  if python3 "$probe" "$mutant/compiler.jar" > "$mutant/probe.out" 2>&1; then
    fail "$name mutant stayed green"
  fi
  grep '^ASSERT: ' "$mutant/probe.out" > "$mutant/assertions.out" || true
  printf 'ASSERT: %s\n' "$marker" > "$mutant/assertions.expected"
  if ! cmp -s "$mutant/assertions.expected" "$mutant/assertions.out"; then
    cat "$mutant/probe.out" >&2
    fail "$name mutant missed its unique owning assertion"
  fi
  echo "PASS  $name compiles, then turns only $marker red"
}

# Which assertion each mutant must turn red, and nothing else. The edits
# themselves live in mutate.py, one registered mutation per mutant name, so
# mutation-anchor-preflight.py proves their anchors before any build, not
# only when the shard holding a mutant reaches it.
marker_of() {
  case "$1" in
    stale-checker-consumer) echo CHECKER_TYPE_INVENTORY ;;
    stale-lsp-consumer) echo LSP_TYPE_INVENTORY ;;
    omit-return-lsp) echo LSP_NEVER_RETURN_CONTEXT ;;
    omit-return-hover) echo LSP_NEVER_RETURN_HOVER ;;
    omit-doc-type) echo DOC_TYPE_INVENTORY ;;
    flatten-return-doc) echo DOC_TYPE_INVENTORY ;;
    omit-public-function-doc) echo DOC_FUNCTION_INVENTORY ;;
    omit-prelude-function-doc) echo DOC_FUNCTION_INVENTORY ;;
    reject-top-return) echo NEVER_TOP_RETURN ;;
    reject-local-return) echo NEVER_LOCAL_RETURN ;;
    reject-trait-return) echo NEVER_TRAIT_RETURN ;;
    reject-impl-return) echo NEVER_IMPL_RETURN ;;
    reject-effect-return) echo NEVER_EFFECT_RETURN ;;
    reject-function-type-return) echo NEVER_FUNCTION_TYPE_RETURN ;;
    allow-storage-parameter) echo NEVER_STORAGE_PARAMETER ;;
    allow-storage-field) echo NEVER_STORAGE_FIELD ;;
    allow-storage-const) echo NEVER_STORAGE_CONST ;;
    allow-storage-let) echo NEVER_STORAGE_LET ;;
    allow-storage-generic) echo NEVER_STORAGE_GENERIC ;;
    allow-storage-tuple) echo NEVER_STORAGE_TUPLE ;;
    allow-function-parameter) echo NEVER_FUNCTION_PARAMETER ;;
    allow-storage-assoc) echo NEVER_STORAGE_ASSOC ;;
    allow-direct-alias) echo NEVER_ALIAS_DIRECT ;;
    allow-reserved-name) echo NEVER_RESERVED_NAME ;;
    allow-never-fallthrough) echo NEVER_BODY_DIVERGES ;;
    make-io-exit-bottom) echo IO_EXIT_UNIT ;;
    *) return 1 ;;
  esac
}

run_builtin_mutant() {
  local marker
  marker=$(marker_of "$1") || fail "no assertion for mutant $1"
  new_mutant "$1"
  python3 "$root/scripts/builtin-type-contract/mutate.py" "$1" "$mutant"
  build_mutant "$1"
  expect_marker "$1" "$marker"
}

# Per-mutant wall clock, when ITEM_TIMES names a file. The round-robin deal in
# matrix.txt is only as good as the costs it was computed from, and a mutant
# here is one whole compiler build plus a probe, so the costs are neither equal
# nor guessable by eye. Off by default and free when off.
timed_mutant() { # name
  if [ -z "${ITEM_TIMES:-}" ]; then
    run_builtin_mutant "$1"
    return
  fi
  local start end
  start=${EPOCHREALTIME/,/.}
  run_builtin_mutant "$1"
  end=${EPOCHREALTIME/,/.}
  awk -v n="$1" -v a="$start" -v b="$end" 'BEGIN{printf "%s %.2f\n", n, b-a}' >> "$ITEM_TIMES"
}

"$dawn" --version > /dev/null
python3 "$probe" "$root/build/dawn-selfhost.jar"

if [ -n "$only" ]; then
  found=0
  for name in "${mutants[@]}"; do
    if [ "$name" = "$only" ]; then
      timed_mutant "$name"
      found=1
    fi
  done
  [ "$found" -eq 1 ] || fail "no mutant named $only"
else
  shard_begin builtin-type-contract
  position=0
  for name in "${mutants[@]}"; do
    if ! shard_skips "$position"; then
      shard_record "$name"
      timed_mutant "$name"
    fi
    position=$((position + 1))
  done
  shard_report "${#mutants[@]}"
fi
