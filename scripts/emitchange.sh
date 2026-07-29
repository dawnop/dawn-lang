# Scoped Emit-Change declarations (REL-02), sourced by the differential
# scripts. One unscoped `Emit-Change:` line used to exempt every target's
# arbitrary diff at once — with two backends and half a dozen corpora that
# says nothing about what was approved. A declaration now names what it
# covers:
#
#   Emit-Change(emit packages/json): errors carry offsets
#   Emit-Change(run calc*): usage line reworded
#   Emit-Change(*): the jar layout changed wholesale
#
# The scope is a shell glob matched against the check label the differential
# prints ("emit selfhost", "run calc (args)", "fmt backend-dawn", ...). A bare
# `Emit-Change:` with no scope keeps the old wildcard meaning, so history and
# muscle memory stay valid — but the scripts print which declaration covered
# which diff, and an over-broad one is visible in review.

# Every declaration since the seed tag that covers this check label.
declared_for() { # label
  local label="$1" tag line scope
  tag=$(tr -d ' \n' < "$(git rev-parse --show-toplevel)/scripts/seed-release.txt")
  git log "$tag..HEAD" --format=%B 2>/dev/null \
    | grep -E '^Emit-Change(\([^)]*\))?:' \
    | while IFS= read -r line; do
        scope=$(printf '%s' "$line" | sed -n 's/^Emit-Change(\([^)]*\)):.*/\1/p')
        if [ -z "$scope" ]; then
          # unscoped: the historical wildcard
          printf '%s\n' "$line"
        else
          # shellcheck disable=SC2254
          case "$label" in
            $scope) printf '%s\n' "$line" ;;
          esac
        fi
      done
}
