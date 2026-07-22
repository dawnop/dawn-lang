#!/usr/bin/env bash
# Golden diff for `selfhost run` / `selfhost test` / `selfhost doc`: stdout+
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
# resolves from that cache (it does not fetch) — outputs must still agree.
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

echo "OK: selfhost run/test/doc agree with the Kotlin CLI"
