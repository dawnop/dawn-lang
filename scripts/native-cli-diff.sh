#!/usr/bin/env bash
# The second-backend differential for the driver's shared subcommands (K-B2).
#
# Why it exists: `selfhost-fmt-diff.sh` and `selfhost-run-diff.sh` were read as
# "the formatter/CLI is checked", and they are — on the JVM. Both hardcoded
# ./bin/dawn as the toolchain under test, so no native binary was ever
# executed by either. Wiring fmt/doc/add into selfhost/src/nmain.dawn does not
# by itself put them under a gate; this script is what does.
#
# Two legs, two different oracles:
#
#   fmt   the N-1 release, by running selfhost-fmt-diff.sh with DAWN_SELF
#         pointed at the native binary. Same corpus (327 tracked .dawn files
#         plus mangled copies), same oracle, other backend.
#   doc   HEAD's JVM driver, byte for byte. There is no N-1 native driver to
#   add   diff against — these subcommands did not exist on this backend
#         before — and the JVM side is itself pinned to N-1 by
#         selfhost-run-diff.sh, so the chain is native == JVM == N-1.
#
# The doc/add legs have no Emit-Change escape hatch on purpose. An
# Emit-Change declares an intended change *over time*; a disagreement between
# two backends at the same commit is a bug in one of them, and there is no
# version of this repository in which it is approved.
#
# The corpus is deliberately free of `use java`: the native driver refuses it
# (jsig_refused), so `doc site` is not a divergence but the documented answer.
#
#   ./scripts/native-cli-diff.sh              # builds the native driver
#   DAWNC_BIN=/path/to/dawnc ./scripts/native-cli-diff.sh   # reuse one
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

OUT=${TMPDIR:-/tmp}/native-cli-diff.$$
mkdir -p "$OUT"
if [ -z "${KEEP:-}" ]; then trap 'rm -rf "$OUT"' EXIT; fi

# the JVM driver is both the reference for doc/add and the compiler that
# produces the native one, so build it first and keep rebuild chatter out of
# the transcripts below
./bin/dawn --version > /dev/null

DAWNC=${DAWNC_BIN:-}
if [ -z "$DAWNC" ]; then
  echo "building the native driver from selfhost/src/nmain.dawn..."
  ./bin/dawn __emitc selfhost/src/nmain.dawn -o "$OUT/nmain.c"
  "${CC:-cc}" -std=c11 -O2 -fwrapv -fno-strict-aliasing -pthread -I "$ROOT/runtime/c" \
    -o "$OUT/dawnc" "$OUT/nmain.c" "$ROOT/runtime/c/dawn_rt.c" -lm
  DAWNC="$OUT/dawnc"
fi
# an absolute path: the add leg runs both drivers with a --dir elsewhere, and
# a relative one would resolve against the wrong place if that ever changes
case "$DAWNC" in /*) ;; *) DAWNC="$ROOT/$DAWNC" ;; esac

fail=0

## Run the same argv through both drivers; stdout, stderr and the exit code
## must agree.
pair() { # label args...
  label=$1; shift
  ./bin/dawn "$@" > "$OUT/j.txt" 2>&1 && j=0 || j=$?
  "$DAWNC" "$@" > "$OUT/n.txt" 2>&1 && n=0 || n=$?
  if [ "$j" != "$n" ] || ! diff "$OUT/j.txt" "$OUT/n.txt" > "$OUT/d.txt"; then
    echo "FAIL: $label differs between backends (exits jvm=$j native=$n)"
    head -20 "$OUT/d.txt"
    fail=1
  else
    echo "OK   $label (exit $j)"
  fi
}

# ---- leg 1: fmt, against the previous release ----
echo "== fmt vs N-1, native backend =="
DAWN_SELF="$DAWNC" ./scripts/selfhost-fmt-diff.sh

# `fmt --check` is a transcript, not a tree: it prints the unformatted files.
# Their order comes from a directory walk, and io.list_dir does not return the
# same order on both backends (#114) — the drivers sort, and this is what says
# so. A directory of deliberately mangled sources makes the list non-empty.
CHK="$OUT/fmtcheck"
mkdir -p "$CHK/b/c"
i=0
while IFS= read -r f; do
  i=$((i + 1))
  if [ "$i" -gt 24 ]; then break; fi
  case $((i % 3)) in
    0) d="$CHK" ;;
    1) d="$CHK/b" ;;
    *) d="$CHK/b/c" ;;
  esac
  sed -e 's/^[[:space:]]*//' -e 's/   */ /g' "$f" > "$d/$i.dawn"
done < <(git ls-files 'selfhost/src/*.dawn')
pair "fmt --check (walk order)" fmt --check "$CHK"
pair "fmt --check (a clean file)" fmt --check "$ROOT/selfhost/src/version.dawn"

# ---- leg 2: doc, against HEAD's JVM driver ----
echo "== doc, JVM vs native =="
pair "doc --builtins" doc --builtins
pair "doc --stdlib" doc --stdlib
pair "doc (traits example)" doc examples/traits.dawn
pair "doc (multi-module project)" doc packages/json
pair "doc (single-module package)" doc packages/sha2

# a pub effect and its operations reach the JSON; a private one does not (#115)
cat > "$OUT/effects_doc.dawn" <<'EOF'
## Answer questions from ambient context.
pub effect Ask {
  ## The context's number.
  fn ask(prompt: String) -> Int
  fn tell(n: Int) -> Unit
}

effect Hidden {
  fn peek() -> Int
}

pub fn main() -> Unit !io = println("ok")
EOF
pair "doc (pub effect)" doc "$OUT/effects_doc.dawn"

# error paths: usage, missing target, compile errors (no count line), and a
# manifest the loader rejects
cat > "$OUT/broken.dawn" <<'EOF'
fn f(x: Int) -> String = x + 1

pub fn main() -> Unit !io = {
  let y = undefined_fn(2)
  println(f(3))
}
EOF
BADMF="$OUT/badmf"
mkdir -p "$BADMF/src"
printf 'name = "x"\nschema = 1\nweird = true\n\n[stuff]\na = 1.5\n' > "$BADMF/dawn.toml"
printf 'pub fn main() -> Unit !io = println("hi")\n' > "$BADMF/src/main.dawn"
pair "doc (usage)" doc
pair "doc (missing target)" doc "$OUT/nowhere"
pair "doc (compile errors)" doc "$OUT/broken.dawn"
pair "doc (manifest diagnostics)" doc "$BADMF"
pair "fmt (missing target)" fmt "$OUT/nowhere"
pair "fmt (usage)" fmt

# ---- leg 3: add, against HEAD's JVM driver ----
# Both sides edit a fresh copy of the same project, so the summary line and
# the rewritten dawn.toml must both come out identical.
echo "== add, JVM vs native =="
PKG="$OUT/greeter-src"
mkdir -p "$PKG/src"
printf 'schema = 1\nname = "greeter"\nversion = "1.0.0"\n' > "$PKG/dawn.toml"
cat > "$PKG/src/hello.dawn" <<'EOF'
pub fn greet(who: String) -> String = "hello, " ++ who
EOF
HASH=$(./bin/dawn __pkghash "$PKG")
python3 - "$PKG" "$OUT/greeter.zip" <<'EOF'
import os, sys, zipfile
src, dst = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(dst, 'w') as z:
    for root, _, files in os.walk(src):
        for f in sorted(files):
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, src))
EOF

ADDT="$OUT/add-template"
mkdir -p "$ADDT/src"
printf '# my app\nschema = 1\nname = "app"   # keep\n' > "$ADDT/dawn.toml"
printf 'pub fn main() -> Unit !io = println("x")\n' > "$ADDT/src/main.dawn"
PROJ="$OUT/addproj"

add_pair() { # label spec...
  label=$1; shift
  rm -rf "$PROJ"; cp -r "$ADDT" "$PROJ"
  DAWN_PKG_CACHE="$OUT/pkgcache-j" ./bin/dawn add "$@" --dir "$PROJ" > "$OUT/j.txt" 2>&1 && j=0 || j=$?
  cp "$PROJ/dawn.toml" "$OUT/j.toml"
  rm -rf "$PROJ"; cp -r "$ADDT" "$PROJ"
  DAWN_PKG_CACHE="$OUT/pkgcache-n" "$DAWNC" add "$@" --dir "$PROJ" > "$OUT/n.txt" 2>&1 && n=0 || n=$?
  if ! diff "$OUT/j.toml" "$PROJ/dawn.toml" > "$OUT/t.txt"; then
    echo "FAIL: $label rewrote dawn.toml differently"
    head -20 "$OUT/t.txt"
    fail=1
  fi
  if [ "$j" != "$n" ] || ! diff "$OUT/j.txt" "$OUT/n.txt" > "$OUT/d.txt"; then
    echo "FAIL: $label differs between backends (exits jvm=$j native=$n)"
    head -20 "$OUT/d.txt"
    fail=1
  else
    echo "OK   $label (exit $j)"
  fi
}

add_pair "add (local path dep)" "$PKG"
add_pair "add (maven coordinate)" "org.ow2.asm:asm:9.7.1"
# the url dep exercises curl, the zip reader and the d1 hash on both backends
add_pair "add (url dep, aliased)" "file://$OUT/greeter.zip" --as g
add_pair "add (bad coordinate)" "a::c"
add_pair "add (usage)" --as g

BADTOML="$OUT/badtoml"
mkdir -p "$BADTOML/src"
printf 'schema = 1\nname = "x\nver = 1.5.2\n' > "$BADTOML/dawn.toml"
printf 'pub fn main() -> Unit !io = println("hi")\n' > "$BADTOML/src/main.dawn"
pair "add (invalid manifest)" add ../nowhere --dir "$BADTOML"

[ "$fail" = 0 ] || { echo "FAIL: the native driver and the JVM driver disagree"; exit 1; }
echo "OK: fmt/doc/add agree across both backends, and native fmt matches the previous release"
