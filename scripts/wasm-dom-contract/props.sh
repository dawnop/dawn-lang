#!/usr/bin/env bash
# The attribute/property split at the bridge, and the mutants that say the
# assertions are looking.
#
#   ./scripts/wasm-dom-contract/props.sh
#
# run.sh calls this before it builds anything, because nothing here needs a
# wasm toolchain: props.mjs drives `DomHost.setSelf` with hand-written patch
# lists against a document stub that carries WHATWG's dirty value flag. It is
# here rather than in a gate of its own because it is about the same file the
# transcripts are about, and the failure it pins is invisible to them: a
# document whose `value` attribute is right and whose live value is stale
# serializes, patches and diffs exactly like a correct one.
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

if node --no-warnings "$here/props.mjs" >"$work/base.txt" 2>&1; then
  echo "OK   props: $(grep -c '^OK' "$work/base.txt") assertions"
else
  echo "FAIL: the prop assertions are red before any mutant was applied:" >&2
  cat "$work/base.txt" >&2
  exit 1
fi

# name | sed program over packages/tea-dom/js/dom.mjs
mutants=(
  # The bug this knife fixed, put back: every prop travels as an attribute.
  # The document object is indistinguishable from a correct one until the
  # user has typed, which is why the assertion that catches it is the one
  # that types first.
  'props-are-attributes|s|const PROPERTIES = new Set(\[.value., .checked.\]);|const PROPERTIES = new Set();|'
  # Half of it: the write is a property write and the reset is not, so a
  # field the model stopped describing keeps whatever was in it.
  'property-never-reset|s|      if (want.has(name) \|\| !(name in el)) continue;|      if (true) continue;|'
  # `checked` read as truthy rather than as an attribute's presence, so the
  # string "false" ticks the box.
  'checked-is-truthy|s|value !== .. \&\& value !== .false.|value !== ""|'
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
  if node --no-warnings "$work/tree/scripts/wasm-dom-contract/props.mjs" >/dev/null 2>&1; then
    echo "HOLE: $name survived, the assertions do not see it"
    holes=$((holes + 1))
  else
    echo "killed: $name"
    killed=$((killed + 1))
  fi
done

if [ "$holes" -ne 0 ]; then
  echo "FAIL: $holes of ${#mutants[@]} prop mutant(s) unaccounted for" >&2
  fail=1
fi
if [ "$fail" != 0 ]; then exit 1; fi
echo "props ok ($killed/${#mutants[@]} mutants killed)"
