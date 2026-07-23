#!/bin/sh
# SAM-conversion spike: generate SpikeSam.class with ASM, run the driver on the
# JVM and as a native-image binary, diff the outputs. See SamGen.java for what
# is under test. Uses the selfhost standalone jar (build/dawn-selfhost.jar,
# built by ./bin/dawn) for ASM — it vendors org.objectweb.asm.
set -e
cd "$(dirname "$0")"

ROOT=$(cd ../.. && pwd)
JAR="$ROOT/build/dawn-selfhost.jar"
[ -f "$JAR" ] || { echo "missing $JAR (run: ./bin/dawn --version)"; exit 2; }

if [ -z "$JAVA_HOME" ]; then
  for d in "$HOME"/tools/graalvm-*/Contents/Home; do
    [ -x "$d/bin/java" ] && JAVA_HOME="$d" && break
  done
fi
export JAVA_HOME
PATH="$JAVA_HOME/bin:$PATH"

OUT=build
rm -rf "$OUT" && mkdir -p "$OUT"

javac -cp "$JAR" -d "$OUT" SamGen.java
java -cp "$JAR:$OUT" SamGen "$OUT"
javac -cp "$OUT" -d "$OUT" SpikeMain.java

echo "== JVM =="
java -cp "$OUT" SpikeMain | tee "$OUT/jvm.out"

echo "== native-image =="
native-image --no-fallback -cp "$OUT" -o "$OUT/spikemain" SpikeMain
"$OUT/spikemain" | tee "$OUT/native.out"

diff "$OUT/jvm.out" "$OUT/native.out" && echo "SPIKE OK: JVM and native outputs identical"
