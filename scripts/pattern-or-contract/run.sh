#!/usr/bin/env bash
# Or-patterns have one arm, one environment and source-level negative controls.
#
#   ./scripts/pattern-or-contract/run.sh              # everything
#   ./scripts/pattern-or-contract/run.sh --shard 2/3  # fixtures + a third
#
# Sharding exists because a mutant costs one whole compiler build plus the
# complete probe. Every shard runs the fixture half and validates the whole
# matrix, so no shard is a partial verdict about what the contract asserts;
# the mutants are divided round-robin, and each shard records what it ran for
# scripts/mutant-coverage/check.py to hold the union to the matrix.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/pattern-or-contract"
dawn=${DAWN_BIN:-"$root/bin/dawn"}

# shellcheck source=scripts/mutant-coverage/shard.sh
source "$root/scripts/mutant-coverage/shard.sh"
shard_parse "$@"
if [ "${#shard_rest[@]}" -gt 0 ]; then
  echo "pattern-or-contract: unknown argument(s): ${shard_rest[*]}" >&2
  exit 2
fi
fixture="$root/scripts/checker-corpus/cases/or_pattern.dawn"
complexity_fixture="$here/complexity.dawn"
budget_fixture="$here/budget.dawn"
qualified_fixture="$root/scripts/checker-corpus/cases/qualified_let.d/entry.dawn"
leading_accept="$root/scripts/grammar-corpus/accept/or_patterns.dawn"
leading_reject="$root/scripts/grammar-corpus/reject/or_pattern_leading_pipe_recovery.dawn"
runtime_fixture="$root/scripts/spike-native/or_pattern.dawn"
runtime_expected="$root/scripts/spike-native/or_pattern.expect"
matrix="$here/matrix.tsv"
work=$(mktemp -d "${TMPDIR:-/tmp}/pattern-or-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "pattern-or-contract: $*" >&2
  exit 1
}

for command in java python3 timeout; do
  command -v "$command" > /dev/null || fail "missing required command: $command"
done

ASSERT_SET='or-pattern alternatives bind the same name set'
ASSERT_TYPE='or-pattern alternatives bind each name at one type'
ASSERT_CASCADE='invalid alternatives do not emit derived binding diagnostics'
ASSERT_QUALIFIED_LET='qualified constructor lets use structural pattern parsing'
ASSERT_LEADING_PIPE='or-patterns accept line-leading continuation pipes'
ASSERT_LSP_REST='list-rest alternatives resolve to the first canonical binding'
ASSERT_LSP_COMPLETION='or-pattern completion deduplicates the shared symbol'
ASSERT_LSP_QUALIFIED='qualified constructor patterns expose constructor and binding queries'
ASSERT_GUARD_ONCE='or-pattern guards run once per arm'
ASSERT_BODY_ONCE='or-pattern bodies run once per arm'
ASSERT_LEFT_BIAS='or-pattern alternatives preserve the first matching bindings'
ASSERT_REDUCTION='complete boolean subpatterns avoid usefulness expansion'
ASSERT_BUDGET='pathological usefulness analysis fails closed at its work budget'
ASSERT_RUNTIME='remaining or-pattern results match the written oracle'
ASSERT_CHECKER_RUN='or-pattern checker probe executes successfully'
ASSERT_COMPLEXITY_RUN='or-pattern complexity smoke executes within its timeout'
ASSERT_BUDGET_RUN='or-pattern budget probe executes within its timeout'
ASSERT_SYNTAX_RUN='or-pattern syntax probes execute within their timeout'
ASSERT_LSP_RUN='or-pattern LSP probe executes successfully'
ASSERT_RUNTIME_RUN='or-pattern runtime probe executes successfully'

owner_registry="$work/owners"
printf '%s\n' \
  "$ASSERT_SET" \
  "$ASSERT_TYPE" \
  "$ASSERT_CASCADE" \
  "$ASSERT_QUALIFIED_LET" \
  "$ASSERT_LEADING_PIPE" \
  "$ASSERT_LSP_REST" \
  "$ASSERT_LSP_COMPLETION" \
  "$ASSERT_LSP_QUALIFIED" \
  "$ASSERT_GUARD_ONCE" \
  "$ASSERT_BODY_ONCE" \
  "$ASSERT_LEFT_BIAS" \
  "$ASSERT_RUNTIME" \
  "$ASSERT_REDUCTION" \
  "$ASSERT_BUDGET" \
  > "$owner_registry"

validate_matrix() {
  local registry=$1 matrix_path=$2 owners=$3 prefix=$4
  local registry_names="$prefix.registry.names"
  local owner_names="$prefix.owner.names"
  local matrix_names="$prefix.matrix.names"
  local matrix_owners="$prefix.matrix.owners"

  if ! awk '
    $0 == "" || index($0, "\t") != 0 || ++seen[$0] > 1 { exit 1 }
    { print }
    END { if (NR == 0) exit 1 }
  ' "$registry" > "$registry_names"; then
    return 1
  fi
  if ! awk '
    $0 == "" || index($0, "\t") != 0 || ++seen[$0] > 1 { exit 1 }
    { print }
    END { if (NR == 0) exit 1 }
  ' "$owners" > "$owner_names"; then
    return 1
  fi
  if ! awk -F '\t' -v names="$matrix_names" -v owners="$matrix_owners" '
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
      print $4 > owners
      records += 1
    }
    END { if (!schema_seen || records == 0) exit 1 }
  ' "$matrix_path"; then
    return 1
  fi
  sort "$registry_names" > "$registry_names.sorted"
  sort "$matrix_names" > "$matrix_names.sorted"
  cmp -s "$registry_names.sorted" "$matrix_names.sorted" || return 1
  sort "$owner_names" > "$owner_names.sorted"
  sort "$matrix_owners" > "$matrix_owners.sorted"
  cmp -s "$owner_names.sorted" "$matrix_owners.sorted" || return 1
}

registry="$work/registry"
python3 "$here/mutate.py" --list > "$registry"
validate_matrix "$registry" "$matrix" "$owner_registry" "$work/actual" ||
  fail "persistent matrix and executable mutator registry disagree"

selftest_number=0
expect_invalid_matrix() {
  local label=$1 registry_path=$2 matrix_path=$3 owners_path=$4
  selftest_number=$((selftest_number + 1))
  if validate_matrix "$registry_path" "$matrix_path" "$owners_path" \
      "$work/selftest-$selftest_number" > /dev/null 2>&1; then
    fail "matrix validation accepted $label"
  fi
  echo "PASS  matrix validation rejects $label"
}

awk -F '\t' 'BEGIN { OFS = "\t" }
  $1 == "mutant" && first == "" { first = $2; print; next }
  $1 == "mutant" && !changed { $2 = first; changed = 1 }
  { print }
' "$matrix" > "$work/matrix-duplicate-mutant"
expect_invalid_matrix "a duplicate mutant" "$registry" "$work/matrix-duplicate-mutant" "$owner_registry"

awk -F '\t' 'BEGIN { OFS = "\t" }
  $1 == "mutant" && first == "" { first = $4; print; next }
  $1 == "mutant" && !changed { $4 = first; changed = 1 }
  { print }
' "$matrix" > "$work/matrix-duplicate-owner"
expect_invalid_matrix "a duplicate owner" "$registry" "$work/matrix-duplicate-owner" "$owner_registry"

awk -F '\t' 'BEGIN { OFS = "\t" }
  $1 == "mutant" && !changed { $4 = "unknown contract owner"; changed = 1 }
  { print }
' "$matrix" > "$work/matrix-unknown-owner"
expect_invalid_matrix "an unknown owner" "$registry" "$work/matrix-unknown-owner" "$owner_registry"

awk -F '\t' '$1 != "schema"' "$matrix" > "$work/matrix-no-schema"
expect_invalid_matrix "a missing schema" "$registry" "$work/matrix-no-schema" "$owner_registry"

awk -F '\t' '
  { lines[NR] = $0; if ($1 == "mutant") last = NR }
  END { for (i = 1; i <= NR; i += 1) if (i != last) print lines[i] }
' "$matrix" > "$work/matrix-missing-member"
expect_invalid_matrix "a missing matrix member" "$registry" "$work/matrix-missing-member" "$owner_registry"

cp "$registry" "$work/registry-extra"
printf '%s\n' unregistered-mutator >> "$work/registry-extra"
expect_invalid_matrix "an extra executable mutator" "$work/registry-extra" "$matrix" "$owner_registry"

sed '$d' "$registry" > "$work/registry-missing"
expect_invalid_matrix "a missing executable mutator" "$work/registry-missing" "$matrix" "$owner_registry"

cp "$owner_registry" "$work/owners-extra"
printf '%s\n' 'unregistered contract owner' >> "$work/owners-extra"
expect_invalid_matrix "an extra registered owner" "$registry" "$matrix" "$work/owners-extra"

sed '$d' "$owner_registry" > "$work/owners-missing"
expect_invalid_matrix "a missing registered owner" "$registry" "$matrix" "$work/owners-missing"

build_compiler() {
  local source=$1 output=$2 label=$3
  if ! "$dawn" build "$source" -o "$output" > "$work/$label-build.out" 2>&1; then
    cat "$work/$label-build.out" >&2
    fail "$label compiler did not compile"
  fi
  java -Xss512m -Xmx2g -jar "$output" --version > /dev/null ||
    fail "$label compiler did not initialize"
}

capture_diagnostics() {
  local jar=$1 source=$2 output=$3
  local status=0
  timeout --kill-after=5s 20s java -Xss512m -Xmx2g -jar "$jar" __check "$source" \
    > "$output.raw" 2>&1 || status=$?
  grep '^D' "$output.raw" > "$output" || true
  return "$status"
}

capture_parse_diagnostics() {
  local jar=$1 source=$2 output=$3
  local status=0
  timeout --kill-after=5s 20s java -Xss512m -Xmx2g -jar "$jar" __parse "$source" \
    > "$output.raw" 2>&1 || status=$?
  grep '^!' "$output.raw" > "$output" || true
  return "$status"
}

contains_count() {
  local file=$1 wanted=$2
  awk -v wanted="$wanted" 'index($0, wanted) { count += 1 } END { print count + 0 }' "$file"
}

line_count() {
  local file=$1 wanted=$2
  awk -v wanted="$wanted" '$0 == wanted { count += 1 } END { print count + 0 }' "$file"
}

diagnostic_count() {
  awk 'END { print NR + 0 }' "$1"
}

checker_assertions() {
  local output=$1
  if ! grep -Fq 'or-pattern alternative does not bind `x`' "$output" ||
      ! grep -Fq 'or-pattern alternative binds extra name `y`' "$output"; then
    printf 'ASSERT: %s\n' "$ASSERT_SET"
  fi
  if ! grep -Fq 'or-pattern binding `x` has type String, but the first alternative binds Int' \
      "$output"; then
    printf 'ASSERT: %s\n' "$ASSERT_TYPE"
  fi
  if [ "$(contains_count "$output" 'undefined constructor in pattern: Goad')" -ne 1 ] ||
      grep -Fq 'or-pattern alternative does not bind `kept`' "$output" ||
      grep -Fq 'undefined variable: kept' "$output"; then
    printf 'ASSERT: %s\n' "$ASSERT_CASCADE"
  fi
}

complexity_assertions() {
  local output=$1
  if [ -s "$output" ]; then
    printf 'ASSERT: %s\n' "$ASSERT_REDUCTION"
  fi
}

budget_assertions() {
  local output=$1
  if [ "$(diagnostic_count "$output")" -ne 1 ] ||
      [ "$(contains_count "$output" 'pattern analysis exceeded its complexity budget')" -ne 1 ]; then
    printf 'ASSERT: %s\n' "$ASSERT_BUDGET"
  fi
}

qualified_let_assertions() {
  local parse_output=$1 check_output=$2
  if [ -s "$parse_output" ] ||
      ! grep -Fq 'PQual q.One' "$parse_output.raw" ||
      [ "$(diagnostic_count "$check_output")" -ne 1 ] ||
      [ "$(contains_count "$check_output" 'unknown module alias `missing` in a pattern')" -ne 1 ] ||
      grep -Fq 'undefined variable: y' "$check_output"; then
    printf 'ASSERT: %s\n' "$ASSERT_QUALIFIED_LET"
  fi
}

leading_pipe_assertions() {
  local accept_output=$1 reject_output=$2
  if [ -s "$accept_output" ] ||
      [ "$(diagnostic_count "$reject_output")" -ne 1 ] ||
      [ "$(contains_count "$reject_output" 'expected a pattern')" -ne 1 ] ||
      ! grep -Fq 'PCtor Right' "$reject_output.raw" ||
      ! grep -Fq 'Fn after' "$reject_output.raw"; then
    printf 'ASSERT: %s\n' "$ASSERT_LEADING_PIPE"
  fi
}

capture_runtime() {
  local jar=$1 output=$2
  (cd "$root" && java -Xss512m -Xmx2g -jar "$jar" run "$runtime_fixture") > "$output" 2>&1
}

runtime_assertions() {
  local output=$1
  if [ "$(line_count "$output" 'guard false')" -ne 1 ] ||
      [ "$(line_count "$output" 'guard true')" -ne 1 ]; then
    printf 'ASSERT: %s\n' "$ASSERT_GUARD_ONCE"
  fi
  if [ "$(line_count "$output" body)" -ne 1 ] ||
      [ "$(line_count "$output" fallback)" -ne 1 ]; then
    printf 'ASSERT: %s\n' "$ASSERT_BODY_ONCE"
  fi
  awk '$0 ~ /^(left-tuple|left-list-first|left-list-second|structural)=/' \
    "$output" > "$output.left"
  awk '$0 ~ /^(left-tuple|left-list-first|left-list-second|structural)=/' \
    "$runtime_expected" > "$output.left.expected"
  if ! cmp -s "$output.left.expected" "$output.left"; then
    printf 'ASSERT: %s\n' "$ASSERT_LEFT_BIAS"
  fi
  awk '
    $0 != "guard false" && $0 != "guard true" && $0 != "body" && $0 != "fallback" &&
      $0 !~ /^(left-tuple|left-list-first|left-list-second|structural)=/
  ' "$output" > "$output.remaining"
  awk '
    $0 != "guard false" && $0 != "guard true" && $0 != "body" && $0 != "fallback" &&
      $0 !~ /^(left-tuple|left-list-first|left-list-second|structural)=/
  ' "$runtime_expected" > "$output.remaining.expected"
  if ! cmp -s "$output.remaining.expected" "$output.remaining"; then
    printf 'ASSERT: %s\n' "$ASSERT_RUNTIME"
  fi
}

probe_compiler() {
  local jar=$1 output_dir=$2
  mkdir -p "$output_dir"
  : > "$output_dir/assertions.out"

  if capture_diagnostics "$jar" "$fixture" "$output_dir/check.out"; then
    checker_assertions "$output_dir/check.out" >> "$output_dir/assertions.out"
  else
    printf 'ASSERT: %s\n' "$ASSERT_CHECKER_RUN" >> "$output_dir/assertions.out"
  fi

  if capture_diagnostics "$jar" "$complexity_fixture" "$output_dir/complexity.out"; then
    complexity_assertions "$output_dir/complexity.out" >> "$output_dir/assertions.out"
  else
    printf 'ASSERT: %s\n' "$ASSERT_COMPLEXITY_RUN" >> "$output_dir/assertions.out"
  fi

  if capture_diagnostics "$jar" "$budget_fixture" "$output_dir/budget.out"; then
    budget_assertions "$output_dir/budget.out" >> "$output_dir/assertions.out"
  else
    printf 'ASSERT: %s\n' "$ASSERT_BUDGET_RUN" >> "$output_dir/assertions.out"
  fi

  local syntax_status=0
  capture_parse_diagnostics "$jar" "$qualified_fixture" \
    "$output_dir/qualified-parse.out" || syntax_status=$?
  capture_diagnostics "$jar" "$qualified_fixture" \
    "$output_dir/qualified-check.out" || syntax_status=$?
  capture_parse_diagnostics "$jar" "$leading_accept" \
    "$output_dir/leading-accept.out" || syntax_status=$?
  capture_parse_diagnostics "$jar" "$leading_reject" \
    "$output_dir/leading-reject.out" || syntax_status=$?
  if [ "$syntax_status" -eq 0 ]; then
    qualified_let_assertions "$output_dir/qualified-parse.out" \
      "$output_dir/qualified-check.out" >> "$output_dir/assertions.out"
    leading_pipe_assertions "$output_dir/leading-accept.out" \
      "$output_dir/leading-reject.out" >> "$output_dir/assertions.out"
  else
    printf 'ASSERT: %s\n' "$ASSERT_SYNTAX_RUN" >> "$output_dir/assertions.out"
  fi

  local lsp_status=0
  python3 "$here/lsp.py" java "$jar" "$root" \
    > "$output_dir/lsp.out" 2> "$output_dir/lsp.err" || lsp_status=$?
  grep '^ASSERT: ' "$output_dir/lsp.out" >> "$output_dir/assertions.out" || true
  if [ "$lsp_status" -ne 0 ] && ! grep -q '^ASSERT: ' "$output_dir/lsp.out"; then
    printf 'ASSERT: %s\n' "$ASSERT_LSP_RUN" >> "$output_dir/assertions.out"
  fi

  if capture_runtime "$jar" "$output_dir/runtime.out"; then
    runtime_assertions "$output_dir/runtime.out" >> "$output_dir/assertions.out"
  else
    printf 'ASSERT: %s\n' "$ASSERT_RUNTIME_RUN" >> "$output_dir/assertions.out"
  fi
}

dump_probe() {
  local output_dir=$1
  for file in assertions.out check.out check.out.raw complexity.out.raw budget.out.raw \
    qualified-parse.out.raw qualified-check.out.raw leading-accept.out.raw \
    leading-reject.out.raw lsp.err runtime.out; do
    if [ -f "$output_dir/$file" ]; then
      cat "$output_dir/$file" >&2
    fi
  done
}

observed="$work/observed.jar"
build_compiler "$root/selfhost" "$observed" observed
probe_compiler "$observed" "$work/observed"
if [ -s "$work/observed/assertions.out" ]; then
  dump_probe "$work/observed"
  fail "observed compiler contract failed"
fi
cat "$work/observed/lsp.out"
echo "PASS  observed compiler satisfies the complete or-pattern assertion set"

expect_source_mutant_red() {
  local name=$1 relative=$2 expected=$3
  local mutant="$work/$name"
  mkdir -p "$mutant"
  cp -R "$root/selfhost" "$mutant/selfhost"
  cp -R "$root/compiler-plan" "$mutant/compiler-plan"
  ln -s "$root/packages" "$mutant/packages"
  python3 "$here/mutate.py" "$name" "$mutant/selfhost" > "$mutant/changed.out"
  printf '%s\n' "$relative" | tr ',' '\n' | sort > "$mutant/changed.expected"
  sort "$mutant/changed.out" > "$mutant/changed.sorted"
  cmp -s "$mutant/changed.expected" "$mutant/changed.sorted" ||
    fail "$name executable targets disagree with its persistent matrix record"
  while IFS= read -r changed; do
    if cmp -s "$root/selfhost/$changed" "$mutant/selfhost/$changed"; then
      fail "$name did not change production source $changed"
    fi
  done < "$mutant/changed.expected"
  build_compiler "$mutant/selfhost" "$mutant/compiler.jar" "$name"
  probe_compiler "$mutant/compiler.jar" "$mutant/probe"
  printf 'ASSERT: %s\n' "$expected" > "$mutant/assert.expected"
  if ! cmp -s "$mutant/assert.expected" "$mutant/probe/assertions.out"; then
    dump_probe "$mutant/probe"
    fail "$name mutant missed its unique owner"
  fi
  echo "PASS  $name changes production source and turns only '$expected' red"
}

shard_begin pattern-or-contract
mutant_position=0
while IFS=$'\t' read -r record name relative expected; do
  if [ "$record" == mutant ]; then
    if ! shard_skips "$mutant_position"; then
      shard_record "$name"
      expect_source_mutant_red "$name" "$relative" "$expected"
    fi
    mutant_position=$((mutant_position + 1))
  fi
done < "$matrix"
shard_report "$mutant_position"

echo "pattern-or-contract: OK"
