#!/usr/bin/env bash
# Build tracked Java fixtures into a private file:// repository, then compile
# an observed LSP server and every behavioral mutant from private selfhost
# copies. Bootstrap is only the compiler runner; fixture resolution cannot use
# a public repository, ignored jar, or pre-existing selfhost build artifact.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/lsp-workspace-contract"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
work="$(mktemp -d "${TMPDIR:-/tmp}/lsp-workspace-contract.XXXXXX")"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "lsp-workspace-contract: $*" >&2
  exit 1
}

for command in java javac jar python3; do
  command -v "$command" > /dev/null || fail "missing required command: $command"
done

# The design heading is a hard count claim. Its case roster is workspace.py's
# CASES dictionary; its mutant roster is the top-level expect_mutant_red calls
# below, because only a call that compiles a mutant and runs its owning case is
# a behavioral negative control. The preflight also perturbs both documented
# counts so a checker that can no longer go red fails before the expensive
# private compiler builds begin.
python3 "$here/roster_check.py" --self-test

"$dawn" --version > "$work/version.out" 2> "$work/version.err" || {
  cat "$work/version.out" >&2
  cat "$work/version.err" >&2
  fail "current compiler did not initialize"
}

repo="$work/maven"
build_fixture() {
  local flavor=$1
  local artifact="api-$flavor"
  local classes="$work/classes-$flavor"
  local target="$repo/fixture/$artifact/1"
  mkdir -p "$classes" "$target"
  javac --release 17 -d "$classes" \
    "$here/fixtures/$flavor/src/fixture/Shared.java"
  jar --create --file "$target/$artifact-1.jar" -C "$classes" .
  cat > "$target/$artifact-1.pom" <<EOF
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>fixture</groupId>
  <artifactId>$artifact</artifactId>
  <version>1</version>
</project>
EOF
}

build_fixture a
build_fixture b

prepare_subject() {
  local name=$1
  SUBJECT="$work/$name"
  SUBJECT_JAR="$SUBJECT/compiler.jar"
  mkdir -p "$SUBJECT"
  cp -R "$root/selfhost" "$SUBJECT/selfhost"
  cp -R "$root/compiler-plan" "$SUBJECT/compiler-plan"
  ln -s "$root/packages" "$SUBJECT/packages"
}

build_subject() {
  local name=$1
  if ! DAWN_SELFHOST_CP="" "$dawn" build "$SUBJECT/selfhost" \
      -o "$SUBJECT_JAR" --std "$root/std" \
      --vendor org/objectweb/asm --vendor coursierapi \
      > "$SUBJECT/build.out" 2> "$SUBJECT/build.err"; then
    cat "$SUBJECT/build.out" >&2
    cat "$SUBJECT/build.err" >&2
    fail "$name private selfhost did not compile"
  fi
}

run_contract() {
  local jar_path=$1
  shift
  python3 "$here/workspace.py" "$@" \
    --repo "$root" \
    --fixture-root "$work/fixtures" \
    --maven-repo "$repo" \
    --cache "$work/cache" \
    -- java -Xss512m -Xmx2g -jar "$jar_path" lsp
}

prepare_subject observed
python3 "$here/mutate.py" observe "$SUBJECT/selfhost"
build_subject observed
if ! run_contract "$SUBJECT_JAR" > "$work/positive.out" 2>&1; then
  cat "$work/positive.out" >&2
  fail "positive workspace contract failed"
fi
cat "$work/positive.out"

expect_mutant_red() {
  local name=$1
  local case_name=$2
  local expected=$3
  prepare_subject "mutant-$name"
  python3 "$here/mutate.py" "$name" "$SUBJECT/selfhost"
  build_subject "$name mutant"
  echo "PASS  $name mutant compiles"
  set +e
  run_contract "$SUBJECT_JAR" --case "$case_name" \
    > "$SUBJECT/run.out" 2>&1
  local status=$?
  set -e
  if [ "$status" -eq 0 ]; then
    fail "$name mutant stayed green"
  fi
  if ! grep -Fq "$expected" "$SUBJECT/run.out"; then
    cat "$SUBJECT/run.out" >&2
    fail "$name mutant missed its owning assertion"
  fi
  echo "PASS  $name mutant compiles, then turns $case_name red"
}

expect_mutant_red single-overlay live-overlay SINGLE_OVERLAY_NOT_SHARED
expect_mutant_red didclose-no-rebuild did-close DIDCLOSE_ROLLBACK_MISSING
expect_mutant_red only-current-diagnostics diagnostics-current WORKSPACE_DIAGNOSTICS_CURRENT_ONLY
expect_mutant_red drop-diagnostics-version diagnostics-current DIAGNOSTIC_VERSION_MISSING
expect_mutant_red unopened-version-zero did-close UNOPENED_URI_VERSION_PUBLISHED
expect_mutant_red skip-empty-diagnostics diagnostics-empty EMPTY_DIAGNOSTIC_CLEAR_MISSING
expect_mutant_red wrong-source-view diagnostics-source-view DIAGNOSTIC_SOURCE_VIEW_MISMATCH
expect_mutant_red duplicate-last-wins duplicate-canonical DUPLICATE_CANONICAL_LAST_WINS
expect_mutant_red ignore-unsaved-module unsaved-module UNSAVED_MODULE_IGNORED
expect_mutant_red current-module-self current-module-completion CURRENT_MODULE_SELF_SUGGESTED
expect_mutant_red extensionless-project-member extensionless-standalone EXTENSIONLESS_JOINED_PROJECT
expect_mutant_red project-only-identity source-root-identity SOURCE_ROOT_WORKSPACE_MERGED
expect_mutant_red global-definition definition-root GLOBAL_DEFINITION_LEAK

merged_cp="$repo/fixture/api-a/1/api-a-1.jar$(python3 -c 'import os; print(os.pathsep, end="")')$repo/fixture/api-b/1/api-b-1.jar"
export DAWN_LSP_MUTANT_MERGED_CP="$merged_cp"
expect_mutant_red merged-java-lease java-roots JAVA_WORKSPACE_LEASE_SHARED
unset DAWN_LSP_MUTANT_MERGED_CP

expect_mutant_red last-close-retains-lease lease-lifecycle LAST_CLOSE_LEASE_RETAINED
expect_mutant_red retry-unavailable-on-change unavailable-retry UNAVAILABLE_DIDCHANGE_RETRIED
expect_mutant_red exit-bypasses-cleanup lease-cleanup EXIT_CLEANUP_BYPASSED
expect_mutant_red close-uncaught close-failure CLOSE_FAILURE_SKIPPED_REMAINING
expect_mutant_red external-owner-clears external-diagnostics EXTERNAL_DIAGNOSTIC_AGGREGATION_MISMATCH
expect_mutant_red standalone-system-loader standalone STANDALONE_SYSTEM_LOADER_LEAK

echo "lsp-workspace-contract: OK"
