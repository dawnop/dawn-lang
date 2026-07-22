#!/usr/bin/env bash
# Replay the bootstrap chain from a seed jar (docs/bootstrap.md, 种子推进协议).
# Manual — run before consecrating a new seed, or to prove the chain from the
# trust root (v0.6.0) still reproduces today's compiler. Not in CI.
#
#   scripts/replay-bootstrap.sh <seed>
#     seed = a jar path, or a release tag like v0.7.0 (downloads its jar)
#
# Both seed shapes work unchanged: a Kotlin dawn.jar and a selfhost
# dawn-selfhost.jar both answer `build selfhost`, and both carry ASM plus the
# dawn.tool frame-writer shim — which is all the class-path tail must supply.
# The seed must be at or above the seed floor recorded in docs/bootstrap.md
# (selfhost/src only uses features the current seed already has).
#
# Why one generation is enough: stage2 is a function of selfhost/src alone —
# any working seed compiling the same sources converges to the same bytes.
# So an old seed plus today's sources must land byte-identical to HEAD.
set -euo pipefail

SEED_ARG=${1:?usage: replay-bootstrap.sh <seed-jar | vX.Y.Z>}

OUT=${TMPDIR:-/tmp}/replay-bootstrap.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

case "$SEED_ARG" in
  v[0-9]*)
    SEED="$OUT/seed.jar"
    base="https://github.com/dawnop/dawn-lang/releases/download/$SEED_ARG"
    echo "fetching seed for $SEED_ARG ..."
    curl -fsSL -o "$SEED" "$base/dawn-selfhost.jar" 2>/dev/null \
      || curl -fsSL -o "$SEED" "$base/dawn.jar"
    ;;
  *)
    SEED="$(readlink -f "$SEED_ARG")"
    [ -f "$SEED" ] || { echo "error: seed jar not found: $SEED_ARG" >&2; exit 2; }
    ;;
esac

cd "$(dirname "$0")/.."
VENDOR=(--vendor dawn/tool --vendor org/objectweb/asm --vendor coursierapi)

# 1) the seed compiles today's selfhost sources
java -Xss512m -jar "$SEED" build selfhost -o "$OUT/boot.jar" > /dev/null
echo "seed compiled selfhost"

# 2) fixed point: boot emits selfhost, that compiler emits selfhost again —
#    byte-identical (the seed's influence is gone after one generation).
#    boot.jar comes first on the class path so its `main` wins over the seed's.
java -Xss512m -cp "$OUT/boot.jar:$SEED" main emit selfhost -o "$OUT/s2" > /dev/null
java -Xss512m -cp "$OUT/s2:$SEED" main emit selfhost -o "$OUT/s3" > /dev/null
diff -r "$OUT/s2" "$OUT/s3" > /dev/null || { echo "FAIL: stage3 != stage2"; exit 1; }
echo "OK: fixed point — stage2 == stage3"

# 3) standalone closure from the replayed generation
java -Xss512m -cp "$OUT/boot.jar:$SEED" main build selfhost -o "$OUT/a.jar" "${VENDOR[@]}" > /dev/null
java -Xss512m -jar "$OUT/a.jar" build selfhost -o "$OUT/b.jar" "${VENDOR[@]}" > /dev/null
cmp "$OUT/a.jar" "$OUT/b.jar"
echo "OK: standalone closure"

# 4) convergence: if the current toolchain is built, the replayed chain must
#    land on exactly its bytes
if [ -f compiler/build/libs/dawn.jar ]; then
  ./bin/dawn __emit selfhost -o "$OUT/head" > /dev/null
  diff -r "$OUT/head" "$OUT/s2" > /dev/null || { echo "FAIL: replayed chain != HEAD emit"; exit 1; }
  echo "OK: converges to the current compiler byte-for-byte"
fi

echo "replay complete: $SEED_ARG is a valid seed for the current sources"
