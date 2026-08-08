#!/usr/bin/env bash
# Advance both bootstrap inputs through one fail-closed entry point. Selecting
# a release is safe only after its JAR and tagged std tree have been fetched,
# independently hashed, and verified through the same consumer checks used by
# the bootstrap resolver. The pointer moves last so an interrupted run can
# leave only verified future trust records, which a retry can safely converge.
set -euo pipefail

export LC_ALL=C

usage() {
  echo "usage: $0 <vMAJOR.MINOR.PATCH>" >&2
  exit 2
}

die() {
  echo "error: $1" >&2
  exit 1
}

if [ "$#" -ne 1 ]; then
  usage
fi

tag="$1"
if [[ ! "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  usage
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ROOT="$root"
export ROOT
# shellcheck disable=SC1091
. "$root/scripts/seedjar.sh"
unset DAWN_SEED_ALLOW_UNVERIFIED

seed_origin="${DAWN_SEED_ORIGIN:-origin}"
if [ -z "$seed_origin" ] || [[ "$seed_origin" == *$'\n'* ]]; then
  die "DAWN_SEED_ORIGIN must name one non-empty remote or path"
fi

release_base_url="https://github.com/dawnop/dawn-lang/releases/download"
release_url_overridden=0
if [ "${DAWN_RELEASE_BASE_URL+x}" = x ]; then
  [ -n "$DAWN_RELEASE_BASE_URL" ] ||
    die "DAWN_RELEASE_BASE_URL cannot be empty"
  release_base_url="$DAWN_RELEASE_BASE_URL"
  release_url_overridden=1
fi
if [[ "$release_base_url" == *$'\n'* ]]; then
  die "release base URL must fit on one line"
fi

seed_files_root="$root"
if [ "${DAWN_SEED_FILES_ROOT+x}" = x ]; then
  [ -n "$DAWN_SEED_FILES_ROOT" ] || die "DAWN_SEED_FILES_ROOT cannot be empty"
  seed_files_root="$DAWN_SEED_FILES_ROOT"
fi
seed_files_root="$(cd "$seed_files_root" 2>/dev/null && pwd -P)" ||
  die "seed file root does not exist"

for required_tool in cmp curl git java mktemp tar; do
  command -v "$required_tool" >/dev/null 2>&1 || die "required tool '$required_tool' is unavailable"
done

seed_release_file="$seed_files_root/scripts/seed-release.txt"
checksum_file="$seed_files_root/scripts/seed-checksums.txt"
std_checksum_file="$seed_files_root/scripts/seed-std-checksums.txt"

for required_file in \
  "$seed_release_file" \
  "$checksum_file" \
  "$std_checksum_file"; do
  [ -f "$required_file" ] || die "missing seed file $required_file"
  [ ! -L "$required_file" ] || die "seed file must not be a symbolic link: $required_file"
done

work="$(mktemp -d "${TMPDIR:-/tmp}/dawn-advance-seed.XXXXXX")"
temp_ref="refs/dawn-advance-seed/$(basename "$work")"
active_stage=""
promotion_started=0
promotion_complete=0

restore_file() {
  local backup="$1"
  local target="$2"
  local restore_stage

  restore_stage="$(mktemp "$(dirname "$target")/.advance-seed.restore.XXXXXX")" || return 1
  if ! cp -p "$backup" "$restore_stage" || ! mv "$restore_stage" "$target"; then
    rm -f "$restore_stage"
    return 1
  fi
}

cleanup() {
  local status=$?
  local restore_failed=0

  trap - EXIT HUP INT TERM
  set +e
  if [ "$promotion_started" -eq 1 ] &&
      [ "$promotion_complete" -eq 0 ] &&
      [ "$status" -ne 0 ]; then
    echo "warning: seed promotion failed; restoring all three seed files" >&2
    restore_file "$work/seed-checksums.txt.original" "$checksum_file" || restore_failed=1
    restore_file "$work/seed-std-checksums.txt.original" "$std_checksum_file" || restore_failed=1
    restore_file "$work/seed-release.txt.original" "$seed_release_file" || restore_failed=1
    if [ "$restore_failed" -ne 0 ]; then
      echo "error: seed promotion failed and rollback was incomplete" >&2
      status=1
    fi
  fi
  [ -z "$active_stage" ] || rm -f "$active_stage"
  if ! git -C "$root" update-ref -d "$temp_ref" >/dev/null 2>&1; then
    echo "error: cannot remove temporary ref $temp_ref" >&2
    status=1
  fi
  rm -rf "$work"
  exit "$status"
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

cp -p "$checksum_file" "$work/seed-checksums.txt.original"
cp -p "$std_checksum_file" "$work/seed-std-checksums.txt.original"
cp -p "$seed_release_file" "$work/seed-release.txt.original"

read_exact_line() {
  local file="$1"
  local description="$2"
  local line

  if ! IFS= read -r line < "$file"; then
    die "$description must contain one newline-terminated line"
  fi
  if ! printf '%s\n' "$line" | cmp -s - "$file"; then
    die "$description must contain exactly one newline-terminated line"
  fi
  exact_line="$line"
}

validate_checksum_table() {
  local file="$1"
  local name="$2"

  awk -v name="$name" '
    /^[[:space:]]*($|#)/ { next }
    !/^[0-9a-f]{64}  v[0-9]+\.[0-9]+\.[0-9]+$/ {
      printf "error: %s has an invalid entry on line %d\n", name, NR > "/dev/stderr"
      failed = 1
      next
    }
    {
      if (seen[$2]++) {
        printf "error: %s records tag %s more than once\n", name, $2 > "/dev/stderr"
        failed = 1
      }
    }
    END { exit failed }
  ' "$file"
}

validate_checksum_table "$checksum_file" "scripts/seed-checksums.txt" || exit 1
validate_checksum_table "$std_checksum_file" "scripts/seed-std-checksums.txt" || exit 1

read_exact_line "$seed_release_file" "scripts/seed-release.txt"
current_seed="$exact_line"
if [[ ! "$current_seed" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  die "scripts/seed-release.txt does not contain one semantic-version tag"
fi

version_is_at_least() {
  local candidate="${1#v}"
  local baseline="${2#v}"
  local candidate_parts baseline_parts
  local candidate_part baseline_part index

  IFS=. read -r -a candidate_parts <<< "$candidate"
  IFS=. read -r -a baseline_parts <<< "$baseline"
  for index in 0 1 2; do
    candidate_part="${candidate_parts[$index]}"
    baseline_part="${baseline_parts[$index]}"
    while [ "${#candidate_part}" -gt 1 ] && [ "${candidate_part:0:1}" = 0 ]; do
      candidate_part="${candidate_part:1}"
    done
    while [ "${#baseline_part}" -gt 1 ] && [ "${baseline_part:0:1}" = 0 ]; do
      baseline_part="${baseline_part:1}"
    done
    if [ "${#candidate_part}" -gt "${#baseline_part}" ]; then
      return 0
    fi
    if [ "${#candidate_part}" -lt "${#baseline_part}" ]; then
      return 1
    fi
    if [[ "$candidate_part" > "$baseline_part" ]]; then
      return 0
    fi
    if [[ "$candidate_part" < "$baseline_part" ]]; then
      return 1
    fi
  done
  return 0
}

if ! version_is_at_least "$tag" "$current_seed"; then
  die "refusing to move the seed backwards from $current_seed to $tag"
fi

entry_count() {
  awk -v tag="$2" '$1 !~ /^#/ && $2 == tag { count++ } END { print count + 0 }' "$1"
}

jar_entry_count="$(entry_count "$checksum_file" "$tag")"
std_entry_count="$(entry_count "$std_checksum_file" "$tag")"
if [ "$current_seed" = "$tag" ] &&
    { [ "$jar_entry_count" -ne 1 ] || [ "$std_entry_count" -ne 1 ]; }; then
  die "$tag is already selected but one or both trust records are missing"
fi

fetch_tag_snapshot() {
  local phase="$1"

  if ! git -C "$root" fetch --quiet --no-tags --no-write-fetch-head \
      "$seed_origin" "+refs/tags/$tag:$temp_ref"; then
    die "cannot fetch tag $tag from origin during $phase verification"
  fi
  fetched_tag_object="$(git -C "$root" rev-parse "$temp_ref")" ||
    die "cannot resolve tag $tag during $phase verification"
  fetched_tag_commit="$(git -C "$root" rev-parse "$temp_ref^{commit}")" ||
    die "tag $tag does not resolve to a commit during $phase verification"
  if [[ ! "$fetched_tag_object" =~ ^([0-9a-f]{40}|[0-9a-f]{64})$ ]] ||
      [[ ! "$fetched_tag_commit" =~ ^([0-9a-f]{40}|[0-9a-f]{64})$ ]]; then
    die "origin returned malformed object identifiers for tag $tag"
  fi
}

verify_remote_tag_unchanged() {
  fetch_tag_snapshot "final"
  if [ "$fetched_tag_object" != "$initial_tag_object" ] ||
      [ "$fetched_tag_commit" != "$tag_commit" ]; then
    die "tag $tag moved while release inputs were being verified"
  fi
}

fetch_tag_snapshot "initial"
initial_tag_object="$fetched_tag_object"
tag_commit="$fetched_tag_commit"

if ! git -C "$root" merge-base --is-ancestor "$tag_commit" HEAD; then
  die "tag $tag does not name an ancestor of the current HEAD"
fi

git -C "$root" show "$tag_commit:selfhost/src/version.dawn" > "$work/version.dawn" ||
  die "tag $tag has no selfhost/src/version.dawn"
mapfile -t source_versions < <(
  sed -n 's/^pub const VERSION: String = "\([^"]*\)"$/\1/p' "$work/version.dawn"
)
if [ "${#source_versions[@]}" -ne 1 ] || [ "${source_versions[0]}" != "${tag#v}" ]; then
  die "tag $tag does not exactly match its source VERSION"
fi

release_url="${release_base_url%/}/$tag"
jar_file="$work/dawn-selfhost.jar"
sidecar_file="$work/dawn-selfhost.jar.sha256"
curl_args=(
  -q
  --fail
  --show-error
  --silent
  --location
  --connect-timeout 15
  --max-time 300
)
if [ "$release_url_overridden" -eq 0 ]; then
  curl_args+=(--proto '=https' --proto-redir '=https')
fi
curl "${curl_args[@]}" -o "$jar_file" "$release_url/dawn-selfhost.jar" ||
  die "cannot download dawn-selfhost.jar for $tag"
curl "${curl_args[@]}" -o "$sidecar_file" "$release_url/dawn-selfhost.jar.sha256" ||
  die "cannot download dawn-selfhost.jar.sha256 for $tag"

read_exact_line "$sidecar_file" "release checksum sidecar"
sidecar_line="$exact_line"
sidecar_sha="${sidecar_line%%  *}"
if [[ ! "$sidecar_sha" =~ ^[0-9a-f]{64}$ ]] ||
    [ "$sidecar_line" != "$sidecar_sha  dawn-selfhost.jar" ]; then
  die "release checksum sidecar must be '<lowercase-sha256>  dawn-selfhost.jar'"
fi
jar_sha="$(seed_sha_of "$jar_file")"
if [ -z "$jar_sha" ]; then
  die "no sha256sum or shasum is available"
fi
if [ "$jar_sha" != "$sidecar_sha" ]; then
  die "downloaded dawn-selfhost.jar does not match its release sidecar"
fi

jar_version_file="$work/jar-version.txt"
expected_jar_version_file="$work/expected-jar-version.txt"
if ! java -Xss512m -jar "$jar_file" --version > "$jar_version_file"; then
  die "the $tag release JAR does not run"
fi
printf 'dawn %s (selfhost)\n' "${tag#v}" > "$expected_jar_version_file"
if ! cmp -s "$expected_jar_version_file" "$jar_version_file"; then
  die "release JAR did not report exactly 'dawn ${tag#v} (selfhost)'"
fi

archive_dir="$work/tag-archive"
mkdir -p "$archive_dir"
if ! (
  git -C "$root" archive "$tag_commit" std | tar -x -C "$archive_dir"
); then
  die "cannot extract std from tag $tag"
fi
[ -f "$archive_dir/std/modules.txt" ] || die "tag $tag does not contain std/modules.txt"
std_sha="$(seed_tree_sha "$archive_dir/std")"
if [[ ! "$std_sha" =~ ^[0-9a-f]{64}$ ]]; then
  die "cannot compute the std tree hash for $tag"
fi

existing_jar_sha="$(awk -v tag="$tag" '$1 !~ /^#/ && $2 == tag { print $1 }' "$checksum_file")"
existing_std_sha="$(awk -v tag="$tag" '$1 !~ /^#/ && $2 == tag { print $1 }' "$std_checksum_file")"
if [ -n "$existing_jar_sha" ] && [ "$existing_jar_sha" != "$jar_sha" ]; then
  die "scripts/seed-checksums.txt already records a conflicting digest for $tag"
fi
if [ -n "$existing_std_sha" ] && [ "$existing_std_sha" != "$std_sha" ]; then
  die "scripts/seed-std-checksums.txt already records a conflicting tree hash for $tag"
fi

checksum_candidate="$work/seed-checksums.candidate"
std_checksum_candidate="$work/seed-std-checksums.candidate"
seed_release_candidate="$work/seed-release.candidate"
cp -p "$checksum_file" "$checksum_candidate"
cp -p "$std_checksum_file" "$std_checksum_candidate"
if [ "$jar_entry_count" -eq 0 ]; then
  printf '%s  %s\n' "$jar_sha" "$tag" >> "$checksum_candidate"
fi
if [ "$std_entry_count" -eq 0 ]; then
  printf '%s  %s\n' "$std_sha" "$tag" >> "$std_checksum_candidate"
fi
printf '%s\n' "$tag" > "$seed_release_candidate"

validate_checksum_table "$checksum_candidate" "candidate seed-checksums.txt" || exit 1
validate_checksum_table "$std_checksum_candidate" "candidate seed-std-checksums.txt" || exit 1

candidate_root="$work/candidate-root"
mkdir -p "$candidate_root/scripts"
cp "$checksum_candidate" "$candidate_root/scripts/seed-checksums.txt"
cp "$std_checksum_candidate" "$candidate_root/scripts/seed-std-checksums.txt"
(
  ROOT="$candidate_root"
  export ROOT
  unset DAWN_SEED_ALLOW_UNVERIFIED
  # shellcheck disable=SC1091
  . "$root/scripts/seedjar.sh"
  seed_verify "$jar_file" "$tag"
  seed_std_verify "$archive_dir/std" "$tag"
)

verify_remote_tag_unchanged

for seed_file in "$checksum_file" "$std_checksum_file" "$seed_release_file"; do
  backup_name="$(basename "$seed_file").original"
  if ! cmp -s "$seed_file" "$work/$backup_name"; then
    die "$seed_file changed while the seed was being verified"
  fi
done

promote_file() {
  local candidate="$1"
  local target="$2"

  if cmp -s "$candidate" "$target"; then
    return
  fi
  active_stage="$(mktemp "$(dirname "$target")/.advance-seed.XXXXXX")"
  cat "$candidate" > "$active_stage"
  chmod 0644 "$active_stage"
  mv "$active_stage" "$target"
  active_stage=""
}

# The pointer moves last. SIGKILL can leave one or both future trust records,
# but never a selected seed without both; retrying recognizes matching records
# and converges. Every trappable failure restores all three original files.
promotion_started=1
promote_file "$checksum_candidate" "$checksum_file"
promote_file "$std_checksum_candidate" "$std_checksum_file"
promote_file "$seed_release_candidate" "$seed_release_file"

echo "OK: bootstrap seed advanced to $tag"
echo "  jar sha256  $jar_sha"
echo "  std sha256  $std_sha"
promotion_complete=1
