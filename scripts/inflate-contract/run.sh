#!/usr/bin/env bash
# Differential test for packages/inflate against java.util.zip.
#
#   ./scripts/inflate-contract/run.sh
#
# Java compresses, Dawn decompresses. That direction is the point: a round
# trip through one implementation proves only that it agrees with itself, and
# what has to hold is that this reads archives someone else wrote.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/inflate-contract"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/src"
cp "$here/probe.dawn" "$work/src/main.dawn"
cat > "$work/dawn.toml" <<TOML
schema = 1
name = "inflate_contract"

[deps]
inflate = "$root/packages/inflate"
TOML

# a real source file: hundreds of KB of text, which is what makes the level
# 6/9 cases dynamic-Huffman rather than a toy
out="$("$root/bin/dawn" run "$work" -- "$root/selfhost/src/check/types.dawn")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: packages/inflate disagrees with java.util.zip" >&2
  exit 1
fi

echo "PASS  packages/inflate reads what java.util.zip writes"

# The compression bomb, in a heap far smaller than the expansion.
#
# A ceiling is only a ceiling if it binds before the memory is spent, and
# nothing about the *answer* can tell the two apart: a limit applied to the
# finished output refuses exactly the same streams, having built them first.
# What tells them apart is the heap. 512MB of expansion against a 256MB heap
# is an OutOfMemoryError for the second and a refusal for the first, so this
# leg is the one that would go red if the check moved back out of the loop.
#
# The bomb is built by Deflater, a megabyte at a time and drained as it goes,
# so the process that makes it never holds the expansion either.
#
# Built to a jar and launched directly, because `dawn run` forks a second JVM
# for the program and DAWN_JVM_OPTS reaches only the compiler's. Pointing the
# heap flag at the wrong process is how this leg first "passed" against a
# deliberately broken ceiling.
bomb_out="$work/bomb.txt"
java=java
if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/java" ]; then
  java="$JAVA_HOME/bin/java"
fi
"$root/bin/dawn" build "$work" -o "$work/probe.jar" > /dev/null
if "$java" -Xss512m -Xmx256m -jar "$work/probe.jar" --bomb 512 \
    > "$bomb_out" 2>&1 && [ "$(tail -n 1 "$bomb_out")" = "mismatches 0" ]; then
  echo "PASS  a 512MB compression bomb is refused inside a 256MB heap"
else
  sed 's/^/  | /' "$bomb_out" >&2
  echo "FAIL: the output ceiling did not bind before the memory was spent" >&2
  exit 1
fi
