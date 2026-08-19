#!/usr/bin/env bash
# Hold SYN-13 across parser, checker, Core lowering, LSP, and the written
# JVM/native Iter oracle. Every production mutant runs this complete set.
#
#   ./scripts/for-pattern-contract/run.sh              # everything
#   ./scripts/for-pattern-contract/run.sh --shard 2/3  # fixtures + a third
#
# Sharding: every shard runs the fixture half and validates the whole matrix,
# so no shard is a partial verdict; the mutants are divided round-robin, and
# each shard records what it ran for scripts/mutant-coverage/check.py to hold
# the union to the matrix.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/for-pattern-contract"
dawn=${DAWN_BIN:-"$root/bin/dawn"}

# shellcheck source=scripts/mutant-coverage/shard.sh
source "$root/scripts/mutant-coverage/shard.sh"
shard_parse "$@"
if [ "${#shard_rest[@]}" -gt 0 ]; then
  echo "for-pattern-contract: unknown argument(s): ${shard_rest[*]}" >&2
  exit 2
fi
syntax="$here/syntax.dawn"
refutable="$here/refutable.dawn"
derived="$here/derived.dawn"
scope="$here/scope.dawn"
complexity="$here/complexity.dawn"
bottom="$here/bottom.dawn"
iter_core="$here/iter_core.dawn"
range_core="$here/range_core.dawn"
runtime="$root/scripts/spike-native/iter_for.dawn"
runtime_expected="$root/scripts/spike-native/iter_for.expect"
matrix="$here/matrix.tsv"
work=$(mktemp -d "${TMPDIR:-/tmp}/for-pattern-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "for-pattern-contract: $*" >&2
  exit 1
}

for command in java python3 timeout; do
  command -v "$command" > /dev/null || fail "missing required command: $command"
done

ASSERT_SYNTAX='for headers reuse the complete recursive pattern grammar'
ASSERT_IRREFUTABLE='refutable for patterns are rejected rather than filtered'
ASSERT_BINDINGS='for pattern bindings reach the body with correct values'
ASSERT_GET_ONCE='iter_get is evaluated once per iteration before pattern lowering'
ASSERT_SOURCE_ONCE='iterable sources are evaluated once before the loop'
ASSERT_SOURCE_PLACEMENT='iterable source is evaluated before loop entry'
ASSERT_START_PLACEMENT='iter_start is evaluated before loop entry'
ASSERT_GET_PLACEMENT='iter_get initializes the hidden item before pattern lowering'
ASSERT_SCOPE='for pattern bindings stay inside the loop body'
ASSERT_LSP_QUERY='for pattern headers expose binder and constructor queries'
ASSERT_LSP_HEADER='for pattern completion suppresses values across the recursive header'
ASSERT_LSP_LATEST_FOR='incomplete pattern recovery selects the latest enclosing for'
ASSERT_LSP_NEWLINE='incomplete pattern recovery does not cross an ordinary newline'
ASSERT_LSP_NESTED_DEPTH='incomplete pattern recovery preserves nested delimiter depth'
ASSERT_LSP_RECORD_DEPTH='incomplete pattern recovery preserves record delimiter depth'
ASSERT_LSP_TOP_LEVEL_IN='incomplete pattern recovery requires a top-level in delimiter'
ASSERT_LSP_PREVIOUS_PIPE='incomplete pattern recovery requires a preceding pipe'
ASSERT_LSP_BOUNDARY='incomplete pattern recovery requires a same-depth pattern boundary'
ASSERT_LSP_HEADER_INTERVAL='incomplete pattern recovery stays before in, outside source body and after'
ASSERT_LSP_SOURCE_CTOR='incomplete pattern recovery excludes rejected source constructors'
ASSERT_LSP_QUALIFIED='for pattern qualified completion exposes only module constructors'
ASSERT_LSP_RANGE='range upper-bound completion offers outer locals'
ASSERT_LSP_SCOPE='for completion does not leak pattern or body locals'
ASSERT_DERIVED='invalid for patterns suppress derived irrefutability diagnostics'
ASSERT_START_ONCE='iter_start is evaluated once before the loop'
ASSERT_COMPLEXITY='for irrefutability analysis fails closed at its work budget'
ASSERT_RANGE_SLOT='range loops keep induction state separate from pattern bindings'
ASSERT_BOTTOM='nonreturning iterable sources lower once as bottom without a witness'

owner_registry="$work/owners"
printf '%s\n' \
  "$ASSERT_SYNTAX" \
  "$ASSERT_IRREFUTABLE" \
  "$ASSERT_BINDINGS" \
  "$ASSERT_GET_ONCE" \
  "$ASSERT_SOURCE_ONCE" \
  "$ASSERT_SOURCE_PLACEMENT" \
  "$ASSERT_START_PLACEMENT" \
  "$ASSERT_GET_PLACEMENT" \
  "$ASSERT_SCOPE" \
  "$ASSERT_LSP_QUERY" \
  "$ASSERT_LSP_HEADER" \
  "$ASSERT_LSP_LATEST_FOR" \
  "$ASSERT_LSP_NEWLINE" \
  "$ASSERT_LSP_NESTED_DEPTH" \
  "$ASSERT_LSP_RECORD_DEPTH" \
  "$ASSERT_LSP_TOP_LEVEL_IN" \
  "$ASSERT_LSP_PREVIOUS_PIPE" \
  "$ASSERT_LSP_BOUNDARY" \
  "$ASSERT_LSP_HEADER_INTERVAL" \
  "$ASSERT_LSP_SOURCE_CTOR" \
  "$ASSERT_LSP_QUALIFIED" \
  "$ASSERT_LSP_RANGE" \
  "$ASSERT_LSP_SCOPE" \
  "$ASSERT_DERIVED" \
  "$ASSERT_START_ONCE" \
  "$ASSERT_COMPLEXITY" \
  "$ASSERT_RANGE_SLOT" \
  "$ASSERT_BOTTOM" \
  > "$owner_registry"

validate_matrix() {
  local registry=$1 matrix_path=$2 owners=$3 prefix=$4
  local registry_names="$prefix.registry.names"
  local owner_names="$prefix.owner.names"
  local matrix_names="$prefix.matrix.names"
  local matrix_owners="$prefix.matrix.owners"

  awk '$0 == "" || index($0, "\t") != 0 || ++seen[$0] > 1 { exit 1 } { print }
    END { if (NR == 0) exit 1 }' "$registry" > "$registry_names" || return 1
  awk '$0 == "" || index($0, "\t") != 0 || ++seen[$0] > 1 { exit 1 } { print }
    END { if (NR == 0) exit 1 }' "$owners" > "$owner_names" || return 1
  awk -F '\t' -v names="$matrix_names" -v owners_out="$matrix_owners" '
    $0 == "" || $0 ~ /^#/ { next }
    $1 == "schema" {
      if (NF != 2 || $2 != "1" || schema_seen) exit 1
      schema_seen = 1
      next
    }
    {
      if ($1 != "mutant" || NF != 4 || $2 == "" || $3 == "" || $4 == "") exit 1
      if (++mutants[$2] > 1 || ++owner_seen[$4] > 1) exit 1
      print $2 > names
      print $4 > owners_out
      records += 1
    }
    END { if (!schema_seen || records == 0) exit 1 }
  ' "$matrix_path" || return 1
  sort "$registry_names" > "$registry_names.sorted"
  sort "$matrix_names" > "$matrix_names.sorted"
  cmp -s "$registry_names.sorted" "$matrix_names.sorted" || return 1
  sort "$owner_names" > "$owner_names.sorted"
  sort "$matrix_owners" > "$matrix_owners.sorted"
  cmp -s "$owner_names.sorted" "$matrix_owners.sorted" || return 1
}

registry="$work/registry"
python3 "$here/mutate.py" --list > "$registry"
validate_matrix "$registry" "$matrix" "$owner_registry" "$work/matrix" ||
  fail "persistent matrix, executable mutators, and owners disagree"

selftest=0
expect_invalid_matrix() {
  local label=$1 candidate=$2
  selftest=$((selftest + 1))
  if validate_matrix "$registry" "$candidate" "$owner_registry" \
      "$work/selftest-$selftest" > /dev/null 2>&1; then
    fail "matrix validation accepted $label"
  fi
  echo "PASS  matrix validation rejects $label"
}

awk -F '\t' 'BEGIN { OFS = "\t" }
  $1 == "mutant" && first == "" { first = $2; print; next }
  $1 == "mutant" && !changed { $2 = first; changed = 1 }
  { print }
' "$matrix" > "$work/matrix-duplicate-mutant"
expect_invalid_matrix "a duplicate mutant" "$work/matrix-duplicate-mutant"

awk -F '\t' 'BEGIN { OFS = "\t" }
  $1 == "mutant" && first == "" { first = $4; print; next }
  $1 == "mutant" && !changed { $4 = first; changed = 1 }
  { print }
' "$matrix" > "$work/matrix-duplicate-owner"
expect_invalid_matrix "a duplicate owner" "$work/matrix-duplicate-owner"

awk -F '\t' '$1 != "schema"' "$matrix" > "$work/matrix-no-schema"
expect_invalid_matrix "a missing schema" "$work/matrix-no-schema"

python3 "$here/core_check.py" --self-test

build_compiler() {
  local source=$1 output=$2 label=$3
  if ! "$dawn" build "$source" -o "$output" > "$work/$label-build.out" 2>&1; then
    cat "$work/$label-build.out" >&2
    fail "$label compiler did not compile"
  fi
  java -Xss512m -Xmx2g -jar "$output" --version > /dev/null ||
    fail "$label compiler did not initialize"
}

capture_parse() {
  local jar=$1 source=$2 output=$3
  timeout --kill-after=5s 30s java -Xss512m -Xmx2g -jar "$jar" __parse "$source" \
    > "$output" 2>&1
}

capture_diagnostics() {
  local jar=$1 source=$2 output=$3
  timeout --kill-after=5s 30s java -Xss512m -Xmx2g -jar "$jar" __check "$source" \
    > "$output.raw" 2>&1
  grep '^D' "$output.raw" > "$output" || true
}

diagnostic_count() {
  awk 'END { print NR + 0 }' "$1"
}

contains_count() {
  local file=$1 wanted=$2
  awk -v wanted="$wanted" 'index($0, wanted) { n += 1 } END { print n + 0 }' "$file"
}

syntax_ok() {
  local jar=$1 output=$2
  capture_parse "$jar" "$syntax" "$output/parse.out" || return 1
  if grep -q '^!' "$output/parse.out"; then return 1; fi
  [ "$(grep -Fc 'PTuple ' "$output/parse.out")" -ge 1 ] || return 1
  [ "$(grep -Fc 'PList npre=1 rest=true restname=tail' "$output/parse.out")" -eq 1 ] || return 1
  [ "$(grep -Fc 'PCtor Pair ' "$output/parse.out")" -eq 1 ] || return 1
  [ "$(grep -Fc 'PCtor Record ' "$output/parse.out")" -eq 1 ] || return 1
  [ "$(grep -Fc 'PArg name=left' "$output/parse.out")" -eq 1 ] || return 1
  [ "$(grep -Fc 'PArg name=right' "$output/parse.out")" -eq 1 ] || return 1
  [ "$(grep -Fc 'PQual q.Only ' "$output/parse.out")" -eq 1 ] || return 1
  [ "$(grep -Fc 'POr nalts=2' "$output/parse.out")" -eq 1 ] || return 1
  cp "$syntax" "$output/syntax_fmt.dawn"
  timeout --kill-after=5s 30s java -Xss512m -Xmx2g -jar "$jar" \
    fmt "$output/syntax_fmt.dawn" --check > "$output/fmt.out" 2>&1 || return 1
  cat > "$output/legacy.dawn" <<'EOF'
fn legacy(xs: List[Int]) -> Unit = { for value in xs { let _ = value } }
EOF
  capture_diagnostics "$jar" "$output/legacy.dawn" "$output/legacy.out" || return 1
  [ ! -s "$output/legacy.out" ]
}

probe_compiler() {
  local jar=$1 output=$2
  mkdir -p "$output"
  : > "$output/assertions.raw"

  if ! syntax_ok "$jar" "$output"; then
    printf 'ASSERT: %s\n' "$ASSERT_SYNTAX" >> "$output/assertions.raw"
  fi

  capture_diagnostics "$jar" "$refutable" "$output/refutable.out" || true
  if [ "$(diagnostic_count "$output/refutable.out")" -ne 1 ] ||
      [ "$(contains_count "$output/refutable.out" 'for pattern must match every item')" -ne 1 ]; then
    printf 'ASSERT: %s\n' "$ASSERT_IRREFUTABLE" >> "$output/assertions.raw"
  fi

  capture_diagnostics "$jar" "$derived" "$output/derived.out" || true
  if [ "$(diagnostic_count "$output/derived.out")" -ne 3 ] ||
      [ "$(contains_count "$output/derived.out" 'pattern type String does not match scrutinee type Int')" -ne 1 ] ||
      [ "$(contains_count "$output/derived.out" 'undefined constructor in pattern: Missing')" -ne 1 ] ||
      [ "$(contains_count "$output/derived.out" 'or-pattern alternative does not bind `value`')" -ne 1 ] ||
      grep -Fq 'for pattern must match every item' "$output/derived.out"; then
    printf 'ASSERT: %s\n' "$ASSERT_DERIVED" >> "$output/assertions.raw"
  fi

  capture_diagnostics "$jar" "$scope" "$output/scope.out" || true
  if [ "$(diagnostic_count "$output/scope.out")" -ne 1 ] ||
      [ "$(contains_count "$output/scope.out" 'undefined variable: leaked')" -ne 1 ]; then
    printf 'ASSERT: %s\n' "$ASSERT_SCOPE" >> "$output/assertions.raw"
  fi

  capture_diagnostics "$jar" "$complexity" "$output/complexity.out" || true
  if [ "$(diagnostic_count "$output/complexity.out")" -ne 1 ] ||
      [ "$(contains_count "$output/complexity.out" 'pattern analysis exceeded its complexity budget')" -ne 1 ]; then
    printf 'ASSERT: %s\n' "$ASSERT_COMPLEXITY" >> "$output/assertions.raw"
  fi

  capture_diagnostics "$jar" "$bottom" "$output/bottom-check.out" || true
  mkdir -p "$output/bottom-dump"
  local bottom_lower=0
  timeout --kill-after=5s 45s java -Xss512m -Xmx2g -jar "$jar" __lower \
    --std "$root/std" --dump "$output/bottom-dump" "$bottom" \
    > "$output/bottom-lower.out" 2> "$output/bottom-lower.err" || bottom_lower=$?
  if [ -s "$output/bottom-check.out" ] ||
      [ "$bottom_lower" -ne 0 ] ||
      ! python3 "$here/core_check.py" bottom "$output/bottom-dump/bottom.core" \
        > "$output/bottom-core.out" 2> "$output/bottom-core.err"; then
    printf 'ASSERT: %s\n' "$ASSERT_BOTTOM" >> "$output/assertions.raw"
  fi

  if ! timeout --kill-after=5s 45s java -Xss512m -Xmx2g -jar "$jar" run "$runtime" \
      > "$output/runtime.out" 2> "$output/runtime.err" ||
      ! cmp -s "$runtime_expected" "$output/runtime.out" ||
      [ -s "$output/runtime.err" ]; then
    printf 'ASSERT: %s\n' "$ASSERT_BINDINGS" >> "$output/assertions.raw"
  fi

  mkdir -p "$output/iter-dump" "$output/range-dump"
  local iter_lower=0 range_lower=0
  timeout --kill-after=5s 45s java -Xss512m -Xmx2g -jar "$jar" __lower \
    --std "$root/std" --dump "$output/iter-dump" "$iter_core" \
    > "$output/iter-lower.out" 2> "$output/iter-lower.err" || iter_lower=$?
  timeout --kill-after=5s 45s java -Xss512m -Xmx2g -jar "$jar" __lower \
    --std "$root/std" --dump "$output/range-dump" "$range_core" \
    > "$output/range-lower.out" 2> "$output/range-lower.err" || range_lower=$?
  if [ "$iter_lower" -ne 0 ] ||
      ! python3 "$here/core_check.py" source "$output/iter-dump/iter_core.core" \
        > "$output/source-core.out" 2> "$output/source-core.err"; then
    printf 'ASSERT: %s\n' "$ASSERT_SOURCE_ONCE" >> "$output/assertions.raw"
  fi
  if [ "$iter_lower" -ne 0 ] ||
      ! python3 "$here/core_check.py" start "$output/iter-dump/iter_core.core" \
        > "$output/start-core.out" 2> "$output/start-core.err"; then
    printf 'ASSERT: %s\n' "$ASSERT_START_ONCE" >> "$output/assertions.raw"
  fi
  if [ "$iter_lower" -ne 0 ] ||
      ! python3 "$here/core_check.py" get "$output/iter-dump/iter_core.core" \
        > "$output/get-core.out" 2> "$output/get-core.err"; then
    printf 'ASSERT: %s\n' "$ASSERT_GET_ONCE" >> "$output/assertions.raw"
  fi
  if [ "$iter_lower" -ne 0 ] ||
      ! python3 "$here/core_check.py" source-placement "$output/iter-dump/iter_core.core" \
        > "$output/source-placement-core.out" 2> "$output/source-placement-core.err"; then
    printf 'ASSERT: %s\n' "$ASSERT_SOURCE_PLACEMENT" >> "$output/assertions.raw"
  fi
  if [ "$iter_lower" -ne 0 ] ||
      ! python3 "$here/core_check.py" start-placement "$output/iter-dump/iter_core.core" \
        > "$output/start-placement-core.out" 2> "$output/start-placement-core.err"; then
    printf 'ASSERT: %s\n' "$ASSERT_START_PLACEMENT" >> "$output/assertions.raw"
  fi
  if [ "$iter_lower" -ne 0 ] ||
      ! python3 "$here/core_check.py" get-placement "$output/iter-dump/iter_core.core" \
        > "$output/get-placement-core.out" 2> "$output/get-placement-core.err"; then
    printf 'ASSERT: %s\n' "$ASSERT_GET_PLACEMENT" >> "$output/assertions.raw"
  fi
  if [ "$range_lower" -ne 0 ] ||
      ! python3 "$here/core_check.py" range "$output/range-dump/range_core.core" \
        > "$output/range-core.out" 2> "$output/range-core.err"; then
    printf 'ASSERT: %s\n' "$ASSERT_RANGE_SLOT" >> "$output/assertions.raw"
  fi

  local lsp_status=0
  python3 "$here/lsp.py" java "$jar" "$root" \
    > "$output/lsp.out" 2> "$output/lsp.err" || lsp_status=$?
  grep '^ASSERT: ' "$output/lsp.out" >> "$output/assertions.raw" || true
  if [ "$lsp_status" -ne 0 ] && ! grep -q '^ASSERT: ' "$output/lsp.out"; then
    printf 'ASSERT: %s\n' "$ASSERT_LSP_QUERY" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_HEADER" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_LATEST_FOR" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_NEWLINE" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_NESTED_DEPTH" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_RECORD_DEPTH" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_TOP_LEVEL_IN" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_PREVIOUS_PIPE" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_BOUNDARY" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_HEADER_INTERVAL" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_SOURCE_CTOR" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_QUALIFIED" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_RANGE" >> "$output/assertions.raw"
    printf 'ASSERT: %s\n' "$ASSERT_LSP_SCOPE" >> "$output/assertions.raw"
  fi

  awk '!seen[$0]++' "$output/assertions.raw" > "$output/assertions.out"
  printf 'complete\n' > "$output/probe.complete"
}

dump_probe() {
  local output=$1
  for file in assertions.out parse.out fmt.out refutable.out.raw derived.out.raw \
    scope.out.raw complexity.out.raw bottom-check.out.raw bottom-lower.err bottom-core.err \
    runtime.out runtime.err iter-lower.err \
    range-lower.err source-core.err start-core.err get-core.err \
    source-placement-core.err start-placement-core.err get-placement-core.err range-core.err \
    lsp.out lsp.err; do
    if [ -f "$output/$file" ]; then cat "$output/$file" >&2; fi
  done
}

observed="$work/observed.jar"
build_compiler "$root/selfhost" "$observed" observed
probe_compiler "$observed" "$work/observed"
[ "$(cat "$work/observed/probe.complete" 2> /dev/null || true)" = complete ] ||
  fail "observed compiler probe did not run the complete assertion set"
if [ -s "$work/observed/assertions.out" ]; then
  dump_probe "$work/observed"
  fail "observed compiler contract failed"
fi
cat "$work/observed/lsp.out"
echo "PASS  observed compiler satisfies the complete for-pattern assertion set"

expect_mutant_red() {
  local name=$1 relative=$2 owner=$3
  local mutant="$work/$name"
  mkdir -p "$mutant"
  cp -R "$root/selfhost" "$mutant/selfhost"
  cp -R "$root/compiler-plan" "$mutant/compiler-plan"
  ln -s "$root/packages" "$mutant/packages"
  python3 "$here/mutate.py" "$name" "$mutant/selfhost" > "$mutant/changed.out"
  printf '%s\n' "$relative" > "$mutant/changed.expected"
  cmp -s "$mutant/changed.expected" "$mutant/changed.out" ||
    fail "$name executable target disagrees with matrix.tsv"
  cmp -s "$root/selfhost/$relative" "$mutant/selfhost/$relative" &&
    fail "$name did not change production source"
  build_compiler "$mutant/selfhost" "$mutant/compiler.jar" "$name"
  probe_compiler "$mutant/compiler.jar" "$mutant/probe"
  [ "$(cat "$mutant/probe/probe.complete" 2> /dev/null || true)" = complete ] ||
    fail "$name probe did not run the complete assertion set"
  printf 'ASSERT: %s\n' "$owner" > "$mutant/assert.expected"
  if ! cmp -s "$mutant/assert.expected" "$mutant/probe/assertions.out"; then
    dump_probe "$mutant/probe"
    fail "$name mutant missed its unique owner"
  fi
  echo "PASS  $name changes production source and turns only '$owner' red"
}

shard_begin for-pattern-contract
mutant_position=0
while IFS=$'\t' read -r record name relative owner; do
  if [ "$record" = mutant ]; then
    if ! shard_skips "$mutant_position"; then
      shard_record "$name"
      expect_mutant_red "$name" "$relative" "$owner"
    fi
    mutant_position=$((mutant_position + 1))
  fi
done < "$matrix"
shard_report "$mutant_position"

echo "for-pattern-contract: OK"
