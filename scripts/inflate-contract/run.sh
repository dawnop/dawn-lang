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
mutate() { # file, old, new
  python3 - "$1" "$2" "$3" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
old, new = sys.argv[2], sys.argv[3]
text = path.read_text()
if text.count(old) != 1:
    raise SystemExit(f"mutation anchor occurs {text.count(old)} times in {path}: {old!r}")
path.write_text(text.replace(old, new))
PY
}

expect_mutant_red() { # name, source file, old, new, expected failure label
  local name source old new expected safe mutant
  name=$1
  source=$2
  old=$3
  new=$4
  expected=$5
  safe=${name//-/_}
  mutant="$work/mutant-$name"
  mkdir -p "$mutant/inflate" "$mutant/project/src"
  cp -R "$root/packages/inflate/." "$mutant/inflate/"
  cp "$here/native.dawn" "$mutant/project/src/main.dawn"
  cp "$here/gzip_cases.dawn" "$mutant/project/src/gzip_cases.dawn"
  cat > "$mutant/project/dawn.toml" <<TOML
schema = 1
name = "inflate_mutant_$safe"

[deps]
inflate = "$mutant/inflate"
TOML
  mutate "$mutant/inflate/src/$source" "$old" "$new"
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

expect_mutant_red member-loop gzip.dawn \
  'while cursor < n {' 'if cursor < n {' 'concatenated members'
expect_mutant_red final-trailer gzip.dawn \
  'let trailer = deflate_end' 'let trailer = bytes.len(src) - 8' 'concatenated members'
expect_mutant_red aggregate-cap gzip.dawn \
  'Some(lim - bytes.size(out))' 'Some(lim)' 'aggregate cap is not reset'
expect_mutant_red reserved-flags gzip.dawn \
  'if flags & RESERVED != 0 {' 'if false {' 'reserved flags in later member'
expect_mutant_red fhcrc gzip.dawn \
  'if got != want {' 'if false {' 'bad FHCRC in second member'
expect_mutant_red fhcrc-origin gzip.dawn \
  'bytes.slice(src, start, i)' 'bytes.slice(src, 0, i)' 'valid FHCRC in second member'

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
