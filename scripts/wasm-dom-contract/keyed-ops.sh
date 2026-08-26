#!/usr/bin/env bash
# The three keyed ops at the bridge, and the mutants that say the assertions
# are looking.
#
#   ./scripts/wasm-dom-contract/keyed-ops.sh
#
# run.sh calls this before it builds anything, because nothing here needs a
# wasm toolchain: keyed-ops.mjs drives `DomHost` with hand-written patch lists
# against the recording document stub. It is here rather than in a gate of its
# own because it is about the same file the transcripts are about, and neither
# application in those transcripts keys its children -- so `insert`, `remove`
# and `move` reach the document by no other route.
#
# Each mutant edits a copy of packages/tea-dom/js/dom.mjs and must turn the
# assertions red. The edit is checked for having applied: a sed that matched
# nothing would report a clean tree as a killed mutant, which is how a mutant
# harness goes quietly blind.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/wasm-dom-contract"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if ! command -v node >/dev/null; then
  echo "MISSING: node is not on PATH (it is the bridge's runtime)." >&2
  exit 1
fi

fail=0

if node --no-warnings "$here/keyed-ops.mjs" >"$work/base.txt" 2>&1; then
  echo "OK   keyed ops: $(grep -c '^OK' "$work/base.txt") assertions"
else
  echo "FAIL: the keyed op assertions are red before any mutant was applied:" >&2
  cat "$work/base.txt" >&2
  exit 1
fi

# name | sed program over packages/tea-dom/js/dom.mjs
mutants=(
  # A move that rebuilds. The document ends up in the right order and every
  # element in it is new, which is the one failure this whole op exists to
  # prevent and the one no ordering assertion can see.
  'move-rebuilds|s|    const node = el.childNodes\[p.from\];|    const node = host.build({ t: "elem", tag: "li", props: [], on: [], kids: [] });|'
  # The off-by-one: a node travelling right has to skip over itself, because
  # the reference child is read before it leaves.
  'move-ref-off-by-one|s|p.to < p.from ? p.to : p.to + 1|p.to|'
  # A move that appends. Correct only when the destination is the end.
  'move-always-appends|s|const ref = p.to >= settled|const ref = p.to >= 0|'
  # An insert that ignores the position it was given.
  'insert-appends|s|el.childNodes\[p.at\] ?? null|null|'
  # A removal one place off. Nothing raises; the wrong row simply goes.
  'remove-off-by-one|s|el.removeChild(el.childNodes\[p.at\]);|el.removeChild(el.childNodes[p.at + 1]);|'
)

holes=0
killed=0
for m in "${mutants[@]}"; do
  name="${m%%|*}"
  prog="${m#*|}"
  rm -rf "$work/tree"
  mkdir -p "$work/tree/scripts"
  cp -r "$root/packages" "$work/tree/"
  cp -r "$here" "$work/tree/scripts/wasm-dom-contract"
  target="$work/tree/packages/tea-dom/js/dom.mjs"
  before="$(md5sum "$target")"
  sed -i "$prog" "$target"
  if [ "$before" = "$(md5sum "$target")" ]; then
    echo "NOT APPLIED: $name (the sed matched nothing; the mutant is vacuous)"
    holes=$((holes + 1))
    continue
  fi
  if node --no-warnings "$work/tree/scripts/wasm-dom-contract/keyed-ops.mjs" >/dev/null 2>&1; then
    echo "HOLE: $name survived, the assertions do not see it"
    holes=$((holes + 1))
  else
    echo "killed: $name"
    killed=$((killed + 1))
  fi
done

if [ "$holes" -ne 0 ]; then
  echo "FAIL: $holes of ${#mutants[@]} keyed-op mutant(s) unaccounted for" >&2
  fail=1
fi
if [ "$fail" != 0 ]; then exit 1; fi
echo "keyed ops ok ($killed/${#mutants[@]} mutants killed)"
