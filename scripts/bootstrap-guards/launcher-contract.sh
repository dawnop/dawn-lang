#!/bin/bash
# Offline end-to-end contract for the selfhost cache generation. Fake compiler
# roles make every forbidden Producer/build/exec observable, while all cache
# and race artifacts stay under private temporary roots.
set -uo pipefail
export LC_ALL=C

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
fixtures=$repo/scripts/bootstrap-guards/fixtures
work=$(mktemp -d "${TMPDIR:-/tmp}/dawn-launcher-contract.XXXXXX")
trap '[ -n "${KEEP_BOOTSTRAP_GUARD_WORK:-}" ] || rm -rf "$work"' EXIT
system_path=$PATH
real_mv=$(command -v mv)
real_rm=$(command -v rm)
real_sha256sum=$(command -v sha256sum || true)
fail=0

pass() { printf 'PASS  %s\n' "$1"; }
bad() {
  printf 'FAIL: %s\n' "$1" >&2
  fail=1
}

make_root() {
  local name=$1
  local launcher=${2:-$repo/bin/dawn}
  local target=$work/$name
  mkdir -p "$target/bin" "$target/scripts" "$target/build" \
    "$target/selfhost/src" "$target/std" \
    "$target/packages/direct/src" "$target/packages/transitive/src" \
    "$target/.fake/java-home/bin" "$target/.fake/seed-std"
  cp "$launcher" "$target/bin/dawn"
  cp "$fixtures/seedjar.sh" "$target/scripts/seedjar.sh"
  cp "$fixtures/fake-java.sh" "$target/.fake/java-home/bin/java"
  cp "$fixtures/source-inputs.manifest" "$target/.fake/manifest.pre"
  grep -v 'packages/transitive' "$fixtures/source-inputs.manifest" \
    > "$target/.fake/manifest.direct"
  printf 'seed\n' > "$target/.fake/seed.jar"
  printf 'seed std\n' > "$target/.fake/seed-std/modules.txt"
  printf '[project]\nname = "selfhost"\n' > "$target/selfhost/dawn.toml"
  printf 'lock\n' > "$target/selfhost/dawn.lock"
  printf 'selfhost source\n' > "$target/selfhost/src/main.dawn"
  printf '[project]\nname = "direct"\n' > "$target/packages/direct/dawn.toml"
  printf 'direct source\n' > "$target/packages/direct/src/main.dawn"
  printf '[project]\nname = "transitive"\n' > "$target/packages/transitive/dawn.toml"
  printf 'transitive source\n' > "$target/packages/transitive/src/main.dawn"
  printf 'std source\n' > "$target/std/modules.txt"
  printf 'v-test\n' > "$target/scripts/seed-release.txt"
  printf 'seed checksum\n' > "$target/scripts/seed-checksums.txt"
  printf 'std checksum\n' > "$target/scripts/seed-std-checksums.txt"
  chmod +x "$target/bin/dawn" "$target/.fake/java-home/bin/java"
  printf '%s\n' "$target"
}

invoke() {
  local target=$1
  local log=$2
  shift 2
  (
    unset DAWN_SEED DAWN_PRINT_STAMP DAWN_SEED_CACHE DAWN_SEED_ALLOW_UNVERIFIED
    export JAVA_HOME="$target/.fake/java-home"
    export DAWN_JVM_OPTS=-Xmx32m
    export FAKE_JAVA_LOG=$log
    export FAKE_MANIFEST_PRE="${TEST_MANIFEST_PRE:-$target/.fake/manifest.pre}"
    export FAKE_MANIFEST_POST="${TEST_MANIFEST_POST:-$FAKE_MANIFEST_PRE}"
    if [[ ${TEST_DAWN_SEED+x} == x ]]; then
      export DAWN_SEED=$TEST_DAWN_SEED
    fi
    if [[ -n ${TEST_PATH:-} ]]; then
      export PATH=$TEST_PATH
    fi
    if [[ -n ${TEST_HASH_MODE:-} ]]; then
      export FAKE_HASH_MODE=$TEST_HASH_MODE
      export REAL_SHA256SUM=$real_sha256sum
    fi
    if [[ -n ${TEST_PRINT_STAMP:-} ]]; then
      export DAWN_PRINT_STAMP=1
    fi
    if [[ -n ${TEST_BUILD_BARRIER:-} ]]; then
      export FAKE_BUILD_BARRIER=$TEST_BUILD_BARRIER
    fi
    if [[ -n ${TEST_MUTATE_SOURCE:-} ]]; then
      export FAKE_MUTATE_SOURCE_ON_FINAL=$TEST_MUTATE_SOURCE
      export FAKE_MUTATE_SOURCE_TEXT=${TEST_MUTATE_SOURCE_TEXT:-changed}
    fi
    if [[ -n ${TEST_MV_LOG:-} ]]; then
      export FAKE_MV_LOG=$TEST_MV_LOG
      export REAL_MV=$real_mv
    fi
    if [[ -n ${TEST_MV_CRASH_AFTER:-} ]]; then
      export FAKE_MV_CRASH_AFTER=$TEST_MV_CRASH_AFTER
    fi
    if [[ -n ${TEST_RM_SWAP_JAR:-} ]]; then
      export FAKE_RM_SWAP_JAR=$TEST_RM_SWAP_JAR
      export FAKE_RM_SWAP_MARKER=$TEST_RM_SWAP_MARKER
      export REAL_RM=$real_rm
    fi
    if [[ -n ${TEST_PROMOTION_SWAP:-} ]]; then
      export REAL_MV=$real_mv
      export REAL_RM=$real_rm
      export FAKE_PROMOTION_STAMP="$target/build/dawn-selfhost.stamp"
      export FAKE_PROMOTION_JAR="$target/build/dawn-selfhost.jar"
      export FAKE_PROMOTION_SWAP_MARKER="$target/.fake/promotion-swapped"
      export FAKE_RESTORE_MARKER="$target/.fake/promotion-restored"
      export FAKE_CLEANUP_LOG=$TEST_CLEANUP_LOG
    fi
    "$target/bin/dawn" "$@"
  )
}

event_count() {
  local log=$1 role=$2 command_name=$3
  awk -F '\t' -v role="$role" -v command_name="$command_name" \
    '$1 == role && $2 == command_name { count++ } END { print count + 0 }' \
    "$log" 2>/dev/null
}

seed_builds() { event_count "$1" seed build; }

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

inputs_digest() {
  local manifest=$1
  local stream=$work/inputs-digest.$$.stream
  local tag=dawn-inputs-digest-v2
  local size
  size=$(wc -c < "$manifest" | tr -d '[:space:]')
  {
    printf '%s:%s' "${#tag}" "$tag"
    printf '8:manifest'
    printf '%s:' "$size"
    cat "$manifest"
  } > "$stream"
  hash_file "$stream"
}

stamp_field() { sed -n "s/^$2=//p" "$1"; }

valid_stamp() {
  local target=$1
  local stamp=$target/build/dawn-selfhost.stamp
  local inputs=$target/build/dawn-selfhost.inputs
  local jar=$target/build/dawn-selfhost.jar
  [[ -f $stamp && ! -L $stamp && -f $inputs && ! -L $inputs && -f $jar && ! -L $jar ]] || return 1
  [[ $(sed -n '1p' "$stamp") == dawn-selfhost-stamp-v2 ]] || return 1
  [[ $(wc -l < "$stamp" | tr -d '[:space:]') == 5 ]] || return 1
  grep -Eq '^source=[0-9a-f]{64}$' "$stamp" || return 1
  grep -Eq '^bootstrap=[0-9a-f]{64}$' "$stamp" || return 1
  grep -Eq '^inputs=[0-9a-f]{64}$' "$stamp" || return 1
  grep -Eq '^jar=[0-9a-f]{64}$' "$stamp" || return 1
  [[ $(stamp_field "$stamp" inputs) == "$(inputs_digest "$inputs")" ]] || return 1
  [[ $(stamp_field "$stamp" jar) == "$(hash_file "$jar")" ]]
}

expect_rebuild() {
  local label=$1 target=$2 log=$3
  local before after
  before=$(seed_builds "$log")
  if ! invoke "$target" "$log" --version > "$work/$label.out" 2> "$work/$label.err"; then
    bad "$label failed instead of rebuilding"
    return
  fi
  after=$(seed_builds "$log")
  if [[ $after -ne $((before + 1)) ]] || ! valid_stamp "$target"; then
    bad "$label did not cause exactly one valid rebuild"
  else
    pass "$label causes a cache miss"
  fi
}

base=$(make_root base)
base_log=$work/base.java.log
: > "$base_log"
if ! invoke "$base" "$base_log" --version > "$work/base.out" 2> "$work/base.err"; then
  bad "cold fake-root bootstrap failed"
elif ! valid_stamp "$base"; then
  bad "cold bootstrap did not produce a strict v2 generation"
elif ! cmp -s "$base/.fake/manifest.pre" "$base/build/dawn-selfhost.inputs"; then
  bad "candidate manifest was not persisted byte-for-byte"
elif [[ $(event_count "$base_log" seed build) -ne 1 ]] ||
    [[ $(event_count "$base_log" seed __source-inputs) -ne 0 ]] ||
    [[ $(event_count "$base_log" stage1 __source-inputs) -ne 1 ]] ||
    [[ $(event_count "$base_log" stage1 build) -ne 1 ]] ||
    [[ $(event_count "$base_log" candidate __source-inputs) -ne 1 ]]; then
  bad "cold bootstrap violated seed-build, pre-plan, build, post-plan ordering"
else
  pass "cold bootstrap persists one complete two-plan generation"
fi

before=$(seed_builds "$base_log")
if ! invoke "$base" "$base_log" --version > "$work/hot.out" 2> "$work/hot.err"; then
  bad "verified hot cache invocation failed"
elif [[ $(seed_builds "$base_log") -ne $before ]]; then
  bad "verified hot cache rebuilt"
else
  pass "verified hot cache executes without Producer or build"
fi

before=$(wc -l < "$base_log")
if ! TEST_PRINT_STAMP=1 invoke "$base" "$base_log" > "$work/print.stamp" 2> "$work/print.err"; then
  bad "DAWN_PRINT_STAMP failed"
elif ! cmp -s "$work/print.stamp" "$base/build/dawn-selfhost.stamp"; then
  bad "DAWN_PRINT_STAMP did not print the complete verified marker"
elif [[ $(wc -l < "$base_log") -ne $before ]]; then
  bad "DAWN_PRINT_STAMP executed the cached compiler"
else
  pass "DAWN_PRINT_STAMP exposes only the verified five-line marker"
fi

coverage=$(make_root coverage)
coverage_log=$work/coverage.java.log
: > "$coverage_log"
invoke "$coverage" "$coverage_log" --version > /dev/null 2> "$work/coverage.err" || bad "coverage setup failed"
printf 'source edit\n' >> "$coverage/packages/transitive/src/main.dawn"
expect_rebuild "transitive-source" "$coverage" "$coverage_log"
printf 'recipe edit\n' >> "$coverage/bin/dawn"
expect_rebuild "launcher-recipe" "$coverage" "$coverage_log"
printf 'seed bytes changed\n' >> "$coverage/.fake/seed.jar"
expect_rebuild "default-seed-bytes" "$coverage" "$coverage_log"
rm -f "$coverage/selfhost/dawn.lock"
expect_rebuild "optional-missing" "$coverage" "$coverage_log"
printf 'std edit\n' >> "$coverage/std/modules.txt"
expect_rebuild "released-std-tree" "$coverage" "$coverage_log"
printf 'pointer edit\n' >> "$coverage/scripts/seed-release.txt"
expect_rebuild "seed-release-pointer" "$coverage" "$coverage_log"
printf 'trust edit\n' >> "$coverage/scripts/seed-checksums.txt"
expect_rebuild "seed-trust-record" "$coverage" "$coverage_log"
printf 'std trust edit\n' >> "$coverage/scripts/seed-std-checksums.txt"
expect_rebuild "seed-std-trust-record" "$coverage" "$coverage_log"
printf '# resolver edit\n' >> "$coverage/scripts/seedjar.sh"
expect_rebuild "seed-resolver" "$coverage" "$coverage_log"
printf '# manifest edit\n' >> "$coverage/selfhost/dawn.toml"
expect_rebuild "selfhost-manifest" "$coverage" "$coverage_log"

# The control. Without it, "the stamp moved" is consistent with hashing the
# whole tree, which would answer yes to anything and mean nothing.
printf 'not an input\n' > "$coverage/README.md"
mkdir -p "$coverage/docs"
printf 'not an input\n' > "$coverage/docs/notes.md"
before=$(seed_builds "$coverage_log")
if ! invoke "$coverage" "$coverage_log" --version > "$work/unrelated.out" 2> "$work/unrelated.err"; then
  bad "an unrelated file made the launcher fail"
elif [[ $(seed_builds "$coverage_log") -ne $before ]]; then
  bad "the generation moved for a file that is not a build input"
else
  pass "a file outside the input set stays a verified hot cache"
fi

override=$coverage/.fake/override.jar
cp "$coverage/.fake/seed.jar" "$override"
before=$(seed_builds "$coverage_log")
if ! TEST_DAWN_SEED=$override invoke "$coverage" "$coverage_log" --version > /dev/null 2> "$work/override.err" ||
    [[ $(seed_builds "$coverage_log") -ne $((before + 1)) ]]; then
  bad "DAWN_SEED mode did not enter bootstrap identity"
else
  pass "DAWN_SEED mode changes bootstrap identity even for equal bytes"
fi
printf 'override bytes changed\n' >> "$override"
before=$(seed_builds "$coverage_log")
if ! TEST_DAWN_SEED=$override invoke "$coverage" "$coverage_log" --version > /dev/null 2> "$work/override-bytes.err" ||
    [[ $(seed_builds "$coverage_log") -ne $((before + 1)) ]]; then
  bad "DAWN_SEED bytes did not enter bootstrap identity"
else
  pass "DAWN_SEED bytes change bootstrap identity"
fi
before=$(seed_builds "$coverage_log")
if ! invoke "$coverage" "$coverage_log" --version > /dev/null 2> "$work/default-again.err" ||
    [[ $(seed_builds "$coverage_log") -ne $((before + 1)) ]]; then
  bad "removing DAWN_SEED reused an override generation"
else
  pass "removing DAWN_SEED restores default bootstrap identity"
fi

damaged=$(make_root damaged)
damaged_log=$work/damaged.java.log
: > "$damaged_log"
invoke "$damaged" "$damaged_log" --version > /dev/null 2> "$work/damaged-setup.err" || bad "damaged-cache setup failed"
rm -f "$damaged/build/dawn-selfhost.inputs"
expect_rebuild "missing-inputs" "$damaged" "$damaged_log"
printf 'not a manifest\n' > "$damaged/build/dawn-selfhost.inputs"
expect_rebuild "malformed-inputs" "$damaged" "$damaged_log"
printf 'legacy\n' > "$damaged/build/dawn-selfhost.stamp"
expect_rebuild "legacy-stamp" "$damaged" "$damaged_log"
printf 'rogue\n' > "$damaged/build/dawn-selfhost.jar"
expect_rebuild "jar-mismatch" "$damaged" "$damaged_log"
{
  sed -n '1p' "$damaged/build/dawn-selfhost.inputs"
  sed -n '3p' "$damaged/build/dawn-selfhost.inputs"
  sed -n '2p' "$damaged/build/dawn-selfhost.inputs"
  sed -n '4,$p' "$damaged/build/dawn-selfhost.inputs"
} > "$work/reordered.inputs"
cp "$work/reordered.inputs" "$damaged/build/dawn-selfhost.inputs"
expect_rebuild "raw-inputs-digest" "$damaged" "$damaged_log"

collision_state_a() {
  local target=$1 tree=$1/packages/transitive/src physical
  physical=$(cd "$target" && pwd -P)
  rm -f "$tree/main.dawn" "$tree/p2"
  printf '%s\nX' "$physical/packages/transitive/src/p2" > "$tree/p1"
}

collision_state_b() {
  local target=$1 tree=$1/packages/transitive/src
  : > "$tree/p1"
  printf X > "$tree/p2"
}

collision=$(make_root collision)
collision_log=$work/collision.java.log
: > "$collision_log"
collision_state_a "$collision"
if ! invoke "$collision" "$collision_log" --version > /dev/null 2> "$work/collision-setup.err"; then
  bad "framing collision setup failed"
else
  before=$(seed_builds "$collision_log")
  collision_state_b "$collision"
  if ! invoke "$collision" "$collision_log" --version > /dev/null 2> "$work/collision.err" ||
      [[ $(seed_builds "$collision_log") -ne $((before + 1)) ]]; then
    bad "length framing did not distinguish the real legacy collision"
  else
    pass "typed length framing distinguishes shifted file boundaries"
  fi
fi

replan=$(make_root replan)
replan_log=$work/replan.java.log
: > "$replan_log"
if TEST_MANIFEST_POST="$replan/.fake/manifest.direct" \
    invoke "$replan" "$replan_log" --version > "$work/replan.out" 2> "$work/replan.err"; then
  bad "divergent pre/post manifests were promoted"
elif ! grep -q 'bootstrap inputs changed during build' "$work/replan.err" ||
    [[ -e $replan/build/dawn-selfhost.stamp ]]; then
  bad "divergent pre/post manifests missed the stable fail-closed boundary"
else
  pass "candidate must reproduce the stage1 input manifest"
fi

source_drift=$(make_root source-drift)
source_drift_log=$work/source-drift.java.log
: > "$source_drift_log"
if TEST_MUTATE_SOURCE="$source_drift/packages/transitive/src/main.dawn" \
    invoke "$source_drift" "$source_drift_log" --version > "$work/source-drift.out" 2> "$work/source-drift.err"; then
  bad "same-manifest source drift was promoted"
elif ! grep -q 'bootstrap inputs changed during build' "$work/source-drift.err" ||
    [[ -e $source_drift/build/dawn-selfhost.stamp ]]; then
  bad "same-manifest source drift missed framed pre/post comparison"
else
  pass "pre/post comparison covers both manifest and source bytes"
fi

# The consumer keeps the Producer honest: a manifest it cannot parse, a record
# that escapes the checkout, or a source entry the filesystem contradicts must
# end the build with no generation committed -- never degrade into a partial
# input set that hashes green.
badman=$work/bad-manifests
mkdir -p "$badman"
printf 'escape target\n' > "$work/escape.txt"
printf 'not-a-source-input-manifest\nR\tF\tselfhost/dawn.toml\n' > "$badman/bad-header"
printf 'dawn-source-inputs-v1\nmalformed\n' > "$badman/malformed-record"
printf 'dawn-source-inputs-v1\nR\tX\tselfhost/dawn.toml\n' > "$badman/unknown-kind"
printf 'dawn-source-inputs-v1\nX\tF\tselfhost/dawn.toml\n' > "$badman/unknown-scope"
printf 'dawn-source-inputs-v1\nR\tF\t../escape.txt\n' > "$badman/escaping-record"
printf 'dawn-source-inputs-v1\nA\tF\trelative.txt\n' > "$badman/relative-absolute"
printf 'dawn-source-inputs-v1\nR\tF\tselfhost/dawn.toml' > "$badman/unterminated"
printf 'dawn-source-inputs-v1\nR\tF\tmissing.txt\n' > "$badman/missing-required"

expect_fail_closed() {
  local label=$1 manifest=$2 message=$3 setup=${4:-}
  local target log
  target=$(make_root "fail-$label")
  [[ -z $setup ]] || "$setup" "$target"
  log=$work/fail-$label.java.log
  : > "$log"
  if TEST_MANIFEST_PRE=$manifest invoke "$target" "$log" --version \
      > "$work/fail-$label.out" 2> "$work/fail-$label.err"; then
    bad "$label was accepted"
  elif [[ -e $target/build/dawn-selfhost.stamp ]]; then
    bad "$label still committed a generation marker"
  elif ! grep -Fq "$message" "$work/fail-$label.err"; then
    bad "$label was rejected for the wrong reason"
  else
    pass "$label fails closed without a generation"
  fi
}

expect_fail_closed "bad-header" "$badman/bad-header" \
  "invalid source input manifest header"
expect_fail_closed "malformed-record" "$badman/malformed-record" \
  "malformed source input manifest record"
expect_fail_closed "unknown-kind" "$badman/unknown-kind" \
  "unknown source input manifest kind"
expect_fail_closed "unknown-scope" "$badman/unknown-scope" \
  "unknown source input manifest scope"
expect_fail_closed "escaping-record" "$badman/escaping-record" \
  "invalid repo-relative source input path"
expect_fail_closed "relative-absolute" "$badman/relative-absolute" \
  "invalid absolute source input path"
expect_fail_closed "unterminated" "$badman/unterminated" \
  "source input manifest record is not newline-terminated"
expect_fail_closed "missing-required" "$badman/missing-required" \
  "required source input is not a regular non-symbolic-link file"

setup_tree_symlink() { ln -s main.dawn "$1/packages/transitive/src/link.dawn"; }
setup_tree_fifo() { mkfifo "$1/packages/transitive/src/pipe"; }
setup_required_symlink() {
  mv "$1/selfhost/dawn.toml" "$1/selfhost/dawn.toml.real"
  ln -s dawn.toml.real "$1/selfhost/dawn.toml"
}
expect_fail_closed "tree-symlink" "" \
  "tree contains a symbolic link" setup_tree_symlink
expect_fail_closed "tree-fifo" "" \
  "tree contains a non-regular entry" setup_tree_fifo
expect_fail_closed "required-symlink" "" \
  "source input has a symbolic-link path component" setup_required_symlink

hash_path=$work/hash-path
mkdir -p "$hash_path"
cp "$fixtures/bad-sha256sum.sh" "$hash_path/sha256sum"
chmod +x "$hash_path/sha256sum"
for mode in zero status shape; do
  hash_root=$(make_root "hash-$mode")
  hash_log=$work/hash-$mode.java.log
  : > "$hash_log"
  if TEST_PATH="$hash_path:$system_path" TEST_HASH_MODE=$mode \
      invoke "$hash_root" "$hash_log" --version > "$work/hash-$mode.out" 2> "$work/hash-$mode.err"; then
    bad "$mode SHA-256 implementation was accepted"
  elif [[ $(wc -l < "$hash_log") -ne 0 ]]; then
    bad "$mode SHA-256 failure reached Producer/build/exec"
  else
    pass "$mode SHA-256 failure is rejected before compiler execution"
  fi
done

nohash_path=$work/nohash-path
mkdir -p "$nohash_path"
for utility in dirname find grep head; do
  ln -s "$(command -v "$utility")" "$nohash_path/$utility"
done
nohash=$(make_root nohash)
nohash_log=$work/nohash.java.log
: > "$nohash_log"
if TEST_PATH=$nohash_path invoke "$nohash" "$nohash_log" --version > "$work/nohash.out" 2> "$work/nohash.err"; then
  bad "launcher ran without a SHA-256 implementation"
elif [[ $(wc -l < "$nohash_log") -ne 0 ]]; then
  bad "missing SHA-256 implementation reached Producer/build/exec"
else
  pass "missing SHA-256 implementation fails closed before compiler execution"
fi

make_mv_path() {
  local target=$1 directory=$1/.fake/mv-path
  mkdir -p "$directory"
  cp "$fixtures/mv-probe.sh" "$directory/mv"
  chmod +x "$directory/mv"
  printf '%s\n' "$directory"
}

promotion=$(make_root promotion)
promotion_log=$work/promotion.java.log
promotion_mv_log=$work/promotion.mv.log
: > "$promotion_log"
: > "$promotion_mv_log"
promotion_path=$(make_mv_path "$promotion")
if ! TEST_PATH="$promotion_path:$system_path" TEST_MV_LOG=$promotion_mv_log \
    invoke "$promotion" "$promotion_log" --version > /dev/null 2> "$work/promotion.err"; then
  bad "promotion-order fixture failed"
else
  grep -E '/build/dawn-selfhost\.(jar|inputs|stamp)$' "$promotion_mv_log" > "$work/promotion.actual"
  printf '%s\n%s\n%s\n' \
    "$promotion/build/dawn-selfhost.jar" \
    "$promotion/build/dawn-selfhost.inputs" \
    "$promotion/build/dawn-selfhost.stamp" > "$work/promotion.expected"
  if ! cmp -s "$work/promotion.expected" "$work/promotion.actual"; then
    bad "promotion order is not JAR, inputs, marker"
  else
    pass "stamp is promoted last as the generation commit marker"
  fi
fi

crash=$(make_root crash-after-jar)
crash_log=$work/crash.java.log
crash_mv_log=$work/crash.mv.log
: > "$crash_log"
: > "$crash_mv_log"
crash_path=$(make_mv_path "$crash")
if TEST_PATH="$crash_path:$system_path" TEST_MV_LOG=$crash_mv_log \
    TEST_MV_CRASH_AFTER="$crash/build/dawn-selfhost.jar" \
    invoke "$crash" "$crash_log" --version > "$work/crash.out" 2> "$work/crash.err"; then
  bad "crash-after-jar fixture did not interrupt promotion"
elif [[ -e $crash/build/dawn-selfhost.stamp ]]; then
  bad "jar-only promotion left a committed marker"
elif ! invoke "$crash" "$crash_log" --version > /dev/null 2> "$work/crash-recover.err" ||
    ! valid_stamp "$crash"; then
  bad "partial promotion did not recover on the next invocation"
else
  pass "jar-before-marker crash is detected and recovered"
fi

run_concurrent() {
  local target=$1 log=$2 barrier=$1/.fake/barrier
  rm -rf "$barrier"
  : > "$log"
  TEST_BUILD_BARRIER=$barrier invoke "$target" "$log" --version > "$work/concurrent-1.out" 2> "$work/concurrent-1.err" &
  local first=$!
  TEST_BUILD_BARRIER=$barrier invoke "$target" "$log" --version > "$work/concurrent-2.out" 2> "$work/concurrent-2.err" &
  local second=$!
  local first_status=0 second_status=0
  wait "$first" || first_status=$?
  wait "$second" || second_status=$?
  [[ $first_status -eq 0 && $second_status -eq 0 ]]
}

concurrent=$(make_root concurrent)
concurrent_log=$work/concurrent.java.log
if ! run_concurrent "$concurrent" "$concurrent_log"; then
  bad "two synchronized builders did not converge"
else
  awk -F '\t' '$1 == "seed" && $2 == "build" { print $3 }' "$concurrent_log" | \
    sed 's#/[^/]*$##' | LC_ALL=C sort -u > "$work/concurrent.transactions"
  if [[ $(wc -l < "$work/concurrent.transactions" | tr -d '[:space:]') -ne 2 ]] ||
      ! valid_stamp "$concurrent"; then
    bad "concurrent builders shared staging or left an invalid generation"
  else
    pass "concurrent builders use unique staging and converge"
  fi
fi

make_rm_swap_path() {
  local target=$1 directory=$1/.fake/rm-swap-path
  mkdir -p "$directory"
  cp "$fixtures/rm-swap.sh" "$directory/rm"
  chmod +x "$directory/rm"
  printf '%s\n' "$directory"
}

execution=$(make_root execution-pair)
execution_log=$work/execution.java.log
execution_marker=$execution/.fake/rm-swapped
: > "$execution_log"
execution_path=$(make_rm_swap_path "$execution")
if ! TEST_PATH="$execution_path:$system_path" \
    TEST_RM_SWAP_JAR="$execution/build/dawn-selfhost.jar" \
    TEST_RM_SWAP_MARKER=$execution_marker \
    invoke "$execution" "$execution_log" --version > /dev/null 2> "$work/execution.err"; then
  bad "pre-exec pairing did not recover from a cleanup-window jar swap"
elif [[ $(event_count "$execution_log" rogue --version) -ne 0 ]] ||
    [[ $(seed_builds "$execution_log") -ne 2 ]] || ! valid_stamp "$execution"; then
  bad "pre-exec pairing executed rogue bytes or failed to rebuild once"
else
  pass "cleanup-window jar replacement is caught before execution"
fi

make_promotion_swap_path() {
  local target=$1 directory=$1/.fake/promotion-swap-path
  mkdir -p "$directory"
  cp "$fixtures/mv-swap-after-stamp.sh" "$directory/mv"
  cp "$fixtures/rm-restore.sh" "$directory/rm"
  chmod +x "$directory/mv" "$directory/rm"
  printf '%s\n' "$directory"
}

post_pair=$(make_root post-promotion-pair)
post_pair_log=$work/post-promotion.java.log
post_cleanup_log=$work/post-promotion.cleanup.log
: > "$post_pair_log"
: > "$post_cleanup_log"
post_pair_path=$(make_promotion_swap_path "$post_pair")
if ! TEST_PATH="$post_pair_path:$system_path" TEST_PROMOTION_SWAP=1 \
    TEST_CLEANUP_LOG=$post_cleanup_log invoke "$post_pair" "$post_pair_log" --version \
    > /dev/null 2> "$work/post-promotion.err"; then
  bad "post-promotion pairing fixture failed"
elif [[ $(wc -l < "$post_cleanup_log" | tr -d '[:space:]') -lt 2 ]] ||
    [[ $(event_count "$post_pair_log" rogue --version) -ne 0 ]]; then
  bad "post-promotion mismatch was not observed before cleanup restored the jar"
else
  pass "promotion is revalidated before cleanup and execution"
fi

prepare_mutant() {
  local name=$1
  mkdir -p "$work/mutants"
  MUTANT=$work/mutants/$name
  cp "$repo/bin/dawn" "$MUTANT"
  if ! PYTHONDONTWRITEBYTECODE=1 python3 "$repo/scripts/bootstrap-guards/mutate-launcher.py" \
      "$MUTANT" "$name" > "$work/mutant-$name.out" 2> "$work/mutant-$name.err"; then
    bad "$name mutant could not be constructed"
    return 1
  fi
  chmod +x "$MUTANT"
  if ! sh -n "$MUTANT"; then
    bad "$name mutant failed shell syntax before its behavior assertion"
    return 1
  fi
}

for mutation in skip-known-vector ignore-hasher-status ignore-hasher-shape; do
  if prepare_mutant "$mutation"; then
    mutant_root=$(make_root "mutant-$mutation" "$MUTANT")
    mutant_log=$work/mutant-$mutation.java.log
    : > "$mutant_log"
    case $mutation in
      skip-known-vector) mode=zero ;;
      ignore-hasher-status) mode=status ;;
      ignore-hasher-shape) mode=shape ;;
    esac
    TEST_PATH="$hash_path:$system_path" TEST_HASH_MODE=$mode \
      invoke "$mutant_root" "$mutant_log" --version > "$work/mutant-$mutation.run.out" \
      2> "$work/mutant-$mutation.run.err" || true
    if [[ $(wc -l < "$mutant_log") -eq 0 ]]; then
      bad "$mutation mutant remained fail-closed"
    else
      pass "$mutation mutant reaches compiler execution and turns its assertion red"
    fi
  fi
done

if prepare_mutant no-hasher-mtime; then
  mutant_root=$(make_root mutant-no-hasher "$MUTANT")
  mutant_log=$work/mutant-no-hasher.java.log
  : > "$mutant_log"
  if ! invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-no-hasher-setup.err"; then
    bad "no-hasher mutant setup failed"
  else
    before=$(wc -l < "$mutant_log")
    if ! TEST_PATH=$nohash_path invoke "$mutant_root" "$mutant_log" --version \
        > /dev/null 2> "$work/mutant-no-hasher.err" ||
        [[ $(wc -l < "$mutant_log") -ne $((before + 1)) ]]; then
      bad "no-hasher mutant did not execute its stale-jar fallback"
    else
      pass "no-hasher/mtime mutant turns the hard-failure assertion red"
    fi
  fi
fi

if prepare_mutant legacy-concat; then
  mutant_root=$(make_root mutant-legacy "$MUTANT")
  mutant_log=$work/mutant-legacy.java.log
  : > "$mutant_log"
  collision_state_a "$mutant_root"
  if ! invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-legacy-setup.err"; then
    bad "legacy concat mutant setup failed"
  else
    before=$(seed_builds "$mutant_log")
    collision_state_b "$mutant_root"
    if ! invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-legacy.err" ||
        [[ $(seed_builds "$mutant_log") -ne $before ]]; then
      bad "legacy concat mutant unexpectedly detected the collision"
    else
      pass "legacy concat mutant hot-hits the real boundary collision"
    fi
  fi
fi

if prepare_mutant ignore-missing-inputs; then
  mutant_root=$(make_root mutant-missing-inputs "$MUTANT")
  mutant_log=$work/mutant-missing-inputs.java.log
  : > "$mutant_log"
  invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-missing-setup.err" || bad "missing-input mutant setup failed"
  before=$(seed_builds "$mutant_log")
  rm -f "$mutant_root/build/dawn-selfhost.inputs"
  if ! invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-missing.err" ||
      [[ $(seed_builds "$mutant_log") -ne $before ]]; then
    bad "missing-input mutant did not hot-hit without persisted inputs"
  else
    pass "missing-input mutant turns cache completeness red"
  fi
fi

if prepare_mutant omit-bootstrap-digest; then
  mutant_root=$(make_root mutant-bootstrap "$MUTANT")
  mutant_log=$work/mutant-bootstrap.java.log
  : > "$mutant_log"
  invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-bootstrap-setup.err" || bad "bootstrap mutant setup failed"
  cp "$mutant_root/.fake/seed.jar" "$mutant_root/.fake/override.jar"
  before=$(seed_builds "$mutant_log")
  if ! TEST_DAWN_SEED="$mutant_root/.fake/override.jar" \
      invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-bootstrap.err" ||
      [[ $(seed_builds "$mutant_log") -ne $before ]]; then
    bad "bootstrap digest mutant did not reuse the wrong seed mode"
  else
    pass "omitted bootstrap digest turns seed-mode identity red"
  fi
fi

if prepare_mutant omit-inputs-digest; then
  mutant_root=$(make_root mutant-inputs-digest "$MUTANT")
  mutant_log=$work/mutant-inputs-digest.java.log
  : > "$mutant_log"
  invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-inputs-setup.err" || bad "inputs digest mutant setup failed"
  {
    sed -n '1p' "$mutant_root/build/dawn-selfhost.inputs"
    sed -n '3p' "$mutant_root/build/dawn-selfhost.inputs"
    sed -n '2p' "$mutant_root/build/dawn-selfhost.inputs"
    sed -n '4,$p' "$mutant_root/build/dawn-selfhost.inputs"
  } > "$work/mutant-reordered.inputs"
  cp "$work/mutant-reordered.inputs" "$mutant_root/build/dawn-selfhost.inputs"
  before=$(seed_builds "$mutant_log")
  if ! invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-inputs.err" ||
      [[ $(seed_builds "$mutant_log") -ne $before ]]; then
    bad "inputs digest mutant detected a raw-manifest change"
  else
    pass "omitted inputs digest turns raw-manifest identity red"
  fi
fi

if prepare_mutant omit-jar-digest; then
  mutant_root=$(make_root mutant-jar-digest "$MUTANT")
  mutant_log=$work/mutant-jar-digest.java.log
  : > "$mutant_log"
  invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-jar-setup.err" || bad "jar digest mutant setup failed"
  printf 'rogue\n' > "$mutant_root/build/dawn-selfhost.jar"
  invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-jar.err" || true
  if [[ $(event_count "$mutant_log" rogue --version) -ne 1 ]]; then
    bad "jar digest mutant refused mismatched jar bytes"
  else
    pass "omitted jar digest executes mismatched bytes and turns red"
  fi
fi

if prepare_mutant seed-hidden-command; then
  mutant_root=$(make_root mutant-seed-hidden "$MUTANT")
  mutant_log=$work/mutant-seed-hidden.java.log
  : > "$mutant_log"
  if ! invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-seed-hidden.err"; then
    bad "seed-hidden mutant failed before its assertion"
  elif [[ $(event_count "$mutant_log" seed __source-inputs) -ne 1 ]]; then
    bad "seed-hidden mutant did not invoke the forbidden hidden command"
  else
    pass "old-seed hidden-command mutant turns the stage boundary red"
  fi
fi

if prepare_mutant no-final-replan; then
  mutant_root=$(make_root mutant-no-replan "$MUTANT")
  mutant_log=$work/mutant-no-replan.java.log
  : > "$mutant_log"
  if ! TEST_MANIFEST_POST="$mutant_root/.fake/manifest.direct" \
      invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-no-replan.err"; then
    bad "no-final-replan mutant failed before promotion"
  elif [[ $(event_count "$mutant_log" candidate __source-inputs) -ne 0 ]] ||
      [[ ! -f $mutant_root/build/dawn-selfhost.stamp ]]; then
    bad "no-final-replan mutant did not promote divergent plans"
  else
    pass "deleted final re-plan promotes divergent manifests and turns red"
  fi
fi

if prepare_mutant inputs-only-replan; then
  mutant_root=$(make_root mutant-inputs-only "$MUTANT")
  mutant_log=$work/mutant-inputs-only.java.log
  : > "$mutant_log"
  if ! TEST_MUTATE_SOURCE="$mutant_root/packages/transitive/src/main.dawn" \
      invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-inputs-only.err" ||
      [[ ! -f $mutant_root/build/dawn-selfhost.stamp ]]; then
    bad "inputs-only mutant failed before promoting source drift"
  else
    pass "inputs-only re-plan misses source drift and turns red"
  fi
fi

if prepare_mutant shared-staging; then
  mutant_root=$(make_root mutant-shared "$MUTANT")
  mutant_log=$work/mutant-shared.java.log
  run_concurrent "$mutant_root" "$mutant_log" || true
  awk -F '\t' '$1 == "seed" && $2 == "build" { print $3 }' "$mutant_log" | \
    sed 's#/[^/]*$##' | LC_ALL=C sort -u > "$work/mutant-shared.transactions"
  if [[ $(wc -l < "$work/mutant-shared.transactions" | tr -d '[:space:]') -eq 2 ]]; then
    bad "shared staging mutant unexpectedly used unique transaction paths"
  else
    pass "shared staging mutant turns the two-builder assertion red"
  fi
fi

if prepare_mutant stamp-first; then
  mutant_root=$(make_root mutant-stamp-first "$MUTANT")
  mutant_log=$work/mutant-stamp-first.java.log
  mutant_mv_log=$work/mutant-stamp-first.mv.log
  : > "$mutant_log"
  : > "$mutant_mv_log"
  mutant_path=$(make_mv_path "$mutant_root")
  if ! TEST_PATH="$mutant_path:$system_path" TEST_MV_LOG=$mutant_mv_log \
      invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-stamp-first.err"; then
    bad "stamp-first mutant failed before its ordering assertion"
  else
    first_promotion=$(grep -E '/build/dawn-selfhost\.(jar|inputs|stamp)$' "$mutant_mv_log" | head -n 1)
    if [[ $first_promotion != "$mutant_root/build/dawn-selfhost.stamp" ]]; then
      bad "stamp-first mutant did not promote the marker first"
    else
      pass "stamp-first mutant turns commit-marker ordering red"
    fi
  fi
fi

if prepare_mutant no-post-promotion-pair; then
  mutant_root=$(make_root mutant-no-post-pair "$MUTANT")
  mutant_log=$work/mutant-no-post-pair.java.log
  mutant_cleanup_log=$work/mutant-no-post-pair.cleanup.log
  : > "$mutant_log"
  : > "$mutant_cleanup_log"
  mutant_path=$(make_promotion_swap_path "$mutant_root")
  if ! TEST_PATH="$mutant_path:$system_path" TEST_PROMOTION_SWAP=1 \
      TEST_CLEANUP_LOG=$mutant_cleanup_log invoke "$mutant_root" "$mutant_log" --version \
      > /dev/null 2> "$work/mutant-no-post-pair.err"; then
    bad "no-post-promotion mutant failed before its assertion"
  elif [[ $(wc -l < "$mutant_cleanup_log" | tr -d '[:space:]') -ne 1 ]]; then
    bad "no-post-promotion mutant unexpectedly retried before cleanup"
  else
    pass "deleted post-promotion pairing misses transient corruption and turns red"
  fi
fi

if prepare_mutant no-pre-exec-pair; then
  mutant_root=$(make_root mutant-no-pre-exec "$MUTANT")
  mutant_log=$work/mutant-no-pre-exec.java.log
  mutant_marker=$mutant_root/.fake/rm-swapped
  : > "$mutant_log"
  mutant_path=$(make_rm_swap_path "$mutant_root")
  TEST_PATH="$mutant_path:$system_path" \
    TEST_RM_SWAP_JAR="$mutant_root/build/dawn-selfhost.jar" \
    TEST_RM_SWAP_MARKER=$mutant_marker \
    invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-no-pre-exec.err" || true
  if [[ $(event_count "$mutant_log" rogue --version) -ne 1 ]]; then
    bad "no-pre-exec mutant did not execute swapped bytes"
  else
    pass "deleted pre-exec pairing executes swapped bytes and turns red"
  fi
fi

if prepare_mutant omit-static-input; then
  mutant_root=$(make_root mutant-omit-static "$MUTANT")
  mutant_log=$work/mutant-omit-static.java.log
  : > "$mutant_log"
  invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-omit-static-setup.err" || bad "omit-static-input mutant setup failed"
  before=$(seed_builds "$mutant_log")
  printf '# resolver edit\n' >> "$mutant_root/scripts/seedjar.sh"
  if ! invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-omit-static.err" ||
      [[ $(seed_builds "$mutant_log") -ne $before ]]; then
    bad "omit-static-input mutant still rebuilt for the dropped input"
  else
    pass "an omitted static input hot-hits and turns coverage red"
  fi
fi

if prepare_mutant track-unrelated-file; then
  mutant_root=$(make_root mutant-track-unrelated "$MUTANT")
  mutant_log=$work/mutant-track-unrelated.java.log
  : > "$mutant_log"
  invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-track-unrelated-setup.err" || bad "track-unrelated-file mutant setup failed"
  before=$(seed_builds "$mutant_log")
  printf 'not an input\n' > "$mutant_root/README.md"
  if ! invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-track-unrelated.err" ||
      [[ $(seed_builds "$mutant_log") -ne $((before + 1)) ]]; then
    bad "track-unrelated-file mutant did not rebuild for the unrelated file"
  else
    pass "tracking an unrelated file rebuilds and turns the control red"
  fi
fi

if prepare_mutant accept-bad-header; then
  mutant_root=$(make_root mutant-bad-header "$MUTANT")
  mutant_log=$work/mutant-bad-header.java.log
  : > "$mutant_log"
  if ! TEST_MANIFEST_PRE=$badman/bad-header \
      invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-bad-header.err" ||
      [[ ! -f $mutant_root/build/dawn-selfhost.stamp ]]; then
    bad "accept-bad-header mutant still rejected the bad header"
  else
    pass "an unchecked manifest header promotes and turns red"
  fi
fi

if prepare_mutant lax-repo-relative-path; then
  mutant_root=$(make_root mutant-lax-path "$MUTANT")
  mutant_log=$work/mutant-lax-path.java.log
  : > "$mutant_log"
  if ! TEST_MANIFEST_PRE=$badman/escaping-record \
      invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-lax-path.err" ||
      [[ ! -f $mutant_root/build/dawn-selfhost.stamp ]]; then
    bad "lax-repo-relative-path mutant still rejected the escaping record"
  else
    pass "lax path spelling promotes an escaping record and turns red"
  fi
fi

if prepare_mutant follow-symlinks; then
  mutant_root=$(make_root mutant-follow-symlinks "$MUTANT")
  mutant_log=$work/mutant-follow-symlinks.java.log
  : > "$mutant_log"
  ln -s main.dawn "$mutant_root/packages/transitive/src/link.dawn"
  if ! invoke "$mutant_root" "$mutant_log" --version > /dev/null 2> "$work/mutant-follow-symlinks.err" ||
      [[ ! -f $mutant_root/build/dawn-selfhost.stamp ]]; then
    bad "follow-symlinks mutant still refused the symlinked tree entry"
  else
    pass "followed symlinks promote a generation and turn red"
  fi
fi

if [[ $fail -ne 0 ]]; then
  exit 1
fi
printf 'OK: bootstrap launcher generation contract\n'
