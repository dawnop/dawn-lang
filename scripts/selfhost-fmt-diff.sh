#!/usr/bin/env bash
# Differential for the formatter against the previous release (the N-1 oracle
# since kotlin-final): HEAD `dawn fmt` must agree byte for byte — over the
# already-formatted corpus (the fixed point) and over mangled copies (leading
# indentation stripped, intra-line space runs squeezed), which exercise real
# reflow work. An intentional formatter change lands with an `Emit-Change:`
# line in its commit message.
#
# `DAWN_SELF` names the toolchain under test; it defaulted to ./bin/dawn with
# no way to say otherwise, so this gate only ever saw the JVM backend. The
# native driver grew `fmt` in K-B2 and scripts/native-cli-diff.sh runs this
# same script with DAWN_SELF pointed at the native binary — which is what
# makes the oracle cover both backends rather than one.
#
# The differential domain is the live path intersection of HEAD and N-1. A
# file introduced with new syntax has no N-1 formatting answer, and a deleted
# file has no HEAD bytes; both path differences are counted and reported rather
# than copied, silently skipped, or replaced with an empty shell. Existing
# paths modified to use new syntax remain in the intersection and still turn
# the gate red.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
. scripts/seedjar.sh
TAG=$(tr -d ' \n' < scripts/seed-release.txt)

OUT=${TMPDIR:-/tmp}/selfhost-fmt-diff.$$
mkdir -p "$OUT/k" "$OUT/d"
trap 'rm -rf "$OUT"' EXIT

SEEDJAR="$(seed_jar)"
printf '#!/bin/sh\nexec java -Xss512m -jar "%s" "$@"\n' "$SEEDJAR" > "$OUT/seed-cli"
chmod +x "$OUT/seed-cli"
DAWN=${DAWN_BIN:-"$OUT/seed-cli"}
SELF=${DAWN_SELF:-./bin/dawn}
./bin/dawn --version > /dev/null

CURRENT="$OUT/current-files"
PREVIOUS="$OUT/previous-files"
SHARED="$OUT/shared-files"
: > "$CURRENT"
while IFS= read -r -d '' f; do
  if [ -f "$f" ]; then
    printf '%s\n' "$f" >> "$CURRENT"
  elif ! git ls-files --deleted --error-unmatch -- "$f" > /dev/null 2>&1; then
    echo "ERROR: tracked Dawn corpus entry is unreadable: $f" >&2
    exit 1
  fi
done < <(git ls-files -z '*.dawn')
git ls-tree -r --name-only "$TAG" | sed -n '/\.dawn$/p' > "$PREVIOUS"
comm -12 "$CURRENT" "$PREVIOUS" > "$SHARED"
current_only=$(comm -23 "$CURRENT" "$PREVIOUS" | wc -l | tr -d ' ')
previous_only=$(comm -13 "$CURRENT" "$PREVIOUS" | wc -l | tr -d ' ')

i=0
while IFS= read -r f; do
  i=$((i + 1))
  cp "$f" "$OUT/k/$i.dawn"
  sed -e 's/^[[:space:]]*//' -e 's/   */ /g' "$f" > "$OUT/k/m$i.dawn"
  cp "$OUT/k/$i.dawn" "$OUT/d/$i.dawn"
  cp "$OUT/k/m$i.dawn" "$OUT/d/m$i.dawn"
done < "$SHARED"

# Both sides may legitimately refuse: scripts/grammar-corpus/reject/ is corpus
# that must not lex, and the differential domain is a path intersection, so a
# reject file enters it one release after it lands. Until v0.63.0 none ever
# had, and the assumption that `fmt` exits 0 went unnoticed -- under `set -e`
# the first refusal killed this script at the invocation below, before a single
# byte was compared. The gate was green because it had never met its own
# corpus, which is the one reason a green says nothing.
#
# Refusal is behavior, so it is part of what the two toolchains must agree on:
# same exit status, same diagnostics (modulo the tree each ran over), and the
# refused files left unchanged so the byte comparison below still means what it
# says.
k_status=0
"$DAWN" fmt "$OUT/k" > "$OUT/k.log" 2>&1 || k_status=$?
d_status=0
"$SELF" fmt "$OUT/d" > "$OUT/d.log" 2>&1 || d_status=$?

if [ "$k_status" -ne "$d_status" ]; then
  echo "FAIL: $TAG exited $k_status but $SELF exited $d_status over the same corpus" >&2
  echo "--- $TAG ---" >&2
  head -20 "$OUT/k.log" >&2
  echo "--- $SELF ---" >&2
  head -20 "$OUT/d.log" >&2
  exit 1
fi

sed "s|$OUT/k/|<corpus>/|g" "$OUT/k.log" > "$OUT/k.log.norm"
sed "s|$OUT/d/|<corpus>/|g" "$OUT/d.log" > "$OUT/d.log.norm"
if ! diff "$OUT/k.log.norm" "$OUT/d.log.norm" > "$OUT/log-diff.txt"; then
  echo "FAIL: $TAG and $SELF disagree on what they say about the corpus" >&2
  head -40 "$OUT/log-diff.txt" >&2
  exit 1
fi

. scripts/emitchange.sh
emitchange_load
if diff -r "$OUT/k" "$OUT/d" > "$OUT/diff.txt" 2>&1; then
  emit_gate "fmt" 0
else
  emit_gate "fmt" 1 || { head -40 "$OUT/diff.txt"; exit 1; }
fi
refused=$(grep -c '^error: ' "$OUT/k.log" || true)
echo "OK: $SELF agrees with $TAG over $i shared live files (plus mangled copies; \
both exited $k_status with the same $refused diagnostic(s); $current_only HEAD-only \
and $previous_only N-1-only path(s) reported outside the differential domain)"
