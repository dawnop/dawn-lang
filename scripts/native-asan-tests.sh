#!/usr/bin/env bash
# std's and the packages' own test blocks, on the native backend, built with
# AddressSanitizer, LeakSanitizer and UndefinedBehaviorSanitizer.
#
# Why this exists: every package suite ran on the JVM and only the JVM
# (scripts/package-tests.sh calls `./bin/dawn test`), and std's ran natively
# only without a sanitizer (native-cli-diff.sh's `test --stdlib` pair). Two
# shipped bugs went through exactly that gap: #9, emitted C that did not
# compile for tea-core's tests, and #237, a read_file failure branch that
# leaked its buffer on every native `test --stdlib`. Neither needed a new
# test to be caught, only the existing tests run on the other backend with the
# memory checker on (research-bug-rate report, section 7.4).
#
# Why a script of its own rather than a mode of package-tests.sh or
# native-selfhost-tests.sh: both are push gates, and scripts/gate-map derives
# what a gate watches from the text of its script. Teaching either of them the
# native driver's recipe (nmain.dawn, runtime/c) would put that push job on
# every compiler and runtime change, which is the push-total cost this leg is
# kept out of. It runs from nightly.yml. Discovery is the same as
# package-tests.sh's: every packages/*/dawn.toml, no list to forget to extend.
#
# The sanitizers reach cc through a wrapper named in CC. `dawnc test` builds
# the test binary with one fixed command line (nmain.dawn, cc_build_with) and
# reads only CC, so the wrapper appends the sanitizer flags to that line
# instead of the driver growing a flag nothing else wants. The wrapper also
# logs each call, and a unit whose run did not go through it is a failure: a
# green that never reached the sanitizer would say nothing about memory.
#
# Leak detection is on. A Dawn program's heap is reference counted down to
# zero at exit (docs/perceus-design.md), so a leak report is a bug, not noise;
# that is the same position scripts/spike-native/run.sh takes for its corpus.
#
#   ./scripts/native-asan-tests.sh                      # builds the native driver
#   DAWNC_BIN=/path/to/dawnc ./scripts/native-asan-tests.sh   # reuse one
#   ./scripts/native-asan-tests.sh packages/json std    # only these units
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

# Packages the native backend cannot build, with the reason. Each reason is
# rechecked below: an entry whose package no longer has a `use java` is stale
# and fails the run, so the table cannot outlive what it excuses.
declare -A EXCLUDED=(
  [packages/web]="use java: the HTTP server and client are java.net and com.sun.net.httpserver, and the native backend refuses use java (jsig_refused)"
)

# Units with a leak that is known and not yet fixed. The unit still runs with
# leak detection on, and passes only if the run is red for a LeakSanitizer
# report and nothing else: every test passed, no other sanitizer spoke. A run
# that comes back clean fails too, so the entry is removed with the fix.
declare -A KNOWN_LEAKS=()

OUT=$(mktemp -d "${TMPDIR:-/tmp}/native-asan-tests.XXXXXX")
if [ -z "${KEEP:-}" ]; then trap 'rm -rf "$OUT"' EXIT; fi

CC_REAL=${CC:-cc}

# Fail closed on a compiler that cannot sanitize, as spike-native does: a run
# that silently built unsanitized binaries would be green about nothing.
printf 'int main(void) { return 0; }\n' > "$OUT/probe.c"
if ! "$CC_REAL" -fsanitize=address,undefined -o "$OUT/probe" "$OUT/probe.c" \
  > "$OUT/probe.err" 2>&1 || ! "$OUT/probe"; then
  cat "$OUT/probe.err" >&2
  echo "FAIL: $CC_REAL cannot build and run with -fsanitize=address,undefined" >&2
  exit 1
fi

DAWNC=${DAWNC_BIN:-}
if [ -z "$DAWNC" ]; then
  # keep the toolchain's rebuild chatter out of the build below
  ./bin/dawn --version > /dev/null
  echo "building the native driver from selfhost/src/nmain.dawn..."
  ./bin/dawn __emitc selfhost/src/nmain.dawn -o "$OUT/nmain.c"
  # the driver itself is not under test here, so it is built the plain way
  "$CC_REAL" -std=c11 -Wno-parentheses-equality -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -I "$ROOT/runtime/c" \
    -o "$OUT/dawnc" "$OUT/nmain.c" "$ROOT/runtime/c/dawn_rt.c" -lm
  DAWNC="$OUT/dawnc"
fi
case "$DAWNC" in /*) ;; *) DAWNC="$ROOT/$DAWNC" ;; esac

# -g and frame pointers so a report names the Dawn function; the driver's own
# -O2 stays in front. -fno-sanitize-recover makes undefined behaviour exit
# non-zero instead of printing and carrying on to a green exit code.
cat > "$OUT/sancc" <<EOF
#!/bin/sh
echo "\$*" >> "$OUT/cc.log"
exec "$CC_REAL" "\$@" -g -fno-omit-frame-pointer \\
  -fsanitize=address,undefined -fno-sanitize-recover=undefined
EOF
chmod +x "$OUT/sancc"
: > "$OUT/cc.log"

units=()
if [ "$#" -gt 0 ]; then
  units=("$@")
else
  units+=(std)
  for m in packages/*/dawn.toml; do
    [ -e "$m" ] || continue
    units+=("$(dirname "$m")")
  done
  if [ "${#units[@]}" -lt 6 ]; then
    echo "FAIL: found only $((${#units[@]} - 1)) package(s) under packages/; the tree cannot have shrunk that far" >&2
    exit 1
  fi
fi

fail=0
for u in "${!EXCLUDED[@]}"; do
  if ! grep -rqE '^\s*use java' "$u"; then
    echo "FAIL: $u is excluded for use java, and has none any more; remove its entry" >&2
    fail=1
  fi
done

ran=0
for u in "${units[@]}"; do
  if [ -n "${EXCLUDED[$u]:-}" ]; then
    echo "== $u: excluded (${EXCLUDED[$u]})"
    continue
  fi
  echo "== $u"
  log="$OUT/$(echo "$u" | tr / _).log"
  before=$(wc -l < "$OUT/cc.log")
  args=("$u")
  if [ "$u" = std ]; then args=(--stdlib); fi
  rc=0
  # `dawnc test` runs from the repository root: some std tests read paths
  # relative to it, as native-selfhost-tests.sh notes.
  CC="$OUT/sancc" ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=print_stacktrace=1 \
    "$DAWNC" test "${args[@]}" > "$log" 2>&1 || rc=$?
  ran=$((ran + 1))
  if [ "$(wc -l < "$OUT/cc.log")" -le "$before" ]; then
    cat "$log"
    if [ "$rc" != 0 ]; then
      echo "FAIL: $u: dawnc test exited $rc before it reached cc" >&2
    else
      echo "FAIL: $u: the test binary was not built through the sanitizing cc" >&2
    fi
    fail=1
    continue
  fi
  if [ -n "${KNOWN_LEAKS[$u]:-}" ]; then
    if [ "$rc" = 0 ]; then
      tail -3 "$log"
      echo "FAIL: $u is listed as a known leak and ran clean; remove its entry" >&2
      fail=1
    elif grep -q 'ERROR: LeakSanitizer' "$log" &&
      grep -q 'test(s) passed$' "$log" &&
      ! grep -Eq 'ERROR: AddressSanitizer|runtime error:' "$log"; then
      echo "known leak, still present: ${KNOWN_LEAKS[$u]}"
      grep 'SUMMARY:' "$log" || true
    else
      cat "$log"
      echo "FAIL: $u: red for more than its known leak" >&2
      fail=1
    fi
    continue
  fi
  if [ "$rc" != 0 ]; then
    cat "$log"
    echo "FAIL: $u: native tests under ASan/UBSan exited $rc" >&2
    fail=1
  else
    tail -1 "$log"
  fi
done

if [ "$fail" != 0 ]; then
  echo "FAIL: a unit's native test blocks did not pass under the sanitizers" >&2
  exit 1
fi
echo "OK: $ran unit(s) run natively under ASan+UBSan, ${#EXCLUDED[@]} excluded by reason"
