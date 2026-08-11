#!/usr/bin/env bash
# Build the one JAR that release gates and release publishing share. Keeping
# the bootstrap recipe here prevents two independently green fixed points from
# consecrating different artifacts.
set -euo pipefail

usage() {
  echo "usage: $0 -o <jar>" >&2
  exit 2
}

if [ "$#" -ne 2 ] || [ "$1" != "-o" ] || [ -z "$2" ]; then
  usage
fi

caller_root="$(pwd -P)"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ROOT="$root"
export ROOT
# shellcheck disable=SC1091
. "$root/scripts/seedjar.sh"

case "$2" in
  /*) output_path="$2" ;;
  *) output_path="$caller_root/$2" ;;
esac
output_dir="$(dirname "$output_path")"
output_name="$(basename "$output_path")"
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd -P)"
output="$output_dir/$output_name"

# A failed build must not leave a stale artifact at the requested path.
rm -f "$output"
work="$(mktemp -d "$output_dir/.build-release-jar.XXXXXX")"
trap 'rm -rf "$work"' EXIT

seed="$(seed_jar)"
seed="$(cd "$(dirname "$seed")" && pwd -P)/$(basename "$seed")"
seed_std="$(seed_std_dir)"
seed_std="$(cd "$seed_std" && pwd -P)"

stage_a="$work/stage-a.jar"
stage_b="$work/stage-b.jar"
stage_c="$work/stage-c.jar"
smoke_dir="$work/smoke"
java_cmd=(java -Xss512m)
seed_args=(
  --std "$seed_std"
  --vendor org/objectweb/asm
  --vendor coursierapi
)
current_args=(
  --std std
  --vendor org/objectweb/asm
  --vendor coursierapi
)

run_release_stage() {
  local stage=$1
  shift
  if [ -z "${DAWN_INTERNAL_RELEASE_STAGE_TIMINGS:-}" ]; then
    "$@"
    return
  fi
  exec 3>&2
  {
    TIMEFORMAT="$stage"$'\t''%U'$'\t''%S'
    time "$@" 2>&3
  } 2>> "$DAWN_INTERNAL_RELEASE_STAGE_TIMINGS"
  exec 3>&-
}

if [ -n "${DAWN_INTERNAL_RELEASE_STAGE_TIMINGS:-}" ]; then
  case "$DAWN_INTERNAL_RELEASE_STAGE_TIMINGS" in
    /*) ;;
    *) echo "error: DAWN_INTERNAL_RELEASE_STAGE_TIMINGS must be absolute" >&2; exit 2 ;;
  esac
  if [ -e "$DAWN_INTERNAL_RELEASE_STAGE_TIMINGS" ]; then
    echo "error: stage timing output already exists: $DAWN_INTERNAL_RELEASE_STAGE_TIMINGS" >&2
    exit 2
  fi
  if [ ! -d "$(dirname "$DAWN_INTERNAL_RELEASE_STAGE_TIMINGS")" ]; then
    echo "error: stage timing output directory does not exist" >&2
    exit 2
  fi
  if ! (set -o noclobber; : > "$DAWN_INTERNAL_RELEASE_STAGE_TIMINGS") 2>/dev/null; then
    echo "error: cannot create stage timing output" >&2
    exit 2
  fi
fi

# Source paths are embedded in panic messages. Keep the historical canonical
# spelling `selfhost` while running from the absolute root; spelling the target
# as an absolute path would change release bytes without changing semantics.
cd "$root"
run_release_stage A "${java_cmd[@]}" -jar "$seed" build selfhost -o "$stage_a" \
  "${seed_args[@]}" > /dev/null
run_release_stage B "${java_cmd[@]}" -jar "$stage_a" build selfhost -o "$stage_b" \
  "${current_args[@]}" > /dev/null
run_release_stage C "${java_cmd[@]}" -jar "$stage_b" build selfhost -o "$stage_c" \
  "${current_args[@]}" > /dev/null
cmp "$stage_b" "$stage_c"
echo "OK: fixed point — HEAD rebuilt itself byte-identically (B == C)"

mkdir -p "$smoke_dir"
"${java_cmd[@]}" -jar "$stage_b" emit "$root/examples/projects/calc.dawn" \
  -o "$smoke_dir" > /dev/null
class_count="$(find "$smoke_dir" -name '*.class' | wc -l | tr -d '[:space:]')"
if [ "$class_count" -eq 0 ]; then
  echo "error: standalone release JAR emitted no classes" >&2
  exit 1
fi
echo "OK: standalone smoke — B emitted calc alone ($class_count classes)"

# The temporary directory is beside the destination, so this rename is the
# atomic publication of the exact B that passed both checks above.
mv "$stage_b" "$output"
if ! cmp "$output" "$stage_c"; then
  rm -f "$output"
  echo "error: promoted release JAR differs from verified stage C" >&2
  exit 1
fi
echo "OK: release JAR ready at $output"
