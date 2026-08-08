#!/usr/bin/env bash
# The two guards standing in front of the bootstrap, driven against the cases
# they exist to refuse.
#
#   ./scripts/bootstrap-guards/run.sh
#
# Neither guard is observable from a green build. `bin/dawn` decides whether to
# rebuild by hashing what it believes the compiler is a function of, and an
# input it forgot looks exactly like an input that did not change: the jar is
# stale, everything works, and nothing says a word. `scripts/seedjar.sh`
# decides whether the seed may be used at all, and a seed that passes and a
# seed that was never checked produce the same output too.
#
# So this moves one thing at a time and requires the answer to move with it.
# The control cases matter as much as the positive ones -- a stamp that changes
# for any edit anywhere proves nothing, and a resolver that refuses everything
# is not a resolver.
#
# No JVM, no network, no seed download: everything runs against a temporary
# root built out of copies. Milliseconds.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

work="$(mktemp -d "${TMPDIR:-/tmp}/bootstrap-guards.XXXXXX")"
trap 'rm -rf "$work"' EXIT

fail=0
ok() { echo "PASS  $1"; }
bad() {
  echo "FAIL: $1" >&2
  fail=1
}

# ---------------------------------------------------------------------------
# TOOL-14: everything the built jar is a function of reaches the stamp.
#
# A copied root, not the real one: the probe edits files, and it has to edit
# the ones bin/dawn will actually read. bin/dawn resolves symlinks to find its
# own root, so it is copied rather than linked -- a symlink would point the
# whole check back at the repo.
# ---------------------------------------------------------------------------
fake="$work/root"
mkdir -p "$fake/bin" "$fake/scripts" "$fake/selfhost"
cp "$root/bin/dawn" "$fake/bin/dawn"
cp "$root/scripts/seedjar.sh" "$root/scripts/seed-release.txt" \
  "$root/scripts/seed-checksums.txt" "$root/scripts/seed-std-checksums.txt" "$fake/scripts/"
cp "$root/selfhost/dawn.toml" "$root/selfhost/dawn.lock" "$fake/selfhost/"
cp -r "$root/selfhost/src" "$fake/selfhost/src"
cp -r "$root/std" "$fake/std"
cp -r "$root/packages" "$fake/packages"

stamp() { DAWN_PRINT_STAMP=1 "$fake/bin/dawn"; }

base="$(stamp)"
if [ -z "$base" ] || [ "$base" = "no-sha256" ]; then
  echo "FAIL: no usable sha256 tool, so the stamp cannot be checked here" >&2
  exit 1
fi

# The declared input set, one file from each member. packages/* are there
# because they are selfhost's [deps] -- the case that was missing, and the one
# a hand-written path list gets wrong again the next time a package is added.
for target in \
  selfhost/src/main.dawn \
  selfhost/dawn.toml \
  selfhost/dawn.lock \
  std/str.dawn \
  scripts/seed-release.txt \
  scripts/seed-checksums.txt \
  scripts/seed-std-checksums.txt \
  scripts/seedjar.sh \
  bin/dawn \
  packages/json/src/parser.dawn \
  packages/sha2/src/sha256.dawn \
  packages/inflate/src/deflate.dawn; do
  printf '\n# bootstrap-guards probe\n' >> "$fake/$target"
  moved="$(stamp)"
  cp "$root/$target" "$fake/$target"
  if [ "$moved" = "$base" ]; then
    bad "$target does not reach the build stamp"
  fi
done
[ "$fail" = 0 ] && ok "every declared build input moves the stamp"

# The control. Without it, "the stamp moved" is consistent with hashing the
# whole directory tree, which would answer yes to anything and mean nothing.
printf 'not an input\n' > "$fake/README.md"
mkdir -p "$fake/docs"
printf 'not an input\n' > "$fake/docs/notes.md"
if [ "$(stamp)" != "$base" ]; then
  bad "the stamp moved for a file that is not a build input"
else
  ok "a file outside the input set leaves the stamp alone"
fi

# ---------------------------------------------------------------------------
# TOOL-16: the seed resolver is fail-closed.
#
# Its preconditions -- a recorded digest for the pinned tag, a hasher on PATH
# -- used to warn and return 0 when absent, so the one occurrence that mattered
# (bump seed-release.txt, forget to add the digest) turned the gate off for
# every build and every CI job while looking like a release omission.
#
# Driven through a root of its own with a pre-filled cache, so nothing here
# downloads anything.
# ---------------------------------------------------------------------------
sroot="$work/seedroot"
mkdir -p "$sroot/scripts" "$sroot/.dawn/seeds/v9.9.9"
cp "$root/scripts/seedjar.sh" "$sroot/scripts/"
printf 'v9.9.9\n' > "$sroot/scripts/seed-release.txt"
printf 'this is the seed jar\n' > "$sroot/.dawn/seeds/v9.9.9/seed.jar"
want=$(sha256sum "$sroot/.dawn/seeds/v9.9.9/seed.jar" | cut -d' ' -f1)

# resolve the seed in a subshell so an `exit 1` inside it stops there
try_seed() { # -> exit code, output in $work/seed.txt
  (
    ROOT="$sroot"
    export ROOT
    # shellcheck disable=SC1091
    . "$sroot/scripts/seedjar.sh"
    seed_jar
  ) > "$work/seed.txt" 2>&1
}

printf '%s  v9.9.9\n' "$want" > "$sroot/scripts/seed-checksums.txt"
if try_seed && [ "$(cat "$work/seed.txt")" = "$sroot/.dawn/seeds/v9.9.9/seed.jar" ]; then
  ok "a cached seed with a matching digest resolves"
else
  bad "the resolver refused a seed that matches its recorded digest"
  sed 's/^/  | /' "$work/seed.txt" >&2
fi

printf '%064d  v9.9.9\n' 0 > "$sroot/scripts/seed-checksums.txt"
if try_seed; then
  bad "a seed whose digest does not match was used anyway"
else
  ok "a seed whose digest does not match is refused"
fi

: > "$sroot/scripts/seed-checksums.txt"
if try_seed; then
  bad "a seed with no recorded digest was used anyway (fail-open)"
  sed 's/^/  | /' "$work/seed.txt" >&2
else
  ok "a seed with no recorded digest is refused"
fi

if DAWN_SEED_ALLOW_UNVERIFIED=1 try_seed; then
  ok "DAWN_SEED_ALLOW_UNVERIFIED re-opens the unrecorded case"
else
  bad "the opt-out does not opt out"
  sed 's/^/  | /' "$work/seed.txt" >&2
fi

# No hasher: the other precondition, and the other thing that used to warn and
# continue. seed_sha_of is redefined rather than PATH emptied -- an empty PATH
# also breaks the awk that reads the table, which would make this pass for the
# wrong reason.
printf '%s  v9.9.9\n' "$want" > "$sroot/scripts/seed-checksums.txt"
if (
  ROOT="$sroot"
  export ROOT
  # shellcheck disable=SC1091
  . "$sroot/scripts/seedjar.sh"
  # shellcheck disable=SC2317 # seed_jar invokes this override indirectly
  seed_sha_of() { echo ""; }
  seed_jar
) > "$work/seed.txt" 2>&1; then
  bad "a seed was used on a machine with no way to hash it"
else
  ok "no way to hash the seed is refused rather than warned about"
fi

# ---------------------------------------------------------------------------
# TOOL-15: the seed's std is verified on the same terms as its jar.
#
# It used to be verified on no terms at all: `modules.txt` exists, use it. Both
# are stage-1 inputs and the cache is a writable directory, so half the
# bootstrap could be swapped with the jar checksum still green.
# ---------------------------------------------------------------------------
mkdir -p "$sroot/.dawn/seeds/std-v9.9.9"
printf 'str\n' > "$sroot/.dawn/seeds/std-v9.9.9/modules.txt"
printf 'pub fn f() -> Int = 1\n' > "$sroot/.dawn/seeds/std-v9.9.9/str.dawn"
std_want=$(
  ROOT="$sroot"
  export ROOT
  # shellcheck disable=SC1091
  . "$sroot/scripts/seedjar.sh"
  seed_tree_sha "$sroot/.dawn/seeds/std-v9.9.9"
)

try_std() { # -> exit code, output in $work/std.txt
  (
    ROOT="$sroot"
    export ROOT
    # shellcheck disable=SC1091
    . "$sroot/scripts/seedjar.sh"
    seed_std_dir
  ) > "$work/std.txt" 2>&1
}

printf '%s  v9.9.9\n' "$std_want" > "$sroot/scripts/seed-std-checksums.txt"
if try_std && [ "$(cat "$work/std.txt")" = "$sroot/.dawn/seeds/std-v9.9.9" ]; then
  ok "a cached seed std with a matching tree hash resolves"
else
  bad "the resolver refused a seed std that matches its recorded hash"
  sed 's/^/  | /' "$work/std.txt" >&2
fi

# The whole point: a writable cache directory. Edit one byte of it.
printf 'pub fn f() -> Int = 2\n' > "$sroot/.dawn/seeds/std-v9.9.9/str.dawn"
if try_std; then
  bad "an edited seed std was used anyway"
  sed 's/^/  | /' "$work/std.txt" >&2
else
  ok "an edited seed std is refused"
fi
printf 'pub fn f() -> Int = 1\n' > "$sroot/.dawn/seeds/std-v9.9.9/str.dawn"

# A file *added* to the tree, which a per-file check would miss and a tree
# hash cannot.
printf 'extra\n' > "$sroot/.dawn/seeds/std-v9.9.9/extra.dawn"
if try_std; then
  bad "a file added to the seed std went unnoticed"
else
  ok "a file added to the seed std is refused"
fi
rm -f "$sroot/.dawn/seeds/std-v9.9.9/extra.dawn"

: > "$sroot/scripts/seed-std-checksums.txt"
if try_std; then
  bad "a seed std with no recorded hash was used anyway (fail-open)"
  sed 's/^/  | /' "$work/std.txt" >&2
else
  ok "a seed std with no recorded hash is refused"
fi

# ---------------------------------------------------------------------------
# TOOL-17: release and fixed-point gates share one build recipe, and release
# compares that recipe's output across both supported JDKs before publishing.
#
# A fixed point only proves the recipe that produced it. If the workflow and
# local gate each spell the chain independently, both may stay green while the
# published artifact drifts from the one tested on every push. Likewise, two
# fixed points produced by different host JDKs are not one reproducible release
# until their final jars compare byte for byte.
# ---------------------------------------------------------------------------
tool17_count_line() {
  awk -v want="$2" '
    {
      line = $0
      sub(/^[[:space:]]+/, "", line)
      sub(/[[:space:]]+$/, "", line)
      if (line == want) count++
    }
    END { print count + 0 }
  ' "$1"
}

tool17_require_line() {
  local file="$1"
  local line="$2"
  local message="$3"
  if [ "$(tool17_count_line "$file" "$line")" -ne 1 ]; then
    echo "$message" >&2
    return 1
  fi
}

tool17_asset_block() {
  awk '
    {
      line = $0
      sub(/^[[:space:]]+/, "", line)
      sub(/[[:space:]]+$/, "", line)
      if (line == "EXPECTED_ASSETS=(") {
        inside = 1
        next
      }
      if (inside && line == ")") exit
      if (inside) print line
    }
  ' "$1"
}

tool17_line_number() {
  grep -nF "$2" "$1" | head -n 1 | cut -d: -f1
}

tool17_validate() {
  local release_file="$1"
  local wrapper_file="$2"
  local compare_line
  local create_line
  local errors=0
  local exact_count
  local expected_assets
  local native_line
  local publish_check_line
  local publish_upload_line
  local ref_count

  exact_count="$(tool17_count_line "$release_file" \
    'run: ./scripts/build-release-jar.sh -o dawn-selfhost.jar')"
  ref_count="$(grep -F -c './scripts/build-release-jar.sh' "$release_file")"
  if [ "$exact_count" -ne 1 ] || [ "$ref_count" -ne 1 ]; then
    echo "release.yml must contain exactly one canonical release-JAR builder call" >&2
    errors=1
  fi

  if ! tool17_require_line "$release_file" \
      "java-version: ['21', '26']" \
      "release.yml must build the canonical jar on exactly JDK 21 and JDK 26"; then
    errors=1
  fi
  # shellcheck disable=SC2016 # literal GitHub expression in workflow source
  if ! tool17_require_line "$release_file" \
      'java-version: ${{ matrix.java-version }}' \
      "release.yml must feed the JDK matrix into the canonical build job"; then
    errors=1
  fi
  # shellcheck disable=SC2016 # literal GitHub expression in workflow source
  if ! tool17_require_line "$release_file" \
      'name: release-jar-jdk-${{ matrix.java-version }}' \
      "release.yml must retain each matrix candidate under its JDK identity"; then
    errors=1
  fi
  if ! tool17_require_line "$release_file" 'needs: release-jar' \
      "release.yml must wait for both matrix candidates before release"; then
    errors=1
  fi
  # shellcheck disable=SC2016 # literal workflow shell source
  for line in \
    'name: release-jar-jdk-21' \
    'name: release-jar-jdk-26' \
    'JDK21_JAR=release-candidates/jdk-21/dawn-selfhost.jar' \
    'JDK26_JAR=release-candidates/jdk-26/dawn-selfhost.jar' \
    'cmp "$JDK21_JAR" "$JDK26_JAR"' \
    'cp "$JDK21_JAR" dawn-selfhost.jar' \
    'cmp "$JDK21_JAR" dawn-selfhost.jar'; do
    if ! tool17_require_line "$release_file" "$line" \
        "release.yml is missing one exact cross-JDK comparison or selection step: $line"; then
      errors=1
    fi
  done

  expected_assets="$(printf '%s\n' \
    dawn-selfhost.jar \
    dawn-selfhost.jar.sha256 \
    dawnc-linux-x86_64 \
    dawnc-linux-x86_64.sha256)"
  if [ "$(tool17_asset_block "$release_file")" != "$expected_assets" ]; then
    echo "release.yml must publish exactly the four canonical asset names" >&2
    errors=1
  fi
  # shellcheck disable=SC2016 # literal workflow shell source
  for line in \
    'if ! gh release view "$GITHUB_REF_NAME" > /dev/null 2>&1; then' \
    'gh release upload "$GITHUB_REF_NAME" --clobber "${EXPECTED_ASSETS[@]}"' \
    'mapfile -t PUBLISHED_ASSETS < <(' \
    'for EXPECTED in "${EXPECTED_ASSETS[@]}"; do' \
    'if [ "$COUNT" -ne 1 ]; then'; do
    if ! tool17_require_line "$release_file" "$line" \
        "release.yml is missing one exact idempotent publish assertion: $line"; then
      errors=1
    fi
  done
  # shellcheck disable=SC2016 # literal workflow shell source
  ref_count="$(grep -F -c 'gh release create "$GITHUB_REF_NAME"' "$release_file")"
  if [ "$ref_count" -ne 1 ]; then
    echo "release.yml must create the release only through its guarded call" >&2
    errors=1
  fi

  # Presence is not enough: the release job must consume the comparison before
  # native compilation, and publication must upload before it checks GitHub's
  # resulting asset set.
  # shellcheck disable=SC2016 # literal workflow shell source
  compare_line="$(tool17_line_number "$release_file" 'cmp "$JDK21_JAR" "$JDK26_JAR"')"
  native_line="$(tool17_line_number "$release_file" './scripts/release-native.sh')"
  # shellcheck disable=SC2016 # literal workflow shell source
  create_line="$(tool17_line_number "$release_file" 'gh release create "$GITHUB_REF_NAME"')"
  # shellcheck disable=SC2016 # literal workflow shell source
  publish_upload_line="$(tool17_line_number "$release_file" 'gh release upload "$GITHUB_REF_NAME"')"
  publish_check_line="$(tool17_line_number "$release_file" 'mapfile -t PUBLISHED_ASSETS')"
  if [ -z "$compare_line" ] || [ -z "$native_line" ] || \
      [ "$compare_line" -ge "$native_line" ]; then
    echo "release.yml must compare JDK candidates before native compilation" >&2
    errors=1
  fi
  if [ -z "$create_line" ] || [ -z "$publish_upload_line" ] || \
      [ -z "$publish_check_line" ] || \
      [ "$create_line" -ge "$publish_upload_line" ] || \
      [ "$publish_upload_line" -ge "$publish_check_line" ]; then
    echo "release.yml must create, clobber-upload, then verify release assets" >&2
    errors=1
  fi

  # shellcheck disable=SC2016 # $work is literal text in the guarded script
  exact_count="$(tool17_count_line "$wrapper_file" \
    './scripts/build-release-jar.sh -o "$work/dawn-selfhost.jar"')"
  ref_count="$(grep -F -c './scripts/build-release-jar.sh' "$wrapper_file")"
  if [ "$exact_count" -ne 1 ] || [ "$ref_count" -ne 1 ]; then
    echo "selfhost-fixpoint.sh must contain exactly one canonical builder call" >&2
    errors=1
  fi

  for caller in "$release_file" "$wrapper_file"; do
    if grep -Eq '(^|[[:space:]])build[[:space:]]+selfhost([[:space:]]|$)' "$caller"; then
      echo "$caller contains a second inline build selfhost recipe" >&2
      errors=1
    fi
    if grep -Eq '(^|[^[:alnum:]_.-])[ac]\.jar([^[:alnum:]_.-]|$)' "$caller"; then
      echo "$caller contains stage artifact names outside the canonical builder" >&2
      errors=1
    fi
  done

  return "$errors"
}

release_file="$root/.github/workflows/release.yml"
wrapper_file="$root/scripts/selfhost-fixpoint.sh"
if tool17_validate "$release_file" "$wrapper_file"; then
  ok "release uses one cross-JDK recipe and an idempotent four-asset contract"
else
  bad "release bypasses its canonical build, comparison, or publish contract"
fi

tool17_dir="$work/tool17"
mkdir -p "$tool17_dir"
cp "$release_file" "$tool17_dir/release.base.yml"
cp "$wrapper_file" "$tool17_dir/wrapper.base.sh"

tool17_expect_reject() {
  local name="$1"
  local mutated_release="$2"
  local mutated_wrapper="$3"
  if tool17_validate "$mutated_release" "$mutated_wrapper" \
      > "$tool17_dir/control.out" 2>&1; then
    bad "$name did not trip the release-recipe guard"
  else
    ok "$name trips the release-recipe guard"
  fi
}

sed '/build-release-jar\.sh -o dawn-selfhost\.jar/d' \
  "$tool17_dir/release.base.yml" > "$tool17_dir/release.missing.yml"
tool17_expect_reject "a missing builder call" \
  "$tool17_dir/release.missing.yml" "$tool17_dir/wrapper.base.sh"

sed "s/java-version: \['21', '26'\]/java-version: ['21']/" \
  "$tool17_dir/release.base.yml" > "$tool17_dir/release.one-jdk.yml"
tool17_expect_reject "removing the second release JDK" \
  "$tool17_dir/release.one-jdk.yml" "$tool17_dir/wrapper.base.sh"

# shellcheck disable=SC2016 # mutate literal workflow shell source
sed '/cmp "$JDK21_JAR" "$JDK26_JAR"/d' \
  "$tool17_dir/release.base.yml" > "$tool17_dir/release.no-cross-jdk-cmp.yml"
tool17_expect_reject "bypassing the cross-JDK comparison" \
  "$tool17_dir/release.no-cross-jdk-cmp.yml" "$tool17_dir/wrapper.base.sh"

cp "$tool17_dir/release.base.yml" "$tool17_dir/release.double.yml"
printf '\n      - name: duplicate builder mutation\n        run: ./scripts/build-release-jar.sh -o dawn-selfhost.jar\n' \
  >> "$tool17_dir/release.double.yml"
tool17_expect_reject "a duplicate builder call" \
  "$tool17_dir/release.double.yml" "$tool17_dir/wrapper.base.sh"

cp "$tool17_dir/release.base.yml" "$tool17_dir/release.inline.yml"
printf '\n      - name: inline recipe mutation\n        run: java -jar seed.jar build selfhost -o candidate.jar\n' \
  >> "$tool17_dir/release.inline.yml"
tool17_expect_reject "an appended inline build" \
  "$tool17_dir/release.inline.yml" "$tool17_dir/wrapper.base.sh"

sed 's/build-release-jar\.sh -o dawn-selfhost\.jar/build-release-jar.sh -o candidate.jar/' \
  "$tool17_dir/release.base.yml" > "$tool17_dir/release.wrong-output.yml"
tool17_expect_reject "a wrong release output name" \
  "$tool17_dir/release.wrong-output.yml" "$tool17_dir/wrapper.base.sh"

sed 's/^[[:space:]]*dawnc-linux-x86_64\.sha256$/            dawnc-linux-amd64.sha256/' \
  "$tool17_dir/release.base.yml" > "$tool17_dir/release.wrong-asset.yml"
tool17_expect_reject "a wrong published asset name" \
  "$tool17_dir/release.wrong-asset.yml" "$tool17_dir/wrapper.base.sh"

# shellcheck disable=SC2016 # mutate the guarded script's literal $work
sed 's|\./scripts/build-release-jar\.sh -o "$work/dawn-selfhost\.jar"|java -Xss512m -jar seed.jar build selfhost -o "$work/dawn-selfhost.jar"|' \
  "$tool17_dir/wrapper.base.sh" > "$tool17_dir/wrapper.bypass.sh"
tool17_expect_reject "a wrapper that bypasses the builder" \
  "$tool17_dir/release.base.yml" "$tool17_dir/wrapper.bypass.sh"

# ---------------------------------------------------------------------------
# TOOL-18: one entry advances both seed trust records before the pointer.
#
# The safe order is not observable after a successful run, and a release notice
# that prints two hashes looks almost as helpful as the single command while
# putting the protocol back in human hands. Keep these source-level invariants
# executable, then mutate each one below.
# ---------------------------------------------------------------------------
tool18_validate() {
  local script_file="$1"
  local action_file="$2"
  local release_workflow="$3"
  local archive_line std_hash_line seed_verify_line std_verify_line
  local recheck_line checksum_line std_line pointer_line
  local errors=0

  # shellcheck disable=SC2016 # literal GitHub expression in action source
  if ! tool17_require_line "$action_file" \
      "key: dawn-seed-\${{ hashFiles('scripts/seed-release.txt', 'scripts/seed-checksums.txt', 'scripts/seed-std-checksums.txt') }}" \
      "the seed cache key must cover the pointer and both trust records"; then
    errors=1
  fi

  # shellcheck disable=SC2016 # literal workflow shell source
  if ! tool17_require_line "$release_workflow" \
      'run: echo "::notice::./scripts/advance-seed.sh $GITHUB_REF_NAME"' \
      "release.yml must report only the single seed-advance command"; then
    errors=1
  fi
  if [ "$(grep -F -c '::notice::' "$release_workflow")" -ne 1 ]; then
    echo "release.yml must contain exactly one seed notice" >&2
    errors=1
  fi

  # shellcheck disable=SC2016 # literal script source
  for line in \
    'git -C "$root" archive "$tag_commit" std | tar -x -C "$archive_dir"' \
    'std_sha="$(seed_tree_sha "$archive_dir/std")"' \
    'seed_verify "$jar_file" "$tag"' \
    'seed_std_verify "$archive_dir/std" "$tag"' \
    'verify_remote_tag_unchanged' \
    'promote_file "$checksum_candidate" "$checksum_file"' \
    'promote_file "$std_checksum_candidate" "$std_checksum_file"' \
    'promote_file "$seed_release_candidate" "$seed_release_file"'; do
    if ! tool17_require_line "$script_file" "$line" \
        "advance-seed.sh is missing one exact trust or promotion step: $line"; then
      errors=1
    fi
  done

  # Presence and source order both matter. The remote-tag check is final only
  # when it follows both consumer verifiers.
  # shellcheck disable=SC2016 # literal script source
  archive_line="$(tool18_line_number "$script_file" 'git -C "$root" archive "$tag_commit" std | tar -x -C "$archive_dir"')"
  # shellcheck disable=SC2016 # literal script source
  std_hash_line="$(tool18_line_number "$script_file" 'std_sha="$(seed_tree_sha "$archive_dir/std")"')"
  # shellcheck disable=SC2016 # literal script source
  seed_verify_line="$(tool18_line_number "$script_file" 'seed_verify "$jar_file" "$tag"')"
  # shellcheck disable=SC2016 # literal script source
  std_verify_line="$(tool18_line_number "$script_file" 'seed_std_verify "$archive_dir/std" "$tag"')"
  # shellcheck disable=SC2016 # literal script source
  recheck_line="$(tool18_line_number "$script_file" 'verify_remote_tag_unchanged')"
  # shellcheck disable=SC2016 # literal script source
  checksum_line="$(tool18_line_number "$script_file" 'promote_file "$checksum_candidate" "$checksum_file"')"
  # shellcheck disable=SC2016 # literal script source
  std_line="$(tool18_line_number "$script_file" 'promote_file "$std_checksum_candidate" "$std_checksum_file"')"
  # shellcheck disable=SC2016 # literal script source
  pointer_line="$(tool18_line_number "$script_file" 'promote_file "$seed_release_candidate" "$seed_release_file"')"
  if [ -z "$archive_line" ] || [ -z "$std_hash_line" ] ||
      [ -z "$seed_verify_line" ] || [ -z "$std_verify_line" ] ||
      [ -z "$recheck_line" ] || [ -z "$checksum_line" ] ||
      [ -z "$std_line" ] || [ -z "$pointer_line" ] ||
      [ "$archive_line" -ge "$std_hash_line" ] ||
      [ "$std_hash_line" -ge "$seed_verify_line" ] ||
      [ "$seed_verify_line" -ge "$std_verify_line" ] ||
      [ "$std_verify_line" -ge "$recheck_line" ] ||
      [ "$recheck_line" -ge "$checksum_line" ] ||
      [ "$checksum_line" -ge "$std_line" ] || [ "$std_line" -ge "$pointer_line" ]; then
    echo "advance-seed.sh must hash tagged std, run both consumer verifiers, recheck the tag, then promote jar hash, std hash, and pointer" >&2
    errors=1
  fi

  return "$errors"
}

tool18_line_number() {
  awk -v want="$2" '
    {
      line = $0
      sub(/^[[:space:]]+/, "", line)
      sub(/[[:space:]]+$/, "", line)
      if (line == want) {
        print NR
        exit
      }
    }
  ' "$1"
}

advance_file="$root/scripts/advance-seed.sh"
action_file="$root/.github/actions/dawn-toolchain/action.yml"
if tool18_validate "$advance_file" "$action_file" "$release_file"; then
  ok "one entry advances both verified seed inputs before the pointer"
else
  bad "the seed-advance protocol is incomplete or manually split"
fi

tool18_dir="$work/tool18"
mkdir -p "$tool18_dir"
cp "$advance_file" "$tool18_dir/advance.base.sh"
cp "$action_file" "$tool18_dir/action.base.yml"
cp "$release_file" "$tool18_dir/release.base.yml"

tool18_expect_reject() {
  local name="$1"
  local mutated_script="$2"
  local mutated_action="$3"
  local mutated_release="$4"
  if tool18_validate "$mutated_script" "$mutated_action" "$mutated_release" \
      > "$tool18_dir/control.out" 2>&1; then
    bad "$name did not trip the seed-advance guard"
  else
    ok "$name trips the seed-advance guard"
  fi
}

sed "s/, 'scripts\/seed-std-checksums.txt'//" \
  "$tool18_dir/action.base.yml" > "$tool18_dir/action.no-std.yml"
tool18_expect_reject "omitting the std checksum from the seed cache key" \
  "$tool18_dir/advance.base.sh" "$tool18_dir/action.no-std.yml" "$tool18_dir/release.base.yml"

# shellcheck disable=SC2016 # mutate literal workflow shell source
sed 's|run: echo "::notice::./scripts/advance-seed.sh $GITHUB_REF_NAME"|run: echo "::notice::add hashes to both seed tables by hand"|' \
  "$tool18_dir/release.base.yml" > "$tool18_dir/release.manual-notice.yml"
tool18_expect_reject "replacing the command with a manual seed notice" \
  "$tool18_dir/advance.base.sh" "$tool18_dir/action.base.yml" "$tool18_dir/release.manual-notice.yml"

# shellcheck disable=SC2016 # mutate literal script source
sed 's/archive "$tag_commit" std/archive HEAD std/' \
  "$tool18_dir/advance.base.sh" > "$tool18_dir/advance.head-std.sh"
tool18_expect_reject "hashing HEAD std instead of the tag archive" \
  "$tool18_dir/advance.head-std.sh" "$tool18_dir/action.base.yml" "$tool18_dir/release.base.yml"

# shellcheck disable=SC2016 # mutate literal script source
sed '/seed_verify "$jar_file" "$tag"/d' \
  "$tool18_dir/advance.base.sh" > "$tool18_dir/advance.no-jar-verify.sh"
tool18_expect_reject "omitting the release JAR consumer verification" \
  "$tool18_dir/advance.no-jar-verify.sh" "$tool18_dir/action.base.yml" "$tool18_dir/release.base.yml"

# shellcheck disable=SC2016 # mutate literal script source
sed '/seed_std_verify "$archive_dir\/std" "$tag"/d' \
  "$tool18_dir/advance.base.sh" > "$tool18_dir/advance.no-std-verify.sh"
tool18_expect_reject "omitting the tagged std consumer verification" \
  "$tool18_dir/advance.no-std-verify.sh" "$tool18_dir/action.base.yml" "$tool18_dir/release.base.yml"

# Move the invocation, not the function definition, ahead of both verifiers.
# shellcheck disable=SC2016 # mutate literal script source
awk '
  /^[[:space:]]*seed_verify "\$jar_file" "\$tag"[[:space:]]*$/ {
    print "verify_remote_tag_unchanged"
  }
  /^[[:space:]]*verify_remote_tag_unchanged[[:space:]]*$/ { next }
  { print }
' "$tool18_dir/advance.base.sh" > "$tool18_dir/advance.early-recheck.sh"
tool18_expect_reject "moving the final tag recheck before consumer verification" \
  "$tool18_dir/advance.early-recheck.sh" "$tool18_dir/action.base.yml" "$tool18_dir/release.base.yml"

awk '
  /promote_file "\$checksum_candidate" "\$checksum_file"/ {
    print "promote_file \"$std_checksum_candidate\" \"$std_checksum_file\""
    next
  }
  /promote_file "\$std_checksum_candidate" "\$std_checksum_file"/ {
    print "promote_file \"$checksum_candidate\" \"$checksum_file\""
    next
  }
  { print }
' "$tool18_dir/advance.base.sh" > "$tool18_dir/advance.wrong-order.sh"
tool18_expect_reject "promoting the std record before the JAR record" \
  "$tool18_dir/advance.wrong-order.sh" "$tool18_dir/action.base.yml" "$tool18_dir/release.base.yml"

exit "$fail"
