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

# The same bomb with no `cap` at all, through deflate, gzip (alone and after a
# small member) and zip, in the same heap. Version 2 of the package defaulted
# to no ceiling, and under that default every one of these is an
# OutOfMemoryError; the default ceiling has to refuse each of them and say so.
# This is the leg that goes red if the default is ever put back to `None`.
default_out="$work/bomb-default.txt"
if "$java" -Xss512m -Xmx256m -jar "$work/probe.jar" --bomb-default 512 \
    > "$default_out" 2>&1 && [ "$(tail -n 1 "$default_out")" = "mismatches 0" ]; then
  echo "PASS  the default ceiling refuses a 512MB bomb inside a 256MB heap, at every entry point"
else
  sed 's/^/  | /' "$default_out" >&2
  echo "FAIL: the default ceiling did not refuse the bomb at every entry point" >&2
  exit 1
fi

# The package fetcher, end to end, in the toolchain's own heap (#405).
#
# Everything above calls the package; this calls `dawn add`, which is where a
# hostile archive actually arrives: a `[deps]` url is fetched and unpacked
# before its d1 hash can be checked. pkgfetch hands the decompressor a byte
# ceiling, and a byte ceiling is only a memory ceiling if the heap can hold
# that many bytes in the decompressor's representation. Its tar.gz ceiling was
# 256 MiB, and a megabyte of gzipped 0xFF took the compiler down with an
# OutOfMemoryError instead of being refused; this leg is red on that tree.
#
# DAWN_JVM_OPTS is cleared so the heap is the one bin/dawn pins, which is the
# heap the promise is about. The pass condition is the ceiling's own words,
# and an OutOfMemoryError anywhere in the output is a failure even if the
# words appear too.
pkg_case() { # kind
  local kind=$1 dir="$work/pkg-$1" out
  mkdir -p "$dir/proj/src" "$dir/cache"
  printf 'schema = 1\nname = "victim"\nversion = "0.1.0"\n' > "$dir/proj/dawn.toml"
  printf 'pub fn main() -> Unit = ()\n' > "$dir/proj/src/main.dawn"
  python3 "$here/pkgbomb.py" "$kind" "$dir/bomb.$kind" 1024
  out="$dir/out.txt"
  if env -u DAWN_JVM_OPTS DAWN_PKG_CACHE="$dir/cache" \
      "$root/bin/dawn" add "file://$dir/bomb.$kind" --dir "$dir/proj" > "$out" 2>&1; then
    sed 's/^/  | /' "$out" >&2
    echo "FAIL: dawn add accepted a 1 GiB $kind bomb" >&2
    exit 1
  fi
  if grep -q 'OutOfMemoryError' "$out" || ! grep -Fq 'byte limit (stopped at' "$out"; then
    sed 's/^/  | /' "$out" | grep -v '^  | *at ' >&2
    echo "FAIL: a 1 GiB $kind bomb was not refused by pkgfetch's ceiling in the toolchain heap" >&2
    exit 1
  fi
  echo "PASS  dawn add refuses a 1 GiB $kind bomb by its ceiling, inside the toolchain heap"
}

pkg_case targz
pkg_case zip
