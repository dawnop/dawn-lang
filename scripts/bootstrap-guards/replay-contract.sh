#!/usr/bin/env bash
# Drive replay-bootstrap through fake compiler roles so its seed/std pairing is
# checked without downloading a seed or compiling the toolchain. The real replay
# is intentionally manual and expensive, but the command shape that selects the
# seed's embedded std is cheap to hold in CI.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
work="$(mktemp -d "${TMPDIR:-/tmp}/replay-contract.XXXXXX")"
trap 'rm -rf "$work"' EXIT

probe() {
  local replay_script="$1"
  local case_root="$2"
  local log="$case_root/java.log"
  local first
  local first_pwd
  local line_count
  local later

  mkdir -p "$case_root/scripts" "$case_root/bin" "$case_root/selfhost" \
    "$case_root/std" "$case_root/fake-bin" "$case_root/tmp"
  cp "$replay_script" "$case_root/scripts/replay-bootstrap.sh"
  cp "$root/scripts/seedjar.sh" "$case_root/scripts/seedjar.sh"
  printf 'fake seed\n' > "$case_root/seed.jar"
  printf 'checkout std must not reach stage 1\n' > "$case_root/std/VERSION"

  cat > "$case_root/fake-bin/java" <<'FAKE_JAVA'
#!/usr/bin/env bash
set -eu
printf '%s' "$PWD" >> "$REPLAY_JAVA_LOG"
for arg in "$@"; do printf '\t%s' "$arg" >> "$REPLAY_JAVA_LOG"; done
printf '\n' >> "$REPLAY_JAVA_LOG"
out=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ] && [ "$#" -gt 1 ]; then out=$2; break; fi
  shift
done
[ -n "$out" ]
case "$out" in
  *.jar) printf 'fake jar\n' > "$out" ;;
  *) mkdir -p "$out"; printf 'fake class\n' > "$out/main.class" ;;
esac
FAKE_JAVA
  chmod +x "$case_root/fake-bin/java"

  cat > "$case_root/bin/dawn" <<'FAKE_DAWN'
#!/usr/bin/env bash
set -eu
out=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ] && [ "$#" -gt 1 ]; then out=$2; break; fi
  shift
done
[ -n "$out" ]
mkdir -p "$out"
printf 'fake class\n' > "$out/main.class"
FAKE_DAWN
  chmod +x "$case_root/bin/dawn"

  if ! REPLAY_JAVA_LOG="$log" TMPDIR="$case_root/tmp" \
      PATH="$case_root/fake-bin:$PATH" \
      bash "$case_root/scripts/replay-bootstrap.sh" "$case_root/seed.jar" \
      > "$case_root/replay.out" 2>&1; then
    cat "$case_root/replay.out" >&2
    echo "replay contract: the fake replay did not complete" >&2
    return 1
  fi

  line_count=$(wc -l < "$log" | tr -d ' ')
  if [ "$line_count" -ne 5 ]; then
    echo "replay contract: expected five compiler calls, saw $line_count" >&2
    return 1
  fi
  first=$(sed -n '1p' "$log")
  first_pwd=$(printf '%s\n' "$first" | cut -f1)
  case "$first_pwd" in
    "$case_root/tmp"/replay-bootstrap.*/seed-stage) ;;
    *)
      echo "replay contract: stage 1 did not run in its std-free directory" >&2
      return 1
      ;;
  esac
  if printf '%s\n' "$first" | grep -F $'\t--std\t' > /dev/null; then
    echo "replay contract: stage 1 must not pass --std" >&2
    return 1
  fi
  if ! printf '%s\n' "$first" | grep -F $'\tbuild\t'"$case_root/selfhost"$'\t-o\t' > /dev/null; then
    echo "replay contract: stage 1 must name selfhost by absolute path" >&2
    return 1
  fi
  later=$(sed -n '2,5p' "$log")
  if [ "$(printf '%s\n' "$later" | grep -F -c $'\t--std\tstd')" -ne 4 ]; then
    echo "replay contract: stages after boot must use the checkout std" >&2
    return 1
  fi
}

if probe "$root/scripts/replay-bootstrap.sh" "$work/base"; then
  echo "PASS  replay stage 1 uses the seed's paired embedded std"
else
  exit 1
fi

sed 's|-o "$OUT/boot.jar" > /dev/null|-o "$OUT/boot.jar" --std "$ROOT/std" > /dev/null|' \
  "$root/scripts/replay-bootstrap.sh" > "$work/replay.current-std.sh"
if cmp -s "$root/scripts/replay-bootstrap.sh" "$work/replay.current-std.sh"; then
  echo "FAIL: replay contract mutation anchor drifted" >&2
  exit 1
fi
if ! bash -n "$work/replay.current-std.sh"; then
  echo "FAIL: replay contract mutant does not compile as shell" >&2
  exit 1
fi
if probe "$work/replay.current-std.sh" "$work/mutant" > "$work/mutant.out" 2>&1; then
  echo "FAIL: passing the checkout std to stage 1 escaped the replay contract" >&2
  exit 1
fi
if ! grep -Fx 'replay contract: stage 1 must not pass --std' "$work/mutant.out" > /dev/null; then
  echo "FAIL: the stage-1 std mutant failed for an unowned reason" >&2
  cat "$work/mutant.out" >&2
  exit 1
fi
echo "PASS  the stage-1 std mutant is owned by its exact assertion"
