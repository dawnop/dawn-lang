#!/usr/bin/env bash
# Golden diff for `selfhost run/test/doc/add/__pkghash`: stdout+
# stderr and exit codes must match the Kotlin CLI — including the failing-test
# report shape and the doc JSON byte for byte.
set -euo pipefail
cd "$(dirname "$0")/.."

DAWN=${DAWN_BIN:-./bin/dawn}
OUT=${TMPDIR:-/tmp}/selfhost-run-diff.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

"$DAWN" build selfhost -o "$OUT/selfhost.jar" > /dev/null
SH=(java -Xss512m -cp "$OUT/selfhost.jar:compiler/build/libs/dawn.jar" main)

check() { # name kotlin-exit dawn-exit
  if [ "$2" != "$3" ]; then echo "FAIL: $1 exit codes differ ($2 vs $3)"; exit 1; fi
  if ! diff "$OUT/k.txt" "$OUT/d.txt"; then echo "FAIL: $1 output differs"; exit 1; fi
  echo "OK   $1"
}

# run: with and without args (the no-args calc usage path exits 1)
"$DAWN" run examples/calc.dawn "1 + 2 * 3" > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" run examples/calc.dawn "1 + 2 * 3" > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "run calc (args)" "$k" "$d"

"$DAWN" run examples/calc.dawn > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" run examples/calc.dawn > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "run calc (usage)" "$k" "$d"

# test: a green multi-module suite
"$DAWN" test site > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" test site > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "test site" "$k" "$d"

# test: a project consuming [deps] source packages (the selfhost package loader)
"$DAWN" test playground > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" test playground > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "test playground (with [deps])" "$k" "$d"

# test: a `[deps.<alias>]` url dependency from a file:// zip. The Kotlin run
# fetches and verifies into a fresh content-addressed cache; the selfhost run
# resolves from that warm cache — outputs must still agree.
PKG="$OUT/greeter-src"
mkdir -p "$PKG/src"
printf 'schema = 1\nname = "greeter"\nversion = "1.0.0"\n' > "$PKG/dawn.toml"
cat > "$PKG/src/hello.dawn" <<'EOF'
pub fn greet(who: String) -> String = "hello, " ++ who

test "greets" {
  assert greet("x") == "hello, x"
}
EOF
HASH=$("$DAWN" __pkghash "$PKG")
python3 - "$PKG" "$OUT/greeter.zip" <<'EOF'
import os, sys, zipfile
src, dst = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(dst, 'w') as z:
    for root, _, files in os.walk(src):
        for f in sorted(files):
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, src))
EOF
APP="$OUT/urlapp"
mkdir -p "$APP/src"
# the dep is consumed under an alias (`g`) that differs from its real name
# (`greeter`) — both compilers must canonicalize imports to the real name
cat > "$APP/dawn.toml" <<EOF
schema = 1
name = "urlapp"

[deps.g]
url = "file://$OUT/greeter.zip"
version = "1.0.0"
hash = "$HASH"
EOF
cat > "$APP/src/main.dawn" <<'EOF'
use g/hello

pub fn main() -> Unit !io = println(hello.greet("packages"))

test "the url dependency is linked" {
  assert hello.greet("a") == "hello, a"
}
EOF
export DAWN_PKG_CACHE="$OUT/pkgcache"
"$DAWN" test "$APP" > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" test "$APP" > "$OUT/d.txt" 2>&1 && d=0 || d=$?
unset DAWN_PKG_CACHE
check "test url dep (aliased; fetched cache, selfhost reads it)" "$k" "$d"

# the same url dep from a cold cache: the selfhost toolchain fetches and
# verifies it itself now (M8 phase 2), no Kotlin pre-seeding
export DAWN_PKG_CACHE="$OUT/pkgcache-cold"
"${SH[@]}" test "$APP" > "$OUT/d.txt" 2>&1 && d=0 || d=$?
unset DAWN_PKG_CACHE
check "test url dep (selfhost fetches a cold cache)" "$k" "$d"

# __pkghash: the d1 canonical tree hash, success and error paths
"$DAWN" __pkghash "$PKG" > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" __pkghash "$PKG" > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "__pkghash" "$k" "$d"

"$DAWN" __pkghash "$OUT/nowhere" > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" __pkghash "$OUT/nowhere" > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "__pkghash (error path)" "$k" "$d"

# add: run both sides against the same project path so summaries match byte
# for byte, and require the edited manifest to come out identical too
ADDT="$OUT/add-template"
mkdir -p "$ADDT/src"
printf '# my app\nschema = 1\nname = "app"   # keep\n' > "$ADDT/dawn.toml"
printf 'pub fn main() -> Unit !io = println("x")\n' > "$ADDT/src/main.dawn"
PROJ="$OUT/addproj"

add_pair() { # label spec...
  label=$1; shift
  rm -rf "$PROJ"; cp -r "$ADDT" "$PROJ"
  DAWN_PKG_CACHE="$OUT/pkgcache-add-k" "$DAWN" add "$@" --dir "$PROJ" > "$OUT/k.txt" 2>&1 && k=0 || k=$?
  cp "$PROJ/dawn.toml" "$OUT/k.toml"
  rm -rf "$PROJ"; cp -r "$ADDT" "$PROJ"
  DAWN_PKG_CACHE="$OUT/pkgcache-add-d" "${SH[@]}" add "$@" --dir "$PROJ" > "$OUT/d.txt" 2>&1 && d=0 || d=$?
  if ! diff "$OUT/k.toml" "$PROJ/dawn.toml"; then echo "FAIL: $label manifests differ"; exit 1; fi
  check "$label" "$k" "$d"
}

add_pair "add (local path dep)" "../greeter-src"
add_pair "add (maven coordinate)" "org.ow2.asm:asm:9.7.1"
add_pair "add (url dep, aliased)" "file://$OUT/greeter.zip" --as g
add_pair "add (bad coordinate errors)" "a::c"

# test: the failing path (report shape, message indentation, exit 1)
cat > "$OUT/failing.dawn" <<'EOF'
fn double(x: Int) -> Int = x * 2

test "doubling four" {
  assert double(4) == 8
}

test "a deliberate failure" {
  assert double(3) == 7
}
EOF
"$DAWN" test "$OUT/failing.dawn" > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" test "$OUT/failing.dawn" > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "test failing fixture" "$k" "$d"

# doc: the builtin reference and a project with types, traits and impls
"$DAWN" doc --builtins > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" doc --builtins > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "doc --builtins" "$k" "$d"

"$DAWN" doc site > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" doc site > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "doc site" "$k" "$d"

"$DAWN" doc examples/traits.dawn > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" doc examples/traits.dawn > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "doc traits example" "$k" "$d"

echo "OK: selfhost run/test/doc/add/__pkghash agree with the Kotlin CLI"
