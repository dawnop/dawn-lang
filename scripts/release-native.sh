#!/usr/bin/env bash
# Build the native compiler binary a release ships, and prove it is one (K-B7).
#
# Until now a release published one artifact, dawn-selfhost.jar, and running it
# needs a JVM. The native backend has compiled the whole compiler since
# 2026-07-30 (scripts/native-fixpoint.sh) and the driver grew the rest of the
# CLI over K-B2..K-B5, so there is a second thing worth handing to a consumer:
# a single self-contained executable with std and the runtime embedded, which
# is what `dawnc run hello.dawn` in an empty directory demonstrates below.
#
# Why this is a script and not eight lines inlined in release.yml: a release
# step runs on tags only, which makes it the least-executed code in the repo
# and the most likely to be broken when it finally runs. As a script,
# gates.yml runs the identical thing on every push (and hands the result to
# scripts/native-cli-diff.sh, so the binary that would be published is the one
# eight differential legs exercised), and a mutant can be pointed at it here on
# a laptop.
#
# ---- what this checks, and why each check is not implied by the one above ----
#
# A release pipeline is the purest form of "green carries no information":
# every one of these failures leaves a pipeline that reports success.
#
#   1. the file exists          -- a build step that silently did nothing, an
#                                  `|| true`, a `-o` pointing somewhere else
#   2. it runs, and says the    -- a binary that cannot start (missing shared
#      version this tree says      library, wrong architecture) answers no
#                                  differently than one nobody tried to start;
#                                  and a leftover from an earlier release is a
#                                  file like any other
#   3. it compiles and runs a   -- 1 and 2 are both satisfied by a shell script
#      program, from a bare        that echoes a version string. This is the
#      directory                   one that says the artifact is a compiler.
#   4. it emits the same C as   -- the toolchain that built it and the artifact
#      the toolchain that          agree about the compiler's own source; the
#      built it                    A == B leg of native-fixpoint.sh, which no
#                                  gate on the release path otherwise runs
#
# Check 4 is A-vs-B and therefore blind to anything that moves both sides at
# once -- a change to the driver's own source is compiled into both. Checks 2
# and 3 are the single-sided invariants that catch that class: their oracle is
# written down here, not read off the other side.
#
#   ./scripts/release-native.sh                        # build + verify
#   ./scripts/release-native.sh -o dawnc-linux-x86_64  # name the output
#   ./scripts/release-native.sh --jar dawn-selfhost.jar --expect 0.49.0
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

OUT="$ROOT/dawnc-linux-x86_64"
JAR=
EXPECT=
while [ $# -gt 0 ]; do
  case $1 in
    -o) OUT=$2; shift 2 ;;
    --jar) JAR=$2; shift 2 ;;
    --expect) EXPECT=$2; shift 2 ;;
    *) echo "usage: $0 [-o OUT] [--jar JAR] [--expect VERSION]" >&2; exit 2 ;;
  esac
done
case $OUT in /*) ;; *) OUT="$ROOT/$OUT" ;; esac

if ! command -v readelf >/dev/null 2>&1; then
  echo "error: readelf is required to verify the native release artifact" >&2
  exit 1
fi

# The version the *sources* claim, which is what the artifact has to agree
# with. release.yml passes --expect "${GITHUB_REF_NAME#v}" so the tag is held
# to it as well; the same three-way agreement release.yml already demands of
# the jar.
VERSION=$(sed -n 's/^pub const VERSION: String = "\(.*\)"$/\1/p' selfhost/src/version.dawn)
if [ -z "$VERSION" ]; then
  echo "error: cannot read VERSION from selfhost/src/version.dawn" >&2
  exit 1
fi
if [ -n "$EXPECT" ] && [ "$EXPECT" != "$VERSION" ]; then
  echo "error: --expect $EXPECT but selfhost/src/version.dawn says $VERSION" >&2
  exit 1
fi

OUT_DIR=$(dirname "$OUT")
OUT_BASE=$(basename "$OUT")
mkdir -p "$OUT_DIR"
WORK=$(mktemp -d "$OUT_DIR/.${OUT_BASE}.release-native.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
CANDIDATE_A="$WORK/candidate-a"
CANDIDATE_B="$WORK/candidate-b"

echo "building $(basename "$OUT") ($VERSION) from selfhost/src/nmain.dawn..."
if [ -n "$JAR" ]; then
  # release.yml hands us the jar it is about to publish, so the binary is that
  # jar's own output rather than a second toolchain built beside it.
  java -Xss512m -jar "$JAR" __emitc selfhost/src/nmain.dawn -o "$WORK/nmain.c"
else
  ./bin/dawn __emitc selfhost/src/nmain.dawn -o "$WORK/nmain.c"
fi

# -static because the failure it removes is invisible here: a dynamically
# linked binary built on the runner's glibc refuses to start on an older one,
# and CI's glibc is always the one it was built against, so nothing on this
# side of the release would ever see it. Measured cost on 2026-08-04: 2.9 MB ->
# 3.7 MB, link time unchanged (15.3 s both ways), zero linker warnings -- the
# runtime calls nothing that needs NSS or dlopen.
"${CC:-cc}" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread -static \
  -I "$ROOT/runtime/c" -o "$CANDIDATE_A" "$WORK/nmain.c" "$ROOT/runtime/c/dawn_rt.c" -lm
"${CC:-cc}" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread -static \
  -I "$ROOT/runtime/c" -o "$CANDIDATE_B" "$WORK/nmain.c" "$ROOT/runtime/c/dawn_rt.c" -lm

for candidate in "$CANDIDATE_A" "$CANDIDATE_B"; do
  if [ ! -s "$candidate" ] || [ ! -x "$candidate" ]; then
    echo "FAIL: $candidate was not produced (or is empty / not executable)" >&2
    exit 1
  fi
done
if ! cmp -s "$CANDIDATE_A" "$CANDIDATE_B"; then
  echo "FAIL: independent native links produced different bytes" >&2
  exit 1
fi
echo "OK   two independent native links are byte-identical"

require_elf_field() {
  local candidate="$1"
  local header="$2"
  local field="$3"
  local expected="$4"
  local actual

  actual=$(
    printf '%s\n' "$header" | awk -F: -v wanted="$field" '
      {
        name = $1
        sub(/^[[:space:]]*/, "", name)
        sub(/[[:space:]]*$/, "", name)
        if (name == wanted) {
          value = $0
          sub(/^[^:]*:[[:space:]]*/, "", value)
          sub(/[[:space:]]*$/, "", value)
          print value
          exit
        }
      }
    '
  )
  if [ "$actual" != "$expected" ]; then
    echo "FAIL: $candidate ELF $field is '$actual', expected '$expected'" >&2
    return 1
  fi
}

reject_elf_marker() {
  local candidate="$1"
  local output="$2"
  local marker="$3"

  if grep -Fq "$marker" <<<"$output"; then
    echo "FAIL: $candidate readelf output contains forbidden $marker" >&2
    return 1
  fi
}

verify_elf_contract() {
  local candidate="$1"
  local elf_header
  local program_headers
  local dynamic_section

  if ! elf_header=$(LC_ALL=C readelf -h "$candidate" 2>&1); then
    echo "FAIL: readelf could not inspect $candidate ELF header" >&2
    echo "$elf_header" >&2
    return 1
  fi
  if ! program_headers=$(LC_ALL=C readelf -l "$candidate" 2>&1); then
    echo "FAIL: readelf could not inspect $candidate program headers" >&2
    echo "$program_headers" >&2
    return 1
  fi
  if ! dynamic_section=$(LC_ALL=C readelf -d "$candidate" 2>&1); then
    echo "FAIL: readelf could not inspect $candidate dynamic section" >&2
    echo "$dynamic_section" >&2
    return 1
  fi

  require_elf_field "$candidate" "$elf_header" Class ELF64
  require_elf_field "$candidate" "$elf_header" Data "2's complement, little endian"
  require_elf_field "$candidate" "$elf_header" Machine "Advanced Micro Devices X86-64"
  reject_elf_marker "$candidate" "$program_headers" INTERP
  reject_elf_marker "$candidate" "$dynamic_section" NEEDED
}

verify_elf_contract "$CANDIDATE_A"
verify_elf_contract "$CANDIDATE_B"
echo "OK   both candidates are static little-endian ELF64 x86-64 executables"

ARTIFACT="$CANDIDATE_A"

# ---- check 1: it exists ----
# Hard exit rather than a tally: every check below reads this file.
echo "OK   the artifact exists ($(wc -c < "$ARTIFACT") bytes)"

fail=0

# ---- check 2: it runs, and it is this tree's version ----
set +e
got=$("$ARTIFACT" version 2>&1)
rc=$?
set -e
want="dawnc $VERSION (native)"
if [ "$rc" != 0 ]; then
  echo "FAIL: the artifact exited $rc instead of printing a version"
  echo "      output: $got"
  fail=1
elif [ "$got" != "$want" ]; then
  echo "FAIL: the artifact says '$got', this tree says '$want'"
  fail=1
else
  echo "OK   it runs and reports $VERSION"
fi

# ---- check 3: it is a compiler ----
# From a directory holding one .dawn file and nothing else: no std/, no
# runtime/, no repo. That is the claim the artifact makes -- both are embedded
# in it -- and it is also what separates a working binary from a file that
# merely answers `version`. Deliberately the same shape as the smoke program in
# scripts/native-fixpoint.sh; the expectation is written down, not obtained
# from the other backend.
SMOKE="$WORK/smoke"
mkdir -p "$SMOKE"
cat > "$SMOKE/hello.dawn" <<'EOF'
use std/str

pub fn main() -> Unit !io = {
  println(join(map(sort([3, 1, 2]), x => "${x}"), ","))
  println(str.to_upper("release"))
}
EOF
printf '1,2,3\nRELEASE\n' > "$WORK/smoke.expect"
set +e
(cd "$SMOKE" && "$ARTIFACT" run hello.dawn) > "$WORK/smoke.out" 2>&1
rc=$?
set -e
if [ "$rc" != 0 ]; then
  echo "FAIL: the artifact exited $rc compiling and running a one-file program"
  head -20 "$WORK/smoke.out"
  fail=1
elif ! cmp -s "$WORK/smoke.expect" "$WORK/smoke.out"; then
  echo "FAIL: the artifact ran the smoke program wrong"
  diff "$WORK/smoke.expect" "$WORK/smoke.out" | head -20 || true
  fail=1
else
  echo "OK   it built and ran a program from a bare directory (embedded std + runtime)"
fi

# ---- check 4: it agrees with the toolchain that built it ----
set +e
"$ARTIFACT" emitc "$ROOT/selfhost/src/nmain.dawn" -o "$WORK/self.c" > "$WORK/self.log" 2>&1
rc=$?
set -e
if [ "$rc" != 0 ]; then
  echo "FAIL: the artifact exited $rc emitting C for the compiler's own source"
  head -20 "$WORK/self.log"
  fail=1
elif ! cmp -s "$WORK/nmain.c" "$WORK/self.c"; then
  echo "FAIL: the artifact emits different C than the toolchain that built it"
  diff "$WORK/nmain.c" "$WORK/self.c" | head -20 || true
  fail=1
else
  echo "OK   it emits the same C as the toolchain that built it (A == B)"
fi

[ "$fail" = 0 ] || { echo "FAIL: the native release artifact did not check out"; exit 1; }

ARTIFACT_SHA=$(sha256sum "$ARTIFACT" | cut -d' ' -f1)
CHECKSUM_CANDIDATE="$WORK/$OUT_BASE.sha256"
printf '%s  %s\n' "$ARTIFACT_SHA" "$OUT_BASE" > "$CHECKSUM_CANDIDATE"

# Everything above is temporary and on the destination filesystem. This final
# rename is the first operation that touches an existing published binary, so
# any earlier failure leaves the old output and checksum untouched.
mv -f "$ARTIFACT" "$OUT"
mv -f "$CHECKSUM_CANDIDATE" "$OUT.sha256"
cat "$OUT.sha256"
echo "OK: $(basename "$OUT") is a $VERSION compiler, built and checked here"
