#!/usr/bin/env bash
# Replay the bootstrap chain from a seed jar (docs/bootstrap.md, 种子推进协议).
# Manual — run before consecrating a new seed, or to prove the chain from the
# trust root (v0.6.0) still reproduces today's compiler. Not in CI.
#
#   scripts/replay-bootstrap.sh [--allow-unverified] <seed>
#     seed = a jar path, or a release tag like v0.7.0 (downloads its jar)
#
# v0.7.0 and earlier published the Kotlin `dawn.jar` and are deliberately
# absent from scripts/seed-checksums.txt, so replaying from the trust root
# needs --allow-unverified. That is the point of the flag: the replay still
# works, and it says out loud that nothing checked what it downloaded.
#
# Both seed shapes work unchanged: a Kotlin dawn.jar and a selfhost
# dawn-selfhost.jar both answer `build selfhost`, and both carry ASM — which
# since K-A7 is all the class-path tail must supply (the null adapters used to
# come from a vendored dawn.tool shim; the compiler emits them now).
# The seed must be at or above the seed floor recorded in docs/bootstrap.md
# (selfhost/src only uses features the current seed already has).
#
# Why one generation is enough: stage2 is a function of selfhost/src alone —
# any working seed compiling the same sources converges to the same bytes.
# So an old seed plus today's sources must land byte-identical to HEAD.
set -euo pipefail

if [ "${1:-}" = "--allow-unverified" ]; then
  DAWN_SEED_ALLOW_UNVERIFIED=1
  export DAWN_SEED_ALLOW_UNVERIFIED
  shift
fi
SEED_ARG=${1:?usage: replay-bootstrap.sh [--allow-unverified] <seed-jar | vX.Y.Z>}

OUT=${TMPDIR:-/tmp}/replay-bootstrap.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

# resolved against the caller's cwd, which the cd below leaves
LOCAL_SEED=$(readlink -f "$SEED_ARG" 2>/dev/null || true)

cd "$(dirname "$0")/.."
# shellcheck disable=SC2034  # read by the sourced seedjar.sh
ROOT=$(pwd)
# seed_verify and the checksum table it reads, relative to ROOT. This script's
# whole subject is the trust root, so a downloaded seed it did not check would
# be the sharpest possible place to skip the check: the chain below would then
# reproduce, byte for byte and with every "OK" printed, whatever compiler the
# download happened to be.
# shellcheck disable=SC1091
. scripts/seedjar.sh

case "$SEED_ARG" in
  v[0-9]*)
    SEED="$OUT/seed.jar"
    base="https://github.com/dawnop/dawn-lang/releases/download/$SEED_ARG"
    echo "fetching seed for $SEED_ARG ..."
    curl -fsSL -o "$SEED" "$base/dawn-selfhost.jar" 2>/dev/null \
      || curl -fsSL -o "$SEED" "$base/dawn.jar"
    # A tag with no recorded digest stops here unless --allow-unverified was
    # passed. v0.7.0 and earlier published the Kotlin `dawn.jar` and are
    # deliberately absent from scripts/seed-checksums.txt, so replaying from
    # the trust root asks for the flag — which is the difference between
    # "nothing checked this, and I meant that" and "nothing checked this".
    seed_verify "$SEED" "$SEED_ARG"
    ;;
  *)
    SEED=$LOCAL_SEED
    if [ -z "$SEED" ] || [ ! -f "$SEED" ]; then
      echo "error: seed jar not found: $SEED_ARG" >&2
      exit 2
    fi
    # The escape hatch, worded as seedjar.sh words DAWN_SEED: a jar pointed at
    # by hand is not the pinned release, so there is nothing to check it
    # against. Naming a path is already the explicit act --allow-unverified is
    # for a tag; say so rather than let it pass as if it had been verified.
    echo "warning: using local seed $SEED (unverified)" >&2
    ;;
esac
# --std std explicitly: an old seed's *default* std is its embedded copy, but
# the replay must compile today's sources against today's std
VENDOR=(--std std
  --vendor org/objectweb/asm --vendor coursierapi)

# 1) the seed compiles today's selfhost sources
java -Xss512m -jar "$SEED" build selfhost -o "$OUT/boot.jar" --std std > /dev/null
echo "seed compiled selfhost"

# 2) fixed point: boot emits selfhost, that compiler emits selfhost again —
#    byte-identical (the seed's influence is gone after one generation).
#    boot.jar comes first on the class path so its `main` wins over the seed's.
java -Xss512m -cp "$OUT/boot.jar:$SEED" main emit selfhost -o "$OUT/s2" --std std > /dev/null
java -Xss512m -cp "$OUT/s2:$SEED" main emit selfhost -o "$OUT/s3" --std std > /dev/null
diff -r "$OUT/s2" "$OUT/s3" > /dev/null || { echo "FAIL: stage3 != stage2"; exit 1; }
echo "OK: fixed point — stage2 == stage3"

# 3) standalone closure from the replayed generation
java -Xss512m -cp "$OUT/boot.jar:$SEED" main build selfhost -o "$OUT/a.jar" "${VENDOR[@]}" > /dev/null
java -Xss512m -jar "$OUT/a.jar" build selfhost -o "$OUT/b.jar" "${VENDOR[@]}" > /dev/null
cmp "$OUT/a.jar" "$OUT/b.jar"
echo "OK: standalone closure"

# 4) convergence: the replayed chain must land on exactly the bytes the
#    current toolchain (bin/dawn, built from the pinned seed) emits
./bin/dawn __emit selfhost -o "$OUT/head" > /dev/null
diff -r "$OUT/head" "$OUT/s2" > /dev/null || { echo "FAIL: replayed chain != HEAD emit"; exit 1; }
echo "OK: converges to the current compiler byte-for-byte"

echo "replay complete: $SEED_ARG is a valid seed for the current sources"
