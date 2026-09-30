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
cp "$here/gzip_cases.dawn" "$work/src/gzip_cases.dawn"
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

# The member-framing corpus is pure Dawn, so run the exact same source through
# both backends. The Java differential above cannot do this because its oracle
# imports java.util.zip, which the native backend correctly refuses.
mkdir -p "$work/pure/src"
cp "$here/native.dawn" "$work/pure/src/main.dawn"
cp "$here/gzip_cases.dawn" "$work/pure/src/gzip_cases.dawn"
cat > "$work/pure/dawn.toml" <<TOML
schema = 1
name = "inflate_gzip_contract"

[deps]
inflate = "$root/packages/inflate"
TOML

pure_jvm="$work/pure.jvm"
"$root/bin/dawn" run "$work/pure" > "$pure_jvm"
if [ "$(tail -n 1 "$pure_jvm")" != "mismatches 0" ]; then
  cat "$pure_jvm" >&2
  echo "FAIL: gzip member boundaries failed on the JVM backend" >&2
  exit 1
fi

"$root/bin/dawn" __emitc "$work/pure" -o "$work/pure.c" > /dev/null
"${CC:-cc}" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -Wall -Wextra -Werror -Wno-unused-variable -Wno-unused-but-set-variable \
  -Wno-unused-parameter -Wno-unused-label \
  -I "$root/runtime/c" -o "$work/pure.bin" "$work/pure.c" "$root/runtime/c/dawn_rt.c" -lm
"$work/pure.bin" > "$work/pure.native"
if ! diff -u "$pure_jvm" "$work/pure.native"; then
  echo "FAIL: gzip member boundaries differ between JVM and native" >&2
  exit 1
fi
echo "PASS  gzip member boundaries agree on JVM and native"

# Every rule below has a live behavioral mutant. A mutant must compile and run;
# only the named contract failure counts as a red gate, so a stale replacement
# or an unrelated compiler error cannot masquerade as discrimination.
expect_mutant_red() { # name, expected failure label
  local name expected safe mutant
  name=$1
  expected=$2
  safe=${name//-/_}
  mutant="$work/mutant-$name"
  mkdir -p "$mutant/packages/inflate" "$mutant/project/src"
  cp -R "$root/packages/inflate/." "$mutant/packages/inflate/"
  cp "$here/native.dawn" "$mutant/project/src/main.dawn"
  cp "$here/gzip_cases.dawn" "$mutant/project/src/gzip_cases.dawn"
  cat > "$mutant/project/dawn.toml" <<TOML
schema = 1
name = "inflate_mutant_$safe"

[deps]
inflate = "$mutant/packages/inflate"
TOML
  # The anchors live in mutate.py, one registered mutation per mutant name, so
  # mutation-anchor-preflight.py proves each one matches exactly once before
  # any build, not only when this contract runs.
  python3 "$here/mutate.py" "$name" "$mutant"
  if ! "$root/bin/dawn" run "$mutant/project" > "$mutant/out" 2> "$mutant/err"; then
    cat "$mutant/err" >&2
    echo "FAIL: $name mutant did not compile and run" >&2
    exit 1
  fi
  if [ "$(tail -n 1 "$mutant/out")" = "mismatches 0" ]; then
    echo "FAIL: $name mutant stayed green" >&2
    exit 1
  fi
  if ! grep -Fq "$expected" "$mutant/out"; then
    cat "$mutant/out" >&2
    echo "FAIL: $name mutant missed its intended contract: $expected" >&2
    exit 1
  fi
  echo "PASS  $name mutant turns the gzip contract red"
}

expect_mutant_red member-loop 'concatenated members'
expect_mutant_red final-trailer 'concatenated members'
expect_mutant_red aggregate-cap 'aggregate cap is not reset'
expect_mutant_red reserved-flags 'reserved flags in later member'
expect_mutant_red fhcrc 'bad FHCRC in second member'
expect_mutant_red fhcrc-origin 'valid FHCRC in second member'

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
